"""The board as a self-contained HTML page (opens in your browser) plus a CSV."""
import csv
import html
import json
import os

from .board import BOOK_LABELS, market_label
from .util import fmt_american, local, local_label, parse_iso, pct

E = html.escape

CSS = """
:root{--bg:#f6f5f1;--panel:#fff;--ink:#1d1f23;--dim:#5d636e;--faint:#8a909a;--line:#e3e1da;
--accent:#0f7b5f;--accent-bg:#e3f3ec;--warn:#9a5b00;--warn-bg:#fdf1dc;--bad:#b3261e;--bad-bg:#fbe7e5;
--chip:#efeee9;--sel:#fff7d6}
@media (prefers-color-scheme:dark){:root:not([data-theme=light]){--bg:#121417;--panel:#1a1d21;--ink:#e8e6e1;
--dim:#a6abb3;--faint:#7c828c;--line:#2b2f35;--accent:#47c79d;--accent-bg:#15342a;--warn:#e7a948;--warn-bg:#3a2c13;
--bad:#f08a80;--bad-bg:#3d1c19;--chip:#24282e;--sel:#3a3418}}
*{box-sizing:border-box}
a{color:var(--accent)}
body{margin:0;background:var(--bg);color:var(--ink);font:14px/1.45 -apple-system,BlinkMacSystemFont,"Segoe UI",Inter,sans-serif;
-webkit-font-smoothing:antialiased;padding-bottom:120px}
.wrap{max-width:1280px;margin:0 auto;padding:20px 16px}
h1{font-size:22px;margin:0 0 2px;letter-spacing:-.01em}
h2{font-size:15px;margin:28px 0 8px;display:flex;align-items:baseline;gap:10px}
h2 small{font-weight:400;color:var(--faint);font-size:12.5px}
.sub{color:var(--dim);font-size:13px}
.chips{display:flex;flex-wrap:wrap;gap:6px;margin:12px 0 4px}
.chip{background:var(--chip);border-radius:999px;padding:3px 10px;font-size:12px;color:var(--dim)}
.chip b{color:var(--ink);font-weight:600}
.notes{margin:12px 0 0;padding:0;list-style:none;display:grid;gap:6px}
.notes li{background:var(--warn-bg);color:var(--warn);border-radius:6px;padding:7px 10px;font-size:12.5px}
.tablewrap{overflow-x:auto;background:var(--panel);border:1px solid var(--line);border-radius:8px}
table{border-collapse:collapse;width:100%;font-size:13px;font-variant-numeric:tabular-nums}
th{position:sticky;top:0;background:var(--panel);text-align:left;font-weight:600;color:var(--dim);font-size:11.5px;
text-transform:uppercase;letter-spacing:.04em;padding:8px 10px;border-bottom:1px solid var(--line);cursor:pointer;white-space:nowrap}
td{padding:7px 10px;border-bottom:1px solid var(--line);white-space:nowrap;vertical-align:top}
tr:last-child td{border-bottom:none}
td.num,th.num{text-align:right}
td.code{color:var(--faint);font-size:12px}
td.player{font-weight:600}
td.sharp{color:var(--faint);font-size:11.5px;white-space:normal;min-width:180px}
tr.dim{display:none}
body.showall tr.dim{display:table-row;opacity:.62}
tr.gone,body.showall tr.gone{display:none}
nav.top{display:flex;gap:4px;flex-wrap:wrap;margin:0 0 14px}
nav.top a{color:var(--dim);text-decoration:none;font-size:13px;font-weight:600;padding:5px 10px;border-radius:6px}
nav.top a.on{background:var(--chip);color:var(--ink)}
a.btn{display:inline-block;font-weight:600;padding:6px 12px;border-radius:6px;background:var(--accent);color:#fff;
text-decoration:none;border:1px solid var(--accent)}
a.btn.off{pointer-events:none;opacity:.4}
a.btn.ghost{background:transparent;color:var(--dim);border-color:var(--line)}
tr.sel{background:var(--sel)}
.pos{color:var(--accent);font-weight:600}
.neg{color:var(--bad)}
.tag{display:inline-block;border-radius:4px;padding:1px 6px;font-size:11px;font-weight:600}
.tag.agree{background:var(--accent-bg);color:var(--accent)}
.tag.conflict{background:var(--bad-bg);color:var(--bad)}
.tag.neutral{background:var(--chip);color:var(--dim)}
.tag.biased{background:var(--warn-bg);color:var(--warn)}
.tag.adj{background:var(--chip);color:var(--dim);font-weight:500}
.empty{padding:14px;color:var(--faint)}
.entries{display:grid;grid-template-columns:repeat(auto-fill,minmax(290px,1fr));gap:10px}
.entry{background:var(--panel);border:1px solid var(--line);border-radius:8px;padding:12px}
.entry .hd{display:flex;justify-content:space-between;align-items:baseline;margin-bottom:6px}
.entry .hd b{font-size:14px}
.entry ol{margin:0;padding-left:18px;font-size:12.5px;color:var(--dim)}
.entry ol b{color:var(--ink);font-weight:600}
.toolbar{display:flex;gap:12px;align-items:center;margin-top:16px;font-size:13px;color:var(--dim)}
input[type=checkbox]{accent-color:var(--accent);width:15px;height:15px;cursor:pointer}
.dock{position:fixed;left:0;right:0;bottom:0;background:var(--panel);border-top:1px solid var(--line);
box-shadow:0 -6px 20px rgba(0,0,0,.08);padding:10px 16px;display:none}
.dock.on{display:block}
.dock .row{max-width:1280px;margin:0 auto;display:flex;flex-wrap:wrap;gap:8px 14px;align-items:center;font-size:13px}
.dock code{flex:1 1 420px;background:var(--chip);border-radius:6px;padding:8px 10px;font:12px ui-monospace,Menlo,monospace;
overflow-x:auto;white-space:nowrap;color:var(--ink)}
.dock select,.dock input{font:inherit;padding:4px 6px;border:1px solid var(--line);border-radius:5px;background:var(--panel);color:var(--ink)}
.dock input{width:64px}
button{font:inherit;font-weight:600;padding:6px 12px;border-radius:6px;border:1px solid var(--accent);background:var(--accent);color:#fff;cursor:pointer}
button.ghost{background:transparent;color:var(--dim);border-color:var(--line)}
.foot{color:var(--faint);font-size:12px;margin-top:28px;line-height:1.6}
"""

