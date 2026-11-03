/* VC STAR — login da staff (Supabase Auth) + troca obrigatória de password no 1.º acesso. */
(function () {
  'use strict';

  // Chave PÚBLICA por natureza (publishable): só dá acesso ao que as regras RLS permitem.
  var SUPABASE_URL = 'https://hwlczaoytcpnlchcqtmm.supabase.co';
  var SUPABASE_KEY = 'sb_publishable_IXQAgFLGY1VPApuKABsp1g_YguGUW-I';
  var EMAIL_DOMAIN = '@staff.vcstar.app';
  var INITIAL_PASSWORD = '123456';
  var MIN_LENGTH = 8;

  var $ = function (id) { return document.getElementById(id); };
  var sb = null;
  window.VCSTAR = window.VCSTAR || {};

  function show(view) {
    $('auth').hidden = !view;
    $('auth-login').hidden = view !== 'login';
    $('auth-change').hidden = view !== 'change';
    $('auth-loading').hidden = view !== 'loading';
    document.body.classList.toggle('locked', !!view);
  }

  function setError(id, msg) {
    var el = $(id);
    el.textContent = msg || '';
    el.hidden = !msg;
  }

  function busy(btn, on, label) {
    btn.disabled = on;
    if (label) btn.textContent = label;
  }

  async function loadProfile() {
    var res = await sb.from('staff_profiles').select('username, role, must_change_password')
      .eq('id', (await sb.auth.getUser()).data.user.id).maybeSingle();
    if (res.error) throw res.error;
    return res.data;
  }

  async function route() {
    var session = (await sb.auth.getSession()).data.session;
    if (!session) { show('login'); return; }
    show('loading');
    var profile;
    try {
      profile = await loadProfile();
    } catch (e) {
      show('login');
      setError('login-error', 'Não foi possível validar a sessão. Verifica a ligação e tenta de novo.');
      return;
    }
    if (!profile) {
      await sb.auth.signOut();
      show('login');
      setError('login-error', 'Esta conta não pertence à staff VC STAR.');
      return;
    }
    window.VCSTAR.user = profile;
    if (profile.must_change_password) {
      $('change-user').textContent = profile.username + ' · ' + profile.role;
      show('change');
      $('new-pass').focus();
      return;
    }
    show(null);
    renderSession(profile);
    window.VCSTAR.ready = true;
    window.dispatchEvent(new Event('vcstar:ready'));
  }

  function renderSession(profile) {
    var box = $('session');
    if (!box) return;
    box.hidden = false;
    $('session-user').textContent = profile.username + ' · ' + profile.role;
    loadStaff();
  }

  async function loadStaff() {
    var list = $('staff-list');
    if (!list) return;
    var res = await sb.from('staff_profiles').select('username, role').order('created_at');
    if (res.error || !res.data) return;
    list.textContent = '';
    res.data.forEach(function (p) {
      var li = document.createElement('li');
      var b = document.createElement('strong');
      b.textContent = p.username;
      li.appendChild(b);
      li.appendChild(document.createTextNode(' — ' + p.role));
      list.appendChild(li);
    });
  }

  async function onLogin(e) {
    e.preventDefault();
    setError('login-error', '');
    var user = $('login-user').value.trim();
    var pass = $('login-pass').value;
    if (!user || !pass) { setError('login-error', 'Escreve o utilizador e a password.'); return; }
    var btn = $('login-btn');
    busy(btn, true, 'A entrar…');
    var res = await sb.auth.signInWithPassword({ email: user.toLowerCase() + EMAIL_DOMAIN, password: pass });
    busy(btn, false, 'Entrar');
    if (res.error) {
      setError('login-error', /invalid/i.test(res.error.message) ? 'Utilizador ou password errados.'
        : 'Erro ao entrar: ' + res.error.message);
      return;
    }
    $('login-pass').value = '';
    route();
  }

  async function onChange(e) {
    e.preventDefault();
    setError('change-error', '');
    var p1 = $('new-pass').value, p2 = $('new-pass2').value;
    if (p1.length < MIN_LENGTH) { setError('change-error', 'A password nova tem de ter pelo menos ' + MIN_LENGTH + ' caracteres.'); return; }
    if (p1 === INITIAL_PASSWORD || /^(\d)\1+$|^12345678?9?$/.test(p1)) { setError('change-error', 'Escolhe uma password diferente da inicial e menos óbvia.'); return; }
    if (p1 !== p2) { setError('change-error', 'As duas passwords não são iguais.'); return; }
    var btn = $('change-btn');
    busy(btn, true, 'A guardar…');
    var res = await sb.auth.updateUser({ password: p1 });
    busy(btn, false, 'Guardar e continuar');
    if (res.error) { setError('change-error', 'Não foi possível guardar: ' + res.error.message); return; }
    $('new-pass').value = $('new-pass2').value = '';
    route();
  }

  async function logout() {
    await sb.auth.signOut();
    location.hash = '';
    location.reload();
  }

  function init() {
    if (!window.supabase || !window.supabase.createClient) {
      show('login');
      setError('login-error', 'Não foi possível carregar o módulo de login.');
      return;
    }
    sb = window.supabase.createClient(SUPABASE_URL, SUPABASE_KEY, {
      auth: { persistSession: true, autoRefreshToken: true, storageKey: 'vcstar-auth' }
    });
    window.VCSTAR.sb = sb;
    $('auth-login').addEventListener('submit', onLogin);
    $('auth-change').addEventListener('submit', onChange);
    $('change-logout').addEventListener('click', logout);
    var out = $('logout-btn');
    if (out) out.addEventListener('click', logout);
    show('loading');
    route();
  }

  init();
})();
