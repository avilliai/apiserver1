/* Apollodorus 前端 — 由 index.html 拆分而来；所有文件共享全局作用域，按 index.html 中的顺序加载。 */
/* ADMIN: USERS */
// 原始用户列表（全量，用于筛选）
let _allUsers = [];
// 当前展示的用户（筛选后）
let _visibleUsers = [];
// 已选中的用户 id 集合
let _selectedIds = new Set();

async function loadAdminUsers() {
  try {
    _allUsers = await apiFetch('/api/admin/users');
    _populatePluginSelectors(_allUsers);
    _visibleUsers = _allUsers;
    _renderUsersTable(_visibleUsers);
  } catch(e) { toast(e.message, 'error'); }
}

/** 从用户列表中收集所有插件名，填充筛选/批量下拉框 */
function _populatePluginSelectors(users) {
  const plugins = new Set();
  users.forEach(u => Object.keys(u.quota || {}).forEach(p => plugins.add(p)));
  const opts = ['<option value="">All Plugins</option>',
    ...[...plugins].sort().map(p => `<option value="${p}">${p}</option>`)].join('');
  document.getElementById('filter-plugin').innerHTML = opts;
  const batchOpts = ['<option value="">— Select Plugin —</option>',
    ...[...plugins].sort().map(p => `<option value="${p}">${p}</option>`)].join('');
  document.getElementById('batch-plugin').innerHTML = batchOpts;
}

/** 渲染用户表格，保留已选中状态 */
function _renderUsersTable(users) {
  document.querySelector('#admin-users-table tbody').innerHTML = users.map(u => `
    <tr id="urow-${u.id}" class="${_selectedIds.has(u.id) ? 'row-selected' : ''}">
      <td style="padding:11px 6px 11px 10px">
        <input type="checkbox" class="user-cb" data-uid="${u.id}"
          style="width:14px;height:14px;cursor:pointer;accent-color:var(--accent)"
          ${_selectedIds.has(u.id) ? 'checked' : ''}
          onchange="toggleUserSelect(${u.id}, this.checked)" />
      </td>
      <td style="color:var(--text);font-weight:600;font-size:13.5px">${u.username}${u.is_banned?' <span class="tag tag-red" style="font-size:9px">banned</span>':''}</td>
      <td><span class="badge ${u.is_admin?'badge-admin':'badge-user'}">${u.is_admin?'admin':'user'}</span></td>
      <td style="color:var(--text3);font-family:var(--mono);font-size:11px">${fmt(u.created_at)}</td>
      <td style="color:var(--text2)">${Object.keys(u.quota || {}).length}</td>
      <td><button class="btn btn-ghost btn-sm" onclick='openUserModal(${JSON.stringify(u).replace(/'/g,"&#39;")})'>Manage</button></td>
    </tr>`).join('');
  _syncSelectAllCheckbox();
}

/** 切换单个用户的勾选状态 */
function toggleUserSelect(uid, checked) {
  if (checked) _selectedIds.add(uid);
  else _selectedIds.delete(uid);
  const row = document.getElementById(`urow-${uid}`);
  if (row) row.classList.toggle('row-selected', checked);
  _syncBatchToolbar();
  _syncSelectAllCheckbox();
}

/** 全选 / 取消全选（仅作用于当前可见行） */
function toggleSelectAll(checked) {
  _visibleUsers.forEach(u => {
    if (checked) _selectedIds.add(u.id);
    else _selectedIds.delete(u.id);
    const row = document.getElementById(`urow-${u.id}`);
    if (row) row.classList.toggle('row-selected', checked);
    const cb = row && row.querySelector('.user-cb');
    if (cb) cb.checked = checked;
  });
  _syncBatchToolbar();
}

/** 同步全选框的半选/全选/未选状态 */
function _syncSelectAllCheckbox() {
  const allCb = document.getElementById('select-all-cb');
  if (!allCb) return;
  const total = _visibleUsers.length;
  const sel   = _visibleUsers.filter(u => _selectedIds.has(u.id)).length;
  allCb.checked = sel > 0 && sel === total;
  allCb.indeterminate = sel > 0 && sel < total;
}

