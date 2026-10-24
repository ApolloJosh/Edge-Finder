"""The GitHub side: commands sent as issues, and the Pages site."""
import contextlib
import html
import io
import json
import os
import re
import shlex
from urllib.parse import quote

from . import bets as betlog
from . import board as boardmod
from . import render
from .board import BOOK_LABELS, market_label
from .util import local, local_label, parse_iso, pct, utcnow

E = html.escape

# Commands an issue may run. Anything else is refused.
ALLOWED = {"bet", "result", "refresh", "ge-import"}


def parse_issue(title, body):
    """Find the command in an issue. The board's Log button puts it in a code
    block in the body; a typed title like 'result 7 win' also works."""
    for text in (body or "", title or ""):
        for line in text.replace("\r", "").split("\n"):
            line = line.strip().strip("`").strip()
            if line.startswith("python3 edgefinder.py "):
                line = line[len("python3 edgefinder.py "):]
            try:
                parts = shlex.split(line)
            except ValueError:
                continue
            if parts and parts[0] in ALLOWED:
                return parts
    return None


def run_cli(main, argv):
    """Run edgefinder.main(argv), capturing what it prints. (ok, text)."""
    buf = io.StringIO()
    ok = True
    with contextlib.redirect_stdout(buf):
        try:
            main(argv)
        except SystemExit as e:
            if e.code not in (None, 0):
                ok = False
                print(e.code if isinstance(e.code, str) else "Failed (exit %s)" % e.code)
    return ok, buf.getvalue().strip()


def issue_url(repo, title, body):
    return "https://github.com/%s/issues/new?title=%s&body=%s" % (repo, quote(title), quote(body))


# ------------------------------------------------------------------ site

PAGE = """<!doctype html><html lang="en"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>%(title)s</title><style>%(css)s
.cards{display:grid;grid-template-columns:repeat(auto-fill,minmax(240px,1fr));gap:10px;margin-top:14px}
.card{display:block;background:var(--panel);border:1px solid var(--line);border-radius:8px;padding:14px;color:var(--ink);text-decoration:none}
.card b{font-size:16px}.card .sub{margin-top:4px}
.stat{font-size:22px;font-weight:700;font-variant-numeric:tabular-nums}
.res a{margin-right:4px;font-size:12px;padding:3px 8px}
ol.how{color:var(--dim);font-size:13.5px;line-height:1.7;padding-left:20px}
</style></head><body><div class="wrap">%(nav)s%(content)s</div></body></html>"""


def _page(title, active, content, web):
    return PAGE % {"title": E(title), "css": render.CSS, "nav": render.nav_html(active, web), "content": content}


def _placeholder(league, why):
    return "<h1>Edge Finder · %s</h1><div class=\"tablewrap\"><div class=\"empty\">%s</div></div>" % (
        league.upper(), E(why))


