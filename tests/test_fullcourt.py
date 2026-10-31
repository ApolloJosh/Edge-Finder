"""Full Court Edge: box-score sync, the projection, and its place on the board."""
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
from test_github import ACFG  # noqa: E402

from ef import auto as automod  # noqa: E402
from ef import board as boardmod  # noqa: E402
from ef import fullcourt  # noqa: E402
from ef.db import connect  # noqa: E402
from ef.util import local, utcnow  # noqa: E402

KEYS = ["minutes", "points", "fieldGoalsMade-fieldGoalsAttempted",
        "threePointFieldGoalsMade-threePointFieldGoalsAttempted", "freeThrowsMade-freeThrowsAttempted",
        "rebounds", "assists", "turnovers", "steals", "blocks"]
TEAMS = {"HOU": "Houston Rockets", "ATL": "Atlanta Hawks", "MIA": "Miami Heat", "CHA": "Charlotte Hornets"}


def line(name, mins, pts, reb, ast, threes):
    return {"athlete": {"displayName": name}, "starter": True, "didNotPlay": False,
            "stats": [str(mins), str(pts), "8-15", "%d-6" % threes, "2-2", str(reb), str(ast), "1", "0", "0"]}


def summary(home, away, home_players, away_players, final=True):
    comp = {"status": {"type": {"state": "post" if final else "in", "completed": final}},
            "competitors": [{"homeAway": "home", "team": {"id": home, "abbreviation": home, "displayName": TEAMS[home]}},
                            {"homeAway": "away", "team": {"id": away, "abbreviation": away, "displayName": TEAMS[away]}}]}
    return {"header": {"competitions": [comp]},
            "boxscore": {"players": [
                {"team": {"id": home, "abbreviation": home}, "statistics": [{"keys": KEYS, "athletes": [line(*p) for p in home_players]}]},
                {"team": {"id": away, "abbreviation": away}, "statistics": [{"keys": KEYS, "athletes": [line(*p) for p in away_players]}]}]}}


class FakeESPN:
    """Alpha One (HOU) plays every other day for 40 days, about 24 points in 32-36 minutes.
    Opponents: ATL lets everyone score; CHA doesn't."""

    def __init__(self, today):
        self.calls = []
        self.games = {}
        for i in range(1, 41, 2):
            d = (today - timedelta(days=i)).strftime("%Y%m%d")
            opp = "ATL" if i % 4 == 1 else "CHA"
            boost = 1.2 if opp == "ATL" else 0.85
            pts = round(24 * boost) + (i % 3) - 1
            hou = [("Alpha One", 34 + (i % 3) - 1, pts, 5, 4, 2), ("Gamma Three", 30, round(15 * boost), 6, 3, 1)]
            other = [("Opp Guard %s" % opp, 34, round(20 * boost), 4, round(6 * boost), 2),
                     ("Opp Big %s" % opp, 30, round(14 * boost), round(10 * boost), 2, 0)]
            self.games[d] = ("ev%d" % i, summary("HOU", opp, hou, other))

    def __call__(self, url):
        self.calls.append(url)
        q = parse_qs(urlparse(url).query)
        if "scoreboard" in url:
            g = self.games.get(q["dates"][0])
            return 200, {}, json.dumps({"events": [{"id": g[0]}] if g else []}).encode()
        if "summary" in url:
            eid = q["event"][0]
            for d, (e, s) in self.games.items():
                if e == eid:
                    return 200, {}, json.dumps(s).encode()
        return 404, {}, b""


