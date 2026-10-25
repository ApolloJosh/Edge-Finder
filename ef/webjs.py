"""Saving from the app: the one-time key sheet, Save, and the "recording" list.

The site is static (GitHub Pages), so a save is a call to GitHub's API with a
key the user creates once and keeps on their phone. The key can only open
issues on this one repo; the scheduled run reads them, records the bet or
result, and closes them. Nobody has to look at GitHub.
"""

SHEET_CSS = """
.sheet-bg{position:fixed;inset:0;background:rgba(0,0,0,.45);z-index:50;display:none}
.sheet-bg.on{display:block}
.sheet{position:fixed;left:0;right:0;bottom:0;z-index:51;background:var(--panel);border-radius:18px 18px 0 0;
max-height:88vh;overflow:auto;transform:translateY(110%);transition:transform .2s ease;box-shadow:var(--shadow)}
.sheet.on{transform:none}
.sheet-in{max-width:560px;margin:0 auto;padding:16px 18px calc(18px + env(safe-area-inset-bottom))}
.sheet h3{margin:4px 0 6px;font-size:18px}
.sheet p,.sheet li{color:var(--dim);font-size:14px;line-height:1.5}
.sheet ol{padding-left:20px;margin:8px 0}
.sheet input[type=password],.sheet input[type=text]{width:100%;font:inherit;font-size:15px;padding:11px 12px;border:1px solid var(--line);
border-radius:10px;background:var(--bg);color:var(--ink);margin:6px 0 10px}
.sheet .row{display:flex;gap:8px;margin-top:6px}
.sheet .row>*{flex:1}
.okline{color:var(--accent);font-weight:650}
#toast{position:fixed;left:50%;bottom:calc(20px + env(safe-area-inset-bottom));transform:translate(-50%,140%);z-index:60;
background:var(--ink);color:var(--bg);border-radius:12px;padding:11px 16px;font-size:14px;font-weight:600;max-width:calc(100% - 32px);
transition:transform .2s ease;box-shadow:var(--shadow)}
#toast.on{transform:translate(-50%,0)}
#toast.bad{background:var(--bad);color:#fff}
body.docked #toast{bottom:calc(240px + env(safe-area-inset-bottom))}
nav.top a.gear{margin-left:auto}
"""

