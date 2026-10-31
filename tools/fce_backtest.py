"""Backtest Full Court Edge against the sharp fair price on past NBA boards.

For every NBA board pull, rebuild the board as of the pull (Full Court Edge only
sees games before that day), grade each line against that night's box score,
and compare log loss and Brier score: the sharp fair price alone, Full Court
Edge alone, and blends of the two. Lower is better.

  python3 tools/fce_backtest.py            (uses data/edgefinder.db or EDGEFINDER_DB)
"""
import math
import os
import sys
from datetime import timedelta

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from ef import board as boardmod, fullcourt  # noqa: E402
from ef.config import load_config  # noqa: E402
from ef.db import connect  # noqa: E402
from ef.util import parse_iso  # noqa: E402

WEIGHTS = (0.0, 0.1, 0.2, 0.25, 0.3, 0.5, 1.0)


def collect(con, cfg):
    out = []
    pulls = con.execute("SELECT * FROM pulls WHERE league='nba' AND kind='board' ORDER BY id").fetchall()
    for pull in pulls:
        now = parse_iso(pull["ts"]) + timedelta(minutes=1)
        try:
            b = boardmod.build(con, cfg, "nba", pull_id=pull["id"], now=now)
        except SystemExit:
            continue
        seen = set()
        for sec in ("pickem", "fliff", "kalshi"):
            for x in b[sec]:
                if x.get("ge_p") is None or x["side"] != "over":
                    continue
                k = (x["event_id"], x["player_key"], x["market"], x["point"])
                if k in seen:
                    continue
                seen.add(k)
                ev = con.execute("SELECT commence_time FROM events WHERE event_id=?", (x["event_id"],)).fetchone()
                day = parse_iso(ev["commence_time"]) - timedelta(hours=6)      # US date of the game
                parts = fullcourt.MARKET_PARTS.get(x["market"])
                key = fullcourt.Model(con, today=day.date())._resolve(x["player_key"])
                r = con.execute("SELECT * FROM nba_box WHERE player_key=? AND game_date=?",
                                (key, day.date().isoformat())).fetchone() if key else None
                if not r or not parts:
                    continue
                val = sum(r[p] or 0 for p in parts)
                if abs(val - x["point"]) < 1e-9:
                    continue
                out.append((x["p_raw"], x["ge_p"], 1 if val > x["point"] else 0, x["market"]))
    return out


def scores(rows, w):
    ll = br = 0.0
    for fair, m, y, _ in rows:
        p = min(max(fair + w * (m - fair), 1e-4), 1 - 1e-4)
        ll -= math.log(p if y else 1 - p)
        br += (p - y) ** 2
    return ll / len(rows), br / len(rows)


def main():
    cfg = load_config()
    con = connect()
    rows = collect(con, cfg)
    if not rows:
        print("Nothing to grade yet.")
        return
    print("%d graded lines (over side, one per player/stat/line)" % len(rows))
    print("weight on Full Court Edge   log loss   Brier")
    for w in WEIGHTS:
        ll, br = scores(rows, w)
        print("  %4.2f %s  %.4f   %.4f" % (w, "(sharp fair only)" if w == 0 else "(model only)    " if w == 1 else "                 ", ll, br))
    by = {}
    for r in rows:
        by.setdefault(r[3], []).append(r)
    print("by market, fair vs model log loss:")
    for mk, rs in sorted(by.items(), key=lambda kv: -len(kv[1])):
        print("  %-34s n=%4d  fair %.4f  model %.4f  blend .25 %.4f" % (mk, len(rs), scores(rs, 0)[0], scores(rs, 1)[0], scores(rs, .25)[0]))


if __name__ == "__main__":
    main()
