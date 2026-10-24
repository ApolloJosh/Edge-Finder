"""Turn one pull into the board: every pick'em, Fliff and Kalshi line priced
against the sharp consensus."""
from collections import defaultdict

from . import gridiron
from .fair import breakeven, consensus, entry_return, kalshi_fee, stat_sigma
from .util import fmt_american, iso, local, parse_iso, short_team, utcnow

MARKET_LABELS = {
    "player_points": "Points",
    "player_rebounds": "Rebounds",
    "player_assists": "Assists",
    "player_threes": "3-Pointers",
    "player_blocks": "Blocks",
    "player_steals": "Steals",
    "player_turnovers": "Turnovers",
    "player_points_rebounds_assists": "Pts+Reb+Ast",
    "player_points_rebounds": "Pts+Reb",
    "player_points_assists": "Pts+Ast",
    "player_rebounds_assists": "Reb+Ast",
    "player_pass_yds": "Pass Yds",
    "player_pass_attempts": "Pass Att",
    "player_pass_completions": "Completions",
    "player_pass_rush_yds": "Pass+Rush Yds",
    "player_rush_yds": "Rush Yds",
    "player_rush_attempts": "Rush Att",
    "player_rush_reception_yds": "Rush+Rec Yds",
    "player_reception_yds": "Rec Yds",
    "player_receptions": "Receptions",
}

BOOK_LABELS = {
    "prizepicks": "PrizePicks", "underdog": "Underdog", "fliff": "Fliff", "kalshi": "Kalshi",
    "pinnacle": "Pinnacle", "fanduel": "FanDuel", "draftkings": "DraftKings",
    "betonlineag": "BetOnline", "betmgm": "BetMGM", "espnbet": "theScore",
    "williamhill_us": "Caesars", "sleeper": "Sleeper",
}
BOOK_SHORT = {"pinnacle": "PIN", "fanduel": "FD", "draftkings": "DK", "betonlineag": "BOL",
              "betmgm": "MGM", "espnbet": "SCR", "williamhill_us": "CZR"}


def market_label(m):
    return MARKET_LABELS.get(m, m.replace("player_", "").replace("_", " ").title())


def latest_pull(con, league, kind="board"):
    return con.execute(
        "SELECT * FROM pulls WHERE league=? AND kind=? ORDER BY id DESC LIMIT 1", (league, kind)
    ).fetchone()


def sharp_quotes(rows, sharp_books):
    """{(event_id, player_key, market): [ {book, point, over, under}, ... ]}"""
    tmp = defaultdict(dict)
    for r in rows:
        if r["book"] not in sharp_books or r["price"] is None:
            continue
        tmp[(r["event_id"], r["player_key"], r["market"], r["book"], r["point"])][r["side"]] = r["price"]
    out = defaultdict(list)
    for (ev, pk, mk, book, pt), sides in tmp.items():
        if "over" in sides and "under" in sides:
            out[(ev, pk, mk)].append({"book": book, "point": pt, "over": sides["over"], "under": sides["under"]})
    return out


def sharp_summary(quotes):
    parts = []
    for q in sorted(quotes, key=lambda q: q["book"]):
        parts.append("%s %g %s/%s" % (BOOK_SHORT.get(q["book"], q["book"][:3].upper()), q["point"],
                                      fmt_american(q["over"]), fmt_american(q["under"])))
    return " · ".join(parts)


def _game_label(ev):
    if not ev:
        return ""
    return "%s @ %s" % (short_team(ev["away"]), short_team(ev["home"]))


def merged_rows(con, league, now):
    """Each upcoming game's lines from the latest board pull that included it,
    plus Kalshi from the latest board pull. Games get pulled at different times
    (each one ahead of its own tip), so one pull rarely holds the whole slate."""
    latest = {}
    for r in con.execute(
            "SELECT l.event_id, MAX(l.pull_id) AS pid FROM lines l JOIN pulls p ON p.id=l.pull_id"
            " JOIN events e ON e.event_id=l.event_id"
            " WHERE p.league=? AND p.kind='board' AND e.commence_time > ? GROUP BY l.event_id",
            (league, iso(now))):
        latest[r["event_id"]] = r["pid"]
    rows = []
    for ev_id, pid in latest.items():
        rows += con.execute("SELECT * FROM lines WHERE pull_id=? AND event_id=?", (pid, ev_id)).fetchall()
    last = latest_pull(con, league)
    if last:
        rows += con.execute("SELECT * FROM lines WHERE pull_id=? AND book='kalshi'", (last["id"],)).fetchall()
    return rows


