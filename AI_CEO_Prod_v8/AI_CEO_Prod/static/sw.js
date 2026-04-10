self.addEventListener('install', event => {
  event.waitUntil(caches.open('ai-ceo-v1').then(cache => cache.addAll(['/', '/static/manifest.webmanifest'])));
  self.skipWaiting();
});

self.addEventListener('activate', event => {
  event.waitUntil(self.clients.claim());
});

self.addEventListener('fetch', event => {
  if (event.request.method !== 'GET') return;
  event.respondWith(
    caches.match(event.request).then(resp => resp || fetch(event.request).then(network => {
      const copy = network.clone();
      caches.open('ai-ceo-v1').then(cache => cache.put(event.request, copy));
      return network;
    }).catch(() => caches.match('/')))
  );
});
