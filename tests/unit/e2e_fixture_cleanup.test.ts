// @vitest-environment node
import { EventEmitter } from 'node:events';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';

const mocks = vi.hoisted(() => ({
  fixtures: {} as Record<string, [(...args: any[]) => Promise<void>]>,
  execFileSync: vi.fn(),
  spawn: vi.fn(),
  writeFileSync: vi.fn(),
  resolvePort: vi.fn((_configured: string | undefined, _offset?: number) => 5150),
}));
vi.mock('@playwright/test', () => ({
  test: { extend: (fixtures: typeof mocks.fixtures) => { mocks.fixtures = fixtures; } },
  expect: vi.fn(),
}));
vi.mock('node:child_process', () => ({ execFileSync: mocks.execFileSync, spawn: mocks.spawn }));
vi.mock('node:fs', () => ({
  existsSync: () => false, mkdirSync: vi.fn(), writeFileSync: mocks.writeFileSync,
}));
vi.mock('node:timers/promises', () => ({ setTimeout: () => new Promise(() => {}) }));
vi.mock('../e2e/port', () => ({
  assertE2EPortAvailable: vi.fn(), resolveE2EPort: mocks.resolvePort,
}));
import '../e2e/fixtures';

beforeEach(() => vi.clearAllMocks());
afterEach(() => vi.unstubAllGlobals());

describe('worker fixture cleanup', () => {
  it.each(['fetch', 'markup', 'url', 'use'])('cleans up after %s fails and preserves its diagnostic', async (failure) => {
    const proc = Object.assign(new EventEmitter(), {
      exitCode: null as number | null,
      signalCode: null,
      stdout: new EventEmitter(), stderr: new EventEmitter(),
      kill: vi.fn(() => { proc.exitCode = 0; proc.emit('exit', 0, null); }),
    });
    mocks.spawn.mockReturnValue(proc);
    mocks.execFileSync.mockImplementation((_python, args) => {
      if (args[1] === 'cleanup') throw new Error('cleanup failed');
      return '/test-worker-data';
    });
    const original = new Error(`${failure} diagnostic`);
    const markup = failure === 'markup' ? 'no API configuration'
      : failure === 'url' ? "apiBase: 'http://['" : "apiBase: '/api/private-key'";
    const fetchMock = vi.fn()
      .mockResolvedValueOnce({ ok: true })
      .mockResolvedValueOnce({ ok: true, text: async () => 'poster-card' })
      .mockResolvedValueOnce({ ok: true, text: async () => 'movie-releases' });
    if (failure === 'fetch') fetchMock.mockRejectedValueOnce(original);
    else fetchMock.mockResolvedValueOnce({ text: async () => markup });
    vi.stubGlobal('fetch', fetchMock);
    const use = vi.fn(async () => { throw original; });

    const result = mocks.fixtures.workerServer[0]({}, use, { parallelIndex: 0, workerIndex: 1 });
    if (failure === 'markup') await expect(result).rejects.toThrow('rendered root did not expose CP.apiBase');
    else if (failure === 'url') await expect(result).rejects.toThrow('Invalid URL');
    else await expect(result).rejects.toBe(original);
    expect(proc.kill).toHaveBeenCalledWith('SIGTERM');
    expect(mocks.execFileSync).toHaveBeenCalledWith(
      expect.any(String), ['scripts/e2e_worker_data.py', 'cleanup', '0'], { stdio: 'pipe' },
    );
    expect(mocks.writeFileSync).toHaveBeenCalledOnce();
  });
});

