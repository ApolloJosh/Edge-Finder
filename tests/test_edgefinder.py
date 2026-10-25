"""Run:  python3 -m unittest discover -s tests   (from the Edge Finder folder)

No network: a fake fetcher serves responses shaped like The Odds API and
Kalshi's real ones.
"""
import json
import os
import sys
import tempfile
import unittest
from datetime import timedelta
from urllib.parse import parse_qs, urlparse

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.dirname(HERE))

from ef import bets as betlog  # noqa: E402
from ef import board as boardmod  # noqa: E402
from ef import gridiron, render  # noqa: E402
from ef.config import load_config  # noqa: E402
from ef.db import connect  # noqa: E402
from ef.fair import (breakeven, consensus, devig_pair, entry_return, kalshi_fee, kalshi_share_fee,  # noqa: E402
                     shift_over)
from ef.sources import kalshi_game_date, pull_kalshi, pull_odds  # noqa: E402
from ef.util import iso, local, player_key, utcnow  # noqa: E402

CFG = load_config()


# ----------------------------------------------------------------- unit


class Names(unittest.TestCase):
    def test_keys(self):
        self.assertEqual(player_key("P.J. Washington"), "pj washington")
        self.assertEqual(player_key("PJ Washington"), "pj washington")
        self.assertEqual(player_key("P J Washington"), "pj washington")
        self.assertEqual(player_key("Jabari Smith Jr."), "jabari smith")
        self.assertEqual(player_key("Nikola Jokić"), "nikola jokic")
        self.assertEqual(player_key("De'Aaron Fox"), "deaaron fox")
        self.assertEqual(player_key("Karl-Anthony Towns"), "karl anthony towns")
        self.assertEqual(player_key("Gary Payton II"), "gary payton")
        self.assertEqual(player_key("Herb Jones", {"herb jones": "herbert jones"}), "herbert jones")


class Math(unittest.TestCase):
    def test_devig_even(self):
        m, p = devig_pair(1.909, 1.909)
        self.assertAlmostEqual(m, 0.5, places=6)
        self.assertAlmostEqual(p, 0.5, places=6)

    def test_devig_favorite(self):
        m, p = devig_pair(1.6667, 2.2)  # -150 / +120
        self.assertAlmostEqual(m, 0.6 / (0.6 + 1 / 2.2), places=3)
        self.assertGreater(p, m)  # power method gives the favourite more
        self.assertLess(p, 0.6)

    def test_breakevens_match_handoff(self):
        self.assertAlmostEqual(breakeven(2, {"2": 3}), 0.5774, places=3)
        self.assertAlmostEqual(breakeven(3, {"3": 5}), 0.5848, places=3)
        self.assertAlmostEqual(breakeven(3, {"3": 6}), 0.5503, places=3)
        flex6 = breakeven(6, {"6": 25, "5": 2, "4": 0.4})
        self.assertTrue(0.53 < flex6 < 0.56, flex6)

    def test_entry_return(self):
        self.assertAlmostEqual(entry_return([0.5, 0.5], {"2": 3}), 0.75)
        self.assertAlmostEqual(entry_return([0.6, 0.5, 0.5], {"3": 6}), 0.9)
        self.assertAlmostEqual(entry_return([0.5] * 3, {"3": 2.25, "2": 1.25}), 0.125 * 2.25 + 0.375 * 1.25)

    def test_shift(self):
        self.assertAlmostEqual(shift_over(0.5, 24.5, 24.5, "player_points"), 0.5)
        down = shift_over(0.5, 24.5, 23.5, "player_points")
        up = shift_over(0.5, 24.5, 25.5, "player_points")
        self.assertTrue(0.54 < down < 0.58, down)
        self.assertAlmostEqual(down - 0.5, 0.5 - up, places=3)
        # whole-number line: conditional on no push, symmetric at the mean
        self.assertAlmostEqual(shift_over(0.5, 24.5, 24.5 + 0.5, "player_points") + shift_over(0.5, 24.5, 24.0, "player_points"), 1.0, places=2)

    def test_consensus_drops_far_lines(self):
        qs = [{"book": "fanduel", "point": 24.5, "over": 1.9, "under": 1.9},
              {"book": "draftkings", "point": 28.5, "over": 1.9, "under": 1.9}]
        c = consensus(qs, 24.5, "player_points", {"fanduel": 1, "draftkings": 1}, 2.0)
        self.assertEqual(c["n"], 1)
        self.assertTrue(c["exact"])

    def test_kalshi_fee(self):
        self.assertAlmostEqual(kalshi_fee(0.50, 1), 0.02)
        self.assertAlmostEqual(kalshi_fee(0.50, 10), 0.018)
        self.assertAlmostEqual(kalshi_fee(0.95, 100), 0.0034)
        self.assertAlmostEqual(kalshi_share_fee(0.50), 0.0175)          # buying by the dollar: no rounding

    def test_kalshi_date(self):
        self.assertEqual(kalshi_game_date("KXNBAPTS-26OCT24HOUATL"), "2026-10-24")
        self.assertIsNone(kalshi_game_date("garbage"))

    def test_ge_prob(self):
        self.assertAlmostEqual(gridiron.prob_over(60, 40, 85, 60), 0.5, places=6)
        self.assertGreater(gridiron.prob_over(60, 40, 85, 50), 0.5)
        self.assertAlmostEqual(gridiron.prob_over(4, 3, 6, 6), 0.25, places=2)