/** 显示/隐藏批量操作栏 */
function _syncBatchToolbar() {
  const bar = document.getElementById('batch-toolbar');
  const cnt = document.getElementById('batch-count');
  const n = _selectedIds.size;
  bar.style.display = n > 0 ? '' : 'none';
  cnt.textContent = n;
}

function clearBatchSelection() {
  _selectedIds.clear();
  _renderUsersTable(_visibleUsers);
  _syncBatchToolbar();
}

/** 批量操作：插件切换时清空 limit 输入框占位符提示 */
function onBatchPluginChange() {}

/** 批量设置 limit */
async function batchSetLimit() {
  const plugin = document.getElementById('batch-plugin').value;
  const raw    = document.getElementById('batch-limit-val').value;
  if (!plugin) { toast('请先选择插件', 'error'); return; }
  if (!_selectedIds.size) { toast('未选中任何用户', 'error'); return; }
  const limit = raw === '' ? null : parseInt(raw, 10);
  const ids = [..._selectedIds];
  let ok = 0, fail = 0;
  await Promise.all(ids.map(async uid => {
    try {
      await apiFetch(`/api/admin/users/${uid}/quota`, {
        method: 'POST',
        body: JSON.stringify({ plugin, limit })
      });
      ok++;
    } catch { fail++; }
  }));
  toast(`Set limit → ${ok} ok${fail ? ', ' + fail + ' failed' : ''}`, fail ? 'error' : 'success');
  await loadAdminUsers();
}

/** 批量重置 used 为 0 */
async function batchResetUsed() {
  const plugin = document.getElementById('batch-plugin').value;
  if (!plugin) { toast('请先选择插件', 'error'); return; }
  if (!_selectedIds.size) { toast('未选中任何用户', 'error'); return; }
  const ids = [..._selectedIds];
  let ok = 0, fail = 0;
  await Promise.all(ids.map(async uid => {
    try {
      await apiFetch(`/api/admin/users/${uid}/reset-quota?plugin=${encodeURIComponent(plugin)}`, { method: 'POST' });
      ok++;
    } catch { fail++; }
  }));
  toast(`Reset used → ${ok} ok${fail ? ', ' + fail + ' failed' : ''}`, fail ? 'error' : 'success');
  await loadAdminUsers();
}

/** 应用筛选条件 */
function applyFilter() {
  const plugin = document.getElementById('filter-plugin').value;
  const op     = document.getElementById('filter-op').value;
  const val    = parseFloat(document.getElementById('filter-val').value);

  // 无条件时直接展示全部
  if (!plugin && !op) { clearFilter(); return; }

  _visibleUsers = _allUsers.filter(u => {
    const quota = u.quota || {};

    // 若指定了插件但用户没有该插件配额，则排除
    if (plugin && !(plugin in quota)) return false;

    // 若只选了插件没选操作符，展示拥有该插件的所有用户
    if (!op) return true;

    const entry   = plugin ? quota[plugin] : null;
    const used    = entry ? (entry.used  ?? 0)    : 0;
    const limit   = entry ? (entry.limit ?? null) : null;
    const remaining = limit === null ? Infinity : Math.max(0, limit - used);
    const pct       = limit ? (used / limit) * 100 : 0;

    switch (op) {
      case 'remaining_lt':  return remaining < val;
      case 'remaining_lte': return remaining <= val;
      case 'used_gt':       return used > val;
      case 'pct_gt':        return limit !== null && pct > val;
      case 'exhausted':     return limit !== null && used >= limit;
      case 'unlimited':     return limit === null;
      default:              return true;
    }
  });

  _renderUsersTable(_visibleUsers);

  const badge = document.getElementById('filter-result-badge');
  badge.style.display = '';
  badge.textContent = `${_visibleUsers.length} / ${_allUsers.length} users`;
}

function clearFilter() {
  document.getElementById('filter-plugin').value = '';
  document.getElementById('filter-op').value = '';
  document.getElementById('filter-val').value = '';
  _visibleUsers = _allUsers;
  _renderUsersTable(_visibleUsers);
  document.getElementById('filter-result-badge').style.display = 'none';
}

