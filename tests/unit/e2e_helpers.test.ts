// @vitest-environment node
/**
 * The E2E helpers SEC-004 adds: the settings-save mock that also covers the group
 * route (AC-QA-19), and the read-back of a worker's real config file (AC-QA-10).
 *
 * The read-back tests run the real Python helper over a real file: they are the
 * boundary between the TypeScript caller and the provider's reader, which a mock of
 * either side would hide.
 */
import { createHash } from 'node:crypto';
import fs from 'node:fs';
import os from 'node:os';
import path from 'node:path';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';

vi.mock('@playwright/test', () => ({ expect: vi.fn() }));
import { configColumns, configEnabled, configSha, configView, mockSettingsSave } from '../e2e/helpers';

describe('mockSettingsSave', () => {
  async function installed() {
    const route = vi.fn();
    await mockSettingsSave({ route } as never);
    const [pattern, handler] = route.mock.calls[0] as [RegExp, (route: unknown) => Promise<void>];
    return { pattern, handler, count: route.mock.calls.length };
  }

  it('matches the group-save route as well as the per-column one', async () => {
    const { pattern, count } = await installed();

    expect(count).toBe(1);
    expect(pattern.test('http://localhost:5150/api/key/settings.save/')).toBe(true);
    expect(pattern.test('http://localhost:5150/api/key/settings.save_group/')).toBe(true);
    expect(pattern.test('http://localhost:5150/api/key/settings/')).toBe(false);
  });

  it('answers with success and never lets the request through', async () => {
    const { handler } = await installed();
    const route = { fulfill: vi.fn(), continue: vi.fn() };

    await handler(route);

    expect(route.continue).not.toHaveBeenCalled();
    expect(JSON.parse(route.fulfill.mock.calls[0][0].body)).toEqual({ success: true });
  });
});

describe('config file read-back', () => {
  let directory: string;
  let configPath: string;

  beforeEach(() => {
    directory = fs.mkdtempSync(path.join(os.tmpdir(), 'cp-readback-'));
    configPath = path.join(directory, 'config.ini');
    fs.writeFileSync(configPath, [
      '[newznab]',
      'use = 1,0',
      'host = https://placeholder-one.invalid/api,https://placeholder-two.invalid/api',
      'api_key = placeholder-key-one,placeholder-key-two',
      '',
    ].join('\n'));
  });
  afterEach(() => fs.rmSync(directory, { recursive: true, force: true }));

  it('hashes the file bytes', () => {
    expect(configSha(configPath)).toBe(createHash('sha256').update(fs.readFileSync(configPath)).digest('hex'));
  });

  it('returns the raw stored column strings', () => {
    expect(configColumns(configPath, 'newznab').api_key).toBe('placeholder-key-one,placeholder-key-two');
  });

  it('returns what the real reader sees, and leaves the file alone', () => {
    const before = fs.readFileSync(configPath);

    const view = configView(configPath, 'newznab') as string[][];

    expect(view.map((row) => row[2])).toEqual(['placeholder-key-one', 'placeholder-key-two']);
    expect(fs.readFileSync(configPath).equals(before)).toBe(true);
  });

  it('runs the real isEnabled over every row', () => {
    expect(configEnabled(configPath, 'newznab')).toEqual({ reader_raises: false, rows: [true, false] });
  });

  it('fails loudly for a section that is not a combine group', () => {
    expect(() => configColumns(configPath, 'core')).toThrow();
  });
});
