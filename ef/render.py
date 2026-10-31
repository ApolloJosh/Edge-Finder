"""The board as a self-contained page, built phone-first: cards, a sticky
filter bar, and a bottom sheet for logging. Also writes a CSV of every row."""
import csv
import html
import json
import os

from .board import BOOK_LABELS, market_label
from .util import fmt_american, local, parse_iso, pct
from .webjs import SHEET_CSS
from .webjs import script as ef_script

E = html.escape

CSS = """
:root{color-scheme:dark;--bg:#0e1218;--panel:#151a22;--raise:#1c2230;--line:#252d3a;--ink:#f2f5f9;--dim:#9ea8b8;--faint:#6c7789;
--accent:#2fd68e;--accent-ink:#04230f;--accent-bg:rgba(47,214,142,.13);--warn:#f4b544;--warn-bg:rgba(244,181,68,.13);
--bad:#ff6f6f;--bad-bg:rgba(255,111,111,.13);--chip:#1c2230;--sel:rgba(47,214,142,.07);--shadow:0 -10px 30px rgba(0,0,0,.55);
--r:16px}
*{box-sizing:border-box;-webkit-tap-highlight-color:transparent}
[hidden]{display:none!important}
html{-webkit-text-size-adjust:100%;background:var(--bg)}
body{margin:0;background:var(--bg);color:var(--ink);font:15px/1.45 -apple-system,BlinkMacSystemFont,"SF Pro Text","Segoe UI",Roboto,sans-serif;
-webkit-font-smoothing:antialiased;padding-bottom:calc(24px + env(safe-area-inset-bottom))}
body.docked{padding-bottom:calc(250px + env(safe-area-inset-bottom))}
a{color:var(--accent);text-decoration:none}
:focus-visible{outline:2px solid var(--accent);outline-offset:2px}
.wrap{max-width:1100px;margin:0 auto;padding:0 16px}
header.bar{position:sticky;top:0;z-index:20;background:rgba(14,18,24,.92);-webkit-backdrop-filter:blur(14px);backdrop-filter:blur(14px);
padding:calc(8px + env(safe-area-inset-top)) 0 8px;border-bottom:1px solid var(--line)}
nav.top{display:flex;gap:4px;overflow-x:auto;scrollbar-width:none;margin:0 -4px;align-items:center}
nav.top::-webkit-scrollbar{display:none}
nav.top a{flex:none;color:var(--dim);font-size:14.5px;font-weight:650;padding:8px 12px;border-radius:999px}
nav.top a.on{background:var(--ink);color:var(--bg)}
nav.top a.gear{margin-left:auto;font-size:17px;padding:6px 10px;color:var(--dim)}
.controls{display:flex;gap:8px;align-items:center;margin-top:10px;overflow-x:auto;scrollbar-width:none;padding-bottom:2px}
.controls::-webkit-scrollbar{display:none}
.seg{display:flex;background:var(--panel);border:1px solid var(--line);border-radius:999px;padding:3px;flex:none}
.seg button{border:0;background:transparent;color:var(--dim);font:inherit;font-size:13.5px;font-weight:650;padding:6px 13px;border-radius:999px;min-height:34px}
.seg button.on{background:var(--raise);color:var(--ink)}
.chip{flex:none;border:1px solid var(--line);background:transparent;color:var(--dim);font:inherit;font-size:13.5px;font-weight:650;
padding:6px 13px;border-radius:999px;min-height:36px;white-space:nowrap}
.chip.on{background:var(--ink);color:var(--bg);border-color:var(--ink)}
select{font:inherit;font-size:14px;font-weight:600;padding:6px 10px;border:1px solid var(--line);border-radius:999px;background:var(--panel);
color:var(--ink);min-height:36px}
h1{font-size:30px;font-weight:800;margin:18px 0 2px;letter-spacing:-.02em}
h2{font-size:17px;font-weight:750;margin:26px 0 10px;display:flex;align-items:center;gap:8px;flex-wrap:wrap}
h2 small{font-weight:500;color:var(--faint);font-size:13px}
.titlerow{display:flex;align-items:center;gap:10px}
.titlerow h1{margin-bottom:2px}
.sub{color:var(--dim);font-size:13.5px}
.dim{color:var(--faint)}
.pos{color:var(--accent)}.neg{color:var(--bad)}
button.info{width:22px;height:22px;min-height:0;padding:0;border-radius:50%;border:1.5px solid var(--faint);background:transparent;
color:var(--dim);font:italic 700 12px/1 Georgia,serif;display:inline-grid;place-items:center;vertical-align:2px;flex:none}
.grid{display:grid;grid-template-columns:1fr;gap:10px}
@media (min-width:760px){.grid{grid-template-columns:1fr 1fr}}
.card{background:var(--panel);border:1px solid transparent;border-radius:var(--r);overflow:hidden}
.card.on{border-color:var(--accent);background:linear-gradient(var(--sel),var(--sel)),var(--panel)}
.card.dimrow{opacity:.62}
label.pick{display:flex;gap:12px;padding:14px 14px 12px;cursor:pointer}
label.pick input{position:absolute;opacity:0;pointer-events:none}
.box{flex:none;width:24px;height:24px;border-radius:50%;border:2px solid var(--faint);margin-top:2px;display:grid;place-items:center}
.card.on .box{background:var(--accent);border-color:var(--accent)}
.card.on .box:after{content:"";width:6px;height:11px;border:solid var(--accent-ink);border-width:0 2.5px 2.5px 0;transform:rotate(45deg) translate(-1px,-1px)}
.main{flex:1;min-width:0}
.row1{display:flex;justify-content:space-between;align-items:flex-start;gap:10px}
.who{font-weight:750;font-size:16.5px;white-space:nowrap;overflow:hidden;text-overflow:ellipsis;letter-spacing:-.01em}
.what{font-size:14.5px;margin-top:2px;color:var(--dim)}
.what b{font-weight:700;color:var(--ink)}
.score{flex:none;min-width:52px;text-align:center;border-radius:12px;padding:5px 6px 4px;background:var(--raise);color:var(--dim)}
.score b{display:block;font-size:22px;font-weight:850;line-height:1;font-variant-numeric:tabular-nums;letter-spacing:-.02em}
.score small{display:block;font-size:10px;font-weight:650;margin-top:2px;opacity:.8}
.score.mid{background:var(--accent-bg);color:var(--accent)}
.score.hi{background:var(--accent);color:var(--accent-ink)}
.nums{display:flex;flex-wrap:wrap;gap:6px 14px;margin-top:9px;font-size:13px;color:var(--dim);font-variant-numeric:tabular-nums}
.nums span b{color:var(--ink);font-weight:700}
.nums span b.pos{color:var(--accent)}.nums span b.neg{color:var(--bad)}
.side{flex:none;display:flex;flex-direction:column;align-items:center;gap:6px}
.betamt{font-size:12.5px;font-weight:800;color:var(--accent);white-space:nowrap}
.meta{font-size:12.5px;color:var(--dim);margin-top:3px;font-variant-numeric:tabular-nums}
.tag{display:inline-block;border-radius:6px;padding:0 6px;font-size:11.5px;font-weight:700;line-height:18px;vertical-align:1px}
.tag.agree{background:var(--accent-bg);color:var(--accent)}
.tag.conflict{background:var(--bad-bg);color:var(--bad)}
.tag.neutral,.tag.adj{background:var(--raise);color:var(--dim)}
.tag.biased,.tag.warn{background:var(--warn-bg);color:var(--warn)}
details.sharp{border-top:1px solid var(--line);font-size:12.5px;color:var(--dim)}
details.sharp summary{padding:9px 14px 9px 50px;cursor:pointer;list-style:none;color:var(--faint)}
details.sharp summary::-webkit-details-marker{display:none}
details.sharp summary:after{content:" ▾"}
details.sharp[open] summary:after{content:" ▴"}
details.sharp div{padding:0 14px 12px 50px;line-height:1.65}
.gamehead{font-size:13px;font-weight:700;color:var(--dim);margin:18px 2px 8px;display:flex;justify-content:space-between}
.gamehead:first-child{margin-top:4px}
.empty{background:var(--panel);border-radius:var(--r);padding:16px;color:var(--dim);font-size:14px}
.empty.slim{padding:12px 14px;font-size:13.5px}
.more{width:100%;margin-top:10px}
details.entries{margin-top:16px;background:var(--panel);border-radius:var(--r);padding:12px 14px}
details.entries summary{font-weight:700;cursor:pointer;list-style:none;display:flex;justify-content:space-between;align-items:center}
details.entries summary::-webkit-details-marker{display:none}
details.entries summary:after{content:"▾";color:var(--faint)}
details.entries[open] summary:after{content:"▴"}
.entry{padding:12px 0 2px;border-top:1px solid var(--line);margin-top:10px}
.entry .row1 b{font-size:15px}
.entry ol{margin:6px 0 10px;padding-left:20px;font-size:13.5px;color:var(--dim)}
.entry ol b{color:var(--ink)}
.budget{display:flex;align-items:center;gap:10px;margin:12px 0 14px;background:var(--panel);border-radius:var(--r);padding:11px 14px}
.budget .bar{flex:1;height:6px;border-radius:3px;background:var(--raise);overflow:hidden}
.budget .bar i{display:block;height:100%;background:var(--accent);border-radius:3px}
.budget .txt{font-size:13.5px;color:var(--dim);white-space:nowrap}
.budget .txt b{color:var(--ink)}
button,.btn{font:inherit;font-weight:700;font-size:15px;border-radius:999px;border:1px solid var(--accent);background:var(--accent);
color:var(--accent-ink);padding:10px 16px;min-height:46px;cursor:pointer;display:inline-flex;align-items:center;justify-content:center}
button.ghost,.btn.ghost{background:transparent;color:var(--ink);border-color:var(--line)}
button.link{background:none;border:0;color:var(--accent);padding:6px 4px;min-height:0;font-weight:650}
button:disabled{opacity:.45;cursor:default}
.btn.off{pointer-events:none;opacity:.4}
#dock{position:fixed;left:0;right:0;bottom:0;z-index:30;background:var(--panel);border-top:1px solid var(--line);
box-shadow:var(--shadow);border-radius:22px 22px 0 0;transform:translateY(110%);transition:transform .18s ease}
#dock.on{transform:none}
.dock-in{max-width:640px;margin:0 auto;padding:14px 16px calc(12px + env(safe-area-inset-bottom))}
.d1{display:flex;justify-content:space-between;align-items:center;font-weight:700}
.d2{display:flex;gap:10px;margin-top:10px;align-items:center}
.d2 select{flex:1;min-height:46px}
.stepper{display:flex;align-items:center;border:1px solid var(--line);border-radius:999px;overflow:hidden;background:var(--bg)}
.stepper button{background:transparent;color:var(--ink);border:0;border-radius:0;min-width:46px;font-size:20px;padding:0}
.stepper span{min-width:52px;text-align:center;font-weight:800;font-variant-numeric:tabular-nums}
.d3{margin-top:9px;font-size:13.5px;color:var(--dim);min-height:19px}
.kp[hidden]{display:none}
.kp{display:flex;align-items:center;gap:7px;font-weight:650;color:var(--dim)}
.kp input{width:84px;min-height:46px;font:inherit;font-size:16px;font-weight:700;text-align:center;border:1px solid var(--line);
border-radius:999px;background:var(--bg);color:var(--ink)}
.d4{display:flex;gap:8px;margin-top:12px}
.d4 .btn,.d4 button{flex:1}
.cmd{margin-top:8px;font:11.5px ui-monospace,Menlo,monospace;color:var(--faint);overflow-x:auto;white-space:nowrap}
.foot{color:var(--faint);font-size:12.5px;margin-top:28px;line-height:1.6}
table{border-collapse:collapse;width:100%;font-size:13.5px;font-variant-numeric:tabular-nums}
th{text-align:left;font-weight:600;color:var(--dim);font-size:12px;padding:8px 10px;border-bottom:1px solid var(--line)}
td{padding:8px 10px;border-bottom:1px solid var(--line)}
tr:last-child td{border-bottom:none}
td.num,th.num{text-align:right}
.tablewrap{overflow-x:auto;background:var(--panel);border-radius:var(--r)}
@media (prefers-reduced-motion:reduce){*{transition:none!important;animation:none!important}}
"""

