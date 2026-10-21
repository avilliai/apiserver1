/* Apollodorus 2.0 // Admin Command Terminal & Telemetry */

let _adminUsers = [];
let _selectedIds = new Set();
let _usersPluginsLoaded = false;

/* ADMIN: USERS */
async function loadAdminUsers() {
  try {
    const users = await apiFetch('/api/admin/users');
    _adminUsers = users || [];
    _populatePluginSelectors();
    _renderUsersTable(_adminUsers);
    _syncBatchToolbar();
  } catch (e) {
    toast(e.message, 'error');
  }
}

function _populatePluginSelectors() {
  if (_usersPluginsLoaded || !Array.isArray(S.plugins) || !S.plugins.length) return;
  const filterSel = document.getElementById('filter-plugin');
  const batchSel = document.getElementById('batch-plugin');

  const filterOpts = ['<option value="">所有接口插件 (All Plugins)</option>',
    ...S.plugins.map(p => `<option value="${escHtml(p.name)}">${escHtml(p.display_name || p.name)}</option>`)
  ].join('');

  const batchOpts = ['<option value="">-- 选择目标插件模块 --</option>',
    ...S.plugins.map(p => `<option value="${escHtml(p.name)}">${escHtml(p.display_name || p.name)}</option>`)
  ].join('');

  if (filterSel) filterSel.innerHTML = filterOpts;
  if (batchSel) batchSel.innerHTML = batchOpts;
  _usersPluginsLoaded = true;
}

function _renderUsersTable(users) {
  const tbody = document.querySelector('#admin-users-table tbody');
  if (!tbody) return;
  if (!users || !users.length) {
    tbody.innerHTML = '<tr><td colspan="6" class="text-muted" style="text-align:center;padding:32px">未检索到匹配的系统用户</td></tr>';
    _syncSelectAllCheckbox();
    return;
  }

  tbody.innerHTML = users.map(u => {
    const isSelected = _selectedIds.has(u.id);
    const quotaEntries = Object.entries(u.quota || {});
    let quotaSummary = '<span class="text-muted" style="font-size:11px">无配置</span>';
    if (quotaEntries.length) {
      quotaSummary = quotaEntries.slice(0, 3).map(([p, q]) => {
        const isUnlim = q.limit == null;
        const pct = isUnlim ? 0 : Math.round(((q.used || 0) / q.limit) * 100);
        const tagCls = isUnlim ? 'tag-green' : pct >= 90 ? 'tag-red' : pct >= 70 ? 'tag-amber' : 'tag-teal';
        return `<span class="tag ${tagCls}" style="margin:2px" title="${escHtml(p)}: ${q.used}/${isUnlim?'∞':q.limit}">${escHtml(p)}: ${q.used}/${isUnlim?'∞':q.limit}</span>`;
      }).join('');
      if (quotaEntries.length > 3) {
        quotaSummary += `<span class="text-muted" style="font-size:11px;margin-left:4px">+${quotaEntries.length - 3}</span>`;
      }
    }

    const roleBadge = u.is_admin ? '<span class="tag tag-cyan">ADMIN</span>' : '<span class="tag tag-slate">USER</span>';
    const banBadge = u.is_banned ? '<span class="tag tag-red">已封禁</span>' : '<span class="tag tag-green">正常</span>';

    return `
      <tr class="${isSelected ? 'selected' : ''}" style="${u.is_banned ? 'opacity:0.6' : ''}">
        <td style="text-align:center;width:40px">
          <input type="checkbox" ${isSelected ? 'checked' : ''} onchange="toggleUserSelect(${u.id}, this.checked)" style="accent-color:var(--cyan);cursor:pointer" />
        </td>
        <td style="font-family:var(--font-mono);font-size:11.5px;color:var(--text-tertiary)">#${u.id}</td>
        <td>
          <div style="font-weight:600;font-size:13.5px;color:var(--text-primary)">${escHtml(u.username)}</div>
          <div style="font-size:11px;color:var(--text-tertiary);margin-top:2px">注册于: ${fmt(u.created_at)}</div>
        </td>
        <td>${roleBadge} ${banBadge}</td>
        <td><div style="display:flex;flex-wrap:wrap;align-items:center;gap:4px">${quotaSummary}</div></td>
        <td style="text-align:right">
          <button class="btn btn-secondary btn-sm" onclick="openUserModalById(${u.id})">
            <span>配额 & 治理</span>
          </button>
        </td>
      </tr>
    `;
  }).join('');

  _syncSelectAllCheckbox();
}