# ----------------------------------------------------------------- integration


def _book(key, markets):
    return {"key": key, "title": key, "markets": [
        {"key": mk, "last_update": "x", "outcomes": outs} for mk, outs in markets.items()]}


def _ou(player, point, over, under, mult=None):
    o = {"name": "Over", "description": player, "price": over, "point": point}
    u = {"name": "Under", "description": player, "price": under, "point": point}
    if mult:
        o["multiplier"] = u["multiplier"] = mult
    return [o, u]


class FakeAPI:
    """Routes URLs to fixture payloads and counts credits like the real API."""

    def __init__(self, events, odds, kalshi):
        self.events, self.odds, self.kalshi = events, odds, kalshi
        self.remaining = 500
        self.calls = []

    def __call__(self, url):
        self.calls.append(url)
        u = urlparse(url)
        qs = parse_qs(u.query)
        if "kalshi" in u.netloc:
            series = qs.get("series_ticker", [""])[0]
            return 200, {}, json.dumps({"markets": self.kalshi.get(series, []), "cursor": ""}).encode()
        if u.path.endswith("/events"):
            return 200, {"x-requests-remaining": str(self.remaining), "x-requests-last": "0"}, json.dumps(self.events).encode()
        if "/odds" in u.path:
            ev_id = u.path.split("/")[-2]
            data = self.odds.get(ev_id)
            if not data:
                return 404, {}, b'{"message":"not found"}'
            mk = set(qs["markets"][0].split(","))
            used = len({m["key"] for b in data["bookmakers"] for m in b["markets"] if m["key"] in mk})
            self.remaining -= used
            trimmed = dict(data, bookmakers=[dict(b, markets=[m for m in b["markets"] if m["key"] in mk])
                                             for b in data["bookmakers"]])
            return 200, {"x-requests-remaining": str(self.remaining), "x-requests-last": str(used)}, json.dumps(trimmed).encode()
        return 404, {}, b""


