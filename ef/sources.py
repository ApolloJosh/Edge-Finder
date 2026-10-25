"""Collectors: The Odds API (PrizePicks, Underdog, Fliff and the sharp books in
one feed) and Kalshi's public market-data API.

Read-only, a handful of requests per pull. Nothing here can place a bet.
"""
import json
import math
import ssl
import time
import urllib.error
import urllib.parse
import urllib.request
from datetime import timedelta

from .util import iso, player_key, utcnow

UA = "EdgeFinder/1.0 (personal research tool)"


def _ssl_context():
    try:
        import certifi  # optional; helps python.org installs on macOS
        return ssl.create_default_context(cafile=certifi.where())
    except Exception:
        return ssl.create_default_context()


def http_get(url, timeout=30):
    """GET a URL. Returns (status, headers, body_bytes). Never raises for HTTP errors."""
    req = urllib.request.Request(url, headers={"User-Agent": UA, "Accept": "application/json"})
    try:
        with urllib.request.urlopen(req, timeout=timeout, context=_ssl_context()) as r:
            return r.status, {k.lower(): v for k, v in r.headers.items()}, r.read()
    except urllib.error.HTTPError as e:
        return e.code, {k.lower(): v for k, v in (e.headers or {}).items()}, e.read() or b""
    except urllib.error.URLError as e:
        reason = getattr(e, "reason", e)
        if isinstance(reason, ssl.SSLError) or "CERTIFICATE" in str(reason).upper():
            raise SystemExit(
                "Python can't verify SSL certificates on this Mac.\n"
                "Fix: open Finder > Applications > Python 3.x and double-click\n"
                "'Install Certificates.command', then run this again.\n(%s)" % reason
            )
        raise SystemExit("Network error reaching %s: %s" % (url.split("?")[0], reason))


def get_json(url, fetch, retries=2):
    for attempt in range(retries + 1):
        status, headers, body = fetch(url)
        if status == 429 and attempt < retries:
            time.sleep(1.5 * (attempt + 1))
            continue
        try:
            data = json.loads(body.decode("utf-8")) if body else None
        except ValueError:
            data = None
        return status, headers, data
    return status, headers, None


# ------------------------------------------------------------------ Odds API


class OddsAPI:
    def __init__(self, cfg, key, fetch=http_get):
        self.base = cfg["odds_api"]["base"].rstrip("/")
        self.key = key
        self.fetch = fetch
        self.remaining = None
        self.used = 0

    def _url(self, path, **params):
        params["apiKey"] = self.key
        return "%s%s?%s" % (self.base, path, urllib.parse.urlencode(params))

    def _get(self, path, **params):
        url = self._url(path, **params)
        status, headers, data = get_json(url, self.fetch)
        if "x-requests-remaining" in headers:
            try:
                self.remaining = int(float(headers["x-requests-remaining"]))
            except ValueError:
                pass
        if "x-requests-last" in headers:
            try:
                self.used += int(float(headers["x-requests-last"]))
            except ValueError:
                pass
        if status == 401:
            raise SystemExit("The Odds API rejected the key (401). Check ODDS_API_KEY in .env.")
        if status == 429 and isinstance(data, dict) and "quota" in json.dumps(data).lower():
            raise SystemExit("Out of Odds API credits for this month.")
        return status, data

    def sports(self):
        return self._get("/sports")

    def events(self, sport, start, end):
        return self._get(
            "/sports/%s/events" % sport,
            commenceTimeFrom=iso(start),
            commenceTimeTo=iso(end),
        )

    def event_odds(self, sport, event_id, books, markets):
        return self._get(
            "/sports/%s/events/%s/odds" % (sport, event_id),
            bookmakers=",".join(books),
            markets=",".join(markets),
            oddsFormat="decimal",
            includeMultipliers="true",
        )


def estimate_cost(n_events, n_markets, n_books):
    return n_events * n_markets * max(1, math.ceil(n_books / 10.0))


def new_pull(con, league, kind, note=None):
    cur = con.execute(
        "INSERT INTO pulls (ts, league, kind, note) VALUES (?,?,?,?)",
        (iso(utcnow()), league, kind, note),
    )
    return cur.lastrowid


def _store_event(con, league, ev):
    con.execute(
        "INSERT OR REPLACE INTO events (event_id, league, commence_time, home, away) VALUES (?,?,?,?,?)",
        (ev["id"], league, ev["commence_time"], ev.get("home_team"), ev.get("away_team")),
    )


def _store_odds(con, pull_id, ts, league, data, aliases):
    n = 0
    for bk in data.get("bookmakers") or []:
        book = bk.get("key")
        for mk in bk.get("markets") or []:
            market = mk.get("key")
            for o in mk.get("outcomes") or []:
                player = o.get("description")
                side = (o.get("name") or "").lower()
                if side in ("yes",):
                    side = "over"
                if side in ("no",):
                    side = "under"
                if not player or side not in ("over", "under") or o.get("point") is None:
                    continue
                con.execute(
                    "INSERT INTO lines (pull_id, ts, league, event_id, book, market, player, player_key,"
                    " side, point, price, multiplier) VALUES (?,?,?,?,?,?,?,?,?,?,?,?)",
                    (pull_id, ts, league, data.get("id"), book, market, player,
                     player_key(player, aliases), side, float(o["point"]),
                     float(o["price"]) if o.get("price") else None,
                     float(o["multiplier"]) if o.get("multiplier") else None),
                )
                n += 1
    return n