ICONS = """<meta name="theme-color" content="#0e1218">
<meta name="apple-mobile-web-app-capable" content="yes">
<meta name="mobile-web-app-capable" content="yes">
<meta name="apple-mobile-web-app-title" content="Edge Finder">
<meta name="apple-mobile-web-app-status-bar-style" content="black-translucent">
<link rel="manifest" href="manifest.webmanifest">
<link rel="icon" type="image/png" sizes="192x192" href="icon-192.png">
<link rel="apple-touch-icon" href="apple-touch-icon.png">"""


def head(title, web=True):
    return ('<!doctype html><html lang="en"><head><meta charset="utf-8">'
            '<meta name="viewport" content="width=device-width,initial-scale=1,viewport-fit=cover">'
            '<title>%s</title>%s<style>%s%s</style></head>' % (E(title), ICONS if web else "", CSS, SHEET_CSS if web else ""))


def nav_html(active, web):
    links = [("index", "Home"), ("nba", "NBA"), ("nfl", "NFL"), ("check", "Check"), ("bets", "Results")]
    return '<nav class="top">%s<a href="#settings" id="navset" class="gear" aria-label="Settings">⚙︎</a></nav>' % "".join(
        '<a href="%s.html"%s>%s</a>' % (k, ' class="on"' if k == active else "", E(t)) for k, t in links)


