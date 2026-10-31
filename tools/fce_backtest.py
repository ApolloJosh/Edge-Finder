"""Backtest Full Court Edge against the sharp fair price on past NBA boards.

For every NBA board pull, rebuild the board as of the pull (Full Court Edge only
sees games before that day), grade each line against that night's box score,
and compare log loss and Brier score: the sharp fair price alone, Full Court
Edge alone, and blends of the two. Lower is better.

The same line is often on several pulls of one day, so the bootstrap resamples
whole player-stat-games, not rows; "P(better)" is the share of resamples in
which the blend beat the sharp price. Treat one market winning out of five as
a lead to re-test, not proof: by luck alone, one in five clears 0.95 now and
then.

  python3 tools/fce_backtest.py            (uses data/edgefinder.db or EDGEFINDER_DB)
"""
import math
import os
import random
import sys
from datetime import timedelta

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from ef import board as boardmod, fullcourt  # noqa: E402
from ef.config import load_config  # noqa: E402
from ef.db import connect  # noqa: E402
from ef.util import parse_iso  # noqa: E402

WEIGHTS = (0.0, 0.1, 0.2, 0.25, 0.3, 0.5, 1.0)
BOOT = 400


def collect(con, cfg):
    """(fair, model, hit, market, cluster, day) for each over-side line on each pull."""
    out = []
    pulls = con.execute("SELECT * FROM pulls WHERE league='nba' AND kind='board' ORDER BY id").fetchall()
    models = {}
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
                day = (parse_iso(ev["commence_time"]) - timedelta(hours=6)).date()      # US date of the game
                parts = fullcourt.MARKET_PARTS.get(x["market"])
                if day not in models:
                    models[day] = fullcourt.Model(con, today=day)
                key = models[day]._resolve(x["player_key"])
                r = con.execute("SELECT * FROM nba_box WHERE player_key=? AND game_date=?",
                                (key, day.isoformat())).fetchone() if key else None
                if not r or not parts:
                    continue
                val = sum(r[p] or 0 for p in parts)
                if abs(val - x["point"]) < 1e-9:
                    continue
                out.append((x["p_raw"], x["ge_p"], 1 if val > x["point"] else 0, x["market"],
                            (x["event_id"], x["player_key"], x["market"]), day.isoformat()))
    return out


def scores(rows, w):
    ll = br = 0.0
    for fair, m, y, *_ in rows:
        p = min(max(fair + w * (m - fair), 1e-4), 1 - 1e-4)
        ll -= math.log(p if y else 1 - p)
        br += (p - y) ** 2
    return ll / len(rows), br / len(rows)


def p_better(rows, w, n=BOOT, seed=1):
    """Share of player-stat-game resamples in which weight w beats the sharp price."""
    groups = {}
    for r in rows:
        groups.setdefault(r[4], []).append(r)
    keys = list(groups)
    rnd = random.Random(seed)
    wins = 0
    for _ in range(n):
        samp = [r for k in rnd.choices(keys, k=len(keys)) for r in groups[k]]
        wins += scores(samp, w)[0] < scores(samp, 0)[0]
    return wins / n


def main():
    cfg = load_config()
    con = connect()
    rows = collect(con, cfg)
    if not rows:
        print("Nothing to grade yet.")
        return
    print("%d graded lines: %d player-stat-games over %d game days (over side)"
          % (len(rows), len({r[4] for r in rows}), len({r[5] for r in rows})))
    print("weight on Full Court Edge   log loss   Brier")
    for w in WEIGHTS:
        ll, br = scores(rows, w)
        print("  %4.2f %s  %.4f   %.4f" % (w, "(sharp fair only)" if w == 0 else "(model only)    " if w == 1 else "                 ", ll, br))
    print("  P(blend .25 beats sharp) %.2f" % p_better(rows, .25))
    by = {}
    for r in rows:
        by.setdefault(r[3], []).append(r)
    print("by market, log loss (lower is better):")
    for mk, rs in sorted(by.items(), key=lambda kv: -len(kv[1])):
        print("  %-32s games=%4d  fair %.4f  model %.4f  blend .25 %.4f  P(better) %.2f"
              % (mk, len({r[4] for r in rs}), scores(rs, 0)[0], scores(rs, 1)[0], scores(rs, .25)[0], p_better(rs, .25)))


if __name__ == "__main__":
    main()
