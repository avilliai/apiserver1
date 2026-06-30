/* Apollodorus 前端 — 由 index.html 拆分而来；所有文件共享全局作用域，按 index.html 中的顺序加载。 */
const API = '';
const S = {
  token:   localStorage.getItem('gw_token'),
  user:    JSON.parse(localStorage.getItem('gw_user') || 'null'),
  plugins:[],
};

async function apiFetch(path, opts = {}) {
  const h = { 'Content-Type': 'application/json' };
  if (S.token) h['Authorization'] = `Bearer ${S.token}`;
  const r = await fetch(API + path, { headers: h, ...opts });
  const d = await r.json().catch(() => ({}));
  if (!r.ok) throw new Error(d.detail || `HTTP ${r.status}`);
  return d;
}

function toast(msg, type = 'success') {
  const el = Object.assign(document.createElement('div'), { className: `toast ${type}`, textContent: msg });
  document.body.appendChild(el);
  setTimeout(() => el.remove(), 3000);
}

function fmt(ts) {
  if (!ts) return '—';
  return new Date(ts).toLocaleString('zh-CN', { month:'2-digit', day:'2-digit', hour:'2-digit', minute:'2-digit' });
}
function statusTag(code) {
  return `<span class="tag ${code>=200&&code<300?'tag-green':'tag-red'}">${code}</span>`;
}
