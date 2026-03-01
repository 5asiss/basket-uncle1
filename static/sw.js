/**
 * Service Worker - PWA 캐시
 * - 캐시 버전: v4 (변경 시 기존 캐시 무효화)
 * - 성공한 응답(res.ok)만 캐시
 * - /static/uploads/ 이미지는 네트워크 우선 (캐시하지 않음)
 */
const CACHE_NAME = 'basket-uncle-v4';

self.addEventListener('install', function (event) {
  self.skipWaiting();
});

self.addEventListener('activate', function (event) {
  event.waitUntil(
    caches.keys().then(function (names) {
      return Promise.all(
        names
          .filter(function (name) { return name !== CACHE_NAME; })
          .map(function (name) { return caches.delete(name); })
      );
    }).then(function () { return self.clients.claim(); })
  );
});

self.addEventListener('fetch', function (event) {
  var url = event.request.url;
  if (event.request.method !== 'GET') return;

  if (url.indexOf('/static/uploads/') !== -1) {
    event.respondWith(fetch(event.request));
    return;
  }

  event.respondWith(
    fetch(event.request)
      .then(function (res) {
        if (!res || !res.ok || res.type !== 'basic') return res;
        var clone = res.clone();
        caches.open(CACHE_NAME).then(function (cache) {
          cache.put(event.request, clone);
        });
        return res;
      })
      .catch(function () {
        return caches.match(event.request);
      })
  );
});
