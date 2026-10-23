// CouchPotato Service Worker
const STATIC_CACHE = 'couchpotato-static-v1';
const DYNAMIC_CACHE = 'couchpotato-dynamic-v1';
const SCOPE_PATH = new URL(self.registration.scope).pathname;
const WEB_BASE = SCOPE_PATH.endsWith('/static/')
  ? SCOPE_PATH.slice(0, -'static/'.length) || '/'
  : '/';

function withBase(path) {
  return `${WEB_BASE}${path.replace(/^\//, '')}`.replace(/\/{2,}/g, '/');
}

// Static assets to cache on install
const STATIC_ASSETS = [
  '',
  'wanted/',
  'available/',
  'add/',
  'static/manifest.json',
  'static/scripts/vendor/new-ui/htmx-2.0.11.min.js',
  'static/scripts/vendor/new-ui/alpine-3.17.5.min.js'
].map(withBase);

async function installAssets() {
  try {
    const cache = await caches.open(STATIC_CACHE);
    await cache.addAll(STATIC_ASSETS);
  } catch {
    // Precache failure must not prevent online use or disclose request URLs.
    console.log('[SW] Some assets could not be cached');
  }
  await self.skipWaiting();
}

self.addEventListener('install', event => {
  event.waitUntil(installAssets());
});

// Activate event - clean up old caches
async function activateCaches() {
  const keys = await caches.keys();
  await Promise.all(keys
    .filter(key => key !== STATIC_CACHE && key !== DYNAMIC_CACHE)
    .map(key => caches.delete(key)));
  await self.clients.claim();
}

self.addEventListener('activate', event => {
  event.waitUntil(activateCaches());
});

async function cachedResponse(request) {
  try {
    return await caches.match(request);
  } catch {
    return undefined;
  }
}

function networkResult(response, cacheName) {
  return {response, cacheName, copy: response.ok && cacheName ? response.clone() : null};
}

async function staticResponse(request) {
  const cached = await cachedResponse(request);
  if (cached) return {response: cached};
  return networkResult(await fetch(request), STATIC_CACHE);
}

async function pageResponse(request) {
  try {
    return networkResult(await fetch(request), request.mode === 'navigate' ? DYNAMIC_CACHE : null);
  } catch {
    const cached = await cachedResponse(request) || await cachedResponse(withBase(''));
    return {response: cached || new Response('Offline', {
      status: 503,
      statusText: 'Service Unavailable',
      headers: {'Content-Type': 'text/plain'},
    })};
  }
}

async function maintainCache(resultPromise, request) {
  try {
    const {copy, cacheName} = await resultPromise;
    if (!copy) return;
    const cache = await caches.open(cacheName);
    await cache.put(request, copy);
  } catch {
    // Cache storage is optional. Its failure must not replace a good response.
    console.log('[SW] Cache update skipped');
  }
}

// Fetch event - serve from cache, fallback to network
self.addEventListener('fetch', event => {
  const { request } = event;
  const url = new URL(request.url);

  // Skip non-GET requests
  if (request.method !== 'GET') return;

  // API requests always go to the network without entering either cache.
  if (url.pathname.startsWith(withBase('api/'))) return;

  // For static assets, use cache-first
  const isStatic = url.pathname.startsWith(withBase('static/')) ||
      url.hostname === 'unpkg.com' || url.hostname.endsWith('.unpkg.com') ||
      url.hostname === 'jsdelivr.net' || url.hostname.endsWith('.jsdelivr.net');
  const result = isStatic ? staticResponse(request) : pageResponse(request);
  event.respondWith(result.then(value => value.response));
  // Register synchronously, and keep writes alive without delaying responses.
  event.waitUntil(maintainCache(result, request));
});

// Handle messages from the page
self.addEventListener('message', event => {
  if (event.data === 'skipWaiting') {
    event.waitUntil(self.skipWaiting());
  }
});
