"""Grade bets automatically from ESPN box scores once their games are final.

Each leg gets the player's actual number and a hit / miss / push / void. A bet
is settled when every leg is graded:
  * straight (Fliff) and Kalshi: win, loss, or push (a void counts as a push)
  * pick'em: paid from the entry's table by how many legs hit; an entry with a
    voided or pushed leg is left for you, because each app re-prices those.
A leg is only voided when ESPN lists the player as not playing. A player who
isn't in the box score at all (inactive, or a name ESPN spells differently) is
marked "review" and the bet is left for you rather than guessed.
Bets you've already settled by hand are never touched.
"""
from datetime import timedelta

from .sources import get_json, http_get
from .util import local, parse_iso, player_key, short_team, utcnow

SPORT = {"nba": "basketball/nba", "nfl": "football/nfl"}
BASE = "https://site.api.espn.com/apis/site/v2/sports/%s/%s"

# Which box-score numbers make up each market.
PARTS = {
    "player_points": ["points"],
    "player_rebounds": ["rebounds"],
    "player_assists": ["assists"],
    "player_threes": ["threes"],
    "player_blocks": ["blocks"],
    "player_steals": ["steals"],
    "player_turnovers": ["turnovers"],
    "player_points_rebounds_assists": ["points", "rebounds", "assists"],
    "player_points_rebounds": ["points", "rebounds"],
    "player_points_assists": ["points", "assists"],
    "player_rebounds_assists": ["rebounds", "assists"],
    "player_pass_yds": ["passingYards"],
    "player_pass_attempts": ["passingAttempts"],
    "player_pass_completions": ["completions"],
    "player_pass_rush_yds": ["passingYards", "rushingYards"],
    "player_rush_yds": ["rushingYards"],
    "player_rush_attempts": ["rushingAttempts"],
    "player_rush_reception_yds": ["rushingYards", "receivingYards"],
    "player_reception_yds": ["receivingYards"],
    "player_receptions": ["receptions"],
}
FINAL_AFTER = {"nba": 2.5, "nfl": 3.25}   # hours after tip before it's worth checking


def _num(v):
    try:
        return float(str(v).strip())
    except (TypeError, ValueError):
        return None


def parse_box(summary, aliases=None):
    """(is_final, {player_key: {stat: value}}, set(player_keys who didn't play))."""
    try:
        status = summary["header"]["competitions"][0]["status"]["type"]
        final = bool(status.get("completed")) or status.get("state") == "post"
    except (KeyError, IndexError, TypeError):
        final = False
    stats, dnp = {}, set()
    for team in (summary.get("boxscore") or {}).get("players") or []:
        for group in team.get("statistics") or []:
            keys = group.get("keys") or group.get("labels") or []
            for a in group.get("athletes") or []:
                name = (a.get("athlete") or {}).get("displayName")
                if not name:
                    continue
                pk = player_key(name, aliases)
                vals = a.get("stats") or []
                if a.get("didNotPlay") or not vals:
                    if pk not in stats:
                        dnp.add(pk)
                    continue
                dnp.discard(pk)
                rec = stats.setdefault(pk, {})
                for k, v in zip(keys, vals):
                    if k in ("threePointFieldGoalsMade-threePointFieldGoalsAttempted", "3PT"):
                        rec["threes"] = _num(str(v).split("-")[0])
                    elif k == "completions/passingAttempts":
                        c, _, att = str(v).partition("/")
                        rec["completions"], rec["passingAttempts"] = _num(c), _num(att)
                    elif k in ("PTS",):
                        rec["points"] = _num(v)
                    elif k in ("REB",):
                        rec["rebounds"] = _num(v)
                    elif k in ("AST",):
                        rec["assists"] = _num(v)
                    else:
                        n = _num(v)
                        if n is not None:
                            rec[k] = n
    return final, stats, dnp


def leg_value(market, rec):
    """The player's number for a market. A player in the box score with no line
    in a category (a receiver who never ran the ball) had zero there."""
    parts = PARTS.get(market)
    if not parts or rec is None:
        return None
    return sum(rec.get(p) or 0.0 for p in parts)


def find_player(pk, stats, dnp):
    """Match a bet's player to the box score: exact key, else a unique
    same-last-name, same-first-letter player ('herb jones' ~ 'herbert jones')."""
    if pk in stats or pk in dnp:
        return pk
    if not pk:
        return None
    last, first = pk.split()[-1], pk[0]
    near = [k for k in list(stats) + list(dnp) if k.split() and k.split()[-1] == last and k[0] == first]
    return near[0] if len(near) == 1 else None


