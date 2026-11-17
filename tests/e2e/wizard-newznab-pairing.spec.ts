import { test, expect, type Page } from './fixtures';
import { configColumns, configSection, configSha, openProvidersStep, recordWizardRequests } from './helpers';
import { SETTINGS_PERSISTENCE_ANNOTATION } from './settings_persistence';

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

// ─────────────────────────────────────────────────────────────────────────────
// SEC-004 P5 (stage 1): the wizard READS the stored Newznab rows.
//
// Every test below runs against its own server seeded from a named starting
// configuration (`seedConfig`) and asserts on the settings FILE (sha256 and the
// raw columns, through tests/helpers/config_readback.py), never only on what the
// page sent or showed. A read that has not completed is never "no indexers".
// ─────────────────────────────────────────────────────────────────────────────

const READ_ROUTE = /\/settings\/(\?.*)?$/;
const urlInput = (page: Page, n: number) => page.getByLabel(`Newznab indexer URL ${n}`);
const keyInput = (page: Page, n: number) => page.getByLabel(`Newznab API key ${n}`);
const newznabSwitch = (page: Page) => page.getByRole('switch', { name: 'Enable Newznab Indexers' });
const providersHeading = (page: Page) => page.getByRole('heading', { name: 'Where to Search' });
const continueButton = (page: Page) => page.getByRole('button', { name: /^(Continue|Saving…)$/ });
const NOT_LOADED = /saved Newznab indexers could not be loaded/i;

/** Every pending timer fires, then the network goes quiet: the point after which "no request" means it. */
async function settle(page: Page) {
  await page.clock.fastForward(5000);
  await page.waitForLoadState('networkidle');
}

const TWO_HOSTS = ['one', 'two'].map((word) => `https://placeholder-${word}.invalid/api`);
const TWO_KEYS = ['one', 'two'].map((word) => `placeholder-key-${word}`);

test.describe('the wizard shows the stored indexers and loading them writes nothing', () => {
  test.use({ seedConfig: 'newznab_two_stored#wizard-read-two' });

  test('two stored indexers are two rows, the keys only in password inputs, and nothing is saved', async ({ page, testServer }) => {
    await page.clock.install();
    const requests = await recordWizardRequests(page);
    const before = configSha(testServer.configPath);

    await openProvidersStep(page);

    await expect(urlInput(page, 1)).toHaveValue(TWO_HOSTS[0]);
    await expect(urlInput(page, 2)).toHaveValue(TWO_HOSTS[1]);
    await expect(keyInput(page, 1)).toHaveValue(TWO_KEYS[0]);
    await expect(keyInput(page, 2)).toHaveValue(TWO_KEYS[1]);
    await expect(keyInput(page, 1)).toHaveAttribute('type', 'password');
    await expect(keyInput(page, 2)).toHaveAttribute('type', 'password');
    await expect(urlInput(page, 3)).toHaveCount(0);
    await expect(newznabSwitch(page)).toHaveAttribute('aria-checked', 'true');

    await settle(page);
    expect(await requests.pageWrites(), 'loading the rows issued a save').toEqual([]);
    expect(requests.groupSaves().concat(requests.columnSaves())).toEqual([]);
    expect(configSha(testServer.configPath)).toBe(before);
    const text = await page.locator('body').innerText();
    for (const key of TWO_KEYS) expect(text, 'an API key is on screen as text').not.toContain(key);
  });

  test('the rows come from the settings API read, never from the page source', async ({ page, testServer }) => {
    const requests = await recordWizardRequests(page);

    await openProvidersStep(page);
    await expect(urlInput(page, 1)).toHaveValue(TWO_HOSTS[0]);

    expect(requests.settingsReads().length, 'the wizard never read the settings API').toBeGreaterThan(0);
    const source = await (await page.request.get(`${testServer.baseURL}/wizard/`)).text();
    for (const stored of [...TWO_HOSTS, ...TWO_KEYS]) {
      expect(source, 'a stored value is in the wizard page source').not.toContain(stored);
    }
  });
});

