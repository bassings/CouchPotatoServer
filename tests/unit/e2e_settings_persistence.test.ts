import { readFileSync } from 'node:fs';
import path from 'node:path';
import { afterEach, describe, expect, it, vi } from 'vitest';

import {
  SETTINGS_PERSISTENCE_ANNOTATION,
  allowsSettingsPersistence,
  PANEL_READ_ATTEMPTS,
  PANEL_READ_INTERVAL_MS,
  changedSettings,
  readPanelPendingSaves,
  readPendingGroupSaves,
  serializeSettingValue,
} from '../e2e/settings_persistence';

describe('reading the Settings panel for a group save that is still pending', () => {
  afterEach(() => { vi.unstubAllGlobals(); });

  function panelWith(groups: Record<string, Record<string, unknown>>, rootPresent = true, alpinePresent = true) {
    const root = {};
    vi.stubGlobal('document', { querySelector: (selector: string) => (rootPresent && selector === '[x-data="settingsPanel()"]' ? root : null) });
    vi.stubGlobal('window', alpinePresent ? { Alpine: { $data: () => ({ groupState: groups }) } } : {});
    vi.stubGlobal('clearTimeout', vi.fn());
  }

  it('names the sections with a timer or a queued save, and leaves them alone when only reading', () => {
    const groups = { newznab: { timer: 7, queued: false }, imdb: { timer: null, queued: true }, itunes: { timer: null, queued: false, saving: true } };
    panelWith(groups);

    expect(readPanelPendingSaves(false)).toEqual({ found: true, sections: ['newznab', 'imdb'] });
    expect(groups.newznab.timer).toBe(7);
    expect(groups.imdb.queued).toBe(true);
  });

  it('cancels what it names: the timer is cleared and nulled and the queued flag dropped, so nothing is sent at close', () => {
    const groups = { newznab: { timer: 7, queued: true } };
    panelWith(groups);

    expect(readPanelPendingSaves(true).sections).toEqual(['newznab']);

    expect(groups.newznab).toEqual({ timer: null, queued: false });
    expect(readPanelPendingSaves(true).sections).toEqual([]);
  });

  it('says the panel was not found when the root or Alpine is missing, rather than "nothing pending"', () => {
    panelWith({}, false);
    expect(readPanelPendingSaves(false)).toEqual({ found: false, sections: [] });
    panelWith({}, true, false);
    expect(readPanelPendingSaves(false)).toEqual({ found: false, sections: [] });
  });

  const page = (overrides: Record<string, unknown>) => ({
    isClosed: () => false,
    url: () => 'http://localhost:5170/settings/',
    evaluate: vi.fn(async () => ({ found: true, sections: [] })),
    ...overrides,
  }) as any;

  it('passes the cancel flag into the page, and returns the sections it read', async () => {
    const evaluate = vi.fn(async () => ({ found: true, sections: ['newznab'] }));

    expect(await readPendingGroupSaves(page({ evaluate }), true)).toEqual(['newznab']);
    expect(evaluate).toHaveBeenCalledWith(readPanelPendingSaves, true);
  });

  it('a page that is closed, or closes or navigates during the read, has nothing pending', async () => {
    const neverRead = vi.fn(async () => { throw new TypeError('a closed page must not be read'); });
    expect(await readPendingGroupSaves(page({ isClosed: () => true, evaluate: neverRead }))).toEqual([]);
    expect(neverRead).not.toHaveBeenCalled();
    for (const message of ['page.evaluate: Target page, context or browser has been closed', 'Execution context was destroyed, most likely because of a navigation']) {
      expect(await readPendingGroupSaves(page({ evaluate: vi.fn(async () => { throw new Error(message); }) }))).toEqual([]);
    }
  });

  it('any other failure of the read is a failure, not "nothing pending"', async () => {
    const broken = page({ evaluate: vi.fn(async () => { throw new TypeError('alpine.$data is not a function'); }) });

    await expect(readPendingGroupSaves(broken)).rejects.toThrow(/alpine/);
  });

  it('on the Settings page a panel that never appears is an error (a blind guard fails), elsewhere it is not', async () => {
    const missing = vi.fn(async () => ({ found: false, sections: [] }));
    const sleep = vi.fn(async () => {});

    await expect(readPendingGroupSaves(page({ evaluate: missing }), false, sleep)).rejects.toThrow(/panel/i);
    expect(missing).toHaveBeenCalledTimes(PANEL_READ_ATTEMPTS);
    expect(sleep).toHaveBeenCalledTimes(PANEL_READ_ATTEMPTS - 1);

    sleep.mockClear();
    expect(await readPendingGroupSaves(page({ evaluate: missing, url: () => 'http://localhost:5170/wanted/' }), false, sleep)).toEqual([]);
    expect(await readPendingGroupSaves(page({ evaluate: missing, url: () => 'about:blank' }), false, sleep)).toEqual([]);
    expect(sleep).not.toHaveBeenCalled();
  });

  it('a Settings page that is still starting is read once its panel is there, not reported as blind', async () => {
    const answers = [{ found: false, sections: [] }, { found: false, sections: [] }, { found: true, sections: ['newznab'] }];
    const evaluate = vi.fn(async () => answers.shift());
    const sleep = vi.fn(async () => {});

    expect(await readPendingGroupSaves(page({ evaluate }), true, sleep)).toEqual(['newznab']);

    expect(evaluate).toHaveBeenCalledTimes(3);
    expect(evaluate).toHaveBeenLastCalledWith(readPanelPendingSaves, true);
    expect(sleep).toHaveBeenCalledTimes(2);
  });

  it('gives a starting page at least five seconds, and does not read again until each wait is over', async () => {
    expect(PANEL_READ_ATTEMPTS * PANEL_READ_INTERVAL_MS).toBeGreaterThanOrEqual(5000);

    vi.useFakeTimers();
    try {
      const missing = vi.fn(async () => ({ found: false, sections: [] }));
      let settled = false;
      const read = readPendingGroupSaves(page({ evaluate: missing })).then(
        () => { settled = true; },
        (error) => { settled = true; return error; },
      );

      await vi.advanceTimersByTimeAsync(PANEL_READ_INTERVAL_MS - 1);
      expect(missing).toHaveBeenCalledTimes(1);
      await vi.advanceTimersByTimeAsync(1);
      expect(missing).toHaveBeenCalledTimes(2);
      await vi.advanceTimersByTimeAsync(4700);
      expect(settled).toBe(false);
      await vi.advanceTimersByTimeAsync(300);
      expect(String(await read)).toMatch(/panel/i);
    } finally {
      vi.useRealTimers();
    }
  });

  it('a read that fails for another reason while the panel is awaited is a failure, not "nothing pending"', async () => {
    const answers: Array<() => unknown> = [
      () => ({ found: false, sections: [] }),
      () => ({ found: false, sections: [] }),
      () => { throw new TypeError('alpine.$data is not a function'); },
    ];
    const evaluate = vi.fn(async () => answers.shift()!());

    await expect(readPendingGroupSaves(page({ evaluate }), false, async () => {})).rejects.toThrow(/alpine/);
  });

  it('a page that navigates away while the panel is awaited has nothing pending', async () => {
    let calls = 0;
    const evaluate = vi.fn(async () => {
      calls += 1;
      if (calls > 1) throw new Error('Execution context was destroyed, most likely because of a navigation');
      return { found: false, sections: [] };
    });

    expect(await readPendingGroupSaves(page({ evaluate }), false, async () => {})).toEqual([]);
  });
});

