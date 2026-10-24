"""The unattended pieces: scheduler, issue commands, the Pages site, pruning."""
import json
import os
import sys
import tempfile
import unittest
from datetime import timedelta

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.dirname(HERE))
sys.path.insert(0, HERE)

from test_edgefinder import CFG, FakeAPI, nba_fixture  # noqa: E402

from ef import auto as automod  # noqa: E402
from ef import bets as betlog  # noqa: E402
from ef import board as boardmod  # noqa: E402
from ef import web  # noqa: E402
from ef.config import load_config  # noqa: E402
from ef.db import connect  # noqa: E402
from ef.util import utcnow  # noqa: E402


class Scheduler(unittest.TestCase):
    def setUp(self):
        self.con = connect(os.path.join(tempfile.mkdtemp(), "a.db"))
        self.t0 = utcnow() + timedelta(hours=3)
        ev, od, ka = nba_fixture(self.t0)        # tips at t0+30, t0+60, t0+90
        self.api = FakeAPI(ev, od, ka)
        self.q = lambda *a, **k: None

    def run_at(self, minutes, cfg=CFG):
        return automod.run_league(self.con, cfg, "nba", "K", now=self.t0 + timedelta(minutes=minutes),
                                  fetch=self.api, log=self.q)

    def pulls(self, kind="board"):
        return self.con.execute("SELECT * FROM pulls WHERE kind=? ORDER BY id", (kind,)).fetchall()

    def test_slots(self):
        self.assertFalse(self.run_at(-70)["board_pull"])          # nothing 90 min out yet
        r = self.run_at(-55)                                      # ev1 is 85 min out
        self.assertTrue(r["board_pull"])
        evs = {x["event_id"] for x in self.con.execute("SELECT DISTINCT event_id FROM lines WHERE pull_id=?",
                                                         (self.pulls()[-1]["id"],)) if x["event_id"]}
        self.assertEqual(evs, {"ev1"})
        self.assertFalse(self.run_at(-50)["board_pull"])          # same slot never paid twice
        r = self.run_at(5)        # ev1's 30-min slot, ev2 and ev3's 90-min slots, all in one pull
        self.assertTrue(r["board_pull"])
        evs = {x["event_id"] for x in self.con.execute("SELECT DISTINCT event_id FROM lines WHERE pull_id=?",
                                                         (self.pulls()[-1]["id"],)) if x["event_id"]}
        self.assertEqual(evs, {"ev1", "ev2", "ev3"})
        self.assertEqual(len(self.pulls()), 2)

        # The merged board holds every game from its own latest pull, plus Kalshi.
        b = boardmod.build(self.con, CFG, "nba", now=self.t0 + timedelta(minutes=6))
        self.assertEqual({x["event_id"] for x in b["pickem"]}, {"ev1", "ev2", "ev3"})
        self.assertTrue(b["kalshi"])
        b2 = boardmod.build(self.con, CFG, "nba", now=self.t0 + timedelta(minutes=45))
        self.assertNotIn("ev1", {x["event_id"] for x in b2["pickem"]})

    def test_caps(self):
        cfg = load_config()
        cfg["auto"]["daily_credit_cap"] = 1
        r = self.run_at(-55, cfg)
        self.assertFalse(r["board_pull"])
        self.assertIn("daily cap", r["skipped"])
        self.assertFalse(self.run_at(-50)["board_pull"])          # marked done, not retried
        cfg = load_config()
        cfg["auto"]["credit_floor"] = 10000
        self.api.remaining = 50
        r = automod.run_league(self.con, cfg, "nba", "K", now=self.t0 + timedelta(minutes=5), fetch=self.api, log=self.q)
        self.assertIn("credits left", r["skipped"])

    def test_closing_snapshot_once(self):
        self.run_at(-55)
        b = boardmod.build(self.con, CFG, "nba", now=self.t0 - timedelta(minutes=50))
        boardmod.save_codes(self.con, b)
        fl = [x for x in b["fliff"] if x["side"] == "over"][0]
        betlog.log_bet(self.con, CFG, "nba", [fl["code"]], board_ts=b["built_at"])
        r = self.run_at(10)       # ev1 tips in 20 min -> snapshot
        self.assertEqual(r["close_pulls"], 1)
        close = self.pulls("close")
        self.assertEqual(len(close), 1)
        mk = {x["market"] for x in self.con.execute("SELECT DISTINCT market FROM lines WHERE pull_id=?", (close[0]["id"],))}
        self.assertEqual(mk, {"player_points"})                   # only what was bet
        self.assertEqual(self.run_at(15)["close_pulls"], 0)
        r = self.run_at(31)
        self.assertEqual(r["closed_legs"], 1)

    def test_prune_keeps_bet_history(self):
        self.run_at(-55)
        b = boardmod.build(self.con, CFG, "nba", now=self.t0 - timedelta(minutes=50))
        boardmod.save_codes(self.con, b)
        fl = [x for x in b["fliff"] if x["side"] == "over"][0]
        betlog.log_bet(self.con, CFG, "nba", [fl["code"]], board_ts=b["built_at"])
        automod.prune(self.con, keep_days=3, now=utcnow() + timedelta(days=5))
        left = self.con.execute("SELECT DISTINCT player_key, market FROM lines").fetchall()
        self.assertEqual({(r["player_key"], r["market"]) for r in left}, {("alpha one", "player_points")})


