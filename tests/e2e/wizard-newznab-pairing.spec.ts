import { test, expect, type Page } from './fixtures';
import { configColumns, configSection, configSha, configView, openProvidersStep, recordWizardRequests } from './helpers';
import { combineGroupWriter, SETTINGS_PERSISTENCE_ANNOTATION } from './settings_persistence';

/**
 * The server pairs the Newznab `host`, `api_key` and `use` lists BY POSITION
 * (`getHosts` in couchpotato/core/media/_base/providers/nzb/newznab.py keeps
 * blanks and indexes all of them by row number), so the wizard saves Newznab as
 * ROWS: one `settings.save_group` request carrying all five columns of every row,
 * and the pairing cannot drift because no column is ever sent on its own.
 *
 * The contract these cases pin: a row is kept if and only if its trimmed URL is
 * non-empty; a kept row contributes its URL, its trimmed key (possibly empty, a
 * row with no key) and the defaults (`use` 1, `extra_score` 0, no tag); a row with
 * no URL is dropped whole, including any key typed into it. The six keyless
 * default hosts of a fresh install are hidden rows: kept, in place, unchanged,
 * ahead of the new rows.
 *
 * Saves are intercepted with `page.route`, so nothing is written to the
 * per-worker server. Keys and hosts are placeholders, never credentials.
 */

type Row = { host?: string; key?: string };
type Saved = { use: string; host: string; api_key: string; extra_score: string; custom_tag: string };
const COLUMNS = ['api_key', 'custom_tag', 'extra_score', 'host', 'use'];
const DEFAULT_ROW_COUNT = 6;

/** Type `rows`, Continue, and return the rows the wizard added after the six hidden defaults. */
async function saveNewznabRows(page: Page, rows: Row[]): Promise<Saved[]> {
  const bodies: any[] = [];
  await page.route('**/settings.save_group/**', async (route) => {
    bodies.push(JSON.parse(route.request().postData() || '{}'));
    await route.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify({ success: true }) });
  });
  await page.route('**/settings.save/**', (route) => route.fulfill({
    status: 200, contentType: 'application/json', body: JSON.stringify({ success: true }),
  }));

  await openProvidersStep(page);
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

  expect(bodies, 'the Newznab rows were not saved as exactly one group').toHaveLength(1);
  expect(bodies[0].section).toBe('newznab');
  const all: Saved[] = bodies[0].rows;
  for (const row of all) expect(Object.keys(row).sort(), 'a row without all five columns').toEqual(COLUMNS);
  expect(all.slice(0, DEFAULT_ROW_COUNT).every((row) => row.api_key === '' && row.use === '0'),
    'the keyless defaults were not kept in place').toBe(true);
  return all.slice(DEFAULT_ROW_COUNT);
}

const added = (host: string, api_key: string): Saved => ({ use: '1', host, api_key, extra_score: '0', custom_tag: '' });

