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


def auto_cfg():
    """The config with automatic pulls switched on (90 and 30 minutes before tip).
    The shipped config pulls only when you press Run."""
    c = load_config()
    c["auto"]["board_offsets_min"] = [90, 30]
    return c


ACFG = auto_cfg()


class Scheduler(unittest.TestCase):
    def setUp(self):
        self.con = connect(os.path.join(tempfile.mkdtemp(), "a.db"))
        self.t0 = utcnow() + timedelta(hours=3)
        ev, od, ka = nba_fixture(self.t0)        # tips at t0+30, t0+60, t0+90
        self.api = FakeAPI(ev, od, ka)
        self.q = lambda *a, **k: None

    def run_at(self, minutes, cfg=ACFG):
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
        cfg = auto_cfg()
        cfg["auto"]["daily_credit_cap"] = 1
        r = self.run_at(-55, cfg)
        self.assertFalse(r["board_pull"])
        self.assertIn("daily cap", r["skipped"])
        self.assertFalse(self.run_at(-50)["board_pull"])          # marked done, not retried
        cfg = auto_cfg()
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
            automod.run_league(con, ACFG, "nba", "K", now=t0 - timedelta(minutes=55), fetch=api, log=lambda *a: None)
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
        automod.run_league(con, ACFG, "nba", "K", now=t0 - timedelta(minutes=55), fetch=api, log=lambda *a: None)
        b = boardmod.build(con, CFG, "nba", now=t0 - timedelta(minutes=50))
        boardmod.save_codes(con, b)
        betlog.log_bet(con, CFG, "nba", [[x for x in b["fliff"] if x["side"] == "over"][0]["code"]],
                       board_ts=b["built_at"])
        out = os.path.join(tempfile.mkdtemp(), "site")
        web.build_site(con, CFG, out, now=t0 - timedelta(minutes=50), status_line="test")
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
        self.assertIn('"et":"straight"', bets)
        self.assertIn("window.EF_REPO", bets)
        self.assertTrue(os.path.exists(os.path.join(out, "bets-data.json")))
        idx = _read(os.path.join(out, "index.html"))
        self.assertIn("1 open", idx)
        self.assertIn('class="runbtn"', idx)
        self.assertIn("Run NBA", idx)
        st = json.loads(_read(os.path.join(out, "status.json")))
        self.assertEqual(st["leagues"]["nba"]["games"], 3)
        self.assertEqual(st["leagues"]["nba"]["credits"], 3 * len(CFG.league("nba")["markets"]))
        self.assertIsNotNone(st["leagues"]["nba"]["last_run"])
        self.assertIsNone(st["leagues"]["nfl"]["last_run"])
        self.assertIn('id="save"', nba)


if __name__ == "__main__":
    unittest.main()


class Workflow(unittest.TestCase):
    def test_database_saved_after_site_build(self):
        """The board page writes the pick numbers bets are logged by, so the
        database must be saved after the site is built - not before."""
        with open(os.path.join(os.path.dirname(HERE), ".github", "workflows", "edge-finder.yml")) as f:
            wf = f.read()
        self.assertLess(wf.index("- name: Build the site"), wf.index("- name: Save database to the state branch"))
        self.assertLess(wf.index("- name: Save database to the state branch"), wf.index("- name: Package the site"))