test.describe('the stored shapes, as the wizard shows them', () => {
  test.describe('a fresh install', () => {
    test.use({ seedConfig: 'fresh_defaults#wizard-read-fresh' });

    test('is one blank row with Newznab off, although `enabled` defaults to on', async ({ page }) => {
      await openProvidersStep(page);

      await expect(newznabSwitch(page)).toHaveAttribute('aria-checked', 'false');
      await newznabSwitch(page).click();
      await expect(urlInput(page, 1)).toHaveValue('');
      await expect(keyInput(page, 1)).toHaveValue('');
      await expect(urlInput(page, 2)).toHaveCount(0);
    });
  });

  test.describe('hidden rows between stored indexers', () => {
    test.use({ seedConfig: 'newznab_interleaved#wizard-read-interleaved' });

    test('only the two stored indexers are shown, in stored order', async ({ page }) => {
      await openProvidersStep(page);

      await expect(urlInput(page, 1)).toHaveValue('https://placeholder-alpha.invalid/api');
      await expect(urlInput(page, 2)).toHaveValue('https://placeholder-bravo.invalid/api');
      await expect(keyInput(page, 2)).toHaveValue('placeholder-key-bravo');
      await expect(urlInput(page, 3)).toHaveCount(0);
    });
  });

  test.describe('a hostless row that carries a key', () => {
    test.use({ seedConfig: 'newznab_hostless#wizard-read-hostless' });

    test('is not shown, and neither is the keyless default', async ({ page }) => {
      await openProvidersStep(page);

      await expect(urlInput(page, 1)).toHaveValue('https://placeholder-alpha.invalid/api');
      await expect(urlInput(page, 2)).toHaveValue('https://placeholder-bravo.invalid/api');
      await expect(urlInput(page, 3)).toHaveCount(0);
      const text = await page.locator('body').innerText();
      expect(text).not.toContain('placeholder-key-hostless');
    });
  });
});

test.describe('a read that has not completed is never "no stored indexers"', () => {
  const FAILURES: [string, { status: number; body: string }][] = [
    ['an HTTP 500', { status: 500, body: '{"success": false}' }],
    ['the API refusal body', { status: 200, body: '{"success": false, "error": "API call doesn\'t exist"}' }],
    ['an answer with no newznab section', { status: 200, body: '{"options": {}, "values": {}, "combine_state": {}}' }],
    ['an answer that is not JSON', { status: 200, body: '<html>proxy error</html>' }],
  ];

  for (const [name, reply] of FAILURES) {
    test.describe(name, () => {
      test.use({ seedConfig: `newznab_two_stored#wizard-read-fails-${name.replaceAll(' ', '-')}` });

      test('Usenet: an error with a way to retry, no rows, Continue refused, the file untouched', async ({ page, testServer }) => {
        await page.clock.install();
        const requests = await recordWizardRequests(page);
        await page.route(READ_ROUTE, (route) => route.fulfill({ status: reply.status, contentType: 'application/json', body: reply.body }));

        await openProvidersStep(page);

        await expect(page.getByTestId('wizard-newznab-error')).toContainText(NOT_LOADED);
        await expect(page.getByRole('button', { name: 'Try loading them again' })).toBeVisible();
        await expect(urlInput(page, 1)).toHaveCount(0);

        const baseline = configSha(testServer.configPath);
        await continueButton(page).click();
        await settle(page);

        await expect(providersHeading(page)).toBeVisible();
        await expect(page.getByTestId('wizard-newznab-error')).toContainText(NOT_LOADED);
        await expect(page.getByTestId('toast-announcer-assertive')).toContainText(NOT_LOADED);
        expect(await requests.pageWrites(), 'a failed read was followed by a save').toEqual([]);
        expect(configSha(testServer.configPath)).toBe(baseline);
      });
    });
  }

  test.describe('a read still pending when Continue is pressed', () => {
    test.use({ seedConfig: 'newznab_two_stored#wizard-read-pending' });

    test('blocks the step and writes nothing; when it lands the rows appear and the error goes', async ({ page, testServer }) => {
      await page.clock.install();
      const requests = await recordWizardRequests(page);
      let release!: () => void;
      const held = new Promise<void>((resolve) => { release = resolve; });
      await page.route(READ_ROUTE, async (route) => { await held; await route.continue(); });

      await openProvidersStep(page);
      await expect(page.getByTestId('wizard-newznab-loading')).toBeVisible();
      await expect(urlInput(page, 1)).toHaveCount(0);

      const baseline = configSha(testServer.configPath);
      await continueButton(page).click();
      // The held read keeps the network busy, so this settles on the clock alone, well inside its 15s.
      await page.clock.fastForward(5000);

      await expect(providersHeading(page)).toBeVisible();
      await expect(page.getByTestId('wizard-newznab-error')).toContainText(NOT_LOADED);
      expect(await requests.pageWrites(), 'a pending read was followed by a save').toEqual([]);
      expect(configSha(testServer.configPath)).toBe(baseline);

      release();
      await expect(urlInput(page, 1)).toHaveValue(TWO_HOSTS[0]);
      await expect(page.getByTestId('wizard-newznab-error')).toBeHidden();
    });
  });

  test.describe('a read that never answers', () => {
    test.use({ seedConfig: 'newznab_two_stored#wizard-read-never' });

    test('counts as failed after its time, with an error and a retry', async ({ page }) => {
      await page.clock.install();
      await page.route(READ_ROUTE, () => new Promise(() => undefined));

      await openProvidersStep(page);
      await expect(page.getByTestId('wizard-newznab-loading')).toBeVisible();

      await page.clock.fastForward(16000);

      await expect(page.getByTestId('wizard-newznab-error')).toContainText(NOT_LOADED);
      await expect(page.getByRole('button', { name: 'Try loading them again' })).toBeVisible();
    });
  });

  test.describe('Torrents only', () => {
    test.use({ seedConfig: 'newznab_two_stored#wizard-read-fails-torrents' });

    test('is not blocked by a failed read and writes no newznab line', async ({ page, testServer }) => {
      test.info().annotations.push({ type: SETTINGS_PERSISTENCE_ANNOTATION });
      const requests = await recordWizardRequests(page);
      await page.route(READ_ROUTE, (route) => route.fulfill({ status: 500, contentType: 'application/json', body: '{}' }));
      const columnsBefore = configColumns(testServer.configPath, 'newznab');

      await openProvidersStep(page, /^Torrents/);
      await continueButton(page).click();

      await expect(providersHeading(page)).toBeHidden({ timeout: 10000 });
      const sections = requests.columnSaves().map((request) => new URLSearchParams(request.body).get('section'));
      expect(sections).not.toContain('newznab');
      expect(requests.groupSaves()).toEqual([]);
      expect(configColumns(testServer.configPath, 'newznab')).toEqual(columnsBefore);
    });
  });

  test.describe('a retry', () => {
    test.use({ seedConfig: 'newznab_two_stored#wizard-read-retry' });

    test('loads the rows, clears the error, and hands focus to the first URL', async ({ page }) => {
      await page.clock.install();
      let answered = 0;
      await page.route(READ_ROUTE, (route) => {
        answered += 1;
        return answered === 1
          ? route.fulfill({ status: 500, contentType: 'application/json', body: '{}' })
          : route.continue();
      });

      await openProvidersStep(page);
      await expect(page.getByTestId('wizard-newznab-error')).toContainText(NOT_LOADED);

      await page.getByRole('button', { name: 'Try loading them again' }).click();

      await expect(urlInput(page, 1)).toHaveValue(TWO_HOSTS[0]);
      await expect(urlInput(page, 1)).toBeFocused();
      await expect(page.getByTestId('wizard-newznab-error')).toBeHidden();
      await expect(newznabSwitch(page)).toBeVisible();
    });
  });
});