function openUserModal(user) {
  const rows = Object.entries(user.quota).map(([plugin, {used, limit}]) => `
    <div style="display:flex;align-items:center;gap:10px;padding:10px 0;border-bottom:1px solid var(--border)">
      <span style="flex:1;font-size:13.5px;color:var(--text)">${plugin}</span>
      <span style="color:var(--text3);font-family:var(--mono);font-size:11px">${used} used</span>
      <input type="number" value="${limit??''}" placeholder="∞" class="form-input" style="width:70px;padding:6px 10px;font-size:12px" id="qi-${plugin}" />
      <button class="btn btn-ghost btn-sm" onclick="setQuota(${user.id},'${plugin}')">Set</button>
      <button class="btn btn-ghost btn-sm" onclick="resetQuota(${user.id},'${plugin}')">Reset</button>
    </div>`).join('');
  const ov = document.createElement('div');
  ov.className = 'modal-overlay';
  ov.innerHTML = `<div class="modal"><div class="modal-head"><div class="modal-title">${escHtml(user.username)}${user.is_banned?' <span class="tag tag-red" style="font-size:10px;vertical-align:middle">banned</span>':''}</div><span class="modal-close" onclick="this.closest('.modal-overlay').remove()">✕</span></div>${rows||'<div class="text-muted">No quotas.</div>'}
    <div style="display:flex;justify-content:flex-end;margin-top:18px;padding-top:14px;border-top:1px solid var(--border)">${user.is_banned
      ? `<button class="btn btn-ghost btn-sm" onclick="unbanUser(${user.id});this.closest('.modal-overlay').remove()">解封并还原配额</button>`
      : `<button class="btn btn-danger btn-sm" onclick="banUser(${user.id});this.closest('.modal-overlay').remove()">封禁此用户 + IP</button>`}</div>
  </div>`;
  ov.addEventListener('click', e => { if (e.target===ov) ov.remove(); });
  document.body.appendChild(ov);
}
async function setQuota(uid, plugin) {
  const v = document.getElementById(`qi-${plugin}`).value;
  try { await apiFetch(`/api/admin/users/${uid}/quota`, { method:'POST', body: JSON.stringify({plugin, limit: v===''?null:parseInt(v)}) }); toast('Updated'); }
  catch(e) { toast(e.message,'error'); }
}
async function resetQuota(uid, plugin) {
  try { await apiFetch(`/api/admin/users/${uid}/reset-quota?plugin=${plugin}`, { method:'POST' }); toast('Reset to 0'); }
  catch(e) { toast(e.message,'error'); }
}
async function banUser(uid) {
  if (!confirm('确认封禁该用户？将封禁其历史 IP，并把其所有接口配额上限设为 0。')) return;
  try {
    const r = await apiFetch(`/api/admin/users/${uid}/ban`, { method:'POST', body: JSON.stringify({ reason: 'banned from users page' }) });
    toast(`已封禁：${(r.banned_ips||[]).length} 个 IP，${(r.zeroed_plugins||[]).length} 个接口配额归零`);
    loadAdminUsers();
  } catch(e) { toast(e.message,'error'); }
}
async function unbanUser(uid) {
  if (!confirm('解封该用户并把配额上限还原为各接口默认值？')) return;
  try { await apiFetch(`/api/admin/users/${uid}/unban`, { method:'POST' }); toast('已解封'); loadAdminUsers(); }
  catch(e) { toast(e.message,'error'); }
}

/* ADMIN: INVITES */
async function loadAdminInvites() {
  try { renderInvites(await apiFetch('/api/admin/invite/list')); }
  catch(e) { toast(e.message,'error'); }
}
function renderInvites(list) {
  const el = document.getElementById('invite-list');
  el.innerHTML = list.length
    ? list.map(i => `
        <div class="code-card">
          <span class="code-val">${i.code}</span>
          <span class="code-btn" onclick="navigator.clipboard.writeText('${i.code}').then(()=>toast('Copied!'))" title="Copy">⎘</span>
          <span class="code-btn code-del" onclick="deleteInvite('${i.code}',this)" title="Delete">✕</span>
        </div>`).join('')
    : '<div class="text-muted">No active codes.</div>';
}
async function generateInvites() {
  const n = parseInt(document.getElementById('invite-count').value) || 1;
  try { await apiFetch(`/api/admin/invite/generate?count=${n}`, { method:'POST' }); toast(`Generated ${n} code(s)`); loadAdminInvites(); }
  catch(e) { toast(e.message,'error'); }
}
async function deleteInvite(code, el) {
  try { await apiFetch(`/api/admin/invite/${code}`, { method:'DELETE' }); el.closest('.code-card').remove(); toast('Deleted'); }
  catch(e) { toast(e.message,'error'); }
}