def build_site(con, cfg, out_dir, now=None, status=None):
    """Write index.html, nba.html, nfl.html and bets.html into out_dir."""
    now = now or utcnow()
    repo = cfg["github"]["repo"]
    web = {"repo": repo}
    os.makedirs(out_dir, exist_ok=True)
    cards = []
    for lg in ("nba", "nfl"):
        try:
            b = boardmod.build(con, cfg, lg, now=now)
        except SystemExit:
            b = None
        if b is None:
            page = _page("Edge Finder " + lg.upper(), lg, _placeholder(
                lg, "No %s lines pulled yet. Edge Finder pulls each game about %s minutes before tip." % (
                    lg.upper(), " and ".join(str(o) for o in cfg["auto"]["board_offsets_min"]))), web)
            cards.append((lg, "No board yet", ""))
        else:
            boardmod.save_codes(con, b)
            page = render.render(b, cfg, "", web=web)
            fl = sum(1 for s in ("pickem", "fliff", "kalshi") for x in b[s] if x["flagged"])
            pulled = local(parse_iso(b["pull"]["ts"])).strftime("%a %I:%M %p").replace(" 0", " ")
            cards.append((lg, "%d flagged" % fl, "%d games · last pull %s" % (b["games"], pulled)))
        with open(os.path.join(out_dir, "%s.html" % lg), "w") as f:
            f.write(page)

    with open(os.path.join(out_dir, "bets.html"), "w") as f:
        f.write(bets_page(con, cfg, web, now))

    s = betlog.clv_summary(con, cfg, now=now)
    open_n = con.execute("SELECT COUNT(*) AS n FROM bets WHERE result IS NULL").fetchone()["n"]
    clv_txt = ("%+.1f pts avg CLV over %d legs" % (100 * s["all"]["avg"], s["all"]["n"])) if s["all"] else "no closed legs yet"
    last = con.execute("SELECT * FROM pulls ORDER BY id DESC LIMIT 1").fetchone()
    credits = last["credits_remaining"] if last and last["credits_remaining"] is not None else None
    tiles = "".join(
        '<a class="card" href="%s.html"><b>%s</b><div class="stat">%s</div><div class="sub">%s</div></a>' % (
            lg, lg.upper(), E(a), E(b)) for lg, a, b in cards)
    tiles += '<a class="card" href="bets.html"><b>Bets &amp; CLV</b><div class="stat">%d open</div><div class="sub">%s</div></a>' % (
        open_n, E(clv_txt))
    st = E(status or "")
    content = """<h1>Edge Finder</h1>
<div class="sub">Updated %(upd)s%(cred)s. Runs itself on GitHub Actions every 15 minutes; it only reads prices.</div>
<div class="cards">%(tiles)s</div>
<h2>How to use it</h2>
<ol class="how">
<li>Open a board. Flagged picks beat the sharp market; tick the ones you actually play.</li>
<li>Tap <b>Log bet on GitHub</b>, then <b>Submit</b> on the issue it opens. Edge Finder records it and replies in a minute or two.</li>
<li>Closing lines are captured automatically before each game you bet. Check <a href="bets.html">Bets &amp; CLV</a>.</li>
<li>Lineup news? <a href="%(refresh)s" target="_blank" rel="noopener">Refresh NBA now</a> · <a href="%(refnfl)s" target="_blank" rel="noopener">Refresh NFL now</a> (costs credits).</li>
</ol>
<div class="foot">%(status)s</div>""" % {
        "upd": local(now).strftime("%a %b %d, %I:%M %p").replace(" 0", " "),
        "cred": (" · %s Odds API credits left" % credits) if credits is not None else "",
        "tiles": tiles,
        "refresh": E(issue_url(repo, "refresh nba", "```\nrefresh nba\n```")),
        "refnfl": E(issue_url(repo, "refresh nfl", "```\nrefresh nfl\n```")),
        "status": st,
    }
    with open(os.path.join(out_dir, "index.html"), "w") as f:
        f.write(_page("Edge Finder", "index", content, web))
    with open(os.path.join(out_dir, ".nojekyll"), "w") as f:
        f.write("")
    return out_dir


def _stat_rows(rows):
    out = []
    for title, st in rows:
        cls = "pos" if st["avg"] > 0 else "neg"
        out.append("<tr><td>%s</td>%s%s%s%s</tr>" % (
            E(title), render._td(str(st["n"]), st["n"], "num"),
            render._td('<span class="%s">%+.1f</span>' % (cls, 100 * st["avg"]), st["avg"], "num"),
            render._td("%.0f%%" % (100 * st["pos"]), st["pos"], "num"),
            render._td("%+.1f" % (100 * st["beat"]) if st["beat"] is not None else "—", st["beat"] or 0, "num")))
    return out