JS = """
const ENTRY_TYPES = __ENTRIES__;
const ROOT = __ROOT__;
const LEAGUE = __LEAGUE__;
const BOARD = __BOARD__;
const REPO = __REPO__;
// Games that have started since this page was built can't be bet.
const nowMs = Date.now();
q('tr[data-start]').forEach(tr=>{ if(Date.parse(tr.dataset.start) <= nowMs){ tr.classList.add('gone'); } });
const picked = new Map();
function q(s, el){return (el||document).querySelectorAll(s)}
function refresh(){
  const dock = document.getElementById('dock');
  dock.classList.toggle('on', picked.size>0);
  if(!picked.size) return;
  const books = new Set([...picked.values()].map(p=>p.book));
  const book = books.size===1 ? [...books][0] : null;
  const sel = document.getElementById('entry');
  const types = book && ENTRY_TYPES[book] ? ENTRY_TYPES[book] : null;
  const prev = sel.value;
  sel.innerHTML = '';
  if(types){
    Object.entries(types).filter(([id,e])=>e.picks===picked.size).forEach(([id,e])=>{
      const o=document.createElement('option'); o.value=id; o.textContent=e.label; sel.appendChild(o);});
    if([...sel.options].some(o=>o.value===prev)) sel.value=prev;
  }
  sel.style.display = types ? '' : 'none';
  const codes=[...picked.keys()].join(' ');
  const stake = document.getElementById('stake').value||1;
  let args = 'bet '+LEAGUE+' '+codes;
  let msg = '';
  if(types){
    if(!sel.options.length){ msg = 'No '+book+' entry takes '+picked.size+' picks'; }
    else args += ' --entry '+sel.value;
  } else if(books.size>1 && [...books].some(b=>ENTRY_TYPES[b])){ msg='Pick\\'em entries must be one app'; }
  args += ' --stake '+stake+' --board '+BOARD;
  const cmd = 'cd "'+ROOT+'" && python3 edgefinder.py '+args;
  document.getElementById('cmd').textContent = msg ? msg : (REPO ? args : cmd);
  document.getElementById('count').textContent = picked.size+' selected';
  const log = document.getElementById('log');
  if(REPO && log){
    const title = 'bet '+LEAGUE+' #'+codes.split(' ').join(' #')+(sel.value&&types?' '+sel.value:'')+' $'+stake;
    const body = '```\\n'+args+'\\n```\\nSubmit this issue to log the bet. Edge Finder replies here in a minute or two.';
    log.href = 'https://github.com/'+REPO+'/issues/new?title='+encodeURIComponent(title)+'&body='+encodeURIComponent(body);
    log.classList.toggle('off', !!msg);
  }
}
q('input.pick').forEach(cb=>cb.addEventListener('change',e=>{
  const tr=cb.closest('tr');
  if(cb.checked) picked.set(cb.dataset.code,{book:cb.dataset.book}); else picked.delete(cb.dataset.code);
  tr.classList.toggle('sel',cb.checked); refresh();
}));
document.getElementById('entry').addEventListener('change',refresh);
document.getElementById('stake').addEventListener('input',refresh);
document.getElementById('clear').addEventListener('click',()=>{
  picked.clear(); q('input.pick').forEach(cb=>{cb.checked=false;cb.closest('tr').classList.remove('sel')}); refresh();});
document.getElementById('copy').addEventListener('click',async()=>{
  const t=document.getElementById('cmd').textContent;
  try{await navigator.clipboard.writeText(t);document.getElementById('copy').textContent='Copied';
    setTimeout(()=>document.getElementById('copy').textContent='Copy',1200);}catch(e){}
});
document.getElementById('showall').addEventListener('change',e=>document.body.classList.toggle('showall',e.target.checked));
q('th[data-k]').forEach(th=>th.addEventListener('click',()=>{
  const table=th.closest('table'), tb=table.tBodies[0], i=[...th.parentNode.children].indexOf(th);
  const dir = th.dataset.dir==='desc' ? 'asc' : 'desc'; th.dataset.dir=dir;
  const rows=[...tb.rows].sort((a,b)=>{
    const x=a.cells[i].dataset.v, y=b.cells[i].dataset.v;
    const nx=parseFloat(x), ny=parseFloat(y);
    const c = (!isNaN(nx)&&!isNaN(ny)) ? nx-ny : String(x).localeCompare(String(y));
    return dir==='asc'?c:-c;});
  rows.forEach(r=>tb.appendChild(r));
}));
"""


