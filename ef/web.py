"""The GitHub side: commands sent as issues, and the Pages site."""
import contextlib
import html
import io
import json
import math
import os
import re
import shlex
import shutil
from statistics import NormalDist
from urllib.parse import quote

from . import auto as automod
from . import board as boardmod
from . import check as checkmod
from . import checkpage
from .bets import update_closes
from . import render
from .board import BOOK_LABELS, market_label
from .fair import stat_sigma
from .util import local, parse_iso, utcnow

E = html.escape

# Commands an issue may run. Anything else is refused.
ALLOWED = {"bet", "bet-line", "result", "actual", "edit", "delete", "restore", "run", "refresh", "ge-import"}


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


def parse_commands(title, body):
    """Every command line in an issue body (the app sends one; a fix-up can carry several).
    Falls back to the title."""
    out = []
    for line in (body or "").replace("\r", "").split("\n"):
        c = parse_issue("", line)
        if c:
            out.append(c)
    if out:
        return out
    c = parse_issue(title, "")
    return [c] if c else []


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
@media (min-width:640px){.kpis{grid-template-columns:repeat(3,1fr)}}
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
    return (render.head(title, web=True).replace("</style>", EXTRA_CSS + HOME_CSS + RESULTS_CSS + checkpage.CSS + "</style>") +
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
(function () {
  const LG = {nba: 'NBA', nfl: 'NFL'};
  const RECENT_MIN = 180;          // warn before re-running within 3 hours
  const GIVE_UP_MIN = 25;
  let st = window.ST;
  const confirmT = {}, watching = {};
  const esc = s => String(s == null ? '' : s).replace(/[&<>"]/g, c => ({'&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;'}[c]));
  const mins = iso => (Date.now() - Date.parse(iso)) / 60000;
  function ago(iso) {
    const m = Math.max(0, Math.round(mins(iso)));
    return m < 1 ? 'just now' : m < 60 ? m + ' min ago' : m < 1440 ? Math.floor(m / 60) + 'h ' + (m % 60) + 'm ago' : Math.floor(m / 1440) + 'd ago';
  }
  function when(iso) {
    const d = new Date(iso), t = d.toLocaleTimeString([], {hour: 'numeric', minute: '2-digit'});
    return d.toDateString() === new Date().toDateString() ? t : d.toLocaleDateString([], {weekday: 'short'}) + ' ' + t;
  }
  const info = lg => (st && st.leagues && st.leagues[lg]) || {};
  function landed(p) { const s = info(p.league); return !!(s.last_run && Date.parse(s.last_run) >= p.ts - 20000); }
  function runs() {
    return EF.pending(p => p.kind === 'run' && (landed(p) || p.failed || Date.now() - p.ts > GIVE_UP_MIN * 60e3))
      .filter(p => p.kind === 'run');
  }
  const runFor = lg => runs().filter(p => p.league === lg).pop();

  function paint() {
    for (const lg of Object.keys(LG)) {
      const card = document.querySelector(`.lgc[data-lg="${lg}"]`);
      if (!card) continue;
      const b = card.querySelector('.runbtn'), rl = b.querySelector('.rl'), rs = b.querySelector('.rs'), rm = card.querySelector('.rm');
      const s = info(lg), p = runFor(lg), left = st && st.credits_left;
      const recent = s.last_run && mins(s.last_run) < RECENT_MIN;
      b.className = 'runbtn'; b.disabled = false;
      if (watching[lg] && !p) {                       // a run just finished (or gave up)
        const w = watching[lg]; delete watching[lg];
        if (landed(w)) EF.toast(`${LG[lg]} board is ready.`);
        else if (!w.failed) EF.toast(`Didn't hear back about the ${LG[lg]} run. Check GitHub's Actions tab.`, true);
      }
      if (p) {
        watching[lg] = p;
        b.classList.add('busy'); b.disabled = true;
        rl.innerHTML = '<span class="spin" aria-hidden="true"></span>Running';
        rs.textContent = `Started ${ago(new Date(p.ts).toISOString())} · new board in about ${lg === 'nfl' ? 4 : 3} min`;
      } else if (confirmT[lg]) {
        b.classList.add('confirm');
        rl.textContent = 'Tap again to run';
        rs.textContent = recent ? `You ran ${LG[lg]} ${ago(s.last_run)}. Up to ${s.credits} more credits.`
          : `Spends up to ${s.credits ?? '?'}${left != null ? ' of your ' + left : ''} credits`;
      } else if (s.games === 0) {
        b.disabled = true;
        rl.textContent = 'Run ' + LG[lg];
        rs.textContent = `No games in the next ${st.hours} hours`;
      } else {
        rl.textContent = 'Run ' + LG[lg];
        rs.textContent = s.games == null ? 'Cost shows after the next check'
          : `${s.games} game${s.games === 1 ? '' : 's'} · up to ${s.credits} credits` + (left != null && s.credits > left ? ` · only ${left} left` : '');
      }
      const last = s.last_run ? `Last run <b class="${recent ? 'recent' : ''}">${esc(ago(s.last_run))}</b>` +
        (s.last_games != null ? ` · ${s.last_games} game${s.last_games === 1 ? '' : 's'}` : '') +
        (s.last_credits != null ? ` · ${s.last_credits} credits` : '') : 'Not run yet';
      const fail = p ? '' : (EF.store.get('ef-run-fail', {})[lg] || '');
      rm.innerHTML = last + (s.games && s.next_tip ? `<br>Next ${lg === 'nfl' ? 'kickoff' : 'tip'} ${esc(when(s.next_tip))}` : '') +
        (fail ? `<br><span class="failed">Last try didn't go through: ${esc(fail)}</span>` : '');
    }
    const c = document.getElementById('cred');
    if (c && st && st.credits_left != null) c.textContent = ` · ${st.credits_left} Odds API credits left`;
  }

  async function refresh() {
    try {
      const r = await fetch('status.json?t=' + Date.now(), {cache: 'no-store'});
      if (r.ok) st = await r.json();
    } catch (e) {}
    for (const p of runs()) if (Date.now() - p.ts > 60e3) await checkIssue(p);
    paint();
  }

  // A run that failed on GitHub (no games, out of credits) says so in its issue.
  async function checkIssue(p) {
    const t = EF.token();
    if (!t || !p.n) return;
    const h = {Authorization: 'Bearer ' + t, Accept: 'application/vnd.github+json'};
    try {
      const r = await fetch(`https://api.github.com/repos/${window.EF_REPO}/issues/${p.n}`, {headers: h});
      if (!r.ok || (await r.json()).state !== 'closed') return;
      const c = await fetch(`https://api.github.com/repos/${window.EF_REPO}/issues/${p.n}/comments?per_page=10`, {headers: h});
      const list = c.ok ? await c.json() : [];
      const body = (list[list.length - 1] || {}).body || '';
      if (!body.startsWith("That didn't go through")) return;
      const out = (body.split('```')[1] || '').trim().split('\n').filter(Boolean);
      const msg = (out[out.length - 1] || 'see the issue on GitHub').slice(0, 180);
      const all = EF.store.get('ef-pending', []);
      all.forEach(x => { if (x.n === p.n) x.failed = msg; });
      EF.store.set('ef-pending', all);
      const f = EF.store.get('ef-run-fail', {}); f[p.league] = msg; EF.store.set('ef-run-fail', f);
      EF.toast(`${LG[p.league]} run didn't go through: ${msg}`, true);
    } catch (e) {}
  }

  document.querySelectorAll('.lgc').forEach(card => {
    const lg = card.dataset.lg, b = card.querySelector('.runbtn');
    b.onclick = async () => {
      if (runFor(lg)) return;
      if (!confirmT[lg]) {                             // first tap arms it
        confirmT[lg] = setTimeout(() => { delete confirmT[lg]; paint(); }, 5000);
        paint(); return;
      }
      clearTimeout(confirmT[lg]); delete confirmT[lg];
      b.disabled = true;
      const n = await EF.send('run ' + lg, 'run', {league: lg, summary: 'Run ' + LG[lg]});
      if (n) {
        const f = EF.store.get('ef-run-fail', {}); delete f[lg]; EF.store.set('ef-run-fail', f);
        EF.toast(`${LG[lg]} run started. The new board lands in a few minutes.`);
      }
      paint();
    };
  });

  paint();
  refresh();
  setInterval(() => { if (runs().length) refresh(); else paint(); }, 15000);
  document.addEventListener('visibilitychange', () => { if (!document.hidden) refresh(); });
  window.addEventListener('ef-auth', paint);
})();
</script>"""

HOME_CSS = """
.runs{display:grid;grid-template-columns:1fr;gap:12px;margin-top:14px}
@media (min-width:640px){.runs{grid-template-columns:1fr 1fr}}
.lgc{background:var(--panel);border:1px solid var(--line);border-radius:16px;padding:14px}
.lgh{display:flex;align-items:baseline;justify-content:space-between;gap:10px;margin-bottom:10px}
.lgh h2{margin:0;font-size:20px}
.lgh a{font-size:14px;font-weight:650;text-decoration:none;white-space:nowrap}
.lgh a.none{color:var(--faint);pointer-events:none}
button.runbtn{width:100%;min-height:78px;flex-direction:column;gap:4px;border-radius:14px;padding:12px 14px}
.runbtn .rl{font-size:21px;font-weight:800;line-height:1.15;display:inline-flex;align-items:center}
.runbtn .rs{font-size:13.5px;font-weight:600;opacity:.92;line-height:1.3}
button.runbtn.confirm{background:var(--warn-bg);border-color:var(--warn);color:var(--warn)}
button.runbtn.busy{background:var(--chip);border-color:var(--line);color:var(--ink);opacity:1;cursor:default}
button.runbtn:disabled:not(.busy){opacity:.45;cursor:default}
.rm{font-size:13.5px;color:var(--dim);margin-top:10px;line-height:1.55}
.rm .recent{color:var(--warn)}
.rm .failed{color:var(--bad)}
.spin{width:15px;height:15px;border:2.5px solid currentColor;border-right-color:transparent;border-radius:50%;
animation:ef-spin .8s linear infinite;margin-right:8px;flex:none}
@keyframes ef-spin{to{transform:rotate(360deg)}}
@media (prefers-reduced-motion:reduce){.spin{animation:none}}
a.tile.res{margin-top:12px}
"""


def build_site(con, cfg, out_dir, now=None, status_line=None):
    """Write index.html, nba.html, nfl.html, bets.html and bets-data.json into out_dir."""
    now = now or utcnow()
    repo = cfg["github"]["repo"]
    web = {"repo": repo}
    os.makedirs(out_dir, exist_ok=True)
    copy_static(out_dir)
    update_closes(con, cfg, now)
    hours = cfg.get("manual", {}).get("hours_ahead", 16)
    status = {"gen": iso_now(now), "hours": hours, "credits_left": automod.credits_left(con),
              "leagues": {lg: automod.run_estimate(con, cfg, lg) for lg in ("nba", "nfl")}}
    tiles = []
    for lg in ("nba", "nfl"):
        try:
            b = boardmod.build(con, cfg, lg, now=now)
        except SystemExit:
            b = None
        if b is None:
            page = _page("Edge Finder " + lg.upper(), lg,
                         '<h1>Edge Finder · %s</h1><div class="empty">No %s lines pulled yet. Tap <a href="index.html">'
                         'Run %s</a> on Home when you are ready to bet.</div>' % (lg.upper(), lg.upper(), lg.upper()), web)
            tiles.append((lg, None, 0))
        else:
            boardmod.save_codes(con, b)
            page = render.render(b, cfg, "", web=web)
            fl = sum(1 for s in ("pickem", "fliff", "kalshi") for x in b[s] if x["flagged"])
            tiles.append((lg, b["pull"]["ts"], fl))
        with open(os.path.join(out_dir, "%s.html" % lg), "w") as f:
            f.write(page)

    # Check page: the sharp prices for every player, fetched by the page when it opens.
    for lg in ("nba", "nfl"):
        with open(os.path.join(out_dir, "%s-check.json" % lg), "w") as f:
            json.dump(checkmod.payload(con, cfg, lg, now), f, separators=(",", ":"))
    with open(os.path.join(out_dir, "check.html"), "w") as f:
        f.write(_page("Check a price", "check", checkpage.CONTENT, web,
                      "<script>window.CK_GEN = %s;</script>%s" % (json.dumps(iso_now(now)), checkpage.JS)))

    data = results_payload(con, cfg, repo, now)
    with open(os.path.join(out_dir, "bets.html"), "w") as f:
        f.write(bets_page(data, web))
    with open(os.path.join(out_dir, "bets-data.json"), "w") as f:
        json.dump(data, f, separators=(",", ":"))

    settled = [b for b in data["bets"] if b["res"]]
    net = sum((b["pay"] or 0) - (b["stake"] or 0) for b in settled)
    open_n = sum(1 for b in data["bets"] if not b["res"])
    res_txt = ("%s%.2f net · %d settled" % ("+" if net >= 0 else "−", abs(net), len(settled))) if settled else "No settled bets yet"
    credits = status["credits_left"]
    cards = ""
    for lg, pulled, fl in tiles:
        link = ('<a href="%s.html">%d flagged · board ›</a>' % (lg, fl)) if pulled else '<a class="none">No board yet</a>'
        cards += ('<section class="lgc" data-lg="%s"><div class="lgh"><h2>%s</h2>%s</div>'
                  '<button class="runbtn" type="button"><span class="rl">Run %s</span><span class="rs"></span></button>'
                  '<div class="rm"></div></section>' % (lg, lg.upper(), link, lg.upper()))
    content = """<h1>Edge Finder</h1>
<div class="sub">Updated <span data-ago="%(upd)s"></span><span id="cred">%(cred)s</span></div>
<div class="runs">%(cards)s</div>
<a class="tile res" href="bets.html"><div class="k">Results</div><div class="v">%(open)d open</div><div class="s">%(res)s</div></a>
<details class="how"><summary>How it works</summary><ol>
<li>Lines are only pulled when you tap <b>Run</b>, so credits go only to days you bet. A run prices every game in the next %(hours)d hours against the sharp books. Tap once to see the cost, again to run.</li>
<li>Open a board, tap the picks you actually play, then <b>Save bet</b>. The first time, Settings walks you through a one-time key.</li>
<li>For games you bet, it saves the closing line just before the start (about 1 credit a game) and grades results from ESPN box scores after.</li>
<li><a href="bets.html">Results</a> shows your record, profit, closing line value, how close your misses were, and what's working by app, stat and entry.</li>
<li>Run NFL also runs Gridiron Edge first and shows its read on each pick.</li>
<li><a href="check.html">Check</a> prices a line from Robinhood or any app without a feed: set the line and its price, get Take it or Skip it.</li>
<li>Add to your Home Screen: Share → <b>Add to Home Screen</b>. It opens full screen like an app.</li>
</ol></details>
<div class="foot">%(status)s</div>""" % {
        "upd": E(iso_now(now)), "cards": cards, "hours": hours, "open": open_n, "res": E(res_txt),
        "cred": (" · %s Odds API credits left" % credits) if credits is not None else "",
        "status": E(status_line or ""),
    }
    js = "<script>window.ST = %s;</script>%s" % (json.dumps(status, separators=(",", ":")), HOME_JS)
    with open(os.path.join(out_dir, "index.html"), "w") as f:
        f.write(_page("Edge Finder", "index", content, web, js))
    with open(os.path.join(out_dir, "status.json"), "w") as f:
        json.dump(status, f, separators=(",", ":"))
    with open(os.path.join(out_dir, ".nojekyll"), "w") as f:
        f.write("")
    return out_dir


def iso_now(now):
    return now.strftime("%Y-%m-%dT%H:%M:%SZ")


# ------------------------------------------------------------------ results page

_ND = NormalDist()


def closeness(leg):
    """How near a leg came, from your side of the line.

    mg   margin past the line (positive = on your side): act - pt for an over, pt - act for an under
    sd   the stat's standard deviation at that line (same model the pricing uses)
    ez   the margin the fair price expected, in SDs (a 55% leg is expected to land about 0.13 SD on your side)
    need the number you needed: an over needs `need` or more, an under `need` or fewer
    hook missed by one (one assist, one catch, one yard)
    """
    if leg["point"] is None or not leg["market"]:
        return {}
    pt = float(leg["point"])
    out = {"sd": round(stat_sigma(leg["market"], pt), 3)}
    p = leg["fair_p"]
    if p is not None and 0.001 < p < 0.999:
        out["ez"] = round(_ND.inv_cdf(p), 3)
    out["need"] = math.floor(pt) + 1 if leg["side"] == "over" else math.ceil(pt) - 1
    act = leg["actual"]
    if act is not None and leg["leg_result"] in ("hit", "miss", "push"):
        if leg["side"] == "over":
            mg, short = act - pt, out["need"] - act
        else:
            mg, short = pt - act, act - out["need"]
        out["mg"] = round(mg, 2)
        out["hook"] = leg["leg_result"] == "miss" and 0 < short <= 1
    return out


def payout_if_hit(cfg, b, legs):
    """What a lost bet would have paid had its one miss hit. None when that
    isn't the situation (or can't be worked out)."""
    res = [l["leg_result"] for l in legs]
    if res.count("miss") != 1 or any(r not in ("hit", "miss") for r in res):
        return None
    if b["book"] in cfg.pickem_books:
        e = cfg.entries(b["book"]).get(b["entry_type"] or "")
        return None if not e else round((b["stake"] or 0) * float(e["pays"].get(str(len(legs)), 0)), 2)
    if b["book"] in ("kalshi", "robinhood"):
        return round(b["contracts"] or 0, 2)
    return round((b["stake"] or 0) * (legs[0]["price"] or 0), 2)


def results_payload(con, cfg, repo, now):
    bets, deleted = [], []
    for b in con.execute("SELECT * FROM bets ORDER BY placed_at, id").fetchall():
        legs = con.execute("SELECT * FROM bet_legs WHERE bet_id=? ORDER BY leg", (b["id"],)).fetchall()
        if b["book"] in cfg.pickem_books:
            entry = (cfg.entries(b["book"]).get(b["entry_type"] or "") or {}).get("label") or b["entry_type"]
        elif b["book"] == "kalshi":
            entry = "Kalshi · %s shares" % ("%g" % round(b["contracts"] or 0, 2))
        elif b["book"] == "robinhood":
            entry = "Robinhood · %s contracts" % ("%g" % round(b["contracts"] or 0, 2))
        else:
            entry = "%s · straight" % BOOK_LABELS.get(b["book"], b["book"])
        starts = [l["commence_time"] for l in legs if l["commence_time"]]
        could = None
        if b["result"] is not None and (b["payout"] or 0) < (b["stake"] or 0):
            could = payout_if_hit(cfg, b, legs)
        (deleted if b["deleted_at"] else bets).append({
            "id": b["id"], "placed": b["placed_at"], "lg": b["league"], "book": b["book"],
            "bl": BOOK_LABELS.get(b["book"], b["book"]), "entry": entry, "et": b["entry_type"],
            "stake": round(b["stake"] or 0, 2), "res": b["result"],
            "pay": None if b["payout"] is None else round(b["payout"], 2),
            "auto": b["graded_by"] == "auto", "fixed": b["graded_by"] == "fixed", "note": b["notes"], "start": min(starts) if starts else None,
            "could": could, "ct": b["contracts"],
            "legs": [dict({"pl": l["player"], "m": market_label(l["market"]), "side": l["side"], "pt": l["point"],
                           "fair": l["fair_p"], "close": l["close_fair_p"], "fl": l["flagged"], "edge": l["edge"],
                           "price": l["price"], "n": l["leg"], "t": l["commence_time"],
                           "act": l["actual"], "lr": l["leg_result"], "gp": l["ge_p"], "lg": b["league"]},
                          **closeness(l)) for l in legs],
        })
    g = cfg["gridiron_edge"]
    return {"repo": repo, "gen": iso_now(now), "bets": bets, "deleted": deleted,
            "geAgree": g["agree_at"], "geConflict": g["conflict_at"]}


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
.badge.saving,.badge.hook{background:var(--warn-bg);color:var(--warn)}
.cardfoot{display:flex;justify-content:flex-end;gap:14px;margin-top:6px}
.fixrow{display:flex;align-items:center;gap:10px;margin-top:3px}
button.link.fix{font-size:12.5px;padding:4px 0;min-height:30px;color:var(--faint)}
button.link.fix.need{color:var(--accent)}
.fx-prev{font-weight:650;color:var(--ink)}
.fld.chk{justify-content:flex-start;gap:10px}
.fld.chk input{width:22px;min-height:22px;height:22px}
.fld{display:flex;justify-content:space-between;align-items:center;gap:12px;margin:8px 0;font-weight:600;color:var(--ink)}
.fld input{width:110px;min-height:44px;font:inherit;font-size:16px;font-weight:700;text-align:center;border:1px solid var(--line);
border-radius:10px;background:var(--bg);color:var(--ink)}
button.link.del{color:var(--faint);font-size:13px;min-height:36px;padding:6px 2px}
details.how .drow{display:flex;justify-content:space-between;align-items:center;gap:12px;padding:10px 0;border-top:1px solid var(--line)}
details.how .drow:first-of-type{border-top:0}
details.how .drow .meta{font-size:12.5px}
details.how .drow button{flex:none;min-height:38px}
.cl{display:flex;align-items:center;gap:9px;margin-top:5px;font-size:12.5px;color:var(--dim)}
.cl-tr{position:relative;flex:0 0 88px;height:8px;background:var(--chip);border-radius:4px}
.cl-tr i{position:absolute;display:block}
.cl-mid{left:50%;top:-3px;bottom:-3px;width:2px;margin-left:-1px;background:var(--base);border-radius:1px}
.cl-f{top:0;bottom:0}.cl-f.pos{background:var(--s-pos);border-radius:0 4px 4px 0}.cl-f.neg{background:var(--s-neg);border-radius:4px 0 0 4px}
.cl-d{top:50%;width:12px;height:12px;margin:-6px 0 0 -6px;border-radius:50%;border:2px solid var(--panel)}
.cl-d.pos{background:var(--s-pos)}.cl-d.neg{background:var(--s-neg)}.cl-d.push{background:var(--faint)}
.chart.hist svg{height:214px}
.takeaway{font-size:13.5px;color:var(--dim);margin:8px 2px 0}
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

// ---------- closeness: how far each leg finished from the line, in SDs of that stat
const NEAR = 0.25;                       // a miss within a quarter SD counts as a near miss
function Phi(x) {
  if (x === Infinity) return 1;
  if (x === -Infinity) return 0;
  const t = 1 / (1 + 0.2316419 * Math.abs(x)), d = 0.3989423 * Math.exp(-x * x / 2);
  const p = d * t * (0.3193815 + t * (-0.3565638 + t * (1.781478 + t * (-1.821256 + t * 1.330274))));
  return x > 0 ? 1 - p : p;
}
const zOf = l => l.mg / l.sd;
const num = x => (Math.round(x * 10) / 10).toString();
const legName = l => `${l.pl} ${l.side === 'over' ? 'O' : 'U'} ${l.pt} ${l.m}`;
function closeText(l) {
  const need = l.side === 'over' ? `${num(l.need)}+` : `${num(l.need)} or fewer`;
  let note;
  if (l.lr === 'push') note = 'push';
  else if (l.lr === 'hit') { const spare = l.side === 'over' ? l.act - l.need : l.need - l.act; note = spare > 0 ? `${num(spare)} to spare` : 'exactly enough'; }
  else if (l.hook) note = '🪝 missed by one';
  else note = l.side === 'over' ? `short by ${num(l.need - l.act)}` : `${num(l.act - l.need)} too many`;
  return `got ${num(l.act)} · needed ${need} · ${note}`;
}
function legClose(l) {
  if (l.mg == null || !l.sd) return l.act != null ? `<div class="cl">got ${esc(num(l.act))}</div>` : '';
  const z = Math.max(-2, Math.min(2, zOf(l))), pos = 50 + 25 * z;
  const cls = l.lr === 'hit' ? 'pos' : l.lr === 'miss' ? 'neg' : 'push';
  const fill = cls === 'push' ? '' : z >= 0 ? `<i class="cl-f pos" style="left:50%;width:${(pos - 50).toFixed(1)}%"></i>`
    : `<i class="cl-f neg" style="left:${pos.toFixed(1)}%;width:${(50 - pos).toFixed(1)}%"></i>`;
  return `<div class="cl"><div class="cl-tr" aria-hidden="true"><i class="cl-mid"></i>${fill}<i class="cl-d ${cls}" style="left:${pos.toFixed(1)}%"></i></div><span>${esc(closeText(l))}</span></div>`;
}
function closeCall(b) {                  // a lost bet whose one miss was a hook or a near miss
  if (b.could == null) return '';
  const m = b.legs.find(l => l.lr === 'miss');
  if (!m || m.mg == null) return '';
  if (m.hook) return `<span class="badge hook">🪝 one hook from $${b.could.toFixed(2)}</span>`;
  if (zOf(m) >= -NEAR) return `<span class="badge hook">one near miss from $${b.could.toFixed(2)}</span>`;
  return '';
}

// Histogram of where legs finished, with the spread the prices expected drawn over it.
function histChart(el, legs) {
  const svg = el.querySelector('svg'), tip = el.querySelector('.tip');
  const W = el.clientWidth - 24, H = 214, L = 28, R = 8, T = 40, B = 24;
  const lo = -2, w = 0.25, n = 16;
  const bins = Array.from({length: n}, (_, i) => ({a: lo + i * w, b: lo + (i + 1) * w, legs: [], exp: 0}));
  for (const l of legs) {
    bins[Math.max(0, Math.min(n - 1, Math.floor((zOf(l) - lo) / w + 1e-9)))].legs.push(l);
    if (l.ez == null) continue;
    bins.forEach((x, i) => { x.exp += Phi((i === n - 1 ? Infinity : x.b) - l.ez) - Phi((i === 0 ? -Infinity : x.a) - l.ez); });
  }
  const top = Math.max(2, Math.ceil(Math.max(...bins.map(x => Math.max(x.legs.length, x.exp)))));
  const ticks = niceTicks(0, top), y1 = ticks[ticks.length - 1];
  const X = z => L + (z - lo) / (n * w) * (W - L - R);
  const Y = v => T + (H - T - B) * (1 - v / y1);
  const bw = X(lo + w) - X(lo);
  let g = ticks.map(t => `<line x1="${L}" x2="${W - R}" y1="${Y(t)}" y2="${Y(t)}" stroke="var(${t === 0 ? '--base' : '--grid'})" stroke-width="1"/>
<text x="${L - 6}" y="${Y(t) + 4}" text-anchor="end" font-size="11" fill="var(--faint)">${t}</text>`).join('');
  g += bins.map((x, i) => {
    const c = x.legs.length, hooks = x.legs.filter(l => l.hook).length;
    const bar = c ? `<rect class="bar" data-i="${i}" x="${(X(x.a) + 1).toFixed(1)}" y="${Y(c).toFixed(1)}" width="${Math.max(1, bw - 2).toFixed(1)}" height="${(Y(0) - Y(c)).toFixed(1)}" rx="2" fill="var(${x.a < 0 ? '--s-neg' : '--s-pos'})"/>` : '';
    return bar + (hooks ? `<text x="${(X(x.a) + bw / 2).toFixed(1)}" y="${(Y(c) - 5).toFixed(1)}" text-anchor="middle" font-size="11.5" font-weight="650" fill="var(--ink)">🪝${hooks > 1 ? hooks : ''}</text>` : '');
  }).join('');
  if (legs.some(l => l.ez != null)) {
    const d = bins.map((x, i) => `${i ? 'L' : 'M'}${X(x.a).toFixed(1)},${Y(x.exp).toFixed(1)}L${X(x.b).toFixed(1)},${Y(x.exp).toFixed(1)}`).join('');
    g += `<path d="${d}" fill="none" stroke="var(--faint)" stroke-width="2" stroke-dasharray="4 3" stroke-linejoin="round"/>`;
  }
  g += `<line x1="${X(0)}" x2="${X(0)}" y1="4" y2="${H - B}" stroke="var(--ink)" stroke-width="1.5" opacity=".55"/>
<text x="${X(0) - 7}" y="13" text-anchor="end" font-size="11.5" font-weight="650" fill="var(--s-neg)">← missed</text>
<text x="${X(0) + 7}" y="13" font-size="11.5" font-weight="650" fill="var(--s-pos)">hit →</text>
${[-2, -1, 0, 1, 2].map(z => `<text x="${X(z) + (z === -2 ? 2 : z === 2 ? -2 : 0)}" y="${H - 6}" text-anchor="${z === -2 ? 'start' : z === 2 ? 'end' : 'middle'}" font-size="11" fill="var(--faint)">${z === 0 ? 'line' : (z > 0 ? '+' : '−') + Math.abs(z) + (Math.abs(z) === 2 ? ' SD' : '')}</text>`).join('')}
<rect x="${L}" y="0" width="${W - L - R}" height="${H}" fill="transparent" class="hit"/>`;
  svg.setAttribute('viewBox', `0 0 ${W} ${H}`);
  svg.innerHTML = g;
  const hit = svg.querySelector('.hit');
  const show = ev => {
    const r = svg.getBoundingClientRect(), x = (ev.clientX - r.left) * W / r.width;
    const i = Math.max(0, Math.min(n - 1, Math.floor((x - L) / bw)));
    const bn = bins[i], c = bn.legs.length, hooks = bn.legs.filter(l => l.hook).length;
    svg.querySelectorAll('.bar').forEach(el2 => el2.setAttribute('opacity', +el2.dataset.i === i ? 1 : 0.4));
    const span = bn.a < 0 ? (i === 0 ? 'Missed by 1.75+ SD' : `Missed by ${-bn.b}–${-bn.a} SD`)
      : (i === n - 1 ? 'Cleared by 1.75+ SD' : `Cleared by ${bn.a}–${bn.b} SD`);
    tip.innerHTML = `<b>${c} leg${c === 1 ? '' : 's'}</b> · ${span}` + (hooks ? `<br>🪝 ${hooks} missed by one` : '') +
      `<br>prices expected ${bn.exp.toFixed(1)}` + bn.legs.slice(0, 3).map(l => `<br>${esc(legName(l))}: ${esc(num(l.act))}`).join('') +
      (c > 3 ? `<br>+${c - 3} more` : '');
    tip.style.display = 'block';
    const px = (X(bn.a) + bw / 2) * r.width / W, maxX = el.clientWidth - tip.offsetWidth - 6;
    tip.style.left = Math.max(6, Math.min(px + 12 - tip.offsetWidth / 2, maxX)) + 'px'; tip.style.top = (r.top - el.getBoundingClientRect().top + 22) + 'px';
  };
  const hide = () => { tip.style.display = 'none'; svg.querySelectorAll('.bar').forEach(el2 => el2.setAttribute('opacity', 1)); };
  hit.addEventListener('pointermove', show); hit.addEventListener('pointerdown', show); hit.addEventListener('pointerleave', hide);
}

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
  const all = D.bets.concat(D.deleted || []);
  const recorded = new Set(all.map(b => b.note).filter(Boolean));
  const settledIds = new Set(D.bets.filter(b => b.res != null).map(b => b.id));
  const liveIds = new Set(D.bets.map(b => b.id));
  const pend = EF.pending(p => p.kind === 'bet' ? recorded.has('issue #' + p.n) : p.kind === 'result' ? settledIds.has(p.bet)
    : p.kind === 'delete' ? !liveIds.has(p.bet) : p.kind === 'restore' ? liveIds.has(p.bet)
    : p.kind === 'edit' ? D.bets.some(b => b.id === p.bet && Math.abs(b.stake - p.stake) < 0.005) || Date.now() - p.ts > 15 * 60e3
    : p.kind === 'fix' ? fixLanded(all, p) || Date.now() - p.ts > 15 * 60e3 : false);
  const deleting = new Set(pend.filter(p => p.kind === 'delete').map(p => p.bet));
  editing = new Set(pend.filter(p => p.kind === 'edit').map(p => p.bet));
  fixing = new Map(pend.filter(p => p.kind === 'fix').map(p => [p.bet + ':' + p.leg, p.value]));
  const restoring = new Set(pend.filter(p => p.kind === 'restore').map(p => p.bet));
  const bets = D.bets.filter(b => !deleting.has(b.id)).filter(inScope);
  const settled = bets.filter(b => b.res != null).sort((a, b) => (a.start || a.placed).localeCompare(b.start || b.placed));
  const staked = settled.reduce((s, b) => s + b.stake, 0), net = settled.reduce((s, b) => s + (b.pay || 0) - b.stake, 0);
  const rec = ['W', 'L', 'P'].map(o => settled.filter(b => outcome(b) === o).length);
  const clvLegs = bets.flatMap(b => b.legs).filter(l => l.close != null && l.fair != null);
  const clv = clvLegs.length ? clvLegs.reduce((s, l) => s + l.close - l.fair, 0) / clvLegs.length : null;
  const graded = settled.flatMap(b => b.legs.map(l => Object.assign({book: b.bl}, l))).filter(l => l.lr === 'hit' || l.lr === 'miss');
  const landed = graded.filter(l => l.mg != null && l.sd);
  const hooks = landed.filter(l => l.hook).length;
  const hookBets = settled.filter(b => closeCall(b).includes('🪝'));
  const avgZ = landed.length ? landed.reduce((s, l) => s + zOf(l), 0) / landed.length : null;
  const withE = landed.filter(l => l.ez != null);
  const expZ = withE.length ? withE.reduce((s, l) => s + l.ez, 0) / withE.length : null;
  const gotZ = withE.length ? withE.reduce((s, l) => s + zOf(l), 0) / withE.length : null;
  let h = `<div class="kpis">
<div class="kpi"><div class="k">Record</div><div class="v">${settled.length ? rec.join('-') : '—'}</div><div class="s">won-lost-push · ${settled.length} settled</div></div>
<div class="kpi"><div class="k">Profit</div><div class="v ${net >= 0 ? 'pos' : 'neg'}">${settled.length ? money(net) : '—'}</div><div class="s">${settled.length ? sgn(100 * net / staked) + '% on $' + staked.toFixed(0) + ' staked' : 'nothing settled yet'}</div></div>
<div class="kpi"><div class="k">Closing line value</div><div class="v ${clv != null && clv >= 0 ? 'pos' : clv != null ? 'neg' : ''}">${clv == null ? '—' : sgn(100 * clv)}</div><div class="s">${clv == null ? 'fills in at tip-off' : 'pts per leg · ' + clvLegs.length + ' legs'}</div></div>
<div class="kpi"><div class="k">Legs hit</div><div class="v">${graded.length ? pct(graded.filter(l => l.lr === 'hit').length / graded.length) : '—'}</div><div class="s">${graded.length ? 'vs ' + pct(graded.reduce((s, l) => s + l.fair, 0) / graded.length) + ' expected · ' + graded.length + ' legs' : 'graded after each game'}</div></div>
<div class="kpi"><div class="k">Hooks 🪝</div><div class="v">${landed.length ? hooks : '—'}</div><div class="s">${!landed.length ? 'legs missed by one' : hookBets.length ? hookBets.length + ' bet' + (hookBets.length === 1 ? '' : 's') + ' one hook from cashing' : 'legs missed by one'}</div></div>
<div class="kpi"><div class="k">Avg finish vs line</div><div class="v ${avgZ == null ? '' : avgZ >= 0 ? 'pos' : 'neg'}">${avgZ == null ? '—' : sgn(avgZ, 2) + ' SD'}</div><div class="s">${expZ == null ? 'how close legs land' : 'prices expected ' + sgn(expZ, 2)}</div></div></div>`;
  if (settled.length >= 2) h += chartBox('c-pl', 'Profit over time', 'Running total after each settled bet');
  else h += `<div class="empty" style="margin-top:10px">Your profit chart starts after two settled bets. Results are graded from ESPN box scores after each game.</div>`;
  if (clvLegs.length >= 2) h += chartBox('c-clv', 'Closing line value', `Average over your last ${Math.min(20, clvLegs.length)} legs, in percentage points. Above zero means the market moved your way`);
  if (landed.length >= 3) {
    h += `<h2>How close your legs landed <small>${landed.length} graded legs</small></h2>` +
      `<div class="chart viz hist" id="c-hist"><div class="st">How far each leg finished from its line, in standard deviations of that stat (1 SD is about ${esc(sdHint(landed))}). Dashed: where the prices you took expected them to land.</div><svg role="img" aria-label="How close your legs landed"></svg><div class="tip"></div></div>`;
    if (gotZ != null) {
      const diff = gotZ - expZ;
      h += `<div class="takeaway">Your legs finished <b class="${diff >= 0 ? 'pos' : 'neg'}">${Math.abs(diff).toFixed(2)} SD ${diff >= 0 ? 'further on your side' : 'short of'}</b> ${diff >= 0 ? 'than' : 'where'} the prices expected${hooks ? `, with ${hooks} hook${hooks === 1 ? '' : 's'}` : ''}.` +
        `${withE.length < 50 ? ' Still a small sample: closeness steadies faster than win-loss, but give it 50+ legs.' : ''}</div>`;
    }
  }
  h += barGroup('What\'s working: by app', byBets(settled, b => b.bl), v => sgn(100 * v) + '%', 'return on money staked');
  h += barGroup('By entry type', byBets(settled, b => b.book === 'kalshi' ? 'Kalshi' : b.et === 'straight' ? b.bl + ' straight' : b.entry), v => sgn(100 * v) + '%');
  h += barGroup('Flagged picks vs your own', byBets(settled, b => b.legs.every(l => l.fl) ? 'Only flagged picks' : 'Includes your own picks'), v => sgn(100 * v) + '%', 'did sticking to the board pay?');
  h += barGroup('By stat', byLegs(graded, l => l.m), v => sgn(100 * v) + ' pts', 'hit rate minus what the market expected');
  const nflLegs = graded.filter(l => l.lg === 'nfl');
  if (nflLegs.length) h += barGroup('Gridiron Edge read', byLegs(nflLegs, l => 'Gridiron Edge ' + geTag(l.gp)), v => sgn(100 * v) + ' pts', 'NFL legs: did its read help?');
  if (settled.length && settled.length < 100) h += `<div class="sub" style="margin-top:10px">Under 100 bets, records swing on luck. Closing line value is the earlier signal.</div>`;

  // lists
  const pendBets = pend.filter(p => p.kind === 'bet');
  if (pendBets.length) h += '<h2>Recording</h2><div class="grid">' + pendBets.map(p => `<div class="card bet"><div class="row1"><b>${esc(p.summary || p.args)}</b><span class="badge saving">saving</span></div>
<div class="meta">Saved ${esc(when(new Date(p.ts).toISOString()))}. It shows here once the next run records it, usually within 2 minutes.</div></div>`).join('') + '</div>';
  const pendRes = new Map(pend.filter(p => p.kind === 'result').map(p => [p.bet, p.outcome]));
  const open = bets.filter(b => b.res == null).sort((a, b) => (a.start || '').localeCompare(b.start || ''));
  h += `<h2>Open <small>graded automatically after each game</small></h2>`;
  h += open.length ? '<div class="grid">' + open.map(b => betCard(b, pendRes.get(b.id))).join('') + '</div>' : '<div class="empty">No open bets.</div>';
  const done = bets.filter(b => b.res != null).sort((a, b) => (b.start || b.placed).localeCompare(a.start || a.placed)).slice(0, 60);
  h += '<h2>Settled</h2>' + (done.length ? '<div class="grid">' + done.map(b => betCard(b)).join('') + '</div>' : '<div class="empty">Nothing settled yet.</div>');
  const gone = D.bets.filter(b => deleting.has(b.id)).concat(D.deleted || []);
  if (gone.length) h += `<details class="how"><summary>Deleted bets (${gone.length})</summary>` + gone.map(b => {
    const state = deleting.has(b.id) ? '<span class="badge saving">deleting</span>' : restoring.has(b.id) ? '<span class="badge saving">restoring</span>'
      : `<button class="ghost" data-restore="${b.id}">Restore</button>`;
    return `<div class="drow"><div><b>#${b.id} ${esc(b.entry)}</b> · $${b.stake.toFixed(2)}<div class="meta">${esc(legLine(b))}</div></div>${state}</div>`;
  }).join('') + '<div class="meta" style="margin-top:6px">Deleted bets are left out of your record, charts and stats.</div></details>';
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
  if ($('#c-hist')) histChart($('#c-hist'), landed);
}

const legLine = b => b.legs.map(l => `${l.pl} ${l.side === 'over' ? 'O' : 'U'} ${l.pt} ${l.m}`).join(', ');

// "1 SD is about 2 assists or 6 points" - the two stats you bet most, so the unit means something.
function sdHint(legs) {
  const m = new Map();
  for (const l of legs) { const e = m.get(l.m) || {n: 0, sd: 0}; e.n++; e.sd += l.sd; m.set(l.m, e); }
  return [...m].sort((a, b) => b[1].n - a[1].n).slice(0, 2)
    .map(([k, e]) => `${num(e.sd / e.n)} ${k.toLowerCase()}`).join(' or ');
}

function betCard(b, savingResult) {
  const o = outcome(b);
  const head = `<div class="row1"><b>#${b.id} ${esc(b.entry)}</b><span class="big">$${b.stake.toFixed(2)}</span></div>
<div class="meta">${esc(b.lg.toUpperCase())} · placed ${esc(when(b.placed))}${b.start ? ' · starts ' + esc(when(b.start)) : ''}</div>`;
  const legs = '<ul class="legs2 viz">' + b.legs.map(l => {
    const mk = l.lr === 'hit' ? '<span class="mark hit">✓</span>' : l.lr === 'miss' ? '<span class="mark miss">✗</span>' : l.lr && l.lr !== 'review' ? `<span class="mark other">${esc(l.lr)}</span>` : '';
    const clv = l.close != null ? ` · close ${pct(l.close, 1)} <b class="${l.close >= l.fair ? 'pos' : 'neg'}">${sgn(100 * (l.close - l.fair))}</b>` : '';
    return `<li>${mk}<b>${esc(l.pl)}</b> ${l.side === 'over' ? 'Over' : 'Under'} ${l.pt} ${esc(l.m)}<div class="meta">fair ${pct(l.fair, 1)}${clv}</div>${legClose(l)}${fixLink(b, l)}</li>`;
  }).join('') + '</ul>';
  if (b.res != null) {
    const cls = o === 'W' ? 'win' : o === 'L' ? 'loss' : '';
    const g = b.legs.filter(l => l.lr === 'hit' || l.lr === 'miss'), hitN = g.filter(l => l.lr === 'hit').length;
    const tally = b.legs.length > 1 && g.length ? ` · ${hitN} of ${b.legs.length} hit` : '';
    return `<div class="card bet">${head}<div class="meta"><span class="badge ${cls}">${esc(b.res)} · $${(b.pay || 0).toFixed(2)}</span>${tally}${b.auto ? ' · graded from the box score' : b.fixed ? ' · settled from your fix' : ''}</div>${closeCall(b) ? `<div class="meta" style="margin-top:6px">${closeCall(b)}</div>` : ''}${legs}${delBtn(b)}</div>`;
  }
  const stale = b.start && Date.now() - Date.parse(b.start) > 5 * 3600e3;
  const btns = savingResult ? `<div class="meta" style="margin-top:10px"><span class="badge saving">saving ${esc(savingResult)}</span></div>` :
    `<div class="res">${['win', 'loss', 'push'].map(x => `<button class="${x === 'win' ? 'win' : 'ghost'}" data-res="${x}" data-bet="${b.id}">${x[0].toUpperCase() + x.slice(1)}</button>`).join('')}</div>`;
  return `<div class="card bet">${head}${stale ? '<div class="meta"><span class="badge saving">needs your result</span> couldn\'t be graded automatically</div>' : ''}${legs}${btns}${delBtn(b)}</div>`;
}
const delBtn = b => editing.has(b.id) ? '<div class="cardfoot"><span class="badge saving">saving edit</span></div>'
  : `<div class="cardfoot"><button class="link del" data-edit="${b.id}">Edit</button><button class="link del" data-del="${b.id}">Delete bet</button></div>`;
let editing = new Set(), fixing = new Map();
function fixLanded(all, p) {
  const b = all.find(x => x.id === p.bet), l = b && b.legs.find(x => x.n === p.leg);
  if (!l) return false;
  return p.value === 'clear' ? l.lr == null : p.value === 'dnp' ? l.lr === 'void' : l.act === +p.value;
}
function fixLink(b, l) {
  const key = b.id + ':' + l.n;
  if (fixing.has(key)) return '<div class="fixrow"><span class="badge saving">saving fix</span></div>';
  if (l.lr === 'review') return `<div class="fixrow"><span class="badge saving">not in the box score</span><button class="link fix need" data-fix="${key}">Enter result</button></div>`;
  if (l.lr == null && !(l.t && Date.parse(l.t) < Date.now())) return '';
  return `<div class="fixrow"><button class="link fix${l.lr == null ? ' need' : ''}" data-fix="${key}">${l.lr == null ? 'Enter result' : 'Fix stat'}</button></div>`;
}


document.addEventListener('click', async e => {
  const d = e.target.closest('[data-del]');
  if (d) {
    const b = D.bets.find(x => x.id === +d.dataset.del);
    if (!b) return;
    const ok = await EF.confirm({
      title: `Delete bet #${b.id}?`,
      body: `<p><b>${esc(b.entry)}</b> · $${b.stake.toFixed(2)} · placed ${esc(when(b.placed))}<br>${b.legs.map(l => esc(`${l.pl} ${l.side === 'over' ? 'Over' : 'Under'} ${l.pt} ${l.m}`)).join('<br>')}</p>` +
        '<p>It comes off your record, charts and stats. If you change your mind, restore it from <b>Deleted bets</b> at the bottom of Results.</p>',
      ok: 'Delete bet', cancel: 'Keep it', danger: true,
    });
    if (!ok) return;
    const n = await EF.send(`delete ${b.id}`, 'delete', {bet: b.id});
    if (n) EF.toast(`Bet #${b.id} deleted.`);
    render(); return;
  }
  const fx = e.target.closest('[data-fix]');
  if (fx) {
    const [bid, n] = fx.dataset.fix.split(':').map(Number);
    const b = D.bets.find(x => x.id === bid), l = b && b.legs.find(x => x.n === n);
    if (!l) return;
    const need = l.side === 'over' ? `${num(l.need)}+` : `${num(l.need)} or fewer`;
    let back = false;
    const pr = EF.confirm({title: `${l.pl}: final ${l.m}`, ok: 'Save', cancel: 'Cancel', body:
      `<p>#${b.id} ${esc(b.entry)} · ${l.side === 'over' ? 'Over' : 'Under'} ${l.pt} ${esc(l.m)} (needed ${esc(need)})` +
      (l.act != null ? `<br>Box score says ${num(l.act)}` : l.lr === 'void' ? '<br>Marked as didn\'t play' : '') + `</p>
<label class="fld">Final ${esc(l.m)} <input id="fx-v" type="number" inputmode="decimal" step="1" value="${l.act != null ? l.act : ''}"></label>
<label class="fld chk"><input id="fx-dnp" type="checkbox"${l.lr === 'void' ? ' checked' : ''}> Didn't play (the leg is void)</label>
<p class="fx-prev" id="fx-prev"></p>
<p>The leg's result follows from this number, and the bet re-settles.</p>` +
      (l.lr != null ? '<p><button class="link" id="fx-back">Undo my fix: grade it from the box score again</button></p>' : '')});
    const prev = () => {
      const dnp = $('#fx-dnp').checked, v = parseFloat($('#fx-v').value);
      $('#fx-v').disabled = dnp;
      $('#fx-prev').textContent = dnp ? 'Void: the leg doesn\'t count.' : isNaN(v) ? ''
        : Math.abs(v - l.pt) < 1e-9 ? 'That\'s a push.' : ((v > l.pt) === (l.side === 'over') ? '✓ That\'s a hit.' : '✗ That\'s a miss.');
    };
    prev(); $('#fx-v').oninput = prev; $('#fx-dnp').onchange = prev;
    if ($('#fx-back')) $('#fx-back').onclick = () => { back = true; $('#cf-yes').click(); };
    if (!(await pr)) return;
    let value;
    if (back) value = 'clear';
    else if ($('#fx-dnp').checked) value = 'dnp';
    else {
      const v = parseFloat($('#fx-v').value);
      if (isNaN(v)) { EF.toast('Enter the final number, or tick Didn\'t play.', true); return; }
      value = String(v);
    }
    const sent = await EF.send(`actual ${bid} ${n} ${value}`, 'fix', {bet: bid, leg: n, value});
    if (sent) EF.toast(value === 'clear' ? 'Going back to the box score.' : 'Fix saved. Results update in a couple of minutes.');
    render(); return;
  }
  const ed = e.target.closest('[data-edit]');
  if (ed) {
    const b = D.bets.find(x => x.id === +ed.dataset.edit);
    if (!b) return;
    const k = b.book === 'kalshi' || b.book === 'robinhood', unit = b.book === 'kalshi' ? 'Shares' : 'Contracts';
    const what = `<p><b>${esc(b.entry)}</b> · placed ${esc(when(b.placed))}<br>${b.legs.map(l => esc(`${l.pl} ${l.side === 'over' ? 'Over' : 'Under'} ${l.pt} ${l.m}`)).join('<br>')}</p>`;
    const body = what + (k
      ? `<label class="fld">Spent ($) <input id="ed-s" type="number" inputmode="decimal" min="0.01" step="0.01" value="${b.stake.toFixed(2)}"></label>
<label class="fld">${unit} <input id="ed-c" type="number" inputmode="decimal" min="0.01" step="0.01" value="${b.ct || ''}"></label>
<p id="ed-sum"></p><p>${b.book === 'kalshi' ? 'Copy both from Kalshi\'s order history (for example "$2.00 · 4.18 shares").' : 'Copy both from Robinhood\'s order (contracts, and the cost including fees).'}</p>`
      : `<label class="fld">Stake ($) <input id="ed-s" type="number" inputmode="decimal" min="0.01" step="0.01" value="${b.stake.toFixed(2)}"></label>`);
    const pr = EF.confirm({title: `Edit bet #${b.id}`, body, ok: 'Save', cancel: 'Cancel'});
    const sum = () => {
      const s = parseFloat($('#ed-s').value), c = parseFloat($('#ed-c').value);
      $('#ed-sum').innerHTML = s > 0 && c > 0 && s / c < 1 ? `${(100 * s / c).toFixed(1)}¢ each with fees · pays <b>$${c.toFixed(2)}</b> if it hits`
        : 'Enter what you spent and the shares you got';
    };
    if (k) { sum(); $('#ed-c').oninput = sum; $('#ed-s').oninput = sum; }
    if (!(await pr)) return;
    let args, stake;
    if (k) {
      stake = Math.round(parseFloat($('#ed-s').value) * 100) / 100;
      const c = Math.round(parseFloat($('#ed-c').value) * 100) / 100;
      if (!(stake > 0 && c > 0 && stake / c < 1)) { EF.toast('Enter what you spent and how many you got (under $1 each).', true); return; }
      args = `edit ${b.id} --stake ${stake.toFixed(2)} --contracts ${c.toFixed(2)}`;
    } else {
      stake = Math.round(parseFloat($('#ed-s').value) * 100) / 100;
      if (!(stake > 0)) { EF.toast('The stake has to be more than $0.', true); return; }
      args = `edit ${b.id} --stake ${stake.toFixed(2)}`;
    }
    const n = await EF.send(args, 'edit', {bet: b.id, stake});
    if (n) EF.toast(`Bet #${b.id} updated. It shows here in a couple of minutes.`);
    render(); return;
  }
  const rs = e.target.closest('[data-restore]');
  if (rs) {
    rs.disabled = true;
    const id = +rs.dataset.restore;
    const n = await EF.send(`restore ${id}`, 'restore', {bet: id});
    if (n) EF.toast(`Restoring bet #${id}.`);
    render(); return;
  }
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
  if (!EF.pending().some(p => ['bet', 'result', 'edit', 'fix', 'delete', 'restore'].includes(p.kind))) return;
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
