"""The GitHub side: commands sent as issues, and the Pages site."""
import contextlib
import html
import io
import json
import os
import re
import shlex
import shutil
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

STATIC = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "static")

EXTRA_CSS = """
.tiles{display:grid;grid-template-columns:1fr;gap:10px;margin-top:14px}
@media (min-width:640px){.tiles{grid-template-columns:repeat(3,1fr)}}
a.tile{display:block;background:var(--panel);border:1px solid var(--line);border-radius:14px;padding:14px 16px;color:var(--ink);text-decoration:none}
a.tile .k{font-size:13px;font-weight:650;color:var(--dim)}
a.tile .v{font-size:26px;font-weight:800;margin:2px 0;font-variant-numeric:tabular-nums}
a.tile .s{font-size:13px;color:var(--dim)}
.actions{display:grid;grid-template-columns:1fr 1fr;gap:10px;margin-top:12px}
.actions .btn{width:100%}
details.how{margin-top:16px;background:var(--panel);border:1px solid var(--line);border-radius:14px;padding:12px 16px}
details.how summary{font-weight:650;cursor:pointer}
details.how ol{color:var(--dim);font-size:14px;line-height:1.65;padding-left:20px;margin:8px 0 2px}
.kpis{display:grid;grid-template-columns:1fr 1fr;gap:10px;margin-top:12px}
@media (min-width:640px){.kpis{grid-template-columns:repeat(4,1fr)}}
.kpi{background:var(--panel);border:1px solid var(--line);border-radius:14px;padding:12px 14px}
.kpi .k{font-size:12.5px;color:var(--dim);font-weight:600}
.kpi .v{font-size:24px;font-weight:800;font-variant-numeric:tabular-nums}
.kpi .s{font-size:12px;color:var(--faint)}
ul.break{list-style:none;margin:0;padding:0;background:var(--panel);border:1px solid var(--line);border-radius:14px}
ul.break li{display:flex;justify-content:space-between;gap:10px;padding:10px 14px;border-bottom:1px solid var(--line);font-size:14px}
ul.break li:last-child{border-bottom:0}
ul.break li span:last-child{color:var(--dim);font-variant-numeric:tabular-nums;text-align:right}
.bet{padding:12px 14px}
.bet ul{list-style:none;margin:8px 0 0;padding:0}
.bet li{font-size:13.5px;padding:6px 0;border-top:1px solid var(--line)}
.bet li:first-child{border-top:0}
.res{display:grid;grid-template-columns:repeat(3,1fr);gap:8px;margin-top:10px}
.res .btn{width:100%;min-height:46px}
.res .btn.win{background:var(--accent);color:var(--accent-ink);border-color:var(--accent)}
.badge{font-size:12px;font-weight:700;border-radius:6px;padding:2px 8px;background:var(--chip);color:var(--dim)}
.badge.win{background:var(--accent-bg);color:var(--accent)}.badge.loss{background:var(--bad-bg);color:var(--bad)}
"""

AGO_JS = """<script>document.querySelectorAll('[data-ago]').forEach(el=>{const m=Math.round((Date.now()-Date.parse(el.dataset.ago))/60000);
el.textContent=m<1?'just now':m<60?m+' min ago':Math.floor(m/60)+'h '+(m%60)+'m ago';});</script>"""


def _page(title, active, content, web):
    return (render.head(title, web=True).replace("</style>", EXTRA_CSS + "</style>") +
            '<body><header class="bar"><div class="wrap">%s</div></header><main class="wrap">%s</main>%s</body></html>' % (
                render.nav_html(active, web), content, AGO_JS))


def _when(iso):
    return local(parse_iso(iso)).strftime("%a %b %d, %I:%M %p").replace(" 0", " ")


def copy_static(out_dir):
    if not os.path.isdir(STATIC):
        return
    for name in os.listdir(STATIC):
        shutil.copyfile(os.path.join(STATIC, name), os.path.join(out_dir, name))


