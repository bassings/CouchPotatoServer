// @vitest-environment node
import {readFileSync} from 'node:fs';
import vm from 'node:vm';
import {format} from 'node:util';
import {describe, expect, it, vi} from 'vitest';

function worker() {
  const handlers = new Map<string, (event: any) => void>();
  const cache = {addAll: vi.fn().mockResolvedValue(undefined), put: vi.fn().mockResolvedValue(undefined)};
  const caches = {
    open: vi.fn().mockResolvedValue(cache),
    match: vi.fn().mockResolvedValue(undefined),
    keys: vi.fn().mockResolvedValue(['old-cache', 'couchpotato-static-v1']),
    delete: vi.fn().mockResolvedValue(true),
  };
  const fetch = vi.fn().mockResolvedValue(new Response('online'));
  const self = {
    registration: {scope: 'https://app.test/static/'},
    addEventListener: (name: string, handler: (event: any) => void) => handlers.set(name, handler),
    skipWaiting: vi.fn().mockResolvedValue(undefined),
    clients: {claim: vi.fn().mockResolvedValue(undefined)},
  };
  const console = {log: vi.fn()};
  vm.runInNewContext(readFileSync('couchpotato/static/sw.js', 'utf8'), {
    self, caches, fetch, console, URL, Response,
  });
  function dispatch(name: string, values: Record<string, unknown> = {}) {
    const lifetime: Promise<unknown>[] = [];
    let active = true;
    const event = {
      ...values,
      respondWith: vi.fn(),
      waitUntil: vi.fn((promise: Promise<unknown>) => {
        if (!active) throw new Error('waitUntil called after event dispatch');
        lifetime.push(promise);
      }),
    };
    handlers.get(name)!(event);
    active = false;
    return {event, lifetime, settled: () => Promise.all(lifetime)};
  }
  const request = (path: string, mode = 'navigate', method = 'GET') => ({
    url: `https://app.test${path}`, mode, method,
  });
  const loggedText = () => console.log.mock.calls.map(args => format(...args)).join('\n');
  return {cache, caches, fetch, self, console, loggedText, dispatch, request};
}

describe('service worker event lifetime and cache failures', () => {
  it.each(['/static/app.js', '/wanted/'])('keeps %s cache writes alive without delaying the response', async path => {
    const w = worker();
    let finish!: () => void;
    w.cache.put.mockImplementation(() => new Promise<void>(resolve => { finish = resolve; }));
    const {event, lifetime, settled} = w.dispatch('fetch', {request: w.request(path)});
    expect(event.waitUntil).toHaveBeenCalledOnce();
    const response = await event.respondWith.mock.calls[0][0];
    expect(await response.text()).toBe('online');
    await vi.waitFor(() => expect(w.cache.put).toHaveBeenCalledOnce());
    expect(lifetime).toHaveLength(1);
    const done = vi.fn();
    void settled().then(done);
    await new Promise(resolve => setImmediate(resolve));
    expect(done).not.toHaveBeenCalled();
    finish();
    await settled();
    expect(await w.cache.put.mock.calls[0][1].text()).toBe('online');
  });

  it.each(['open', 'put'])('retains the online response when cache %s rejects', async failure => {
    const w = worker();
    const error = new Error('private URL and credentials');
    if (failure === 'open') w.caches.open.mockRejectedValue(error);
    else w.cache.put.mockRejectedValue(error);
    const {event, settled} = w.dispatch('fetch', {request: w.request('/wanted/')});
    expect(await (await event.respondWith.mock.calls[0][0]).text()).toBe('online');
    await expect(settled()).resolves.toBeDefined();
    expect(w.loggedText()).not.toContain(error.message);
  });

  it('serves cached static assets without fetching or rewriting them', async () => {
    const w = worker();
    w.caches.match.mockResolvedValue(new Response('cached'));
    const {event, settled} = w.dispatch('fetch', {request: w.request('/static/app.js')});
    expect(await (await event.respondWith.mock.calls[0][0]).text()).toBe('cached');
    await settled();
    expect(w.fetch).not.toHaveBeenCalled();
    expect(w.cache.put).not.toHaveBeenCalled();
  });

  it('fetches static assets when reading the cache fails', async () => {
    const w = worker();
    w.caches.match.mockRejectedValue(new Error('unavailable'));
    const {event, settled} = w.dispatch('fetch', {request: w.request('/static/app.js')});
    expect(await (await event.respondWith.mock.calls[0][0]).text()).toBe('online');
    await settled();
  });

  it.each(['requested page', 'home page', 'no cache', 'unavailable cache'])('handles offline navigation with %s', async scenario => {
    const w = worker();
    w.fetch.mockRejectedValue(new Error('offline'));
    if (scenario === 'requested page') w.caches.match.mockResolvedValueOnce(new Response('requested page'));
    if (scenario === 'home page') w.caches.match.mockResolvedValueOnce(undefined).mockResolvedValueOnce(new Response('home page'));
    if (scenario === 'unavailable cache') w.caches.match.mockRejectedValue(new Error('unavailable'));
    const {event, settled} = w.dispatch('fetch', {request: w.request('/wanted/')});
    const response = await event.respondWith.mock.calls[0][0];
    expect(await response.text()).toBe(['no cache', 'unavailable cache'].includes(scenario) ? 'Offline' : scenario);
    expect(response.status).toBe(['no cache', 'unavailable cache'].includes(scenario) ? 503 : 200);
    await settled();
    expect(w.cache.put).not.toHaveBeenCalled();
  });

  it.each([['/api/key/movie.list/', 'GET'], ['/wanted/', 'POST']])('leaves %s %s to the browser', (path, method) => {
    const w = worker();
    const {event} = w.dispatch('fetch', {request: w.request(path, 'navigate', method)});
    expect(event.respondWith).not.toHaveBeenCalled();
    expect(event.waitUntil).not.toHaveBeenCalled();
  });

  it('does not cache unsuccessful responses or non-navigation page requests', async () => {
    for (const [status, mode] of [[503, 'navigate'], [200, 'cors']] as const) {
      const w = worker();
      w.fetch.mockResolvedValue(new Response('response', {status}));
      const {event, settled} = w.dispatch('fetch', {request: w.request('/wanted/', mode)});
      expect((await event.respondWith.mock.calls[0][0]).status).toBe(status);
      await settled();
      expect(w.cache.put).not.toHaveBeenCalled();
    }
  });

  it('keeps installation alive through skipWaiting despite a failed precache', async () => {
    const w = worker();
    w.cache.addAll.mockRejectedValue(new Error('private URL'));
    const {settled} = w.dispatch('install');
    await settled();
    expect(w.self.skipWaiting).toHaveBeenCalledOnce();
    expect(w.loggedText()).not.toContain('private URL');
  });

  it('waits for cache deletion before claiming clients', async () => {
    const w = worker();
    let finish!: () => void;
    w.caches.delete.mockImplementation(() => new Promise<boolean>(resolve => { finish = () => resolve(true); }));
    const {settled} = w.dispatch('activate');
    await vi.waitFor(() => expect(w.caches.delete).toHaveBeenCalledWith('old-cache'));
    expect(w.self.clients.claim).not.toHaveBeenCalled();
    finish();
    await settled();
    expect(w.self.clients.claim).toHaveBeenCalledOnce();
  });
});
