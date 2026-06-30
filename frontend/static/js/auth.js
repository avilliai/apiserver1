/* Apollodorus 前端 — 由 index.html 拆分而来；所有文件共享全局作用域，按 index.html 中的顺序加载。 */
/* AUTH */
function switchTab(t) {['login','register'].forEach(x => {
    document.getElementById(`tab-${x}`).classList.toggle('active', x===t);
    document.getElementById(`${x}-form`).style.display = x===t ? '' : 'none';
  });
}
async function doLogin() {
  const username = document.getElementById('login-user').value.trim();
  const password = document.getElementById('login-pass').value;
  document.getElementById('login-err').textContent = '';
  try { saveSession(await apiFetch('/api/auth/login', { method:'POST', body: JSON.stringify({username,password}) })); await initApp(); goPage('dashboard'); toast('登录成功'); }
  catch(e) { document.getElementById('login-err').textContent = e.message; }
}
async function doRegister() {
  const username    = document.getElementById('reg-user').value.trim();
  const password    = document.getElementById('reg-pass').value;
  const invite_code = document.getElementById('reg-invite').value.trim();
  document.getElementById('reg-err').textContent = '';
  try { saveSession(await apiFetch('/api/auth/register', { method:'POST', body: JSON.stringify({username,password,invite_code}) })); await initApp(); goPage('dashboard'); toast('注册成功'); }
  catch(e) { document.getElementById('reg-err').textContent = e.message; }
}
function saveSession(data) {
  S.token = data.access_token;
  S.user  = { username: data.username, is_admin: data.is_admin };
  localStorage.setItem('gw_token', S.token);
  localStorage.setItem('gw_user', JSON.stringify(S.user));
}
function doLogout() {
  S.token = S.user = null;
  localStorage.removeItem('gw_token'); localStorage.removeItem('gw_user');
  buildPluginPages();   // 重渲染插件页，移除已登录态下的在线调试面板
  renderNav();
  const cta = document.getElementById('home-cta'); if (cta) cta.style.display = '';
  goPage('home');
  toast('已退出登录');
}