function toggleUserSelect(uid, checked) {
  if (checked) _selectedIds.add(uid);
  else _selectedIds.delete(uid);
  _syncSelectAllCheckbox();
  _syncBatchToolbar();
}

function toggleSelectAll(checked) {
  const visibleUids = _getCurrentFilteredUsers().map(u => u.id);
  if (checked) {
    visibleUids.forEach(id => _selectedIds.add(id));
  } else {
    visibleUids.forEach(id => _selectedIds.delete(id));
  }
  _renderUsersTable(_getCurrentFilteredUsers());
  _syncBatchToolbar();
}

function _syncSelectAllCheckbox() {
  const cb = document.getElementById('select-all-users');
  if (!cb) return;
  const visible = _getCurrentFilteredUsers();
  if (!visible.length) {
    cb.checked = false;
    cb.indeterminate = false;
    return;
  }
  const selectedCount = visible.filter(u => _selectedIds.has(u.id)).length;
  cb.checked = selectedCount === visible.length;
  cb.indeterminate = selectedCount > 0 && selectedCount < visible.length;
}

function _syncBatchToolbar() {
  const bar = document.getElementById('batch-toolbar');
  const countEl = document.getElementById('batch-selected-count');
  if (!bar) return;
  const count = _selectedIds.size;
  if (count > 0) {
    bar.style.display = 'flex';
    if (countEl) countEl.textContent = count;
  } else {
    bar.style.display = 'none';
  }
}

function clearBatchSelection() {
  _selectedIds.clear();
  _renderUsersTable(_getCurrentFilteredUsers());
  _syncBatchToolbar();
}

function onBatchPluginChange() {
  const p = document.getElementById('batch-plugin')?.value;
  const hint = document.getElementById('batch-quota-hint');
  if (!hint) return;
  if (!p) { hint.textContent = ''; return; }
  const found = (S.plugins || []).find(x => x.name === p);
  hint.textContent = found && found.quota_default != null ? `(默认: ${found.quota_default}次)` : '(默认: 无限制)';
}

async function batchSetLimit() {
  const plugin = document.getElementById('batch-plugin')?.value;
  const raw = document.getElementById('batch-limit-val')?.value;
  if (!plugin) { toast('请先选择要调整的插件接口', 'error'); return; }
  if (!_selectedIds.size) { toast('未勾选任何用户', 'error'); return; }

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
    } catch (_) { fail++; }
  }));
  toast(`批量修改上限完成: 成功 ${ok} 人, 失败 ${fail} 人`);
  loadAdminUsers();
}

async function batchResetUsed() {
  const plugin = document.getElementById('batch-plugin')?.value;
  if (!plugin) { toast('请先选择目标插件接口', 'error'); return; }
  if (!_selectedIds.size) { toast('未勾选任何用户', 'error'); return; }

  const ids = [..._selectedIds];
  let ok = 0, fail = 0;
  await Promise.all(ids.map(async uid => {
    try {
      await apiFetch(`/api/admin/users/${uid}/reset-quota?plugin=${encodeURIComponent(plugin)}`, { method: 'POST' });
      ok++;
    } catch (_) { fail++; }
  }));
  toast(`批量归零已用计数完成: 成功 ${ok} 人, 失败 ${fail} 人`);
  loadAdminUsers();
}

