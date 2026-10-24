"""Small shared helpers: player-name keys, odds conversions, time.

Everything here is stdlib-only and Python 3.9 compatible, because the Mac's
built-in python3 is 3.9.
"""
import json
import math
import re
import unicodedata
from datetime import datetime, timedelta, timezone
from statistics import NormalDist

N01 = NormalDist()

try:
    from zoneinfo import ZoneInfo
    LOCAL_TZ = ZoneInfo("America/Chicago")
except Exception:  # pragma: no cover - tz database missing
    LOCAL_TZ = timezone(timedelta(hours=-5))

_SUFFIXES = {"jr", "sr", "ii", "iii", "iv", "v"}


def player_key(name, aliases=None):
    """A matching key for a player name across books.

    "P.J. Washington", "PJ Washington" and "P J Washington" all become
    "pj washington"; "Jabari Smith Jr." becomes "jabari smith"; accents drop.
    `aliases` maps one key to another for the stubborn cases (see aliases.json).
    """
    if not name:
        return ""
    s = unicodedata.normalize("NFKD", str(name)).encode("ascii", "ignore").decode()
    s = s.lower()
    s = s.replace(".", "").replace("'", "").replace("’", "")
    s = re.sub(r"[^a-z0-9]+", " ", s)
    parts = [p for p in s.split() if p not in _SUFFIXES]
    # Collapse runs of single letters: "p j washington" -> "pj washington"
    out, run = [], ""
    for p in parts:
        if len(p) == 1:
            run += p
        else:
            if run:
                out.append(run)
                run = ""
            out.append(p)
    if run:
        out.append(run)
    key = " ".join(out)
    if aliases:
        key = aliases.get(key, key)
    return key


def american_to_decimal(a):
    a = float(a)
    return 1 + (a / 100.0 if a > 0 else 100.0 / -a)


def decimal_to_american(d):
    if d is None or d <= 1:
        return None
    return round((d - 1) * 100) if d >= 2 else round(-100 / (d - 1))


def fmt_american(d):
    a = decimal_to_american(d)
    if a is None:
        return "—"
    return "+%d" % a if a > 0 else str(a)


def utcnow():
    return datetime.now(timezone.utc)


def iso(dt):
    return dt.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def parse_iso(s):
    if not s:
        return None
    s = s.replace("Z", "+00:00")
    return datetime.fromisoformat(s)


def local(dt):
    return dt.astimezone(LOCAL_TZ)


def local_label(s):
    """'2026-10-24T23:30:00Z' -> 'Sat 6:30 PM' in Central time."""
    dt = parse_iso(s)
    if not dt:
        return ""
    d = local(dt)
    return d.strftime("%a ") + d.strftime("%I:%M %p").lstrip("0")


def short_team(name):
    """'Golden State Warriors' -> 'Warriors', 'Portland Trail Blazers' -> 'Blazers'."""
    return (name or "").split()[-1] if name else ""


def load_json(path, default=None):
    try:
        with open(path) as f:
            return json.load(f)
    except FileNotFoundError:
        return default


def clamp(x, lo, hi):
    return max(lo, min(hi, x))


def pct(p, digits=1):
    if p is None or (isinstance(p, float) and math.isnan(p)):
        return "—"
    return ("%." + str(digits) + "f%%") % (p * 100)