# --------------------------------------------------------------- small table helpers (Bets page)


def _td(text, v=None, cls=None):
    attrs = ""
    if cls:
        attrs += ' class="%s"' % cls
    if v is not None:
        attrs += ' data-v="%s"' % E(str(v))
    return "<td%s>%s</td>" % (attrs, text)


def _table(head_cells, rows, empty):
    if not rows:
        return '<div class="empty">%s</div>' % empty
    ths = "".join('<th%s>%s</th>' % (' class="num"' if n else "", h) for h, n in head_cells)
    return '<div class="tablewrap"><table><thead><tr>%s</tr></thead><tbody>%s</tbody></table></div>' % (ths, "".join(rows))


# --------------------------------------------------------------- board data


def _pick_text(x):
    if x["book"] == "kalshi":
        return ("YES %g+" if x["side"] == "over" else "NO on %g+") % (x["point"] + 0.5)
    return "%s %g" % ("Over" if x["side"] == "over" else "Under", x["point"])


SHOW_ALL_LIMIT = 150   # per section, so "All" stays quick on a phone


def _row(x, sec, nfl):
    d = {"c": x["code"], "s": sec, "f": bool(x["flagged"]), "b": x["book"], "ev": x["event_id"],
         "bl": BOOK_LABELS.get(x["book"], x["book"]), "pl": x["player"], "g": x["game"], "t": x["commence"],
         "m": market_label(x["market"]), "pk": _pick_text(x), "p": round(x["p"], 4), "ex": bool(x["exact"]),
         "gap": x["gap"], "n": x["n_sharp"], "sh": x["sharp"],
         "sc": x.get("score", 0), "k": round(x.get("kelly", -1), 4),
         "e": None if x.get("ev_pct") is None else round(x["ev_pct"], 4),
         "pb": round(x.get("p_blend", x["p"]), 4)}
    if sec == "pickem":
        d.update(bar=round(x["breakeven"] or 0, 4), cl=x["clears"])
        if x["multiplier"] and abs(x["multiplier"] - 1) > 1e-9:
            d["mu"] = x["multiplier"]
    elif sec == "fliff":
        d.update(pr=fmt_american(x["price"]))
    else:
        d.update(ask=x["ask"], fee=round(x["fee"], 4), sz=x["size"])
    if x.get("ge_p") is not None:
        d.update(gp=round(x["ge_p"], 3), gt=x["ge_tag"], gs=x.get("ge_score"))
    if x.get("proj") is not None:
        d["pj"] = x["proj"]
    return d


def notes(board, cfg):
    out = []
    counts = board["counts"]
    for b in cfg.pickem_books + cfg.sportsbooks:
        if not counts.get(b):
            out.append("No %s lines in the latest pull (not posted yet, or not in the feed)." % BOOK_LABELS.get(b, b))
    if not any(counts.get(b) for b in cfg.sharp_weights):
        out.append("No sharp-book prices came back, so nothing could be priced.")
    if board["league"] == "nba" and not board.get("model_ready"):
        out.append("Full Court Edge has no box scores yet. It fills itself in over the next few scheduled runs.")
    for book in cfg.pickem_books:
        if any(e.get("verify") for e in cfg.entries(book).values()):
            out.append("%s payouts in config.json are placeholders - check the app and fix them." % BOOK_LABELS.get(book, book))
    if board["league"] == "nfl":
        if not board["ge_rows"]:
            out.append("No Gridiron Edge read loaded yet. On game days it loads itself; or upload an export to the repo's inputs folder.")
        else:
            out.append("'runs high' marks markets where Gridiron Edge's median sits too high "
                       "(Pass Yds, Pass+Rush, Rush+Rec, RB receptions, TE Rec Yds); those don't move the score.")
    out.append("Entries assume picks are independent, so suggested entries use one pick per game.")
    return out


