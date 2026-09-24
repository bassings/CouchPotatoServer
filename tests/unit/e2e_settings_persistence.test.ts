import { readFileSync } from 'node:fs';
import path from 'node:path';
import { describe, expect, it } from 'vitest';

import {
  SETTINGS_PERSISTENCE_ANNOTATION,
  allowsSettingsPersistence,
  changedSettings,
  serializeSettingValue,
} from '../e2e/settings_persistence';

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
