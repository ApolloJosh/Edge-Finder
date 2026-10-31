"""Full Court Edge: Edge Finder's own NBA projection, a second opinion next to
the sharp books (what Gridiron Edge is for the NFL).

Data: ESPN box scores, stored one row per player per game (nba_box). Every
scheduled run fills in a few more days, newest first, so recent form arrives
first and last season fills in behind it. Nothing here costs Odds API credits.

Model (v1, deliberately simple and transparent):
  * per-minute rate for each stat: recent games count more (half-life 10
    games); last season's games count half
  * minutes: recent games, half-life 5 games
  * opponent: how much of that stat the opponent allows per game against the
    league average this season, pulled halfway (or more, early on) toward
    average, and kept within +/-15%
  * spread: the player's own game-to-game spread blended with the board's
    model spread for that stat
  * P(over a line) from a normal with a continuity correction, like the board

What it doesn't know: injuries and who's sitting tonight (a teammate out means
more shots for everyone else), rest, blowouts, role changes. The sharp books
do know those, which is why it's a second opinion and its weight in the
overall score is small until Results shows it helps.
"""
import math
from datetime import date, datetime, timedelta

from .fair import cond_over, stat_sigma
from .sources import get_json, http_get
from .util import iso, local, player_key, utcnow

BASE = "https://site.api.espn.com/apis/site/v2/sports/basketball/nba/"
STATS = ("points", "rebounds", "assists", "threes", "steals", "blocks", "turnovers")
MARKET_PARTS = {
    "player_points": ["points"], "player_rebounds": ["rebounds"], "player_assists": ["assists"],
    "player_threes": ["threes"], "player_blocks": ["blocks"], "player_steals": ["steals"],
    "player_turnovers": ["turnovers"],
    "player_points_rebounds_assists": ["points", "rebounds", "assists"],
    "player_points_rebounds": ["points", "rebounds"], "player_points_assists": ["points", "assists"],
    "player_rebounds_assists": ["rebounds", "assists"],
}
LABELS = {"MIN": "minutes", "PTS": "points", "REB": "rebounds", "AST": "assists", "3PT": "threes",
          "STL": "steals", "BLK": "blocks", "TO": "turnovers"}
SEASON_START_MONTH = 10        # a game from October on belongs to the season starting that year

SCHEMA = """
CREATE TABLE IF NOT EXISTS nba_box (
  event_id TEXT NOT NULL, game_date TEXT NOT NULL, season INTEGER NOT NULL,
  team TEXT, opp TEXT, home INTEGER,
  player TEXT, player_key TEXT NOT NULL, starter INTEGER,
  minutes REAL, points REAL, rebounds REAL, assists REAL, threes REAL,
  steals REAL, blocks REAL, turnovers REAL,
  PRIMARY KEY (event_id, player_key)
);
CREATE INDEX IF NOT EXISTS nba_box_player ON nba_box (player_key, game_date);
CREATE INDEX IF NOT EXISTS nba_box_opp ON nba_box (season, opp);
CREATE TABLE IF NOT EXISTS nba_days (day TEXT PRIMARY KEY, games INTEGER, fetched_at TEXT);
CREATE TABLE IF NOT EXISTS nba_teams (abbr TEXT PRIMARY KEY, name TEXT);
"""


def ensure(con):
    con.executescript(SCHEMA)
    have = {r[1] for r in con.execute("PRAGMA table_info(nba_box)")}
    if "stype" not in have:          # season type: 1 preseason, 2 regular season, 3 playoffs, 5 play-in
        con.execute("ALTER TABLE nba_box ADD COLUMN stype INTEGER")
        con.commit()


def _stype(obj):
    try:
        return int((obj or {}).get("season", {}).get("type"))
    except (TypeError, ValueError):
        return None


def season_of(day):
    d = day if isinstance(day, date) else datetime.strptime(day[:10], "%Y-%m-%d").date()
    return d.year if d.month >= SEASON_START_MONTH else d.year - 1


def _num(v):
    try:
        s = str(v).strip()
        if ":" in s:                       # "34:12" minutes
            m, sec = s.split(":", 1)
            return float(m) + float(sec) / 60
        return float(s)
    except (TypeError, ValueError):
        return None