def _td(text, v=None, cls=None):
    attrs = ""
    if cls:
        attrs += ' class="%s"' % cls
    if v is not None:
        attrs += ' data-v="%s"' % E(str(v))
    return "<td%s>%s</td>" % (attrs, text)


def _pick_text(x):
    side = "Over" if x["side"] == "over" else "Under"
    s = "%s %g" % (side, x["point"])
    if x["book"] == "kalshi":
        s = ("YES %g+" if x["side"] == "over" else "NO %g+") % (x["point"] + 0.5)
    return s


def _adj(x):
    if x["exact"]:
        return ""
    return ' <span class="tag adj" title="A sharp line differs from this one by up to %g; its price was moved to this line">adj %g</span>' % (x["gap"], x["gap"])


def _ge_cell(x):
    if x.get("ge_p") is None:
        return _td('<span class="tag neutral">—</span>', -1)
    tag = x["ge_tag"]
    label = {"agree": "agrees", "conflict": "check news", "neutral": "neutral", "biased": "runs high"}[tag]
    score = (" · EDGE %d" % x["ge_score"]) if x.get("ge_score") is not None else ""
    return _td('%s <span class="tag %s">%s</span><br><span class="sub">%s</span>' % (
        pct(x["ge_p"], 0), tag, label, score.strip(" ·")), round(x["ge_p"], 4))


def _tr(x, cells):
    return '<tr class="%s" data-start="%s">%s</tr>' % ("" if x["flagged"] else "dim", E(x["commence"] or ""),
                                                      "".join(cells))


def _common(x):
    return [
        _td('<input type="checkbox" class="pick" data-code="%s" data-book="%s">' % (x["code"], x["book"])),
        _td(x["code"], int(x["code"]), "code"),
        _td(E(x["player"]), x["player"], "player"),
        _td('%s<br><span class="sub">%s</span>' % (E(x["game"]), E(local_label(x["commence"]))), x["commence"]),
        _td(E(market_label(x["market"])), x["market"]),
    ]


def _table(head, rows, empty):
    if not rows:
        return '<div class="tablewrap"><div class="empty">%s</div></div>' % empty
    ths = "".join('<th%s data-k="1">%s</th>' % (' class="num"' if n else "", h) if h else "<th></th>"
                  for h, n in head)
    return '<div class="tablewrap"><table><thead><tr>%s</tr></thead><tbody>%s</tbody></table></div>' % (
        ths, "".join(rows))