/* ADMIN: STATS */
async function loadAdminStats() {
  try {
    const s = await apiFetch('/api/admin/stats');
    document.getElementById('admin-stat-cards').innerHTML = `
      <div class="stat-card"><div class="stat-label">Total Users</div><div class="stat-value c-teal">${s.total_users}</div></div>
      <div class="stat-card"><div class="stat-label">Total Requests</div><div class="stat-value c-green">${s.total_requests}</div></div>
      <div class="stat-card"><div class="stat-label">Active Plugins</div><div class="stat-value c-amber">${s.by_plugin.length}</div></div>`;
    drawLineChart(s.daily);
    document.getElementById('stats-by-plugin').innerHTML =
      s.by_plugin.map(p => `
        <div style="display:flex;justify-content:space-between;align-items:center;padding:9px 0;border-bottom:1px solid var(--border)">
          <span class="tag tag-teal">${p.plugin}</span>
          <span style="color:var(--text);font-family:var(--mono);font-size:13px">${p.count}</span>
        </div>`).join('')
      || '<div class="text-muted">No data</div>';
    document.getElementById('stats-by-user').innerHTML =
      s.by_user.sort((a,b)=>b.count-a.count).slice(0,10).map(u => `
        <div style="display:flex;justify-content:space-between;align-items:center;padding:9px 0;border-bottom:1px solid var(--border)">
          <span style="color:var(--text);font-size:13.5px;font-weight:500">${u.username}</span>
          <span style="color:var(--text2);font-family:var(--mono);font-size:12px">${u.count}</span>
        </div>`).join('')
      || '<div class="text-muted">No data</div>';
  } catch(e) { toast(e.message,'error'); }
}

/* LINE CHART */
function drawLineChart(daily) {
  const svg = document.getElementById('line-svg');
  if (!daily || !daily.length) {
    svg.innerHTML = '<text x="400" y="80" fill="#9ab0b2" font-size="13" text-anchor="middle" font-family="JetBrains Mono">No data</text>';
    return;
  }
  const W=800, H=160, PX=20, PY=16;
  const max = Math.max(...daily.map(d=>d.count), 1);
  const n = daily.length;
  const pts = daily.map((d,i) =>[
    PX + (i/Math.max(n-1,1))*(W-PX*2),
    PY + (1 - d.count/max)*(H-PY*2),
    d.day, d.count
  ]);
  let area = `M ${pts[0][0]} ${H} L ${pts[0][0]} ${pts[0][1]}`;
  let line = `M ${pts[0][0]} ${pts[0][1]}`;
  for (let i=1; i<pts.length; i++) {
    const [x0,y0]=pts[i-1],[x1,y1]=pts[i], cx=(x0+x1)/2;
    area += ` C ${cx} ${y0} ${cx} ${y1} ${x1} ${y1}`;
    line += ` C ${cx} ${y0} ${cx} ${y1} ${x1} ${y1}`;
  }
  area += ` L ${pts[pts.length-1][0]} ${H} Z`;
  const step = Math.max(1, Math.floor(n/6));
  const labels = pts.filter((_,i)=>i%step===0||i===n-1)
    .map(([x,,day])=>`<text x="${x}" y="${H+14}" fill="#9ab0b2" font-size="9" text-anchor="middle" font-family="JetBrains Mono">${(day||'').slice(5)}</text>`)
    .join('');
  const dots = pts.map(([x,y,day,count])=>
    `<circle cx="${x}" cy="${y}" r="3" fill="#58a0a4" opacity="0.8"><title>${day}: ${count}</title></circle>`
  ).join('');
  svg.innerHTML = `
    <defs>
      <linearGradient id="ag" x1="0" y1="0" x2="0" y2="1">
        <stop offset="0%" stop-color="#9ad4d6" stop-opacity="0.35"/>
        <stop offset="100%" stop-color="#9ad4d6" stop-opacity="0.02"/>
      </linearGradient>
    </defs>
    <path d="${area}" fill="url(#ag)"/>
    <path d="${line}" fill="none" stroke="#58a0a4" stroke-width="2" stroke-opacity="0.9"/>
    ${dots}${labels}`;
}