def nba_fixture(t0, moved=False):
    ev = lambda i, away, home: {"id": "ev%d" % i, "sport_key": "basketball_nba",
                                "commence_time": iso(t0 + timedelta(minutes=30 * i)),
                                "home_team": home, "away_team": away}
    events = [ev(1, "Houston Rockets", "Atlanta Hawks"), ev(2, "Miami Heat", "Charlotte Hornets"),
              ev(3, "Golden State Warriors", "Phoenix Suns")]
    a_fd = (1.80, 2.02) if moved else (1.87, 1.95)
    odds = {
        "ev1": {"id": "ev1", "bookmakers": [
            _book("fanduel", {"player_points": _ou("Alpha One", 24.5, *a_fd)}),
            _book("draftkings", {"player_points": _ou("Alpha One", 24.5, 1.90, 1.90),
                                 "player_assists": _ou("Delta Four", 5.5, 1.70, 2.15)}),
            _book("pinnacle", {"player_points": _ou("Alpha One", 24.5, 1.83, 2.03)}),
            _book("underdog", {"player_points": _ou("Alpha One", 23.5, 1.0, 1.0, mult=1.0),
                               "player_assists": _ou("Delta Four", 5.5, 1.0, 1.0)}),
            _book("prizepicks", {"player_points": _ou("Alpha One", 24.5, 1.73, 1.73)}),
            _book("fliff", {"player_points": _ou("Alpha One", 24.5, 2.10, 1.70)}),
        ]},
        "ev2": {"id": "ev2", "bookmakers": [
            _book("fanduel", {"player_rebounds": _ou("Beta Two Jr.", 9.5, 2.30, 1.65)}),
            _book("draftkings", {"player_rebounds": _ou("Beta Two", 9.5, 2.25, 1.67)}),
            _book("underdog", {"player_rebounds": _ou("Beta Two", 9.5, 1.0, 1.0)}),
        ]},
        "ev3": {"id": "ev3", "bookmakers": [
            _book("fanduel", {"player_assists": _ou("Gámma Three", 6.5, 1.65, 2.30)}),
            _book("draftkings", {"player_assists": _ou("Gamma Three", 6.5, 1.67, 2.25)}),
            _book("underdog", {"player_assists": _ou("Gamma Three", 6.5, 1.0, 1.0)}),
        ]},
    }
    d = local(t0 + timedelta(minutes=30)).strftime("%y%b%d").upper()
    kalshi = {"KXNBAPTS": [
        {"ticker": "KXNBAPTS-%sHOUATL-HOUAONE-24" % d, "event_ticker": "KXNBAPTS-%sHOUATL" % d,
         "title": "Alpha One: 24+ points", "yes_sub_title": "Alpha One: 24+", "floor_strike": 23.5,
         "strike_type": "greater", "yes_ask_dollars": "0.5000", "yes_bid_dollars": "0.4600",
         "yes_ask_size_fp": "120.00", "yes_bid_size_fp": "80.00"},
        {"ticker": "KXNBAPTS-%sHOUATL-HOUAONE-35" % d, "event_ticker": "KXNBAPTS-%sHOUATL" % d,
         "title": "Alpha One: 35+ points", "yes_sub_title": "Alpha One: 35+", "floor_strike": 34.5,
         "strike_type": "greater", "yes_ask_dollars": "0.0500", "yes_bid_dollars": "0.0200"},
    ]}
    return events, odds, kalshi


