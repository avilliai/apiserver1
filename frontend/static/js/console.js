/* Apollodorus 2.0 // User Console, Dashboard & Keys */

function renderQuota(elId, quotaMap) {
  const el = document.getElementById(elId);
  if (!el) return;
  const entries = Object.entries(quotaMap || {});
  if (!entries.length) {
    el.innerHTML = '<div class="text-muted" style="padding:16px 0">暂无接口配额数据</div>';
    return;
  }

  el.innerHTML = entries.map(([plugin, { used, limit }]) => {
    const isUnlimited = limit == null;
    const pct = isUnlimited ? 0 : Math.min(100, Math.round(((used || 0) / limit) * 100));
    const cls = pct >= 90 ? 'danger' : pct >= 70 ? 'warn' : '';

    return `
      <div class="quota-item">
        <div class="quota-header">
          <div style="display:flex;align-items:center;gap:8px">
            <span class="quota-name">${escHtml(plugin)}</span>
            ${isUnlimited ? '<span class="tag tag-green">无限配额</span>' : `<span class="tag ${pct>=90?'tag-red':pct>=70?'tag-amber':'tag-teal'}">${pct}%</span>`}
          </div>
          <span class="quota-count">
            ${isUnlimited
              ? `<span class="quota-unlimited">∞ 无限 · 已用 ${used || 0} 次</span>`
              : `<strong>${used || 0}</strong> / ${limit} 次`}
          </span>
        </div>
        <div class="quota-track">
          <div class="quota-bar ${cls}" style="width: ${isUnlimited ? (used > 0 ? 100 : 0) : pct}%"></div>
        </div>
      </div>
    `;
  }).join('');
}

/* DASHBOARD */
async function loadDashboard() {
  try {
    const d = await apiFetch('/api/user/usage');
    const quotaKeys = Object.keys(d.quota || {});
    let totalUsed = 0;
    quotaKeys.forEach(k => {
      totalUsed += (d.quota[k].used || 0);
    });

    const statGrid = document.getElementById('dash-stat-grid');
    if (statGrid) {
      statGrid.innerHTML = `
        <div class="stat-card">
          <div class="stat-label">今日调用总量</div>
          <div class="stat-value c-teal">${totalUsed}</div>
          <div class="stat-sub">Total Dispatched Calls</div>
        </div>
        <div class="stat-card">
          <div class="stat-label">已启用网关接口</div>
          <div class="stat-value c-green">${quotaKeys.length}</div>
          <div class="stat-sub">Enabled Microservice Routes</div>
        </div>
        <div class="stat-card">
          <div class="stat-label">最近访问流水日志</div>
          <div class="stat-value c-amber">${(d.recent_logs || []).length}</div>
          <div class="stat-sub">Recent Stream Logs</div>
        </div>
      `;
    }

    renderQuota('dash-quota', d.quota);

    const tbody = document.querySelector('#dash-recent tbody');
    if (tbody) {
      if (!d.recent_logs || !d.recent_logs.length) {
        tbody.innerHTML = '<tr><td colspan="4" class="text-muted" style="text-align:center;padding:24px">暂无请求记录</td></tr>';
      } else {
        tbody.innerHTML = d.recent_logs.slice(0, 8).map(l => `
          <tr>
            <td><span class="tag tag-teal">${escHtml(l.plugin)}</span></td>
            <td style="color:var(--text-secondary);font-family:var(--font-mono);font-size:11.5px;max-width:180px;overflow:hidden;text-overflow:ellipsis;white-space:nowrap" title="${escHtml(l.endpoint || '')}">${escHtml(l.endpoint || '—')}</td>
            <td>${statusTag(l.status_code)}</td>
            <td style="color:var(--text-tertiary);font-family:var(--font-mono);font-size:11px">${fmt(l.created_at)}</td>
          </tr>
        `).join('');
      }
    }
  } catch(e) {
    toast(e.message, 'error');
  }
}