class Issues(unittest.TestCase):
    def test_parse(self):
        body = "```\nbet nba 4 9 12 --entry ud3 --stake 2 --board 2026-10-24T23:05:00Z\n```\nSubmit this issue..."
        self.assertEqual(web.parse_issue("bet nba #4 #9 #12 ud3 $2", body),
                         ["bet", "nba", "4", "9", "12", "--entry", "ud3", "--stake", "2", "--board", "2026-10-24T23:05:00Z"])
        self.assertEqual(web.parse_issue("result 7 win", ""), ["result", "7", "win"])
        self.assertEqual(web.parse_issue("x", "python3 edgefinder.py refresh nfl"), ["refresh", "nfl"])
        self.assertIsNone(web.parse_issue("rm -rf /", "clv; echo hi"))
        self.assertIsNone(web.parse_issue("hello", "nothing here"))

    def test_sweep(self):
        """Open command issues run oldest first, get a reply, and get closed;
        ordinary issues and other people's are left alone."""
        tmp = tempfile.mkdtemp()
        os.environ["EDGEFINDER_DB"] = os.path.join(tmp, "s.db")
        try:
            import edgefinder
            con = connect()
            t0 = utcnow() + timedelta(hours=3)
            ev, od, ka = nba_fixture(t0)
            api = FakeAPI(ev, od, ka)
            automod.run_league(con, CFG, "nba", "K", now=t0 - timedelta(minutes=55), fetch=api, log=lambda *a: None)
            b = boardmod.build(con, CFG, "nba", now=t0 - timedelta(minutes=50))
            boardmod.save_codes(con, b)
            fl = [x for x in b["fliff"] if x["side"] == "over"][0]
            issues = [
                {"number": 12, "title": "result 1 win", "body": "", "author": {"login": "ApolloJosh"}},
                {"number": 11, "title": "bet nba #%s $3" % fl["code"],
                 "body": "```\nbet nba %s --stake 3 --board %s\n```" % (fl["code"], b["built_at"]),
                 "author": {"login": "ApolloJosh"}},
                {"number": 13, "title": "Bug: board slow", "body": "", "author": {"login": "ApolloJosh"}},
                {"number": 14, "title": "bet nba 1", "body": "", "author": {"login": "someone"}},
            ]
            calls = []

            class R:
                def __init__(self, out=""):
                    self.returncode, self.stdout, self.stderr = 0, out, ""

            def fake_gh(*args, stdin=None):
                calls.append((args, stdin))
                return R(json.dumps(issues)) if args[:2] == ("issue", "list") else R()

            real = edgefinder._gh
            edgefinder._gh = fake_gh
            try:
                edgefinder.cmd_sweep_issues(CFG, con, None)
            finally:
                edgefinder._gh = real
            comments = [(a[2], s) for a, s in calls if a[:2] == ("issue", "comment")]
            closed = [a[2] for a, s in calls if a[:2] == ("issue", "close")]
            self.assertEqual([c[0] for c in comments], ["11", "12"])   # oldest first, only commands by owner
            self.assertEqual(closed, ["11", "12"])
            self.assertIn("Done.", comments[0][1])
            self.assertIn("Logged bet #1", comments[0][1])
            self.assertIn("Done.", comments[1][1])
            con2 = connect()
            bet = con2.execute("SELECT * FROM bets WHERE id=1").fetchone()
            self.assertEqual((bet["stake"], bet["result"]), (3.0, "win"))
            self.assertAlmostEqual(bet["payout"], 3 * 2.10)
        finally:
            del os.environ["EDGEFINDER_DB"]


def _read(path):
    with open(path) as f:
        return f.read()


class Site(unittest.TestCase):
    def test_build(self):
        con = connect(os.path.join(tempfile.mkdtemp(), "w.db"))
        t0 = utcnow() + timedelta(hours=3)
        ev, od, ka = nba_fixture(t0)
        api = FakeAPI(ev, od, ka)
        automod.run_league(con, CFG, "nba", "K", now=t0 - timedelta(minutes=55), fetch=api, log=lambda *a: None)
        b = boardmod.build(con, CFG, "nba", now=t0 - timedelta(minutes=50))
        boardmod.save_codes(con, b)
        betlog.log_bet(con, CFG, "nba", [[x for x in b["fliff"] if x["side"] == "over"][0]["code"]],
                       board_ts=b["built_at"])
        out = os.path.join(tempfile.mkdtemp(), "site")
        web.build_site(con, CFG, out, now=t0 - timedelta(minutes=50), status="test")
        names = sorted(os.listdir(out))
        for n in (".nojekyll", "bets.html", "index.html", "nba.html", "nfl.html", "manifest.webmanifest",
                  "apple-touch-icon.png", "icon-192.png", "icon-512.png"):
            self.assertIn(n, names)
        nba = _read(os.path.join(out, "nba.html"))
        self.assertIn('id="log"', nba)
        self.assertIn('"ApolloJosh/Edge-Finder"', nba)
        self.assertIn('"t":"', nba)
        self.assertIn('rel="manifest"', nba)
        nfl = _read(os.path.join(out, "nfl.html"))
        self.assertIn("No NFL lines pulled yet", nfl)
        bets = _read(os.path.join(out, "bets.html"))
        self.assertIn("issues/new?title=result%201%20win", bets)
        idx = _read(os.path.join(out, "index.html"))
        self.assertIn("1 open", idx)
        self.assertIn("refresh%20nba", idx)


if __name__ == "__main__":
    unittest.main()
