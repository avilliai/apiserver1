/* Apollodorus 2.0 // Authentication & Session */

function switchTab(t) {
  ['login', 'register'].forEach(x => {
    const tabEl = document.getElementById(`tab-${x}`);
    const formEl = document.getElementById(`${x}-form`);
    if (tabEl) tabEl.classList.toggle('active', x === t);
    if (formEl) formEl.style.display = x === t ? '' : 'none';
  });
  const lErr = document.getElementById('login-err');
  const rErr = document.getElementById('reg-err');
  if (lErr) lErr.textContent = '';
  if (rErr) rErr.textContent = '';
}

async function doLogin() {
  const username = document.getElementById('login-user').value.trim();
  const password = document.getElementById('login-pass').value;
  const errEl = document.getElementById('login-err');
  if (!username || !password) {
    toast('请输入用户名与密码', 'error');
    if (errEl) errEl.textContent = '请输入用户名与密码';
    return;
  }
  if (errEl) errEl.textContent = '';
  try {
    const res = await apiFetch('/api/auth/login', {
      method: 'POST',
      body: JSON.stringify({ username, password })
    });
    saveSession(res);
    await initApp();
    goPage('dashboard');
    toast(`欢迎回来，开发者 ${res.username}`);
  } catch(e) {
    const msg = e.message || '登录失败，请核对凭证';
    toast(msg, 'error');
    if (errEl) errEl.textContent = msg;
  }
}

async function doRegister() {
  const username = document.getElementById('reg-user').value.trim();
  const password = document.getElementById('reg-pass').value;
  const invite_code = document.getElementById('reg-invite').value.trim();
  const errEl = document.getElementById('reg-err');
  if (!username || !password) {
    toast('请输入用户名与密码', 'error');
    if (errEl) errEl.textContent = '请输入用户名与密码';
    return;
  }
  if (!invite_code) {
    toast('请输入通行邀请码', 'error');
    if (errEl) errEl.textContent = '请输入通行邀请码';
    return;
  }
  if (errEl) errEl.textContent = '';
  try {
    const res = await apiFetch('/api/auth/register', {
      method: 'POST',
      body: JSON.stringify({ username, password, invite_code })
    });
    saveSession(res);
    await initApp();
    goPage('dashboard');
    toast(`注册成功，已接入网关终端`);
  } catch(e) {
    const msg = e.message || '注册失败';
    toast(msg, 'error');
    if (errEl) errEl.textContent = msg;
  }
}

function saveSession(data) {
  S.token = data.access_token;
  S.user = { username: data.username, is_admin: data.is_admin };
  localStorage.setItem('gw_token', S.token);
  localStorage.setItem('gw_user', JSON.stringify(S.user));
}

function doLogout() {
  S.token = null;
  S.user = null;
  S.userKeys = [];
  localStorage.removeItem('gw_token');
  localStorage.removeItem('gw_user');
  buildPluginPages();
  renderNav();
  const cta = document.getElementById('home-cta');
  if (cta) cta.style.display = '';
  goPage('home');
  toast('已安全登出终端');
}