describe('settings fixture restoration', () => {
  const workerServer = { apiBase: 'http://localhost:5150/api/private-api-key' };

  describe.each(['baseline', 'after', 'restored'])('%s snapshot validation', (stage) => {
    it.each([
      'http', 'unsuccessful', 'missing', 'null', 'array', 'primitive',
      'null-section', 'array-section', 'primitive-section',
      'null-payload', 'network', 'json',
    ])(
      'fails closed on %s responses without unsafe restoration writes', async (failure) => {
        const before = { values: { core: { enabled: false } } };
        const after = { values: { core: { enabled: true } } };
        const page = { route: vi.fn(), close: vi.fn() };
        const use = vi.fn();
        const writes: string[] = [];
        let reads = 0;
        const invalidRead = ['baseline', 'after', 'restored'].indexOf(stage);
        vi.stubGlobal('fetch', vi.fn(async (_url, options) => {
          if (options) {
            writes.push(options.body.get('name'));
            return { ok: true, json: async () => ({ success: true }) };
          }
          const read = reads++;
          if (read !== invalidRead) return { ok: true, json: async () => read === 1 ? after : before };
          if (failure === 'network') throw new Error('private-api-key');
          return {
            ok: failure !== 'http',
            json: async () => {
              if (failure === 'json') throw new Error('private-api-key');
              if (failure === 'unsuccessful') return { ...before, success: false };
              if (failure === 'missing') return { success: false };
              if (failure === 'null') return { values: null };
              if (failure === 'array') return { values: [] };
              if (failure === 'primitive') return { values: 'private-api-key' };
              if (failure === 'null-section') return { values: { core: null } };
              if (failure === 'array-section') return { values: { core: ['private-api-key'] } };
              if (failure === 'primitive-section') return { values: { core: 'private-api-key' } };
              if (failure === 'null-payload') return null;
              return before;
            },
          };
        }));

        const result = mocks.fixtures.settingsPersistenceGuard[0](
          { page, testServer: workerServer }, use, { annotations: [{ type: 'persistsSettings' }] },
        );
        await expect(result).rejects.toThrow(/snapshot/i);
        await expect(result).rejects.not.toThrow('private-api-key');
        expect(writes).toEqual(stage === 'restored' ? ['enabled'] : []);
        expect(use).toHaveBeenCalledTimes(stage === 'baseline' ? 0 : 1);
        expect(reads).toBe(invalidRead + 1);
      },
    );
  });

  it.each(['http', 'network', 'payload'])('restores later values after masked and %s failures, then verifies and reports all names', async (failure) => {
    const before = { values: { core: { password: '****', failed: 'old', enabled: false, leftover: 'old' } } };
    const after = { values: { core: { password: '******', failed: 'new', enabled: true, leftover: 'new' } } };
    const restored = { values: { core: { password: '******', failed: 'new', enabled: false, leftover: 'new' } } };
    const page = { route: vi.fn(), close: vi.fn() };
    const writes: string[] = [];
    let reads = 0;
    vi.stubGlobal('fetch', vi.fn(async (_url, options) => {
      if (!options) return { ok: true, json: async () => [before, after, restored][reads++] };
      const name = options.body.get('name');
      writes.push(name);
      if (name === 'failed' && failure === 'network') throw new Error('network private-api-key');
      return { ok: name !== 'failed' || failure !== 'http', json: async () => ({ success: name !== 'failed' }) };
    }));
    const result = mocks.fixtures.settingsPersistenceGuard[0](
      { page, testServer: workerServer }, async () => {}, { annotations: [{ type: 'persistsSettings' }] },
    );
    const error = await result.catch((err: Error) => err);
    expect(writes).toEqual(['failed', 'enabled', 'leftover']);
    expect(reads).toBe(3);
    expect(error).toBeInstanceOf(Error);
    expect((error as Error).message).toContain('core.password');
    expect((error as Error).message).toContain('core.failed');
    expect((error as Error).message).toContain('core.leftover');
    expect((error as Error).message).not.toContain('private-api-key');
    expect(page.close).toHaveBeenCalledOnce();
  });

  it('reports blocked saves without retaining a credential-bearing request URL', async () => {
    let onRoute: (route: unknown) => Promise<void>;
    const page = {
      route: vi.fn(async (_pattern, handler) => { onRoute = handler; }),
      close: vi.fn(),
    };
    vi.stubGlobal('fetch', vi.fn(async () => ({ ok: true, json: async () => ({ values: {} }) })));
    const result = mocks.fixtures.settingsPersistenceGuard[0](
      { page, testServer: workerServer }, async () => {
        await onRoute({
          request: () => ({ url: () => `${workerServer.apiBase}/settings.save/?value=private-password` }),
          fulfill: vi.fn(),
        });
      }, { annotations: [] },
    );
    const error = await result.catch((err: Error) => err);
    expect(error).toBeInstanceOf(Error);
    expect((error as Error).message).toContain('1 unmocked settings.save request(s)');
    expect((error as Error).message).not.toContain('private-api-key');
    expect((error as Error).message).not.toContain('private-password');
    expect((error as Error).message).not.toContain(workerServer.apiBase);
  });

  it.each([false, true])('verifies successful restore attempts (verification unavailable: %s)', async (verificationUnavailable) => {
    const before = { values: { core: { enabled: false } } };
    const after = { values: { core: { enabled: true } } };
    const page = { route: vi.fn(), close: vi.fn() };
    let reads = 0;
    const fetchMock = vi.fn(async (_url, options) => {
      if (options) {
        expect(options.body.get('value')).toBe('0');
        return { ok: true, json: async () => ({ success: true }) };
      }
      reads += 1;
      if (reads === 3 && verificationUnavailable) throw new Error('private-api-key');
      return { ok: true, json: async () => reads === 2 ? after : before };
    });
    vi.stubGlobal('fetch', fetchMock);
    const result = mocks.fixtures.settingsPersistenceGuard[0](
      { page, testServer: workerServer }, async () => {}, { annotations: [{ type: 'persistsSettings' }] },
    );
    if (verificationUnavailable) {
      await expect(result).rejects.toThrow(
        'E2E setting restoration failed or could not safely restore: core.enabled; snapshot verification failed',
      );
    } else {
      await expect(result).resolves.toBeUndefined();
    }
    expect(reads).toBe(3);
    expect(fetchMock).toHaveBeenCalledTimes(4);
  });
});

