/* Apollodorus 2.0 // Bootstrap & Event Bus */

(async () => {
  if (S.token) {
    try {
      const me = await apiFetch('/api/user/me');
      S.user = { username: me.username, is_admin: me.is_admin };
      localStorage.setItem('gw_user', JSON.stringify(S.user));
    } catch (_) {
      S.token = null;
      S.user = null;
      localStorage.removeItem('gw_token');
      localStorage.removeItem('gw_user');
    }
  }

  await initApp();
  goPage(S.token && S.user ? 'dashboard' : 'home');
})();

document.addEventListener('keydown', e => {
  if (e.key !== 'Enter') return;
  const ap = document.getElementById('page-auth');
  if (!ap || !ap.classList.contains('active')) return;
  const regForm = document.getElementById('register-form');
  if (regForm && regForm.style.display !== 'none') {
    doRegister();
  } else {
    doLogin();
  }
});