def build_site(con, cfg, out_dir, now=None, status=None):
    """Write index.html, nba.html, nfl.html and bets.html into out_dir."""
    now = now or utcnow()
    repo = cfg["github"]["repo"]
    web = {"repo": repo}
    os.makedirs(out_dir, exist_ok=True)
    copy_static(out_dir)
    offsets = " and ".join(str(o) for o in cfg["auto"]["board_offsets_min"])
    tiles = []
    for lg in ("nba", "nfl"):
        try:
            b = boardmod.build(con, cfg, lg, now=now)
        except SystemExit:
            b = None
        if b is None:
            page = _page("Edge Finder " + lg.upper(), lg,
                         '<h1>Edge Finder · %s</h1><div class="empty">No %s lines pulled yet. Each game is pulled about '
                         '%s minutes before tip.</div>' % (lg.upper(), lg.upper(), offsets), web)
            tiles.append((lg, "—", "No board yet"))
        else:
            boardmod.save_codes(con, b)
            page = render.render(b, cfg, "", web=web)
            fl = sum(1 for s in ("pickem", "fliff", "kalshi") for x in b[s] if x["flagged"])
            tiles.append((lg, "%d flagged" % fl, '%d games · pulled <span data-ago="%s"></span>' % (b["games"], E(b["pull"]["ts"]))))
        with open(os.path.join(out_dir, "%s.html" % lg), "w") as f:
            f.write(page)

    with open(os.path.join(out_dir, "bets.html"), "w") as f:
        f.write(bets_page(con, cfg, web, now))

    s = betlog.clv_summary(con, cfg, now=now)
    open_n = con.execute("SELECT COUNT(*) AS n FROM bets WHERE result IS NULL").fetchone()["n"]
    clv_txt = ("%+.1f pts avg CLV · %d legs" % (100 * s["all"]["avg"], s["all"]["n"])) if s["all"] else "No closed legs yet"
    last = con.execute("SELECT * FROM pulls ORDER BY id DESC LIMIT 1").fetchone()
    credits = last["credits_remaining"] if last and last["credits_remaining"] is not None else None
    tile_html = "".join('<a class="tile" href="%s.html"><div class="k">%s</div><div class="v">%s</div><div class="s">%s</div></a>' % (
        lg, lg.upper(), E(v), sub) for lg, v, sub in tiles)
    tile_html += ('<a class="tile" href="bets.html"><div class="k">Bets &amp; CLV</div><div class="v">%d open</div>'
                  '<div class="s">%s</div></a>' % (open_n, E(clv_txt)))
    content = """<h1>Edge Finder</h1>
<div class="sub">Updated <span data-ago="%(upd)s"></span>%(cred)s</div>
<div class="tiles">%(tiles)s</div>
<div class="actions">
<a class="btn ghost" href="%(rn)s" target="_blank" rel="noopener">Refresh NBA now</a>
<a class="btn ghost" href="%(rf)s" target="_blank" rel="noopener">Refresh NFL now</a>
</div>
<div class="sub" style="margin-top:6px">Refresh when lineup news breaks. Each refresh costs credits; Submit the issue it opens.</div>
<details class="how"><summary>How it works</summary><ol>
<li>Every 15 minutes, GitHub pulls each game about %(off)s minutes before tip and prices every line against the sharp books.</li>
<li>Open a board, tap the picks you actually play, then <b>Log bet on GitHub</b> and <b>Submit</b>. It's recorded within a couple of minutes.</li>
<li>Closing lines are saved automatically before each game you bet. Tap Win / Loss / Push on <a href="bets.html">Bets</a> when it settles.</li>
<li>On NFL game days it runs Gridiron Edge itself and shows its read on each pick.</li>
<li>Add to your Home Screen: Share → <b>Add to Home Screen</b>. It opens full screen like an app.</li>
</ol></details>
<div class="foot">%(status)s</div>""" % {
        "upd": E(iso_now(now)),
        "cred": (" · %s Odds API credits left" % credits) if credits is not None else "",
        "tiles": tile_html,
        "rn": E(issue_url(repo, "refresh nba", "```\nrefresh nba\n```\nSubmit to re-pull tonight's NBA lines.")),
        "rf": E(issue_url(repo, "refresh nfl", "```\nrefresh nfl\n```\nSubmit to re-pull NFL lines.")),
        "off": offsets, "status": E(status or ""),
    }
    with open(os.path.join(out_dir, "index.html"), "w") as f:
        f.write(_page("Edge Finder", "index", content, web))
    with open(os.path.join(out_dir, ".nojekyll"), "w") as f:
        f.write("")
    return out_dir


def iso_now(now):
    return now.strftime("%Y-%m-%dT%H:%M:%SZ")


def _kpi(k, v, s="", cls=""):
    return '<div class="kpi"><div class="k">%s</div><div class="v %s">%s</div><div class="s">%s</div></div>' % (k, cls, v, s)


def _break(title, rows):
    if not rows:
        return ""
    items = "".join("<li><span>%s</span><span>%d legs · <b class=\"%s\">%+.1f</b> · %.0f%% your way</span></li>" % (
        E(name), st["n"], "pos" if st["avg"] > 0 else "neg", 100 * st["avg"], 100 * st["pos"]) for name, st in rows)
    return "<h2>%s</h2><ul class=\"break\">%s</ul>" % (title, items)