def leg_result(value, point, side):
    if value is None:
        return None
    if abs(value - point) < 1e-9:
        return "push"
    over = value > point
    return "hit" if over == (side == "over") else "miss"


class ESPN:
    def __init__(self, fetch=http_get):
        self.fetch = fetch
        self.boards, self.summaries = {}, {}

    def scoreboard(self, league, day):
        key = (league, day)
        if key not in self.boards:
            st, _, data = get_json((BASE % (SPORT[league], "scoreboard")) + "?dates=" + day, self.fetch)
            self.boards[key] = (data or {}).get("events") or [] if st == 200 else []
        return self.boards[key]

    def find_event(self, league, home, away, commence):
        """ESPN event id for an Odds API game, matched on team nicknames and date."""
        want = {short_team(home).lower(), short_team(away).lower()}
        start = parse_iso(commence)
        for delta in (0, -1, 1):
            day = local(start + timedelta(days=delta)).strftime("%Y%m%d")
            for e in self.scoreboard(league, day):
                try:
                    names = {(c["team"].get("name") or short_team(c["team"]["displayName"])).lower()
                             for c in e["competitions"][0]["competitors"]}
                except (KeyError, IndexError):
                    continue
                if names == want:
                    return e["id"]
        return None

    def summary(self, league, event_id):
        if event_id not in self.summaries:
            st, _, data = get_json((BASE % (SPORT[league], "summary")) + "?event=" + str(event_id), self.fetch)
            self.summaries[event_id] = data if st == 200 else None
        return self.summaries[event_id]


def grade_open_bets(con, cfg, now=None, fetch=http_get, aliases=None, log=print):
    """Grade legs whose games are done, then settle bets whose legs are all graded.
    Returns the number of bets settled."""
    from .bets import set_result
    now = now or utcnow()
    espn = ESPN(fetch)
    legs = con.execute(
        "SELECT l.*, b.league, e.home, e.away FROM bet_legs l JOIN bets b ON b.id=l.bet_id"
        " LEFT JOIN events e ON e.event_id=l.event_id"
        " WHERE b.result IS NULL AND b.deleted_at IS NULL AND l.leg_result IS NULL AND l.commence_time IS NOT NULL").fetchall()
    boxes = {}
    for l in legs:
        if parse_iso(l["commence_time"]) + timedelta(hours=FINAL_AFTER.get(l["league"], 3)) > now:
            continue
        if not l["home"]:
            continue
        gkey = (l["league"], l["event_id"])
        if gkey not in boxes:
            eid = espn.find_event(l["league"], l["home"], l["away"], l["commence_time"])
            summ = espn.summary(l["league"], eid) if eid else None
            boxes[gkey] = parse_box(summ, aliases) if summ else None
        box = boxes[gkey]
        if not box or not box[0]:
            continue
        final, stats, dnp = box
        pk = find_player(l["player_key"], stats, dnp)
        if pk is None:
            res, val = "review", None
        elif pk in dnp and pk not in stats:
            res, val = "void", None
        else:
            val = leg_value(l["market"], stats.get(pk))
            res = leg_result(val, l["point"], l["side"])
            if res is None:
                continue
        con.execute("UPDATE bet_legs SET actual=?, leg_result=? WHERE bet_id=? AND leg=?",
                    (val, res, l["bet_id"], l["leg"]))
    con.commit()

    settled = 0
    for b in con.execute("SELECT * FROM bets WHERE result IS NULL AND deleted_at IS NULL").fetchall():
        ls = con.execute("SELECT * FROM bet_legs WHERE bet_id=?", (b["id"],)).fetchall()
        if not ls or any(l["leg_result"] is None for l in ls):
            continue
        results = [l["leg_result"] for l in ls]
        if "review" in results:
            continue              # a player we couldn't find - yours to settle
        if b["book"] in cfg.pickem_books:
            if any(r in ("void", "push") for r in results):
                continue          # apps re-price these; leave for a manual result
            hits = results.count("hit")
            outcome = "win" if hits == len(ls) else ("partial" if hits and _pays(cfg, b, hits) else "loss")
            set_result(con, cfg, b["id"], outcome, hits=hits)
        else:
            r = results[0]
            outcome = {"hit": "win", "miss": "loss"}.get(r, "push")
            set_result(con, cfg, b["id"], outcome)
        con.execute("UPDATE bets SET graded_by='auto' WHERE id=?", (b["id"],))
        con.commit()
        settled += 1
    if settled:
        log("Graded %d bet(s) from ESPN box scores." % settled)
    return settled


def _pays(cfg, b, hits):
    e = cfg.entries(b["book"]).get(b["entry_type"]) or {}
    return float((e.get("pays") or {}).get(str(hits), 0))
