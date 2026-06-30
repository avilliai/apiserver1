/* Apollodorus 前端 — 由 index.html 拆分而来；所有文件共享全局作用域，按 index.html 中的顺序加载。 */
/* APP INIT — public-aware: 游客也能浏览接口 hub，仅控制台/调试需登录 */
async function initApp() {
  try { S.plugins = await apiFetch('/api/plugins'); } catch(_) { S.plugins = []; }
  buildPluginPages();
  renderHomeHub();
  renderNav();
  const loggedIn = !!(S.token && S.user);
  const cta = document.getElementById('home-cta');
  if (cta) cta.style.display = loggedIn ? 'none' : '';
}

/* 顶栏导航随登录态切换 */
function renderNav() {
  const loggedIn = !!(S.token && S.user);
  const links = document.getElementById('nav-links');
  const auth  = document.getElementById('nav-auth');
  const items = [['home','首页']];
  if (loggedIn) {
    items.push(['dashboard','概览'], ['apikeys','API 密钥'], ['usage','用量']);
    if (S.user.is_admin) items.push(['admin-users','管理']);
  }
  links.innerHTML = items.map(([page,label]) =>
    `<span class="nav-link" data-page="${page}" onclick="goPage('${page}')">${label}</span>`).join('');
  auth.innerHTML = loggedIn
    ? `<span class="nav-user">${escHtml(S.user.username)}${S.user.is_admin?' · admin':''}</span><span class="nav-btn" onclick="doLogout()">退出</span>`
    : `<span class="nav-btn" onclick="goPage('auth')">登录</span><span class="nav-btn primary" onclick="switchTab('register');goPage('auth')">注册</span>`;
}

/* 首页接口卡（由后端 /api/plugins 自动生成） */
function renderHomeHub() {
  const el = document.getElementById('home-hub');
  if (!el) return;
  if (!S.plugins.length) { el.innerHTML = '<div class="text-muted">暂无可用接口</div>'; return; }
  const icons = ['❀','♪','✦','❖','✺','◈','❉','✿','♢','✲'];
  el.innerHTML = S.plugins.map((p,i) => `
    <div class="hub-card" onclick="goPage('plugin-${p.name}')">
      <div class="hub-icon">${icons[i % icons.length]}</div>
      <h3>${escHtml(p.display_name||p.name)}</h3>
      <p>${escHtml(p.description||'')}</p>
      <div class="hub-foot">
        <span class="hub-go">查看详情 →</span>
        ${p.quota_default!=null ? `<span class="hub-quota">配额 ${p.quota_default}RPD/key</span>` : ''}
      </div>
    </div>`).join('');
}

/* 为每个插件构建/刷新详情页（刷新以便登录态变化时重新渲染调试面板门禁） */
function buildPluginPages() {
  const main = document.getElementById('main');
  S.plugins.forEach(p => {
    let pg = document.getElementById(`page-plugin-${p.name}`);
    if (!pg) { pg = document.createElement('div'); pg.className = 'page'; pg.id = `page-plugin-${p.name}`; main.appendChild(pg); }
    pg.innerHTML = buildPluginPage(p);
  });
}