class Pipeline(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.con = connect(os.path.join(self.tmp, "t.db"))
        self.t0 = utcnow() + timedelta(hours=2)
        self.quiet = lambda *a, **k: None

    def _pull(self, moved=False, kind="board", events=None, markets=None):
        ev, od, ka = nba_fixture(self.t0, moved)
        api = FakeAPI(ev, od, ka)
        pid, info = pull_odds(self.con, CFG, "nba", "KEY", fetch=api, yes=True, kind=kind,
                              event_ids=events, markets=markets, log=self.quiet)
        if kind == "board":
            pull_kalshi(self.con, CFG, "nba", pid, fetch=api, log=self.quiet)
        return pid, info, api

    def test_end_to_end(self):
        pid, info, api = self._pull()
        self.assertEqual(info["events"], 3)
        # 3 games: ev1 has 2 markets, ev2 and ev3 one each, 9 books -> 1 region
        self.assertEqual(info["credits_used"], 4)
        self.assertTrue(all("apiKey=KEY" in c for c in api.calls if "the-odds-api" in c))

        b = boardmod.build(self.con, CFG, "nba", pull_id=pid)
        rows = {(x["book"], x["player_key"], x["side"], x["point"]): x for x in b["pickem"]}

        # Delta has one sharp book -> excluded at min_sharp_books=2
        self.assertFalse(any(k[1] == "delta four" for k in rows))

        pp = rows[("prizepicks", "alpha one", "over", 24.5)]
        self.assertTrue(0.50 < pp["p"] < 0.53, pp["p"])
        self.assertFalse(pp["flagged"])
        self.assertTrue(pp["exact"])

        ud = rows[("underdog", "alpha one", "over", 23.5)]
        self.assertFalse(ud["exact"])
        self.assertAlmostEqual(ud["gap"], 1.0)
        self.assertGreater(ud["p"], 0.56)
        self.assertIn("ud3", ud["clears"])

        beta = rows[("underdog", "beta two", "under", 9.5)]  # "Beta Two Jr." at FD matched
        self.assertEqual(beta["n_sharp"], 2)
        self.assertTrue(beta["flagged"])
        gamma = rows[("underdog", "gamma three", "over", 6.5)]  # accent matched
        self.assertTrue(gamma["flagged"])

        fl = [x for x in b["fliff"] if x["side"] == "over"][0]
        self.assertTrue(fl["flagged"])
        self.assertAlmostEqual(fl["ev"], fl["p"] * 2.10 - 1)

        kal = [x for x in b["kalshi"] if x["point"] == 23.5 and x["side"] == "over"]
        self.assertEqual(len(kal), 1, "Kalshi 24+ should match Alpha's game by date")
        self.assertEqual(kal[0]["event_id"], "ev1")
        self.assertAlmostEqual(kal[0]["ev"], kal[0]["p"] - 0.50 - kalshi_share_fee(0.5))
        self.assertFalse(any(x["point"] == 34.5 for x in b["kalshi"]), "35+ is 10 points off - must be dropped")

        ud3 = [e for e in b["entries"] if e["entry"] == "ud3"]
        self.assertEqual(len(ud3), 1)
        self.assertEqual(len({l["event_id"] for l in ud3[0]["legs"]}), 3)
        self.assertGreater(ud3[0]["roi"], 0)

        boardmod.save_codes(self.con, b)
        path, csv_path = render.write(b, CFG, "/Users/x/Edge Finder", self.tmp)
        with open(path) as f:
            page = f.read()
        self.assertIn("Alpha One", page)
        self.assertIn('"c":"%s"' % ud["code"], page)
        self.assertIn("UD Standard 3", page)
        self.assertTrue(os.path.exists(csv_path))

        # log the ud3 entry by code, then a Fliff straight bet
        codes = [ud["code"], beta["code"], gamma["code"]]
        ids = betlog.log_bet(self.con, CFG, "nba", codes, entry="ud3", stake=2)
        self.assertEqual(len(ids), 1)
        fid = betlog.log_bet(self.con, CFG, "nba", [fl["code"]], stake=1)[0]
        with self.assertRaises(SystemExit):
            betlog.log_bet(self.con, CFG, "nba", codes[:2], entry="ud3")
        with self.assertRaises(SystemExit):
            betlog.log_bet(self.con, CFG, "nba", [ud["code"], pp["code"]])

        # closing snapshot: Alpha's over gets steamed at FanDuel
        self._pull(moved=True, kind="close", events=["ev1"], markets=["player_points"])
        n = betlog.update_closes(self.con, CFG, now=self.t0 + timedelta(hours=3))
        self.assertEqual(n, 4)
        leg = self.con.execute("SELECT * FROM bet_legs WHERE bet_id=? AND leg=1", (ids[0],)).fetchone()
        self.assertGreater(leg["close_fair_p"], leg["fair_p"])

        rep = betlog.clv_report(self.con, CFG, now=self.t0 + timedelta(hours=3))
        self.assertIn("All legs", rep)
        self.assertIn("n=4", rep)

        self.assertAlmostEqual(betlog.set_result(self.con, CFG, ids[0], "win"), 12.0)
        self.assertAlmostEqual(betlog.set_result(self.con, CFG, fid, "win"), 2.10)
        self.assertIn("RESULTS", betlog.clv_report(self.con, CFG))

    def test_started_games_are_skipped(self):
        pid, _, _ = self._pull()
        b = boardmod.build(self.con, CFG, "nba", pull_id=pid, now=self.t0 + timedelta(minutes=45))
        self.assertFalse(any(x["event_id"] == "ev1" for x in b["pickem"] + b["fliff"] + b["kalshi"]))

    def test_budget_prompt(self):
        ev, od, ka = nba_fixture(self.t0)
        cfg = load_config()
        cfg["odds_api"]["budget_per_pull"] = 1
        with self.assertRaises(SystemExit):
            pull_odds(self.con, cfg, "nba", "KEY", fetch=FakeAPI(ev, od, ka), log=self.quiet,
                      ask=lambda _: "n")

    def test_adjusted_lines_and_thin_kalshi(self):
        """A price moved to a different line takes a cut before flagging, but bets
        store the market's own number so CLV compares like with like. Kalshi
        needs real size to flag."""
        pid, _, _ = self._pull()
        b = boardmod.build(self.con, CFG, "nba", pull_id=pid)
        rows = b["pickem"] + b["fliff"] + b["kalshi"]
        for x in rows:
            if x["exact"]:
                self.assertEqual(x["p"], x["p_raw"])
            else:
                self.assertLess(x["p"], x["p_raw"])
        boardmod.save_codes(self.con, b)
        ud = [x for x in b["pickem"] if x["book"] == "underdog" and x["player_key"] == "alpha one" and x["side"] == "over"][0]
        stored = self.con.execute("SELECT fair_p FROM board_picks WHERE code=?", (ud["code"],)).fetchone()["fair_p"]
        self.assertAlmostEqual(stored, ud["p_raw"])
        cfg = load_config()
        cfg["kalshi"]["min_size"] = 1000           # fixture offers 120
        b2 = boardmod.build(self.con, cfg, "nba", pull_id=pid)
        k = [x for x in b2["kalshi"] if x["point"] == 23.5 and x["side"] == "over"][0]
        self.assertGreater(k["roi"], CFG["thresholds"]["kalshi_min_ev"])
        self.assertFalse(k["flagged"])

    def test_codes_follow_their_board(self):
        """A command copied from an older board must log that board's picks,
        even after a lineup-time rerun renumbers everything."""
        pid, _, _ = self._pull()
        b1 = boardmod.build(self.con, CFG, "nba", pull_id=pid)
        boardmod.save_codes(self.con, b1)
        first = {x["code"]: x["player_key"] for s in ("pickem", "fliff", "kalshi") for x in b1[s]}
        later = iso(utcnow() + timedelta(minutes=5))
        self.con.execute("INSERT INTO board_picks (board_ts, league, code, event_id, commence_time, book, market,"
                         " player, player_key, side, point, fair_p) VALUES (?,?,?,?,?,?,?,?,?,?,?,?)",
                         (later, "nba", "1", "ev2", iso(self.t0), "fliff", "player_rebounds", "Someone Else",
                          "someone else", "over", 9.5, 0.5))
        _, picks = betlog.resolve_codes(self.con, "nba", ["1"], b1["built_at"])
        self.assertEqual(picks[0]["player_key"], first["1"])
        _, picks = betlog.resolve_codes(self.con, "nba", ["1"])
        self.assertEqual(picks[0]["player_key"], "someone else")
        with self.assertRaises(SystemExit):
            betlog.resolve_codes(self.con, "nba", ["1"], "2020-01-01T00:00:00Z")

    def test_watch_waits_for_last_game(self):
        pid, _, _ = self._pull()
        b = boardmod.build(self.con, CFG, "nba", pull_id=pid)
        boardmod.save_codes(self.con, b)
        fl = [x for x in b["fliff"] if x["side"] == "over"][0]           # ev1, starts t0+30m
        beta = [x for x in b["pickem"] if x["player_key"] == "beta two" and x["side"] == "under"][0]  # ev2, t0+60m
        gamma = [x for x in b["pickem"] if x["player_key"] == "gamma three" and x["side"] == "over"][0]  # ev3, t0+90m
        betlog.log_bet(self.con, CFG, "nba", [fl["code"]], stake=1, board_ts=b["built_at"])
        betlog.log_bet(self.con, CFG, "nba", [beta["code"], gamma["code"]], entry="ud2", stake=1,
                       board_ts=b["built_at"])

        clock = {"t": self.t0}
        ev, od, ka = nba_fixture(self.t0, moved=True)
        api = FakeAPI(ev, od, ka)
        msgs = []
        real = betlog.utcnow
        betlog.utcnow = lambda: clock["t"]
        try:
            def tick(sec):
                clock["t"] = clock["t"] + timedelta(seconds=sec)
            betlog.watch(self.con, CFG, "nba", "KEY", lead=12, poll=60, fetch=api, log=msgs.append, sleep=tick)
        finally:
            betlog.utcnow = real
        closes = self.con.execute("SELECT COUNT(*) AS n FROM pulls WHERE kind='close'").fetchone()["n"]
        self.assertEqual(closes, 3, msgs)                       # one snapshot per game
        self.assertGreater(clock["t"], self.t0 + timedelta(minutes=90))  # stayed until the last tip
        self.assertTrue(msgs[-1].startswith("Every game you bet has started"), msgs[-1])
        self.assertEqual(self.con.execute("SELECT COUNT(*) AS n FROM bet_legs WHERE close_fair_p IS NOT NULL")
                         .fetchone()["n"], 3)
        self.assertTrue(any("Next closing snapshot" in m for m in msgs))


class GridironIntegration(unittest.TestCase):
    def test_nfl_board_shows_ge(self):
        tmp = tempfile.mkdtemp()
        con = connect(os.path.join(tmp, "t.db"))
        t0 = utcnow() + timedelta(hours=20)
        events = [{"id": "nf1", "sport_key": "americanfootball_nfl", "commence_time": iso(t0),
                   "home_team": "Denver Broncos", "away_team": "Cincinnati Bengals"}]
        odds = {"nf1": {"id": "nf1", "bookmakers": [
            _book("fanduel", {"player_reception_yds": _ou("Tee Higgins", 64.5, 1.91, 1.91),
                              "player_pass_yds": _ou("Joe Burrow", 262.5, 1.87, 1.95)}),
            _book("draftkings", {"player_reception_yds": _ou("Tee Higgins", 64.5, 1.87, 1.95),
                                 "player_pass_yds": _ou("Joe Burrow", 259.5, 1.90, 1.90)}),
            _book("prizepicks", {"player_reception_yds": _ou("Tee Higgins", 58.5, 1.0, 1.0),
                                 "player_pass_yds": _ou("Joe Burrow", 249.5, 1.0, 1.0)}),
        ]}}
        export = {"source": "gridiron-edge", "build": "v17", "snapshot": {
            "year": 2026, "week": 8, "savedAt": 1761300000000, "band": 2, "rows": [
                {"id": "1", "name": "Tee Higgins", "pos": "WR", "kind": "REC", "team": "CIN", "opp": "DEN",
                 "markets": {"recYds": {"median": 70, "p25": 45, "p75": 96, "score": 74},
                             "rec": {"median": 5, "p25": 4, "p75": 7, "score": 70}}},
                {"id": "2", "name": "Joe Burrow", "pos": "QB", "kind": "QB", "team": "CIN", "opp": "DEN",
                 "markets": {"passYds": {"median": 290, "p25": 240, "p75": 330, "score": 81}}},
            ]}}
        path = os.path.join(tmp, "gridiron-edge-2026-wk08.json")
        with open(path, "w") as f:
            json.dump(export, f)
        info = gridiron.import_export(con, CFG, path)
        self.assertEqual(info["rows"], 3)
        pid, _ = pull_odds(con, CFG, "nfl", "K", fetch=FakeAPI(events, odds, {}), yes=True, log=lambda *a: None)
        b = boardmod.build(con, CFG, "nfl", pull_id=pid)
        tee = [x for x in b["pickem"] if x["player_key"] == "tee higgins" and x["side"] == "over"][0]
        self.assertTrue(tee["exact"] is False and tee["gap"] == 6)
        self.assertGreater(tee["ge_p"], 0.6)
        self.assertEqual(tee["ge_tag"], "agree")
        self.assertEqual(tee["ge_score"], 74)
        burrow = [x for x in b["pickem"] if x["player_key"] == "joe burrow" and x["side"] == "over"]
        self.assertTrue(burrow and burrow[0]["ge_tag"] == "biased")
        page = render.render(b, CFG, "/x")
        self.assertIn("Gridiron Edge", page)
        self.assertIn("runs high", page)


if __name__ == "__main__":
    unittest.main()
