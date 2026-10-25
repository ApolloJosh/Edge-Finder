"""Price checker data: everything the Check page needs to price ANY line for a
player against the sharp books, in the browser, for apps with no price feed
(Robinhood). Same math as the board (fair.consensus): each sharp book's
de-vigged price is turned into an implied mean once here, so the page only has
to move it to the line you type.

Also logs a bet on such a line (`bet-line`), since it has no board code.
"""
from . import gridiron
from .board import BOOK_LABELS, _game_label, market_label, merged_rows, sharp_quotes
from .fair import SIGMA_FLOOR, STAT_MODELS, devig_pair, implied_mean, stat_sigma
from .util import iso, utcnow


def _r(x, d=4):
    return round(float(x), d)


def payload(con, cfg, league, now=None):
    now = now or utcnow()
    rows = merged_rows(con, league, now)
    events = {r["event_id"]: r for r in con.execute("SELECT * FROM events WHERE league=?", (league,))}
    weights = cfg.sharp_weights
    quotes = sharp_quotes(rows, weights)
    names, pulled = {}, {}
    for r in rows:
        if r["book"] in weights:
            names.setdefault(r["player_key"], r["player"])
            pulled[r["event_id"]] = max(pulled.get(r["event_id"], ""), r["ts"])
    books = sorted(weights)
    th = cfg["thresholds"]
    rh = cfg.get("robinhood", {})
    items = []
    for (ev_id, pk, mk), qs in sorted(quotes.items(), key=lambda kv: (kv[0][1], kv[0][2])):
        ev = events.get(ev_id)
        if not ev or ev["commence_time"] <= iso(now) or mk not in STAT_MODELS:
            continue
        qrows = []
        for q in qs:
            m0, p0 = devig_pair(q["over"], q["under"])
            sig = stat_sigma(mk, q["point"])
            qrows.append([books.index(q["book"]), q["point"], _r(m0), _r(p0), _r(sig, 3),
                          _r(implied_mean(m0, q["point"], sig), 3), _r(implied_mean(p0, q["point"], sig), 3)])
        items.append({"k": pk, "pl": names.get(pk, pk), "ev": ev_id, "g": _game_label(ev), "t": ev["commence_time"],
                      "m": mk, "q": qrows, "ts": pulled.get(ev_id)})
    return {
        "league": league, "gen": iso(now), "books": books,
        "bl": {b: BOOK_LABELS.get(b, b) for b in books}, "w": [weights[b] for b in books],
        "labels": {m: market_label(m) for m in cfg.league(league)["markets"]},
        "models": {m: [STAT_MODELS[m][0], STAT_MODELS[m][1], SIGMA_FLOOR.get(m, 0)] for m in cfg.league(league)["markets"]
                   if m in STAT_MODELS},
        "gap": {m: cfg.max_gap(m) for m in cfg.league(league)["markets"]},
        "shift": th.get("max_shift", 0.08), "cut": th.get("adj_haircut_per_sd", 0.0),
        "minBooks": 1 if th.get("one_book_ok") else th["min_sharp_books"],
        "fee": rh.get("fee_per_contract", 0.015), "minEv": rh.get("min_ev", 0.03),
        "items": items,
    }


def log_line_bet(con, cfg, league, event_id, player_key, market, side, point, book="robinhood",
                 stake=None, contracts=None, price=None, notes=None, now=None):
    """Record a bet on a line that isn't on the board (bought on Robinhood after
    the Check page priced it). Fair and Gridiron Edge are worked out here, from
    the same pull the page used, so the record doesn't depend on the page."""
    from .bets import _insert_leg, fair_at
    now = now or utcnow()
    if side not in ("over", "under"):
        raise SystemExit("Side must be over or under.")
    ev = con.execute("SELECT * FROM events WHERE event_id=?", (event_id,)).fetchone()
    if not ev:
        raise SystemExit("Unknown game %s." % event_id)
    row = con.execute("SELECT player FROM lines WHERE event_id=? AND player_key=? AND market=? LIMIT 1",
                      (event_id, player_key, market)).fetchone()
    if not row:
        raise SystemExit("No lines for %s %s in that game." % (player_key, market_label(market)))
    if not contracts or contracts <= 0 or not stake or stake <= 0:
        raise SystemExit("Give the contracts you got and what it cost (from the order summary).")
    leg = {"event_id": event_id, "player_key": player_key, "market": market, "point": float(point), "side": side}
    got = fair_at(con, cfg, league, leg, iso(now))
    fair = got[0] if got else None
    per = stake / contracts
    edge = (fair / per - 1) if fair else None
    rh = cfg.get("robinhood", {})
    ge_p = ge_s = None
    if league == "nfl":
        ge_map, _ = gridiron.load_latest(con)
        g = ge_map.get((player_key, market))
        ge_p, _tag = gridiron.assess(cfg, g, float(point), side)
        ge_s = g["score"] if g else None
    cur = con.execute("INSERT INTO bets (placed_at, league, book, entry_type, stake, contracts, notes) VALUES (?,?,?,?,?,?,?)",
                      (iso(now), league, book, book, round(stake, 2), contracts, notes))
    pick = {"event_id": event_id, "commence_time": ev["commence_time"], "market": market, "player": row["player"],
            "player_key": player_key, "side": side, "point": float(point), "ge_p": ge_p, "ge_score": ge_s,
            "flagged": int(edge is not None and edge >= rh.get("min_ev", 0.03)), "edge": edge}
    _insert_leg(con, cur.lastrowid, 1, pick, price=per, fair=fair, be=per)
    con.commit()
    return cur.lastrowid, fair