class ManualRuns(unittest.TestCase):
    """Lines are pulled only when you press Run; the scheduled pass only
    notes what a Run would cost and takes closing snapshots for bets."""

    def setUp(self):
        self.con = connect(os.path.join(tempfile.mkdtemp(), "m.db"))
        self.t0 = utcnow() + timedelta(hours=3)
        ev, od, ka = nba_fixture(self.t0)
        self.api = FakeAPI(ev, od, ka)

    def test_scheduled_pass_never_pulls_boards(self):
        cfg = load_config()
        self.assertEqual(cfg["auto"]["board_offsets_min"], [])
        for m in (-95, -55, -25, 5):
            r = automod.run_league(self.con, cfg, "nba", "K", now=self.t0 + timedelta(minutes=m),
                                   fetch=self.api, log=lambda *a: None)
            self.assertFalse(r["board_pull"])
            self.assertEqual(r["credits"], 0)
        self.assertEqual(self.api.remaining, 500)
        self.assertFalse([u for u in self.api.calls if "/odds" in u])

    def test_status_and_estimate(self):
        cfg = load_config()
        r = automod.run_league(self.con, cfg, "nba", "K", now=self.t0 - timedelta(minutes=60), fetch=self.api, log=lambda *a: None)
        self.assertTrue(r["status_changed"])
        est = automod.run_estimate(self.con, cfg, "nba")
        self.assertEqual(est["games"], 3)
        self.assertEqual(est["credits"], 3 * len(cfg.league("nba")["markets"]))
        self.assertIsNone(est["last_run"])
        self.assertEqual(automod.credits_left(self.con), 500)
        r = automod.run_league(self.con, cfg, "nba", "K", now=self.t0 - timedelta(minutes=45), fetch=self.api, log=lambda *a: None)
        self.assertFalse(r["status_changed"])                    # same games: no republish needed
        r = automod.run_league(self.con, cfg, "nba", "K", now=self.t0 + timedelta(minutes=35), fetch=self.api, log=lambda *a: None)
        self.assertTrue(r["status_changed"])                     # first game started
        self.assertEqual(automod.run_estimate(self.con, cfg, "nba")["games"], 2)

    def test_closing_snapshots_can_be_switched_off(self):
        automod.run_league(self.con, ACFG, "nba", "K", now=self.t0 - timedelta(minutes=55), fetch=self.api, log=lambda *a: None)
        b = boardmod.build(self.con, CFG, "nba", now=self.t0 - timedelta(minutes=50))
        boardmod.save_codes(self.con, b)
        betlog.log_bet(self.con, CFG, "nba", [[x for x in b["fliff"] if x["side"] == "over"][0]["code"]], board_ts=b["built_at"])
        cfg = load_config()
        cfg["auto"]["closing_snapshots"] = False
        r = automod.run_league(self.con, cfg, "nba", "K", now=self.t0 + timedelta(minutes=10), fetch=self.api, log=lambda *a: None)
        self.assertEqual(r["close_pulls"], 0)
        r = automod.run_league(self.con, load_config(), "nba", "K", now=self.t0 + timedelta(minutes=12), fetch=self.api, log=lambda *a: None)
        self.assertEqual(r["close_pulls"], 1)

    def test_run_command(self):
        import edgefinder
        self.assertIn("run", web.ALLOWED)
        self.assertEqual(web.parse_issue("run nba", "```\nrun nba\n```"), ["run", "nba"])
        seen = []

        def fake_pull(con, cfg, league, key, hours=None, yes=False, aliases=None, **k):
            seen.append((league, hours, yes))
            print("No upcoming %s games in the next %d hours." % (league.upper(), hours))
            return None, {"events": 0, "lines": 0}

        real = edgefinder.pull_odds, edgefinder.odds_api_key
        edgefinder.pull_odds, edgefinder.odds_api_key = fake_pull, lambda: "K"
        os.environ["EDGEFINDER_DB"] = os.path.join(tempfile.mkdtemp(), "r.db")
        try:
            ok, text = edgefinder.handle_command(["run", "nfl"], 5)
        finally:
            edgefinder.pull_odds, edgefinder.odds_api_key = real
            del os.environ["EDGEFINDER_DB"]
        self.assertEqual(seen, [("nfl", 16, True)])
        self.assertFalse(ok)                                    # nothing pulled: the app stops waiting
        self.assertIn("No upcoming NFL games", text)
        self.assertIn("didn't go through", web.comment_for(["run", "nfl"], ok, text))

    def test_out_of_credits_stops_before_spending(self):
        from ef.sources import pull_odds
        self.api.remaining = 2
        with self.assertRaises(SystemExit) as e:
            pull_odds(self.con, CFG, "nba", "K", fetch=self.api, hours=16, yes=True, log=lambda *a: None)
        self.assertIn("Out of Odds API credits", str(e.exception))

    def test_ge_due_follows_run_nfl(self):
        import edgefinder

        class R:
            def __init__(self, out):
                self.returncode, self.stdout, self.stderr = 0, out, ""

        for titles, want in ((["run nba"], "false"), (["bet nfl 3"], "false"), (["run nfl"], "true"), (["Run NFL"], "true")):
            out = os.path.join(tempfile.mkdtemp(), "out")
            os.environ["GITHUB_OUTPUT"] = out
            real = edgefinder._gh
            edgefinder._gh = lambda *a, stdin=None, t=titles: R(json.dumps([{"title": x} for x in t]))
            try:
                edgefinder.cmd_ge_due(CFG, self.con, None)
            finally:
                edgefinder._gh = real
                del os.environ["GITHUB_OUTPUT"]
            self.assertIn("ge_due=%s" % want, _read(out), titles)


