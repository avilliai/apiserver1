/* Apollodorus 2.0 // Core State, Network & Utilities */
const API = '';
const S = {
  token: localStorage.getItem('gw_token'),
  user: JSON.parse(localStorage.getItem('gw_user') || 'null'),
  plugins: [],
  userKeys: []
};

async function apiFetch(path, opts = {}) {
  const headers = opts.headers || {};
  if (!(opts.body instanceof FormData) && !headers['Content-Type']) {
    headers['Content-Type'] = 'application/json';
  }
  if (S.token) {
    headers['Authorization'] = `Bearer ${S.token}`;
  }
  const res = await fetch(API + path, { ...opts, headers });
  const data = await res.json().catch(() => ({}));
  if (!res.ok) {
    throw new Error(data.detail || `HTTP ${res.status}`);
  }
  return data;
}

function toast(msg, type = 'success') {
  document.querySelectorAll('.toast').forEach(t => t.remove());
  const el = Object.assign(document.createElement('div'), {
    className: `toast ${type}`,
    textContent: msg
  });
  document.body.appendChild(el);
  setTimeout(() => {
    el.style.opacity = '0';
    el.style.transform = 'translateY(12px) scale(0.96)';
    el.style.transition = 'all 0.2s cubic-bezier(0.16, 1, 0.3, 1)';
    setTimeout(() => el.remove(), 220);
  }, 2800);
}

function fmt(ts) {
  if (!ts) return '—';
  let s = ts;
  if (typeof s === 'string') {
    s = s.replace(' ', 'T');
    if (!/[zZ]|[+-]\d\d:?\d\d$/.test(s)) s += 'Z';
  }
  return new Date(s).toLocaleString('zh-CN', {
    month: '2-digit',
    day: '2-digit',
    hour: '2-digit',
    minute: '2-digit',
    second: '2-digit'
  });
}

function escHtml(str) {
  if (str == null) return '';
  return String(str)
    .replace(/&/g, '&amp;')
    .replace(/</g, '&lt;')
    .replace(/>/g, '&gt;')
    .replace(/"/g, '&quot;')
    .replace(/'/g, '&#39;');
}

function statusTag(code) {
  const c = parseInt(code, 10);
  if (isNaN(c)) return `<span class="tag tag-amber">${escHtml(code)}</span>`;
  const cls = (c >= 200 && c < 300) ? 'tag-green' : (c >= 400 && c < 500) ? 'tag-amber' : 'tag-red';
  return `<span class="tag ${cls}">${c}</span>`;
}

function copyCode(elementId) {
  const el = document.getElementById(elementId);
  if (!el) return;
  const text = el.innerText || el.textContent;
  copyText(text, '代码已复制到剪贴板');
}

function copyText(text, successMsg = '已复制到剪贴板') {
  if (navigator.clipboard && window.isSecureContext) {
    navigator.clipboard.writeText(text)
      .then(() => toast(successMsg))
      .catch(() => _fallbackCopy(text, successMsg));
  } else {
    _fallbackCopy(text, successMsg);
  }
}

function _fallbackCopy(text, successMsg) {
  const ta = document.createElement('textarea');
  ta.value = text;
  ta.style.position = 'fixed';
  ta.style.left = '-9999px';
  document.body.appendChild(ta);
  ta.focus();
  ta.select();
  try {
    document.execCommand('copy');
    toast(successMsg);
  } catch (e) {
    toast('复制失败，请手动选取复制', 'error');
  }
  ta.remove();
}
