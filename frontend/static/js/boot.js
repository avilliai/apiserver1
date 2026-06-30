/* Apollodorus 前端 — 由 index.html 拆分而来；所有文件共享全局作用域，按 index.html 中的顺序加载。 */
/* BOOTSTRAP */
(async () => {
  if (S.token) {
    // 校验 token，顺便刷新用户信息（含 is_admin）
    try {
      const me = await apiFetch('/api/user/me');
      S.user = { username: me.username, is_admin: me.is_admin };
      localStorage.setItem('gw_user', JSON.stringify(S.user));
    } catch(_) {
      S.token = null; S.user = null;
      localStorage.removeItem('gw_token'); localStorage.removeItem('gw_user');
    }
  }
  await initApp();
  goPage(S.token && S.user ? 'dashboard' : 'home');
})();

document.addEventListener('keydown', e => {
  if (e.key !== 'Enter') return;
  const ap = document.getElementById('page-auth');
  if (!ap || !ap.classList.contains('active')) return;
  if (document.getElementById('register-form').style.display !== 'none') doRegister();
  else doLogin();
});