class Closeness(unittest.TestCase):
    def leg(self, side, pt, act, lr, market="player_assists", fair=0.55, price=None):
        return {"side": side, "point": pt, "actual": act, "leg_result": lr, "market": market, "fair_p": fair, "price": price}

    def test_hooks_and_margins(self):
        c = web.closeness(self.leg("over", 5.5, 5, "miss"))
        self.assertEqual((c["need"], c["mg"], c["hook"]), (6, -0.5, True))
        self.assertGreater(c["sd"], 0)
        self.assertAlmostEqual(c["ez"], 0.126, places=2)          # a 55% leg should land ~0.13 SD on your side
        self.assertFalse(web.closeness(self.leg("over", 5.5, 4, "miss"))["hook"])
        c = web.closeness(self.leg("under", 24.5, 25, "miss", "player_points"))
        self.assertEqual((c["need"], c["mg"], c["hook"]), (24, -0.5, True))
        self.assertFalse(web.closeness(self.leg("under", 24.5, 27, "miss", "player_points"))["hook"])
        self.assertTrue(web.closeness(self.leg("over", 64.5, 64, "miss", "player_reception_yds"))["hook"])
        c = web.closeness(self.leg("over", 5, 5, "push"))            # whole-number line
        self.assertEqual((c["need"], c["mg"], c["hook"]), (6, 0, False))
        c = web.closeness(self.leg("over", 9.5, 11, "hit", "player_points"))
        self.assertEqual((c["mg"], c["hook"]), (1.5, False))
        self.assertNotIn("mg", web.closeness(self.leg("over", 9.5, None, None)))

    def test_one_hook_from(self):
        b = {"book": "prizepicks", "entry_type": "pp4", "stake": 2.0, "contracts": None}
        legs = [self.leg("over", 5.5, 7, "hit")] * 3 + [self.leg("over", 5.5, 5, "miss")]
        self.assertEqual(web.payout_if_hit(CFG, b, legs), 20.0)
        self.assertIsNone(web.payout_if_hit(CFG, b, legs[:2] + [self.leg("over", 5.5, 5, "miss")] * 2))
        k = {"book": "kalshi", "entry_type": "kalshi", "stake": 2.0, "contracts": 7}
        self.assertEqual(web.payout_if_hit(CFG, k, [self.leg("over", 5.5, 5, "miss")]), 7)
        f = {"book": "fliff", "entry_type": "straight", "stake": 2.0, "contracts": None}
        self.assertEqual(web.payout_if_hit(CFG, f, [self.leg("over", 5.5, 5, "miss", price=2.1)]), 4.2)


class DeleteBets(unittest.TestCase):
    def test_delete_and_restore(self):
        tmp = tempfile.mkdtemp()
        os.environ["EDGEFINDER_DB"] = os.path.join(tmp, "d.db")
        try:
            import edgefinder
            con = connect()
            t0 = utcnow() + timedelta(hours=3)
            ev, od, ka = nba_fixture(t0)
            api = FakeAPI(ev, od, ka)
            automod.run_league(con, ACFG, "nba", "K", now=t0 - timedelta(minutes=55), fetch=api, log=lambda *a: None)
            b = boardmod.build(con, CFG, "nba", now=t0 - timedelta(minutes=50))
            boardmod.save_codes(con, b)
            code = [x for x in b["fliff"] if x["side"] == "over"][0]["code"]
            ids = [betlog.log_bet(con, CFG, "nba", [code], board_ts=b["built_at"])[0] for _ in range(2)]

            self.assertIn("delete", web.ALLOWED)
            self.assertIn("restore", web.ALLOWED)
            self.assertEqual(web.parse_issue("delete 2", "```\ndelete 2\n```"), ["delete", "2"])
            ok, text = edgefinder.handle_command(["delete", str(ids[1])], 20)
            self.assertTrue(ok, text)
            self.assertIn("Deleted bet #%d" % ids[1], text)
            ok, text = edgefinder.handle_command(["delete", "99"], 21)
            self.assertFalse(ok)

            con = connect()
            data = web.results_payload(con, CFG, "x/y", utcnow())
            self.assertEqual([x["id"] for x in data["bets"]], [ids[0]])
            self.assertEqual([x["id"] for x in data["deleted"]], [ids[1]])
            # a deleted bet costs nothing: no closing snapshot for it
            legs = betlog.legs_needing_close(con, "nba", t0 + timedelta(minutes=10), 30)
            self.assertEqual({l["bet_id"] for l in legs}, {ids[0]})
            self.assertNotIn("#%d " % ids[1], betlog.list_bets(con))

            ok, text = edgefinder.handle_command(["restore", str(ids[1])], 22)
            self.assertTrue(ok, text)
            con = connect()
            data = web.results_payload(con, CFG, "x/y", utcnow())
            self.assertEqual(sorted(x["id"] for x in data["bets"]), ids)
            self.assertEqual(data["deleted"], [])
        finally:
            del os.environ["EDGEFINDER_DB"]