def build(con, cfg, league, pull_id=None, now=None):
    """Price everything. With pull_id, only that pull; otherwise the merged slate."""
    now = now or utcnow()
    pull = (con.execute("SELECT * FROM pulls WHERE id=?", (pull_id,)).fetchone()
            if pull_id else latest_pull(con, league))
    if not pull:
        raise SystemExit("No %s pull yet. Run:  python3 edgefinder.py pull %s" % (league.upper(), league))
    if pull_id:
        rows = con.execute("SELECT * FROM lines WHERE pull_id=?", (pull["id"],)).fetchall()
    else:
        rows = merged_rows(con, league, now)
    events = {r["event_id"]: r for r in con.execute("SELECT * FROM events WHERE league=?", (league,))}

    th = cfg["thresholds"]
    weights = cfg.sharp_weights
    min_books = 1 if th.get("one_book_ok") else th["min_sharp_books"]
    quotes = sharp_quotes(rows, weights)

    # Which game each sharp-priced player is in, by local date, for Kalshi.
    by_date = {}
    for (ev_id, pk, mk) in quotes:
        ev = events.get(ev_id)
        if ev:
            d = local(parse_iso(ev["commence_time"])).strftime("%Y-%m-%d")
            by_date[(d, pk, mk)] = ev_id

    ge_map, ge_saved = ({}, None)
    if league == "nfl":
        ge_map, ge_saved = gridiron.load_latest(con)

    # Per-pick breakevens for each pick'em book's entry types.
    be = {}
    for book in cfg.pickem_books:
        be[book] = {eid: (e, breakeven(e["picks"], e["pays"])) for eid, e in cfg.entries(book).items()}

    def started(ev_id):
        ev = events.get(ev_id)
        return ev is not None and ev["commence_time"] <= iso(now)

    def price_it(ev_id, pk, market, point, side):
        qs = quotes.get((ev_id, pk, market))
        if not qs:
            return None
        c = consensus(qs, point, market, weights, cfg.max_gap(market))
        if not c or c["n"] < min_books:
            return None
        # p_raw is the market's fair number (stored with bets, so CLV compares like with like).
        # p is what flags use: when a sharp price had to be moved to this line, take a cut
        # proportional to how far it moved, because the move is a model, not a market.
        c["p_raw"] = c[side]
        cut = 0.0 if c["exact"] else th.get("adj_haircut_per_sd", 0.0) * c["max_gap"] / stat_sigma(market, point)
        c["p"] = c["p_raw"] - cut
        c["sharp"] = sharp_summary([q for q in qs if q["book"] in c["books"]])
        return c

    def with_ge(row, market, point, side):
        if league != "nfl":
            return row
        p, tag = gridiron.assess(cfg, ge_map.get((row["player_key"], market)), point, side)
        g = ge_map.get((row["player_key"], market))
        row.update(ge_p=p, ge_tag=tag, ge_score=(g["score"] if g else None))
        return row

    pickem, fliff, kalshi = [], [], []
    seen = set()
    for r in rows:
        book, side = r["book"], r["side"]
        if book in weights:
            continue
        key = (book, r["event_id"], r["player_key"], r["market"], r["point"], side, r["ref"])
        if key in seen:
            continue
        seen.add(key)

        ev_id = r["event_id"]
        if book == "kalshi":
            ev_id = by_date.get((r["game_date"], r["player_key"], r["market"]))
            if not ev_id:
                continue
        if started(ev_id):
            continue
        c = price_it(ev_id, r["player_key"], r["market"], r["point"], side)
        if not c:
            continue
        ev = events.get(ev_id)
        base = {
            "event_id": ev_id, "game": _game_label(ev), "commence": ev["commence_time"] if ev else None,
            "book": book, "market": r["market"], "player": r["player"], "player_key": r["player_key"],
            "side": side, "point": r["point"], "p": c["p"], "p_raw": c["p_raw"], "n_sharp": c["n"], "exact": c["exact"],
            "gap": c["max_gap"], "sharp": c["sharp"], "multiplier": r["multiplier"],
            "price": r["price"], "ask": r["ask"], "size": r["size"], "ref": r["ref"],
        }

        if book in cfg.pickem_books:
            mult = r["multiplier"] or 1.0
            clears, best = [], None
            for eid, (e, b) in be.get(book, {}).items():
                b_eff = b * (1.0 / mult) ** (1.0 / e["picks"])
                if best is None or b_eff < best[1]:
                    best = (eid, b_eff)
                if c["p"] >= b_eff + th["pickem_cushion"]:
                    clears.append(eid)
            base.update(best_entry=best[0] if best else None, breakeven=best[1] if best else None,
                        edge=(c["p"] - best[1]) if best else None, clears=clears, flagged=bool(clears))
            pickem.append(with_ge(base, r["market"], r["point"], side))
        elif book in cfg.sportsbooks:
            if not r["price"]:
                continue
            ev_pct = c["p"] * r["price"] - 1
            base.update(ev=ev_pct, flagged=ev_pct >= th["fliff_min_ev"])
            fliff.append(with_ge(base, r["market"], r["point"], side))
        elif book == "kalshi":
            fee = kalshi_fee(r["ask"], cfg["kalshi"]["contracts"])
            ev_c = c["p"] - r["ask"] - fee
            roi = ev_c / (r["ask"] + fee)
            deep = (r["size"] or 0) >= cfg["kalshi"].get("min_size", 0)
            base.update(fee=fee, ev=ev_c, roi=roi, flagged=roi >= th["kalshi_min_ev"] and deep)
            kalshi.append(with_ge(base, r["market"], r["point"], side))

    pickem.sort(key=lambda x: (-x["flagged"], -(x["edge"] or -1)))
    fliff.sort(key=lambda x: (-x["flagged"], -x["ev"]))
    kalshi.sort(key=lambda x: (-x["flagged"], -x["roi"]))

    # Codes: one number per row across the whole board, flagged rows first.
    code = 0
    for section in (pickem, fliff, kalshi):
        for x in section:
            code += 1
            x["code"] = str(code)

    entries = suggest_entries(cfg, pickem, be)

    counts = defaultdict(int)
    for r in rows:
        counts[r["book"]] += 1
    return {
        "league": league, "pull": dict(pull), "built_at": iso(now), "pickem": pickem, "fliff": fliff,
        "kalshi": kalshi, "entries": entries, "counts": dict(counts), "events": len(events),
        "games": len({x["event_id"] for x in pickem + fliff + kalshi}),
        "ge_saved": ge_saved, "ge_rows": len(ge_map), "breakevens": be,
    }