def bets_page(con, cfg, web, now):
    repo = web["repo"]
    s = betlog.clv_summary(con, cfg, now=now)
    parts = ["<h1>Bets &amp; closing line value</h1>",
             '<div class="sub">CLV = the sharp market\'s fair chance for your pick at close, minus when you placed it. '
             "Consistently positive CLV is the earliest real sign of an edge. Keep stakes at $1&ndash;5 until it holds "
             "over a few hundred bets.</div>"]
    head = [("Group", 0), ("Legs", 1), ("Avg CLV (pts)", 1), ("Moved your way", 1), ("Close vs breakeven", 1)]
    if s["all"]:
        rows = _stat_rows([("All legs", s["all"])] + [("Book: " + k, v) for k, v in s["books"]]
                          + [("Week " + k, v) for k, v in s["weeks"]])
        parts.append("<h2>CLV</h2>" + render._table(head, rows, ""))
        if s["ge"]:
            parts.append("<h2>Gridiron Edge as a second opinion <small>NFL legs, by whether it agreed</small></h2>")
            parts.append(render._table(head, _stat_rows([("GE " + k, v) for k, v in s["ge"]]), ""))
    else:
        parts.append('<h2>CLV</h2><div class="tablewrap"><div class="empty">No closed legs yet. CLV fills in once a game you bet has started.</div></div>')
    r = s["results"]
    if r["n"]:
        parts.append('<div class="chips"><span class="chip"><b>%d</b> settled</span><span class="chip">$<b>%.2f</b> staked</span>'
                     '<span class="chip">$<b>%.2f</b> back</span><span class="chip"><b class="%s">%+.2f</b> (%+.1f%%)</span></div>' % (
                         r["n"], r["staked"], r["paid"], "pos" if r["net"] >= 0 else "neg", r["net"], 100 * (r["roi"] or 0)))

    bets = con.execute("SELECT * FROM bets ORDER BY id DESC LIMIT 200").fetchall()
    open_rows, done_rows = [], []
    for b in bets:
        legs = con.execute("SELECT * FROM bet_legs WHERE bet_id=? ORDER BY leg", (b["id"],)).fetchall()
        leg_html = "<br>".join(
            "%s %s %g %s · %s%s" % (
                E(l["player"]), "Over" if l["side"] == "over" else "Under", l["point"], E(market_label(l["market"])),
                pct(l["fair_p"]),
                (' → %s <span class="%s">(%+.1f)</span>' % (pct(l["close_fair_p"]), "pos" if l["close_fair_p"] >= l["fair_p"] else "neg",
                                                            100 * (l["close_fair_p"] - l["fair_p"])))
                if l["close_fair_p"] is not None else "")
            for l in legs)
        start = min((l["commence_time"] for l in legs if l["commence_time"]), default=None)
        cells = [render._td("#%d" % b["id"], b["id"], "code"),
                 render._td(E(local(parse_iso(b["placed_at"])).strftime("%m/%d %I:%M %p").replace(" 0", " ")), b["placed_at"]),
                 render._td(E(BOOK_LABELS.get(b["book"], b["book"])) + '<br><span class="sub">%s</span>' % E(b["entry_type"] or ""), b["book"]),
                 render._td("$%.2f" % (b["stake"] or 0), b["stake"] or 0, "num"),
                 render._td(leg_html, None, "sharp"),
                 render._td(E(local_label(start)) if start else "", start or "")]
        if b["result"]:
            cells.insert(1, render._td("%s · $%.2f" % (E(b["result"]), b["payout"] or 0), b["payout"] or 0))
            done_rows.append("<tr>%s</tr>" % "".join(cells))
        else:
            links = "".join('<a class="btn ghost" target="_blank" rel="noopener" href="%s">%s</a>' % (
                E(issue_url(repo, "result %d %s" % (b["id"], o), "```\nresult %d %s\n```" % (b["id"], o))), o.title())
                for o in ("win", "loss", "push"))
            cells.insert(1, '<td class="res">%s</td>' % links)
            open_rows.append("<tr>%s</tr>" % "".join(cells))
    bh = [("Placed", 0), ("App", 0), ("Stake", 1), ("Legs: fair at bet → at close (CLV)", 0), ("Game", 0)]
    parts.append("<h2>Open bets <small>tap a result once it settles; for a flex entry that partly hit, open an issue "
                 "like <code>result 12 partial --hits 4</code></small></h2>")
    parts.append(render._table([("#", 0), ("Result", 0)] + bh, open_rows, "No open bets."))
    parts.append("<h2>Settled</h2>")
    parts.append(render._table([("#", 0), ("Result", 0)] + bh, done_rows, "Nothing settled yet."))
    return _page("Edge Finder bets", "bets", "\n".join(parts), web)


def write_json(path, data):
    with open(path, "w") as f:
        json.dump(data, f, indent=2, default=str)


def comment_for(cmd, ok, text):
    head = "Done." if ok else "That didn't go through."
    text = re.sub(r"\n{3,}", "\n\n", text or "")
    return "%s\n\n```\n%s\n```\n\n_Command:_ `%s`" % (head, text[-6000:] or "(no output)", " ".join(cmd))