GH_JS = r"""
window.EF = (function () {
  const REPO = window.EF_REPO;
  const TOKEN_URL = 'https://github.com/settings/personal-access-tokens/new?name=' + encodeURIComponent('Edge Finder app') +
    '&description=' + encodeURIComponent('Lets the Edge Finder app save bets and start runs') +
    '&target_name=' + encodeURIComponent(REPO.split('/')[0]) + '&expires_in=366&issues=write';
  const store = {
    get(k, d) { try { const v = localStorage.getItem(k); return v == null ? d : JSON.parse(v); } catch (e) { return d; } },
    set(k, v) { try { localStorage.setItem(k, JSON.stringify(v)); } catch (e) {} },
    del(k) { try { localStorage.removeItem(k); } catch (e) {} },
  };
  const token = () => store.get('ef-token', '');
  let toastTimer;
  function toast(msg, bad) {
    let t = document.getElementById('toast');
    if (!t) { t = document.createElement('div'); t.id = 'toast'; document.body.appendChild(t); }
    t.textContent = msg; t.classList.toggle('bad', !!bad); t.classList.add('on');
    clearTimeout(toastTimer); toastTimer = setTimeout(() => t.classList.remove('on'), bad ? 6000 : 3500);
  }
  function issueLink(args) {
    return `https://github.com/${REPO}/issues/new?title=${encodeURIComponent(args)}&body=${encodeURIComponent('```\n' + args + '\n```')}`;
  }
  async function send(args, kind, meta) {
    const t = token();
    if (!t) { openSettings('Connect once, then Save and Run work from here.'); return false; }
    let r;
    try {
      r = await fetch(`https://api.github.com/repos/${REPO}/issues`, {
        method: 'POST',
        headers: {Authorization: 'Bearer ' + t, Accept: 'application/vnd.github+json', 'X-GitHub-Api-Version': '2022-11-28',
                  'Content-Type': 'application/json'},
        body: JSON.stringify({title: args, body: '```\n' + args + '\n```\nSaved from the Edge Finder app.'}),
      });
    } catch (e) { toast("Couldn't reach GitHub. Check your connection and try again.", true); return false; }
    if (r.status === 201) {
      const j = await r.json();
      const p = store.get('ef-pending', []);
      p.push(Object.assign({n: j.number, kind, args, ts: Date.now()}, meta || {}));
      store.set('ef-pending', p);
      return j.number;
    }
    if (r.status === 401) toast('GitHub rejected the key (it may have expired). Reconnect in Settings.', true);
    else if (r.status === 403 || r.status === 404) toast("The key can't save to Edge-Finder. Recreate it with Edge-Finder selected and Issues: Read and write.", true);
    else toast('GitHub said ' + r.status + '. Try again in a minute.', true);
    return false;
  }
  // Pending saves the data hasn't caught up with yet. `done(p)` says a save is now recorded.
  function pending(done) {
    let p = store.get('ef-pending', []);
    const keep = p.filter(x => !(done && done(x)) && Date.now() - x.ts < 12 * 3600e3);
    if (keep.length !== p.length) store.set('ef-pending', keep);
    return keep;
  }

  function sheet() {
    let bg = document.getElementById('sheet-bg');
    if (bg) return bg;
    bg = document.createElement('div'); bg.id = 'sheet-bg'; bg.className = 'sheet-bg';
    const s = document.createElement('div'); s.id = 'sheet'; s.className = 'sheet';
    s.innerHTML = `<div class="sheet-in">
<h3>Save bets and run from this app</h3>
<p id="set-why"></p>
<div id="set-on" hidden><p class="okline">Connected. Save works on this device.</p>
<div class="row"><button class="ghost" id="set-test">Check it</button><button class="ghost" id="set-off">Disconnect</button></div></div>
<div id="set-off-box"><p>Edge Finder saves to your GitHub repo. To let this phone do that, create a key once. It can only open
notes on Edge-Finder; it can't change code or see anything else.</p>
<ol><li>Tap <b>Create the key</b>. GitHub opens with it filled in.</li>
<li>Under <b>Repository access</b> choose <b>Only select repositories</b> → <b>Edge-Finder</b>.</li>
<li>Tap <b>Generate token</b>, then copy it.</li>
<li>Come back here, paste it below, and tap <b>Connect</b>.</li></ol>
<a class="btn ghost" id="set-make" target="_blank" rel="noopener" style="width:100%">Create the key on GitHub</a>
<input type="password" id="set-key" placeholder="Paste the key (starts with github_pat_)" autocomplete="off" autocapitalize="off" spellcheck="false">
<div class="row"><button id="set-save">Connect</button></div></div>
<p style="margin-top:14px;font-size:12.5px">The key stays in this browser only. Each device you use needs its own connect.</p>
<div class="row"><button class="ghost" id="set-close">Done</button></div></div>`;
    document.body.appendChild(bg); document.body.appendChild(s);
    s.querySelector('#set-make').href = TOKEN_URL;
    bg.onclick = close; s.querySelector('#set-close').onclick = close;
    s.querySelector('#set-save').onclick = async () => {
      const v = s.querySelector('#set-key').value.trim();
      if (!/^(github_pat_|ghp_)/.test(v)) { toast('That doesn\'t look like a GitHub key. It starts with github_pat_.', true); return; }
      if (await check(v)) { store.set('ef-token', v); s.querySelector('#set-key').value = ''; render(); toast('Connected. Save is ready.'); window.dispatchEvent(new Event('ef-auth')); }
    };
    s.querySelector('#set-off').onclick = () => { store.del('ef-token'); render(); toast('Disconnected on this device.'); window.dispatchEvent(new Event('ef-auth')); };
    s.querySelector('#set-test').onclick = async () => { if (await check(token())) toast('Key works.'); };
    return bg;
  }
  async function check(t) {
    try {
      const r = await fetch(`https://api.github.com/repos/${REPO}`, {headers: {Authorization: 'Bearer ' + t, Accept: 'application/vnd.github+json'}});
      if (r.status === 200) return true;
      toast(r.status === 401 ? 'GitHub rejected that key.' : "That key can't see Edge-Finder. Pick Edge-Finder under Repository access.", true);
    } catch (e) { toast("Couldn't reach GitHub.", true); }
    return false;
  }
  function render(why) {
    const s = document.getElementById('sheet');
    const on = !!token();
    s.querySelector('#set-on').hidden = !on;
    s.querySelector('#set-off-box').hidden = on;
    s.querySelector('#set-why').textContent = why || '';
    s.querySelector('#set-why').hidden = !why;
  }
  function openSettings(why) { const bg = sheet(); render(why); bg.classList.add('on'); document.getElementById('sheet').classList.add('on'); }
  function close() { document.getElementById('sheet-bg').classList.remove('on'); document.getElementById('sheet').classList.remove('on'); }
  document.addEventListener('click', e => { if (e.target.closest('#navset')) { e.preventDefault(); openSettings(); } });
  return {send, pending, openSettings, token, toast, issueLink, store};
})();
"""


def script(repo):
    import json
    return "<script>window.EF_REPO = %s;%s</script>" % (json.dumps(repo), GH_JS)