def parse_summary(summary, aliases=None):
    """[(row dict)] for every player who played, from an ESPN NBA game summary."""
    try:
        comp = summary["header"]["competitions"][0]
        st = comp["status"]["type"]
        if not (st.get("completed") or st.get("state") == "post"):
            return None                      # not final yet
        sides = {c["team"]["id"]: (c["team"].get("abbreviation"), c.get("homeAway") == "home")
                 for c in comp["competitors"]}
    except (KeyError, IndexError, TypeError):
        return None
    teams = [t for t in (summary.get("boxscore") or {}).get("players") or []]
    abbr = {}
    for t in teams:
        tid = (t.get("team") or {}).get("id")
        abbr[tid] = (t.get("team") or {}).get("abbreviation") or sides.get(tid, (None,))[0]
    out = []
    for t in teams:
        tid = (t.get("team") or {}).get("id")
        opp = next((a for k, a in abbr.items() if k != tid), None)
        home = sides.get(tid, (None, False))[1]
        for group in t.get("statistics") or []:
            keys = group.get("keys") or []
            labels = group.get("labels") or []
            names = []
            for i in range(max(len(keys), len(labels))):
                k = keys[i] if i < len(keys) else ""
                lab = labels[i] if i < len(labels) else ""
                if k.startswith("threePointFieldGoals") or lab == "3PT":
                    names.append("threes")
                elif k in ("minutes",) or lab == "MIN":
                    names.append("minutes")
                elif k in STATS:
                    names.append(k)
                else:
                    names.append(LABELS.get(lab))
            for a in group.get("athletes") or []:
                name = (a.get("athlete") or {}).get("displayName")
                vals = a.get("stats") or []
                if not name or a.get("didNotPlay") or not vals:
                    continue
                rec = {"player": name, "player_key": player_key(name, aliases), "team": abbr.get(tid), "opp": opp,
                       "home": 1 if home else 0, "starter": 1 if a.get("starter") else 0}
                for n, v in zip(names, vals):
                    if not n:
                        continue
                    rec[n] = _num(str(v).split("-")[0]) if n == "threes" else _num(v)
                if (rec.get("minutes") or 0) <= 0:
                    continue
                out.append(rec)
    return out


def _get(url, fetch):
    """get_json that never raises: a timeout or network error is just a failed read."""
    try:
        return get_json(url, fetch)
    except (Exception, SystemExit) as e:          # http_get raises SystemExit on network errors
        return "error: %s" % str(e)[:60], {}, None


