const CACHE_NAME = 'basket-uncle-v3';

// 설치: 정적 자원 + 오프라인 페이지 캐시
self.addEventListener('install', (event) => {
  event.waitUntil(
    caches.open(CACHE_NAME).then((cache) => {
      return cache.addAll([
        '/',
        '/static/logo/sede1roding.png',
        '/static/offline.html'
      ]).catch(() => {});
    }).then(() => self.skipWaiting())
  );
});

// 활성화: 이전 캐시 정리
self.addEventListener('activate', (event) => {
  event.waitUntil(
    caches.keys().then((keys) =>
      Promise.all(keys.filter((k) => k !== CACHE_NAME).map((k) => caches.delete(k)))
    ).then(() => self.clients.claim())
  );
});

// 푸시 알림: 서버에서 보낸 payload로 알림 표시
self.addEventListener('push', (event) => {
  var data = { title: '바구니삼촌', body: '', url: '/mypage/messages' };
  if (event.data) {
    try {
      var j = event.data.json();
      if (j.title) data.title = j.title;
      if (j.body) data.body = j.body;
      if (j.url) data.url = j.url;
    } catch (e) {}
  }
  var opts = {
    body: data.body,
    icon: '/static/logo/sede1roding.png',
    badge: '/static/logo/sede1roding.png',
    tag: 'basket-uncle-msg',
    requireInteraction: false,
    data: { url: data.url }
  };
  event.waitUntil(
    self.registration.showNotification(data.title, opts)
  );
});

// 알림 클릭 시 해당 URL로 열기
self.addEventListener('notificationclick', (event) => {
  event.notification.close();
  var url = (event.notification.data && event.notification.data.url) || '/mypage/messages';
  event.waitUntil(
    self.clients.matchAll({ type: 'window', includeUncontrolled: true }).then(function(clientList) {
      for (var i = 0; i < clientList.length; i++) {
        if (clientList[i].url.indexOf(self.location.origin) === 0 && 'focus' in clientList[i]) {
          clientList[i].navigate(url);
          return clientList[i].focus();
        }
      }
      if (self.clients.openWindow) return self.clients.openWindow(self.location.origin + url);
    })
  );
});

// fetch: 네트워크 우선, 실패 시 캐시 → 오프라인 페이지
self.addEventListener('fetch', (event) => {
  if (event.request.mode === 'navigate') {
    event.respondWith(
      fetch(event.request)
        .then((res) => res)
        .catch(() =>
          caches.match(event.request)
            .then((r) => r || caches.match('/'))
            .then((r) => r || caches.match('/static/offline.html'))
        )
    );
    return;
  }
  if (/\.(js|css|jpg|jpeg|png|gif|ico|woff2?|svg)(\?.*)?$/i.test(event.request.url)) {
    event.respondWith(
      caches.match(event.request).then((cached) => {
        if (cached) return cached;
        return fetch(event.request).then((res) => {
          const clone = res.clone();
          caches.open(CACHE_NAME).then((cache) => cache.put(event.request, clone));
          return res;
        });
      })
    );
  }
});
