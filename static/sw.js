// Verzija 30: Odstranjeni zunanji CDN viri iz pre-cache, da ne pade cache.addAll
const CACHE_NAME = 'deklaracije-cache-v32';
const DATA_CACHE_NAME = 'deklaracije-data-v32';

// Pomembno: pre-cacheamo samo iste domene (deklaracije.eu / localhost),
// ker SW spodaj ne prestreza zunanjih CDN in bi addAll padel, če bi kateri URL vrnil napako.
const URLS_TO_CACHE = [
  '/',
  '/login',
  '/static/favicon.ico',
  '/static/favicon.png',
  '/static/favicon.PNG',
  '/static/logo.png',
  '/static/manifest.json',
  '/static/js/db.js',
  '/static/js/sync-manager.js',
  '/static/js/main.js'
];

self.addEventListener('install', event => {
  event.waitUntil(
    caches.open(CACHE_NAME)
      .then(cache => {
        console.log(`[SW ${CACHE_NAME}] Predpomnim vire...`);
        return cache.addAll(URLS_TO_CACHE);
      })
      .then(() => {
        console.log(`[SW ${CACHE_NAME}] Vsi viri uspešno predpomnjeni.`);
        return self.skipWaiting();
      })
      .catch(err => console.error(`[SW ${CACHE_NAME}] Napaka pri predpomnjenju: `, err))
  );
});

self.addEventListener('activate', event => {
  event.waitUntil(
    caches.keys().then(cacheNames => {
      return Promise.all(
        cacheNames
          .filter(name => name !== CACHE_NAME)
          .map(name => caches.delete(name))
      );
    }).then(() => self.clients.claim())
  );
});

// Poslušaj sporočila za prisilno posodobitev
self.addEventListener('message', event => {
  if (event.data && event.data.type === 'SKIP_WAITING') {
    console.log('[SW] Prejemam SKIP_WAITING sporočilo');
    self.skipWaiting();
  }
});

