"""Automatic grading from ESPN box scores (shapes copied from real responses)."""
import json
import os
import sys
import tempfile
import unittest
from datetime import timedelta
from urllib.parse import parse_qs, urlparse

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.dirname(HERE))
sys.path.insert(0, HERE)

from test_edgefinder import CFG, FakeAPI, nba_fixture  # noqa: E402

from ef import bets as betlog  # noqa: E402
from ef import board as boardmod  # noqa: E402
from ef import grade  # noqa: E402
from ef.db import connect  # noqa: E402
from ef.sources import pull_kalshi, pull_odds  # noqa: E402
from ef.util import local, utcnow  # noqa: E402

NBA_KEYS = ["minutes", "points", "fieldGoalsMade-fieldGoalsAttempted",
            "threePointFieldGoalsMade-threePointFieldGoalsAttempted", "freeThrowsMade-freeThrowsAttempted",
            "rebounds", "assists", "turnovers", "steals", "blocks", "offensiveRebounds", "defensiveRebounds",
            "fouls", "plusMinus"]


def nba_line(name, pts, reb, ast, threes):
    return {"athlete": {"displayName": name}, "starter": True, "didNotPlay": False,
            "stats": ["34", str(pts), "8-15", "%d-6" % threes, "2-2", str(reb), str(ast), "1", "0", "0", "1",
                      str(reb - 1), "2", "+4"]}


def nba_summary(players, dnp=(), final=True):
    athletes = [nba_line(*p) for p in players]
    athletes += [{"athlete": {"displayName": n}, "didNotPlay": True, "reason": "COACH'S DECISION", "stats": []} for n in dnp]
    return {"header": {"competitions": [{"status": {"type": {"state": "post" if final else "in", "completed": final}}}]},
            "boxscore": {"players": [{"team": {"displayName": "X"}, "statistics": [{"keys": NBA_KEYS, "athletes": athletes}]}]}}


class Parse(unittest.TestCase):
    def test_nba(self):
        final, stats, dnp = grade.parse_box(nba_summary([("OG Anunoby", 20, 10, 8, 2)], dnp=["Mohamed Diawara"]))
        self.assertTrue(final)
        self.assertEqual(stats["og anunoby"]["points"], 20)
        self.assertEqual(stats["og anunoby"]["threes"], 2)
        self.assertEqual(grade.leg_value("player_points_rebounds_assists", stats["og anunoby"]), 38)
        self.assertIn("mohamed diawara", dnp)

    def test_nfl(self):
        summ = {"header": {"competitions": [{"status": {"type": {"state": "post", "completed": True}}}]},
                "boxscore": {"players": [{"statistics": [
                    {"name": "passing", "keys": ["completions/passingAttempts", "passingYards", "yardsPerPassAttempt"],
                     "athletes": [{"athlete": {"displayName": "Drake Maye"}, "stats": ["24/31", "321", "10.4"]}]},
                    {"name": "rushing", "keys": ["rushingAttempts", "rushingYards"],
                     "athletes": [{"athlete": {"displayName": "Drake Maye"}, "stats": ["4", "26"]}]},
                    {"name": "receiving", "keys": ["receptions", "receivingYards", "yardsPerReception"],
                     "athletes": [{"athlete": {"displayName": "Rhamondre Stevenson"}, "stats": ["5", "93", "18.6"]}]},
                ]}]}}
        final, stats, dnp = grade.parse_box(summ)
        m = stats["drake maye"]
        self.assertEqual((m["completions"], m["passingAttempts"], m["passingYards"]), (24, 31, 321))
        self.assertEqual(grade.leg_value("player_pass_rush_yds", m), 347)
        self.assertEqual(grade.leg_value("player_reception_yds", m), 0)        # no catches = zero
        self.assertEqual(grade.leg_value("player_rush_reception_yds", stats["rhamondre stevenson"]), 93)

    def test_results_and_names(self):
        self.assertEqual(grade.leg_result(27, 24.5, "over"), "hit")
        self.assertEqual(grade.leg_result(27, 24.5, "under"), "miss")
        self.assertEqual(grade.leg_result(25, 25, "over"), "push")
        stats = {"herbert jones": {}, "jalen williams": {}, "jaylin williams": {}}
        self.assertEqual(grade.find_player("herb jones", stats, set()), "herbert jones")
        self.assertIsNone(grade.find_player("j williams", stats, set()))     # ambiguous -> review


