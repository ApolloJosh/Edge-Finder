"""Bet log and closing line value.

CLV here is measured in fair probability: the sharp market's fair chance for
the exact pick you took, at the last pull before the game started, minus what
it was when you placed it. Positive means the market moved your way.
"""
import time
from collections import defaultdict
from datetime import timedelta

from .board import BOOK_LABELS, market_label, sharp_quotes
from .fair import breakeven, consensus, kalshi_shares
from .util import iso, local, parse_iso, pct, utcnow


# ------------------------------------------------------------------ logging


def resolve_codes(con, league, codes, board_ts=None):
    """Find picks by their number on a board. Numbers change every time the
    board is rebuilt, so the board page puts its own timestamp in the command."""
    latest = con.execute("SELECT MAX(board_ts) AS t FROM board_picks WHERE league=?", (league,)).fetchone()["t"]
    if not latest:
        raise SystemExit("No %s board yet. Run:  python3 edgefinder.py run %s" % (league.upper(), league))
    ts = board_ts or latest
    if board_ts and not con.execute("SELECT 1 FROM board_picks WHERE league=? AND board_ts=? LIMIT 1",
                                    (league, board_ts)).fetchone():
        raise SystemExit("Couldn't find the %s board from %s." % (league.upper(), board_ts))
    picks = []
    for c in codes:
        r = con.execute("SELECT * FROM board_picks WHERE league=? AND board_ts=? AND code=?",
                        (league, ts, str(c))).fetchone()
        if not r:
            raise SystemExit("There's no pick #%s on the latest %s board." % (c, league.upper()))
        picks.append(r)
    return ts, picks


def log_bet(con, cfg, league, codes, entry=None, stake=1.0, price=None, contracts=None, notes=None, now=None,
            board_ts=None):
    now = now or utcnow()
    _, picks = resolve_codes(con, league, codes, board_ts)
    books = {p["book"] for p in picks}
    created = []

    if books & set(cfg.pickem_books):
        if len(books) > 1:
            raise SystemExit("A pick'em entry has to be on one app. Got: %s" % ", ".join(sorted(books)))
        book = picks[0]["book"]
        types = cfg.entries(book)
        if not entry:
            fits = [(breakeven(e["picks"], e["pays"]), eid) for eid, e in types.items() if e["picks"] == len(picks)]
            if not fits:
                raise SystemExit("No %s entry type takes %d picks." % (BOOK_LABELS.get(book, book), len(picks)))
            entry = min(fits)[1]
        if entry not in types:
            raise SystemExit("Unknown entry '%s' for %s. Options: %s" % (entry, book, ", ".join(types)))
        e = types[entry]
        if e["picks"] != len(picks):
            raise SystemExit("%s takes %d picks; you gave %d." % (e["label"], e["picks"], len(picks)))
        if len({p["player_key"] for p in picks}) < len(picks):
            raise SystemExit("The same player appears twice in this entry.")
        be = breakeven(e["picks"], e["pays"])
        cur = con.execute(
            "INSERT INTO bets (placed_at, league, book, entry_type, stake, notes) VALUES (?,?,?,?,?,?)",
            (iso(now), league, book, entry, stake, notes))
        bet_id = cur.lastrowid
        for i, p in enumerate(picks, 1):
            mult = p["multiplier"] or 1.0
            _insert_leg(con, bet_id, i, p, price=None, fair=p["fair_p"],
                        be=be * (1.0 / mult) ** (1.0 / e["picks"]))
        created.append(bet_id)
    else:
        if price is not None and len(picks) > 1:
            raise SystemExit("--price only works when logging one pick at a time.")
        for p in picks:
            if p["book"] == "kalshi":
                # Kalshi buys by the dollar: the stake is what you spend, fee included, and it
                # fills fractional shares. --contracts is the shares Kalshi gave you, when known.
                ask = price if price is not None else p["ask"]
                spent = round(stake, 2)
                shares = round(float(contracts), 2) if contracts else kalshi_shares(spent, ask)
                if shares <= 0:
                    raise SystemExit("Shares have to be more than 0.")
                per = spent / shares                     # what each share cost, fee included
                cur = con.execute(
                    "INSERT INTO bets (placed_at, league, book, entry_type, stake, contracts, notes)"
                    " VALUES (?,?,?,?,?,?,?)", (iso(now), league, "kalshi", "kalshi", spent, shares, notes))
                _insert_leg(con, cur.lastrowid, 1, p, price=per, fair=p["fair_p"], be=per)
            else:
                dec = price if price is not None else p["price"]
                cur = con.execute(
                    "INSERT INTO bets (placed_at, league, book, entry_type, stake, notes) VALUES (?,?,?,?,?,?)",
                    (iso(now), league, p["book"], "straight", stake, notes))
                _insert_leg(con, cur.lastrowid, 1, p, price=dec, fair=p["fair_p"], be=1.0 / dec)
            created.append(cur.lastrowid)
    con.commit()
    return created


