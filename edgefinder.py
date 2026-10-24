#!/usr/bin/env python3
"""Edge Finder - prices PrizePicks, Underdog, Fliff and Kalshi player props
against the sharp books and flags the few worth betting.

  python3 edgefinder.py check              key, credits, and which feeds answer
  python3 edgefinder.py run nba            pull lines and open the board
  python3 edgefinder.py pull nba           pull only
  python3 edgefinder.py board nba          rebuild the board from the last pull
  python3 edgefinder.py ge-import [file]   load a Gridiron Edge export (NFL)
  python3 edgefinder.py bet nba 4 9 12 --entry ud3 --stake 2
  python3 edgefinder.py watch nba          closing snapshot before each game you bet
  python3 edgefinder.py result 7 win
  python3 edgefinder.py bets               recent bets
  python3 edgefinder.py clv                closing line value report

GitHub Actions uses: auto, sweep-issues, site, ge-due, probe (see .github/workflows).

It only reads prices. It never places a bet.
"""
import argparse
import os
import sys
import webbrowser

if sys.version_info < (3, 8):
    sys.exit("Edge Finder needs Python 3.8 or newer (you have %s)." % sys.version.split()[0])

from ef import bets as betlog
from ef import board as boardmod
from ef import gridiron, render
from ef import auto as automod
from ef import web
from ef.config import BOARDS_DIR, ROOT, load_aliases, load_config, load_env, odds_api_key
from ef.db import connect
from ef.sources import OddsAPI, get_json, http_get, pull_kalshi, pull_odds


def cmd_check(cfg, args):
    key = odds_api_key()
    api = OddsAPI(cfg, key)
    st, data = api.sports()
    if st == 200:
        keys = {s.get("key") for s in data or []}
        print("Odds API key works. Credits left this month: %s" % api.remaining)
        for lg, spec in cfg["leagues"].items():
            print("  %s (%s): %s" % (lg.upper(), spec["sport_key"], "in season" if spec["sport_key"] in keys else "not listed"))
    else:
        print("Odds API answered HTTP %s: %s" % (st, data))
    base = cfg["kalshi"]["base"].rstrip("/")
    st, _, data = get_json(base + "/markets?series_ticker=KXNBAPTS&status=open&limit=5", http_get)
    print("Kalshi API: %s" % ("reachable" if st == 200 else "HTTP %s" % st))
    print("Books requested from the Odds API: %s" % ", ".join(cfg.all_books()))


def do_pull(cfg, con, league, args):
    key = odds_api_key()
    aliases = load_aliases()
    pid, info = pull_odds(con, cfg, league, key, hours=args.hours, yes=args.yes, aliases=aliases)
    if not pid:
        return None
    k = 0
    if not args.no_kalshi:
        k = pull_kalshi(con, cfg, league, pid, aliases=aliases)
    counts = con.execute("SELECT book, COUNT(*) AS n FROM lines WHERE pull_id=? GROUP BY book ORDER BY n DESC",
                         (pid,)).fetchall()
    print("Pulled %d games: %d Odds API lines + %d Kalshi lines. Credits used %s, left %s."
          % (info["events"], info["lines"], k, info["credits_used"], info["credits_remaining"]))
    for r in counts:
        print("  %-12s %5d" % (boardmod.BOOK_LABELS.get(r["book"], r["book"]), r["n"]))
    return pid


def do_board(cfg, con, league, args, pull_id=None):
    b = boardmod.build(con, cfg, league, pull_id=pull_id)
    boardmod.save_codes(con, b)
    path, csv_path = render.write(b, cfg, ROOT, BOARDS_DIR)
    fl = [x for s in ("pickem", "fliff", "kalshi") for x in b[s] if x["flagged"]]
    print("Board: %d flagged (%d pick'em, %d Fliff, %d Kalshi) of %d priced lines."
          % (len(fl), sum(x["flagged"] for x in b["pickem"]), sum(x["flagged"] for x in b["fliff"]),
             sum(x["flagged"] for x in b["kalshi"]), sum(len(b[s]) for s in ("pickem", "fliff", "kalshi"))))
    for x in fl[:12]:
        extra = ("edge %+.1f" % (x["edge"] * 100)) if x["book"] in cfg.pickem_books else (
            "EV %+.1f%%" % (100 * (x["roi"] if x["book"] == "kalshi" else x["ev"])))
        print("  #%-3s %-10s %-22s %-5s %-6g %-12s fair %5.1f%%  %s" % (
            x["code"], boardmod.BOOK_LABELS.get(x["book"], x["book"]), x["player"][:22], x["side"],
            x["point"], boardmod.market_label(x["market"])[:12], 100 * x["p"], extra))
    print("Saved %s" % path)
    if not args.no_open:
        webbrowser.open("file://" + os.path.abspath(path))
    return b


