const CACHE_NAME = 'emzini-v1';
const STATIC_ASSETS = [
  '/static/manifest.json',
  '/static/icons/icon.svg',
  '/offline',
];

self.addEventListener('install', event => {
  event.waitUntil(
    caches.open(CACHE_NAME).then(cache => cache.addAll(STATIC_ASSETS))
  );
  self.skipWaiting();
});

self.addEventListener('activate', event => {
  event.waitUntil(
    caches.keys().then(keys =>
      Promise.all(keys.filter(k => k !== CACHE_NAME).map(k => caches.delete(k)))
    )
  );
  self.clients.claim();
});

self.addEventListener('fetch', event => {
  const url = new URL(event.request.url);

  // Don't intercept WebSocket upgrades or socket.io polling
  if (url.pathname.startsWith('/socket.io')) return;

  // Only handle navigation requests with network-first + offline fallback
  if (event.request.mode === 'navigate') {
    event.respondWith(
      fetch(event.request).catch(() => caches.match('/offline'))
    );
  }
});
