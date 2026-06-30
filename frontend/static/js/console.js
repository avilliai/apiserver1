/* Apollodorus 前端 — 由 index.html 拆分而来；所有文件共享全局作用域，按 index.html 中的顺序加载。 */
/* NAV */
const PUBLIC_PAGES = new Set(['home', 'auth']);
function pageNeedsAuth(name) {
  return !PUBLIC_PAGES.has(name) && !name.startsWith('plugin-');
}

function goPage(name) {
  // 门禁：控制台 / 管理页需登录
  if (pageNeedsAuth(name) && !(S.token && S.user)) {
    toast('请先登录', 'error');
    switchTab('login');
    name = 'auth';
  }
  document.querySelectorAll('.page').forEach(p => p.classList.remove('active'));
  document.querySelectorAll('.nav-link').forEach(n => n.classList.remove('active'));
  document.querySelectorAll('.subnav .pill').forEach(n => n.classList.remove('active'));

  const pg = document.getElementById(`page-${name}`);
  if (pg) pg.classList.add('active');

  // 顶栏高亮
  document.querySelectorAll(`.nav-link[data-page="${name}"]`).forEach(el => el.classList.add('active'));

  // 管理子导航
  const sub = document.getElementById('admin-subnav');
  if (name.startsWith('admin-')) {
    sub.classList.add('show');
    document.querySelectorAll(`.subnav .pill[data-page="${name}"]`).forEach(el => el.classList.add('active'));
    document.querySelectorAll('.nav-link[data-page="admin-users"]').forEach(el => el.classList.add('active'));
  } else {
    sub.classList.remove('show');
  }

  // 收起移动端菜单 + 回到顶部
  const nm = document.getElementById('navMenu'); if (nm) nm.classList.remove('is-open');
  window.scrollTo({ top: 0, behavior: 'smooth' });

  ({
    dashboard:       loadDashboard,
    usage:           loadUsage,
    apikeys:         loadApiKeys,
    'admin-users':   loadAdminUsers,
    'admin-invites': loadAdminInvites,
    'admin-stats':   loadAdminStats,
    'admin-logs':    loadAdminLogs,
  }[name] || (()=>{}))();
}

/* QUOTA RENDERER */
function renderQuota(elId, quota) {
  const el = document.getElementById(elId);
  const entries = Object.entries(quota || {});
  if (!entries.length) { el.innerHTML = '<div class="text-muted">No plugins configured.</div>'; return; }
  el.innerHTML = entries.map(([plugin, {used, limit}]) => {
    const pct = limit == null ? 0 : Math.min(100, Math.round((used/limit)*100));
    const cls = pct > 90 ? 'danger' : pct > 70 ? 'warn' : '';
    return `<div class="quota-item">
      <div class="quota-header">
        <span class="quota-name">${plugin}</span>
        <span class="quota-count">${limit==null
          ? `<span class="quota-unlimited">∞ unlimited · ${used} used</span>`
          : `${used} / ${limit}`}</span>
      </div>
      ${limit!=null ? `<div class="quota-track"><div class="quota-fill ${cls}" style="width:${pct}%"></div></div>` : ''}
    </div>`;
  }).join('');
}

/* DASHBOARD */
async function loadDashboard() {
  try {
    const d = await apiFetch('/api/user/usage');
    const total = Object.values(d.quota).reduce((s,q) => s+(q.used||0), 0);
    document.getElementById('dash-stats').innerHTML = `
      <div class="stat-card"><div class="stat-label">Total Requests</div><div class="stat-value c-teal">${total}</div><div class="stat-sub">across all plugins</div></div>
      <div class="stat-card"><div class="stat-label">Active Plugins</div><div class="stat-value c-green">${Object.keys(d.quota).length}</div><div class="stat-sub">with quota entries</div></div>
      <div class="stat-card"><div class="stat-label">Recent Logs</div><div class="stat-value c-amber">${d.recent_logs.length}</div><div class="stat-sub">last 200 requests</div></div>`;
    renderQuota('dash-quota', d.quota);
    document.querySelector('#dash-recent tbody').innerHTML =
      d.recent_logs.slice(0,8).map(l => `
        <tr>
          <td><span class="tag tag-teal">${l.plugin}</span></td>
          <td style="color:var(--text3);max-width:160px;overflow:hidden;text-overflow:ellipsis;white-space:nowrap">${l.endpoint}</td>
          <td>${statusTag(l.status_code)}</td>
          <td style="color:var(--text3);font-family:var(--mono);font-size:11px">${fmt(l.created_at)}</td>
        </tr>`).join('')
      || '<tr><td colspan="4" class="text-muted" style="text-align:center">No requests yet</td></tr>';
  } catch(e) { toast(e.message,'error'); }
}

/* USAGE */
async function loadUsage() {
  try {
    const d = await apiFetch('/api/user/usage');
    renderQuota('usage-quota', d.quota);
    document.querySelector('#usage-logs tbody').innerHTML =
      d.recent_logs.map(l => `
        <tr>
          <td style="color:var(--text3);font-family:var(--mono);font-size:11px">${l.id}</td>
          <td><span class="tag tag-teal">${l.plugin}</span></td>
          <td style="color:var(--text3);max-width:160px;overflow:hidden;text-overflow:ellipsis;white-space:nowrap">${l.endpoint}</td>
          <td>${statusTag(l.status_code)}</td>
          <td style="color:var(--text3);font-family:var(--mono);font-size:11px">${fmt(l.created_at)}</td>
        </tr>`).join('')
      || '<tr><td colspan="5" class="text-muted" style="text-align:center">No requests yet</td></tr>';
  } catch(e) { toast(e.message,'error'); }
}

/* API KEYS */
async function loadApiKeys() {
  try { renderKeyList(await apiFetch('/api/user/apikeys')); }
  catch(e) { toast(e.message,'error'); }
}
function renderKeyList(keys) {
  const el = document.getElementById('key-list');
  if (!keys.length) { el.innerHTML = '<div class="text-muted">No API keys yet.</div>'; return; }
  el.innerHTML = keys.map(k => `
    <div class="key-row">
      <div class="key-dot"></div>
      <div class="key-name">${k.name}</div>
      <div class="key-prefix">${k.key_prefix}…</div>
      <div class="key-date">Used: ${fmt(k.last_used_at)}</div>
      <div class="key-date">Created: ${fmt(k.created_at)}</div>
      <button class="btn btn-danger btn-sm" onclick="revokeKey(${k.id})">Revoke</button>
    </div>`).join('');
}
async function createApiKey() {
  const name = document.getElementById('new-key-name').value.trim() || 'New Key';
  try {
    const data = await apiFetch('/api/user/apikeys', { method:'POST', body: JSON.stringify({name}) });
    const reveal = document.getElementById('new-key-reveal');
    reveal.style.display = '';
    reveal.innerHTML = `<div class="key-reveal-box">
      <div class="key-reveal-label">⚡ Key Created — Save it now</div>
      <div class="key-reveal-value" onclick="navigator.clipboard.writeText('${data.key}').then(()=>toast('Copied!'))" title="Click to copy">${data.key}</div>
      <div class="key-reveal-warn">⚠ This key will not be shown again. Click above to copy.</div>
    </div>`;
    document.getElementById('new-key-name').value = '';
    toast('API key created'); loadApiKeys();
  } catch(e) { toast(e.message,'error'); }
}
async function revokeKey(id) {
  try { await apiFetch(`/api/user/apikeys/${id}`, { method:'DELETE' }); toast('Key revoked'); loadApiKeys(); }
  catch(e) { toast(e.message,'error'); }
}
