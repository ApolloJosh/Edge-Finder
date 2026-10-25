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
:root{--bg:#f4f3ef;--panel:#fff;--ink:#17191d;--dim:#5b616c;--faint:#8b919b;--line:#e2e0d9;
--accent:#0e7a5d;--accent-ink:#fff;--accent-bg:#e1f2ea;--warn:#8f5600;--warn-bg:#fcefd8;--bad:#b3261e;--bad-bg:#fae6e4;
--chip:#ebe9e3;--sel:#fff5cc;--shadow:0 -8px 24px rgba(0,0,0,.10)}
@media (prefers-color-scheme:dark){:root:not([data-theme=light]){--bg:#0f1113;--panel:#181b1f;--ink:#ecebe7;
--dim:#a7acb4;--faint:#7b818a;--line:#272b31;--accent:#3fc596;--accent-ink:#06261b;--accent-bg:#123428;--warn:#e8ab4c;
--warn-bg:#352812;--bad:#f08a80;--bad-bg:#3a1b18;--chip:#23272d;--sel:#2e2a14;--shadow:0 -8px 24px rgba(0,0,0,.5)}}
*{box-sizing:border-box;-webkit-tap-highlight-color:transparent}
html{-webkit-text-size-adjust:100%}
body{margin:0;background:var(--bg);color:var(--ink);font:15px/1.45 -apple-system,BlinkMacSystemFont,"Segoe UI",Inter,sans-serif;
-webkit-font-smoothing:antialiased;padding-bottom:calc(24px + env(safe-area-inset-bottom))}
body.docked{padding-bottom:calc(230px + env(safe-area-inset-bottom))}
a{color:var(--accent)}
.wrap{max-width:1100px;margin:0 auto;padding:0 16px}
header.bar{position:sticky;top:0;z-index:20;background:var(--bg);padding:calc(8px + env(safe-area-inset-top)) 0 8px;
border-bottom:1px solid var(--line)}
nav.top{display:flex;gap:2px;overflow-x:auto;scrollbar-width:none;margin:0 -4px}
nav.top::-webkit-scrollbar{display:none}
nav.top a{flex:none;color:var(--dim);text-decoration:none;font-size:14px;font-weight:600;padding:8px 10px;border-radius:8px}
nav.top a.on{background:var(--chip);color:var(--ink)}
.controls{display:flex;gap:8px;align-items:center;margin-top:8px;overflow-x:auto;scrollbar-width:none;padding-bottom:2px}
.controls::-webkit-scrollbar{display:none}
.seg{display:flex;background:var(--chip);border-radius:9px;padding:2px;flex:none}
.seg button{border:0;background:transparent;color:var(--dim);font:inherit;font-size:13px;font-weight:600;padding:6px 11px;border-radius:7px;min-height:34px}
.seg button.on{background:var(--panel);color:var(--ink);box-shadow:0 1px 2px rgba(0,0,0,.12)}
.chip{flex:none;border:1px solid var(--line);background:var(--panel);color:var(--dim);font:inherit;font-size:13px;font-weight:600;
padding:6px 11px;border-radius:999px;min-height:34px;white-space:nowrap}
.chip.on{background:var(--ink);color:var(--bg);border-color:var(--ink)}
select{font:inherit;font-size:14px;padding:6px 8px;border:1px solid var(--line);border-radius:8px;background:var(--panel);color:var(--ink);min-height:36px}
h1{font-size:22px;margin:16px 0 2px;letter-spacing:-.01em}
@media (max-width:640px){h1{font-size:19px;margin-top:12px}.stats{margin-top:8px}h2{margin-top:20px}}
h2{font-size:16px;margin:24px 0 10px;display:flex;align-items:baseline;gap:8px;flex-wrap:wrap}
h2 small{font-weight:400;color:var(--faint);font-size:12.5px}
.sub{color:var(--dim);font-size:13px}
.dim{color:var(--faint)}
.pos{color:var(--accent)}.neg{color:var(--bad)}
.stats{display:flex;flex-wrap:wrap;gap:6px;margin:10px 0 0}
.stat{background:var(--chip);border-radius:999px;padding:3px 10px;font-size:12.5px;color:var(--dim)}
.stat b{color:var(--ink)}
details.notes{margin-top:10px;background:var(--warn-bg);color:var(--warn);border-radius:10px;padding:8px 12px;font-size:13px}
details.notes summary{cursor:pointer;font-weight:600}
details.notes ul{margin:6px 0 2px;padding-left:18px}
.grid{display:grid;grid-template-columns:1fr;gap:10px}
@media (min-width:760px){.grid{grid-template-columns:1fr 1fr}}
.card{background:var(--panel);border:1px solid var(--line);border-radius:14px;overflow:hidden}
.card.on{border-color:var(--accent);background:var(--sel)}
.card.dimrow{opacity:.72}
label.pick{display:flex;gap:12px;padding:12px 14px;cursor:pointer;min-height:64px}
label.pick input{position:absolute;opacity:0;pointer-events:none}
.box{flex:none;width:24px;height:24px;border-radius:7px;border:2px solid var(--faint);margin-top:2px;display:grid;place-items:center}
.card.on .box{background:var(--accent);border-color:var(--accent)}
.card.on .box:after{content:"";width:6px;height:11px;border:solid var(--accent-ink);border-width:0 2.5px 2.5px 0;transform:rotate(45deg) translate(-1px,-1px)}
.main{flex:1;min-width:0}
.row1{display:flex;justify-content:space-between;align-items:baseline;gap:10px}
.who{font-weight:700;font-size:16px;white-space:nowrap;overflow:hidden;text-overflow:ellipsis}
.big{font-weight:800;font-size:18px;font-variant-numeric:tabular-nums;white-space:nowrap}
.big small{font-size:11px;font-weight:600;color:var(--faint);margin-left:2px}
.what{font-size:14.5px;margin-top:1px}
.what b{font-weight:650}
.meta{font-size:12.5px;color:var(--dim);margin-top:3px;font-variant-numeric:tabular-nums}
.tag{display:inline-block;border-radius:5px;padding:0 6px;font-size:11.5px;font-weight:650;line-height:18px;vertical-align:1px}
.tag.agree{background:var(--accent-bg);color:var(--accent)}
.tag.conflict{background:var(--bad-bg);color:var(--bad)}
.tag.neutral,.tag.adj{background:var(--chip);color:var(--dim)}
.tag.biased,.tag.warn{background:var(--warn-bg);color:var(--warn)}
details.sharp{border-top:1px solid var(--line);font-size:12.5px;color:var(--dim)}
details.sharp summary{padding:8px 14px 8px 50px;cursor:pointer;list-style:none;color:var(--faint)}
details.sharp summary::-webkit-details-marker{display:none}
details.sharp summary:after{content:" ▾"}
details.sharp[open] summary:after{content:" ▴"}
details.sharp div{padding:0 14px 10px 50px;line-height:1.6}
.empty{background:var(--panel);border:1px dashed var(--line);border-radius:14px;padding:16px;color:var(--dim);font-size:14px}
.empty.slim{padding:10px 14px;font-size:13px}
.more{width:100%;margin-top:10px}
.entry{padding:12px 14px}
.entry .row1 b{font-size:15px}
.entry ol{margin:6px 0 10px;padding-left:20px;font-size:13.5px;color:var(--dim)}
.entry ol b{color:var(--ink)}
button,.btn{font:inherit;font-weight:650;font-size:15px;border-radius:10px;border:1px solid var(--accent);background:var(--accent);
color:var(--accent-ink);padding:10px 14px;min-height:44px;cursor:pointer;text-decoration:none;display:inline-flex;align-items:center;justify-content:center}
button.ghost,.btn.ghost{background:transparent;color:var(--ink);border-color:var(--line)}
button.link{background:none;border:0;color:var(--accent);padding:6px 4px;min-height:0;font-weight:600}
.btn.off{pointer-events:none;opacity:.4}
#dock{position:fixed;left:0;right:0;bottom:0;z-index:30;background:var(--panel);border-top:1px solid var(--line);
box-shadow:var(--shadow);border-radius:16px 16px 0 0;transform:translateY(110%);transition:transform .18s ease}
#dock.on{transform:none}
.dock-in{max-width:640px;margin:0 auto;padding:12px 16px calc(12px + env(safe-area-inset-bottom))}
.d1{display:flex;justify-content:space-between;align-items:center;font-weight:650}
.d2{display:flex;gap:10px;margin-top:8px}
.d2 select{flex:1;min-height:44px}
.stepper{display:flex;align-items:center;border:1px solid var(--line);border-radius:10px;overflow:hidden}
.stepper button{background:transparent;color:var(--ink);border:0;border-radius:0;min-width:44px;font-size:20px;padding:0}
.stepper span{min-width:46px;text-align:center;font-weight:700;font-variant-numeric:tabular-nums}
.d3{margin-top:8px;font-size:13.5px;color:var(--dim);min-height:19px}
.kp[hidden]{display:none}
.kp{display:flex;align-items:center;gap:7px;font-weight:650;color:var(--dim)}
.kp input{width:84px;min-height:44px;font:inherit;font-size:16px;font-weight:700;text-align:center;border:1px solid var(--line);
border-radius:10px;background:var(--bg);color:var(--ink)}
.d4{display:flex;gap:8px;margin-top:10px}
.d4 .btn,.d4 button{flex:1}
.cmd{margin-top:8px;font:11.5px ui-monospace,Menlo,monospace;color:var(--faint);overflow-x:auto;white-space:nowrap}
.foot{color:var(--faint);font-size:12.5px;margin-top:28px;line-height:1.6}
table{border-collapse:collapse;width:100%;font-size:13.5px;font-variant-numeric:tabular-nums}
th{text-align:left;font-weight:600;color:var(--dim);font-size:11.5px;text-transform:uppercase;letter-spacing:.04em;padding:8px 10px;
border-bottom:1px solid var(--line)}
td{padding:8px 10px;border-bottom:1px solid var(--line)}
tr:last-child td{border-bottom:none}
td.num,th.num{text-align:right}
.tablewrap{overflow-x:auto;background:var(--panel);border:1px solid var(--line);border-radius:14px}
"""

ICONS = """<meta name="theme-color" content="#f4f3ef" media="(prefers-color-scheme: light)">
<meta name="theme-color" content="#0f1113" media="(prefers-color-scheme: dark)">
<meta name="apple-mobile-web-app-capable" content="yes">
<meta name="mobile-web-app-capable" content="yes">
<meta name="apple-mobile-web-app-title" content="Edge Finder">
<meta name="apple-mobile-web-app-status-bar-style" content="default">
<link rel="manifest" href="manifest.webmanifest">
<link rel="icon" type="image/png" sizes="192x192" href="icon-192.png">
<link rel="apple-touch-icon" href="apple-touch-icon.png">"""


def head(title, web=True):
    return ('<!doctype html><html lang="en"><head><meta charset="utf-8">'
            '<meta name="viewport" content="width=device-width,initial-scale=1,viewport-fit=cover">'
            '<title>%s</title>%s<style>%s%s</style></head>' % (E(title), ICONS if web else "", CSS, SHEET_CSS if web else ""))


def nav_html(active, web):
    links = [("index", "Home"), ("nba", "NBA"), ("nfl", "NFL"), ("check", "Check"), ("bets", "Results")]
    return '<nav class="top">%s<a href="#settings" id="navset" class="gear" aria-label="Settings">Settings</a></nav>' % "".join(
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
    d = {"c": x["code"], "s": sec, "f": bool(x["flagged"]), "b": x["book"],
         "bl": BOOK_LABELS.get(x["book"], x["book"]), "pl": x["player"], "g": x["game"], "t": x["commence"],
         "m": market_label(x["market"]), "pk": _pick_text(x), "p": round(x["p"], 4), "ex": bool(x["exact"]),
         "gap": x["gap"], "n": x["n_sharp"], "sh": x["sharp"]}
    if sec == "pickem":
        d.update(bar=round(x["breakeven"] or 0, 4), v=round(x["edge"] or 0, 4), cl=x["clears"])
        if x["multiplier"] and abs(x["multiplier"] - 1) > 1e-9:
            d["mu"] = x["multiplier"]
    elif sec == "fliff":
        d.update(pr=fmt_american(x["price"]), v=round(x["ev"], 4))
    else:
        d.update(ask=x["ask"], fee=round(x["fee"], 4), ev=round(x["ev"], 4), v=round(x["roi"], 4), sz=x["size"])
    if nfl and x.get("ge_p") is not None:
        d.update(gp=round(x["ge_p"], 3), gt=x["ge_tag"], gs=x.get("ge_score"))
    return d


def notes(board, cfg):
    out = []
    counts = board["counts"]
    for b in cfg.pickem_books + cfg.sportsbooks:
        if not counts.get(b):
            out.append("No %s lines in the latest pull (not posted yet, or not in the feed)." % BOOK_LABELS.get(b, b))
    if not any(counts.get(b) for b in cfg.sharp_weights):
        out.append("No sharp-book prices came back, so nothing could be priced.")
    for book in cfg.pickem_books:
        if any(e.get("verify") for e in cfg.entries(book).values()):
            out.append("%s payouts in config.json are placeholders - check the app and fix them." % BOOK_LABELS.get(book, book))
    if board["league"] == "nfl":
        if not board["ge_rows"]:
            out.append("No Gridiron Edge read loaded yet. On game days it loads itself; or upload an export to the repo's inputs folder.")
        else:
            out.append("Gridiron Edge is a second opinion only. 'runs high' marks markets where its median sits too high "
                       "(Pass Yds, Pass+Rush, Rush+Rec, RB receptions, TE Rec Yds).")
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
        "offsets": cfg.get("auto", {}).get("board_offsets_min", [90, 30]),
    }


# --------------------------------------------------------------- page

BODY = """<body>
<header class="bar"><div class="wrap">
%(nav)s
<div class="controls">
<div class="seg" id="view"><button data-v="flag" class="on">Flagged&nbsp;<span id="nflag"></span></button><button data-v="all">All</button></div>
<button class="chip on" data-app="all">All apps</button>
<button class="chip" data-app="prizepicks">PrizePicks</button>
<button class="chip" data-app="underdog">Underdog</button>
<button class="chip" data-app="fliff">Fliff</button>
<button class="chip" data-app="kalshi">Kalshi</button>
<select id="sort" aria-label="Sort"><option value="v">Best value</option><option value="t">Start time</option><option value="pl">Player</option></select>
</div></div></header>
<main class="wrap">
<h1 id="title"></h1>
<div class="sub" id="when"></div>
<div class="stats" id="stats"></div>
<details class="notes" id="notes"><summary></summary><ul></ul></details>
<section id="sec-entries"><h2>Best entries <small>top flagged picks on one app, one per game</small></h2><div class="grid" id="entries"></div></section>
<section id="sec-pickem"><h2>Pick'em <small id="h-pickem"></small></h2><div class="grid" id="pickem"></div></section>
<section id="sec-fliff"><h2>Fliff <small id="h-fliff"></small></h2><div class="grid" id="fliff"></div></section>
<section id="sec-kalshi"><h2>Kalshi <small id="h-kalshi"></small></h2><div class="grid" id="kalshi"></div></section>
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
const sgn = (x, d = 1) => (x >= 0 ? '+' : '') + x.toFixed(d);
const now = Date.now();
const live = D.rows.filter(r => !r.t || Date.parse(r.t) > now);
const byCode = new Map(live.map(r => [r.c, r]));
const LG = D.league.toUpperCase();
let view = 'flag', app = 'all', sort = 'v';
const picked = new Map();
let stake = 1;
// Kalshi buys by the dollar and fills fractional shares at ask + fee (0.07 x P x (1 - P) a share).
// One Kalshi pick at a time can take the exact shares Kalshi shows.
let ks = null, kkey = '';
const kShares = (s, p) => Math.floor(s / (p + 0.07 * p * (1 - p)) * 100 + 1e-6) / 100;
try { stake = Math.max(1, parseInt(localStorage.getItem('ef-stake') || '1', 10) || 1); } catch (e) {}

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

// ---------- header
$('#title').textContent = 'Edge Finder · ' + LG;
$('#when').innerHTML = 'Lines pulled ' + esc(ago(D.pulled)) + ' · page built ' + esc(ago(D.built)) +
  ' · <button class="link" onclick="location.reload()">Reload</button>';
const flagged = live.filter(r => r.f).length;
const st = [`<b>${flagged}</b> flagged`, `<b>${D.games}</b> games`];
if (D.credits != null) st.push(`<b>${D.credits}</b> credits left`);
$('#stats').innerHTML = st.map(s => `<span class="stat">${s}</span>`).join('');
if (D.notes.length) {
  $('#notes summary').textContent = 'Notes (' + D.notes.length + ')';
  $('#notes ul').innerHTML = D.notes.map(n => `<li>${esc(n)}</li>`).join('');
} else $('#notes').remove();
$('#h-pickem').textContent = `flagged when fair beats an entry's per-pick breakeven by ${(D.th.cush*100).toFixed(0)}+ pt`;
$('#h-fliff').textContent = `flagged at ${(D.th.fliff*100).toFixed(0)}%+ expected value`;
$('#h-kalshi').textContent = `after Kalshi's fee; flagged at ${(D.th.kalshi*100).toFixed(0)}%+ return with ${D.th.kmin}+ on offer`;
const counts = Object.entries(D.counts).map(([b, n]) => `${{prizepicks:'PrizePicks',underdog:'Underdog',fliff:'Fliff',kalshi:'Kalshi'}[b]} ${n}`).join(' · ');
$('#foot').innerHTML = `Lines in the latest pull: ${esc(counts)}.<br>Per-pick breakevens: ${esc(D.be)}.<br>Fair = the sharp books' chance of the pick hitting, margin removed, using the
  less generous of two methods. <span class="tag adj">adj</span> = a sharp line sat a little off this one and its price was moved here;
  those take an extra cut before they can flag. Lines need ${D.th.minb} sharp books. Judge it by closing line value, not early wins.`;

// ---------- cards
function card(r) {
  let big, what, meta;
  if (r.s === 'pickem') {
    big = `<span class="big ${r.v >= 0 ? 'pos' : 'neg'}">${sgn(r.v * 100)}<small>pts</small></span>`;
    what = `<b>${esc(r.pk)}</b> ${esc(r.m)} · ${esc(r.bl)}${r.mu ? ' ×' + r.mu : ''}`;
    meta = `Fair ${pct(r.p)} · bar ${pct(r.bar)}${r.cl.length ? ' · clears ' + esc(r.cl.join(', ')) : ''}`;
  } else if (r.s === 'fliff') {
    big = `<span class="big ${r.v >= 0 ? 'pos' : 'neg'}">${sgn(r.v * 100)}%<small>EV</small></span>`;
    what = `<b>${esc(r.pk)}</b> ${esc(r.m)} · Fliff ${esc(r.pr)}`;
    meta = `Fair ${pct(r.p)}`;
  } else {
    big = `<span class="big ${r.v >= 0 ? 'pos' : 'neg'}">${sgn(r.v * 100)}%<small>ROI</small></span>`;
    what = `<b>${esc(r.pk)}</b> ${esc(r.m)} · Kalshi ${Math.round(r.ask * 100)}¢`;
    meta = `Fair ${pct(r.p)} · fee ${(r.fee * 100).toFixed(1)}¢ · ${r.sz == null ? '?' : Math.floor(r.sz)} on offer`;
  }
  let ge = '';
  if (D.nfl) {
    if (r.gp != null) {
      const lab = {agree: 'agrees', conflict: 'check news', neutral: 'neutral', biased: 'runs high'}[r.gt];
      ge = `<div class="meta">Gridiron Edge ${pct(r.gp, 0)} <span class="tag ${r.gt}">${lab}</span>${r.gs != null ? ' · EDGE ' + Math.round(r.gs) : ''}</div>`;
    } else ge = `<div class="meta dim">No Gridiron Edge read</div>`;
  }
  const adj = r.ex ? '' : ` · <span class="tag adj">adj ${r.gap}</span>`;
  const on = picked.has(r.c) ? ' on' : '';
  return `<div class="card${on}${r.f ? '' : ' dimrow'}" data-c="${esc(r.c)}">
<label class="pick"><input type="checkbox" ${on ? 'checked' : ''} aria-label="Select ${esc(r.pl)}"><span class="box"></span>
<div class="main"><div class="row1"><span class="who">${esc(r.pl)}</span>${big}</div>
<div class="what">${what}</div><div class="meta">${meta}</div>${ge}
<div class="meta dim">#${esc(r.c)} · ${esc(r.g)} · ${esc(when(r.t))}${adj}</div></div></label>
<details class="sharp"><summary>Sharp lines (${r.n})</summary><div>${esc(r.sh).replace(/ · /g, '<br>')}</div></details></div>`;
}

const EMPTY = {
  pickem: "Nothing clears the bar yet. Pick'em edges tend to show up after lineup news, so a fresh Run from Home is worth it when news breaks.",
  fliff: 'Nothing beats the sharp market by enough right now.',
  kalshi: 'Nothing clears the bar with enough on offer right now.',
};
const shown = {pickem: 40, fliff: 40, kalshi: 40};

function draw() {
  const rows = live.filter(r => (view === 'all' || r.f) && (app === 'all' || r.b === app));
  const cmp = {v: (a, b) => b.v - a.v, t: (a, b) => (a.t || '').localeCompare(b.t || '') || b.v - a.v,
               pl: (a, b) => a.pl.localeCompare(b.pl)}[sort];
  $('#nflag').textContent = flagged;
  // Sections with something to show go first; empty ones drop to the bottom as one line.
  const secs = ['pickem', 'fliff', 'kalshi'];
  const counts = Object.fromEntries(secs.map(sec => [sec, rows.filter(r => r.s === sec).length]));
  const foot = $('#foot');
  [...secs].sort((a, b) => (counts[b] > 0) - (counts[a] > 0)).forEach(sec => foot.parentNode.insertBefore($('#sec-' + sec), foot));
  for (const sec of secs) {
    const list = rows.filter(r => r.s === sec).sort(cmp);
    const el = $('#' + sec);
    const section = $('#sec-' + sec);
    const hideSec = app !== 'all' && !list.length && !live.some(r => r.s === sec && r.b === app);
    section.style.display = hideSec ? 'none' : '';
    if (!list.length) { el.innerHTML = `<div class="empty slim">${EMPTY[sec]}</div>`; continue; }
    const n = shown[sec];
    el.innerHTML = list.slice(0, n).map(card).join('') +
      (list.length > n ? `<button class="ghost more" data-more="${sec}">Show ${Math.min(40, list.length - n)} more of ${list.length - n}</button>` : '');
  }
  const ents = D.entries.filter(e => (app === 'all' || e.b === app) && e.legs.every(c => byCode.has(c)));
  $('#sec-entries').style.display = ents.length ? '' : 'none';
  $('#entries').innerHTML = ents.map(e => `<div class="card entry"><div class="row1"><b>${esc(e.label)}</b>
<span class="big pos">${sgn(e.roi * 100)}%<small>exp.</small></span></div>
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
  dock();
});
document.addEventListener('click', ev => {
  const more = ev.target.closest('[data-more]');
  if (more) { shown[more.dataset.more] += 40; draw(); return; }
  const sel = ev.target.closest('[data-legs]');
  if (sel) {
    picked.clear();
    sel.dataset.legs.split(',').forEach(c => picked.set(c, byCode.get(c)));
    draw(); dock(sel.dataset.entry);
  }
});
$$('#view button').forEach(b => b.onclick = () => { view = b.dataset.v; $$('#view button').forEach(x => x.classList.toggle('on', x === b)); draw(); });
$$('[data-app]').forEach(b => b.onclick = () => { app = b.dataset.app; $$('[data-app]').forEach(x => x.classList.toggle('on', x === b)); draw(); });
$('#sort').onchange = e => { sort = e.target.value; draw(); };

// ---------- bottom sheet
function pbin(ps) { let d = [1]; for (const p of ps) { const n = new Array(d.length + 1).fill(0); d.forEach((v, k) => { n[k] += v * (1 - p); n[k + 1] += v * p; }); d = n; } return d; }
function entryReturn(ps, pays, boost) { return pbin(ps).reduce((s, v, k) => s + v * (+(pays[String(k)] || 0)) * (k === ps.length ? boost : 1), 0); }

let args = '';
function dock(preferEntry) {
  const on = picked.size > 0;
  $('#dock').classList.toggle('on', on);
  document.body.classList.toggle('docked', on);
  if (!on) return;
  $('#stake').textContent = stake;
  const legs = [...picked.values()];
  const books = new Set(legs.map(r => r.b));
  const book = books.size === 1 ? [...books][0] : null;
  const types = book && D.types[book];
  const sel = $('#entry');
  const prev = preferEntry || sel.value;
  sel.innerHTML = '';
  let msg = '', exp = '';
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
      exp = `Expected return <b class="${ret >= 1 ? 'pos' : 'neg'}">${sgn((ret - 1) * 100)}%</b> on ${e.label}` +
            (games < legs.length ? ' · <span class="tag warn">same-game picks</span>' : '');
    }
  } else if ([...books].some(b => D.types[b])) {
    msg = "A pick'em entry has to be all on one app";
  } else {
    const avg = legs.reduce((s, r) => s + r.v, 0) / legs.length;
    exp = `${legs.length} separate bet${legs.length > 1 ? 's' : ''} · avg ${legs[0].s === 'kalshi' && books.size === 1 ? 'return' : 'value'} <b class="${avg >= 0 ? 'pos' : 'neg'}">${sgn(avg * 100)}%</b>`;
  }
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
}
let summary = '';
if ($('#save')) $('#save').onclick = async () => {
  const btn = $('#save');
  btn.disabled = true; btn.textContent = 'Saving…';
  const n = await EF.send(args, 'bet', {summary, league: D.league});
  if (n) {
    EF.toast('Saved. It shows on Results in a couple of minutes.');
    picked.clear(); draw();
  }
  dock();
};
$('#entry').onchange = () => dock();
window.addEventListener('ef-auth', () => dock());
const setStake = v => { stake = Math.max(1, Math.min(100, v)); ks = null; try { localStorage.setItem('ef-stake', stake); } catch (e) {} dock(); };
$('#minus').onclick = () => setStake(stake - 1);
$('#plus').onclick = () => setStake(stake + 1);
$('#ks').oninput = () => { const v = parseFloat($('#ks').value); if (v > 0 && stake / v < 1) { ks = Math.round(v * 100) / 100; dock(); } };
$('#ks').onblur = () => dock();
$('#clear').onclick = () => { picked.clear(); draw(); dock(); };
$('#copy').onclick = async () => {
  const t = $('#cmd').textContent;
  try { await navigator.clipboard.writeText(t); $('#copy').textContent = 'Copied'; setTimeout(() => $('#copy').textContent = 'Copy', 1200); } catch (e) {}
};
draw(); dock();
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