self.addEventListener('fetch', event => {
  const { request } = event;
  const url = new URL(request.url);
  
  console.log(`[SW] Fetch event: ${request.method} ${request.url}`);

  // Preveri, ali je shema podprta za cachiranje
  if (url.protocol !== 'https:' && url.protocol !== 'http:') {
    // Ne cachiraj chrome-extension, data:, file: itd.
    return;
  }

  // Preveri, ali je zahtevek za našo domeno
  if (!url.hostname.includes('deklaracije.eu') && !url.hostname.includes('localhost')) {
    // Za zunanje vire (CDN) samo poskusi fetch, ne cachiraj
    return;
  }

  // Posebna obravnava za /logout endpoint
  if (url.pathname === '/logout') {
    console.log('[SW] Zahtevek za /logout endpoint');
    event.respondWith(
      fetch(request)
        .then(response => {
          console.log('[SW] /logout fetch uspešen');
          return response;
        })
        .catch(() => {
          console.log('[SW] /logout fetch neuspešen - offline logout');
          // Offline logout - vrni HTML stran, ki bo preusmerila na login
          const offlineLogoutHTML = `
<!DOCTYPE html>
<html>
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>Odjava - Offline</title>
    <script>
        // Počisti localStorage
        localStorage.removeItem('user');
        localStorage.removeItem('auth_token');
        localStorage.removeItem('isAuthenticated');
        
        // Preusmeri na login stran
        window.location.href = '/login';
    </script>
</head>
<body>
    <p>Odjavljam vas...</p>
</body>
</html>`;
          
          return new Response(offlineLogoutHTML, { 
            status: 200,
            headers: { 
              'Content-Type': 'text/html; charset=utf-8',
              'Cache-Control': 'no-cache, no-store, must-revalidate'
            }
          });
        })
    );
    return;
  }

  // Posebna obravnava za glavno stran in login - vedno poskusi cache first
  if (url.pathname === '/' || url.pathname === '/login') {
    console.log(`[SW] Zahtevek za glavno stran/login: ${request.url}`);
    event.respondWith(
      caches.match(request)
        .then(cachedResponse => {
          if (cachedResponse) {
            console.log(`[SW] Glavna stran/login najdena v cache-u: ${request.url}`);
            return cachedResponse;
          }
          
          // Če ni v cache-u, poskusi fetch
          return fetch(request).then(response => {
            if (response.ok && response.status === 200) {
              const responseClone = response.clone();
              caches.open(CACHE_NAME).then(cache => {
                cache.put(request, responseClone).catch(err => {
                  console.warn('[SW] Napaka pri cachiranju glavne strani:', err);
                });
              });
            }
            return response;
          }).catch(() => {
            // Če fetch ne deluje, poskusi najti index.html
            return caches.match('/').then(indexResponse => {
              if (indexResponse) {
                console.log('[SW] Vračam index.html kot fallback');
                return indexResponse;
              }
              // Če ni niti index.html, vrni 404
              return new Response('', { 
                status: 404,
                headers: { 'Content-Type': 'text/plain' }
              });
            });
          });
        })
        .catch(() => {
          // Če cache match ne deluje, poskusi fetch
          return fetch(request).then(response => {
            if (response.ok && response.status === 200) {
              const responseClone = response.clone();
              caches.open(CACHE_NAME).then(cache => {
                cache.put(request, responseClone).catch(err => {
                  console.warn('[SW] Napaka pri cachiranju glavne strani:', err);
                });
              });
            }
            return response;
          }).catch(() => {
            return new Response('', { 
              status: 404,
              headers: { 'Content-Type': 'text/plain' }
            });
          });
        })
    );
    return;
  }

  // API zahteve - poskusi network first, nato cache
  if (url.pathname.startsWith('/api/')) {
    // Za /api/narocila ne uporabljaj cache (da ne kaže starih podatkov)
    if (url.pathname.startsWith('/api/narocila')) {
      event.respondWith(
        fetch(request).catch(() => {
          return new Response('', {
            status: 503,
            headers: { 'Content-Type': 'text/plain' }
          });
        })
      );
      return;
    }
    event.respondWith(
      fetch(request)
        .then(response => {
          // Shrani v data cache samo če je response veljaven
          if (response.ok && response.status === 200) {
            const responseClone = response.clone();
            caches.open(DATA_CACHE_NAME).then(cache => {
              cache.put(request, responseClone).catch(err => {
                console.warn('[SW] Napaka pri cachiranju API odgovora:', err);
              });
            });
          }
          return response;
        })
        .catch(() => {
          // Če network ne deluje, poskusi iz cache
          return caches.match(request).then(cachedResponse => {
            if (cachedResponse) {
              return cachedResponse;
            }
            // Če ni v cache-u, vrni 404
            return new Response('', { 
              status: 404,
              headers: { 'Content-Type': 'text/plain' }
            });
          }).catch(() => {
            // Če cache match ne deluje, vrni 404
            return new Response('', { 
              status: 404,
              headers: { 'Content-Type': 'text/plain' }
            });
          });
        })
    );
    return;
  }

  // Statični viri - cache first
  if (request.method === 'GET' && !url.pathname.includes('/api/') && !url.pathname.includes('/generiraj_pdf/')) {
    console.log(`[SW] Zahtevek za statični vir: ${request.url}`);
    event.respondWith(
      caches.match(request)
        .then(cachedResponse => {
          if (cachedResponse) {
            console.log(`[SW] Najden v cache-u: ${request.url}`);
            return cachedResponse;
          }
          
          console.log(`[SW] Ni najden v cache-u: ${request.url}`);
          
          // Če ni v cache-u, poskusi fetch
          return fetch(request).then(response => {
                // Shrani v cache za naslednjič samo če je response veljaven
                if (response.ok && response.status === 200) {
                  const responseClone = response.clone();
                  caches.open(CACHE_NAME).then(cache => {
                    cache.put(request, responseClone).catch(err => {
                      console.warn('[SW] Napaka pri cachiranju statičnega vira:', err);
                    });
                  });
                }
                return response;
              }).catch(() => {
                // Če fetch ne deluje, vrni 404
                return new Response('', { 
                  status: 404,
                  headers: { 'Content-Type': 'text/plain' }
                });
              });
        })
        .catch(err => {
          console.warn('[SW] Napaka pri fetch:', err);
          // Vrni prazno response namesto napake
          return new Response('', { 
            status: 404,
            headers: { 'Content-Type': 'text/plain' }
          });
        })
    );
  }

  // Dinamični endpoint-i - direktno na strežnik
  if (request.method === 'GET' && url.pathname.includes('/generiraj_pdf/')) {
    console.log(`[SW] Dinamični zahtevek za PDF: ${request.url}`);
    event.respondWith(
      fetch(request).then(response => {
        return response;
      }).catch(error => {
        console.error('[SW] Napaka pri fetch PDF-ja:', error);
        return new Response('Napaka pri generiranju PDF-ja', { 
          status: 500,
          headers: { 'Content-Type': 'text/plain' }
        });
      })
    );
  }
});

// Background Sync za offline operacije
self.addEventListener('sync', event => {
  if (event.tag === 'background-sync') {
    event.waitUntil(
      // Pošlji sporočilo na glavno stran za sinhronizacijo
      self.clients.matchAll().then(clients => {
        clients.forEach(client => {
          client.postMessage({
            type: 'background-sync',
            timestamp: new Date().toISOString()
          });
        });
      })
    );
  }
});

// Push obvestila
self.addEventListener('push', event => {
  const options = {
    body: event.data ? event.data.text() : 'Nova sprememba v aplikaciji',
    icon: '/static/logo.png',
    badge: '/static/logo.png',
    vibrate: [100, 50, 100],
    data: {
      dateOfArrival: Date.now(),
      primaryKey: 1
    },
    actions: [
      {
        action: 'explore',
        title: 'Odpri aplikacijo',
        icon: '/static/logo.png'
      },
      {
        action: 'close',
        title: 'Zapri',
        icon: '/static/logo.png'
      }
    ]
  };

  event.waitUntil(
    self.registration.showNotification('Deklaracije', options)
  );
});

// Klik na push obvestilo
self.addEventListener('notificationclick', event => {
  event.notification.close();

  if (event.action === 'explore') {
    event.waitUntil(
      clients.openWindow('/')
    );
  }
});