class FullCourt(unittest.TestCase):
    def setUp(self):
        self.con = connect(os.path.join(tempfile.mkdtemp(), "fc.db"))
        self.today = local(utcnow()).date()
        self.espn = FakeESPN(self.today)

    def sync(self, n=500):
        return fullcourt.sync(self.con, max_requests=n, today=self.today, fetch=self.espn,
                              back_to=(self.today - timedelta(days=45)).isoformat(), log=lambda *a: None)

    def test_parse(self):
        rows = fullcourt.parse_summary(summary("HOU", "ATL", [("Alpha One", "34:30", 25, 5, 4, 3)], []))
        self.assertEqual(len(rows), 1)
        r = rows[0]
        self.assertEqual((r["player_key"], r["team"], r["opp"], r["home"]), ("alpha one", "HOU", "ATL", 1))
        self.assertAlmostEqual(r["minutes"], 34.5)
        self.assertEqual((r["points"], r["threes"], r["assists"]), (25, 3, 4))
        self.assertIsNone(fullcourt.parse_summary(summary("HOU", "ATL", [], [], final=False)))

    def test_sync_newest_first_and_resumes(self):
        r = self.sync(n=12)
        self.assertEqual(r["requests"], 12)
        newest = self.con.execute("SELECT MAX(game_date) FROM nba_box").fetchone()[0]
        self.assertEqual(newest, (self.today - timedelta(days=1)).isoformat())   # newest days first
        self.sync()
        self.assertEqual(self.con.execute("SELECT COUNT(DISTINCT event_id) FROM nba_box").fetchone()[0], 20)
        before = len(self.espn.calls)
        self.sync()
        self.assertEqual(len(self.espn.calls), before)                           # nothing left to fetch
        self.assertEqual(self.con.execute("SELECT name FROM nba_teams WHERE abbr='HOU'").fetchone()[0], "Houston Rockets")

    def test_projection(self):
        self.sync()
        m = fullcourt.Model(self.con, today=self.today)
        self.assertTrue(m.ready())
        base = m.project("alpha one", "player_points")
        self.assertAlmostEqual(base["mean"], 24, delta=1.0)
        soft = m.project("alpha one", "player_points", "ATL")
        tough = m.project("alpha one", "player_points", "CHA")
        self.assertGreater(soft["mean"], base["mean"])                           # ATL allows more
        self.assertLess(tough["mean"], base["mean"])
        self.assertGreater(m.prob(base, 21.5, "over"), 0.6)
        self.assertLess(m.prob(base, 27.5, "over"), 0.4)
        self.assertAlmostEqual(m.prob(base, 23.5, "over") + m.prob(base, 23.5, "under"), 1.0)
        pra = m.project("alpha one", "player_points_rebounds_assists")
        self.assertAlmostEqual(pra["mean"], 33, delta=1.5)
        self.assertEqual(m.opponent("alpha one", "Houston Rockets", "Atlanta Hawks"), "ATL")
        self.assertIsNone(m.project("nobody here", "player_points"))
        self.assertEqual(m._resolve("al one"), "alpha one")              # same last name and first letter

    def test_board_reads(self):
        self.sync()
        t0 = utcnow() + timedelta(hours=3)
        ev, od, ka = nba_fixture(t0)
        automod.run_league(self.con, ACFG, "nba", "K", now=t0 - timedelta(minutes=55), fetch=FakeAPI(ev, od, ka), log=lambda *a: None)
        b = boardmod.build(self.con, CFG, "nba", now=t0 - timedelta(minutes=50))
        self.assertTrue(b["model_ready"])
        alpha = [x for x in b["fliff"] if x["player"] == "Alpha One" and x["side"] == "over"][0]
        self.assertIsNotNone(alpha["ge_p"])
        self.assertIsNotNone(alpha["proj"])
        self.assertIn(alpha["ge_tag"], ("agree", "neutral", "conflict"))
        w = CFG["model"]["weight"]
        self.assertAlmostEqual(alpha["p_blend"], alpha["p"] + w * (alpha["ge_p"] - alpha["p"]))
        for sec in ("pickem", "fliff", "kalshi"):
            for x in b[sec]:
                self.assertIn("score", x)
                self.assertTrue(0 <= x["score"] <= 100)


class Score(unittest.TestCase):
    def test_likelier_picks_score_higher_at_the_same_edge(self):
        base = {"book": "kalshi", "fee": 0.0, "price": None, "ge_p": None}
        lo = boardmod.score_row(dict(base, p=0.42, ask=0.40), CFG)            # +5% edge, 42% to hit
        hi = boardmod.score_row(dict(base, p=0.63, ask=0.60), CFG)            # +5% edge, 63% to hit
        self.assertAlmostEqual(lo["ev_pct"], hi["ev_pct"], places=2)
        self.assertGreater(hi["score"], lo["score"])
        self.assertGreater(hi["kelly"], lo["kelly"])
        neg = boardmod.score_row(dict(base, p=0.38, ask=0.40), CFG)
        self.assertEqual(neg["score"], 0)
        agree = boardmod.score_row(dict(base, p=0.42, ask=0.40, ge_p=0.55, ge_tag="agree"), CFG)
        self.assertGreater(agree["score"], lo["score"])
        biased = boardmod.score_row(dict(base, p=0.42, ask=0.40, ge_p=0.70, ge_tag="biased"), CFG)
        self.assertEqual(biased["score"], lo["score"])                         # a model that runs high doesn't count
        fl = boardmod.score_row({"book": "fliff", "p": 0.55, "price": 2.0, "ge_p": None}, CFG)
        self.assertAlmostEqual(fl["ev_pct"], 0.10)


if __name__ == "__main__":
    unittest.main()
