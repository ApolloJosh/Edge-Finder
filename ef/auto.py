"""Unattended runs (GitHub Actions calls this every 15 minutes).

Each run decides what is due:
  * a board pull for any group of games whose tip is `offset` minutes away
    (default 90 and 30: once with the day's news, once after lineups post)
  * a closing snapshot for games you bet that start within `close_window`
and does nothing otherwise. Slots are recorded, so a late or repeated run
never pays for the same pull twice. A daily credit cap and a floor on the
month's remaining credits keep it from draining the plan.
"""
from collections import defaultdict
from datetime import timedelta

from . import bets as betlog
from .sources import OddsAPI, http_get, pull_kalshi, pull_odds
from .util import iso, local, parse_iso, utcnow


def _slot_done(con, slot):
    return con.execute("SELECT 1 FROM auto_slots WHERE slot=?", (slot,)).fetchone() is not None


def _mark(con, slot, now):
    con.execute("INSERT OR IGNORE INTO auto_slots (slot, ts) VALUES (?,?)", (slot, iso(now)))
    con.commit()


def credits_today(con, now):
    """Credits spent since local midnight, from the pulls log."""
    start = local(now).replace(hour=0, minute=0, second=0, microsecond=0)
    r = con.execute("SELECT COALESCE(SUM(credits_used),0) AS n FROM pulls WHERE ts >= ?", (iso(start),)).fetchone()
    return int(r["n"] or 0)


def tip_groups(events, minutes=20):
    """Group games whose tips are within `minutes` of the first in the group."""
    groups = []
    for e in sorted(events, key=lambda e: e["commence_time"]):
        t = parse_iso(e["commence_time"])
        if groups and t - groups[-1]["tip"] <= timedelta(minutes=minutes):
            groups[-1]["events"].append(e)
        else:
            groups.append({"tip": t, "events": [e]})
    return groups


def due_board_slots(con, cfg, league, events, now):
    """[(slot_key, group)] for board pulls due now and not yet done."""
    a = cfg["auto"]
    due = []
    for g in tip_groups(events):
        for off in a["board_offsets_min"]:
            slot = "%s:board:%s:%d" % (league, iso(g["tip"]), off)
            starts = g["tip"] - timedelta(minutes=off)
            if starts <= now < g["tip"] - timedelta(minutes=a["min_lead_min"]) and not _slot_done(con, slot):
                due.append((slot, g))
    return due


def run_league(con, cfg, league, key, now=None, fetch=http_get, log=print, aliases=None):
    """One unattended pass for one league. Returns a summary dict."""
    now = now or utcnow()
    a = cfg["auto"]
    lg = cfg.league(league)
    out = {"league": league, "board_pull": False, "close_pulls": 0, "credits": 0, "skipped": None}

    api = OddsAPI(cfg, key, fetch)
    st, evs = api.events(lg["sport_key"], now, now + timedelta(hours=a["horizon_hours"]))
    if st != 200 or not isinstance(evs, list):
        out["skipped"] = "couldn't list games (HTTP %s)" % st
        log("%s: %s" % (league.upper(), out["skipped"]))
        return out
    upcoming = [e for e in evs if e["commence_time"] > iso(now)]
    remaining = api.remaining

    # 1. board pulls
    due = due_board_slots(con, cfg, league, upcoming, now)
    if due:
        ev_ids = sorted({e["id"] for _, g in due for e in g["events"]})
        cost = len(ev_ids) * len(lg["markets"])
        spent = credits_today(con, now)
        if remaining is not None and remaining - cost < a["credit_floor"]:
            out["skipped"] = "only %s credits left this month (floor %d)" % (remaining, a["credit_floor"])
        elif spent + cost > a["daily_credit_cap"]:
            out["skipped"] = "daily cap: %d spent today, this pull needs ~%d (cap %d)" % (spent, cost, a["daily_credit_cap"])
        if out["skipped"]:
            log("%s board pull skipped: %s" % (league.upper(), out["skipped"]))
            for slot, _ in due:
                _mark(con, slot, now)          # don't retry every 15 minutes
        else:
            tips = ", ".join(sorted({local(g["tip"]).strftime("%I:%M%p").lstrip("0") for _, g in due}))
            log("%s board pull: %d game(s) tipping %s" % (league.upper(), len(ev_ids), tips))
            pid, info = pull_odds(con, cfg, league, key, fetch=fetch, event_ids=ev_ids, yes=True,
                                  aliases=aliases, log=log)
            if pid:
                pull_kalshi(con, cfg, league, pid, fetch=fetch, aliases=aliases, log=log)
                out["board_pull"] = True
                out["credits"] += info.get("credits_used") or 0
            for slot, _ in due:
                _mark(con, slot, now)

    # 2. closing snapshots for games you bet
    legs = betlog.legs_needing_close(con, league, now, a["close_window_min"])
    by_event = defaultdict(set)
    for l in legs:
        if not _slot_done(con, "%s:close:%s" % (league, l["event_id"])):
            by_event[l["event_id"]].add(l["market"])
    if by_event:
        markets = sorted({m for ms in by_event.values() for m in ms})
        log("%s closing snapshot: %d game(s)" % (league.upper(), len(by_event)))
        pid, info = pull_odds(con, cfg, league, key, fetch=fetch, event_ids=sorted(by_event),
                              markets=markets, kind="close", yes=True, aliases=aliases, log=log)
        out["close_pulls"] = len(by_event)
        out["credits"] += (info or {}).get("credits_used") or 0
        for ev in by_event:
            _mark(con, "%s:close:%s" % (league, ev), now)

    out["closed_legs"] = betlog.update_closes(con, cfg, now)
    out["games_ahead"] = len(upcoming)
    return out


def prune(con, keep_days=3, now=None):
    """Drop old lines nobody needs. Lines for players you bet are kept forever
    (they are the CLV record); everything else goes after `keep_days`."""
    now = now or utcnow()
    cutoff = iso(now - timedelta(days=keep_days))
    con.execute(
        "DELETE FROM lines WHERE ts < ? AND NOT EXISTS (SELECT 1 FROM bet_legs b WHERE b.event_id=lines.event_id"
        " AND b.player_key=lines.player_key AND b.market=lines.market)", (cutoff,))
    con.execute("DELETE FROM lines WHERE ts < ? AND book='kalshi'", (cutoff,))
    con.execute("DELETE FROM board_picks WHERE board_ts < ?", (cutoff,))
    con.execute("DELETE FROM auto_slots WHERE ts < ?", (iso(now - timedelta(days=10)),))
    con.commit()
    con.execute("VACUUM")
