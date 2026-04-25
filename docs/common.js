// 朝設定／保有銘柄の両画面で共有するコア関数
window.SML = (() => {
  const KEY = 'stock-morning-line';
  let state = JSON.parse(localStorage.getItem(KEY) || '{}');
  state.holdings = state.holdings || [];

  function save() {
    localStorage.setItem(KEY, JSON.stringify(state));
  }

  function log(msg) {
    const el = document.getElementById('log');
    if (!el) return;
    el.textContent += `\n[${new Date().toLocaleTimeString()}] ${msg}`;
    el.scrollTop = el.scrollHeight;
  }

  async function getRepoSettings() {
    if (!state.gh_pat) throw new Error('PAT未入力');
    const url = `https://api.github.com/repos/${state.gh_user || 'KATO-BOON'}/${state.gh_repo || 'stock-morning-line'}/contents/config/settings.json`;
    const resp = await fetch(url, { headers: { Authorization: `token ${state.gh_pat}` } });
    if (resp.status === 200) {
      const j = await resp.json();
      const decoded = decodeURIComponent(escape(atob(j.content.replace(/\n/g, ''))));
      return { sha: j.sha, body: JSON.parse(decoded) };
    } else if (resp.status === 404) {
      return { sha: null, body: {} };
    } else {
      throw new Error(`GET失敗 ${resp.status}: ${await resp.text()}`);
    }
  }

  async function patchRepoSettings(patch, message) {
    save();
    const cur = await getRepoSettings();
    const merged = { ...cur.body, ...patch };
    const url = `https://api.github.com/repos/${state.gh_user || 'KATO-BOON'}/${state.gh_repo || 'stock-morning-line'}/contents/config/settings.json`;
    const content = btoa(unescape(encodeURIComponent(JSON.stringify(merged, null, 2))));
    const resp = await fetch(url, {
      method: 'PUT',
      headers: { Authorization: `token ${state.gh_pat}`, 'Content-Type': 'application/json' },
      body: JSON.stringify({ message, content, sha: cur.sha }),
    });
    if (!resp.ok) throw new Error(`PUT失敗 ${resp.status}: ${await resp.text()}`);
    return await resp.json();
  }

  async function dispatch(workflow) {
    if (!state.gh_pat) throw new Error('PAT未入力');
    const url = `https://api.github.com/repos/${state.gh_user || 'KATO-BOON'}/${state.gh_repo || 'stock-morning-line'}/actions/workflows/${workflow}/dispatches`;
    const resp = await fetch(url, {
      method: 'POST',
      headers: { Authorization: `token ${state.gh_pat}`, 'Content-Type': 'application/json', Accept: 'application/vnd.github+json' },
      body: JSON.stringify({ ref: 'main' }),
    });
    if (!resp.ok) throw new Error(`${resp.status}: ${await resp.text()}`);
  }

  return { state, save, log, getRepoSettings, patchRepoSettings, dispatch };
})();
