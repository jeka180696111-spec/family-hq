const CACHE = 'budget-v9';
const STATIC = [
  '/', '/index.html',
  '/base.css', '/layout.css', '/components.css', '/pages.css', '/new-features.css',
  '/main.js', '/config.js', '/utils.js', '/storage.js', '/theme.js', '/auth.js',
  '/api.js', '/dashboard.js', '/operations.js', '/operations-list.js',
  '/analytics.js', '/wallets.js', '/goals.js', '/reserve.js',
  '/recurring-payments.js', '/ai-chat.js', '/ai-reports.js', '/challenges.js',
  '/settings-ui.js', '/modals.js', '/fab.js', '/onboarding.js',
  '/receipt-scanner.js', '/transfer.js', '/credit-cards.js', '/lock-screen.js',
  '/icon-picker.js', '/icon-192.png', '/icon-512.png', '/manifest.json',
];

self.addEventListener('install', e => {
  e.waitUntil(
    caches.open(CACHE).then(c => c.addAll(STATIC)).then(() => self.skipWaiting())
  );
});

self.addEventListener('activate', e => {
  e.waitUntil(
    caches.keys().then(keys =>
      Promise.all(keys.filter(k => k !== CACHE).map(k => caches.delete(k)))
    ).then(() => self.clients.claim())
  );
});

self.addEventListener('fetch', e => {
  // Cache API does not support non-GET requests
  if (e.request.method !== 'GET') return;

  const url = new URL(e.request.url);

  // API calls: network-first, fallback to cache
  if (url.pathname.startsWith('/api/')) {
    e.respondWith(
      fetch(e.request)
        .then(res => {
          if (res.ok) {
            const clone = res.clone();
            caches.open(CACHE).then(c => c.put(e.request, clone));
          }
          return res;
        })
        .catch(() => caches.match(e.request).then(r => r || new Response(JSON.stringify({ error: 'offline' }), { headers: { 'Content-Type': 'application/json' } })))
    );
    return;
  }

  // Static assets: cache-first
  e.respondWith(
    caches.match(e.request).then(r => r || fetch(e.request).then(res => {
      if (res.ok) {
        const clone = res.clone();
        caches.open(CACHE).then(c => c.put(e.request, clone));
      }
      return res;
    }))
  );
});
