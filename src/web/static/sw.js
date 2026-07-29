// Family HQ Tablet — минимальный service worker.
//
// Намеренно НИЧЕГО не кэширует: шаблон планшета меняется часто (правки
// почти каждый день), и агрессивное кэширование означало бы, что семья
// видит старую версию, пока кто-то вручную не почистит кэш. Он существует
// только чтобы страница формально считалась «устанавливаемым PWA»
// (Chrome/Android требует зарегистрированный SW с обработчиком fetch) и
// открывалась в отдельном standalone-окне без адресной строки браузера.
self.addEventListener('install', () => self.skipWaiting());
self.addEventListener('activate', (event) => event.waitUntil(self.clients.claim()));
self.addEventListener('fetch', (event) => {
  event.respondWith(fetch(event.request));
});
