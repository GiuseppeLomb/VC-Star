/* GTA6 RP Radar — vanilla JS, no build step. */
(function () {
  'use strict';

  var isNative = !!(window.Capacitor && typeof window.Capacitor.isNativePlatform === 'function' &&
    window.Capacitor.isNativePlatform());
  var remoteMeta = document.querySelector('meta[name="radar-remote"]');
  // In the Android app the data always comes from the public Pages URL (never the bundled copy).
  var BASE = isNative && remoteMeta ? remoteMeta.content : './';

  var URGENT = ['rp', 'online', 'servidores', 'creator'];
  var TOPIC_LABEL = { rp: 'RP', servidores: 'Servidores', creator: 'Criadores', online: 'Online', pc: 'PC', trailer: 'Trailer', data: 'Data' };
  var TAGS = {
    OFICIAL: { text: '🟢 OFICIAL', cls: 'oficial' },
    CREDIVEL: { text: '🟡 CREDÍVEL', cls: 'credivel' },
    RUMOR: { text: '⚪ RUMOR', cls: 'rumor' }
  };
  var FILTERS = {
    all: function () { return true; },
    rp: function (it) { return (it.topics || []).some(function (t) { return URGENT.indexOf(t) !== -1; }); },
    oficial: function (it) { return it.tag === 'OFICIAL'; },
    credivel: function (it) { return it.tag === 'CREDIVEL'; },
    rumor: function (it) { return it.tag === 'RUMOR'; },
    pt: function (it) { return it.lang === 'pt'; }
  };
  var PAGE = 60;
  var PIN_DAYS = 30;
  var REFRESH_MS = 2 * 60 * 1000;
  var LAST_VISIT_KEY = 'radar:lastVisit';

  var state = { items: [], health: null, updatedAt: null, filter: 'rp', query: '', shown: PAGE, prevVisit: null, loaded: false };
  var $ = function (id) { return document.getElementById(id); };

  // ------------------------------------------------------------------ storage (may be unavailable)
  function store(key, value) {
    try {
      if (value === undefined) return window.localStorage.getItem(key);
      window.localStorage.setItem(key, value);
    } catch (e) { /* private mode / blocked storage: ignore */ }
    return null;
  }

  // ------------------------------------------------------------------ helpers
  function parseTime(s) { var t = Date.parse(s || ''); return isNaN(t) ? null : t; }

  function ago(ts) {
    if (ts == null) return '—';
    var s = Math.max(0, (Date.now() - ts) / 1000);
    if (s < 60) return 'agora';
    var m = Math.floor(s / 60);
    if (m < 60) return 'há ' + m + ' min';
    var h = Math.floor(m / 60);
    if (h < 24) return 'há ' + h + ' h';
    var d = Math.floor(h / 24);
    if (d < 7) return 'há ' + d + (d === 1 ? ' dia' : ' dias');
    return new Date(ts).toLocaleDateString('pt-PT', { day: 'numeric', month: 'short', year: d > 300 ? 'numeric' : undefined });
  }

  function safeUrl(u) { return /^https?:\/\//i.test(u || '') ? u : '#'; }

  function fold(s) {
    return (s || '').toLowerCase().normalize('NFD').replace(/[̀-ͯ]/g, '');
  }

  function isPinned(it) {
    if (it.tag !== 'OFICIAL') return false;
    var hot = (it.topics || []).some(function (t) { return URGENT.indexOf(t) !== -1; });
    var t = parseTime(it.published);
    return hot && t != null && Date.now() - t < PIN_DAYS * 864e5;
  }

  function isNew(it) {
    if (state.prevVisit == null) return false;
    var t = parseTime(it.fetched);
    return t != null && t > state.prevVisit;
  }

  // ------------------------------------------------------------------ data
  function getJSON(path) {
    var url = BASE + path + '?t=' + Date.now();
    return fetch(url, { cache: 'no-store' })
      .then(function (r) { if (!r.ok) throw new Error('HTTP ' + r.status); return r.json(); })
      .catch(function () {
        if (!isNative) return null;
        // Offline in the app: fall back to the copy bundled in the APK.
        return fetch('./' + path).then(function (r) { return r.ok ? r.json() : null; }).catch(function () { return null; });
      });
  }

  function load() {
    return Promise.all([getJSON('data/news.json'), getJSON('data/health.json')]).then(function (res) {
      var news = res[0], health = res[1];
      if (news && Array.isArray(news.items)) state.items = news.items;
      if (health) state.health = health;
      var times = [news && parseTime(news.generated_at), health && parseTime(health.generated_at)].filter(function (x) { return x != null; });
      state.updatedAt = times.length ? Math.max.apply(null, times) : null;
      state.loaded = true;
      render();
    });
  }

  // ------------------------------------------------------------------ status
  function healthLevel() {
    var h = state.health;
    if (!h || !h.sources) return { cls: '', text: 'sem dados de estado' };
    var stale = state.updatedAt == null || Date.now() - state.updatedAt > 60 * 60 * 1000;
    var failing = [], officialDown = [];
    Object.keys(h.sources).forEach(function (id) {
      var s = h.sources[id];
      if (s.enabled === false || !s.error) return;
      failing.push(s.name || id);
      if (s.tier === 'official' && (s.consecutive_failures || 0) >= 3) officialDown.push(s.name || id);
    });
    if (stale) return { cls: 'bad', text: 'Sem atualizações há mais de 1 h' };
    if (officialDown.length) return { cls: 'bad', text: 'Fonte oficial em baixo: ' + officialDown.join(', ') };
    if (failing.length) return { cls: 'warn', text: failing.length + ' fonte(s) com erro: ' + failing.join(', ') };
    return { cls: 'ok', text: 'Todas as fontes ativas a funcionar' };
  }

  function renderStatus() {
    var lvl = healthLevel();
    $('status-dot').className = 'dot ' + lvl.cls;
    var u = $('updated');
    u.textContent = '';
    if (state.loaded && state.updatedAt) {
      var lbl = document.createElement('span');
      lbl.className = 'lbl';
      lbl.textContent = 'atualizado ';
      u.appendChild(lbl);
      u.appendChild(document.createTextNode(ago(state.updatedAt)));
    } else {
      u.textContent = state.loaded ? 'à espera da 1.ª recolha' : 'a carregar…';
    }
    $('status').title = lvl.text;
    $('status').setAttribute('aria-label', 'Estado: ' + lvl.text + '. ' + u.textContent);
  }

  // ------------------------------------------------------------------ list
  function matchesQuery(it) {
    if (!state.query) return true;
    var hay = fold([it.title, it.excerpt, it.source_name, it.domain, (it.topics || []).join(' ')].join(' '));
    return fold(state.query).split(/\s+/).every(function (w) { return hay.indexOf(w) !== -1; });
  }

  function card(it, pinned) {
    var node = $('card-tpl').content.firstElementChild.cloneNode(true);
    var tag = TAGS[it.tag] || TAGS.RUMOR;
    node.classList.add('tag-' + tag.cls);
    if (pinned) node.classList.add('is-pinned');
    var badge = node.querySelector('.badge');
    badge.textContent = tag.text;
    badge.classList.add(tag.cls);
    var src = it.source_name || it.domain || '';
    if (it.domain && it.source_name && fold(it.source_name).indexOf(fold(it.domain.split('.')[0])) === -1) src += ' · ' + it.domain;
    node.querySelector('.source').textContent = src;
    var t = parseTime(it.published);
    var time = node.querySelector('time');
    time.textContent = ago(t);
    if (t) { time.dateTime = it.published; time.title = new Date(t).toLocaleString('pt-PT'); }
    if (isNew(it)) node.querySelector('.new-flag').hidden = false;
    var url = safeUrl(it.url);
    var a = node.querySelector('.card-title a');
    a.textContent = it.title;
    a.href = url;
    node.querySelector('.open').href = url;
    node.querySelector('.excerpt').textContent = it.excerpt || '';
    var topics = node.querySelector('.topics');
    (it.topics || []).forEach(function (tp) {
      var s = document.createElement('span');
      s.className = 'topic' + (URGENT.indexOf(tp) !== -1 ? ' hot' : '');
      s.textContent = '#' + (TOPIC_LABEL[tp] || tp);
      topics.appendChild(s);
    });
    if (it.also_on && it.also_on.length) {
      var also = node.querySelector('.also');
      also.textContent = 'Também em: ' + it.also_on.join(', ');
      also.hidden = false;
    }
    return node;
  }

  function counts() {
    var c = {};
    Object.keys(FILTERS).forEach(function (k) { c[k] = 0; });
    state.items.forEach(function (it) {
      Object.keys(FILTERS).forEach(function (k) { if (FILTERS[k](it)) c[k]++; });
    });
    return c;
  }

  function renderChips() {
    var c = counts();
    Array.prototype.forEach.call($('chips').querySelectorAll('button'), function (b) {
      var f = b.getAttribute('data-filter');
      b.setAttribute('aria-pressed', String(f === state.filter));
      var n = b.querySelector('.n');
      if (!n) { n = document.createElement('span'); n.className = 'n'; b.appendChild(n); }
      n.textContent = state.loaded ? String(c[f]) : '';
    });
  }

  function renderList() {
    var filter = FILTERS[state.filter] || FILTERS.all;
    var visible = state.items.filter(function (it) { return filter(it) && matchesQuery(it); });
    var pinned = visible.filter(isPinned).slice(0, 5);
    var pinnedIds = {};
    pinned.forEach(function (it) { pinnedIds[it.id] = true; });
    var rest = visible.filter(function (it) { return !pinnedIds[it.id]; });

    var pinBox = $('pinned');
    pinBox.textContent = '';
    if (pinned.length) {
      var lbl = document.createElement('p');
      lbl.className = 'pinned-label';
      lbl.textContent = '🚨 Oficial · RP / Online / Servidores';
      pinBox.appendChild(lbl);
      pinned.forEach(function (it) { pinBox.appendChild(card(it, true)); });
    }
    pinBox.hidden = !pinned.length;

    var list = $('list');
    list.textContent = '';
    var frag = document.createDocumentFragment();
    rest.slice(0, state.shown).forEach(function (it) { frag.appendChild(card(it, false)); });
    list.appendChild(frag);
    $('more').hidden = rest.length <= state.shown;

    var newCount = visible.filter(isNew).length;
    $('summary').textContent = !state.loaded ? '' :
      visible.length + (visible.length === 1 ? ' notícia' : ' notícias') + (newCount ? ' · ' + newCount + ' nova(s) desde a última visita' : '');

    if (state.loaded && !visible.length) {
      var empty = document.createElement('div');
      empty.className = 'empty';
      var strong = document.createElement('strong');
      var p = document.createElement('p');
      if (!state.items.length) {
        strong.textContent = 'Ainda não há notícias recolhidas.';
        p.textContent = 'A primeira recolha automática corre em poucos minutos.';
      } else if (state.query) {
        strong.textContent = 'Nada encontrado para «' + state.query + '».';
        p.textContent = 'Experimenta outras palavras ou o filtro «Tudo».';
      } else if (state.filter === 'rp') {
        strong.textContent = 'Ainda nada sobre RP / servidores.';
        p.textContent = 'Quando houver, aparece aqui primeiro — e com push se for oficial.';
      } else {
        strong.textContent = 'Sem notícias neste filtro.';
      }
      empty.appendChild(strong);
      empty.appendChild(p);
      if (state.filter !== 'all') {
        var b = document.createElement('button');
        b.type = 'button';
        b.textContent = 'Ver tudo';
        b.addEventListener('click', function () { setFilter('all'); });
        empty.appendChild(b);
      }
      list.appendChild(empty);
    }
  }

  // ------------------------------------------------------------------ about
  function renderSources() {
    var box = $('sources');
    var h = state.health;
    if (!h || !h.sources) { box.innerHTML = '<p class="muted">O estado das fontes aparece depois da 1.ª recolha.</p>'; return; }
    box.textContent = '';
    var order = { official: 0, credible: 1, community: 2 };
    var ids = Object.keys(h.sources).sort(function (a, b) {
      var sa = h.sources[a], sb = h.sources[b];
      return (order[sa.tier] - order[sb.tier]) || (sa.name || a).localeCompare(sb.name || b);
    });
    ids.forEach(function (id) {
      var s = h.sources[id];
      var row = document.createElement('div');
      row.className = 'src-row';
      var dot = document.createElement('span');
      dot.className = 'dot ' + (s.enabled === false ? '' : (s.error ? ((s.consecutive_failures || 0) >= 3 ? 'bad' : 'warn') : 'ok'));
      var name = document.createElement('span');
      name.className = 'name';
      name.textContent = s.name || id;
      var tier = document.createElement('span');
      tier.className = 'tier';
      tier.textContent = { official: 'oficial', credible: 'credível', community: 'comunidade' }[s.tier] || s.tier;
      var info = document.createElement('span');
      info.className = 'info';
      if (s.enabled === false) info.textContent = 'Desligada (enabled: false)';
      else if (s.error) info.textContent = 'Erro: ' + s.error + (s.last_success ? ' · último sucesso ' + ago(parseTime(s.last_success)) : ' · ainda sem sucesso');
      else info.textContent = (s.last_count || 0) + ' itens lidos · ' + ago(parseTime(s.last_success));
      row.appendChild(dot); row.appendChild(name); row.appendChild(tier); row.appendChild(info);
      box.appendChild(row);
    });
  }

  // ------------------------------------------------------------------ views
  function route() {
    var about = location.hash === '#sobre';
    $('view-about').hidden = !about;
    $('view-list').hidden = about;
    if (about) { renderSources(); window.scrollTo(0, 0); }
  }

  function render() {
    renderStatus();
    renderChips();
    renderList();
    if (location.hash === '#sobre') renderSources();
  }

  function setFilter(f) {
    state.filter = FILTERS[f] ? f : 'all';
    state.shown = PAGE;
    renderChips();
    renderList();
  }

  // ------------------------------------------------------------------ boot
  function boot() {
    var prev = parseTime(store(LAST_VISIT_KEY));
    state.prevVisit = prev;
    var markVisit = function () { store(LAST_VISIT_KEY, new Date().toISOString()); };
    window.addEventListener('pagehide', markVisit);
    document.addEventListener('visibilitychange', function () {
      if (document.visibilityState === 'hidden') markVisit();
      else load();
    });

    $('chips').addEventListener('click', function (e) {
      var b = e.target.closest('button[data-filter]');
      if (b) setFilter(b.getAttribute('data-filter'));
    });
    var timer = null;
    $('q').addEventListener('input', function (e) {
      clearTimeout(timer);
      timer = setTimeout(function () { state.query = e.target.value.trim(); state.shown = PAGE; renderList(); }, 150);
    });
    $('more').addEventListener('click', function () { state.shown += PAGE; renderList(); });
    $('status').addEventListener('click', function () { location.hash = '#sobre'; });
    window.addEventListener('hashchange', route);

    if (isNative) {
      // Open articles in the system browser instead of inside the app.
      document.addEventListener('click', function (e) {
        var a = e.target.closest('a[target="_blank"]');
        if (a && /^https?:/i.test(a.href)) { e.preventDefault(); window.location.href = a.href; }
      });
    } else if ('serviceWorker' in navigator) {
      navigator.serviceWorker.register('sw.js').catch(function () { /* PWA optional */ });
    }

    route();
    render();
    load();
    setInterval(function () { if (document.visibilityState !== 'hidden') load(); }, REFRESH_MS);
    setInterval(renderStatus, 30 * 1000);
  }

  boot();
})();