def gh_output(**kv):
    """Pass values to later workflow steps when running on GitHub Actions."""
    path = os.environ.get("GITHUB_OUTPUT")
    if path:
        with open(path, "a") as f:
            for k, v in kv.items():
                f.write("%s=%s\n" % (k, v))


def notice(msg):
    """Print, and on GitHub Actions also show it on the run's summary page."""
    print(msg)
    if os.environ.get("GITHUB_ACTIONS"):
        print("::notice::" + msg.replace("%", "%25").replace("\r", "").replace("\n", "%0A"))


def has_key():
    load_env()
    k = os.environ.get("ODDS_API_KEY", "").strip()
    return bool(k) and not k.startswith("paste")


def cmd_auto(cfg, con, args):
    changed = False
    if not has_key():
        notice("No ODDS_API_KEY secret yet - add it in the repo's Settings > Secrets and variables > Actions.")
    else:
        key = odds_api_key()
        for lg in (args.league and [args.league]) or cfg["auto"]["leagues"]:
            r = automod.run_league(con, cfg, lg, key, aliases=load_aliases())
            changed = changed or r["board_pull"] or r["close_pulls"] > 0 or r.get("closed_legs", 0) > 0
            notice("%s: %d games ahead, board pull %s, %d closing snapshot(s), %d credits%s" % (
                lg.upper(), r.get("games_ahead", 0), "yes" if r["board_pull"] else "no", r["close_pulls"],
                r["credits"], (" (" + r["skipped"] + ")") if r["skipped"] else ""))
    automod.prune(con)
    gh_output(changed="true" if changed else "false")


def _gh(*args, stdin=None):
    import subprocess
    return subprocess.run(["gh"] + list(args), input=stdin, capture_output=True, text=True)


def handle_command(cmd):
    """Run one issue command. (ok, text)."""
    argv = list(cmd)
    if argv[0] == "refresh":
        lg = argv[1] if len(argv) > 1 else "nba"
        argv = ["pull", lg, "--yes", "--hours", "14"]
    return web.run_cli(main, argv)


def cmd_sweep_issues(cfg, con, args):
    """Run every open command issue you filed, oldest first, reply, and close it.
    Every workflow run sweeps, so an issue whose own run got dropped from
    GitHub's queue is picked up by the next one."""
    import json
    repo = os.environ.get("GITHUB_REPOSITORY") or cfg["github"]["repo"]
    owner = os.environ.get("GITHUB_REPOSITORY_OWNER") or repo.split("/")[0]
    r = _gh("issue", "list", "--repo", repo, "--state", "open", "--author", owner,
            "--json", "number,title,body,author", "--limit", "30")
    if r.returncode != 0:
        print("Couldn't list issues: %s" % r.stderr.strip())
        gh_output(swept="0")
        return
    issues = sorted(json.loads(r.stdout or "[]"), key=lambda i: i["number"])
    done = 0
    for it in issues:
        if (it.get("author") or {}).get("login", "").lower() != owner.lower():
            continue
        first = ((it.get("title") or "").strip().split() or [""])[0].lower()
        if first not in web.ALLOWED:
            continue            # an ordinary issue, not a command - leave it alone
        cmd = web.parse_issue(it.get("title"), it.get("body"))
        if not cmd:
            ok, text, cmd = False, ("No command found. Use the Log button on the board, or write one line like:\n"
                                    "result 7 win\nrefresh nba"), ["?"]
        else:
            ok, text = handle_command(cmd)
        _gh("issue", "comment", str(it["number"]), "--repo", repo, "--body-file", "-",
            stdin=web.comment_for(cmd, ok, text))
        _gh("issue", "close", str(it["number"]), "--repo", repo)
        notice("Issue #%d %s: %s" % (it["number"], " ".join(cmd), "ok" if ok else "failed - " + text[-300:]))
        done += 1
    gh_output(changed="true" if done else "false", swept=str(done))