class KalshiStake(unittest.TestCase):
    def test_shares_match_kalshi_fills(self):
        """Kalshi's order history: $2 at 46c -> 4.18 shares at 47.7c; 54c -> 3.58; 28c -> 6.80."""
        from ef.fair import kalshi_shares
        self.assertEqual(kalshi_shares(2, 0.46), 4.18)
        self.assertEqual(kalshi_shares(2, 0.54), 3.58)
        self.assertEqual(kalshi_shares(2, 0.28), 6.80)
        self.assertEqual(kalshi_shares(2, 0.34), 5.62)

    def test_edit(self):
        con = connect(os.path.join(tempfile.mkdtemp(), "e.db"))
        t0 = utcnow() + timedelta(hours=3)
        ev, od, ka = nba_fixture(t0)
        automod.run_league(con, ACFG, "nba", "K", now=t0 - timedelta(minutes=55), fetch=FakeAPI(ev, od, ka), log=lambda *a: None)
        b = boardmod.build(con, CFG, "nba", now=t0 - timedelta(minutes=50))
        boardmod.save_codes(con, b)
        k = b["kalshi"][0]
        bid = betlog.log_bet(con, CFG, "nba", [k["code"]], stake=2, board_ts=b["built_at"])[0]
        row = con.execute("SELECT * FROM bets WHERE id=?", (bid,)).fetchone()
        self.assertEqual(row["stake"], 2.0)                       # the stake is what you spend
        from ef.fair import kalshi_shares
        self.assertEqual(row["contracts"], kalshi_shares(2, k["ask"]))
        bid2 = betlog.log_bet(con, CFG, "nba", [k["code"]], stake=2, contracts=4.18, board_ts=b["built_at"])[0]
        self.assertEqual(tuple(con.execute("SELECT stake, contracts FROM bets WHERE id=?", (bid2,)).fetchone()), (2.0, 4.18))

        msg = betlog.edit_bet(con, CFG, bid2, stake=2.59, contracts=6.36)
        self.assertIn("$2.59 for 6.36 shares", msg)
        self.assertAlmostEqual(con.execute("SELECT price FROM bet_legs WHERE bet_id=?", (bid2,)).fetchone()["price"], 2.59 / 6.36)
        betlog.set_result(con, CFG, bid2, "win")
        self.assertAlmostEqual(con.execute("SELECT payout FROM bets WHERE id=?", (bid2,)).fetchone()["payout"], 6.36)
        betlog.edit_bet(con, CFG, bid2, stake=2, contracts=4.18)
        self.assertAlmostEqual(con.execute("SELECT payout FROM bets WHERE id=?", (bid2,)).fetchone()["payout"], 4.18)
        with self.assertRaises(SystemExit):
            betlog.edit_bet(con, CFG, bid2, stake=5, contracts=4)          # $1.25 a share can't be right

        fl = [x for x in b["fliff"] if x["side"] == "over"][0]
        fid = betlog.log_bet(con, CFG, "nba", [fl["code"]], stake=3, board_ts=b["built_at"])[0]
        betlog.set_result(con, CFG, fid, "win")
        betlog.edit_bet(con, CFG, fid, stake=2)
        r = con.execute("SELECT stake, payout FROM bets WHERE id=?", (fid,)).fetchone()
        self.assertEqual(r["stake"], 2.0)
        self.assertAlmostEqual(r["payout"], 2 * 2.10)
        self.assertIn("edit", web.ALLOWED)

    def test_issue_with_several_commands(self):
        body = "Matching Kalshi's order history:\n```\nedit 1 --stake 2 --contracts 3.58\nedit 3 --stake 2 --contracts 4.18\n```"
        self.assertEqual(web.parse_commands("edit Kalshi bets", body),
                         [["edit", "1", "--stake", "2", "--contracts", "3.58"], ["edit", "3", "--stake", "2", "--contracts", "4.18"]])
        self.assertEqual(web.parse_commands("result 7 win", ""), [["result", "7", "win"]])
        app = "```\nbet nba 4 --stake 2 --board 2026-10-25T10:00:00Z\n```\nSaved from the Edge Finder app."
        self.assertEqual(len(web.parse_commands("bet nba #4 $2", app)), 1)
