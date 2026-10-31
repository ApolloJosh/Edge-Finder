"""The Check page: price any player line from an app with no feed (Robinhood)
and get a plain Take it / Skip it call.

The math mirrors fair.consensus exactly: each sharp book's de-vigged price
comes in as an implied mean (worked out in check.py), the page moves it to the
line you type with the same normal model and continuity correction, drops books
that are too far away or would move too much, applies the same haircut for a
moved price, then compares the fair chance with the price plus fees.
"""

CONTENT = """<div class="titlerow"><h1>Check a price</h1><button class="info" data-info="check" aria-label="How Check works">i</button></div>
<div class="sub">For Robinhood and other apps without a price feed.</div>
<div class="ck-top">
<div class="seg" id="ck-lg"><button data-l="nfl">NFL</button><button data-l="nba">NBA</button></div>
<input id="ck-q" type="search" placeholder="Player name" autocomplete="off" autocapitalize="off" spellcheck="false" aria-label="Player name">
</div>
<div id="ck-list"></div>
<div id="ck-pick"></div>
<div class="foot" id="ck-foot"></div>"""

CSS = """
.ck-top{display:flex;gap:10px;align-items:center;margin:14px 0 8px}
.ck-top input{flex:1;min-width:0;min-height:44px;font:inherit;font-size:16px;padding:0 12px;border:1px solid var(--line);border-radius:10px;
background:var(--panel);color:var(--ink)}
#ck-list .hit{display:block;width:100%;text-align:left;background:var(--panel);border:1px solid var(--line);border-radius:12px;
padding:10px 14px;margin-top:8px;color:var(--ink);font:inherit;min-height:0;font-weight:400}
#ck-list .hit b{font-weight:700}
#ck-list .hit .meta{margin-top:2px}
.ck{padding:14px}
.ck .chips{display:flex;flex-wrap:wrap;gap:6px;margin:10px 0 4px}
.ck .grid2{display:grid;grid-template-columns:1fr 1fr;gap:10px;margin-top:12px}
.ck label.ckf{display:flex;flex-direction:column;gap:5px;font-size:12.5px;font-weight:650;color:var(--dim)}
.ck .num{display:flex;align-items:center;border:1px solid var(--line);border-radius:10px;overflow:hidden;background:var(--bg)}
.ck .num button{background:transparent;color:var(--ink);border:0;border-radius:0;min-width:40px;font-size:20px;padding:0;min-height:44px}
.ck .num input{flex:1;min-width:0;width:100%;border:0;background:transparent;color:var(--ink);font:inherit;font-size:17px;font-weight:700;
text-align:center;min-height:44px;-moz-appearance:textfield}
.ck .num input::-webkit-outer-spin-button,.ck .num input::-webkit-inner-spin-button{-webkit-appearance:none;margin:0}
.ck .num span{padding-right:12px;color:var(--dim);font-weight:650}
.ck .num input:focus{outline:none}
.ck .num:focus-within{border-color:var(--ink)}
.ck .sides{display:grid;grid-template-columns:1fr 1fr;gap:8px;margin-top:12px}
.ck .sides button{min-height:52px;flex-direction:column;gap:1px;background:var(--panel);color:var(--ink);border:1px solid var(--line)}
.ck .sides button small{font-weight:600;color:var(--dim);font-size:12.5px}
.ck .sides button.on{border:2px solid var(--ink)}
.verdict{border-radius:14px;padding:14px 16px;margin-top:14px;border:1px solid var(--line);background:var(--bg)}
.verdict .call{font-size:26px;font-weight:850;line-height:1.1;letter-spacing:-.01em}
.verdict .why{font-size:14.5px;margin-top:6px;line-height:1.45}
.verdict .nums{font-size:13px;color:var(--dim);margin-top:8px;line-height:1.5}
.verdict.take{background:var(--accent-bg);border-color:var(--accent)}
.verdict.take .call{color:var(--accent)}
.verdict.skip{background:var(--bad-bg);border-color:var(--bad)}
.verdict.skip .call{color:var(--bad)}
.verdict.wait .call{font-size:20px}
.ck .after{display:flex;gap:10px;margin-top:12px}
.ck .after button{flex:1}
.ck .after button:disabled{opacity:.45;cursor:default}
.ck .stale{color:var(--warn);font-weight:650}
"""