def _insert_leg(con, bet_id, leg, p, price, fair, be):
    con.execute(
        "INSERT INTO bet_legs (bet_id, leg, event_id, commence_time, market, player, player_key, side, point,"
        " price, fair_p, breakeven, ge_p, ge_score, flagged, edge) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
        (bet_id, leg, p["event_id"], p["commence_time"], p["market"], p["player"], p["player_key"],
         p["side"], p["point"], price, fair, be, p["ge_p"], p["ge_score"], p["flagged"], p["edge"]))


# ------------------------------------------------------------------ closing lines


def fair_at(con, cfg, league, leg, before_ts):
    """Sharp fair probability for this leg from the latest pull before `before_ts`
    that still had sharp prices for the player. (prob, pull_ts, n_books) or None."""
    sharp = list(cfg.sharp_weights)
    marks = ",".join("?" * len(sharp))
    pulls = con.execute(
        "SELECT DISTINCT pull_id, ts FROM lines WHERE league=? AND event_id=? AND player_key=? AND market=?"
        " AND ts < ? AND book IN (%s) ORDER BY ts DESC, pull_id DESC" % marks,
        [league, leg["event_id"], leg["player_key"], leg["market"], before_ts] + sharp).fetchall()
    th = cfg["thresholds"]
    min_books = 1 if th.get("one_book_ok") else th["min_sharp_books"]
    for pr in pulls:
        rows = con.execute(
            "SELECT * FROM lines WHERE pull_id=? AND event_id=? AND player_key=? AND market=?",
            (pr["pull_id"], leg["event_id"], leg["player_key"], leg["market"])).fetchall()
        qs = sharp_quotes(rows, cfg.sharp_weights).get((leg["event_id"], leg["player_key"], leg["market"]))
        if not qs:
            continue
        c = consensus(qs, leg["point"], leg["market"], cfg.sharp_weights, cfg.max_gap(leg["market"]),
                      cfg["thresholds"].get("max_shift", 0.08))
        if c and c["n"] >= min_books:
            return c[leg["side"]], pr["ts"], c["n"]
    return None


def update_closes(con, cfg, now=None):
    """Fill the closing fair probability for every leg whose game has started."""
    now = now or utcnow()
    legs = con.execute(
        "SELECT l.*, b.league FROM bet_legs l JOIN bets b ON b.id=l.bet_id"
        " WHERE b.deleted_at IS NULL AND l.close_fair_p IS NULL AND l.commence_time <= ?", (iso(now),)).fetchall()
    n = 0
    for leg in legs:
        got = fair_at(con, cfg, leg["league"], leg, leg["commence_time"])
        if got:
            con.execute("UPDATE bet_legs SET close_fair_p=?, close_ts=?, close_n=? WHERE bet_id=? AND leg=?",
                        (got[0], got[1], got[2], leg["bet_id"], leg["leg"]))
            n += 1
    con.commit()
    return n


def legs_needing_close(con, league, now, minutes):
    return con.execute(
        "SELECT l.*, b.league FROM bet_legs l JOIN bets b ON b.id=l.bet_id"
        " WHERE b.league=? AND b.deleted_at IS NULL AND l.commence_time > ? AND l.commence_time <= ?",
        (league, iso(now), iso(now + timedelta(minutes=minutes)))).fetchall()