def payload(board, cfg, root, web):
    nfl = board["league"] == "nfl"
    rows = []
    for sec in ("pickem", "fliff", "kalshi"):
        items = board[sec]
        keep = [x for x in items if x["flagged"]]
        rest = [x for x in items if not x["flagged"]][:SHOW_ALL_LIMIT]
        rows += [_row(x, sec, nfl) for x in keep + rest]
    entries = [{"b": e["book"], "bl": BOOK_LABELS.get(e["book"], e["book"]), "id": e["entry"], "label": e["label"],
                "roi": round(e["roi"], 4), "verify": e["verify"], "legs": [l["code"] for l in e["legs"]]}
               for e in board["entries"] if e["roi"] > 0][:6]
    types = {b: {k: {"label": v["label"], "picks": v["picks"], "pays": v["pays"]} for k, v in cfg.entries(b).items()}
             for b in cfg.pickem_books}
    th = cfg["thresholds"]
    be = []
    for book, t in board["breakevens"].items():
        be.append("%s: %s" % (BOOK_LABELS.get(book, book), ", ".join(
            "%s %s" % (e["label"].split(" ", 1)[-1], pct(b)) for _, (e, b) in sorted(t.items(), key=lambda q: q[1][1]))))
    pull = board["pull"]
    return {
        "league": board["league"], "nfl": nfl, "built": board["built_at"], "pulled": pull["ts"],
        "credits": pull.get("credits_remaining"), "repo": web["repo"] if web else None, "root": root,
        "rows": rows, "entries": entries, "types": types, "notes": notes(board, cfg), "be": " · ".join(be),
        "counts": {b: board["counts"].get(b, 0) for b in ("prizepicks", "underdog", "fliff", "kalshi")},
        "geSaved": board.get("ge_saved"), "games": board["games"],
        "th": {"cush": th["pickem_cushion"], "fliff": th["fliff_min_ev"], "kalshi": th["kalshi_min_ev"],
               "kmin": cfg["kalshi"].get("min_size", 0),
               "minb": 1 if th.get("one_book_ok") else th["min_sharp_books"]},
        "model": board.get("model"), "modelShort": "GE" if nfl else "FCE", "modelReady": board.get("model_ready"),
        "weight": cfg.get("model", {}).get("weight", 0.25),
        "budget": cfg.get("budget", {"daily": 25, "nfl_sunday": 40, "max_share": 0.25}),
    }


# --------------------------------------------------------------- page

BODY = """<body>
<header class="bar"><div class="wrap">
%(nav)s
<div class="controls">
<div class="seg" id="view"><button data-v="flag" class="on">Edges&nbsp;<span id="nflag"></span></button><button data-v="all">All</button></div>
<select id="sort" aria-label="Sort"><option value="sc">Best score</option><option value="e">Biggest edge</option><option value="g">By game</option><option value="t">Start time</option><option value="pl">Player</option></select>
<button class="chip on" data-app="all">All apps</button>
<button class="chip" data-app="prizepicks">PrizePicks</button>
<button class="chip" data-app="underdog">Underdog</button>
<button class="chip" data-app="kalshi">Kalshi</button>
<button class="chip" data-app="fliff">Fliff</button>
</div></div></header>
<main class="wrap">
<div class="titlerow"><h1 id="title"></h1><button class="info" data-info="board" aria-label="How the board works">i</button></div>
<div class="sub" id="when"></div>
<div class="budget" id="budget" role="button" tabindex="0" aria-label="Today's budget"></div>
<details class="entries" id="sec-entries"><summary><span>Best pick'em entries <span class="dim" id="nent"></span></span></summary><div id="entries"></div></details>
<div id="list"></div>
<div class="foot" id="foot"></div>
</main>
<div id="dock" aria-live="polite"><div class="dock-in">
<div class="d1"><span id="dsum"></span><button class="link" id="clear">Clear</button></div>
<div class="d2"><select id="entry" aria-label="Entry type"></select>
<div class="stepper" id="sstep"><button id="minus" aria-label="Less">−</button><span>$<b id="stake">1</b></span><button id="plus" aria-label="More">+</button></div>
<label class="kp" id="kbuy" hidden><input id="ks" type="number" inputmode="decimal" min="0.01" step="0.01" aria-label="Shares Kalshi filled"> shares</label></div>
<div class="d3" id="dexp"></div>
<div class="d4">%(primary)s<button class="ghost" id="copy">Copy</button></div>
<div class="cmd" id="cmd"></div>%(fallback)s
</div></div>
%(efjs)s<script>const D = %(data)s;</script>
<script>%(js)s</script>
</body></html>"""