// A misaligned stored group (the server's flag) is never written by the wizard: a
// save would turn rows whose keys are paired with the wrong hosts into an aligned
// group, keeping each key against the wrong host for good.
for (const fixture of ['newznab_misaligned_key_short', 'newznab_misaligned_use_short']) {
  test.describe(`a misaligned stored group (${fixture})`, () => {
    test.use({ seedConfig: `${fixture}#wizard-misaligned` });

    test('shows the notice and no rows, writes nothing newznab, and lets the step advance', async ({ page, testServer }) => {
      test.info().annotations.push({ type: SETTINGS_PERSISTENCE_ANNOTATION });
      const requests = await recordWizardRequests(page);
      const before = configSection(testServer.configPath, 'newznab');

      await openProvidersStep(page);

      const notice = page.getByTestId('combine-misaligned-notice');
      await expect(notice).toBeVisible();
      await expect(notice).toContainText('do not line up');
      await expect(notice).toContainText('Fix the rows in Settings');
      await expect(page.locator('[data-newznab-host]')).toHaveCount(0);
      await expect(page.locator('[data-newznab-key]')).toHaveCount(0);
      await expect(newznabSwitch(page)).toHaveCount(0);
      await expect(page.getByTestId('wizard-newznab-error')).toBeHidden();

      await continueButton(page).click();
      await expect(providersHeading(page)).toBeHidden({ timeout: 10000 });

      expect(requests.groupSaves(), 'a misaligned group was saved').toEqual([]);
      const sections = requests.columnSaves().map((request) => new URLSearchParams(request.body).get('section'));
      expect(sections, 'a newznab setting (enabled included) was written').not.toContain('newznab');
      expect(configSection(testServer.configPath, 'newznab')).toEqual(before);
    });
  });
}