def sync(con, max_requests=120, today=None, fetch=http_get, aliases=None, back_to="2025-10-21", log=print):
    """Fill in box scores, newest days first, within a request budget.
    A day is done once all its games were final when fetched."""
    ensure(con)
    today = today or local(utcnow()).date()
    done = {r[0] for r in con.execute("SELECT day FROM nba_days")}
    used, days_done, games, fails = 0, 0, 0, []
    # Games stored before season types were kept: look their days up again (one request a day).
    for (day,) in con.execute("SELECT DISTINCT replace(game_date, '-', '') FROM nba_box WHERE stype IS NULL "
                              "ORDER BY 1 DESC").fetchall():
        if used >= max_requests // 4:
            break
        st, _, data = _get(BASE + "scoreboard?dates=" + day, fetch)
        used += 1
        for e in (data or {}).get("events") or []:
            con.execute("UPDATE nba_box SET stype=? WHERE event_id=? AND stype IS NULL", (_stype(e) or 0, str(e.get("id"))))
    con.commit()
    d = today - timedelta(days=1)
    stop = datetime.strptime(back_to, "%Y-%m-%d").date()
    while d >= stop and used < max_requests:
        key = d.strftime("%Y%m%d")
        if key in done:
            d -= timedelta(days=1)
            continue
        st, _, data = _get(BASE + "scoreboard?dates=" + key, fetch)
        used += 1
        if st != 200 or data is None:
            fails.append("%s: HTTP %s" % (key, st))     # skip the day; the next run tries it again
            if len(fails) >= 3:
                break
            d -= timedelta(days=1)
            continue
        events = data.get("events") or []
        complete = True
        for e in events:
            if used >= max_requests:
                complete = False
                break
            eid = str(e.get("id"))
            if con.execute("SELECT 1 FROM nba_box WHERE event_id=? LIMIT 1", (eid,)).fetchone():
                con.execute("UPDATE nba_box SET stype=? WHERE event_id=? AND stype IS NULL", (_stype(e) or 0, eid))
                continue
            st2, _, summ = _get(BASE + "summary?event=" + eid, fetch)
            used += 1
            rows = parse_summary(summ, aliases) if st2 == 200 and summ else None
            if rows is None:
                complete = False
                continue
            try:
                for c in summ["header"]["competitions"][0]["competitors"]:
                    con.execute("INSERT OR REPLACE INTO nba_teams (abbr, name) VALUES (?,?)",
                                (c["team"].get("abbreviation"), c["team"].get("displayName")))
            except (KeyError, IndexError, TypeError):
                pass
            for r in rows:
                con.execute(
                    "INSERT OR REPLACE INTO nba_box (event_id, game_date, season, team, opp, home, player, player_key,"
                    " starter, minutes, points, rebounds, assists, threes, steals, blocks, turnovers, stype)"
                    " VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                    (eid, d.isoformat(), season_of(d), r["team"], r["opp"], r["home"], r["player"], r["player_key"],
                     r["starter"], r.get("minutes"), r.get("points"), r.get("rebounds"), r.get("assists"),
                     r.get("threes"), r.get("steals"), r.get("blocks"), r.get("turnovers"),
                     _stype(summ.get("header")) or _stype(e) or 0))
            games += 1
        if complete:
            con.execute("INSERT OR REPLACE INTO nba_days (day, games, fetched_at) VALUES (?,?,?)",
                        (key, len(events), iso(utcnow())))
            days_done += 1
        con.commit()
        d -= timedelta(days=1)
    if games or days_done or fails:
        log("Full Court Edge: %d new game(s), %d day(s) complete, %d ESPN requests%s." % (
            games, days_done, used, ("; couldn't read " + ", ".join(fails)) if fails else ""))
    return {"games": games, "days": days_done, "requests": used, "failed": fails}


# ------------------------------------------------------------------ the model


def _weights(n, half_life):
    return [0.5 ** (i / half_life) for i in range(n)]