function _getCurrentFilteredUsers() {
  const search = (document.getElementById('search-user')?.value || '').trim().toLowerCase();
  const plugin = document.getElementById('filter-plugin')?.value || '';
  const filterState = document.getElementById('filter-state')?.value || 'all';

  return _adminUsers.filter(u => {
    if (search && !u.username.toLowerCase().includes(search) && !String(u.id).includes(search)) return false;
    if (plugin) {
      const q = u.quota ? u.quota[plugin] : null;
      if (!q) return false;
      const isUnlim = q.limit == null;
      const pct = isUnlim ? 0 : Math.round(((q.used || 0) / q.limit) * 100);
      if (filterState === 'exhausted' && (isUnlim || pct < 100)) return false;
      if (filterState === 'warn' && (isUnlim || pct < 80)) return false;
    }
    return true;
  });
}

function applyFilter() {
  _renderUsersTable(_getCurrentFilteredUsers());
}

function clearFilter() {
  const su = document.getElementById('search-user');
  const fp = document.getElementById('filter-plugin');
  const fs = document.getElementById('filter-state');
  if (su) su.value = '';
  if (fp) fp.value = '';
  if (fs) fs.value = 'all';
  _renderUsersTable(_adminUsers);
}

function openUserModalById(id) {
  const u = _adminUsers.find(x => x.id === id);
  if (u) openUserModal(u);
}

function openUserModal(u) {
  const modal = document.getElementById('user-modal');
  if (!modal) return;
  modal.style.display = 'flex';

  document.getElementById('modal-user-title').innerHTML = `
    <span>用户配额控制 // <strong>${escHtml(u.username)}</strong></span>
    <span style="font-family:var(--font-mono);font-size:12px;color:var(--text-tertiary)">ID: #${u.id}</span>
  `;

  const rows = Object.entries(u.quota || {}).map(([plugin, { used, limit }]) => {
    return `
      <div style="display:flex;align-items:center;justify-content:space-between;padding:10px 0;border-bottom:1px solid var(--border-dim);gap:12px">
        <div style="flex:1">
          <div style="font-weight:600;font-size:13px;color:var(--text-primary)">${escHtml(plugin)}</div>
          <div style="font-size:11px;font-family:var(--font-mono);color:var(--text-tertiary);margin-top:2px">已调用: <strong style="color:var(--cyan)">${used || 0}</strong> 次</div>
        </div>
        <div style="display:flex;align-items:center;gap:8px">
          <input type="number" id="qi-${plugin}" value="${limit == null ? '' : limit}" placeholder="∞ 无限" class="form-input" style="width:90px;padding:6px 10px;font-size:12px" />
          <button class="btn btn-secondary btn-sm" onclick="setQuota(${u.id}, '${escHtml(plugin)}')">保存上限</button>
          <button class="btn btn-danger btn-sm" onclick="resetQuota(${u.id}, '${escHtml(plugin)}')">计数归零</button>
        </div>
      </div>
    `;
  }).join('');

  document.getElementById('modal-quota-rows').innerHTML = rows || '<div class="text-muted" style="padding:16px 0">该用户暂无配置任何接口配额</div>';

  const banActionBox = document.getElementById('modal-ban-zone');
  if (banActionBox) {
    banActionBox.innerHTML = u.is_banned
      ? `<div style="display:flex;align-items:center;justify-content:space-between;background:rgba(244,63,94,0.1);padding:12px 16px;border-radius:var(--radius-xs);border:1px solid var(--rose-border)">
          <div>
            <div style="color:var(--rose);font-weight:600;font-size:13px">⚠ 当前账户已处于封禁状态</div>
            <div style="font-size:11px;color:var(--text-tertiary);margin-top:2px">封禁时间: ${fmt(u.banned_at)} · 原因: ${escHtml(u.ban_reason || '管理员操作')}</div>
          </div>
          <button class="btn btn-primary btn-sm" onclick="unbanUser(${u.id})">解除封禁 (恢复默认配额)</button>
        </div>`
      : `<div style="display:flex;align-items:center;justify-content:space-between;background:rgba(0,0,0,0.25);padding:12px 16px;border-radius:var(--radius-xs);border:1px solid var(--border-dim)">
          <div>
            <div style="font-size:13px;font-weight:600;color:var(--text-secondary)">风险账户封禁治理</div>
            <div style="font-size:11px;color:var(--text-tertiary);margin-top:2px">封禁将拉黑其历史请求 IP，并将其所有接口配额上限清零</div>
          </div>
          <button class="btn btn-danger btn-sm" onclick="banUser(${u.id})">封禁此用户</button>
        </div>`;
  }
}