/* ADMIN: REQUEST LOGS */
let _logsOffset = 0;
const _logsLimit = 50;
let _logsTotal = 0;
let _logsById = {};
let _logsPluginsLoaded = false;

async function loadAdminLogs(resetPage = true) {
  if (resetPage) _logsOffset = 0;
  if (!_logsPluginsLoaded && Array.isArray(S.plugins)) {
    document.getElementById('logs-plugin').innerHTML =
      '<option value="">All Plugins</option>' +
      S.plugins.map(p => `<option value="${escHtml(p.name)}">${escHtml(p.display_name||p.name)}</option>`).join('');
    _logsPluginsLoaded = true;
  }
  const search = document.getElementById('logs-search').value.trim();
  const plugin = document.getElementById('logs-plugin').value;
  const qs = new URLSearchParams({ search, plugin, limit: _logsLimit, offset: _logsOffset });
  try {
    const d = await apiFetch('/api/admin/logs?' + qs.toString());
    _logsTotal = d.total;
    _logsById = {};
    d.logs.forEach(l => { _logsById[l.id] = l; });
    _renderLogsTable(d.logs);
    const from = d.total ? _logsOffset + 1 : 0;
    const to = Math.min(_logsOffset + _logsLimit, d.total);
    document.getElementById('logs-page-info').textContent = `${from}–${to} of ${d.total}`;
    document.getElementById('logs-result-badge').textContent = `${d.total} 条记录`;
    document.getElementById('logs-prev').disabled = _logsOffset <= 0;
    document.getElementById('logs-next').disabled = to >= d.total;
  } catch(e) { toast(e.message, 'error'); }
}

function logsPage(dir) {
  const next = _logsOffset + dir * _logsLimit;
  if (next < 0 || next >= _logsTotal) return;
  _logsOffset = next;
  loadAdminLogs(false);
}

function _renderLogsTable(logs) {
  const tb = document.querySelector('#admin-logs-table tbody');
  if (!logs.length) {
    tb.innerHTML = '<tr><td colspan="8" class="text-muted" style="text-align:center">No matching logs</td></tr>';
    return;
  }
  tb.innerHTML = logs.map(l => {
    const params = (l.request_body || '').replace(/\s+/g, ' ').trim();
    const preview = params.length > 64 ? params.slice(0, 64) + '…' : params;
    const userCell = l.user_id
      ? `${escHtml(l.username||'')}${l.user_banned ? ' <span class="tag tag-red" style="font-size:9px">banned</span>' : ''}`
      : `<span class="text-muted" style="padding:0">${escHtml(l.username||'(anonymous)')}</span>`;
    let actionBtn = '';
    if (l.user_id) {
      actionBtn = l.user_banned
        ? `<button class="btn btn-ghost btn-sm" onclick="unbanFromLog(${l.id})">Unban</button>`
        : `<button class="btn btn-danger btn-sm" onclick="banFromLog(${l.id})">Ban</button>`;
    }
    return `<tr>
      <td style="color:var(--text3);font-family:var(--mono);font-size:11px;white-space:nowrap">${fmt(l.created_at)}</td>
      <td style="font-size:13px">${userCell}</td>
      <td style="color:var(--text3);font-family:var(--mono);font-size:11px">${escHtml(l.ip_address||'')}</td>
      <td><span class="tag tag-teal">${escHtml(l.plugin||'')}</span></td>
      <td style="color:var(--text3);max-width:150px;overflow:hidden;text-overflow:ellipsis;white-space:nowrap" title="${escHtml(l.endpoint||'')}">${escHtml(l.endpoint||'')}</td>
      <td>${statusTag(l.status_code)}</td>
      <td style="max-width:240px;overflow:hidden;text-overflow:ellipsis;white-space:nowrap;color:var(--text2);font-family:var(--mono);font-size:11px;cursor:pointer" onclick="openLogDetail(${l.id})" title="点击查看完整内容">${escHtml(preview) || '<span class="text-muted" style="padding:0">—</span>'}</td>
      <td style="white-space:nowrap"><button class="btn btn-ghost btn-sm" onclick="openLogDetail(${l.id})">View</button> ${actionBtn}</td>
    </tr>`;
  }).join('');
}