// SEC-004 AC-QA-19: the persistence guard covers the group-save route.
describe('settings fixture group-save coverage', () => {
  const workerServer = { apiBase: 'http://localhost:5150/api/private-api-key' };
  const COLUMNS = ['use', 'host', 'api_key', 'extra_score', 'custom_tag'];
  const options = {
    newznab: { groups: [{ options: [{ name: 'api_key', type: 'combined', combine: COLUMNS }] }] },
    core: { groups: [{ options: [{ name: 'port' }] }] },
  };
  const aligned = {
    use: '1,0', host: 'https://placeholder-one.invalid,https://placeholder-two.invalid',
    api_key: 'placeholder-key-one,placeholder-key-two', extra_score: '5,10', custom_tag: 'tag-one,tag-two',
  };
  const snapshot = (newznab: Record<string, string>, state = { misaligned: false, rows: 2 }, core = { port: '5150' }) => ({
    options, values: { newznab, core }, combine_state: { newznab: state },
  });
  const edited = { ...aligned, host: 'https://placeholder-edited.invalid,https://placeholder-two.invalid' };
  const GROUP_URL = `${workerServer.apiBase}/settings.save_group/`;

  type Write = { url: string; options: any };
  function stubServer(reads: unknown[], failGroup = false) {
    const writes: Write[] = [];
    let read = 0;
    vi.stubGlobal('fetch', vi.fn(async (url, init) => {
      if (!init) return { ok: true, json: async () => reads[read++] };
      writes.push({ url, options: init });
      return { ok: !failGroup, json: async () => ({ success: !failGroup }) };
    }));
    return { writes, reads: () => read };
  }
  const run = (annotations: { type: string }[], use: () => Promise<void> = async () => {}) => {
    const page = { route: vi.fn(), close: vi.fn() };
    // A seeded server: a group changes only on a test's own server (see the shared-server tests).
    const result = mocks.fixtures.settingsPersistenceGuard[0](
      { page, testServer: workerServer, seedConfig: 'newznab_aligned#restore' }, use, { annotations });
    return { page, result };
  };

  it('intercepts the group-save route as well as the per-column one', async () => {
    stubServer([snapshot(aligned), snapshot(aligned)]);
    const { page, result } = run([]);
    await result;

    expect(page.route).toHaveBeenCalledTimes(1);
    const pattern = page.route.mock.calls[0][0] as RegExp;
    expect(pattern).toBeInstanceOf(RegExp);
    expect(pattern.test(GROUP_URL)).toBe(true);
    expect(pattern.test(`${workerServer.apiBase}/settings.save/`)).toBe(true);
    expect(pattern.test(`${workerServer.apiBase}/settings/`)).toBe(false);
    expect(pattern.test(`${workerServer.apiBase}/settings.saveother/`)).toBe(false);
  });

  it('blocks an unannotated group save and fails the test at teardown without the request URL', async () => {
    stubServer([snapshot(aligned), snapshot(aligned)]);
    let onRoute: (route: unknown) => Promise<void> = async () => {};
    const fulfill = vi.fn();
    const page = { route: vi.fn(async (_pattern, handler) => { onRoute = handler; }), close: vi.fn() };
    const result = mocks.fixtures.settingsPersistenceGuard[0](
      { page, testServer: workerServer, seedConfig: 'newznab_aligned#unannotated' },
      async () => { await onRoute({ request: () => ({ url: () => GROUP_URL }), fulfill }); },
      { annotations: [] },
    );
    const error = await result.catch((err: Error) => err);

    expect(fulfill).toHaveBeenCalledWith(expect.objectContaining({ status: 409 }));
    expect((error as Error).message).toContain('1 unmocked settings.save request(s)');
    expect((error as Error).message).not.toContain('private-api-key');
  });

  it('restores a changed group with ONE group save of its baseline rows, never per column', async () => {
    const server = stubServer([snapshot(aligned), snapshot(edited), snapshot(aligned)]);
    const { result } = run([{ type: 'persistsSettings' }]);
    await result;

    expect(server.writes).toHaveLength(1);
    expect(server.writes[0].url).toBe(GROUP_URL);
    expect(server.writes[0].options.headers['content-type']).toMatch(/^application\/json/);
    expect(JSON.parse(server.writes[0].options.body)).toEqual({
      section: 'newznab',
      rows: [
        { use: '1', host: 'https://placeholder-one.invalid', api_key: 'placeholder-key-one', extra_score: '5', custom_tag: 'tag-one' },
        { use: '0', host: 'https://placeholder-two.invalid', api_key: 'placeholder-key-two', extra_score: '10', custom_tag: 'tag-two' },
      ],
    });
    expect(server.reads()).toBe(3);
  });

  it('still restores a non-combine option in the same section per column', async () => {
    const before = { ...snapshot(aligned), values: { newznab: aligned, core: { port: '5150' } } };
    const after = { ...snapshot(edited), values: { newznab: edited, core: { port: '5199' } } };
    const server = stubServer([before, after, before]);
    const { result } = run([{ type: 'persistsSettings' }]);
    await result;

    expect(server.writes.map((write) => write.url)).toEqual(
      expect.arrayContaining([GROUP_URL, `${workerServer.apiBase}/settings.save/`]),
    );
    expect(server.writes).toHaveLength(2);
  });

  it('skips the restore and its verification for a misaligned baseline, and does not fail', async () => {
    const short = { ...aligned, api_key: 'placeholder-key-one', use: '1' };
    const server = stubServer([snapshot(short, { misaligned: true, rows: 2 }), snapshot(edited, { misaligned: true, rows: 2 })]);
    const { result } = run([{ type: 'persistsSettings' }]);
    await expect(result).resolves.toBeUndefined();

    expect(server.writes).toHaveLength(0);
  });

  it('skips a baseline a group save cannot reproduce (a column shorter than the row count)', async () => {
    const shortColumn = { ...aligned, extra_score: '5' };
    const server = stubServer([snapshot(shortColumn), snapshot({ ...shortColumn, host: 'changed,changed' })]);
    const { result } = run([{ type: 'persistsSettings' }]);
    await expect(result).resolves.toBeUndefined();

    expect(server.writes).toHaveLength(0);
  });

  it('reports a failed group restore by section, not by column', async () => {
    stubServer([snapshot(aligned), snapshot(edited), snapshot(edited)], true);
    const { result } = run([{ type: 'persistsSettings' }]);
    const error = await result.catch((err: Error) => err);

    expect((error as Error).message).toContain('newznab (group)');
    expect((error as Error).message).not.toContain('placeholder');
  });
});