def capture_close(con, cfg, league, key, minutes=20, fetch=None, log=print, now=None):
    """Pull the markets you bet, for games starting within `minutes`."""
    from .sources import http_get, pull_odds
    now = now or utcnow()
    legs = legs_needing_close(con, league, now, minutes)
    if not legs:
        log("No logged %s bets start in the next %d minutes." % (league.upper(), minutes))
        return None
    events = sorted({l["event_id"] for l in legs})
    markets = sorted({l["market"] for l in legs})
    pid, info = pull_odds(con, cfg, league, key, fetch=fetch or http_get, event_ids=events,
                          markets=markets, kind="close", yes=True, log=log)
    log("Closing snapshot: %d game(s), %d market(s), %s credits used, %s left."
        % (len(events), len(markets), info.get("credits_used"), info.get("credits_remaining")))
    return pid


def watch(con, cfg, league, key, lead=12, poll=60, fetch=None, log=print, sleep=time.sleep):
    """Stay open and take a closing snapshot ~`lead` minutes before each game
    you bet. Ctrl-C to stop."""
    done, said = set(), None
    log("Watching %s games with logged bets. Leave this window open; Ctrl-C to stop." % league.upper())
    try:
        while True:
            now = utcnow()
            future = con.execute(
                "SELECT DISTINCT l.event_id, l.commence_time FROM bet_legs l JOIN bets b ON b.id=l.bet_id"
                " WHERE b.league=? AND b.deleted_at IS NULL AND l.commence_time > ?", (league, iso(now))).fetchall()
            if not future:
                n = update_closes(con, cfg, now)
                log("Every game you bet has started. Closing lines saved for %d leg(s)." % n)
                return
            pending = [f for f in future if f["event_id"] not in done]
            due = [f for f in pending if parse_iso(f["commence_time"]) - now <= timedelta(minutes=lead)]
            if due:
                capture_close(con, cfg, league, key, minutes=lead + 1, fetch=fetch, log=log, now=now)
                done.update(f["event_id"] for f in due)
                said = None
            else:
                if pending:
                    nxt = min(parse_iso(f["commence_time"]) for f in pending)
                    msg = "Next closing snapshot ~%s." % local(nxt - timedelta(minutes=lead)).strftime("%I:%M %p").lstrip("0")
                else:
                    msg = "All closing snapshots taken. Waiting for the last game to start."
                if msg != said:
                    log(msg)
                    said = msg
            sleep(5 if due else poll)
    except KeyboardInterrupt:
        log("\nStopped watching.")


# ------------------------------------------------------------------ results & report


def delete_bet(con, bet_id, now=None):
    """Take a bet out of your record (a duplicate, a mistake). It's hidden from
    Results, grading, closing snapshots and stats, but kept, so it can be restored."""
    b = con.execute("SELECT * FROM bets WHERE id=?", (bet_id,)).fetchone()
    if not b:
        raise SystemExit("No bet #%s." % bet_id)
    if b["deleted_at"]:
        return "Bet #%d was already deleted." % bet_id
    con.execute("UPDATE bets SET deleted_at=? WHERE id=?", (iso(now or utcnow()), bet_id))
    con.commit()
    return "Deleted bet #%d (%s %s, $%.2f). Restore it with: restore %d" % (
        bet_id, BOOK_LABELS.get(b["book"], b["book"]), b["entry_type"] or "", b["stake"] or 0, bet_id)