function openLogDetail(id) {
  const l = _logsById[id];
  if (!l) return;
  const preBox = 'background:rgba(42,61,62,0.05);border:1.5px solid var(--border2);border-radius:var(--r);padding:12px;font-family:var(--mono);font-size:12px;color:var(--text2);line-height:1.7;overflow:auto;max-height:240px;white-space:pre-wrap;word-break:break-word;margin:0';
  const banZone = l.user_id
    ? `<div style="margin-top:16px;display:flex;justify-content:flex-end">${l.user_banned
        ? `<button class="btn btn-ghost btn-sm" onclick="unbanFromLog(${l.id});this.closest('.modal-overlay').remove()">Unban User</button>`
        : `<button class="btn btn-danger btn-sm" onclick="banFromLog(${l.id});this.closest('.modal-overlay').remove()">封禁该用户 + IP</button>`}</div>`
    : '';
  const ov = document.createElement('div');
  ov.className = 'modal-overlay';
  ov.innerHTML = `<div class="modal" style="width:680px">
    <div class="modal-head">
      <div class="modal-title">Request #${l.id}</div>
      <span class="modal-close" onclick="this.closest('.modal-overlay').remove()">✕</span>
    </div>
    <div style="display:grid;grid-template-columns:auto 1fr;gap:6px 14px;font-size:13px;margin-bottom:16px">
      <span style="color:var(--text3)">User</span><span>${escHtml(l.username||'')} ${l.user_id?`(#${l.user_id})`:''}${l.user_banned?' · <span style="color:var(--red)">banned</span>':''}</span>
      <span style="color:var(--text3)">IP</span><span style="font-family:var(--mono)">${escHtml(l.ip_address||'')}</span>
      <span style="color:var(--text3)">API Key</span><span style="font-family:var(--mono)">${escHtml(l.api_key_prefix||'—')}</span>
      <span style="color:var(--text3)">Endpoint</span><span style="font-family:var(--mono)">${escHtml(l.method||'')} ${escHtml(l.endpoint||'')}</span>
      <span style="color:var(--text3)">Status</span><span>${statusTag(l.status_code)} · ${l.duration_ms??'?'} ms</span>
      <span style="color:var(--text3)">Time</span><span>${fmt(l.created_at)}</span>
    </div>
    <div class="card-title" style="margin-bottom:6px">Request Params</div>
    <pre style="${preBox}">${escHtml(l.request_body||'(empty)')}</pre>
    <div class="card-title" style="margin:14px 0 6px">Response</div>
    <pre style="${preBox}">${escHtml(l.response_body||'(empty)')}</pre>
    ${banZone}
  </div>`;
  ov.addEventListener('click', e => { if (e.target===ov) ov.remove(); });
  document.body.appendChild(ov);
}

async function banFromLog(id) {
  const l = _logsById[id];
  if (!l || !l.user_id) return;
  if (!confirm(`确认封禁用户「${l.username}」？\n将封禁其 IP（${l.ip_address} 及其历史 IP）并把其所有接口配额上限设为 0。`)) return;
  try {
    const r = await apiFetch(`/api/admin/users/${l.user_id}/ban`, {
      method:'POST', body: JSON.stringify({ reason: 'banned from request logs', ip: l.ip_address })
    });
    toast(`已封禁 ${l.username}：${(r.banned_ips||[]).length} 个 IP，${(r.zeroed_plugins||[]).length} 个接口配额归零`);
    loadAdminLogs(false);
  } catch(e) { toast(e.message, 'error'); }
}

async function unbanFromLog(id) {
  const l = _logsById[id];
  if (!l || !l.user_id) return;
  if (!confirm(`解封用户「${l.username}」？将解除其 IP 封禁并把接口配额上限还原为默认值。`)) return;
  try {
    await apiFetch(`/api/admin/users/${l.user_id}/unban`, { method:'POST' });
    toast(`已解封 ${l.username}`);
    loadAdminLogs(false);
  } catch(e) { toast(e.message, 'error'); }
}