def pickem_table(board, nfl):
    head = [("", 0), ("#", 0), ("Player", 0), ("Game", 0), ("Market", 0), ("App", 0), ("Pick", 0),
            ("Fair", 1), ("Lowest bar", 1), ("Edge", 1), ("Clears", 0)]
    if nfl:
        head.append(("Gridiron Edge", 0))
    head.append(("Sharp lines", 0))
    rows = []
    for x in board["pickem"]:
        cells = _common(x)
        mult = (" ×%g" % x["multiplier"]) if x["multiplier"] and abs(x["multiplier"] - 1) > 1e-9 else ""
        cells += [
            _td(E(BOOK_LABELS.get(x["book"], x["book"])), x["book"]),
            _td(E(_pick_text(x)) + mult + _adj(x), x["point"]),
            _td(pct(x["p"]), round(x["p"], 4), "num"),
            _td(pct(x["breakeven"]), round(x["breakeven"] or 0, 4), "num"),
            _td('<span class="%s">%+.1f</span>' % ("pos" if x["edge"] > 0 else "neg", x["edge"] * 100),
                round(x["edge"], 4), "num"),
            _td(E(", ".join(x["clears"])) or '<span class="sub">—</span>', len(x["clears"])),
        ]
        if nfl:
            cells.append(_ge_cell(x))
        cells.append(_td(E(x["sharp"]), x["n_sharp"], "sharp"))
        rows.append(_tr(x, cells))
    return _table(head, rows, "No pick'em lines matched a sharp price in this pull.")


def fliff_table(board, nfl):
    head = [("", 0), ("#", 0), ("Player", 0), ("Game", 0), ("Market", 0), ("Pick", 0), ("Fliff", 1),
            ("Fair", 1), ("EV", 1)]
    if nfl:
        head.append(("Gridiron Edge", 0))
    head.append(("Sharp lines", 0))
    rows = []
    for x in board["fliff"]:
        cells = _common(x) + [
            _td(E(_pick_text(x)) + _adj(x), x["point"]),
            _td(fmt_american(x["price"]), x["price"], "num"),
            _td(pct(x["p"]), round(x["p"], 4), "num"),
            _td('<span class="%s">%+.1f%%</span>' % ("pos" if x["ev"] > 0 else "neg", x["ev"] * 100),
                round(x["ev"], 4), "num"),
        ]
        if nfl:
            cells.append(_ge_cell(x))
        cells.append(_td(E(x["sharp"]), x["n_sharp"], "sharp"))
        rows.append(_tr(x, cells))
    return _table(head, rows, "No Fliff lines in this pull (check Fliff is in the Odds API response).")


def kalshi_table(board, nfl):
    head = [("", 0), ("#", 0), ("Player", 0), ("Game", 0), ("Market", 0), ("Contract", 0), ("Ask", 1),
            ("Fee", 1), ("Fair", 1), ("EV/contract", 1), ("ROI", 1), ("Size", 1)]
    if nfl:
        head.append(("Gridiron Edge", 0))
    head.append(("Sharp lines", 0))
    rows = []
    for x in board["kalshi"]:
        cells = _common(x) + [
            _td(E(_pick_text(x)) + _adj(x), x["point"]),
            _td("%.0f¢" % (x["ask"] * 100), x["ask"], "num"),
            _td("%.1f¢" % (x["fee"] * 100), x["fee"], "num"),
            _td(pct(x["p"]), round(x["p"], 4), "num"),
            _td('<span class="%s">%+.1f¢</span>' % ("pos" if x["ev"] > 0 else "neg", x["ev"] * 100),
                round(x["ev"], 4), "num"),
            _td('<span class="%s">%+.1f%%</span>' % ("pos" if x["roi"] > 0 else "neg", x["roi"] * 100),
                round(x["roi"], 4), "num"),
            _td("%g" % x["size"] if x["size"] is not None else "—", x["size"] or 0, "num"),
        ]
        if nfl:
            cells.append(_ge_cell(x))
        cells.append(_td(E(x["sharp"]), x["n_sharp"], "sharp"))
        rows.append(_tr(x, cells))
    return _table(head, rows, "No Kalshi ladders matched a sharp price.")


