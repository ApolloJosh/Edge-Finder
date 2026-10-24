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

from . import board as boardmod
from .bets import update_closes
from . import render
from .board import BOOK_LABELS, market_label
from .util import local, parse_iso, utcnow

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
.res .btn,.res button{width:100%;min-height:46px}

.badge{font-size:12px;font-weight:700;border-radius:6px;padding:2px 8px;background:var(--chip);color:var(--dim)}
.badge.win{background:var(--accent-bg);color:var(--accent)}.badge.loss{background:var(--bad-bg);color:var(--bad)}
"""

AGO_JS = """<script>document.querySelectorAll('[data-ago]').forEach(el=>{const m=Math.round((Date.now()-Date.parse(el.dataset.ago))/60000);
el.textContent=m<1?'just now':m<60?m+' min ago':Math.floor(m/60)+'h '+(m%60)+'m ago';});</script>"""


def _page(title, active, content, web, js=""):
    return (render.head(title, web=True).replace("</style>", EXTRA_CSS + RESULTS_CSS + "</style>") +
            '<body><header class="bar"><div class="wrap">%s</div></header><main class="wrap">%s</main>%s%s%s</body></html>' % (
                render.nav_html(active, web), content, render.ef_script(web["repo"]), AGO_JS, js))


def _when(iso):
    return local(parse_iso(iso)).strftime("%a %b %d, %I:%M %p").replace(" 0", " ")


def copy_static(out_dir):
    if not os.path.isdir(STATIC):
        return
    for name in os.listdir(STATIC):
        shutil.copyfile(os.path.join(STATIC, name), os.path.join(out_dir, name))


HOME_JS = r"""<script>
document.querySelectorAll('[data-cmd]').forEach(b => b.onclick = async e => {
  e.preventDefault();
  const n = await EF.send(b.dataset.cmd, 'refresh', {});
  if (n) EF.toast('Refresh requested. New lines in about 2 minutes.');
});
</script>"""


def build_site(con, cfg, out_dir, now=None, status=None):
    """Write index.html, nba.html, nfl.html, bets.html and bets-data.json into out_dir."""
    now = now or utcnow()
    repo = cfg["github"]["repo"]
    web = {"repo": repo}
    os.makedirs(out_dir, exist_ok=True)
    copy_static(out_dir)
    update_closes(con, cfg, now)
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

    data = results_payload(con, cfg, repo, now)
    with open(os.path.join(out_dir, "bets.html"), "w") as f:
        f.write(bets_page(data, web))
    with open(os.path.join(out_dir, "bets-data.json"), "w") as f:
        json.dump(data, f, separators=(",", ":"))

    settled = [b for b in data["bets"] if b["res"]]
    net = sum((b["pay"] or 0) - (b["stake"] or 0) for b in settled)
    open_n = sum(1 for b in data["bets"] if not b["res"])
    res_txt = ("%s%.2f net · %d settled" % ("+" if net >= 0 else "−", abs(net), len(settled))) if settled else "No settled bets yet"
    last = con.execute("SELECT * FROM pulls ORDER BY id DESC LIMIT 1").fetchone()
    credits = last["credits_remaining"] if last and last["credits_remaining"] is not None else None
    tile_html = "".join('<a class="tile" href="%s.html"><div class="k">%s</div><div class="v">%s</div><div class="s">%s</div></a>' % (
        lg, lg.upper(), E(v), sub) for lg, v, sub in tiles)
    tile_html += ('<a class="tile" href="bets.html"><div class="k">Results</div><div class="v">%d open</div>'
                  '<div class="s">%s</div></a>' % (open_n, E(res_txt)))
    content = """<h1>Edge Finder</h1>