// SEC-004 AC-QA-10: a test that names a seedConfig gets its own server, started from
// that named fixture BEFORE it starts; a test that names none shares the worker's.
describe('seedConfig test server', () => {
  const shared = { baseURL: 'http://localhost:5150', apiBase: 'http://localhost:5150/api/k', configPath: '/shared/config.ini' };

  function serverProcess() {
    const proc = Object.assign(new EventEmitter(), {
      exitCode: null as number | null,
      signalCode: null,
      stdout: new EventEmitter(), stderr: new EventEmitter(),
      kill: vi.fn(() => { proc.exitCode = 0; proc.emit('exit', 0, null); }),
    });
    return proc;
  }

  function stubReadyServer() {
    mocks.spawn.mockReturnValue(serverProcess());
    mocks.execFileSync.mockImplementation((_python, args) => (args[1] === 'prepare' ? '/seeded-data' : ''));
    vi.stubGlobal('fetch', vi.fn()
      .mockResolvedValueOnce({ ok: true })
      .mockResolvedValueOnce({ ok: true, text: async () => 'poster-card' })
      .mockResolvedValueOnce({ ok: true, text: async () => 'movie-releases' })
      .mockResolvedValueOnce({ text: async () => "apiBase: '/api/seeded-key'" }));
  }

  it('shares the worker server, and starts nothing, when no seedConfig is named', async () => {
    const use = vi.fn();
    await (mocks.fixtures.testServer as any)({ seedConfig: '', workerServer: shared }, use, { parallelIndex: 0, workerIndex: 1 });

    expect(use).toHaveBeenCalledWith(shared);
    expect(mocks.execFileSync).not.toHaveBeenCalled();
    expect(mocks.spawn).not.toHaveBeenCalled();
  });

  it('seeds the named fixture before the server starts, on a port and data dir of its own', async () => {
    stubReadyServer();
    let served: Record<string, string> | undefined;
    await (mocks.fixtures.testServer as any)(
      { seedConfig: 'newznab_aligned#a-test', workerServer: shared },
      async (server: Record<string, string>) => { served = server; },
      { parallelIndex: 0, workerIndex: 1 },
    );

    const calls = mocks.execFileSync.mock.calls.map((call) => call[1] as string[]);
    const seed = calls.find((args) => args[0] === 'scripts/seed_e2e_data.py');
    expect(seed).toContain('--config-fixture=newznab_aligned#a-test');
    expect(calls.find((args) => args[1] === 'prepare')).toEqual(['scripts/e2e_worker_data.py', 'prepare', '20']);
    expect(mocks.resolvePort).toHaveBeenCalledWith(undefined, 20);
    expect(served?.configPath).toBe('/seeded-data/config.ini');
  });

  it('seeds the fixture before it spawns the server', async () => {
    stubReadyServer();
    const order: string[] = [];
    mocks.execFileSync.mockImplementation((_python, args) => {
      order.push(String(args[0]));
      return args[1] === 'prepare' ? '/seeded-data' : '';
    });
    mocks.spawn.mockImplementation(() => { order.push('spawn'); return serverProcess(); });
    await (mocks.fixtures.testServer as any)(
      { seedConfig: 'newznab_aligned', workerServer: shared }, async () => {}, { parallelIndex: 0, workerIndex: 1 },
    );

    expect(order.indexOf('scripts/seed_e2e_data.py')).toBeLessThan(order.indexOf('spawn'));
  });

  it('stops the dedicated server and frees its data dir after the test', async () => {
    stubReadyServer();
    await (mocks.fixtures.testServer as any)(
      { seedConfig: 'newznab_aligned', workerServer: shared }, async () => {}, { parallelIndex: 0, workerIndex: 1 },
    );

    expect(mocks.execFileSync).toHaveBeenCalledWith(
      expect.any(String), ['scripts/e2e_worker_data.py', 'cleanup', '20'], { stdio: 'pipe' },
    );
  });
});