class FakeESPN:
    def __init__(self, games):
        self.games = games          # {espn_id: (day, home, away, summary)}

    def __call__(self, url):
        u = urlparse(url)
        q = parse_qs(u.query)
        if u.path.endswith("/scoreboard"):
            day = q["dates"][0]
            evs = [{"id": gid, "competitions": [{"competitors": [
                {"homeAway": "home", "team": {"displayName": h, "name": h.split()[-1]}},
                {"homeAway": "away", "team": {"displayName": a, "name": a.split()[-1]}}]}]}
                for gid, (d, h, a, _) in self.games.items() if d == day]
            return 200, {}, json.dumps({"events": evs}).encode()
        if u.path.endswith("/summary"):
            g = self.games.get(q["event"][0])
            return (200, {}, json.dumps(g[3]).encode()) if g else (404, {}, b"")
        return 404, {}, b""


class Settle(unittest.TestCase):
    def test_end_to_end(self):
        con = connect(os.path.join(tempfile.mkdtemp(), "g.db"))
        t0 = utcnow() + timedelta(hours=2)
        ev, od, ka = nba_fixture(t0)
        api = FakeAPI(ev, od, ka)
        pid, _ = pull_odds(con, CFG, "nba", "K", fetch=api, yes=True, log=lambda *a: None)
        pull_kalshi(con, CFG, "nba", pid, fetch=api, log=lambda *a: None)
        b = boardmod.build(con, CFG, "nba", pull_id=pid)
        boardmod.save_codes(con, b)
        pick = lambda book, pk, side: [x for x in b[{"underdog": "pickem", "prizepicks": "pickem", "fliff": "fliff",
                                                     "kalshi": "kalshi"}[book]]
                                       if x["book"] == book and x["player_key"] == pk and x["side"] == side][0]
        fl = pick("fliff", "alpha one", "over")                     # Over 24.5 pts
        fl_under = pick("fliff", "alpha one", "under")
        ud = [pick("underdog", "alpha one", "over"), pick("underdog", "beta two", "under"), pick("underdog", "gamma three", "over")]
        k = [x for x in b["kalshi"] if x["point"] == 23.5 and x["side"] == "over"][0]
        ts = b["built_at"]
        win = betlog.log_bet(con, CFG, "nba", [fl["code"]], stake=2, board_ts=ts)[0]
        lose = betlog.log_bet(con, CFG, "nba", [fl_under["code"]], stake=1, board_ts=ts)[0]
        entry = betlog.log_bet(con, CFG, "nba", [x["code"] for x in ud], entry="ud3", stake=1, board_ts=ts)[0]
        kal = betlog.log_bet(con, CFG, "nba", [k["code"]], contracts=10, board_ts=ts)[0]
        leg = con.execute("SELECT flagged, edge FROM bet_legs WHERE bet_id=?", (win,)).fetchone()
        self.assertEqual(leg["flagged"], 1)
        self.assertAlmostEqual(leg["edge"], fl["ev"])

        day = lambda m: local(t0 + timedelta(minutes=m)).strftime("%Y%m%d")
        games = {
            "g1": (day(30), "Atlanta Hawks", "Houston Rockets", nba_summary([("Alpha One", 27, 5, 4, 3)])),
            "g2": (day(60), "Charlotte Hornets", "Miami Heat", nba_summary([("Beta Two Jr.", 12, 7, 2, 1)])),
            "g3": (day(90), "Phoenix Suns", "Golden State Warriors", nba_summary([("Gamma Three", 15, 3, 5, 1)])),
        }
        espn = FakeESPN(games)
        # Too early: nothing graded.
        self.assertEqual(grade.grade_open_bets(con, CFG, now=t0 + timedelta(hours=1), fetch=espn, log=lambda *a: None), 0)
        n = grade.grade_open_bets(con, CFG, now=t0 + timedelta(hours=6), fetch=espn, log=lambda *a: None)
        self.assertEqual(n, 4)
        r = {row["id"]: row for row in con.execute("SELECT * FROM bets")}
        self.assertEqual((r[win]["result"], r[win]["payout"], r[win]["graded_by"]), ("win", 4.2, "auto"))
        self.assertEqual((r[lose]["result"], r[lose]["payout"]), ("loss", 0.0))
        # Alpha 27 > 23.5 hit, Beta 7 < 9.5 under hit, Gamma 5 < 6.5 over miss -> 2 of 3 on a 3-pick standard = loss
        self.assertEqual((r[entry]["result"], r[entry]["payout"]), ("loss", 0.0))
        self.assertEqual((r[kal]["result"], r[kal]["payout"]), ("win", 10.0))
        legs = {row["player_key"]: row for row in con.execute("SELECT * FROM bet_legs WHERE bet_id=?", (entry,))}
        self.assertEqual((legs["gamma three"]["actual"], legs["gamma three"]["leg_result"]), (5, "miss"))
        self.assertEqual(legs["beta two"]["leg_result"], "hit")      # "Beta Two Jr." matched

    def test_void_and_review(self):
        con = connect(os.path.join(tempfile.mkdtemp(), "v.db"))
        t0 = utcnow() + timedelta(hours=2)
        ev, od, ka = nba_fixture(t0)
        pid, _ = pull_odds(con, CFG, "nba", "K", fetch=FakeAPI(ev, od, ka), yes=True, log=lambda *a: None)
        b = boardmod.build(con, CFG, "nba", pull_id=pid)
        boardmod.save_codes(con, b)
        fl = [x for x in b["fliff"] if x["side"] == "over"][0]
        a = betlog.log_bet(con, CFG, "nba", [fl["code"]], stake=1, board_ts=b["built_at"])[0]
        c = betlog.log_bet(con, CFG, "nba", [fl["code"]], stake=1, board_ts=b["built_at"])[0]
        day = local(t0 + timedelta(minutes=30)).strftime("%Y%m%d")
        dnp = FakeESPN({"g1": (day, "Atlanta Hawks", "Houston Rockets", nba_summary([("Someone", 1, 1, 1, 0)], dnp=["Alpha One"]))})
        grade.grade_open_bets(con, CFG, now=t0 + timedelta(hours=6), fetch=dnp, log=lambda *a: None)
        self.assertEqual(con.execute("SELECT result, payout FROM bets WHERE id=?", (a,)).fetchone()["result"], "push")
        # Settle c by hand first: grading must never overwrite it.
        betlog.set_result(con, CFG, c, "loss")
        self.assertEqual(con.execute("SELECT result FROM bets WHERE id=?", (c,)).fetchone()["result"], "loss")
        con2 = connect(os.path.join(tempfile.mkdtemp(), "w.db"))
        pid, _ = pull_odds(con2, CFG, "nba", "K", fetch=FakeAPI(ev, od, ka), yes=True, log=lambda *a: None)
        b2 = boardmod.build(con2, CFG, "nba", pull_id=pid)
        boardmod.save_codes(con2, b2)
        fl2 = [x for x in b2["fliff"] if x["side"] == "over"][0]
        d = betlog.log_bet(con2, CFG, "nba", [fl2["code"]], stake=1, board_ts=b2["built_at"])[0]
        missing = FakeESPN({"g1": (day, "Atlanta Hawks", "Houston Rockets", nba_summary([("Someone Else", 1, 1, 1, 0)]))})
        grade.grade_open_bets(con2, CFG, now=t0 + timedelta(hours=6), fetch=missing, log=lambda *a: None)
        self.assertIsNone(con2.execute("SELECT result FROM bets WHERE id=?", (d,)).fetchone()["result"])
        self.assertEqual(con2.execute("SELECT leg_result FROM bet_legs WHERE bet_id=?", (d,)).fetchone()["leg_result"], "review")


if __name__ == "__main__":
    unittest.main()