def cmd_ge_due(cfg, con, args):
    """True when an NFL game starts within 4 hours and Gridiron Edge hasn't been read in 3."""
    from datetime import timedelta
    from ef.sources import OddsAPI
    from ef.util import iso, utcnow
    due = False
    if has_key():
        now = utcnow()
        st, evs = OddsAPI(cfg, odds_api_key()).events(cfg.league("nfl")["sport_key"], now, now + timedelta(hours=4))
        soon = st == 200 and any(e["commence_time"] > iso(now) for e in (evs or []))
        last = con.execute("SELECT MAX(imported_at) AS t FROM ge_proj").fetchone()["t"]
        due = bool(soon and (not last or last < iso(now - timedelta(hours=3))))
        # At most one attempt an hour, so a failing export doesn't rerun every 15 minutes.
        slot = "ge:attempt:" + iso(now)[:13]
        if due and con.execute("SELECT 1 FROM auto_slots WHERE slot=?", (slot,)).fetchone():
            due = False
        elif due:
            con.execute("INSERT INTO auto_slots (slot, ts) VALUES (?,?)", (slot, iso(now)))
            con.commit()
    print("Gridiron Edge export due: %s" % due)
    if due:
        notice("Gridiron Edge export due - running it")
    gh_output(ge_due="true" if due else "false")


def cmd_probe(cfg, con, args):
    from ef.sources import get_json
    base = cfg["kalshi"]["base"].rstrip("/")
    for series in ("KXNBAPTS", "KXNFLRECYDS"):
        st, _, data = get_json(base + "/markets?series_ticker=%s&status=open&limit=1000" % series, http_get)
        n = len((data or {}).get("markets") or []) if st == 200 else 0
        notice("Kalshi %s: HTTP %s, %d open markets" % (series, st, n))
    st, _, data = get_json("https://site.api.espn.com/apis/site/v2/sports/basketball/nba/scoreboard", http_get)
    notice("ESPN NBA scoreboard: HTTP %s, %d games" % (st, len((data or {}).get("events") or [])))
    if has_key():
        api = OddsAPI(cfg, odds_api_key())
        st, data = api.sports()
        notice("Odds API: HTTP %s, %s credits left" % (st, api.remaining))
        lg = cfg.league("nba")
        from datetime import timedelta
        from ef.util import utcnow
        now = utcnow()
        st, evs = api.events(lg["sport_key"], now, now + timedelta(hours=14))
        notice("Odds API NBA games in the next 14 hours: %s (HTTP %s, free call)" % (len(evs or []), st))
    else:
        notice("Odds API: no key yet")


