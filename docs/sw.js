/* Service worker: app shell cached; data/*.json network-first with cache fallback. */
var VERSION = 'vcstar-v7';
var SHELL = [
  './', './index.html', './style.css', './app.js', './auth.js', './vendor/supabase-2.45.4.js', './vendor/591.supabase.js', './manifest.webmanifest',
  './icons/logo-emblem.png', './icons/pattern.svg', './icons/favicon-48.png', './icons/icon-192.png'
];

self.addEventListener('install', function (event) {
  event.waitUntil(caches.open(VERSION).then(function (c) { return c.addAll(SHELL); }).then(function () { return self.skipWaiting(); }));
});

self.addEventListener('activate', function (event) {
  event.waitUntil(caches.keys().then(function (keys) {
    return Promise.all(keys.filter(function (k) { return k !== VERSION; }).map(function (k) { return caches.delete(k); }));
  }).then(function () { return self.clients.claim(); }));
});

self.addEventListener('fetch', function (event) {
  var req = event.request;
  if (req.method !== 'GET') return;
  var url = new URL(req.url);
  if (url.origin !== self.location.origin) return;

  if (url.pathname.indexOf('/data/') !== -1) {
    // network-first: always try fresh news; offline -> last cached copy
    event.respondWith(fetch(req).then(function (res) {
      if (res.ok) {
        var copy = res.clone();
        caches.open(VERSION).then(function (c) { c.put(url.origin + url.pathname, copy); });
      }
      return res;
    }).catch(function () {
      return caches.match(url.origin + url.pathname).then(function (hit) {
        return hit || new Response('{"items":[]}', { headers: { 'Content-Type': 'application/json' } });
      });
    }));
    return;
  }

  // shell: stale-while-revalidate
  event.respondWith(caches.match(req, { ignoreSearch: true }).then(function (hit) {
    var net = fetch(req).then(function (res) {
      if (res.ok) { var copy = res.clone(); caches.open(VERSION).then(function (c) { c.put(req, copy); }); }
      return res;
    }).catch(function () { return hit; });
    return hit || net;
  }));
});