def bets_page(con, cfg, web, now):
    repo = web["repo"]
    s = betlog.clv_summary(con, cfg, now=now)
    r = s["results"]
    a = s["all"]
    parts = ["<h1>Bets &amp; CLV</h1>",
             '<div class="sub">CLV = the sharp market\'s fair chance for your pick at close minus when you placed it. '
             "Positive and steady is the earliest real sign of an edge. Keep stakes at $1&ndash;5 until it holds over a few "
             "hundred bets.</div>"]
    kp = [
        _kpi("Avg CLV", "%+.1f" % (100 * a["avg"]) if a else "—", "pts per leg", ("pos" if a and a["avg"] > 0 else "neg") if a else ""),
        _kpi("Moved your way", "%.0f%%" % (100 * a["pos"]) if a else "—", "of closed legs"),
        _kpi("Closed legs", str(a["n"]) if a else "0", "aim for a few hundred"),
        _kpi("Net", ("%+.2f" % r["net"]) if r["n"] else "—", ("%d settled · %+.1f%%" % (r["n"], 100 * (r["roi"] or 0))) if r["n"] else "nothing settled",
             ("pos" if r["net"] >= 0 else "neg") if r["n"] else ""),
    ]
    parts.append('<div class="kpis">%s</div>' % "".join(kp))
    if s["ge"]:
        parts.append(_break("Gridiron Edge as a second opinion <small>NFL legs</small>", [("GE " + k, v) for k, v in s["ge"]]))
    parts.append(_break("By app", s["books"]))
    parts.append(_break("By week", s["weeks"][-8:]))

    bets = con.execute("SELECT * FROM bets ORDER BY id DESC LIMIT 200").fetchall()
    open_cards, done_cards = [], []
    for b in bets:
        legs = con.execute("SELECT * FROM bet_legs WHERE bet_id=? ORDER BY leg", (b["id"],)).fetchall()
        li = []
        for l in legs:
            close = ""
            if l["close_fair_p"] is not None:
                d = l["close_fair_p"] - l["fair_p"]
                close = ' → %s <b class="%s">%+.1f</b>' % (pct(l["close_fair_p"]), "pos" if d >= 0 else "neg", 100 * d)
            li.append("<li><b>%s</b> %s %g %s<div class=\"meta\">fair %s%s</div></li>" % (
                E(l["player"]), "Over" if l["side"] == "over" else "Under", l["point"], E(market_label(l["market"])),
                pct(l["fair_p"]), close))
        start = min((l["commence_time"] for l in legs if l["commence_time"]), default=None)
        et = cfg.entries(b["book"]).get(b["entry_type"] or "", {}).get("label") if b["book"] in cfg.pickem_books else None
        label = et or "%s · %s" % (BOOK_LABELS.get(b["book"], b["book"]),
                                   {"kalshi": "%s contracts" % int(b["contracts"] or 0), "straight": "straight"}.get(b["entry_type"], b["entry_type"] or ""))
        top = '<div class="row1"><b>#%d %s</b><span class="big">$%.2f</span></div>' % (b["id"], E(label), b["stake"] or 0)
        meta = '<div class="meta">Placed %s%s</div>' % (E(_when(b["placed_at"])), (" · starts " + E(local_label(start))) if start else "")
        if b["result"]:
            badge = '<span class="badge %s">%s · $%.2f</span>' % (E(b["result"]), E(b["result"]).title(), b["payout"] or 0)
            done_cards.append('<div class="card bet">%s%s<div class="meta">%s</div><ul>%s</ul></div>' % (top, meta, badge, "".join(li)))
        else:
            btns = "".join('<a class="btn %s" target="_blank" rel="noopener" href="%s">%s</a>' % (
                "win" if o == "win" else "ghost",
                E(issue_url(repo, "result %d %s" % (b["id"], o), "```\nresult %d %s\n```\nSubmit to record it." % (b["id"], o))),
                o.title()) for o in ("win", "loss", "push"))
            open_cards.append('<div class="card bet">%s%s<ul>%s</ul><div class="res">%s</div></div>' % (top, meta, "".join(li), btns))
    parts.append("<h2>Open <small>flex entry that partly hit? open an issue titled <code>result 12 partial --hits 4</code></small></h2>")
    parts.append('<div class="grid">%s</div>' % "".join(open_cards) if open_cards else '<div class="empty">No open bets.</div>')
    parts.append("<h2>Settled</h2>")
    parts.append('<div class="grid">%s</div>' % "".join(done_cards[:60]) if done_cards else '<div class="empty">Nothing settled yet.</div>')
    return _page("Edge Finder bets", "bets", "\n".join(parts), web)


def write_json(path, data):
    with open(path, "w") as f:
        json.dump(data, f, indent=2, default=str)


def comment_for(cmd, ok, text):
    head = "Done." if ok else "That didn't go through."
    text = re.sub(r"\n{3,}", "\n\n", text or "")
    return "%s\n\n```\n%s\n```\n\n_Command:_ `%s`" % (head, text[-6000:] or "(no output)", " ".join(cmd))
