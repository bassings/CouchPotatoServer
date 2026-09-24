// @vitest-environment node
import { EventEmitter } from 'node:events';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';

const mocks = vi.hoisted(() => ({
  fixtures: {} as Record<string, [(...args: any[]) => Promise<void>]>,
  execFileSync: vi.fn(),
  spawn: vi.fn(),
  writeFileSync: vi.fn(),
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
  assertE2EPortAvailable: vi.fn(), resolveE2EPort: () => 5150,
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
          { page, workerServer }, use, { annotations: [{ type: 'persistsSettings' }] },
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
      { page, workerServer }, async () => {}, { annotations: [{ type: 'persistsSettings' }] },
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
      { page, workerServer }, async () => {
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
      { page, workerServer }, async () => {}, { annotations: [{ type: 'persistsSettings' }] },
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