test.describe('Newznab rows are saved whole, each URL beside its own key', () => {
  test('URL without a key, then a complete row: the key stays with its own URL', async ({ page }) => {
    const saved = await saveNewznabRows(page, [
      { host: 'https://indexer-a.invalid' },
      { host: 'https://indexer-b.invalid', key: 'placeholder-key-b' },
    ]);
    expect(saved).toEqual([added('https://indexer-a.invalid', ''), added('https://indexer-b.invalid', 'placeholder-key-b')]);
  });

  test('a blank row between two complete rows is dropped and both keep their keys and stay enabled', async ({ page }) => {
    const saved = await saveNewznabRows(page, [
      { host: 'https://indexer-a.invalid', key: 'placeholder-key-a' },
      {},
      { host: 'https://indexer-c.invalid', key: 'placeholder-key-c' },
    ]);
    expect(saved).toEqual([
      added('https://indexer-a.invalid', 'placeholder-key-a'),
      added('https://indexer-c.invalid', 'placeholder-key-c'),
    ]);
  });

  test('a key with no URL is dropped and the following row keeps its own key', async ({ page }) => {
    const saved = await saveNewznabRows(page, [
      { key: 'placeholder-orphan-key' },
      { host: 'https://indexer-b.invalid', key: 'placeholder-key-b' },
    ]);
    expect(saved).toEqual([added('https://indexer-b.invalid', 'placeholder-key-b')]);
    expect(JSON.stringify(saved)).not.toContain('placeholder-orphan-key');
  });

  test('a whitespace-only URL counts as blank, and its key is dropped with it', async ({ page }) => {
    const saved = await saveNewznabRows(page, [
      { host: '   ', key: 'placeholder-orphan-key' },
      { host: 'https://indexer-b.invalid', key: 'placeholder-key-b' },
    ]);
    expect(saved).toEqual([added('https://indexer-b.invalid', 'placeholder-key-b')]);
  });

  test('URLs and keys are saved trimmed', async ({ page }) => {
    const saved = await saveNewznabRows(page, [
      { host: '  https://indexer-a.invalid  ', key: '  placeholder-key-a  ' },
      { host: 'https://indexer-b.invalid', key: '   ' },
    ]);
    expect(saved).toEqual([added('https://indexer-a.invalid', 'placeholder-key-a'), added('https://indexer-b.invalid', '')]);
  });

  test('a single complete row is one added row', async ({ page }) => {
    const saved = await saveNewznabRows(page, [{ host: 'https://indexer-a.invalid', key: 'placeholder-key-a' }]);
    expect(saved).toEqual([added('https://indexer-a.invalid', 'placeholder-key-a')]);
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

// ─────────────────────────────────────────────────────────────────────────────
// SEC-004 P5 (stage 3): the wizard SAVES Newznab as one group, only when a row
// changed, and every claim about what was written is made on the FILE.
//
// Each writer owns its seedConfig value and says so (`combineGroupWriter()`), and
// is checked through the provider's real reader (`configView`, which runs
// `getHosts`) as well as the raw columns, so a key beside the wrong host cannot
// pass for being "the right cells".
// ─────────────────────────────────────────────────────────────────────────────

type Columns = Record<string, string | null>;
type StoredRow = Record<string, string>;
const NEWZNAB_COLUMNS = ['use', 'host', 'api_key', 'extra_score', 'custom_tag'];

/** A group's raw columns as rows of cells: every column split on `,`, nothing trimmed. */
function rowsOf(columns: Columns): StoredRow[] {
  const cells = Object.fromEntries(NEWZNAB_COLUMNS.map((name) => [name, (columns[name] ?? '').split(',')]));
  const count = Math.max(...Object.values(cells).map((list) => list.length));
  return Array.from({ length: count }, (_, i) => Object.fromEntries(NEWZNAB_COLUMNS.map((name) => [name, cells[name][i] ?? ''])));
}

/** What `getHosts` must return for `rows`: (use, host, api_key, extra_score, custom_tag), in order. Every reader strips each cell, so the stored spaces are not in it. */
const viewOf = (rows: StoredRow[]) => rows.map((row) => [row.use.trim(), row.host.trim(), row.api_key.trim(), Number(row.extra_score), row.custom_tag.trim()]);

async function advance(page: Page) {
  await continueButton(page).click();
  await expect(providersHeading(page)).toBeHidden({ timeout: 10000 });
}

const ALIGNED_STARTS = [
  'fresh_defaults', 'newznab_wizard_written', 'newznab_key_in_row_four', 'newznab_untrimmed',
  'newznab_legacy_bytes', 'newznab_two_stored', 'newznab_interleaved', 'newznab_hostless', 'newznab_hostile_cells',
];

test.describe('re-running the wizard and changing nothing sends no Newznab group save at all', () => {
  for (const fixture of ALIGNED_STARTS) {
    test.describe(fixture, () => {
      test.use({ seedConfig: `${fixture}#wizard-no-change` });

      test('every newznab column is byte-identical afterwards', async ({ page, testServer }) => {
        test.info().annotations.push({ type: SETTINGS_PERSISTENCE_ANNOTATION });
        const requests = await recordWizardRequests(page);
        const before = configColumns(testServer.configPath, 'newznab');

        await openProvidersStep(page);
        await advance(page);

        expect(requests.groupSaves(), 'a run that changed no row sent a group save').toEqual([]);
        expect(configColumns(testServer.configPath, 'newznab')).toEqual(before);
      });
    });
  }
});

test.describe('editing one displayed row changes that row only', () => {
  test.describe('between hidden rows', () => {
    test.use({ seedConfig: 'newznab_interleaved#wizard-edit-url' });

    test('A\'s URL changes; every hidden row and B keep their own five cells in the same place', async ({ page, testServer }) => {
      test.info().annotations.push(...combineGroupWriter());
      const requests = await recordWizardRequests(page);
      const original = rowsOf(configColumns(testServer.configPath, 'newznab'));
      await openProvidersStep(page);

      await urlInput(page, 1).fill('  https://placeholder-alpha-edited.invalid/api  ');
      await advance(page);

      expect(requests.groupSaves()).toHaveLength(1);
      const expected = original.map((row, i) => (i === 1 ? { ...row, host: 'https://placeholder-alpha-edited.invalid/api' } : row));
      expect(rowsOf(configColumns(testServer.configPath, 'newznab'))).toEqual(expected);
      expect(configView(testServer.configPath, 'newznab')).toEqual(viewOf(expected));
    });
  });

  test.describe('two stored indexers', () => {
    test.use({ seedConfig: 'newznab_two_stored#wizard-url-keeps-key' });

    test('a key left untouched stays with the URL it was stored beside, whatever the URL is edited to', async ({ page, testServer }) => {
      test.info().annotations.push(...combineGroupWriter());
      const original = rowsOf(configColumns(testServer.configPath, 'newznab'));
      await openProvidersStep(page);

      await urlInput(page, 2).fill('https://placeholder-two-moved.invalid/api');
      await advance(page);

      const expected = [original[0], { ...original[1], host: 'https://placeholder-two-moved.invalid/api' }];
      expect(rowsOf(configColumns(testServer.configPath, 'newznab'))).toEqual(expected);
      expect(configView(testServer.configPath, 'newznab')).toEqual(viewOf(expected));
      expect(expected[1].api_key).toBe('placeholder-key-two');
    });
  });
});

test.describe('adding and removing rows', () => {
  test.describe('add', () => {
    test.use({ seedConfig: 'newznab_interleaved#wizard-add-row' });

    test('a new indexer is appended after every stored row with the documented defaults', async ({ page, testServer }) => {
      test.info().annotations.push(...combineGroupWriter());
      const original = rowsOf(configColumns(testServer.configPath, 'newznab'));
      await openProvidersStep(page);

      await page.getByRole('button', { name: '+ Add another indexer' }).click();
      await urlInput(page, 3).fill(' https://placeholder-charlie.invalid/api ');
      await keyInput(page, 3).fill(' placeholder-key-charlie ');
      await advance(page);

      const expected = [...original, { use: '1', host: 'https://placeholder-charlie.invalid/api', api_key: 'placeholder-key-charlie', extra_score: '0', custom_tag: '' }];
      expect(rowsOf(configColumns(testServer.configPath, 'newznab'))).toEqual(expected);
      expect(configView(testServer.configPath, 'newznab')).toEqual(viewOf(expected));
    });
  });

  test.describe('remove between hidden rows', () => {
    test.use({ seedConfig: 'newznab_interleaved#wizard-remove-a' });

    test('removing A closes up as whole rows: D1, D2, B, D3, each with its own cells', async ({ page, testServer }) => {
      test.info().annotations.push(...combineGroupWriter());
      const original = rowsOf(configColumns(testServer.configPath, 'newznab'));
      await openProvidersStep(page);

      await page.getByRole('button', { name: 'Remove indexer 1', exact: true }).click();
      await advance(page);

      const expected = [original[0], original[2], original[3], original[4]];
      expect(rowsOf(configColumns(testServer.configPath, 'newznab'))).toEqual(expected);
      expect(configView(testServer.configPath, 'newznab')).toEqual(viewOf(expected));
    });
  });

  test.describe('remove every displayed row', () => {
    test.describe('with hidden rows', () => {
      test.use({ seedConfig: 'newznab_interleaved#wizard-remove-all-hidden-kept' });

      test('A and B go; D1, D2 and D3 are stored with their own cells', async ({ page, testServer }) => {
        test.info().annotations.push(...combineGroupWriter());
        const original = rowsOf(configColumns(testServer.configPath, 'newznab'));
        await openProvidersStep(page);

        await page.getByRole('button', { name: 'Remove indexer 1', exact: true }).click();
        await urlInput(page, 1).fill('');   // the last row cannot be removed; a cleared URL is a removal
        await advance(page);

        const expected = [original[0], original[2], original[4]];
        expect(rowsOf(configColumns(testServer.configPath, 'newznab'))).toEqual(expected);
        expect(configView(testServer.configPath, 'newznab')).toEqual(viewOf(expected));
      });
    });

    test.describe('with none', () => {
      test.use({ seedConfig: 'newznab_two_stored#wizard-remove-all-none-left' });

      test('one all-empty row is stored, and the reader finds no indexer', async ({ page, testServer }) => {
        test.info().annotations.push(...combineGroupWriter());
        await openProvidersStep(page);

        await page.getByRole('button', { name: 'Remove indexer 2', exact: true }).click();
        await urlInput(page, 1).fill('');
        await advance(page);

        const columns = configColumns(testServer.configPath, 'newznab');
        for (const name of NEWZNAB_COLUMNS) expect(columns[name], `${name} is not one empty cell`).toBe('');
        expect(configView(testServer.configPath, 'newznab')).toEqual([]);
      });
    });

    test.describe('on a fresh install', () => {
      test.use({ seedConfig: 'fresh_defaults#wizard-nothing-typed' });

      test('nothing typed sends no group save and leaves the six defaults alone', async ({ page, testServer }) => {
        test.info().annotations.push({ type: SETTINGS_PERSISTENCE_ANNOTATION });
        const requests = await recordWizardRequests(page);
        const before = configColumns(testServer.configPath, 'newznab');
        await openProvidersStep(page);
        await newznabSwitch(page).click();

        await advance(page);

        expect(requests.groupSaves()).toEqual([]);
        expect(configColumns(testServer.configPath, 'newznab')).toEqual(before);
      });
    });
  });

  test.describe('a key cleared on its own', () => {
    test.use({ seedConfig: 'newznab_two_stored#wizard-clear-key' });

    test('is written back in place with an empty key, and on the next run the row is hidden', async ({ page, testServer }) => {
      test.info().annotations.push(...combineGroupWriter());
      const original = rowsOf(configColumns(testServer.configPath, 'newznab'));
      await openProvidersStep(page);

      await keyInput(page, 1).fill('');
      await advance(page);

      const expected = [{ ...original[0], api_key: '' }, original[1]];
      expect(rowsOf(configColumns(testServer.configPath, 'newznab'))).toEqual(expected);
      expect(configView(testServer.configPath, 'newznab')).toEqual(viewOf(expected));

      await openProvidersStep(page);
      await expect(urlInput(page, 1)).toHaveValue(original[1].host);
      await expect(urlInput(page, 2)).toHaveCount(0);
    });
  });
});

test.describe('Newznab switched off and on again', () => {
  test.use({ seedConfig: 'newznab_two_stored#wizard-off-and-on' });

  test('off writes `enabled` only; the rows stay stored; on again in a later run restores them unchanged', async ({ page, testServer }) => {
    test.info().annotations.push({ type: SETTINGS_PERSISTENCE_ANNOTATION });
    const requests = await recordWizardRequests(page);
    const original = configColumns(testServer.configPath, 'newznab');
    await openProvidersStep(page);

    await newznabSwitch(page).click();
    await expect(newznabSwitch(page)).toHaveAttribute('aria-checked', 'false');
    await advance(page);

    expect(requests.groupSaves(), 'switching Newznab off saved the group').toEqual([]);
    expect(configColumns(testServer.configPath, 'newznab')).toEqual(original);
    expect(configSection(testServer.configPath, 'newznab').enabled).toMatch(/^(0|false)$/i);

    await openProvidersStep(page);
    await expect(newznabSwitch(page)).toHaveAttribute('aria-checked', 'false');
    await newznabSwitch(page).click();
    await expect(urlInput(page, 1)).toHaveValue('https://placeholder-one.invalid/api');
    await expect(urlInput(page, 2)).toHaveValue('https://placeholder-two.invalid/api');
    await advance(page);

    expect(requests.groupSaves(), 'switching it back on saved the group').toEqual([]);
    expect(configColumns(testServer.configPath, 'newznab')).toEqual(original);
    expect(configSection(testServer.configPath, 'newznab').enabled).toMatch(/^(1|true)$/i);
  });
});

test.describe('edit, Continue, Back, revert, Continue', () => {
  test.use({ seedConfig: 'newznab_two_stored#wizard-edit-back-revert' });

  test('is two group saves, one per Continue, and the file holds the original rows again', async ({ page, testServer }) => {
    test.info().annotations.push(...combineGroupWriter());
    const requests = await recordWizardRequests(page);
    const original = configColumns(testServer.configPath, 'newznab');
    await openProvidersStep(page);

    await urlInput(page, 1).fill('https://placeholder-one-edited.invalid/api');
    await advance(page);
    expect(requests.groupSaves()).toHaveLength(1);
    expect(rowsOf(configColumns(testServer.configPath, 'newznab'))[0].host).toBe('https://placeholder-one-edited.invalid/api');

    await page.getByRole('button', { name: /Back$/ }).click();
    await expect(providersHeading(page)).toBeVisible();
    await expect(urlInput(page, 1)).toHaveValue('https://placeholder-one-edited.invalid/api');
    await urlInput(page, 1).fill('https://placeholder-one.invalid/api');
    await advance(page);

    expect(requests.groupSaves()).toHaveLength(2);
    expect(configColumns(testServer.configPath, 'newznab')).toEqual(original);
  });

});

test.describe('Back and Continue with nothing changed', () => {
  test.use({ seedConfig: 'newznab_two_stored#wizard-back-continue-unchanged' });

  test('does not write the rows that were already written again', async ({ page, testServer }) => {
    test.info().annotations.push(...combineGroupWriter());
    const requests = await recordWizardRequests(page);
    await openProvidersStep(page);
    await urlInput(page, 1).fill('https://placeholder-one-edited.invalid/api');
    await advance(page);
    expect(requests.groupSaves()).toHaveLength(1);

    await page.getByRole('button', { name: /Back$/ }).click();
    await expect(providersHeading(page)).toBeVisible();
    await advance(page);

    expect(requests.groupSaves(), 'the rows already written were written again').toHaveLength(1);
    expect(rowsOf(configColumns(testServer.configPath, 'newznab'))[0].host).toBe('https://placeholder-one-edited.invalid/api');
  });
});

test.describe('Continue pressed twice, or held', () => {
  test.use({ seedConfig: 'newznab_two_stored#wizard-double-continue' });

  test('sends one group save', async ({ page }) => {
    test.info().annotations.push(...combineGroupWriter());
    const requests = await recordWizardRequests(page);
    await page.route('**/settings.save_group/**', async (route) => {
      await new Promise((resolve) => setTimeout(resolve, 300));   // keeps the first save in flight while the second press lands
      await route.continue();
    });
    await openProvidersStep(page);
    await urlInput(page, 1).fill('https://placeholder-one-edited.invalid/api');

    await continueButton(page).dblclick();
    await expect(providersHeading(page)).toBeHidden({ timeout: 10000 });

    expect(requests.groupSaves()).toHaveLength(1);
  });

});

test.describe('Continue held with Enter', () => {
  test.use({ seedConfig: 'newznab_two_stored#wizard-held-enter' });

  test('sends one group save', async ({ page }) => {
    test.info().annotations.push(...combineGroupWriter());
    const requests = await recordWizardRequests(page);
    await openProvidersStep(page);
    await urlInput(page, 1).fill('https://placeholder-one-held.invalid/api');
    await continueButton(page).focus();

    for (let i = 0; i < 5; i++) await page.keyboard.down('Enter');
    await page.keyboard.up('Enter');
    await expect(providersHeading(page)).toBeHidden({ timeout: 10000 });

    expect(requests.groupSaves()).toHaveLength(1);
  });
});

// ─────────────────────────────────────────────────────────────────────────────
// SEC-004 P5 (stage 5): cells the wizard must not alter, the shapes only the
// real reader can judge, and what must never leave the page.
// ─────────────────────────────────────────────────────────────────────────────

test.describe('cells with %, +, &, = and an encoded comma', () => {
  test.use({ seedConfig: 'newznab_hostile_cells#wizard-hostile-key' });

  test('a key typed with them is stored as typed, and a later edit elsewhere leaves every cell byte-identical', async ({ page, testServer }) => {
    test.info().annotations.push(...combineGroupWriter());
    const original = rowsOf(configColumns(testServer.configPath, 'newznab'));
    const typed = 'placeholder%key+and&equals=%2Cend';
    await openProvidersStep(page);

    await page.getByRole('button', { name: '+ Add another indexer' }).click();
    await urlInput(page, 4).fill('https://placeholder-four.invalid/api?a=b&c=d+e');
    await keyInput(page, 4).fill(typed);
    await advance(page);

    const afterFirst = rowsOf(configColumns(testServer.configPath, 'newznab'));
    expect(afterFirst.slice(0, 3)).toEqual(original);
    expect(afterFirst[3]).toEqual({ use: '1', host: 'https://placeholder-four.invalid/api?a=b&c=d+e', api_key: typed, extra_score: '0', custom_tag: '' });

    // A reload, then an edit to a DIFFERENT row: every other cell, every column's count, unchanged.
    await openProvidersStep(page);
    await expect(keyInput(page, 4)).toHaveValue(typed);
    await urlInput(page, 1).fill('https://placeholder-one-moved.invalid/api?x=a%2Cb&y=1+2=z');
    await advance(page);

    const afterSecond = rowsOf(configColumns(testServer.configPath, 'newznab'));
    expect(afterSecond).toHaveLength(4);
    expect(afterSecond.slice(1)).toEqual(afterFirst.slice(1));
    expect(afterSecond[0]).toEqual({ ...afterFirst[0], host: 'https://placeholder-one-moved.invalid/api?x=a%2Cb&y=1+2=z' });
    expect(configView(testServer.configPath, 'newznab')).toEqual(viewOf(afterSecond));
  });
});

test.describe('a legacy bytes-literal stored group', () => {
  test.use({ seedConfig: 'newznab_legacy_bytes#wizard-legacy-edit' });

  test('is read as the rows it holds, and an edit rewrites it as plain rows with the other row intact', async ({ page, testServer }) => {
    test.info().annotations.push(...combineGroupWriter());
    await openProvidersStep(page);
    await expect(urlInput(page, 2)).toHaveValue('https://placeholder-two.invalid/api');

    await urlInput(page, 1).fill('https://placeholder-one-edited.invalid/api');
    await advance(page);

    const columns = configColumns(testServer.configPath, 'newznab');
    for (const name of NEWZNAB_COLUMNS) expect(columns[name], `${name} still wrapped as a bytes literal`).not.toMatch(/^b'/);
    const expected = [
      { use: '1', host: 'https://placeholder-one-edited.invalid/api', api_key: 'placeholder-key-one', extra_score: '0', custom_tag: '' },
      { use: '0', host: 'https://placeholder-two.invalid/api', api_key: 'placeholder-key-two', extra_score: '0', custom_tag: '' },
    ];
    expect(rowsOf(columns)).toEqual(expected);
    expect(configView(testServer.configPath, 'newznab')).toEqual(viewOf(expected));
  });
});

test.describe('a hostless row that carries a key', () => {
  test.use({ seedConfig: 'newznab_hostless#wizard-hostless-edit' });

  test('survives an edit of a stored indexer: its key is still at its position, beside no host', async ({ page, testServer }) => {
    test.info().annotations.push(...combineGroupWriter());
    const original = rowsOf(configColumns(testServer.configPath, 'newznab'));
    await openProvidersStep(page);

    await urlInput(page, 2).fill('https://placeholder-bravo-moved.invalid/api');
    await advance(page);

    const expected = original.map((row, i) => (i === 3 ? { ...row, host: 'https://placeholder-bravo-moved.invalid/api' } : row));
    expect(rowsOf(configColumns(testServer.configPath, 'newznab'))).toEqual(expected);
    expect(expected[2].api_key).toBe('placeholder-key-hostless');
    expect(configView(testServer.configPath, 'newznab')).toEqual(viewOf(expected));
  });
});

test.describe('a whole wizard with two Newznab rows', () => {
  test.use({ seedConfig: 'fresh_defaults#wizard-complete-two-rows' });

  test('saves the group once, never a combine column on its own, and the reader pairs each key with its host', async ({ page, testServer }) => {
    test.info().annotations.push(...combineGroupWriter());
    const requests = await recordWizardRequests(page);
    await openProvidersStep(page);
    await newznabSwitch(page).click();
    await page.getByRole('button', { name: '+ Add another indexer' }).click();
    await urlInput(page, 1).fill('https://placeholder-first.invalid/api');
    await keyInput(page, 1).fill('placeholder-key-first');
    await urlInput(page, 2).fill('https://placeholder-second.invalid/api');
    await keyInput(page, 2).fill('placeholder-key-second');

    await advance(page);                                                   // Providers -> Downloader
    await continueButton(page).click();                                    // Downloader -> Library
    await page.getByRole('button', { name: 'Finish Setup' }).click();      // Library -> Done
    await expect(page.getByRole('heading', { name: "You're All Set!" })).toBeVisible({ timeout: 10000 });

    const combineNames = new Set(NEWZNAB_COLUMNS);
    const perColumn = requests.columnSaves()
      .map((request) => new URLSearchParams(request.body))
      .filter((params) => params.get('section') === 'newznab' && combineNames.has(params.get('name') || ''));
    expect(perColumn, 'a combine column was saved on its own').toEqual([]);
    expect(requests.groupSaves()).toHaveLength(1);
    const view = configView(testServer.configPath, 'newznab') as unknown[][];
    expect(view.slice(-2).map((row) => [row[1], row[2]])).toEqual([
      ['https://placeholder-first.invalid/api', 'placeholder-key-first'],
      ['https://placeholder-second.invalid/api', 'placeholder-key-second'],
    ]);
  });
});

/** Every text change in a live region, from before the first script runs. */
async function watchLiveRegions(page: Page) {
  await page.addInitScript(() => {
    const texts: string[] = [];
    (window as any).__liveTexts = texts;
    const selector = '[aria-live], [role="status"], [role="alert"], output';
    new MutationObserver((records) => {
      for (const record of records) {
        const node = record.target instanceof Element ? record.target : record.target.parentElement;
        const region = node?.closest(selector);
        if (region?.textContent) texts.push(region.textContent);
      }
    }).observe(document, { subtree: true, childList: true, characterData: true });
  });
  return () => page.evaluate(() => (window as any).__liveTexts as string[]);
}

test.describe('what must never leave the page (a distinctive word in every cell)', () => {
  test.use({ seedConfig: 'newznab_sentinels#wizard-sentinels' });

  test('no request URL, console line, live-region text or visible text holds a stored key, tag or host', async ({ page, testServer }) => {
    test.info().annotations.push(...combineGroupWriter());
    const requests = await recordWizardRequests(page);
    const liveTexts = await watchLiveRegions(page);
    const consoleLines: string[] = [];
    page.on('console', (message) => consoleLines.push(message.text()));
    page.on('pageerror', (error) => consoleLines.push(error.message));
    const visible: string[] = [];
    const sentinels = ['sentinel-key', 'sentinel-tag', 'sentinel-host'];

    await openProvidersStep(page);
    visible.push(await page.locator('body').innerText());
    await page.evaluate(() => {
      const root = document.querySelector('[x-data="setupWizard()"]') as HTMLElement;
      (window as any).Alpine.$data(root).assertNewznabHasNoCommas = () => undefined;
    });
    await urlInput(page, 1).fill('https://placeholder-sentinel-host-one.invalid/api,x');   // the server refuses it
    await continueButton(page).click();
    await expect(page.getByTestId('wizard-newznab-error')).toContainText('cannot contain a comma');
    visible.push(await page.locator('body').innerText());

    await urlInput(page, 1).fill('https://placeholder-sentinel-host-one.invalid/api?moved=1');
    await advance(page);
    await continueButton(page).click();
    await page.getByRole('button', { name: 'Finish Setup' }).click();
    await expect(page.getByRole('heading', { name: "You're All Set!" })).toBeVisible({ timeout: 10000 });
    visible.push(await page.locator('body').innerText());

    expect(requests.groupSaves().length).toBeGreaterThan(0);
    for (const word of sentinels) {
      expect(requests.seen.filter((request) => request.url.includes(word)), `${word} in a request URL`).toEqual([]);
      expect(consoleLines.filter((line) => line.includes(word)), `${word} in the console`).toEqual([]);
      expect((await liveTexts()).filter((text) => text.includes(word)), `${word} in a live region`).toEqual([]);
      expect(visible.filter((text) => text.includes(word)), `${word} in visible text`).toEqual([]);
    }
    expect(configView(testServer.configPath, 'newznab')).toHaveLength(2);
  });
});