JS = r"""
(function(){
const $ = (s, el) => (el || document).querySelector(s);
const $$ = (s, el) => [...(el || document).querySelectorAll(s)];
const esc = s => String(s == null ? '' : s).replace(/[&<>"']/g, c => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
const pct = (p, d = 1) => (p * 100).toFixed(d) + '%';
const sgn = (x, d = 1) => (x >= 0 ? '+' : '−') + Math.abs(x).toFixed(d);
const now = Date.now();
const live = D.rows.filter(r => !r.t || Date.parse(r.t) > now);
const byCode = new Map(live.map(r => [r.c, r]));
const LG = D.league.toUpperCase();
const store = {get(k, d) { try { const v = localStorage.getItem(k); return v == null ? d : v; } catch (e) { return d; } },
               set(k, v) { try { localStorage.setItem(k, v); } catch (e) {} }};
let view = 'flag', app = 'all', sort = store.get('ef-sort', 'sc');
const picked = new Map();
let stake = 1, stakeAuto = true;
let ks = null, kkey = '';
const kShares = (s, p) => Math.floor(s / (p + 0.07 * p * (1 - p)) * 100 + 1e-6) / 100;

function ago(iso) {
  const m = Math.round((now - Date.parse(iso)) / 60000);
  if (m < 1) return 'just now';
  if (m < 60) return m + ' min ago';
  const h = Math.floor(m / 60);
  return h + 'h ' + (m % 60) + 'm ago';
}
function when(iso) {
  const d = new Date(iso);
  return d.toLocaleDateString(undefined, {weekday: 'short'}) + ' ' + d.toLocaleTimeString(undefined, {hour: 'numeric', minute: '2-digit'});
}
const clock = iso => new Date(iso).toLocaleTimeString(undefined, {hour: 'numeric', minute: '2-digit'});

// ---------- explanations behind the (i) buttons
const M = D.modelShort, MN = D.model;
window.INFO = {
  board: {t: 'How the board works', b: `<p>Every pick is priced against the sharp books: <b>Fair</b> is their chance of it hitting with the bookmaker's margin removed. Lines need ${D.th.minb} sharp books.</p>
<p><b>Edge</b> is how much better the app's price is than fair. <b>Edges</b> shows picks that clear the bar: Kalshi and Fliff at ${(D.th.kalshi * 100).toFixed(0)}%+, pick'em when fair beats an entry's per-pick breakeven by ${(D.th.cush * 100).toFixed(1)}+ points.</p>
<p><b>Score</b> (0–100) is the default order. It blends the edge with ${esc(MN)}'s read and favors picks likely to hit. Tap a score's <b>i</b> for more.</p>
<p><span class="tag adj">adj</span> means the nearest sharp line was a little off this one, so its price was moved here and trimmed for that.</p>
<p>Per-pick breakevens: ${esc(D.be)}.</p>` + (D.notes.length ? '<p><b>Notes</b></p><ul>' + D.notes.map(n => `<li>${esc(n)}</li>`).join('') + '</ul>' : '') +
     `<p>Judge it by closing line value, not early wins.</p>`},
  score: {t: 'Score', b: `<p>One number for how good a pick is, 0–100. It starts from the sharp fair chance, leans ${Math.round(D.weight * 100)}% toward ${esc(MN)}'s read when it has one, and asks how much of a bankroll the pick deserves at this price (the Kelly formula).</p>
<p>That rewards both a bigger edge and a better chance of hitting: at the same edge, a 58% pick scores higher than a 40% one, because it grows your money with fewer swings.</p>
<p>60+ is strong, 40–59 is solid, under 40 is thin.</p>`},
  model: {t: MN, b: D.nfl ? `<p>Gridiron Edge's own chance for the pick, from its weekly scan. <span class="tag agree">agrees</span> at 55%+, <span class="tag conflict">check news</span> at 45% or less. <span class="tag biased">runs high</span> marks markets where its median sits too high; those don't move the score.</p>`
    : `<p>Edge Finder's own NBA projection from ESPN box scores: recent minutes and per-minute production, adjusted for how much the opponent allows. <span class="tag agree">agrees</span> at 55%+, <span class="tag conflict">disagrees</span> at 45% or less.</p>
<p>It doesn't know about injuries or who's sitting tonight, so it's a second opinion: it moves the score ${Math.round(D.weight * 100)}% of the way toward its read. Results tracks whether it helps.</p>`},
  budget: {t: "Today's budget", b: `<p>Suggested stakes split what's left of today's budget across the best Kalshi and Fliff picks by score, with no more than ${Math.round(D.budget.max_share * 100)}% of the day on any one bet. Pick'em entries get a suggestion when you select them.</p>
<p>The budget is $${D.budget.daily} a day and $${D.budget.nfl_sunday} on NFL Sundays. Bets you've saved today come off the top. Tap the bar to change today's number.</p>`},
};

// ---------- header
$('#title').textContent = LG;
$('#when').innerHTML = `Lines from ${esc(ago(D.pulled))} · ${D.games} game${D.games === 1 ? '' : 's'}${D.credits != null ? ' · ' + D.credits + ' credits' : ''} · <button class="link" onclick="location.reload()">Reload</button>`;
const flagged = live.filter(r => r.f).length;
$('#sort').value = sort;

// ---------- budget
const today = new Date().toLocaleDateString('en-CA');
function defaultBudget() {
  const d = new Date(), m = d.getMonth() + 1;
  return d.getDay() === 0 && (m >= 9 || m <= 2) ? D.budget.nfl_sunday : D.budget.daily;
}
let budget = +store.get('ef-budget-' + today, defaultBudget()) || defaultBudget();
let spent = 0, alloc = new Map();
function allocate() {
  const rem = Math.max(0, budget - spent);
  const cap = Math.max(1, Math.floor(budget * D.budget.max_share));
  const seen = new Set(), top = [];
  for (const r of live.filter(r => r.f && r.s !== 'pickem' && r.k > 0).sort((a, b) => b.k - a.k)) {
    const key = r.pl + '|' + r.m;           // one bet per player and stat
    if (seen.has(key)) continue;
    seen.add(key); top.push(r);
    if (top.length >= 8) break;
  }
  const sum = top.reduce((s, r) => s + r.k, 0);
  const out = new Map();
  let left = Math.floor(rem);
  for (const r of top) {
    let amt = Math.min(cap, Math.round(rem * r.k / sum), left);
    if (amt >= 1) { out.set(r.c, amt); left -= amt; }
  }
  alloc = out;
  return {rem, cap, topK: sum};
}
function drawBudget() {
  const a = allocate();
  const used = Math.min(1, spent / budget);
  $('#budget').innerHTML = `<span class="txt">Today <b>$${budget}</b></span><span class="bar"><i style="width:${(100 * used).toFixed(0)}%"></i></span>` +
    `<span class="txt"><b>$${Math.max(0, budget - spent).toFixed(0)}</b> left</span><button class="info" data-info="budget" aria-label="About the budget">i</button>`;
  return a;
}
async function loadSpent() {
  try {
    const r = await fetch('bets-data.json?t=' + Date.now(), {cache: 'no-store'});
    if (!r.ok) return;
    const d = await r.json();
    const mine = d.bets.filter(b => new Date(b.placed).toLocaleDateString('en-CA') === today);
    const notes = new Set(d.bets.concat(d.deleted || []).map(b => b.note));
    const pend = window.EF ? EF.pending().filter(p => p.kind === 'bet' && p.stake && !notes.has('issue #' + p.n) &&
      new Date(p.ts).toLocaleDateString('en-CA') === today) : [];
    spent = mine.reduce((s, b) => s + b.stake, 0) + pend.reduce((s, p) => s + p.stake, 0);
    drawBudget(); draw(); dock();
  } catch (e) {}
}
$('#budget').onclick = async ev => {
  if (ev.target.closest('[data-info]') || !window.EF) return;
  const pr = EF.confirm({title: "Today's budget", ok: 'Save', cancel: 'Cancel', body:
    `<label class="fld">Budget for today ($) <input id="bg-v" type="number" inputmode="numeric" min="1" step="1" value="${budget}"></label>
<p>Only for today. Tomorrow goes back to $${D.budget.daily} ($${D.budget.nfl_sunday} on NFL Sundays).</p>`});
  if (!(await pr)) return;
  const v = parseInt($('#bg-v').value, 10);
  if (v >= 1) { budget = v; store.set('ef-budget-' + today, v); drawBudget(); draw(); dock(); }
};

// ---------- cards
function scoreCls(sc) { return sc >= 60 ? 'hi' : sc >= 40 ? 'mid' : ''; }
function card(r) {
  let what, extra;
  if (r.s === 'pickem') {
    what = `<b>${esc(r.pk)}</b> ${esc(r.m)} · ${esc(r.bl)}${r.mu ? ' ×' + r.mu : ''}`;
    extra = `Bar ${pct(r.bar)}${r.cl.length ? ' · clears ' + esc(r.cl.join(', ')) : ''}`;
  } else if (r.s === 'fliff') {
    what = `<b>${esc(r.pk)}</b> ${esc(r.m)} · Fliff ${esc(r.pr)}`;
    extra = '';
  } else {
    what = `<b>${esc(r.pk)}</b> ${esc(r.m)} · Kalshi ${Math.round(r.ask * 100)}¢`;
    extra = `Fee ${(r.fee * 100).toFixed(1)}¢ · ${r.sz == null ? '?' : Math.floor(r.sz)} on offer`;
  }
  const nums = [];
  if (r.e != null) nums.push(`<span>Edge <b class="${r.e >= 0 ? 'pos' : 'neg'}">${sgn(r.e * 100)}%</b></span>`);
  nums.push(`<span>Fair <b>${pct(r.p, 0)}</b></span>`);
  if (r.gp != null) {
    const lab = {agree: 'agrees', conflict: D.nfl ? 'check news' : 'disagrees', neutral: 'neutral', biased: 'runs high'}[r.gt];
    nums.push(`<span>${M} <b>${pct(r.gp, 0)}</b> <span class="tag ${r.gt}">${lab}</span></span>`);
  } else if (D.modelReady) nums.push(`<span class="dim">${M} no read</span>`);
  const amt = alloc.get(r.c);
  const detail = [`${esc(r.g)} · ${esc(when(r.t))} · #${esc(r.c)}`];
  if (extra) detail.push(extra);
  if (!r.ex) detail.push(`<span class="tag adj">adj ${r.gap}</span> moved from a sharp line ${r.gap} away`);
  if (r.pj != null) detail.push(`Full Court Edge projects ${r.pj}`);
  if (r.gs != null) detail.push(`Gridiron Edge EDGE score ${Math.round(r.gs)}`);
  detail.push(`Sharp lines: ${esc(r.sh)}`);
  const on = picked.has(r.c) ? ' on' : '';
  return `<div class="card${on}${r.f ? '' : ' dimrow'}" data-c="${esc(r.c)}">
<label class="pick"><input type="checkbox" ${on ? 'checked' : ''} aria-label="Select ${esc(r.pl)}"><span class="box"></span>
<div class="main"><div class="row1"><div style="min-width:0"><div class="who">${esc(r.pl)}</div><div class="what">${what}</div></div>
<div class="side"><span class="score ${scoreCls(r.sc)}"><b>${r.sc}</b><small>score</small></span>${amt ? `<span class="betamt">Bet $${amt}</span>` : ''}</div></div>
<div class="nums">${nums.join('')}</div></div></label>
<details class="sharp"><summary>Details</summary><div>${detail.join('<br>')}</div></details></div>`;
}

let shown = 60;
const CMP = {
  sc: (a, b) => b.k - a.k,
  e: (a, b) => (b.e ?? -9) - (a.e ?? -9),
  t: (a, b) => (a.t || '').localeCompare(b.t || '') || b.k - a.k,
  pl: (a, b) => a.pl.localeCompare(b.pl) || b.k - a.k,
  g: (a, b) => (a.t || '').localeCompare(b.t || '') || a.g.localeCompare(b.g) || b.k - a.k,
};
function draw() {
  const rows = live.filter(r => (view === 'all' || r.f) && (app === 'all' || r.b === app)).sort(CMP[sort]);
  $('#nflag').textContent = flagged;
  const list = rows.slice(0, shown);
  let h = '';
  if (!rows.length) {
    h = `<div class="empty">${view === 'flag' ? `Nothing clears the bar${app === 'all' ? '' : ' on ' + esc(app[0].toUpperCase() + app.slice(1))} right now. Edges tend to show up after lineup news, so a fresh Run from Home is worth it when news breaks. Or tap <b>All</b> to see everything ranked.` : 'No lines here in the latest pull.'}</div>`;
  } else if (sort === 'g') {
    let g = null;
    for (const r of list) {
      if (r.ev !== g) { if (g !== null) h += '</div>'; g = r.ev; h += `<div class="gamehead"><span>${esc(r.g)}</span><span>${esc(clock(r.t))}</span></div><div class="grid">`; }
      h += card(r);
    }
    h += '</div>';
  } else {
    h = '<div class="grid">' + list.map(card).join('') + '</div>';
  }
  if (rows.length > shown) h += `<button class="ghost more" data-more="1">Show ${Math.min(60, rows.length - shown)} more of ${rows.length - shown}</button>`;
  $('#list').innerHTML = h;
  const ents = D.entries.filter(e => (app === 'all' || e.b === app) && e.legs.every(c => byCode.has(c)));
  $('#sec-entries').style.display = ents.length ? '' : 'none';
  $('#nent').textContent = ents.length;
  $('#entries').innerHTML = ents.map(e => `<div class="entry"><div class="row1"><b>${esc(e.label)}</b>
<span class="pos" style="font-weight:800">${sgn(e.roi * 100)}% expected</span></div>
<div class="meta">${esc(e.bl)}${e.verify ? ' <span class="tag warn">verify payout</span>' : ''}</div>
<ol>${e.legs.map(c => { const r = byCode.get(c); return `<li><b>${esc(r.pl)}</b> ${esc(r.pk)} ${esc(r.m)} · ${pct(r.p)}</li>`; }).join('')}</ol>
<button class="ghost" data-entry="${esc(e.id)}" data-legs="${esc(e.legs.join(','))}" style="width:100%">Select these ${e.legs.length}</button></div>`).join('');
}

document.addEventListener('change', ev => {
  const cb = ev.target.closest('label.pick input');
  if (!cb) return;
  const cardEl = cb.closest('.card');
  const c = cardEl.dataset.c;
  if (cb.checked) picked.set(c, byCode.get(c)); else picked.delete(c);
  cardEl.classList.toggle('on', cb.checked);
  stakeAuto = true;
  dock();
});
document.addEventListener('click', ev => {
  if (ev.target.closest('[data-more]')) { shown += 60; draw(); return; }
  const sel = ev.target.closest('[data-legs]');
  if (sel) {
    picked.clear();
    sel.dataset.legs.split(',').forEach(c => picked.set(c, byCode.get(c)));
    stakeAuto = true;
    draw(); dock(sel.dataset.entry);
  }
});
$$('#view button').forEach(b => b.onclick = () => { view = b.dataset.v; shown = 60; $$('#view button').forEach(x => x.classList.toggle('on', x === b)); draw(); });
$$('[data-app]').forEach(b => b.onclick = () => { app = b.dataset.app; shown = 60; $$('[data-app]').forEach(x => x.classList.toggle('on', x === b)); draw(); });
$('#sort').onchange = e => { sort = e.target.value; store.set('ef-sort', sort); draw(); };

// ---------- bottom sheet
function pbin(ps) { let d = [1]; for (const p of ps) { const n = new Array(d.length + 1).fill(0); d.forEach((v, k) => { n[k] += v * (1 - p); n[k + 1] += v * p; }); d = n; } return d; }
function entryReturn(ps, pays, boost) { return pbin(ps).reduce((s, v, k) => s + v * (+(pays[String(k)] || 0)) * (k === ps.length ? boost : 1), 0); }
function entryKelly(ps, pays, boost) {
  const d = pbin(ps), n = ps.length;
  const R = d.map((v, k) => (+(pays[String(k)] || 0)) * (k === n ? boost : 1));
  const mean = d.reduce((s, v, k) => s + v * R[k], 0), ex2 = d.reduce((s, v, k) => s + v * R[k] * R[k], 0);
  const vr = ex2 - mean * mean;
  return vr > 0 ? (mean - 1) / vr : 0;
}
function suggest(legs, entry) {
  const a = allocate();
  if (a.rem < 1) return 0;
  if (entry) {
    const f = entryKelly(legs.map(r => r.pb), entry.pays, legs.reduce((b, r) => b * (r.mu || 1), 1));
    if (f <= 0) return 0;
    return Math.max(1, Math.min(a.cap, Math.round(a.rem * f / (f + (a.topK || 0)))));
  }
  const amts = legs.map(r => alloc.get(r.c) || 0).filter(x => x > 0);
  return amts.length ? Math.round(amts.reduce((s, x) => s + x, 0) / amts.length) : 1;
}

let args = '';
function dock(preferEntry) {
  const on = picked.size > 0;
  $('#dock').classList.toggle('on', on);
  document.body.classList.toggle('docked', on);
  if (!on) return;
  const legs = [...picked.values()];
  const books = new Set(legs.map(r => r.b));
  const book = books.size === 1 ? [...books][0] : null;
  const types = book && D.types[book];
  const sel = $('#entry');
  const prev = preferEntry || sel.value;
  sel.innerHTML = '';
  let msg = '', exp = '', sug = 0;
  if (types) {
    Object.entries(types).filter(([, e]) => e.picks === legs.length).forEach(([id, e]) => {
      const o = document.createElement('option'); o.value = id; o.textContent = e.label; sel.appendChild(o);
    });
    if ([...sel.options].some(o => o.value === prev)) sel.value = prev;
    if (!sel.options.length) msg = `${legs[0].bl} has no entry with ${legs.length} pick${legs.length > 1 ? 's' : ''}`;
    else {
      const e = types[sel.value];
      const boost = legs.reduce((b, r) => b * (r.mu || 1), 1);
      const ret = entryReturn(legs.map(r => r.p), e.pays, boost);
      const games = new Set(legs.map(r => r.g)).size;
      sug = ret > 1 ? suggest(legs, e) : 0;
      exp = `Expected return <b class="${ret >= 1 ? 'pos' : 'neg'}">${sgn((ret - 1) * 100)}%</b> on ${e.label}` +
            (ret < 1 ? ' · <span class="tag conflict">loses value</span>' : '') +
            (games < legs.length ? ' · <span class="tag warn">same-game picks</span>' : '');
    }
  } else if ([...books].some(b => D.types[b])) {
    msg = "A pick'em entry has to be all on one app. Kalshi picks are for buying on Kalshi.";
  } else {
    const avg = legs.reduce((s, r) => s + (r.e || 0), 0) / legs.length;
    sug = suggest(legs, null);
    exp = `${legs.length} separate bet${legs.length > 1 ? 's' : ''} · avg edge <b class="${avg >= 0 ? 'pos' : 'neg'}">${sgn(avg * 100)}%</b>`;
  }
  if (stakeAuto && sug >= 1) stake = sug;
  $('#stake').textContent = stake;
  const kal = legs.filter(r => r.s === 'kalshi');
  const single = legs.length === 1 && kal.length === 1;
  $('#kbuy').hidden = !single;
  let kargs = '';
  if (single) {
    const r = kal[0];
    if (kkey !== r.c) { kkey = r.c; ks = null; }
    const est = kShares(stake, r.ask), sh = ks != null ? ks : est;
    if (document.activeElement !== $('#ks')) $('#ks').value = sh.toFixed(2);
    exp = (ks != null ? `${sh.toFixed(2)} shares at ${(100 * stake / sh).toFixed(1)}¢` : `About ${est.toFixed(2)} shares at ${(100 * stake / est).toFixed(1)}¢`) +
          ` with fee · pays <b>$${sh.toFixed(2)}</b> if it hits. Type the shares Kalshi shows to log it exactly.`;
    kargs = ` --contracts ${sh.toFixed(2)}`;
  } else if (kal.length) {
    const list = kal.slice(0, 3).map(r => `${esc(r.pl.split(' ').slice(-1)[0])} ≈${kShares(stake, r.ask).toFixed(2)} sh`);
    exp += `<br>Kalshi: ${list.join(' · ')}${kal.length > 3 ? ` · +${kal.length - 3} more` : ''}`;
  }
  if (!msg) {
    const rem = Math.max(0, budget - spent);
    exp += `<br>${sug >= 1 ? `Suggested <b>$${sug}</b>${legs.length > 1 && !types ? ' each' : ''}` : 'No suggested stake'} · $${rem.toFixed(0)} of today's $${budget} left`;
  }
  sel.style.display = types && sel.options.length ? '' : 'none';
  $('#dsum').textContent = `${legs.length} pick${legs.length > 1 ? 's' : ''}` + (book ? ' · ' + legs[0].bl : '');
  $('#dexp').innerHTML = msg ? `<span class="neg">${esc(msg)}</span>` : exp;
  args = `bet ${D.league} ${[...picked.keys()].join(' ')}` + (types && sel.value ? ` --entry ${sel.value}` : '') +
         ` --stake ${stake}${kargs} --board ${D.built}`;
  $('#cmd').textContent = D.repo ? args : `cd "${D.root}" && python3 edgefinder.py ${args}`;
  const log = $('#log');
  if (log) log.href = `https://github.com/${D.repo}/issues/new?title=${encodeURIComponent(args)}&body=${encodeURIComponent('```\n' + args + '\n```')}`;
  const save = $('#save');
  if (save) { save.disabled = !!msg; save.textContent = window.EF && EF.token() ? 'Save bet' : 'Save bet (set up once)'; }
  summary = (types && sel.value ? types[sel.value].label : legs.map(r => r.bl).filter((x, i, a) => a.indexOf(x) === i).join(' + ')) +
            ' · $' + stake + ' · ' + legs.map(r => `${r.pl} ${r.pk} ${r.m}`).join(', ');
  total = types ? stake : stake * legs.length;
}
let summary = '', total = 0;
if ($('#save')) $('#save').onclick = async () => {
  const btn = $('#save');
  btn.disabled = true; btn.textContent = 'Saving…';
  const n = await EF.send(args, 'bet', {summary, league: D.league, stake: total});
  if (n) {
    EF.toast('Saved. It shows on Results in a couple of minutes.');
    spent += total;
    picked.clear(); drawBudget(); draw();
  }
  dock();
};
$('#entry').onchange = () => { stakeAuto = true; dock(); };
window.addEventListener('ef-auth', () => dock());
const setStake = v => { stake = Math.max(1, Math.min(100, v)); stakeAuto = false; ks = null; try { localStorage.setItem('ef-stake', stake); } catch (e) {} dock(); };
$('#minus').onclick = () => setStake(stake - 1);
$('#plus').onclick = () => setStake(stake + 1);
$('#ks').oninput = () => { const v = parseFloat($('#ks').value); if (v > 0 && stake / v < 1) { ks = Math.round(v * 100) / 100; dock(); } };
$('#ks').onblur = () => dock();
$('#clear').onclick = () => { picked.clear(); draw(); dock(); };
$('#copy').onclick = async () => {
  const t = $('#cmd').textContent;
  try { await navigator.clipboard.writeText(t); $('#copy').textContent = 'Copied'; setTimeout(() => $('#copy').textContent = 'Copy', 1200); } catch (e) {}
};
drawBudget(); draw(); dock();
if (D.repo) loadSpent();
})();
"""