function closeUserModal() {
  const modal = document.getElementById('user-modal');
  if (modal) modal.style.display = 'none';
}

async function setQuota(uid, plugin) {
  const v = document.getElementById(`qi-${plugin}`)?.value;
  try {
    await apiFetch(`/api/admin/users/${uid}/quota`, {
      method: 'POST',
      body: JSON.stringify({ plugin, limit: v === '' ? null : parseInt(v, 10) })
    });
    toast('配额上限修改已生效');
    loadAdminUsers();
  } catch (e) {
    toast(e.message, 'error');
  }
}

async function resetQuota(uid, plugin) {
  try {
    await apiFetch(`/api/admin/users/${uid}/reset-quota?plugin=${encodeURIComponent(plugin)}`, { method: 'POST' });
    toast('调用计数已归零');
    loadAdminUsers();
  } catch (e) {
    toast(e.message, 'error');
  }
}

async function banUser(uid) {
  if (!confirm('确认封禁该用户？将封禁其历史关联 IP，并把其所有接口配额上限设为 0。')) return;
  try {
    const r = await apiFetch(`/api/admin/users/${uid}/ban`, {
      method: 'POST',
      body: JSON.stringify({ reason: 'Admin panel manual ban' })
    });
    toast(`已封禁：${(r.banned_ips || []).length} 个 IP，${(r.zeroed_plugins || []).length} 个接口配额归零`);
    closeUserModal();
    loadAdminUsers();
  } catch (e) {
    toast(e.message, 'error');
  }
}

async function unbanUser(uid) {
  if (!confirm('确认解封该用户？解封将把其各接口配额上限还原为系统默认值。')) return;
  try {
    await apiFetch(`/api/admin/users/${uid}/unban`, { method: 'POST' });
    toast('已解除封禁，配额已恢复系统默认值');
    closeUserModal();
    loadAdminUsers();
  } catch (e) {
    toast(e.message, 'error');
  }
}

/* ADMIN: INVITES */
async function loadAdminInvites() {
  try {
    const list = await apiFetch('/api/admin/invite/list');
    renderInvites(list || []);
  } catch (e) {
    toast(e.message, 'error');
  }
}

function renderInvites(list) {
  const el = document.getElementById('invite-list');
  if (!el) return;
  if (!list.length) {
    el.innerHTML = '<div class="text-muted" style="grid-column:1/-1;text-align:center;padding:36px">暂无任何活跃的邀请码，请在上方生成</div>';
    return;
  }

  el.innerHTML = list.map(inv => `
    <div class="code-card">
      <div style="display:flex;align-items:center;justify-content:space-between;margin-bottom:8px">
        <span class="code-val" onclick="copyText('${inv.code}', '邀请码已复制')" title="点击复制">${escHtml(inv.code)}</span>
        <button class="btn btn-danger btn-sm" onclick="deleteInvite('${inv.code}', this)">废除</button>
      </div>
      <div class="code-meta">
        <span>签发者: <strong style="color:var(--cyan)">${escHtml(inv.created_by || 'admin')}</strong></span>
        <span>生成于: ${fmt(inv.created_at)}</span>
      </div>
    </div>
  `).join('');
}

