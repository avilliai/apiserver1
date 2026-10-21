/* Apollodorus 2.0 // Application Controller, Routing & Navigation */

const PUBLIC_PAGES = new Set(['home', 'auth']);
let currentHubCategory = 'all';

function pageNeedsAuth(name) {
  return !PUBLIC_PAGES.has(name) && !name.startsWith('plugin-');
}

async function initApp() {
  try {
    S.plugins = await apiFetch('/api/plugins');
  } catch (_) {
    S.plugins = [];
  }

  if (S.token && S.user) {
    try {
      S.userKeys = await apiFetch('/api/user/apikeys');
    } catch (_) {
      S.userKeys = [];
    }
  } else {
    S.userKeys = [];
  }

  buildPluginPages();
  renderHomeHub();
  renderNav();

  const loggedIn = !!(S.token && S.user);
  const cta = document.getElementById('home-cta');
  if (cta) cta.style.display = loggedIn ? 'none' : '';
}

function renderNav() {
  const loggedIn = !!(S.token && S.user);
  const links = document.getElementById('nav-links');
  const auth = document.getElementById('nav-auth');

  const items = [
    ['home', '接口市场', '01']
  ];

  if (loggedIn) {
    items.push(
      ['dashboard', '控制台', '02'],
      ['apikeys', 'API 密钥', '03'],
      ['usage', '用量审计', '04']
    );
    if (S.user.is_admin) {
      items.push(['admin-users', '管理终端', '05']);
    }
  }

  if (links) {
    links.innerHTML = items.map(([page, label, num]) =>
      `<span class="nav-link" data-page="${page}" onclick="goPage('${page}')">
        <span class="nav-link-num">${num}</span>
        <span>${label}</span>
      </span>`
    ).join('');
  }

  if (auth) {
    auth.innerHTML = loggedIn
      ? `<div class="nav-user">
          <span class="pulse-dot"></span>
          <span style="font-weight:600;font-size:13px">${escHtml(S.user.username)}</span>
          <span class="nav-user-badge ${S.user.is_admin ? 'admin' : ''}">${S.user.is_admin ? 'ADMIN' : 'DEV'}</span>
         </div>
         <button class="btn btn-secondary btn-sm" onclick="doLogout()">登出</button>`
      : `<button class="btn btn-primary btn-sm" onclick="goPage('auth')">登录 / 注册</button>`;
  }
}

function goPage(page) {
  if (pageNeedsAuth(page) && !(S.token && S.user)) {
    toast('访问该模块需要先登录网关通行证', 'error');
    switchTab('login');
    page = 'auth';
  }

  const navMenu = document.getElementById('navMenu');
  if (navMenu) navMenu.classList.remove('is-open');

  document.querySelectorAll('.page').forEach(p => p.classList.remove('active'));

  const target = document.getElementById(`page-${page}`);
  if (target) {
    target.classList.add('active');
    window.scrollTo({ top: 0, behavior: 'smooth' });
  }

  document.querySelectorAll('.nav-link').forEach(l => {
    l.classList.toggle('active', l.dataset.page === page);
  });

  const isAdmin = page.startsWith('admin-');
  const subnav = document.getElementById('admin-subnav');
  if (subnav) {
    if (isAdmin && S.user && S.user.is_admin) {
      subnav.style.display = 'flex';
      subnav.classList.add('show');
      subnav.querySelectorAll('.pill').forEach(p => {
        p.classList.toggle('active', p.dataset.page === page);
      });
      document.querySelectorAll('.nav-link[data-page="admin-users"]').forEach(el => el.classList.add('active'));
    } else {
      subnav.style.display = 'none';
      subnav.classList.remove('show');
    }
  }

  switch(page) {
    case 'dashboard':
      loadDashboard();
      break;
    case 'usage':
      loadUsage();
      break;
    case 'apikeys':
      loadApiKeys();
      break;
    case 'admin-users':
      loadAdminUsers();
      break;
    case 'admin-invites':
      loadAdminInvites();
      break;
    case 'admin-stats':
      loadAdminStats();
      break;
    case 'admin-logs':
      loadAdminLogs();
      break;
  }
}

function setHubCategory(cat, btnEl) {
  currentHubCategory = cat || 'all';
  document.querySelectorAll('.cat-chip').forEach(el => el.classList.remove('active'));
  if (btnEl) btnEl.classList.add('active');
  applyHubFilter();
}

function filterHubCards(query) {
  applyHubFilter();
}

function clearHubSearch() {
  const inp = document.getElementById('hub-search');
  if (inp) {
    inp.value = '';
    applyHubFilter();
    inp.focus();
  }
}

function applyHubFilter() {
  const query = (document.getElementById('hub-search')?.value || '').toLowerCase().trim();
  const cards = document.querySelectorAll('.hub-card');
  let matchCount = 0;
  cards.forEach(card => {
    const text = (card.dataset.searchText || '').toLowerCase();
    const cat = card.dataset.category || 'all';
    const matchCat = (currentHubCategory === 'all') || (cat === currentHubCategory);
    const matchText = !query || text.includes(query);
    const show = matchCat && matchText;
    card.style.display = show ? 'flex' : 'none';
    if (show) matchCount++;
  });

  const countEl = document.getElementById('hub-match-count');
  if (countEl) {
    countEl.innerText = `已展示 ${matchCount} 个微服务接口`;
  }
}

function toggleNavMenu() {
  const m = document.getElementById('navMenu');
  if (m) m.classList.toggle('is-open');
}