JS = r"""<script>
(function () {
const $ = s => document.querySelector(s);
const esc = s => String(s == null ? '' : s).replace(/[&<>"']/g, c => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
const store = {get(k, d) { try { const v = localStorage.getItem(k); return v == null ? d : v; } catch (e) { return d; } },
               set(k, v) { try { localStorage.setItem(k, v); } catch (e) {} }};
const when = iso => { const d = new Date(iso); return d.toLocaleDateString([], {weekday: 'short'}) + ' ' + d.toLocaleTimeString([], {hour: 'numeric', minute: '2-digit'}); };
const ago = iso => { const m = Math.round((Date.now() - Date.parse(iso)) / 60000); return m < 60 ? m + ' min ago' : Math.floor(m / 60) + 'h ' + (m % 60) + 'm ago'; };
const pct = (p, d = 1) => (100 * p).toFixed(d) + '%';
const sgn = x => (x >= 0 ? '+' : '−') + Math.abs(100 * x).toFixed(1) + '%';
const norm = s => (s || '').toLowerCase().normalize('NFD').replace(/[\u0300-\u036f]/g, '').replace(/[^a-z0-9 ]/g, ' ');

let lg = store.get('ef-check-lg', 'nfl');
const cache = {};
let D = null, players = [], cur = null;   // cur: {key, ev, items, m, n, side, cents}

// ---------- the model (same as fair.py)
function cdf(z) {   // standard normal, |error| < 1.5e-7
  const t = 1 / (1 + 0.3275911 * Math.abs(z) / Math.SQRT2);
  const y = 1 - (((((1.061405429 * t - 1.453152027) * t) + 1.421413741) * t - 0.284496736) * t + 0.254829592) * t * Math.exp(-z * z / 2);
  return z >= 0 ? (1 + y) / 2 : (1 - y) / 2;
}
const whole = x => Math.abs(x - Math.round(x)) < 1e-9;
function sigmaFor(m, line) {
  const [kind, k, floor] = D.models[m] || ['sqrt', 1.2, 0];
  line = Math.max(line, 0.5);
  const s = kind === 'cv' ? Math.max(k * line, 1) : Math.max(k * Math.sqrt(line), 0.5);
  return Math.max(s, floor);
}
function condOver(mu, s, line) {
  let o, u;
  if (whole(line)) { const hi = cdf((line + 0.5 - mu) / s), lo = cdf((line - 0.5 - mu) / s); o = 1 - hi; u = lo; }
  else { const c = cdf((line - mu) / s); o = 1 - c; u = c; }
  return o + u > 0 ? o / (o + u) : 0.5;
}
function consensus(it, target) {
  let nm = 0, np = 0, den = 0; const used = [], gaps = [];
  for (const [bi, pt, m0, p0, sig, mum, mup] of it.q) {
    const gap = Math.abs(pt - target);
    if (gap > (D.gap[it.m] ?? 1) + 1e-9) continue;
    const m = gap < 1e-9 ? m0 : condOver(mum, sig, target), p = gap < 1e-9 ? p0 : condOver(mup, sig, target);
    if (Math.max(Math.abs(m - m0), Math.abs(p - p0)) > D.shift + 1e-9) continue;
    const w = D.w[bi]; nm += w * m; np += w * p; den += w; used.push(bi); gaps.push(gap);
  }
  if (!den) return null;
  const m = nm / den, p = np / den;
  return {over: Math.min(m, p), under: Math.min(1 - m, 1 - p), n: used.length, maxGap: Math.max(...gaps),
          exact: gaps.every(g => g < 1e-9), used};
}
function sharpLine(it) {
  const pts = it.q.map(q => q[1]).sort((a, b) => a - b);
  return pts[Math.floor(pts.length / 2)];
}
// n = the number in "n+" ; Yes = n or more (over n - 0.5), No = n - 1 or fewer (under n - 0.5)
function evaluate(it, n, side, cents) {
  const target = n - 0.5, c = consensus(it, target);
  if (!c || c.n < D.minBooks) return {call: 'none', c};
  const raw = side === 'over' ? c.over : c.under;
  const cut = c.exact ? 0 : D.cut * c.maxGap / sigmaFor(it.m, target);
  const p = raw - cut;
  const maxC = Math.floor((p / (1 + D.minEv) - D.fee) * 100 + 1e-9);
  if (cents == null) return {call: 'wait', p, raw, cut, maxC, c};
  const allin = cents / 100 + D.fee, roi = p / allin - 1;
  return {call: roi >= D.minEv ? 'take' : 'skip', p, raw, cut, maxC, c, allin, roi};
}

// ---------- data
async function load(l) {
  if (cache[l]) return cache[l];
  try {
    const r = await fetch(`${l}-check.json?v=${encodeURIComponent(window.CK_GEN || '')}`);
    if (r.ok) cache[l] = await r.json();
  } catch (e) {}
  return cache[l] || null;
}
function group(d) {
  const by = new Map();
  for (const it of d.items) {
    const k = it.k + '|' + it.ev;
    if (!by.has(k)) by.set(k, {key: it.k, pl: it.pl, ev: it.ev, g: it.g, t: it.t, ts: it.ts, items: [], s: norm(it.pl + ' ' + it.g)});
    by.get(k).items.push(it);
  }
  return [...by.values()].sort((a, b) => a.t.localeCompare(b.t) || a.pl.localeCompare(b.pl));
}

async function setLeague(l) {
  lg = l; store.set('ef-check-lg', l);
  document.querySelectorAll('#ck-lg button').forEach(b => b.classList.toggle('on', b.dataset.l === l));
  D = await load(l);
  players = D ? group(D) : [];
  cur = null;
  $('#ck-pick').innerHTML = '';
  $('#ck-foot').innerHTML = D ? `${players.length} ${l.toUpperCase()} players with sharp prices from the last Run.` : '';
  window.INFO = {check: {t: 'Check a price', b: `<p>Find the player, pick the stat, set the line the app shows (60+ means Yes = 60 or more) and its price in cents. You get <b>Take it</b> or <b>Skip it</b>, and the most it's worth paying.</p>
<p>It uses the same sharp fair price as the board. Take it needs a ${D ? (100 * D.minEv).toFixed(0) : 3}%+ expected return after about ${D ? (100 * D.fee).toFixed(1) : '1.5'}¢ a contract in fees. Lines far from the sharp books' number get Skip it, because there's no reliable fair price there.</p>
<p>Touchdown markets aren't priced yet.</p>`}};
  list();
}

function list() {
  const q = norm($('#ck-q').value).trim();
  const box = $('#ck-list');
  if (!D || !players.length) {
    box.innerHTML = `<div class="empty">No ${lg.toUpperCase()} lines to check yet. Tap <a href="index.html">Run ${lg.toUpperCase()}</a> on Home first.</div>`;
    return;
  }
  if (cur && !q) { box.innerHTML = ''; return; }
  if (!q) { box.innerHTML = '<div class="sub" style="margin-top:6px">Type a name, like the one on Robinhood.</div>'; return; }
  const words = q.split(/\s+/);
  const hits = players.filter(p => words.every(w => p.s.split(' ').some(x => x.startsWith(w)))).slice(0, 8);
  box.innerHTML = hits.length ? hits.map((p, i) => `<button class="hit" data-i="${players.indexOf(p)}"><b>${esc(p.pl)}</b>
<div class="meta">${esc(p.g)} · ${esc(when(p.t))} · ${esc(p.items.map(it => D.labels[it.m] || it.m).join(', '))}</div></button>`).join('')
    : `<div class="empty">No ${lg.toUpperCase()} player matches "${esc($('#ck-q').value)}" in the last Run.</div>`;
}

function choose(p) {
  const prefer = ['player_rush_yds', 'player_reception_yds', 'player_receptions', 'player_pass_yds', 'player_points'];
  const it = p.items.slice().sort((a, b) => (prefer.indexOf(a.m) + 99) % 99 - (prefer.indexOf(b.m) + 99) % 99)[0];
  cur = {p, it: it, n: Math.floor(sharpLine(it)) + 1, side: 'over', cents: null};
  $('#ck-q').value = '';
  list(); draw();
  $('#ck-pick').scrollIntoView({behavior: 'smooth', block: 'start'});
}
function setMarket(m) {
  const it = cur.p.items.find(x => x.m === m);
  if (!it) return;
  cur.it = it; cur.n = Math.floor(sharpLine(it)) + 1;
  draw();
}

function verdictHtml(v) {
  const it = cur.it, lab = D.labels[it.m] || it.m, sl = sharpLine(it);
  const pick = cur.side === 'over' ? `${cur.n}+ ${lab}` : `${cur.n - 1} or fewer ${lab}`;
  if (v.call === 'none') {
    return `<div class="verdict skip"><div class="call">✗ Skip it</div><div class="why">There's no sharp price for ${esc(pick)}. ` +
      `The sharp books have ${esc(cur.p.pl)} at ${sl} ${esc(lab.toLowerCase())}, and this is too far from that to price, so there's no edge to trust.</div></div>`;
  }
  const moved = v.c.exact ? '' : ` Moved from the sharp line (${sl}) and trimmed ${(100 * v.cut).toFixed(1)} pts for that.`;
  const books = v.c.used.map(i => D.bl[D.books[i]]).join(', ');
  const nums = `<div class="nums">Fair ${pct(v.p)} from ${v.c.n} sharp book${v.c.n > 1 ? 's' : ''} (${esc(books)}).${moved}</div>`;
  if (v.call === 'wait') {
    return `<div class="verdict wait"><div class="call">${v.maxC >= 1 ? `Worth up to ${v.maxC}¢` : 'Not worth buying at any price'}</div>
<div class="why">Type the price Robinhood shows for ${esc(pick)} to get a call.</div>${nums}</div>`;
  }
  if (v.call === 'take') {
    return `<div class="verdict take"><div class="call">✓ Take it</div>
<div class="why">${cur.cents}¢ is a good price: it's worth up to ${v.maxC}¢. You pay about ${(100 * v.allin).toFixed(1)}¢ with fees for a ${pct(v.p, 0)} chance, ` +
      `an expected return of <b>${sgn(v.roi)}</b>.</div>${nums}</div>`;
  }
  const why = v.roi >= 0
    ? `Only a hair better than fair (${sgn(v.roi)}), not enough to beat the noise in the fair price.`
    : `${cur.cents}¢ costs more than it's worth: about ${(100 * v.allin).toFixed(1)}¢ with fees for a ${pct(v.p, 0)} chance (${sgn(v.roi)} expected).`;
  return `<div class="verdict skip"><div class="call">✗ Skip it</div><div class="why">${why} ` +
    (v.maxC >= 1 ? `Take it at <b>${v.maxC}¢ or less</b>.` : 'Not worth buying at any price.') + `</div>${nums}</div>`;
}

function draw() {
  if (!cur) { $('#ck-pick').innerHTML = ''; return; }
  const p = cur.p, it = cur.it, v = evaluate(it, cur.n, cur.side, cur.cents);
  cur.v = v;
  const lab = D.labels[it.m] || it.m;
  const stale = it.ts && Date.now() - Date.parse(it.ts) > 3 * 3600e3;
  const chips = p.items.map(x => `<button class="chip${x === it ? ' on' : ''}" data-m="${x.m}">${esc(D.labels[x.m] || x.m)}</button>`).join('');
  $('#ck-pick').innerHTML = `<div class="card ck">
<div class="row1"><b>${esc(p.pl)}</b><button class="link" id="ck-x">Change</button></div>
<div class="meta">${esc(p.g)} · ${esc(when(p.t))} · sharp line ${sharpLine(it)}${it.ts ? ` · <span class="${stale ? 'stale' : ''}">prices from ${esc(ago(it.ts))}</span>` : ''}</div>
<div class="chips">${chips}</div>
<div class="grid2">
<label class="ckf">Robinhood line (${esc(lab)})<div class="num"><button data-d="-1" aria-label="Lower">−</button>
<input id="ck-n" type="number" inputmode="numeric" value="${cur.n}" aria-label="Line"><button data-d="1" aria-label="Higher">+</button></div></label>
<label class="ckf">Price it shows<div class="num"><input id="ck-c" type="number" inputmode="numeric" min="1" max="99" placeholder="—" value="${cur.cents ?? ''}" aria-label="Price in cents"><span>¢</span></div></label>
</div>
<div class="sides"><button data-s="over" class="${cur.side === 'over' ? 'on' : ''}">Yes<small>${cur.n} or more</small></button>
<button data-s="under" class="${cur.side === 'under' ? 'on' : ''}">No<small>${cur.n - 1} or fewer</small></button></div>
<div id="ck-v">${verdictHtml(v)}</div>
${stale ? `<div class="meta stale" style="margin-top:8px">These prices are over 3 hours old. Run ${lg.toUpperCase()} on Home for fresh ones before you trust a call.</div>` : ''}
<div class="after"><button class="ghost" id="ck-buy"${v.call === 'none' || cur.cents == null ? ' disabled' : ''}>I bought it</button></div>
</div>`;
}
function redrawVerdict() {   // keep focus in the inputs while typing
  const v = evaluate(cur.it, cur.n, cur.side, cur.cents); cur.v = v;
  $('#ck-v').innerHTML = verdictHtml(v);
  document.querySelectorAll('.ck .sides small')[0].textContent = `${cur.n} or more`;
  document.querySelectorAll('.ck .sides small')[1].textContent = `${cur.n - 1} or fewer`;
  $('#ck-buy').disabled = v.call === 'none' || cur.cents == null;
}

async function bought() {
  const v = cur.v, it = cur.it;
  const stake = Math.max(1, parseInt(store.get('ef-stake', '2'), 10) || 2);
  const n0 = Math.max(1, Math.floor(stake / v.allin));
  const lab = D.labels[it.m] || it.m;
  const pick = cur.side === 'over' ? `${cur.n}+ ${lab}` : `${cur.n - 1} or fewer ${lab}`;
  const pr = EF.confirm({title: 'Save this Robinhood bet', ok: 'Save bet', cancel: 'Cancel', body:
    `<p><b>${esc(cur.p.pl)}</b> ${cur.side === 'over' ? 'Yes' : 'No'} · ${esc(pick)} at ${cur.cents}¢</p>
<label class="fld">Contracts <input id="bl-c" type="number" inputmode="numeric" min="1" step="1" value="${n0}"></label>
<label class="fld">Cost with fees ($) <input id="bl-s" type="number" inputmode="decimal" min="0.01" step="0.01" value="${(n0 * v.allin).toFixed(2)}"></label>
<p>Copy both from Robinhood's order summary ("approximately 3 contracts", "estimated cost $1.96").</p>`});
  if (!(await pr)) return;
  const c = parseInt($('#bl-c').value, 10), s = Math.round(parseFloat($('#bl-s').value) * 100) / 100;
  if (!(c >= 1 && s > 0 && s / c < 1)) { EF.toast('Enter the contracts and the cost (under $1 each).', true); return; }
  const q = x => '"' + String(x).replace(/["\\]/g, '\\$&') + '"';
  const args = `bet-line ${lg} --event ${it.ev} --player ${q(it.k)} --market ${it.m} --side ${cur.side} --point ${cur.n - 0.5}` +
               ` --stake ${s.toFixed(2)} --contracts ${c}`;
  const n = await EF.send(args, 'bet', {summary: `Robinhood · $${s.toFixed(2)} · ${cur.p.pl} ${cur.side === 'over' ? 'Yes' : 'No'} ${pick}`, league: lg});
  if (n) EF.toast('Saved. It shows on Results in a couple of minutes.');
}

// ---------- events
document.addEventListener('click', e => {
  const l = e.target.closest('#ck-lg button'); if (l) { setLeague(l.dataset.l); return; }
  const h = e.target.closest('#ck-list .hit'); if (h) { choose(players[+h.dataset.i]); return; }
  if (e.target.closest('#ck-x')) { cur = null; draw(); $('#ck-q').focus(); list(); return; }
  const m = e.target.closest('.ck .chips [data-m]'); if (m) { setMarket(m.dataset.m); return; }
  const d = e.target.closest('.ck [data-d]'); if (d) { cur.n = Math.max(1, cur.n + +d.dataset.d); $('#ck-n').value = cur.n; redrawVerdict(); return; }
  const s = e.target.closest('.ck .sides [data-s]'); if (s) { cur.side = s.dataset.s; draw(); return; }
  if (e.target.closest('#ck-buy')) { bought(); return; }
});
document.addEventListener('input', e => {
  if (e.target.id === 'ck-q') list();
  if (e.target.id === 'ck-n') { const v = parseInt(e.target.value, 10); if (v >= 1) { cur.n = v; redrawVerdict(); } }
  if (e.target.id === 'ck-c') { const v = parseFloat(e.target.value); cur.cents = v >= 1 && v <= 99 ? v : null; redrawVerdict(); }
});
setLeague(lg === 'nba' ? 'nba' : 'nfl');
})();
</script>"""