async function generateInvites() {
  const n = parseInt(document.getElementById('invite-count')?.value, 10) || 1;
  try {
    await apiFetch(`/api/admin/invite/generate?count=${n}`, { method: 'POST' });
    toast(`已成功批量签发 ${n} 个邀请码`);
    loadAdminInvites();
  } catch (e) {
    toast(e.message, 'error');
  }
}

async function deleteInvite(code, btn) {
  if (!confirm(`确认废除邀请码【${code}】？废除后用户将无法再使用该码注册。`)) return;
  try {
    await apiFetch(`/api/admin/invite/${code}`, { method: 'DELETE' });
    btn.closest('.code-card')?.remove();
    toast('邀请码已永久废除');
  } catch (e) {
    toast(e.message, 'error');
  }
}

/* ADMIN: STATS */
async function loadAdminStats() {
  try {
    const s = await apiFetch('/api/admin/stats');
    const container = document.getElementById('admin-stat-cards');
    if (container) {
      container.innerHTML = `
        <div class="stat-card">
          <div class="stat-label">注册用户总量</div>
          <div class="stat-value c-teal">${s.total_users || 0}</div>
          <div class="stat-sub">Registered Developers</div>
        </div>
        <div class="stat-card">
          <div class="stat-label">全局请求总量</div>
          <div class="stat-value c-green">${s.total_requests || 0}</div>
          <div class="stat-sub">All-time Cumulative Dispatches</div>
        </div>
        <div class="stat-card">
          <div class="stat-label">活跃接口插件数</div>
          <div class="stat-value c-cyan">${(s.by_plugin || []).length}</div>
          <div class="stat-sub">Microservice Routes in Telemetry</div>
        </div>
        <div class="stat-card">
          <div class="stat-label">调用用户数</div>
          <div class="stat-value c-amber">${(s.by_user || []).length}</div>
          <div class="stat-sub">Users with Activity History</div>
        </div>
      `;
    }

    drawLineChart(s.daily || []);
  } catch (e) {
    toast(e.message, 'error');
  }
}

function drawLineChart(daily) {
  const svg = document.getElementById('line-svg');
  if (!svg) return;
  if (!daily || !daily.length) {
    svg.innerHTML = '<text x="400" y="85" fill="#4a5568" font-size="12" text-anchor="middle" font-family="JetBrains Mono">[NO TELEMETRY DATA AVAILABLE]</text>';
    return;
  }

  const W = 800, H = 160, PX = 40, PY = 24;
  const max = Math.max(...daily.map(d => d.count), 1);
  const n = daily.length;

  const pts = daily.map((d, i) => [
    PX + (i / Math.max(n - 1, 1)) * (W - PX * 2),
    PY + (1 - d.count / max) * (H - PY * 2)
  ]);

  const pathD = pts.reduce((acc, [x, y], i) => (i === 0 ? `M ${x} ${y}` : `${acc} L ${x} ${y}`), '');
  const areaD = `${pathD} L ${pts[pts.length - 1][0]} ${H - PY} L ${pts[0][0]} ${H - PY} Z`;

  let circles = '';
  pts.forEach(([x, y], i) => {
    circles += `<circle cx="${x.toFixed(1)}" cy="${y.toFixed(1)}" r="3.5" fill="#00f0ff" stroke="#06070a" stroke-width="2">
      <title>${daily[i].day}: ${daily[i].count} 次请求</title>
    </circle>`;
  });

  svg.innerHTML = `
    <defs>
      <linearGradient id="cyber-grad" x1="0%" y1="0%" x2="0%" y2="100%">
        <stop offset="0%" stop-color="#00f0ff" stop-opacity="0.3" />
        <stop offset="100%" stop-color="#00f0ff" stop-opacity="0.0" />
      </linearGradient>
    </defs>
    <!-- Gridlines -->
    <line x1="${PX}" y1="${PY}" x2="${W - PX}" y2="${PY}" stroke="rgba(255,255,255,0.06)" stroke-dasharray="4" />
    <line x1="${PX}" y1="${H / 2}" x2="${W - PX}" y2="${H / 2}" stroke="rgba(255,255,255,0.06)" stroke-dasharray="4" />
    <line x1="${PX}" y1="${H - PY}" x2="${W - PX}" y2="${H - PY}" stroke="rgba(255,255,255,0.08)" />

    <!-- Fill & Line -->
    <path d="${areaD}" fill="url(#cyber-grad)" />
    <path d="${pathD}" fill="none" stroke="#00f0ff" stroke-width="2.2" stroke-linecap="round" stroke-linejoin="round" />
    ${circles}

    <!-- Labels -->
    <text x="${PX}" y="${H - 6}" fill="#718096" font-size="10" font-family="JetBrains Mono">${daily[0].day || ''}</text>
    <text x="${W - PX}" y="${H - 6}" fill="#718096" font-size="10" text-anchor="end" font-family="JetBrains Mono">${daily[daily.length - 1].day || ''}</text>
    <text x="${PX - 6}" y="${PY + 4}" fill="#00f0ff" font-size="10" text-anchor="end" font-family="JetBrains Mono">MAX: ${max}</text>
  `;
}