def entries_html(board):
    good = [e for e in board["entries"] if e["roi"] > 0]
    if not good:
        return '<div class="tablewrap"><div class="empty">No entry built from tonight\'s flagged picks shows a profit.</div></div>'
    cards = []
    for e in good[:6]:
        legs = "".join("<li><b>#%s %s</b> %s %s · %s</li>" % (
            l["code"], E(l["player"]), E(_pick_text(l)), E(market_label(l["market"])), pct(l["p"]))
            for l in e["legs"])
        verify = ' <span class="tag biased" title="Payout table not confirmed - check the app">verify payout</span>' if e["verify"] else ""
        cards.append(
            '<div class="entry"><div class="hd"><b>%s</b><span class="%s">%+.1f%% expected</span></div>'
            '<div class="sub" style="margin-bottom:6px">%s%s</div><ol>%s</ol></div>' % (
                E(e["label"]), "pos" if e["roi"] > 0 else "neg", e["roi"] * 100,
                E(BOOK_LABELS.get(e["book"], e["book"])), verify, legs))
    return '<div class="entries">%s</div>' % "".join(cards)


def notes(board, cfg):
    out = []
    counts = board["counts"]
    for b in cfg.pickem_books + cfg.sportsbooks:
        if not counts.get(b):
            out.append("No %s lines came back in this pull. The free Odds API plan may not include it, or it hasn't posted lines yet." % BOOK_LABELS.get(b, b))
    if not any(counts.get(b) for b in cfg.sharp_weights):
        out.append("No sharp-book prices came back, so nothing could be priced.")
    for book in cfg.pickem_books:
        if any(e.get("verify") for e in cfg.entries(book).values()):
            out.append("%s payouts in config.json are placeholders. Check the app and fix them before trusting its breakevens." % BOOK_LABELS.get(book, book))
    if board["league"] == "nfl":
        if not board["ge_rows"]:
            out.append("No Gridiron Edge export loaded. In Gridiron Edge, click Export for Edge Finder, then run ge-import.")
        else:
            out.append("Gridiron Edge is a second opinion only. 'Runs high' marks markets where its median is known to sit too high (Pass Yds, Pass+Rush, Rush+Rec, RB receptions, TE Rec Yds).")
    out.append("Entries assume picks are independent. Same-game picks are kept apart for that reason.")
    return "".join("<li>%s</li>" % E(n) for n in out)