// SEC-004 P3 fix round: a group save is refused on the worker's SHARED server whatever the
// test declares, and a combine-group writer must own its seedConfig value at RUN time (the
// static check cannot see through a helper, a bare annotation or a looped constant).
describe('group saves and the shared server', () => {
  const workerServer = { apiBase: 'http://localhost:5150/api/private-api-key' };
  const GROUP_URL = `${workerServer.apiBase}/settings.save_group/`;
  const COLUMN_URL = `${workerServer.apiBase}/settings.save/`;
  const snapshot = { options: {}, values: {}, combine_state: {} };

  async function runGuard(seedConfig: string | undefined, annotations: { type: string }[], url: string) {
    vi.stubGlobal('fetch', vi.fn(async () => ({ ok: true, json: async () => snapshot })));
    let onRoute: (route: unknown) => Promise<void> = async () => {};
    const route = { request: () => ({ url: () => url }), fulfill: vi.fn(), continue: vi.fn() };
    const page = { route: vi.fn(async (_pattern, handler) => { onRoute = handler; }), close: vi.fn() };
    const result = (mocks.fixtures.settingsPersistenceGuard[0] as any)(
      { page, testServer: workerServer, seedConfig }, async () => { await onRoute(route); }, { annotations },
    );
    const error = await result.catch((err: Error) => err);
    return { route, error: error as Error | undefined };
  }

  it('blocks a group save on the shared server even when the test declares persistence', async () => {
    const { route, error } = await runGuard('', [{ type: 'persistsSettings' }], GROUP_URL);

    expect(route.continue).not.toHaveBeenCalled();
    expect(route.fulfill).toHaveBeenCalledWith(expect.objectContaining({ status: 409 }));
    expect(error?.message).toMatch(/shared server/);
    expect(error?.message).not.toContain('private-api-key');
  });

  it('lets a group save through on a test\'s own seeded server when it declares persistence', async () => {
    const { route, error } = await runGuard('newznab_aligned#own', [{ type: 'persistsSettings' }], GROUP_URL);

    expect(route.continue).toHaveBeenCalledOnce();
    expect(error).toBeUndefined();
  });

  it('still lets a per-column save through on the shared server when declared', async () => {
    const { route, error } = await runGuard('', [{ type: 'persistsSettings' }], COLUMN_URL);

    expect(route.continue).toHaveBeenCalledOnce();
    expect(error).toBeUndefined();
  });

  it('fails a test whose group changed on the shared server by ANY channel, before restoring it', async () => {
    const columns = ['use', 'host'];
    const options = { newznab: { groups: [{ options: [{ name: 'host', type: 'combined', combine: columns }] }] } };
    const before = { options, values: { newznab: { use: '1', host: 'https://placeholder-one.invalid' } }, combine_state: { newznab: { misaligned: false, rows: 1 } } };
    const after = { options, values: { newznab: { use: '1', host: 'https://placeholder-changed.invalid' } }, combine_state: before.combine_state };
    const writes: unknown[] = [];
    let reads = 0;
    vi.stubGlobal('fetch', vi.fn(async (_url, init) => {
      if (init) writes.push(init);
      return { ok: true, json: async () => (reads++ === 0 ? before : after) };
    }));
    const page = { route: vi.fn(), close: vi.fn() };

    const error = await (mocks.fixtures.settingsPersistenceGuard[0] as any)(
      { page, testServer: workerServer, seedConfig: '' }, async () => {}, { annotations: [{ type: 'persistsSettings' }] },
    ).catch((err: Error) => err);

    expect(error?.message).toMatch(/shared server/);
    expect(error?.message).toContain('newznab');
    expect(error?.message).not.toContain('placeholder');
    expect(writes).toEqual([]);
  });

  it('fails a combine-group writer that runs on the shared server', async () => {
    const { error } = await runGuard('', [{ type: 'persistsSettings' }, { type: 'writesCombineGroup' }], COLUMN_URL);

    expect(error?.message).toMatch(/own seedConfig/);
  });

  it('fails a second combine-group writer on a seedConfig value already used by one', async () => {
    const writer = [{ type: 'persistsSettings' }, { type: 'writesCombineGroup' }];
    const first = await runGuard('newznab_aligned#runtime-owner', writer, COLUMN_URL);
    const second = await runGuard('newznab_aligned#runtime-owner', writer, COLUMN_URL);

    expect(first.error).toBeUndefined();
    expect(second.error?.message).toMatch(/already owned/);
  });
});