<div class="sub">Updated <span data-ago="%(upd)s"></span>%(cred)s</div>
<div class="tiles">%(tiles)s</div>
<div class="actions">
<button class="ghost" data-cmd="refresh nba">Refresh NBA now</button>
<button class="ghost" data-cmd="refresh nfl">Refresh NFL now</button>
</div>
<div class="sub" style="margin-top:6px">Use these when lineup news breaks. Each refresh costs Odds API credits.</div>
<details class="how"><summary>How it works</summary><ol>
<li>Every 15 minutes, GitHub pulls each game about %(off)s minutes before tip and prices every line against the sharp books.</li>
<li>Open a board, tap the picks you actually play, then <b>Save bet</b>. The first time, Settings walks you through a one-time key.</li>
<li>Closing lines are saved before each game you bet, and results are graded from ESPN box scores after the game.</li>
<li><a href="bets.html">Results</a> shows your record, profit over time, closing line value, and what's working by app, stat and entry.</li>
<li>On NFL game days it runs Gridiron Edge itself and shows its read on each pick.</li>
<li>Add to your Home Screen: Share → <b>Add to Home Screen</b>. It opens full screen like an app.</li>
</ol></details>
<div class="foot">%(status)s</div>""" % {
        "upd": E(iso_now(now)),
        "cred": (" · %s Odds API credits left" % credits) if credits is not None else "",
        "tiles": tile_html, "off": offsets, "status": E(status or ""),
    }
    with open(os.path.join(out_dir, "index.html"), "w") as f:
        f.write(_page("Edge Finder", "index", content, web, HOME_JS))
    with open(os.path.join(out_dir, ".nojekyll"), "w") as f:
        f.write("")
    return out_dir


def iso_now(now):
    return now.strftime("%Y-%m-%dT%H:%M:%SZ")


# ------------------------------------------------------------------ results page

def results_payload(con, cfg, repo, now):
    bets = []
    for b in con.execute("SELECT * FROM bets ORDER BY placed_at, id").fetchall():
        legs = con.execute("SELECT * FROM bet_legs WHERE bet_id=? ORDER BY leg", (b["id"],)).fetchall()
        if b["book"] in cfg.pickem_books:
            entry = (cfg.entries(b["book"]).get(b["entry_type"] or "") or {}).get("label") or b["entry_type"]
        elif b["book"] == "kalshi":
            entry = "Kalshi · %d contracts" % int(b["contracts"] or 0)
        else:
            entry = "%s · straight" % BOOK_LABELS.get(b["book"], b["book"])
        starts = [l["commence_time"] for l in legs if l["commence_time"]]
        bets.append({
            "id": b["id"], "placed": b["placed_at"], "lg": b["league"], "book": b["book"],
            "bl": BOOK_LABELS.get(b["book"], b["book"]), "entry": entry, "et": b["entry_type"],
            "stake": round(b["stake"] or 0, 2), "res": b["result"],
            "pay": None if b["payout"] is None else round(b["payout"], 2),
            "auto": b["graded_by"] == "auto", "note": b["notes"], "start": min(starts) if starts else None,
            "legs": [{"pl": l["player"], "m": market_label(l["market"]), "side": l["side"], "pt": l["point"],
                      "fair": l["fair_p"], "close": l["close_fair_p"], "fl": l["flagged"], "edge": l["edge"],
                      "act": l["actual"], "lr": l["leg_result"], "gp": l["ge_p"], "lg": b["league"]} for l in legs],
        })
    g = cfg["gridiron_edge"]
    return {"repo": repo, "gen": iso_now(now), "bets": bets, "geAgree": g["agree_at"], "geConflict": g["conflict_at"]}


RESULTS_CSS = """
.viz{--s-pos:#2a78d6;--s-neg:#e34948;--grid:#e1e0d9;--base:#c3c2b7}
@media (prefers-color-scheme:dark){:root:not([data-theme=light]) .viz{--s-pos:#3987e5;--s-neg:#e66767;--grid:#2c2c2a;--base:#383835}}
.filters{display:flex;gap:8px;align-items:center;margin:14px 0 4px;overflow-x:auto;scrollbar-width:none}
.filters::-webkit-scrollbar{display:none}
.chart{position:relative;background:var(--panel);border:1px solid var(--line);border-radius:14px;padding:12px 12px 6px;margin-top:10px}
.chart .t{font-weight:650;font-size:14px}.chart .st{font-size:12.5px;color:var(--faint);margin-bottom:4px}
.chart svg{display:block;width:100%;height:190px;touch-action:pan-y}
.chart .tip{position:absolute;pointer-events:none;background:var(--ink);color:var(--bg);border-radius:8px;padding:6px 9px;font-size:12.5px;
line-height:1.35;white-space:nowrap;display:none;z-index:2}
.chart .tip b{font-size:14px}
.bars{background:var(--panel);border:1px solid var(--line);border-radius:14px;padding:4px 14px}
.bar-row{padding:10px 0 9px;border-bottom:1px solid var(--line)}
.bar-row:last-child{border-bottom:0}
.bar-row .top{display:flex;justify-content:space-between;align-items:baseline;gap:10px}
.bar-row .lab{font-size:14px;font-weight:600}
.bar-row .track{margin:7px 0 5px}
.bar-row .sub2{font-size:12px;color:var(--faint)}
.bar-row.small .lab,.bar-row.small .val{color:var(--faint)}
.track{position:relative;height:14px}
.track .zero{position:absolute;left:50%;top:-3px;bottom:-3px;width:1px;background:var(--base)}
.track .fill{position:absolute;top:0;height:14px}
.track .fill.pos{left:50%;background:var(--s-pos);border-radius:0 4px 4px 0}
.track .fill.neg{right:50%;background:var(--s-neg);border-radius:4px 0 0 4px}
.val{font-size:14px;font-weight:700;font-variant-numeric:tabular-nums;text-align:right;white-space:nowrap}
.legs2{list-style:none;margin:8px 0 0;padding:0}
.legs2 li{font-size:13.5px;padding:6px 0;border-top:1px solid var(--line)}
.legs2 li:first-child{border-top:0}
.mark{font-weight:800;margin-right:4px}
.mark.hit{color:var(--accent)}.mark.miss{color:var(--bad)}.mark.other{color:var(--faint)}
.badge.saving{background:var(--warn-bg);color:var(--warn)}
"""

RESULTS_JS = r"""<script>
(function () {
let D = window.RD;
const $ = s => document.querySelector(s);
const esc = s => String(s == null ? '' : s).replace(/[&<>"']/g, c => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
const pct = (p, d = 0) => (p * 100).toFixed(d) + '%';
const sgn = (x, d = 1) => (x >= 0 ? '+' : '−') + Math.abs(x).toFixed(d);
const money = x => (x >= 0 ? '+$' : '−$') + Math.abs(x).toFixed(2);
const day = iso => new Date(iso).toLocaleDateString(undefined, {month: 'short', day: 'numeric'});
const when = iso => new Date(iso).toLocaleDateString(undefined, {weekday: 'short'}) + ' ' + new Date(iso).toLocaleTimeString(undefined, {hour: 'numeric', minute: '2-digit'});
let range = 'all', league = 'all';
try { range = localStorage.getItem('ef-range') || 'all'; } catch (e) {}

function outcome(b) { if (b.res == null) return null; const d = (b.pay || 0) - b.stake; return d > 0.005 ? 'W' : d < -0.005 ? 'L' : 'P'; }
function inScope(b) {
  if (league !== 'all' && b.lg !== league) return false;
  if (range === 'all') return true;
  return Date.now() - Date.parse(b.placed) <= (+range) * 864e5;
}
function geTag(p) { return p == null ? 'no read' : p >= D.geAgree ? 'agrees' : p <= D.geConflict ? 'disagrees' : 'neutral'; }

// ---------- charts (single series, one axis, hairline grid, crosshair tooltip)
function niceTicks(lo, hi) {
  if (lo === hi) { lo -= 1; hi += 1; }
  const step0 = (hi - lo) / 3, mag = Math.pow(10, Math.floor(Math.log10(step0)));
  const step = [1, 2, 2.5, 5, 10].map(m => m * mag).find(s => s >= step0);
  const out = [], top = Math.ceil(hi / step - 1e-9) * step;
  for (let v = Math.floor(lo / step + 1e-9) * step; v <= top + 1e-9; v += step) out.push(+v.toFixed(6));
  return out;
}
function lineChart(el, pts, fmt, tipFn) {
  const svg = el.querySelector('svg'), tip = el.querySelector('.tip');
  const W = el.clientWidth - 24, H = 190, L = 44, R = 12, T = 10, B = 22;
  svg.setAttribute('viewBox', `0 0 ${W} ${H}`);
  const ys = pts.map(p => p.y).concat([0]);
  const ticks = niceTicks(Math.min(...ys), Math.max(...ys));
  const y0 = ticks[0], y1 = ticks[ticks.length - 1];
  const X = i => L + (pts.length === 1 ? (W - L - R) / 2 : i * (W - L - R) / (pts.length - 1));
  const Y = v => T + (H - T - B) * (1 - (v - y0) / (y1 - y0));
  let g = ticks.map(t => `<line x1="${L}" x2="${W - R}" y1="${Y(t)}" y2="${Y(t)}" stroke="var(${t === 0 ? '--base' : '--grid'})" stroke-width="1"/>
<text x="${L - 6}" y="${Y(t) + 4}" text-anchor="end" font-size="11" fill="var(--faint)">${esc(fmt(t))}</text>`).join('');
  const d = pts.map((p, i) => `${i ? 'L' : 'M'}${X(i).toFixed(1)},${Y(p.y).toFixed(1)}`).join('');
  const area = d + `L${X(pts.length - 1).toFixed(1)},${Y(0)}L${X(0).toFixed(1)},${Y(0)}Z`;
  const last = pts[pts.length - 1];
  g += `<path d="${area}" fill="var(--s-pos)" opacity="0.1"/>
<path d="${d}" fill="none" stroke="var(--s-pos)" stroke-width="2" stroke-linejoin="round" stroke-linecap="round"/>
<circle cx="${X(pts.length - 1)}" cy="${Y(last.y)}" r="5" fill="var(--s-pos)" stroke="var(--panel)" stroke-width="2"/>
<text x="${L}" y="${H - 5}" font-size="11" fill="var(--faint)">${esc(pts[0].label)}</text>
<text x="${W - R}" y="${H - 5}" font-size="11" fill="var(--faint)" text-anchor="end">${esc(last.label)}</text>
<line class="xh" x1="0" x2="0" y1="${T}" y2="${H - B}" stroke="var(--faint)" stroke-width="1" visibility="hidden"/>
<circle class="xd" r="5" fill="var(--s-pos)" stroke="var(--panel)" stroke-width="2" visibility="hidden"/>
<rect x="${L}" y="0" width="${W - L - R}" height="${H}" fill="transparent" class="hit"/>`;
  svg.innerHTML = g;
  const xh = svg.querySelector('.xh'), xd = svg.querySelector('.xd'), hit = svg.querySelector('.hit');
  const show = ev => {
    const r = svg.getBoundingClientRect(), x = (ev.clientX - r.left) * W / r.width;
    const i = Math.max(0, Math.min(pts.length - 1, Math.round((x - L) / ((W - L - R) / Math.max(1, pts.length - 1)))));
    const px = X(i), py = Y(pts[i].y);
    xh.setAttribute('x1', px); xh.setAttribute('x2', px); xh.setAttribute('visibility', 'visible');
    xd.setAttribute('cx', px); xd.setAttribute('cy', py); xd.setAttribute('visibility', 'visible');
    tip.innerHTML = tipFn(pts[i]); tip.style.display = 'block';
    const tx = px * r.width / W + 12, maxX = el.clientWidth - tip.offsetWidth - 6;
    tip.style.left = Math.max(6, Math.min(tx - tip.offsetWidth / 2, maxX)) + 'px'; tip.style.top = '30px';
  };
  const hide = () => { xh.setAttribute('visibility', 'hidden'); xd.setAttribute('visibility', 'hidden'); tip.style.display = 'none'; };
  hit.addEventListener('pointermove', show); hit.addEventListener('pointerdown', show); hit.addEventListener('pointerleave', hide);
}
function chartBox(id, title, sub) {
  return `<div class="chart viz" id="${id}"><div class="t">${esc(title)}</div><div class="st">${esc(sub)}</div><svg role="img" aria-label="${esc(title)}"></svg><div class="tip"></div></div>`;
}

// ---------- diverging bars (value labelled with its sign, so color never carries it alone)
function barGroup(title, rows, fmtV, note) {
  if (!rows.length) return '';
  const max = Math.max(...rows.map(r => Math.abs(r.v)), 1e-9);
  return `<h2>${esc(title)}${note ? ` <small>${esc(note)}</small>` : ''}</h2><div class="bars viz">` + rows.map(r => {
    const w = Math.max(1.5, 50 * Math.abs(r.v) / max);
    return `<div class="bar-row${r.n < 10 ? ' small' : ''}"><div class="top"><span class="lab">${esc(r.k)}</span><span class="val">${esc(fmtV(r.v))}</span></div>
<div class="track"><div class="zero"></div><div class="fill ${r.v >= 0 ? 'pos' : 'neg'}" style="width:${w}%"></div></div>
<div class="sub2">${esc(r.sub)}${r.n < 10 ? ' · small sample' : ''}</div></div>`;
  }).join('') + '</div>';
}
function byBets(list, keyFn) {
  const m = new Map();
  for (const b of list) { const k = keyFn(b); if (k == null) continue; (m.get(k) || m.set(k, []).get(k)).push(b); }
  return [...m].map(([k, bs]) => {
    const st = bs.reduce((s, b) => s + b.stake, 0), net = bs.reduce((s, b) => s + (b.pay || 0) - b.stake, 0);
    const rec = ['W', 'L', 'P'].map(o => bs.filter(b => outcome(b) === o).length).join('-');
    return {k, n: bs.length, v: st ? net / st : 0, sub: `${rec} · ${money(net)} on $${st.toFixed(0)}`};
  }).sort((a, b) => b.n - a.n);
}
function byLegs(legs, keyFn) {
  const m = new Map();
  for (const l of legs) { const k = keyFn(l); if (k == null) continue; (m.get(k) || m.set(k, []).get(k)).push(l); }
  return [...m].map(([k, ls]) => {
    const hit = ls.filter(l => l.lr === 'hit').length, exp = ls.reduce((s, l) => s + l.fair, 0) / ls.length;
    const rate = hit / ls.length;
    return {k, n: ls.length, v: rate - exp, sub: `hit ${pct(rate)} vs ${pct(exp)} expected · ${ls.length} legs`};
  }).sort((a, b) => b.n - a.n);
}

// ---------- page
function render() {
  const bets = D.bets.filter(inScope);
  const settled = bets.filter(b => b.res != null).sort((a, b) => (a.start || a.placed).localeCompare(b.start || b.placed));
  const staked = settled.reduce((s, b) => s + b.stake, 0), net = settled.reduce((s, b) => s + (b.pay || 0) - b.stake, 0);
  const rec = ['W', 'L', 'P'].map(o => settled.filter(b => outcome(b) === o).length);
  const clvLegs = bets.flatMap(b => b.legs).filter(l => l.close != null && l.fair != null);
  const clv = clvLegs.length ? clvLegs.reduce((s, l) => s + l.close - l.fair, 0) / clvLegs.length : null;
  const graded = settled.flatMap(b => b.legs.map(l => Object.assign({book: b.bl}, l))).filter(l => l.lr === 'hit' || l.lr === 'miss');
  let h = `<div class="kpis">
<div class="kpi"><div class="k">Record</div><div class="v">${settled.length ? rec.join('-') : '—'}</div><div class="s">won-lost-push · ${settled.length} settled</div></div>
<div class="kpi"><div class="k">Profit</div><div class="v ${net >= 0 ? 'pos' : 'neg'}">${settled.length ? money(net) : '—'}</div><div class="s">${settled.length ? sgn(100 * net / staked) + '% on $' + staked.toFixed(0) + ' staked' : 'nothing settled yet'}</div></div>
<div class="kpi"><div class="k">Closing line value</div><div class="v ${clv != null && clv >= 0 ? 'pos' : clv != null ? 'neg' : ''}">${clv == null ? '—' : sgn(100 * clv)}</div><div class="s">${clv == null ? 'fills in at tip-off' : 'pts per leg · ' + clvLegs.length + ' legs'}</div></div>
<div class="kpi"><div class="k">Legs hit</div><div class="v">${graded.length ? pct(graded.filter(l => l.lr === 'hit').length / graded.length) : '—'}</div><div class="s">${graded.length ? 'vs ' + pct(graded.reduce((s, l) => s + l.fair, 0) / graded.length) + ' expected · ' + graded.length + ' legs' : 'graded after each game'}</div></div></div>`;
  if (settled.length >= 2) h += chartBox('c-pl', 'Profit over time', 'Running total after each settled bet');
  else h += `<div class="empty" style="margin-top:10px">Your profit chart starts after two settled bets. Results are graded from ESPN box scores after each game.</div>`;
  if (clvLegs.length >= 2) h += chartBox('c-clv', 'Closing line value', `Average over your last ${Math.min(20, clvLegs.length)} legs, in percentage points. Above zero means the market moved your way`);
  h += barGroup('What\'s working: by app', byBets(settled, b => b.bl), v => sgn(100 * v) + '%', 'return on money staked');
  h += barGroup('By entry type', byBets(settled, b => b.book === 'kalshi' ? 'Kalshi contracts' : b.et === 'straight' ? b.bl + ' straight' : b.entry), v => sgn(100 * v) + '%');
  h += barGroup('Flagged picks vs your own', byBets(settled, b => b.legs.every(l => l.fl) ? 'Only flagged picks' : 'Includes your own picks'), v => sgn(100 * v) + '%', 'did sticking to the board pay?');
  h += barGroup('By stat', byLegs(graded, l => l.m), v => sgn(100 * v) + ' pts', 'hit rate minus what the market expected');
  const nflLegs = graded.filter(l => l.lg === 'nfl');
  if (nflLegs.length) h += barGroup('Gridiron Edge read', byLegs(nflLegs, l => 'Gridiron Edge ' + geTag(l.gp)), v => sgn(100 * v) + ' pts', 'NFL legs: did its read help?');
  if (settled.length && settled.length < 100) h += `<div class="sub" style="margin-top:10px">Under 100 bets, records swing on luck. Closing line value is the earlier signal.</div>`;

  // lists
  const recorded = new Set(D.bets.map(b => b.note).filter(Boolean));
  const settledIds = new Set(D.bets.filter(b => b.res != null).map(b => b.id));
  const pend = EF.pending(p => p.kind === 'bet' ? recorded.has('issue #' + p.n) : p.kind === 'result' ? settledIds.has(p.bet) : Date.now() - p.ts > 15 * 60e3);
  const pendBets = pend.filter(p => p.kind === 'bet');
  if (pendBets.length) h += '<h2>Recording</h2><div class="grid">' + pendBets.map(p => `<div class="card bet"><div class="row1"><b>${esc(p.summary || p.args)}</b><span class="badge saving">saving</span></div>
<div class="meta">Saved ${esc(when(new Date(p.ts).toISOString()))}. It shows here once the next run records it, usually within 2 minutes.</div></div>`).join('') + '</div>';
  const pendRes = new Map(pend.filter(p => p.kind === 'result').map(p => [p.bet, p.outcome]));
  const open = bets.filter(b => b.res == null).sort((a, b) => (a.start || '').localeCompare(b.start || ''));
  h += `<h2>Open <small>graded automatically after each game</small></h2>`;
  h += open.length ? '<div class="grid">' + open.map(b => betCard(b, pendRes.get(b.id))).join('') + '</div>' : '<div class="empty">No open bets.</div>';
  const done = bets.filter(b => b.res != null).sort((a, b) => (b.start || b.placed).localeCompare(a.start || a.placed)).slice(0, 60);
  h += '<h2>Settled</h2>' + (done.length ? '<div class="grid">' + done.map(b => betCard(b)).join('') + '</div>' : '<div class="empty">Nothing settled yet.</div>');
  $('#res').innerHTML = h;

  if (settled.length >= 2) {
    let run = 0;
    const pts = settled.map(b => { run += (b.pay || 0) - b.stake; return {y: run, label: day(b.start || b.placed), b}; });
    lineChart($('#c-pl'), pts, v => (v < 0 ? '−$' : '$') + Math.abs(v).toFixed(0),
      p => `<b>${money(p.y)}</b> total<br>#${p.b.id} ${esc(p.b.entry)} · ${money((p.b.pay || 0) - p.b.stake)}<br>${esc(p.label)}`);
  }
  if (clvLegs.length >= 2) {
    const ordered = bets.flatMap(b => b.legs.map(l => Object.assign({placed: b.placed}, l))).filter(l => l.close != null && l.fair != null)
      .sort((a, b) => a.placed.localeCompare(b.placed));
    const pts = ordered.map((l, i) => { const w = ordered.slice(Math.max(0, i - 19), i + 1);
      return {y: 100 * w.reduce((s, x) => s + x.close - x.fair, 0) / w.length, label: day(l.placed), l, n: w.length}; });
    lineChart($('#c-clv'), pts, v => (v > 0 ? '+' : '') + v.toFixed(1),
      p => `<b>${sgn(p.y)} pts</b> avg of ${p.n} legs<br>${esc(p.l.pl)} ${p.l.side === 'over' ? 'Over' : 'Under'} ${p.l.pt} ${esc(p.l.m)}<br>${esc(p.label)}`);
  }
}

function betCard(b, savingResult) {
  const o = outcome(b);
  const head = `<div class="row1"><b>#${b.id} ${esc(b.entry)}</b><span class="big">$${b.stake.toFixed(2)}</span></div>
<div class="meta">${esc(b.lg.toUpperCase())} · placed ${esc(when(b.placed))}${b.start ? ' · starts ' + esc(when(b.start)) : ''}</div>`;
  const legs = '<ul class="legs2">' + b.legs.map(l => {
    const mk = l.lr === 'hit' ? '<span class="mark hit">✓</span>' : l.lr === 'miss' ? '<span class="mark miss">✗</span>' : l.lr ? `<span class="mark other">${esc(l.lr)}</span>` : '';
    const act = l.act != null ? ` · got ${l.act}` : '';
    const clv = l.close != null ? ` · close ${pct(l.close, 1)} <b class="${l.close >= l.fair ? 'pos' : 'neg'}">${sgn(100 * (l.close - l.fair))}</b>` : '';
    return `<li>${mk}<b>${esc(l.pl)}</b> ${l.side === 'over' ? 'Over' : 'Under'} ${l.pt} ${esc(l.m)}<div class="meta">fair ${pct(l.fair, 1)}${clv}${act}</div></li>`;
  }).join('') + '</ul>';
  if (b.res != null) {
    const cls = o === 'W' ? 'win' : o === 'L' ? 'loss' : '';
    return `<div class="card bet">${head}<div class="meta"><span class="badge ${cls}">${esc(b.res)} · $${(b.pay || 0).toFixed(2)}</span>${b.auto ? ' graded from the box score' : ''}</div>${legs}</div>`;
  }
  const stale = b.start && Date.now() - Date.parse(b.start) > 5 * 3600e3;
  const btns = savingResult ? `<div class="meta" style="margin-top:10px"><span class="badge saving">saving ${esc(savingResult)}</span></div>` :
    `<div class="res">${['win', 'loss', 'push'].map(x => `<button class="${x === 'win' ? 'win' : 'ghost'}" data-res="${x}" data-bet="${b.id}">${x[0].toUpperCase() + x.slice(1)}</button>`).join('')}</div>`;
  return `<div class="card bet">${head}${stale ? '<div class="meta"><span class="badge saving">needs your result</span> couldn\'t be graded automatically</div>' : ''}${legs}${btns}</div>`;
}

document.addEventListener('click', async e => {
  const r = e.target.closest('[data-res]');
  if (r) {
    r.disabled = true;
    const n = await EF.send(`result ${r.dataset.bet} ${r.dataset.res}`, 'result', {bet: +r.dataset.bet, outcome: r.dataset.res});
    if (n) EF.toast('Result saved.');
    render(); return;
  }
  const f = e.target.closest('[data-range],[data-lg]');
  if (f) {
    if (f.dataset.range) { range = f.dataset.range; try { localStorage.setItem('ef-range', range); } catch (x) {} }
    if (f.dataset.lg) league = f.dataset.lg;
    document.querySelectorAll('[data-range]').forEach(x => x.classList.toggle('on', x.dataset.range === range));
    document.querySelectorAll('[data-lg]').forEach(x => x.classList.toggle('on', x.dataset.lg === league));
    render();
  }
});
document.querySelectorAll('[data-range]').forEach(x => x.classList.toggle('on', x.dataset.range === range));
render();
let resized; window.addEventListener('resize', () => { clearTimeout(resized); resized = setTimeout(render, 150); });

// While a save is waiting to be recorded, check for fresh data every 30 seconds.
setInterval(async () => {
  if (!EF.pending().length) return;
  try {
    const r = await fetch('bets-data.json?t=' + Date.now(), {cache: 'no-store'});
    if (r.ok) { const nd = await r.json(); if (nd.gen !== D.gen) { D = nd; render(); } }
  } catch (e) {}
}, 30000);
})();
</script>"""


def bets_page(data, web):
    content = """<h1>Results</h1>
<div class="filters">
<div class="seg"><button data-range="7">7 days</button><button data-range="30">30 days</button><button data-range="all" class="on">All</button></div>
<button class="chip on" data-lg="all">All</button><button class="chip" data-lg="nba">NBA</button><button class="chip" data-lg="nfl">NFL</button>
</div>
<div id="res"></div>"""
    js = "<script>window.RD = %s;</script>%s" % (json.dumps(data, separators=(",", ":")).replace("</", "<\\/"), RESULTS_JS)
    return _page("Edge Finder results", "bets", content, web, js)


def write_json(path, data):
    with open(path, "w") as f:
        json.dump(data, f, indent=2, default=str)


def comment_for(cmd, ok, text):
    head = "Done." if ok else "That didn't go through."
    text = re.sub(r"\n{3,}", "\n\n", text or "")
    return "%s\n\n```\n%s\n```\n\n_Command:_ `%s`" % (head, text[-6000:] or "(no output)", " ".join(cmd))
