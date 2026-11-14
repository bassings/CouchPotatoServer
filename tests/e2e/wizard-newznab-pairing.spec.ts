import { test, expect, type Page } from './fixtures';

/**
 * The server pairs the Newznab `host`, `api_key` and `use` lists BY POSITION
 * (`getHosts` in couchpotato/core/media/_base/providers/nzb/newznab.py keeps
 * blanks and indexes all three by row number). If the wizard drops blanks from
 * one list but not another, position i stops describing one row: an indexer is
 * sent another indexer's API key, or is switched off by someone else's "0".
 *
 * The contract these cases pin: a row is kept if and only if its trimmed URL is
 * non-empty; a kept row contributes its URL, its trimmed key (possibly empty,
 * as a slot that preserves position) and a `1`; a row with no URL is dropped
 * whole, including any key typed into it. All three lists therefore always have
 * the same number of entries.
 *
 * Saves are intercepted with `page.route`, so nothing is written to the
 * per-worker server. Keys and hosts are placeholders, never credentials.
 */

type Row = { host?: string; key?: string };
type Saved = { host: string; api_key: string; use: string };

async function saveNewznabRows(page: Page, rows: Row[]): Promise<Saved> {
  const saved: Record<string, string> = {};
  await page.route('**/settings.save/**', async (route) => {
    const params = new URLSearchParams(route.request().postData() || '');
    if (params.get('section') === 'newznab') saved[params.get('name') || ''] = params.get('value') || '';
    await route.fulfill({
      status: 200,
      contentType: 'application/json',
      body: JSON.stringify({ success: true }),
    });
  });

  await page.goto('/wizard/');
  await page.getByRole('button', { name: /Continue/i }).click();           // Welcome -> Security
  await page.getByRole('button', { name: /Continue/i }).click();           // Security -> Providers
  await expect(page.getByRole('heading', { name: 'Where to Search' })).toBeVisible({ timeout: 10000 });
  await page.getByRole('radio', { name: /^Usenet/ }).click();
  await page.getByRole('switch', { name: 'Enable Newznab Indexers' }).click();
  for (let i = 1; i < rows.length; i++) {
    await page.getByRole('button', { name: '+ Add another indexer' }).click();
  }
  for (const [i, row] of rows.entries()) {
    if (row.host !== undefined) await page.getByLabel(`Newznab indexer URL ${i + 1}`).fill(row.host);
    if (row.key !== undefined) await page.getByLabel(`Newznab API key ${i + 1}`).fill(row.key);
  }

  await page.getByRole('button', { name: /Continue/i }).click();
  await expect(page.getByRole('heading', { name: 'Where to Search' })).toBeHidden({ timeout: 10000 });

  expect(Object.keys(saved).sort(), 'the three Newznab lists were not all saved').toEqual(
    ['api_key', 'enabled', 'host', 'use'],
  );
  return { host: saved.host, api_key: saved.api_key, use: saved.use };
}

/** The invariant itself: one slot per kept row in every list. */
function expectSameLength(saved: Saved) {
  const counts = [saved.host, saved.api_key, saved.use].map((v) => v.split(',').length);
  expect(counts, 'host, api_key and use must have the same number of entries').toEqual([
    counts[0], counts[0], counts[0],
  ]);
}

test.describe('Newznab host, API key and use lists stay paired by position', () => {
  test('URL without a key, then a complete row: the key stays with its own URL', async ({ page }) => {
    const saved = await saveNewznabRows(page, [
      { host: 'https://indexer-a.invalid' },
      { host: 'https://indexer-b.invalid', key: 'placeholder-key-b' },
    ]);
    expect(saved).toEqual({
      host: 'https://indexer-a.invalid,https://indexer-b.invalid',
      api_key: ',placeholder-key-b',
      use: '1,1',
    });
    expectSameLength(saved);
  });

  test('a blank row between two complete rows is dropped and both keep their keys and stay enabled', async ({ page }) => {
    const saved = await saveNewznabRows(page, [
      { host: 'https://indexer-a.invalid', key: 'placeholder-key-a' },
      {},
      { host: 'https://indexer-c.invalid', key: 'placeholder-key-c' },
    ]);
    expect(saved).toEqual({
      host: 'https://indexer-a.invalid,https://indexer-c.invalid',
      api_key: 'placeholder-key-a,placeholder-key-c',
      use: '1,1',
    });
    expectSameLength(saved);
  });

  test('a key with no URL is dropped and the following row keeps its own key', async ({ page }) => {
    const saved = await saveNewznabRows(page, [
      { key: 'placeholder-orphan-key' },
      { host: 'https://indexer-b.invalid', key: 'placeholder-key-b' },
    ]);
    expect(saved).toEqual({
      host: 'https://indexer-b.invalid',
      api_key: 'placeholder-key-b',
      use: '1',
    });
    expect(saved.api_key).not.toContain('placeholder-orphan-key');
    expectSameLength(saved);
  });

  test('a whitespace-only URL counts as blank, and its key is dropped with it', async ({ page }) => {
    const saved = await saveNewznabRows(page, [
      { host: '   ', key: 'placeholder-orphan-key' },
      { host: 'https://indexer-b.invalid', key: 'placeholder-key-b' },
    ]);
    expect(saved).toEqual({
      host: 'https://indexer-b.invalid',
      api_key: 'placeholder-key-b',
      use: '1',
    });
    expectSameLength(saved);
  });

  test('URLs and keys are saved trimmed', async ({ page }) => {
    const saved = await saveNewznabRows(page, [
      { host: '  https://indexer-a.invalid  ', key: '  placeholder-key-a  ' },
      { host: 'https://indexer-b.invalid', key: '   ' },
    ]);
    expect(saved).toEqual({
      host: 'https://indexer-a.invalid,https://indexer-b.invalid',
      api_key: 'placeholder-key-a,',
      use: '1,1',
    });
    expectSameLength(saved);
  });

  test('a single complete row saves exactly as it always did', async ({ page }) => {
    const saved = await saveNewznabRows(page, [
      { host: 'https://indexer-a.invalid', key: 'placeholder-key-a' },
    ]);
    expect(saved).toEqual({
      host: 'https://indexer-a.invalid',
      api_key: 'placeholder-key-a',
      use: '1',
    });
    expectSameLength(saved);
  });
});