/* MY USAGE */
async function loadUsage() {
  try {
    const d = await apiFetch('/api/user/usage');
    renderQuota('usage-quota', d.quota);

    const tbody = document.querySelector('#usage-logs tbody');
    if (tbody) {
      if (!d.recent_logs || !d.recent_logs.length) {
        tbody.innerHTML = '<tr><td colspan="5" class="text-muted" style="text-align:center;padding:28px">暂无详细调用记录</td></tr>';
      } else {
        tbody.innerHTML = d.recent_logs.map(l => `
          <tr>
            <td style="color:var(--text-tertiary);font-family:var(--font-mono);font-size:11px">#${l.id}</td>
            <td><span class="tag tag-teal">${escHtml(l.plugin)}</span></td>
            <td style="color:var(--text-secondary);font-family:var(--font-mono);font-size:11.5px;max-width:240px;overflow:hidden;text-overflow:ellipsis;white-space:nowrap" title="${escHtml(l.endpoint || '')}">${escHtml(l.endpoint || '—')}</td>
            <td>${statusTag(l.status_code)}</td>
            <td style="color:var(--text-tertiary);font-family:var(--font-mono);font-size:11px">${fmt(l.created_at)}</td>
          </tr>
        `).join('');
      }
    }
  } catch(e) {
    toast(e.message, 'error');
  }
}

/* API KEYS */
async function loadApiKeys() {
  try {
    const keys = await apiFetch('/api/user/apikeys');
    S.userKeys = keys || [];
    renderKeyList(S.userKeys);
  } catch(e) {
    toast(e.message, 'error');
  }
}

function renderKeyList(keys) {
  const el = document.getElementById('key-list');
  if (!el) return;
  if (!keys.length) {
    el.innerHTML = '<div class="text-muted" style="padding:20px 0">尚未生成 API Key，请点击上方创建您的首个访问令牌</div>';
    return;
  }

  el.innerHTML = keys.map(k => `
    <div class="key-row">
      <div class="key-dot" title="Active"></div>
      <div class="key-name">${escHtml(k.name || 'API Key')}</div>
      <div class="key-prefix" title="点击复制前缀" onclick="copyText('${k.key_prefix}', '前缀已复制')">${escHtml(k.key_prefix)}…</div>
      <div class="key-date">最后使用: ${fmt(k.last_used_at)}</div>
      <div class="key-date">创建于: ${fmt(k.created_at)}</div>
      <button class="btn btn-danger btn-sm" onclick="revokeKey(${k.id}, '${escHtml(k.name || '')}')">吊销</button>
    </div>
  `).join('');
}

async function createApiKey() {
  const nameInp = document.getElementById('new-key-name');
  const name = (nameInp.value || '').trim() || 'Default Key';

  try {
    const data = await apiFetch('/api/user/apikeys', {
      method: 'POST',
      body: JSON.stringify({ name })
    });

    const reveal = document.getElementById('new-key-reveal');
    if (reveal) {
      reveal.style.display = 'block';
      reveal.innerHTML = `
        <div class="key-reveal-box">
          <div class="key-reveal-label">⚡ 密钥已生成 · 请立即完整复制并妥善保存</div>
          <div class="key-reveal-value" onclick="copyText('${data.key}', 'API Key 完整密钥已复制')" title="点击一键复制">${data.key}</div>
          <div class="key-reveal-warn">⚠ 该密钥仅在当前生成时显示一次，关闭页面后将不可再查，请妥善保存至您的生产环境 .env 配置文件中。</div>
        </div>
      `;
    }

    nameInp.value = '';
    toast('API Key 创建成功');
    loadApiKeys();
  } catch(e) {
    toast(e.message, 'error');
  }
}

async function revokeKey(id, name) {
  if (!confirm(`确认要吊销此密钥【${name || '#' + id}】吗？\n吊销后所有使用该 Key 的生产环境 API 请求将立即失效！`)) return;
  try {
    await apiFetch(`/api/user/apikeys/${id}`, { method: 'DELETE' });
    toast('API Key 已永久吊销');
    loadApiKeys();
  } catch(e) {
    toast(e.message, 'error');
  }
}