def render(board, cfg, root, web=None):
    """web: {'repo': 'owner/name'} for the GitHub Pages version (Log button opens an issue)."""
    data = payload(board, cfg, root, web)
    primary = '<button id="save">Save bet</button>' if web else ""
    fallback = ('<div class="cmd"><a id="log" target="_blank" rel="noopener">or log it on GitHub instead</a></div>'
                if web else "")
    body = BODY % {
        "nav": nav_html(board["league"], web) if web else "",
        "primary": primary, "fallback": fallback,
        "efjs": ef_script(web["repo"]) if web else "",
        "data": json.dumps(data, separators=(",", ":")).replace("</", "<\\/"),
        "js": JS,
    }
    return head("Edge Finder " + board["league"].upper(), web=bool(web)) + body


def write(board, cfg, root, boards_dir):
    os.makedirs(boards_dir, exist_ok=True)
    stamp = local(parse_iso(board["built_at"])).strftime("%Y-%m-%d-%H%M")
    lg = board["league"]
    page = render(board, cfg, root)
    path = os.path.join(boards_dir, "%s-%s.html" % (lg, stamp))
    with open(path, "w") as f:
        f.write(page)
    with open(os.path.join(boards_dir, "latest-%s.html" % lg), "w") as f:
        f.write(page)
    csv_path = os.path.join(boards_dir, "%s-%s.csv" % (lg, stamp))
    with open(csv_path, "w", newline="") as f:
        w = csv.writer(f)
        w.writerow(["code", "section", "flagged", "book", "player", "game", "start", "market", "side", "line",
                    "fair_p", "fair_p_raw", "breakeven", "edge", "price_or_ask", "ev", "n_sharp", "adj_gap", "ge_p",
                    "ge_tag", "sharp"])
        for sec in ("pickem", "fliff", "kalshi"):
            for x in board[sec]:
                w.writerow([x["code"], sec, int(x["flagged"]), x["book"], x["player"], x["game"], x["commence"],
                            x["market"], x["side"], x["point"], round(x["p"], 4), round(x["p_raw"], 4),
                            round(x["breakeven"], 4) if x.get("breakeven") else "",
                            round(x["edge"], 4) if x.get("edge") is not None else "",
                            x["ask"] if sec == "kalshi" else (x["price"] or ""),
                            round(x["ev"], 4) if x.get("ev") is not None else "",
                            x["n_sharp"], x["gap"], round(x["ge_p"], 4) if x.get("ge_p") is not None else "",
                            x.get("ge_tag") or "", x["sharp"]])
    return path, csv_path