/* ADMIN: LOGS AUDIT */
let _logsOffset = 0;
const _logsLimit = 20;
let _logsAutoTimer = null;
let _logsById = {};
let _logsPluginsLoaded = false;

function _ensureLogsAutoRefresh() {
  const cb = document.getElementById('logs-auto-refresh');
  const ind = document.getElementById('logs-auto-ind');
  if (cb && cb.checked) {
    if (ind) ind.style.display = 'inline-block';
    if (!_logsAutoTimer) {
      _logsAutoTimer = setInterval(() => {
        const pageEl = document.getElementById('page-admin-logs');
        if (pageEl && pageEl.classList.contains('active')) {
          loadAdminLogs(false);
        }
      }, 8000);
    }
  } else {
    if (ind) ind.style.display = 'none';
    if (_logsAutoTimer) {
      clearInterval(_logsAutoTimer);
      _logsAutoTimer = null;
    }
  }
}

async function loadAdminLogs(resetPage = true) {
  if (resetPage) _logsOffset = 0;
  if (!_logsPluginsLoaded && Array.isArray(S.plugins)) {
    const lps = document.getElementById('logs-plugin');
    if (lps) {
      lps.innerHTML = '<option value="">所有插件接口 (All)</option>' +
        S.plugins.map(p => `<option value="${escHtml(p.name)}">${escHtml(p.display_name || p.name)}</option>`).join('');
      _logsPluginsLoaded = true;
    }
  }

  const search = (document.getElementById('logs-search')?.value || '').trim();
  const plugin = document.getElementById('logs-plugin')?.value || '';

  const qs = new URLSearchParams({
    limit: _logsLimit,
    offset: _logsOffset
  });
  if (search) qs.append('search', search);
  if (plugin) qs.append('plugin', plugin);

  try {
    const res = await apiFetch(`/api/admin/logs?${qs.toString()}`);
    _renderLogsTable(res.logs || [], res.total || 0);
  } catch (e) {
    toast(e.message, 'error');
  }
}