def edit_bet(con, cfg, bet_id, stake=None, contracts=None, price=None):
    """Correct a logged bet to match what the app actually filled.
    Kalshi: what you spent (stake) and the shares you got, as the order history shows them.
    Others: the stake (and for Fliff the decimal price). A settled bet's payout follows."""
    b = con.execute("SELECT * FROM bets WHERE id=?", (bet_id,)).fetchone()
    if not b:
        raise SystemExit("No bet #%s." % bet_id)
    pay = b["payout"]
    if b["book"] == "kalshi":
        shares = round(float(contracts if contracts is not None else (b["contracts"] or 0)), 2)
        if stake is not None:
            spent = round(float(stake), 2)
        elif price is not None:
            spent = round(shares * float(price), 2)
        else:
            spent = b["stake"]
        if shares <= 0 or not spent or spent <= 0:
            raise SystemExit("Kalshi needs what you spent and the shares you got, both more than 0.")
        per = spent / shares
        if per >= 1:
            raise SystemExit("That works out to %.0f cents a share - Kalshi shares cost under $1. Check the numbers." % (per * 100))
        if b["result"] == "win":
            pay = shares
        elif b["result"] == "push":
            pay = spent
        con.execute("UPDATE bets SET contracts=?, stake=?, payout=? WHERE id=?", (shares, spent, pay, bet_id))
        con.execute("UPDATE bet_legs SET price=?, breakeven=? WHERE bet_id=?", (per, per, bet_id))
        con.commit()
        return "Bet #%d: $%.2f for %.2f shares (%.1f cents each, fee included)." % (bet_id, spent, shares, per * 100)
    new = round(float(stake if stake is not None else b["stake"]), 2)
    if new <= 0:
        raise SystemExit("The stake has to be more than $0.")
    if pay is not None and (b["stake"] or 0) > 0:
        pay = round(pay * new / b["stake"], 2)
    if price is not None and b["book"] not in cfg.pickem_books:
        con.execute("UPDATE bet_legs SET price=?, breakeven=? WHERE bet_id=?", (price, 1.0 / price, bet_id))
        if b["result"] == "win":
            pay = round(new * price, 2)
    con.execute("UPDATE bets SET stake=?, payout=? WHERE id=?", (new, pay, bet_id))
    con.commit()
    return "Bet #%d: stake $%.2f." % (bet_id, new)


def restore_bet(con, bet_id):
    b = con.execute("SELECT * FROM bets WHERE id=?", (bet_id,)).fetchone()
    if not b:
        raise SystemExit("No bet #%s." % bet_id)
    con.execute("UPDATE bets SET deleted_at=NULL WHERE id=?", (bet_id,))
    con.commit()
    return "Restored bet #%d." % bet_id


def set_result(con, cfg, bet_id, result, payout=None, hits=None):
    b = con.execute("SELECT * FROM bets WHERE id=?", (bet_id,)).fetchone()
    if not b:
        raise SystemExit("No bet #%s." % bet_id)
    if payout is None:
        legs = con.execute("SELECT * FROM bet_legs WHERE bet_id=?", (bet_id,)).fetchall()
        if result == "loss":
            payout = 0.0
        elif result == "push":
            payout = b["stake"]
        elif b["book"] in cfg.pickem_books:
            e = cfg.entries(b["book"]).get(b["entry_type"])
            k = hits if hits is not None else (len(legs) if result == "win" else None)
            if k is None or not e:
                raise SystemExit("For a partial pick'em result, pass --hits N or --payout X.")
            payout = b["stake"] * float(e["pays"].get(str(k), 0))
        elif b["book"] == "kalshi":
            payout = (b["contracts"] or 0) * 1.0 if result == "win" else 0.0
        else:
            payout = b["stake"] * (legs[0]["price"] or 0) if result == "win" else 0.0
    con.execute("UPDATE bets SET result=?, payout=? WHERE id=?", (result, payout, bet_id))
    con.commit()
    return payout


def _ge_tag(cfg, p):
    if p is None:
        return "no GE"
    g = cfg["gridiron_edge"]
    return "agree" if p >= g["agree_at"] else ("conflict" if p <= g["conflict_at"] else "neutral")


def list_bets(con, limit=30):
    bets = con.execute("SELECT * FROM bets WHERE deleted_at IS NULL ORDER BY id DESC LIMIT ?", (limit,)).fetchall()
    lines = []
    for b in bets:
        when = local(parse_iso(b["placed_at"])).strftime("%m/%d %I:%M%p")
        res = b["result"] or "open"
        lines.append("#%-4d %s  %-10s %-8s $%-6.2f %s" % (b["id"], when, BOOK_LABELS.get(b["book"], b["book"]),
                                                          b["entry_type"], b["stake"] or 0, res.upper()))
        for l in con.execute("SELECT * FROM bet_legs WHERE bet_id=? ORDER BY leg", (b["id"],)):
            clv = ""
            if l["close_fair_p"] is not None:
                clv = "  CLV %+.1f pts" % ((l["close_fair_p"] - l["fair_p"]) * 100)
            lines.append("        %s %s %g %s  fair %s%s" % (l["player"], l["side"], l["point"],
                                                           market_label(l["market"]), pct(l["fair_p"]), clv))
    return "\n".join(lines) if lines else "No bets logged yet."


