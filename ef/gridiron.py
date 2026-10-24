"""Gridiron Edge as a second opinion on NFL picks.

Gridiron Edge saves, for every player on its board, a median and a 25-75%
range for each prop market. Here that range becomes a probability of clearing
the book's line. It is shown beside the market's fair probability - it does
not decide which picks make the board.
"""
import glob
import json
import math
import os
from datetime import datetime, timezone

from .config import INPUTS_DIR
from .util import N01, iso, player_key, utcnow

Z75 = 0.6744897501960817  # 75th percentile of a standard normal


def find_export():
    """Newest Gridiron Edge export in inputs/ or ~/Downloads."""
    pats = [os.path.join(INPUTS_DIR, "gridiron-edge-*.json"),
            os.path.expanduser("~/Downloads/gridiron-edge-*.json")]
    files = [f for p in pats for f in glob.glob(p)]
    return max(files, key=os.path.getmtime) if files else None


def _is_biased(cfg, ge_market, pos):
    for b in cfg["gridiron_edge"]["biased"]:
        if ":" in b:
            m, p = b.split(":", 1)
            if m == ge_market and pos == p:
                return True
        elif b == ge_market:
            return True
    return False


def import_export(con, cfg, path, aliases=None):
    with open(path) as f:
        raw = json.load(f)
    snap = raw.get("snapshot", raw) if isinstance(raw, dict) else None
    if not snap or "rows" not in snap:
        raise SystemExit("%s doesn't look like a Gridiron Edge export." % path)
    mapping = cfg["gridiron_edge"]["map"]
    saved = snap.get("savedAt")
    saved_iso = iso(datetime.fromtimestamp(saved / 1000.0, tz=timezone.utc)) if saved else None
    now = iso(utcnow())
    n = 0
    con.execute("DELETE FROM ge_proj WHERE year=? AND week=?", (snap.get("year"), snap.get("week")))
    for r in snap["rows"]:
        for ge_id, m in (r.get("markets") or {}).items():
            odds_key = mapping.get(ge_id)
            if not odds_key or m.get("median") is None:
                continue
            con.execute(
                "INSERT INTO ge_proj (imported_at, saved_at, year, week, player, player_key, pos, team, opp,"
                " ge_market, market, median, p25, p75, score, biased) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                (now, saved_iso, snap.get("year"), snap.get("week"), r.get("name"),
                 player_key(r.get("name"), aliases), r.get("pos"), r.get("team"), r.get("opp"),
                 ge_id, odds_key, m.get("median"), m.get("p25"), m.get("p75"), m.get("score"),
                 1 if _is_biased(cfg, ge_id, r.get("pos")) else 0),
            )
            n += 1
    con.commit()
    return {"rows": n, "year": snap.get("year"), "week": snap.get("week"), "saved_at": saved_iso,
            "build": raw.get("build") if isinstance(raw, dict) else None}


def load_latest(con):
    """{(player_key, market): row} from the most recent import."""
    last = con.execute("SELECT MAX(imported_at) AS t FROM ge_proj").fetchone()["t"]
    if not last:
        return {}, None
    rows = con.execute("SELECT * FROM ge_proj WHERE imported_at=?", (last,)).fetchall()
    out = {}
    for r in rows:
        k = (r["player_key"], r["market"])
        # A player listed under two kinds (RB receptions vs REC receptions) keeps the higher score.
        if k not in out or (r["score"] or 0) > (out[k]["score"] or 0):
            out[k] = r
    return out, rows[0]["saved_at"] if rows else None


def prob_over(median, p25, p75, line):
    """P(stat > line) from Gridiron Edge's median and 25th/75th percentiles.

    Two-piece fit: one spread below the median, another above it, so the curve
    passes exactly through all three numbers Gridiron Edge published and keeps
    their skew. Log scale when everything is positive (yardage is right-skewed),
    plain scale otherwise.
    """
    if median is None or p25 is None or p75 is None or not (p25 <= median <= p75) or p75 <= p25:
        return None
    if p25 > 0 and line > 0:
        m, lo, hi, x = math.log(median), math.log(p25), math.log(p75), math.log(line)
    else:
        m, lo, hi, x = median, p25, p75, line
    s_lo, s_hi = (m - lo) / Z75, (hi - m) / Z75
    s = s_hi if x >= m else s_lo
    if s <= 0:  # median sits on a quartile - fall back to the other side's spread
        s = max(s_lo, s_hi)
    return 1 - N01.cdf((x - m) / s)


def assess(cfg, ge_row, line, side):
    """(probability for this side, tag) or (None, None)."""
    if not ge_row:
        return None, None
    p = prob_over(ge_row["median"], ge_row["p25"], ge_row["p75"], line)
    if p is None:
        return None, None
    if side == "under":
        p = 1 - p
    g = cfg["gridiron_edge"]
    if ge_row["biased"]:
        tag = "biased"
    elif p >= g["agree_at"]:
        tag = "agree"
    elif p <= g["conflict_at"]:
        tag = "conflict"
    else:
        tag = "neutral"
    return p, tag