function _renderLogsTable(logs, total) {
  const tbody = document.querySelector('#admin-logs-table tbody');
  const countEl = document.getElementById('logs-total-count');
  const pageInfo = document.getElementById('logs-page-info');
  const prevBtn = document.getElementById('logs-prev-btn');
  const nextBtn = document.getElementById('logs-next-btn');

  if (countEl) countEl.textContent = total;
  _logsById = {};
  logs.forEach(l => { _logsById[l.id] = l; });

  if (pageInfo) {
    const curPage = Math.floor(_logsOffset / _logsLimit) + 1;
    const maxPage = Math.ceil(total / _logsLimit) || 1;
    pageInfo.textContent = `第 ${curPage} / ${maxPage} 页 (共 ${total} 条日志)`;
    if (prevBtn) prevBtn.disabled = _logsOffset <= 0;
    if (nextBtn) nextBtn.disabled = _logsOffset + _logsLimit >= total;
  }

  if (!tbody) return;
  if (!logs.length) {
    tbody.innerHTML = '<tr><td colspan="7" class="text-muted" style="text-align:center;padding:32px">未检索到匹配的请求审计日志</td></tr>';
    return;
  }

  tbody.innerHTML = logs.map(l => `
    <tr>
      <td style="font-family:var(--font-mono);font-size:11px;color:var(--text-tertiary)">#${l.id}</td>
      <td style="font-family:var(--font-mono);font-size:11.5px;color:var(--text-secondary)">${fmt(l.created_at)}</td>
      <td>
        <span style="font-weight:600;font-size:13px;color:var(--text-primary)">${escHtml(l.username || 'GUEST')}</span>
        ${l.user_banned ? '<span class="tag tag-red" style="font-size:10px;padding:1px 4px;margin-left:4px">BANNED</span>' : ''}
      </td>
      <td><span class="tag tag-teal">${escHtml(l.plugin)}</span></td>
      <td style="font-family:var(--font-mono);font-size:11.5px;max-width:200px;overflow:hidden;text-overflow:ellipsis;white-space:nowrap;color:var(--text-secondary)" title="${escHtml(l.endpoint || '')}">${escHtml(l.endpoint || '—')}</td>
      <td>${statusTag(l.status_code)}</td>
      <td style="text-align:right">
        <button class="btn btn-secondary btn-sm" onclick="openLogDetail(${l.id})">报文审计</button>
      </td>
    </tr>
  `).join('');
}

function logsPage(delta) {
  _logsOffset = Math.max(0, _logsOffset + delta * _logsLimit);
  loadAdminLogs(false);
}

