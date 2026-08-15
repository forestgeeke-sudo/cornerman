/* Cornerman service worker.
   Shell is cache-first so the window opens instantly and works offline.
   The feed is network-first so a live scan always beats a stale copy. */

const VERSION = 'cornerman-v7';
const SHELL = ['./', 'index.html', 'styles.css', 'app.js', 'icon.svg', 'manifest.webmanifest'];

self.addEventListener('install', e => {
  e.waitUntil(
    caches.open(VERSION)
      .then(c => c.addAll(SHELL))
      .then(() => self.skipWaiting())
  );
});

self.addEventListener('activate', e => {
  e.waitUntil(
    caches.keys()
      .then(keys => Promise.all(keys.filter(k => k !== VERSION).map(k => caches.delete(k))))
      .then(() => self.clients.claim())
  );
});

self.addEventListener('fetch', e => {
  const req = e.request;
  if (req.method !== 'GET') return;

  const url = new URL(req.url);
  if (url.origin !== self.location.origin) return;   // let service links go straight out

  if (url.pathname.endsWith('fights.json')) {
    e.respondWith(
      fetch(req)
        .then(res => {
          const copy = res.clone();
          caches.open(VERSION).then(c => c.put('fights.json', copy));
          return res;
        })
        .catch(() => caches.match('fights.json'))
    );
    return;
  }

  // Shell: stale-while-revalidate. Serve the cached copy so the window opens
  // instantly, but always refetch in the background so a shipped fix lands on
  // the next launch instead of never (cache-first alone strands old code).
  e.respondWith(
    caches.match(req, { ignoreSearch: true }).then(hit => {
      const fresh = fetch(req)
        .then(res => {
          if (res && res.ok) {
            const copy = res.clone();
            caches.open(VERSION).then(c => c.put(req, copy));
          }
          return res;
        })
        .catch(() => hit);
      return hit || fresh;
    })
  );
});