def pull_odds(con, cfg, league, key, fetch=http_get, hours=None, yes=False,
              event_ids=None, markets=None, kind="board", aliases=None, log=print, ask=input):
    """Pull player props for upcoming games. Returns (pull_id, summary dict)."""
    lg = cfg.league(league)
    sport = lg["sport_key"]
    markets = list(markets or lg["markets"])
    books = cfg.all_books()
    api = OddsAPI(cfg, key, fetch)

    now = utcnow()
    hours = hours or cfg["odds_api"]["hours_ahead"]
    status, evs = api.events(sport, now - timedelta(hours=6), now + timedelta(hours=hours))
    if status != 200 or not isinstance(evs, list):
        raise SystemExit("Couldn't list %s games from The Odds API (HTTP %s): %s" % (league.upper(), status, evs))
    upcoming = [e for e in evs if e["commence_time"] > iso(now)]
    if event_ids is not None:
        upcoming = [e for e in upcoming if e["id"] in set(event_ids)]
    if not upcoming:
        log("No upcoming %s games in the next %d hours." % (league.upper(), hours))
        return None, {"events": 0, "lines": 0}

    if api.remaining is not None and api.remaining < len(upcoming):
        raise SystemExit("Out of Odds API credits (%s left this month)." % api.remaining)
    cost = estimate_cost(len(upcoming), len(markets), len(books))
    budget = cfg["odds_api"]["budget_per_pull"]
    log("%s: %d games x %d markets -> up to %d Odds API credits." % (league.upper(), len(upcoming), len(markets), cost))
    if cost > budget and not yes:
        ans = ask("That's over your %d-credit budget per pull. Go ahead? [y/N] " % budget)
        if ans.strip().lower() not in ("y", "yes"):
            raise SystemExit("Stopped before spending credits.")

    pull_id = new_pull(con, league, kind)
    ts = iso(utcnow())
    total = 0
    for ev in upcoming:
        _store_event(con, league, ev)
        st, data = api.event_odds(sport, ev["id"], books, markets)
        if st != 200 or not isinstance(data, dict):
            log("  %s @ %s: no props (HTTP %s)" % (ev.get("away_team"), ev.get("home_team"), st))
            continue
        total += _store_odds(con, pull_id, ts, league, data, aliases)
    con.execute(
        "UPDATE pulls SET credits_used=?, credits_remaining=?, events=? WHERE id=?",
        (api.used, api.remaining, len(upcoming), pull_id),
    )
    con.commit()
    return pull_id, {"events": len(upcoming), "lines": total, "credits_used": api.used,
                     "credits_remaining": api.remaining}


# ------------------------------------------------------------------ Kalshi

_MONTHS = {m: i for i, m in enumerate(
    ["JAN", "FEB", "MAR", "APR", "MAY", "JUN", "JUL", "AUG", "SEP", "OCT", "NOV", "DEC"], 1)}


def kalshi_game_date(event_ticker):
    """'KXNBAPTS-26OCT24HOUATL' -> '2026-10-24'."""
    try:
        part = event_ticker.split("-")[1]
        yy, mon, dd = int(part[0:2]), _MONTHS[part[2:5]], int(part[5:7])
        return "%04d-%02d-%02d" % (2000 + yy, mon, dd)
    except (IndexError, KeyError, ValueError):
        return None


def _dollars(m, key_dollars, key_cents):
    v = m.get(key_dollars)
    if v not in (None, ""):
        return float(v)
    v = m.get(key_cents)
    if v not in (None, ""):
        return float(v) / 100.0
    return None


def _num(v):
    try:
        return float(v)
    except (TypeError, ValueError):
        return None


def pull_kalshi(con, cfg, league, pull_id, fetch=http_get, aliases=None, log=print):
    """Store open Kalshi player-prop ladders ('X+ points') as over/under rows."""
    base = cfg["kalshi"]["base"].rstrip("/")
    series_map = cfg.league(league).get("kalshi_series", {})
    ts = iso(utcnow())
    n = 0
    for series, market in series_map.items():
        cursor, pages = None, 0
        while pages < 10:
            params = {"series_ticker": series, "status": "open", "limit": 1000}
            if cursor:
                params["cursor"] = cursor
            url = "%s/markets?%s" % (base, urllib.parse.urlencode(params))
            status, _, data = get_json(url, fetch)
            if status != 200 or not isinstance(data, dict):
                log("  Kalshi %s: HTTP %s" % (series, status))
                break
            for m in data.get("markets") or []:
                if m.get("strike_type") != "greater" or m.get("floor_strike") is None:
                    continue
                name = (m.get("yes_sub_title") or m.get("title") or "").split(":")[0].strip()
                if not name:
                    continue
                pk = player_key(name, aliases)
                line = float(m["floor_strike"])
                gdate = kalshi_game_date(m.get("event_ticker", ""))
                yes_ask = _dollars(m, "yes_ask_dollars", "yes_ask")
                yes_bid = _dollars(m, "yes_bid_dollars", "yes_bid")
                no_ask = _dollars(m, "no_ask_dollars", "no_ask")
                if no_ask is None and yes_bid is not None:
                    no_ask = 1 - yes_bid
                rows = [
                    ("over", yes_ask, _num(m.get("yes_ask_size_fp"))),
                    ("under", no_ask, _num(m.get("yes_bid_size_fp"))),
                ]
                for side, ask_px, size in rows:
                    if ask_px is None or not (0 < ask_px < 1):
                        continue
                    con.execute(
                        "INSERT INTO lines (pull_id, ts, league, event_id, book, market, player, player_key,"
                        " side, point, price, ask, size, ref, game_date) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                        (pull_id, ts, league, None, "kalshi", market, name, pk, side, line,
                         1.0 / ask_px, ask_px, size, m.get("ticker"), gdate),
                    )
                    n += 1
            cursor = data.get("cursor")
            pages += 1
            if not cursor:
                break
    con.commit()
    return n