describe('E2E settings persistence policy', () => {
  it('rejects persistence unless the test explicitly opts in', () => {
    expect(allowsSettingsPersistence([])).toBe(false);
    expect(allowsSettingsPersistence([{ type: 'issue', description: '#451' }])).toBe(false);
  });

  it('recognises only the named persistence annotation', () => {
    expect(allowsSettingsPersistence([{ type: SETTINGS_PERSISTENCE_ANNOTATION }])).toBe(true);
    expect(allowsSettingsPersistence([{ type: 'persists-setting' }])).toBe(false);
  });

  it('finds coupled backend changes that were not named by the request', () => {
    const before = { values: { core: { password: '****', auth_required: false } } };
    const after = { values: { core: { password: '******', auth_required: true } } };
    expect(changedSettings(before, after)).toEqual([
      { section: 'core', name: 'password' },
      { section: 'core', name: 'auth_required' },
    ]);
  });

  it('keeps the backend audit wired as an automatic fixture', () => {
    const source = readFileSync(path.resolve(__dirname, '../e2e/fixtures.ts'), 'utf8');
    expect(source).toMatch(/settingsPersistenceGuard:\s*\[async/);
    expect(source).toContain('await page.close()');
    expect(source).toContain('changedSettings(before, after)');
    expect(source).toMatch(/settingsPersistenceGuard:[\s\S]*?\{ auto: true \}\]/);
  });

  it('serializes scalar and directory-list values for the settings API', () => {
    expect(serializeSettingValue(true)).toBe('1');
    expect(serializeSettingValue(false)).toBe('0');
    expect(serializeSettingValue(['/media/one', '/media/two'])).toBe('/media/one::/media/two');
    expect(serializeSettingValue(5050)).toBe('5050');
  });
});