def main(argv=None):
    p = argparse.ArgumentParser(description="Edge Finder")
    sub = p.add_subparsers(dest="cmd")

    sub.add_parser("check")
    for name in ("pull", "run", "board"):
        sp = sub.add_parser(name)
        sp.add_argument("league", choices=["nba", "nfl"])
        sp.add_argument("--hours", type=int, default=None, help="look this far ahead (default 30)")
        sp.add_argument("--yes", action="store_true", help="skip the credit-budget prompt")
        sp.add_argument("--no-kalshi", action="store_true")
        sp.add_argument("--no-open", action="store_true", help="don't open the board in the browser")

    sp = sub.add_parser("ge-import")
    sp.add_argument("file", nargs="?")

    sp = sub.add_parser("bet")
    sp.add_argument("league", choices=["nba", "nfl"])
    sp.add_argument("codes", nargs="+")
    sp.add_argument("--entry", help="pick'em entry type, e.g. pp5, ppf6, ud3")
    sp.add_argument("--stake", type=float, default=1.0)
    sp.add_argument("--price", type=float, help="decimal odds you actually got (Fliff) or ask paid (Kalshi)")
    sp.add_argument("--contracts", type=int, help="Kalshi contracts bought")
    sp.add_argument("--note")
    sp.add_argument("--board", help="which board the numbers came from (the board page fills this in)")

    for name in ("close", "watch"):
        sp = sub.add_parser(name)
        sp.add_argument("league", choices=["nba", "nfl"])
        sp.add_argument("--minutes", type=int, default=15)

    sp = sub.add_parser("result")
    sp.add_argument("bet_id", type=int)
    sp.add_argument("outcome", choices=["win", "loss", "push", "partial"])
    sp.add_argument("--payout", type=float)
    sp.add_argument("--hits", type=int, help="pick'em: how many legs hit (flex entries)")

    sub.add_parser("bets")
    sp = sub.add_parser("auto")
    sp.add_argument("--league", choices=["nba", "nfl"])
    sub.add_parser("sweep-issues")
    sp = sub.add_parser("site")
    sp.add_argument("--out", default="site")
    sp.add_argument("--status", default="")
    sub.add_parser("ge-due")
    sub.add_parser("probe")
    sp = sub.add_parser("clv")
    sp.add_argument("league", nargs="?", choices=["nba", "nfl"])

    args = p.parse_args(argv)
    if not args.cmd:
        p.print_help()
        return
    cfg = load_config()
    if args.cmd == "check":
        return cmd_check(cfg, args)

    con = connect()
    if args.cmd == "pull":
        do_pull(cfg, con, args.league, args)
    elif args.cmd == "run":
        pid = do_pull(cfg, con, args.league, args)
        if pid:
            do_board(cfg, con, args.league, args, pull_id=pid)
    elif args.cmd == "board":
        do_board(cfg, con, args.league, args)
    elif args.cmd == "ge-import":
        path = args.file or gridiron.find_export()
        if not path:
            sys.exit("No Gridiron Edge export found in inputs/ or Downloads. In Gridiron Edge, click "
                     "'Export for Edge Finder' first.")
        info = gridiron.import_export(con, cfg, path, aliases=load_aliases())
        notice("Loaded Gridiron Edge %s week %s: %d player-markets (scan saved %s) from %s"
              % (info["year"], info["week"], info["rows"], info["saved_at"], os.path.basename(path)))
    elif args.cmd == "bet":
        ids = betlog.log_bet(con, cfg, args.league, args.codes, entry=args.entry, stake=args.stake,
                             price=args.price, contracts=args.contracts, notes=args.note, board_ts=args.board)
        print("Logged bet%s %s." % ("s" if len(ids) > 1 else "", ", ".join("#%d" % i for i in ids)))
        print(betlog.list_bets(con, limit=len(ids)))
        if os.environ.get("GITHUB_ACTIONS"):
            print("Closing lines will be captured automatically before each game.")
        else:
            print("Run 'watch %s' before tip-off to capture closing lines." % args.league)
    elif args.cmd == "close":
        betlog.capture_close(con, cfg, args.league, odds_api_key(), minutes=args.minutes)
        betlog.update_closes(con, cfg)
    elif args.cmd == "watch":
        betlog.watch(con, cfg, args.league, odds_api_key(), lead=args.minutes)
    elif args.cmd == "result":
        pay = betlog.set_result(con, cfg, args.bet_id, args.outcome, payout=args.payout, hits=args.hits)
        print("Bet #%d: %s, payout $%.2f" % (args.bet_id, args.outcome, pay))
    elif args.cmd == "bets":
        betlog.update_closes(con, cfg)
        print(betlog.list_bets(con))
    elif args.cmd == "clv":
        print(betlog.clv_report(con, cfg, league=args.league))
    elif args.cmd == "auto":
        cmd_auto(cfg, con, args)
    elif args.cmd == "sweep-issues":
        cmd_sweep_issues(cfg, con, args)
    elif args.cmd == "site":
        web.build_site(con, cfg, args.out, status=args.status)
        print("Site written to %s/" % args.out)
    elif args.cmd == "ge-due":
        cmd_ge_due(cfg, con, args)
    elif args.cmd == "probe":
        cmd_probe(cfg, con, args)


if __name__ == "__main__":
    main()