function openLogDetail(id) {
  const l = _logsById[id];
  if (!l) return;

  const modal = document.getElementById('log-detail-modal');
  if (!modal) return;
  modal.style.display = 'flex';

  document.getElementById('log-modal-title').innerHTML = `
    <span>请求报文审计 // <strong>#${l.id}</strong></span>
    <span style="font-family:var(--font-mono);font-size:12px;color:var(--cyan)">${escHtml(l.plugin)} · ${escHtml(l.endpoint || '')}</span>
  `;

  document.getElementById('log-modal-body').innerHTML = `
    <div class="log-detail-grid">
      <div class="log-kv-item">
        <div class="log-kv-label">发起用户 (User)</div>
        <div class="log-kv-val">${escHtml(l.username || '游客 / GUEST')} ${l.user_id ? `(#${l.user_id})` : ''}</div>
      </div>
      <div class="log-kv-item">
        <div class="log-kv-label">客户端 IP 地址 (Client IP)</div>
        <div class="log-kv-val" style="display:flex;align-items:center;justify-content:space-between">
          <span>${escHtml(l.ip_address || '未知')}</span>
        </div>
      </div>
      <div class="log-kv-item">
        <div class="log-kv-label">HTTP 状态码 (Status)</div>
        <div class="log-kv-val">${statusTag(l.status_code)}</div>
      </div>
      <div class="log-kv-item">
        <div class="log-kv-label">请求时间 (Timestamp)</div>
        <div class="log-kv-val">${fmt(l.created_at)}</div>
      </div>
    </div>

    <!-- 用户治理快捷动作 -->
    ${l.user_id ? `
      <div style="margin-bottom:16px;display:flex;align-items:center;justify-content:space-between;background:rgba(0,0,0,0.3);padding:10px 14px;border-radius:var(--radius-xs);border:1px solid var(--border-dim)">
        <span style="font-size:12px;color:var(--text-secondary);font-family:var(--font-mono)">关联用户治理: ${escHtml(l.username)} (ID #${l.user_id})</span>
        <div>
          ${l.user_banned
            ? `<button class="btn btn-secondary btn-sm" onclick="unbanFromLog(${l.id})">解除该用户封禁</button>`
            : `<button class="btn btn-danger btn-sm" onclick="banFromLog(${l.id})">封禁此用户及其 IP</button>`}
        </div>
      </div>
    ` : ''}

    <div style="margin-bottom:12px">
      <div style="font-size:11px;font-family:var(--font-mono);color:var(--text-tertiary);margin-bottom:4px">请求载荷报文 (REQUEST PAYLOAD)</div>
      <pre style="background:var(--bg-canvas);border:1px solid var(--border-dim);border-radius:var(--radius-xs);padding:12px;font-family:var(--font-mono);font-size:12px;color:var(--text-secondary);max-height:180px;overflow:auto;margin:0">${escHtml(l.request_body || '[No Payload Body]')}</pre>
    </div>

    <div>
      <div style="font-size:11px;font-family:var(--font-mono);color:var(--text-tertiary);margin-bottom:4px">响应数据摘要 (RESPONSE SUMMARY)</div>
      <pre style="background:var(--bg-canvas);border:1px solid var(--border-dim);border-radius:var(--radius-xs);padding:12px;font-family:var(--font-mono);font-size:12px;color:var(--text-secondary);max-height:180px;overflow:auto;margin:0">${escHtml(l.response_body || '[No Response Body Logged]')}</pre>
    </div>
  `;
}

function closeLogDetailModal() {
  const modal = document.getElementById('log-detail-modal');
  if (modal) modal.style.display = 'none';
}

async function banFromLog(id) {
  const l = _logsById[id];
  if (!l || !l.user_id) return;
  if (!confirm(`确认封禁用户【${l.username}】？\n将封禁该 IP（${l.ip_address}）及历史关联 IP，并把该用户所有接口配额清零。`)) return;
  try {
    const r = await apiFetch(`/api/admin/users/${l.user_id}/ban`, {
      method: 'POST',
      body: JSON.stringify({ reason: 'banned from request logs', ip: l.ip_address })
    });
    toast(`已封禁 ${l.username}：${(r.banned_ips || []).length} 个 IP，${(r.zeroed_plugins || []).length} 个接口配额归零`);
    closeLogDetailModal();
    loadAdminLogs(false);
  } catch (e) {
    toast(e.message, 'error');
  }
}

async function unbanFromLog(id) {
  const l = _logsById[id];
  if (!l || !l.user_id) return;
  if (!confirm(`解封用户【${l.username}】？将释放关联 IP 封禁，并将各接口配额还原为系统默认值。`)) return;
  try {
    await apiFetch(`/api/admin/users/${l.user_id}/unban`, { method: 'POST' });
    toast(`已成功解封用户 ${l.username}`);
    closeLogDetailModal();
    loadAdminLogs(false);
  } catch (e) {
    toast(e.message, 'error');
  }
}

async function purgeLogsPrompt() {
  const daysStr = prompt('请输入要保留的天数（早于该天数的请求日志将被彻底清除以释放存储）：', '3');
  if (daysStr === null) return;
  const days = parseInt(daysStr, 10);
  if (isNaN(days) || days < 0) {
    alert('请输入有效的非负整数天数');
    return;
  }
  if (!confirm(`确认永久清理 ${days} 天前的历史审计日志？此操作无法撤销。`)) return;
  try {
    const res = await apiFetch('/api/admin/logs/purge', {
      method: 'POST',
      body: JSON.stringify({ days })
    });
    toast(`日志清理完毕：已释放 ${res.purged_access_logs || 0} 条历史记录`);
    loadAdminLogs(true);
  } catch (e) {
    toast(e.message, 'error');
  }
}