class Model:
    """Projections for one slate. Build once per board."""

    def __init__(self, con, today=None, cfg=None):
        ensure(con)
        self.con = con
        self.today = today or local(utcnow()).date()
        self.season = season_of(self.today)
        self.cfg = (cfg or {}).get("full_court_edge", {}) if cfg else {}
        self.uncertainty = self.cfg.get("projection_error", 0.15)
        self._opp = None
        self._keys = None

    def ready(self):
        return self.con.execute("SELECT COUNT(*) FROM nba_box WHERE season=?", (self.season,)).fetchone()[0] > 0

    # league-average allowed per team-game, and each team's allowed per game, this season
    def _opp_factors(self):
        if self._opp is not None:
            return self._opp
        out = {}
        rows = self.con.execute(
            "SELECT opp, event_id, SUM(points) p, SUM(rebounds) r, SUM(assists) a, SUM(threes) t, SUM(steals) s,"
            " SUM(blocks) b, SUM(turnovers) o FROM nba_box WHERE season=? AND game_date < ? AND COALESCE(NULLIF(stype, 0), 2) IN (2, 3, 5)"
            " GROUP BY opp, event_id",
            (self.season, self.today.isoformat())).fetchall()
        if rows:
            stats = ("points", "rebounds", "assists", "threes", "steals", "blocks", "turnovers")
            league = {s: sum((r[i + 2] or 0) for r in rows) / len(rows) for i, s in enumerate(stats)}
            by = {}
            for r in rows:
                by.setdefault(r[0], []).append(r)
            for team, rs in by.items():
                n = len(rs)
                shrink = n / (n + 15.0)            # few games: stay near average
                f = {}
                for i, s in enumerate(stats):
                    allowed = sum((r[i + 2] or 0) for r in rs) / n
                    raw = allowed / league[s] if league[s] else 1.0
                    f[s] = max(0.85, min(1.15, 1 + 0.5 * shrink * (raw - 1)))
                out[team] = f
        self._opp = out
        return out

    def _resolve(self, pk):
        """Board player key -> box-score player key (exact, else unique last name + first letter)."""
        if self.con.execute("SELECT 1 FROM nba_box WHERE player_key=? LIMIT 1", (pk,)).fetchone():
            return pk
        if not pk:
            return None
        if self._keys is None:
            self._keys = [r[0] for r in self.con.execute(
                "SELECT DISTINCT player_key FROM nba_box WHERE season>=?", (self.season - 1,))]
        last, first = pk.split()[-1], pk[0]
        near = [k for k in self._keys if k.split() and k.split()[-1] == last and k[0] == first]
        return near[0] if len(near) == 1 else None

    def opponent(self, pk, home_name, away_name):
        """Tonight's opponent's abbreviation, from the player's latest team."""
        key = self._resolve(pk)
        if not key:
            return None
        r = self.con.execute("SELECT team FROM nba_box WHERE player_key=? ORDER BY game_date DESC LIMIT 1", (key,)).fetchone()
        names = {n: a for a, n in self.con.execute("SELECT abbr, name FROM nba_teams")}
        h, a = names.get(home_name), names.get(away_name)
        if not r or not h or not a:
            return None
        return a if r["team"] == h else (h if r["team"] == a else None)

    def project(self, pk, market, opp_team=None):
        """{'mean', 'sd', 'games', 'minutes'} or None when there isn't enough to go on."""
        parts = MARKET_PARTS.get(market)
        key = self._resolve(pk)
        if not parts or not key:
            return None
        rows = self.con.execute(
            "SELECT * FROM nba_box WHERE player_key=? AND game_date < ? AND minutes > 0 AND COALESCE(NULLIF(stype, 0), 2) IN (2, 3, 5)"
            " ORDER BY game_date DESC LIMIT 40", (key, self.today.isoformat())).fetchall()
        cur = [r for r in rows if r["season"] == self.season]
        if len(rows) < 3 or (not cur and len(rows) < 8):
            return None
        # weights: recency, and last season counts half
        w = [wt * (1.0 if r["season"] == self.season else 0.5) for wt, r in zip(_weights(len(rows), 10), rows)]
        mins_rows = cur[:12] if len(cur) >= 3 else rows[:12]
        med = sorted(r["minutes"] for r in mins_rows)[len(mins_rows) // 2]
        mins_rows = [r for r in mins_rows if r["minutes"] >= 0.5 * med] or mins_rows   # drop early exits
        wm = _weights(len(mins_rows), 5)
        minutes = sum(x * r["minutes"] for x, r in zip(wm, mins_rows)) / sum(wm)
        opp = self._opp_factors().get(opp_team) if opp_team else None
        mean = 0.0
        totals = []
        for s in parts:
            num = sum(x * (r[s] or 0) for x, r in zip(w, rows))
            den = sum(x * r["minutes"] for x, r in zip(w, rows))
            rate = num / den if den else 0.0
            mean += rate * minutes * (opp[s] if opp else 1.0)
        for r in rows[:20]:
            totals.append(sum((r[s] or 0) for s in parts) * (minutes / r["minutes"] if r["minutes"] else 1.0))
        emp = _sd(totals) if len(totals) >= 5 else None
        model_sd = stat_sigma(market, max(mean, 0.5))
        game_sd = max(math.sqrt(0.5 * emp ** 2 + 0.5 * model_sd ** 2) if emp else model_sd, 0.8 * model_sd)
        # Plus the projection's own error: it doesn't know tonight's role, minutes or matchup the way the market does.
        sd = math.sqrt(game_sd ** 2 + (self.uncertainty * mean) ** 2)
        return {"mean": mean, "sd": sd, "games": len(cur), "minutes": minutes, "key": key}

    def prob(self, proj, line, side):
        if not proj:
            return None
        p_over = cond_over(proj["mean"], proj["sd"], float(line))
        return p_over if side == "over" else 1 - p_over


def _sd(xs):
    m = sum(xs) / len(xs)
    return math.sqrt(sum((x - m) ** 2 for x in xs) / (len(xs) - 1))


def tag(cfg, p):
    g = cfg["gridiron_edge"]
    if p is None:
        return None
    return "agree" if p >= g["agree_at"] else ("conflict" if p <= g["conflict_at"] else "neutral")
