import { readFileSync } from 'node:fs';
import path from 'node:path';
import { afterEach, describe, expect, it, vi } from 'vitest';

import {
  SETTINGS_PERSISTENCE_ANNOTATION,
  allowsSettingsPersistence,
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
    expect(await readPendingGroupSaves(page({ isClosed: () => true }))).toEqual([]);
    for (const message of ['page.evaluate: Target page, context or browser has been closed', 'Execution context was destroyed, most likely because of a navigation']) {
      expect(await readPendingGroupSaves(page({ evaluate: vi.fn(async () => { throw new Error(message); }) }))).toEqual([]);
    }
  });

  it('any other failure of the read is a failure, not "nothing pending"', async () => {
    const broken = page({ evaluate: vi.fn(async () => { throw new TypeError('alpine.$data is not a function'); }) });

    await expect(readPendingGroupSaves(broken)).rejects.toThrow(/alpine/);
  });

  it('on the Settings page a missing panel is an error (a blind guard fails), elsewhere it is not', async () => {
    const missing = vi.fn(async () => ({ found: false, sections: [] }));

    await expect(readPendingGroupSaves(page({ evaluate: missing }))).rejects.toThrow(/panel/i);
    expect(await readPendingGroupSaves(page({ evaluate: missing, url: () => 'http://localhost:5170/wanted/' }))).toEqual([]);
    expect(await readPendingGroupSaves(page({ evaluate: missing, url: () => 'about:blank' }))).toEqual([]);
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
