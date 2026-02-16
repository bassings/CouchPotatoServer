// CouchPotato Service Worker
const CACHE_NAME = 'couchpotato-v1';
const STATIC_CACHE = 'couchpotato-static-v1';
const DYNAMIC_CACHE = 'couchpotato-dynamic-v1';

// Static assets to cache on install
const STATIC_ASSETS = [
  '/',
  '/wanted/',
  '/available/',
  '/add/',
  '/static/manifest.json',
  // External CDN assets
  'https://unpkg.com/htmx.org@2.0.4/dist/htmx.min.js',
  'https://cdn.jsdelivr.net/npm/alpinejs@3.x.x/dist/cdn.min.js'
];

// Install event - cache static assets
self.addEventListener('install', event => {
  event.waitUntil(
    caches.open(STATIC_CACHE).then(cache => {
      console.log('[SW] Caching static assets');
      return cache.addAll(STATIC_ASSETS).catch(err => {
        console.log('[SW] Some assets failed to cache:', err);
        // Continue anyway - some assets might be cross-origin
      });
    })
  );
  self.skipWaiting();
});

// Activate event - clean up old caches
self.addEventListener('activate', event => {
  event.waitUntil(
    caches.keys().then(keys => {
      return Promise.all(
        keys
          .filter(key => key !== STATIC_CACHE && key !== DYNAMIC_CACHE)
          .map(key => {
            console.log('[SW] Removing old cache:', key);
            return caches.delete(key);
          })
      );
    })
  );
  self.clients.claim();
});

// Fetch event - serve from cache, fallback to network
self.addEventListener('fetch', event => {
  const { request } = event;
  const url = new URL(request.url);

  // Skip non-GET requests
  if (request.method !== 'GET') return;

  // Skip API calls - always go to network
  if (url.pathname.startsWith('/api/') || url.pathname.includes('.')) {
    // For API calls, network-first with no caching
    if (url.pathname.startsWith('/api/')) {
      return;
    }
  }

  // For static assets, use cache-first
  if (url.pathname.startsWith('/static/') ||
      url.hostname.includes('unpkg.com') ||
      url.hostname.includes('jsdelivr.net')) {
    event.respondWith(
      caches.match(request).then(cached => {
        if (cached) return cached;
        return fetch(request).then(response => {
          // Cache successful responses
          if (response.ok) {
            const clone = response.clone();
            caches.open(STATIC_CACHE).then(cache => {
              cache.put(request, clone);
            });
          }
          return response;
        });
      })
    );
    return;
  }

  // For pages, use network-first with cache fallback
  event.respondWith(
    fetch(request)
      .then(response => {
        // Cache successful page responses
        if (response.ok && request.mode === 'navigate') {
          const clone = response.clone();
          caches.open(DYNAMIC_CACHE).then(cache => {
            cache.put(request, clone);
          });
        }
        return response;
      })
      .catch(() => {
        // Network failed, try cache
        return caches.match(request).then(cached => {
          if (cached) return cached;
          // Return offline page if available
          return caches.match('/').then(offline => {
            if (offline) return offline;
            return new Response('Offline', {
              status: 503,
              statusText: 'Service Unavailable',
              headers: { 'Content-Type': 'text/plain' }
            });
          });
        });
      })
  );
});

// Handle messages from the page
self.addEventListener('message', event => {
  if (event.data === 'skipWaiting') {
    self.skipWaiting();
  }
});