def render(board, cfg, root, web=None):
    """web: {'repo': 'owner/name'} for the GitHub Pages version (Log button opens an issue)."""
    lg = board["league"]
    nfl = lg == "nfl"
    pull = board["pull"]
    built = local(parse_iso(board["built_at"]))
    pulled = local(parse_iso(pull["ts"]))
    flagged = sum(1 for s in ("pickem", "fliff", "kalshi") for x in board[s] if x["flagged"])
    total = sum(len(board[s]) for s in ("pickem", "fliff", "kalshi"))
    chips = [
        "<b>%d</b> flagged of %d priced" % (flagged, total),
        "<b>%d</b> games" % board["games"],
        "pulled <b>%s</b>" % pulled.strftime("%a %I:%M %p").replace(" 0", " "),
    ]
    if pull.get("credits_remaining") is not None:
        chips.append("<b>%s</b> Odds API credits left" % pull["credits_remaining"])
    for b in ("prizepicks", "underdog", "fliff", "kalshi"):
        chips.append("%s <b>%d</b>" % (BOOK_LABELS[b], board["counts"].get(b, 0)))
    if nfl and board["ge_saved"]:
        chips.append("Gridiron Edge scan <b>%s</b>" % local(parse_iso(board["ge_saved"])).strftime("%a %m/%d"))

    be_lines = []
    for book, types in board["breakevens"].items():
        be_lines.append("%s: %s" % (BOOK_LABELS.get(book, book), ", ".join(
            "%s %s" % (e["label"].split(" ", 1)[-1], pct(b)) for _, (e, b) in sorted(types.items(), key=lambda t: t[1][1]))))

    entry_types = {b: {k: {"label": v["label"], "picks": v["picks"]} for k, v in cfg.entries(b).items()}
                   for b in cfg.pickem_books}
    js = (JS.replace("__ENTRIES__", json.dumps(entry_types))
            .replace("__ROOT__", json.dumps(root))
            .replace("__LEAGUE__", json.dumps(lg))
            .replace("__BOARD__", json.dumps(board["built_at"]))
            .replace("__REPO__", json.dumps(web["repo"] if web else None)))
    th = cfg["thresholds"]
    page = """<!doctype html><html lang="en"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>Edge Finder %(LG)s</title><style>%(css)s</style></head><body>
<div class="wrap">
%(nav)s<h1>Edge Finder · %(LG)s</h1>
<div class="sub">Built %(built)s. Lines are priced against the sharp books' fair odds (margin removed). Place every bet by hand.</div>
<div class="chips">%(chips)s</div>
<ul class="notes">%(notes)s</ul>
<div class="toolbar"><label><input type="checkbox" id="showall"> Show every priced line, not just flagged</label></div>

<h2>Best entries tonight <small>top flagged picks per app, one per game</small></h2>
%(entries)s

<h2>Pick'em <small>flagged when fair odds beat an entry's per-pick breakeven by %(cush)s+. Lowest bar = the easiest entry on that app; Clears = every entry it beats</small></h2>
%(pickem)s
<div class="sub" style="margin-top:6px">Per-pick breakevens: %(be)s</div>

<h2>Fliff <small>flagged at %(fev)s+ expected value</small></h2>
%(fliff)s

<h2>Kalshi <small>after the taker fee on %(kc)d contracts; flagged at %(kev)s+ return</small></h2>
%(kalshi)s

<div class="foot">Fair = the sharp books' consensus chance after removing their margin, using whichever of two
de-vig methods is less generous to your side. "adj" means a sharp line sat a little off this one and its price was moved
to this line using the stat's typical spread. Rows need %(minb)s sharp book(s). Judge results by closing line value
(%(clvref)s), not early wins and losses.</div>
</div>
<div class="dock" id="dock"><div class="row">
<span id="count"></span>
<select id="entry"></select>
<label>Stake $ <input id="stake" type="number" min="1" step="1" value="1"></label>
%(logbtn)s<code id="cmd"></code>
<button id="copy" class="%(copycls)s">Copy</button><button class="ghost" id="clear">Clear</button>
</div></div>
<script>%(js)s</script></body></html>""" % {
        "LG": lg.upper(), "css": CSS, "built": built.strftime("%a %b %d, %I:%M %p").replace(" 0", " "),
        "chips": "".join('<span class="chip">%s</span>' % c for c in chips),
        "notes": notes(board, cfg), "entries": entries_html(board),
        "pickem": pickem_table(board, nfl), "fliff": fliff_table(board, nfl), "kalshi": kalshi_table(board, nfl),
        "be": E(" · ".join(be_lines)), "cush": "%g pt" % round(th["pickem_cushion"] * 100, 2),
        "fev": pct(th["fliff_min_ev"], 0), "kev": pct(th["kalshi_min_ev"], 0),
        "kc": cfg["kalshi"]["contracts"], "minb": 1 if th.get("one_book_ok") else th["min_sharp_books"],
        "js": js, "nav": nav_html(lg, web) if web else "",
        "logbtn": '<a id="log" class="btn" target="_blank" rel="noopener">Log bet on GitHub</a>' if web else "",
        "copycls": "ghost" if web else "",
        "clvref": '<a href="bets.html">Bets &amp; CLV</a>' if web else "<code>python3 edgefinder.py clv</code>",
    }
    return page


def nav_html(active, web):
    links = [("index", "Home"), ("nba", "NBA"), ("nfl", "NFL"), ("bets", "Bets & CLV")]
    return '<nav class="top">%s</nav>' % "".join(
        '<a href="%s.html"%s>%s</a>' % (k, ' class="on"' if k == active else "", E(t)) for k, t in links)


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
                    "fair_p", "breakeven", "edge", "price_or_ask", "ev", "n_sharp", "adj_gap", "ge_p", "ge_tag", "sharp"])
        for sec in ("pickem", "fliff", "kalshi"):
            for x in board[sec]:
                w.writerow([x["code"], sec, int(x["flagged"]), x["book"], x["player"], x["game"], x["commence"],
                            x["market"], x["side"], x["point"], round(x["p"], 4),
                            round(x["breakeven"], 4) if x.get("breakeven") else "",
                            round(x["edge"], 4) if x.get("edge") is not None else "",
                            x["ask"] if sec == "kalshi" else (x["price"] or ""),
                            round(x["ev"], 4) if x.get("ev") is not None else "",
                            x["n_sharp"], x["gap"], round(x["ge_p"], 4) if x.get("ge_p") is not None else "",
                            x.get("ge_tag") or "", x["sharp"]])
    return path, csv_path