def _stats(rows):
    d = [(r["close_fair_p"] - r["fair_p"]) for r in rows]
    beat = [r["close_fair_p"] - r["breakeven"] for r in rows if r["breakeven"]]
    return {"n": len(rows), "avg": sum(d) / len(d), "pos": sum(1 for x in d if x > 0) / len(d),
            "beat": (sum(beat) / len(beat)) if beat else None}


def clv_summary(con, cfg, league=None, now=None):
    """Structured CLV and results numbers, used by the text report and the Bets page."""
    update_closes(con, cfg, now)
    q = ("SELECT l.*, b.league, b.book, b.entry_type, b.placed_at FROM bet_legs l JOIN bets b ON b.id=l.bet_id"
         " WHERE b.deleted_at IS NULL AND l.close_fair_p IS NOT NULL")
    args = []
    if league:
        q += " AND b.league=?"
        args.append(league)
    legs = con.execute(q, args).fetchall()
    s = {"all": _stats(legs) if legs else None, "books": [], "weeks": [], "ge": []}
    groups, weeks, tags = defaultdict(list), defaultdict(list), defaultdict(list)
    for r in legs:
        groups[BOOK_LABELS.get(r["book"], r["book"])].append(r)
        y, w, _ = local(parse_iso(r["placed_at"])).isocalendar()
        weeks["%d-W%02d" % (y, w)].append(r)
        if r["league"] == "nfl":
            tags[_ge_tag(cfg, r["ge_p"])].append(r)
    s["books"] = [(k, _stats(v)) for k, v in sorted(groups.items())]
    s["weeks"] = [(k, _stats(v)) for k, v in sorted(weeks.items())]
    s["ge"] = [(k, _stats(tags[k])) for k in ("agree", "neutral", "conflict", "no GE") if tags.get(k)]
    settled = con.execute("SELECT * FROM bets WHERE deleted_at IS NULL AND result IS NOT NULL" + (" AND league=?" if league else ""),
                          ([league] if league else [])).fetchall()
    staked = sum(b["stake"] or 0 for b in settled)
    paid = sum(b["payout"] or 0 for b in settled)
    s["results"] = {"n": len(settled), "staked": staked, "paid": paid, "net": paid - staked,
                    "roi": (paid - staked) / staked if staked else None}
    return s


def clv_report(con, cfg, league=None, now=None):
    s = clv_summary(con, cfg, league, now)

    def line(title, st):
        return "%-22s n=%-4d avg CLV %+5.1f pts   moved your way %3.0f%%   close vs breakeven %+5.1f pts" % (
            title, st["n"], 100 * st["avg"], 100 * st["pos"], 100 * (st["beat"] or 0))

    out = []
    if not s["all"]:
        out.append("No closed legs yet. CLV fills in once a game you bet has started.")
    else:
        out.append("CLOSING LINE VALUE  (fair probability at close minus at bet)")
        out.append(line("All legs", s["all"]))
        out += [line("book: " + k, v) for k, v in s["books"]]
        out += [line("week of " + k, v) for k, v in s["weeks"]]
        if s["ge"]:
            out.append("")
            out.append("Gridiron Edge as a second opinion (NFL legs):")
            out += [line("GE " + k if k != "no GE" else "no GE read", v) for k, v in s["ge"]]
            out.append("If 'agree' legs don't beat 'conflict' legs over a few hundred bets, GE isn't adding signal.")
    r = s["results"]
    if r["n"]:
        out.append("")
        out.append("RESULTS  %d settled, $%.2f staked, $%.2f back, %+.2f (%+.1f%%)" % (
            r["n"], r["staked"], r["paid"], r["net"], 100 * (r["roi"] or 0)))
        out.append("Win-loss needs ~1,500 bets to mean much. Trust CLV first; keep stakes at $1-5 until it holds.")
    return "\n".join(out)