def suggest_entries(cfg, pickem, be):
    """Best entry per pick'em entry type from the flagged picks: one pick per
    player, and (by default) one per game, since same-game picks are
    correlated and can pay reduced multipliers."""
    distinct_games = cfg["thresholds"].get("entries_from_different_games", True)
    out = []
    for book, types in be.items():
        pool = [x for x in pickem if x["book"] == book and x["flagged"]]
        pool.sort(key=lambda x: -x["p"])
        chosen, players, games = [], set(), set()
        for x in pool:
            if x["player_key"] in players or (distinct_games and x["event_id"] in games):
                continue
            chosen.append(x)
            players.add(x["player_key"])
            games.add(x["event_id"])
        for eid, (e, b) in types.items():
            n = e["picks"]
            if len(chosen) < n:
                continue
            legs = chosen[:n]
            boost = 1.0
            for l in legs:
                boost *= l["multiplier"] or 1.0
            ret = entry_return([l["p"] for l in legs], e["pays"], boost)
            out.append({"book": book, "entry": eid, "label": e["label"], "legs": legs,
                        "roi": ret - 1, "verify": bool(e.get("verify")), "breakeven": b})
    out.sort(key=lambda x: -x["roi"])
    return out


def row_value(x):
    """The one number a row is judged by: pick'em edge over the bar, Fliff EV, Kalshi ROI."""
    for k in ("edge", "roi", "ev"):
        if x.get(k) is not None:
            return x[k]
    return None


def save_codes(con, board):
    ts = board["built_at"]
    for section in ("pickem", "fliff", "kalshi"):
        for x in board[section]:
            con.execute(
                "INSERT INTO board_picks (board_ts, league, code, pull_id, event_id, commence_time, book,"
                " market, player, player_key, side, point, price, multiplier, ask, ref, fair_p, n_sharp,"
                " ge_p, ge_score, flagged, edge) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                (ts, board["league"], x["code"], board["pull"]["id"], x["event_id"], x["commence"],
                 x["book"], x["market"], x["player"], x["player_key"], x["side"], x["point"],
                 x["price"], x["multiplier"], x["ask"], x["ref"], x["p_raw"], x["n_sharp"],
                 x.get("ge_p"), x.get("ge_score"), 1 if x["flagged"] else 0, row_value(x)),
            )
    con.commit()
