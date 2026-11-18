import { test, expect, type APIRequestContext, type Locator, type Page } from './fixtures';
import { configColumns, configSection, configSha, openProvidersStep, recordWizardRequests, waitForNewznabRead, watchLiveRegions } from './helpers';
import { combineGroupWriter } from './settings_persistence';

/**
 * Owner decision 2026-11-18 (AC-DATA-23, reversing D5 for the wizard only): before the
 * wizard sends a Newznab group save it reads the settings again and compares what is
 * stored with the baseline its edits were built on.
 *
 *  - unchanged: the group is saved as before;
 *  - changed (a cell of any row, hidden rows included, the row count): NOTHING newznab is
 *    written, `enabled` included, the step does not advance, the rows and the baseline are
 *    replaced by the fresh read, and one persistent message says so;
 *  - the re-read fails, is malformed or times out: nothing is written and the existing
 *    read-failure state (with Retry) is shown.
 *
 * "Another tab" is a SECOND request context calling the real group route on the same
 * server between the wizard's load and its Continue. What was written is asserted from
 * `config.ini` (`tests.helpers.config_readback`), never from a request body. Every test
 * writes a combine group, so each has its own `seedConfig` server. Keys and hosts are
 * placeholders.
 */

type Row = { use: string; host: string; api_key: string; extra_score: string; custom_tag: string };

const READ_ROUTE = /\/settings\/(\?.*)?$/;
const COLUMNS = ['use', 'host', 'api_key', 'extra_score', 'custom_tag'] as const;
const EDITED_URL = 'https://placeholder-wizard-edit.invalid/api';
const NOT_LOADED = /saved Newznab indexers could not be loaded.*cannot continue until they load/is;
const CHANGED = /changed since this page opened.*unsaved edits.*discarded.*rows shown have been reloaded/is;

const urlInput = (page: Page, n: number) => page.getByLabel(`Newznab indexer URL ${n}`);
const keyInput = (page: Page, n: number) => page.getByLabel(`Newznab API key ${n}`);
const providersHeading = (page: Page) => page.getByRole('heading', { name: 'Where to Search' });
const continueButton = (page: Page) => page.getByRole('button', { name: /^(Continue|Saving…)$/ });
const errorMessage = (page: Page) => page.getByTestId('wizard-newznab-error');
const retryButton = (page: Page) => page.getByRole('button', { name: 'Try loading saved indexers again' });

/** The stored columns as rows of cells, nothing trimmed. */
function rowsOf(columns: Record<string, string | null>): Row[] {
  const cells = Object.fromEntries(COLUMNS.map((name) => [name, (columns[name] ?? '').split(',')]));
  const count = Math.max(...Object.values(cells).map((list) => list.length));
  return Array.from({ length: count }, (_, i) => Object.fromEntries(COLUMNS.map((name) => [name, cells[name][i] ?? ''])) as Row);
}

/** Another tab: the real group route, from a request context that is not the wizard's page. */
async function otherTabSaves(request: APIRequestContext, apiBase: string, rows: Row[]) {
  const response = await request.post(`${apiBase}/settings.save_group/`, { data: { section: 'newznab', rows } });
  expect(response.ok(), 'the other tab\'s save was refused').toBe(true);
  expect((await response.json()).success).toBe(true);
}

/** Open the Providers step and wait until the stored rows are on screen. */
async function openWithRows(page: Page, firstUrl: string) {
  await openProvidersStep(page);
  await waitForNewznabRead(page);
  await expect(urlInput(page, 1)).toHaveValue(firstUrl);
}

const isOn = (value: string | undefined) => /^(1|true)$/i.test(value ?? '');

/**
 * The store is changed by another tab after the wizard loaded and the user edited row 1's
 * URL; then Continue. Everything the owner decision requires of the changed path, in one place.
 */
async function expectChangedPath(page: Page, testServer: { configPath: string }, requests: Awaited<ReturnType<typeof recordWizardRequests>>, theirs: Row[], enabledBefore: string | undefined) {
  await expect(errorMessage(page)).toContainText(CHANGED);
  // Nothing newznab written, the `enabled` line included, and the step did not advance.
  expect(await requests.pageWrites(), 'the changed path wrote something').toEqual([]);
  expect(requests.groupSaves().concat(requests.columnSaves())).toEqual([]);
  expect(rowsOf(configColumns(testServer.configPath, 'newznab'))).toEqual(theirs);
  expect(configSection(testServer.configPath, 'newznab').enabled).toBe(enabledBefore);
  await expect(providersHeading(page)).toBeVisible();
  await expect(continueButton(page)).toHaveAttribute('aria-disabled', 'false');
  // Nothing stale on screen: the rows are the fresh read and the user's edit is gone.
  await expect(urlInput(page, 1)).toHaveValue(theirs.filter((row) => row.host && row.api_key)[0].host);
  const shown = await page.locator('[data-newznab-host]').evaluateAll((inputs) => inputs.map((input) => (input as HTMLInputElement).value));
  expect(shown, 'the user\'s unsaved edit is still on screen').not.toContain(EDITED_URL);
  expect(shown).toEqual(theirs.filter((row) => row.host.trim() && row.api_key.trim()).map((row) => row.host));
  // Focus goes somewhere sensible, never to body.
  await expect(urlInput(page, 1)).toBeFocused();
}

test.describe('the stored indexers changed in another tab after the wizard loaded', () => {
  test.describe('a key rotated to another value of the same length', () => {
    test.use({ seedConfig: 'newznab_two_stored#wizard-reread-key-rotated' });

    test('writes nothing, reloads the rows, says so once, and a second Continue advances with no group save', async ({ page, request, testServer }) => {
      test.info().annotations.push(...combineGroupWriter());
      const readLive = await watchLiveRegions(page);
      const requests = await recordWizardRequests(page);
      await openWithRows(page, 'https://placeholder-one.invalid/api');

      // What the read returns for a key: the text, not a mask (measured, not assumed).
      const read = await (await request.get(`${testServer.apiBase}/settings/`)).json();
      expect(read.values.newznab.api_key).toBe('placeholder-key-one,placeholder-key-two');

      const stored = rowsOf(configColumns(testServer.configPath, 'newznab'));
      const rotated = stored.map((row, i) => (i === 0 ? { ...row, api_key: 'placeholder-key-ONE' } : row));
      expect(rotated[0].api_key).toHaveLength(stored[0].api_key.length);
      await otherTabSaves(request, testServer.apiBase, rotated);
      const theirs = rowsOf(configColumns(testServer.configPath, 'newznab'));
      expect(theirs[0].api_key).toBe('placeholder-key-ONE');
      const enabledBefore = configSection(testServer.configPath, 'newznab').enabled;

      await urlInput(page, 1).fill(EDITED_URL);
      await continueButton(page).click();

      await expectChangedPath(page, testServer, requests, theirs, enabledBefore);
      // Announced once: the message is the page's single speech for this attempt.
      const spoken = (await readLive()).filter((text) => /changed since this page opened/.test(text));
      expect(spoken, 'the changed message was announced more than once').toHaveLength(1);
      await expect(page.getByTestId('toast-announcer-assertive')).toContainText(CHANGED);

      // A second Continue with no further edit advances, and sends no group save.
      await continueButton(page).click();
      await expect(providersHeading(page)).toBeHidden({ timeout: 10000 });
      expect(requests.groupSaves(), 'the second Continue wrote the group').toEqual([]);
      expect(rowsOf(configColumns(testServer.configPath, 'newznab'))).toEqual(theirs);
      expect(isOn(configSection(testServer.configPath, 'newznab').enabled)).toBe(isOn(enabledBefore));
    });
  });

  test.describe('a hidden row', () => {
    test.use({ seedConfig: 'newznab_interleaved#wizard-reread-hidden-row' });

    test('changed by the other tab is detected although the wizard shows no such row', async ({ page, request, testServer }) => {
      test.info().annotations.push(...combineGroupWriter());
      const requests = await recordWizardRequests(page);
      await openWithRows(page, 'https://placeholder-alpha.invalid/api');
      const stored = rowsOf(configColumns(testServer.configPath, 'newznab'));
      expect(stored[0].api_key, 'row 1 must be a hidden (keyless) row').toBe('');
      await otherTabSaves(request, testServer.apiBase, stored.map((row, i) => (i === 0 ? { ...row, custom_tag: 'other-tab-tag' } : row)));
      const theirs = rowsOf(configColumns(testServer.configPath, 'newznab'));
      const enabledBefore = configSection(testServer.configPath, 'newznab').enabled;

      await urlInput(page, 1).fill(EDITED_URL);
      await continueButton(page).click();

      await expectChangedPath(page, testServer, requests, theirs, enabledBefore);
      expect(theirs[0].custom_tag).toBe('other-tab-tag');
    });
  });

  test.describe('a row added', () => {
    test.use({ seedConfig: 'newznab_two_stored#wizard-reread-row-added' });

    test('is detected by the row count, and the new row is then on screen', async ({ page, request, testServer }) => {
      test.info().annotations.push(...combineGroupWriter());
      const requests = await recordWizardRequests(page);
      await openWithRows(page, 'https://placeholder-one.invalid/api');
      const stored = rowsOf(configColumns(testServer.configPath, 'newznab'));
      await otherTabSaves(request, testServer.apiBase, [...stored, {
        use: '1', host: 'https://placeholder-three.invalid/api', api_key: 'placeholder-key-three', extra_score: '0', custom_tag: '',
      }]);
      const theirs = rowsOf(configColumns(testServer.configPath, 'newznab'));
      const enabledBefore = configSection(testServer.configPath, 'newznab').enabled;

      await urlInput(page, 1).fill(EDITED_URL);
      await continueButton(page).click();

      await expectChangedPath(page, testServer, requests, theirs, enabledBefore);
      await expect(urlInput(page, 3)).toHaveValue('https://placeholder-three.invalid/api');
      await expect(keyInput(page, 3)).toHaveValue('placeholder-key-three');
    });
  });

  test.describe('and the user edits again after the reload', () => {
    test.use({ seedConfig: 'newznab_two_stored#wizard-reread-edit-after-reload' });

    test('the baseline is the fresh read, so the next edit is saved on top of what the other tab wrote', async ({ page, request, testServer }) => {
      test.info().annotations.push(...combineGroupWriter());
      const requests = await recordWizardRequests(page);
      await openWithRows(page, 'https://placeholder-one.invalid/api');
      const stored = rowsOf(configColumns(testServer.configPath, 'newznab'));
      await otherTabSaves(request, testServer.apiBase, stored.map((row, i) => (i === 1 ? { ...row, custom_tag: 'other-tab-tag' } : row)));
      await urlInput(page, 1).fill(EDITED_URL);
      await continueButton(page).click();
      await expect(errorMessage(page)).toContainText(CHANGED);

      await urlInput(page, 1).fill('https://placeholder-second-edit.invalid/api');
      await continueButton(page).click();

      await expect(providersHeading(page)).toBeHidden({ timeout: 10000 });
      expect(requests.groupSaves()).toHaveLength(1);
      const now = rowsOf(configColumns(testServer.configPath, 'newznab'));
      expect(now[0].host).toBe('https://placeholder-second-edit.invalid/api');
      expect(now[1].custom_tag, 'the other tab\'s row was lost').toBe('other-tab-tag');
    });
  });
});

test.describe('the stored indexers did not change', () => {
  test.describe('an edit', () => {
    test.use({ seedConfig: 'newznab_two_stored#wizard-reread-unchanged-edit' });

    test('is saved as before, after exactly one more read of the settings', async ({ page, testServer }) => {
      test.info().annotations.push(...combineGroupWriter());
      const requests = await recordWizardRequests(page);
      await openWithRows(page, 'https://placeholder-one.invalid/api');
      const readsBefore = requests.settingsReads().length;

      await urlInput(page, 1).fill(EDITED_URL);
      await continueButton(page).click();
      await expect(providersHeading(page)).toBeHidden({ timeout: 10000 });

      expect(requests.settingsReads().length, 'the group save was not preceded by one re-read').toBe(readsBefore + 1);
      expect(requests.groupSaves()).toHaveLength(1);
      const now = rowsOf(configColumns(testServer.configPath, 'newznab'));
      expect(now[0].host).toBe(EDITED_URL);
      expect(now[1].host).toBe('https://placeholder-two.invalid/api');
    });

  });

  test.describe('an edit, Back, and a second edit', () => {
    test.use({ seedConfig: 'newznab_two_stored#wizard-reread-second-edit' });

    test('is saved too: the rows the wizard wrote are the next baseline, not another tab\'s change', async ({ page, testServer }) => {
      test.info().annotations.push(...combineGroupWriter());
      const requests = await recordWizardRequests(page);
      await openWithRows(page, 'https://placeholder-one.invalid/api');
      await urlInput(page, 1).fill(EDITED_URL);
      await continueButton(page).click();
      await expect(providersHeading(page)).toBeHidden({ timeout: 10000 });

      await page.getByRole('button', { name: /Back$/ }).click();
      await expect(providersHeading(page)).toBeVisible();
      await urlInput(page, 2).fill('https://placeholder-two-edit.invalid/api');
      await continueButton(page).click();
      await expect(providersHeading(page)).toBeHidden({ timeout: 10000 });

      expect(requests.groupSaves(), 'the wizard\'s own earlier save was taken for another tab\'s change').toHaveLength(2);
      const now = rowsOf(configColumns(testServer.configPath, 'newznab'));
      expect([now[0].host, now[1].host]).toEqual([EDITED_URL, 'https://placeholder-two-edit.invalid/api']);
    });
  });

  // The baseline after a save is the rows the wizard SENT; the re-read is what the server then
  // holds. If the server normalised them (an emptied group is stored as one all-empty row), the
  // wizard's own write would be mistaken for another tab's on the next Continue.
  test.describe('after the wizard emptied the group itself', () => {
    test.use({ seedConfig: 'newznab_two_stored#wizard-reread-emptied-then-added' });

    test('its own all-empty row is not taken for a change, and a new indexer is then saved', async ({ page, testServer }) => {
      test.info().annotations.push(...combineGroupWriter());
      const requests = await recordWizardRequests(page);
      await openWithRows(page, 'https://placeholder-one.invalid/api');
      await page.getByRole('button', { name: 'Remove indexer 2' }).click();
      await urlInput(page, 1).fill('');
      await continueButton(page).click();
      await expect(providersHeading(page)).toBeHidden({ timeout: 10000 });
      expect(requests.groupSaves()).toHaveLength(1);

      await page.getByRole('button', { name: /Back$/ }).click();
      await expect(providersHeading(page)).toBeVisible();
      await urlInput(page, 1).fill(EDITED_URL);
      await keyInput(page, 1).fill('placeholder-key-new');
      await continueButton(page).click();

      await expect(providersHeading(page)).toBeHidden({ timeout: 10000 });
      expect(requests.groupSaves()).toHaveLength(2);
      // The all-empty row the first save stored is a hidden row (AC-DATA-20), so it stays and the new indexer follows it.
      expect(rowsOf(configColumns(testServer.configPath, 'newznab'))).toEqual([
        { use: '', host: '', api_key: '', extra_score: '', custom_tag: '' },
        { use: '1', host: EDITED_URL, api_key: 'placeholder-key-new', extra_score: '0', custom_tag: '' },
      ]);
    });
  });

  test.describe('no edit', () => {
    test.use({ seedConfig: 'newznab_two_stored#wizard-reread-no-edit' });

    test('sends no group save and does not read the settings again', async ({ page }) => {
      test.info().annotations.push(...combineGroupWriter());
      const requests = await recordWizardRequests(page);
      await openWithRows(page, 'https://placeholder-one.invalid/api');
      const readsBefore = requests.settingsReads().length;

      await continueButton(page).click();
      await expect(providersHeading(page)).toBeHidden({ timeout: 10000 });

      expect(requests.groupSaves()).toEqual([]);
      expect(requests.settingsReads().length, 'a Continue that changed nothing re-read the settings').toBe(readsBefore);
    });
  });
});

test.describe('the re-read itself fails', () => {
  const FAILURES: [string, string, (page: Page) => Promise<void>][] = [
    ['an HTTP 500', 'http-500', (page) => page.route(READ_ROUTE, (route) => route.fulfill({ status: 500, contentType: 'application/json', body: '{"success": false}' }))],
    ['an answer that is not JSON', 'not-json', (page) => page.route(READ_ROUTE, (route) => route.fulfill({ status: 200, contentType: 'text/html', body: '<html>proxy error</html>' }))],
    ['an answer with no newznab section', 'no-section', (page) => page.route(READ_ROUTE, (route) => route.fulfill({ status: 200, contentType: 'application/json', body: '{"options": {}, "values": {}, "combine_state": {}}' }))],
    ['a dropped connection', 'dropped', (page) => page.route(READ_ROUTE, (route) => route.abort())],
  ];

  for (const [name, label, fail] of FAILURES) {
    test.describe(name, () => {
      test.use({ seedConfig: `newznab_two_stored#wizard-reread-fails-${label}` });

      // Owner decision (fix round 1): a failed RE-read costs the user nothing when the store
      // did not change. The edits are held in page memory; Retry brings the rows back with them.
      test('writes nothing and does not advance; Retry, the store unchanged, brings the rows back WITH the edits, and Continue then saves them', async ({ page, testServer }) => {
        test.info().annotations.push(...combineGroupWriter());
        const readLive = await watchLiveRegions(page);
        const requests = await recordWizardRequests(page);
        await openWithRows(page, 'https://placeholder-one.invalid/api');
        await urlInput(page, 1).fill(EDITED_URL);
        await page.getByRole('button', { name: '+ Add another indexer' }).click();
        await urlInput(page, 3).fill('https://placeholder-three.invalid/api');
        await keyInput(page, 3).fill('placeholder-key-three');
        await keyInput(page, 2).fill('placeholder-key-typed');
        const baseline = configSha(testServer.configPath);
        await fail(page);

        await continueButton(page).click();

        await expect(errorMessage(page)).toContainText(NOT_LOADED);
        await expect(retryButton(page)).toBeVisible();
        await expect(retryButton(page)).toBeFocused();
        await expect(providersHeading(page)).toBeVisible();
        expect(await requests.pageWrites(), 'a failed re-read was followed by a write').toEqual([]);
        expect(configSha(testServer.configPath), 'config.ini changed').toBe(baseline);

        await page.unroute(READ_ROUTE);
        await retryButton(page).click();

        // The store did not change, so the edits are still there, and the state is as it was before the failure.
        await expect(errorMessage(page)).toBeHidden();
        await expect(urlInput(page, 1)).toHaveValue(EDITED_URL);
        await expect(urlInput(page, 3)).toHaveValue('https://placeholder-three.invalid/api');
        await expect(keyInput(page, 3)).toHaveValue('placeholder-key-three');
        await expect(keyInput(page, 2)).toHaveValue('placeholder-key-typed');
        await expect(urlInput(page, 1)).toBeFocused();
        const loaded = (await readLive()).filter((text) => /saved Newznab indexers have loaded/.test(text));
        expect(loaded, 'the load was announced other than once').toHaveLength(1);
        expect(configSha(testServer.configPath)).toBe(baseline);

        await continueButton(page).click();
        await expect(providersHeading(page)).toBeHidden({ timeout: 10000 });
        expect(requests.groupSaves()).toHaveLength(1);
        const now = rowsOf(configColumns(testServer.configPath, 'newznab'));
        expect(now.map((row) => [row.host, row.api_key])).toEqual([
          [EDITED_URL, 'placeholder-key-one'],
          ['https://placeholder-two.invalid/api', 'placeholder-key-typed'],
          ['https://placeholder-three.invalid/api', 'placeholder-key-three'],
        ]);
      });
    });
  }

  // The held edits must survive leaving the step and coming back, not only a Retry on the spot:
  // a user who is told the indexers could not be loaded may well press Back first.
  test.describe('a failed re-read, then Back, then the Providers step again', () => {
    test.use({ seedConfig: 'newznab_two_stored#wizard-reread-back-then-retry' });

    test('Retry on an unchanged store gives back the held edits, and the next Continue saves them', async ({ page, testServer }) => {
      test.info().annotations.push(...combineGroupWriter());
      const requests = await recordWizardRequests(page);
      await openWithRows(page, 'https://placeholder-one.invalid/api');
      await urlInput(page, 1).fill(EDITED_URL);
      await keyInput(page, 2).fill('placeholder-key-typed');
      const baseline = configSha(testServer.configPath);
      await page.route(READ_ROUTE, (route) => route.fulfill({ status: 500, contentType: 'application/json', body: '{"success": false}' }));
      await continueButton(page).click();
      await expect(errorMessage(page)).toContainText(NOT_LOADED);
      await expect(retryButton(page)).toBeVisible();

      await page.getByRole('button', { name: /Back$/ }).click();
      await expect(providersHeading(page)).toBeHidden();
      await page.getByRole('button', { name: /Continue/i }).click();
      await expect(providersHeading(page)).toBeVisible();
      await page.unroute(READ_ROUTE);
      await expect(retryButton(page)).toBeVisible();
      await retryButton(page).click();

      await expect(errorMessage(page)).toBeHidden();
      await expect(urlInput(page, 1)).toHaveValue(EDITED_URL);
      await expect(keyInput(page, 2)).toHaveValue('placeholder-key-typed');
      expect(await requests.pageWrites(), 'something was written before the second Continue').toEqual([]);
      expect(configSha(testServer.configPath)).toBe(baseline);

      await continueButton(page).click();
      await expect(providersHeading(page)).toBeHidden({ timeout: 10000 });
      expect(requests.groupSaves()).toHaveLength(1);
      const now = rowsOf(configColumns(testServer.configPath, 'newznab'));
      expect(now.map((row) => [row.host, row.api_key])).toEqual([
        [EDITED_URL, 'placeholder-key-one'],
        ['https://placeholder-two.invalid/api', 'placeholder-key-typed'],
      ]);
    });
  });

  test.describe('an answer that never comes', () => {
    test.use({ seedConfig: 'newznab_two_stored#wizard-reread-fails-timeout' });

    test('counts as failed after its 15 seconds: nothing written, Retry shown', async ({ page, testServer }) => {
      test.info().annotations.push(...combineGroupWriter());
      await page.clock.install();
      const requests = await recordWizardRequests(page);
      await openWithRows(page, 'https://placeholder-one.invalid/api');
      await urlInput(page, 1).fill(EDITED_URL);
      const baseline = configSha(testServer.configPath);
      await page.route(READ_ROUTE, () => new Promise(() => undefined));

      await continueButton(page).click();
      await expect(continueButton(page)).toHaveAttribute('aria-disabled', 'true');
      await page.clock.fastForward(16000);

      await expect(errorMessage(page)).toContainText(NOT_LOADED);
      await expect(retryButton(page)).toBeVisible();
      // Focus goes to the way out, as it does for a failed first read. The retry button is shown a
      // frame after the state changes, so this fails if focus is moved before it is visible.
      await expect(retryButton(page)).toBeFocused();
      expect(await requests.pageWrites()).toEqual([]);
      expect(configSha(testServer.configPath)).toBe(baseline);
    });
  });

  test.describe('the store changed while the re-read was failing', () => {
    test.use({ seedConfig: 'newznab_two_stored#wizard-reread-fail-then-changed' });

    test('Retry then behaves as the changed path: the rows and baseline are reloaded, the edits discarded, the changed message shown', async ({ page, request, testServer }) => {
      test.info().annotations.push(...combineGroupWriter());
      const readLive = await watchLiveRegions(page);
      const requests = await recordWizardRequests(page);
      await openWithRows(page, 'https://placeholder-one.invalid/api');
      await urlInput(page, 1).fill(EDITED_URL);
      await page.route(READ_ROUTE, (route) => route.fulfill({ status: 500, contentType: 'application/json', body: '{"success": false}' }));
      await continueButton(page).click();
      await expect(errorMessage(page)).toContainText(NOT_LOADED);
      const stored = rowsOf(configColumns(testServer.configPath, 'newznab'));
      await otherTabSaves(request, testServer.apiBase, stored.map((row, i) => (i === 1 ? { ...row, custom_tag: 'other-tab-tag' } : row)));
      const theirs = rowsOf(configColumns(testServer.configPath, 'newznab'));

      await page.unroute(READ_ROUTE);
      await retryButton(page).click();

      await expect(errorMessage(page)).toContainText(CHANGED);
      await expect(errorMessage(page)).not.toContainText('could not be loaded');
      await expect(urlInput(page, 1)).toHaveValue('https://placeholder-one.invalid/api');
      const shown = await page.locator('[data-newznab-host]').evaluateAll((inputs) => inputs.map((input) => (input as HTMLInputElement).value));
      expect(shown, 'the discarded edit is still on screen').not.toContain(EDITED_URL);
      await expect(urlInput(page, 1)).toBeFocused();
      const spoken = (await readLive()).filter((text) => /changed since this page opened/.test(text));
      expect(spoken, 'the changed message was announced other than once').toHaveLength(1);
      expect(await requests.pageWrites()).toEqual([]);
      expect(rowsOf(configColumns(testServer.configPath, 'newznab'))).toEqual(theirs);

      // The baseline is now the fresh read: the next Continue, no further edit, advances with no group save.
      await continueButton(page).click();
      await expect(providersHeading(page)).toBeHidden({ timeout: 10000 });
      expect(requests.groupSaves()).toEqual([]);
    });
  });

  test.describe('two failed retries, then one that works', () => {
    test.use({ seedConfig: 'newznab_two_stored#wizard-reread-double-failure' });

    test('stays failed with the edits held, and the edits are back once a retry succeeds', async ({ page, testServer }) => {
      test.info().annotations.push(...combineGroupWriter());
      const requests = await recordWizardRequests(page);
      await openWithRows(page, 'https://placeholder-one.invalid/api');
      await urlInput(page, 1).fill(EDITED_URL);
      const baseline = configSha(testServer.configPath);
      await page.route(READ_ROUTE, (route) => route.fulfill({ status: 500, contentType: 'application/json', body: '{"success": false}' }));
      await continueButton(page).click();
      await expect(errorMessage(page)).toContainText(NOT_LOADED);

      for (const attempt of [1, 2]) {
        const reads = requests.settingsReads().length;
        await retryButton(page).click();
        await expect.poll(() => requests.settingsReads().length, `retry ${attempt} did not read`).toBeGreaterThan(reads);
        await expect(errorMessage(page)).toContainText(NOT_LOADED);
        await expect(retryButton(page)).toBeFocused();
        await expect(urlInput(page, 1)).toHaveCount(0);
      }

      await page.unroute(READ_ROUTE);
      await retryButton(page).click();

      await expect(errorMessage(page)).toBeHidden();
      await expect(urlInput(page, 1)).toHaveValue(EDITED_URL);
      expect(await requests.pageWrites()).toEqual([]);
      expect(configSha(testServer.configPath)).toBe(baseline);
    });
  });
});

// AC-DATA-23(b): where focus goes after the rows are replaced, and what describes the control that
// takes it. The message must be read with that control (a focus move can cut off an announcement),
// and the description must come off when the message does.
test.describe('the message describes the control that takes focus after a reload', () => {
  const DESCRIBED = 'wizard-newznab-error';

  /** Back to Providers after advancing: the message is gone and no control still points at it. */
  async function expectNothingDescribedAfterContinue(page: Page, controls: Locator[]) {
    await continueButton(page).click();
    await expect(providersHeading(page)).toBeHidden({ timeout: 10000 });
    await page.getByRole('button', { name: /Back$/ }).click();
    await expect(providersHeading(page)).toBeVisible();
    await expect(errorMessage(page)).toBeHidden();
    for (const control of controls) await expect(control).not.toHaveAttribute('aria-describedby', /./);
  }

  test.describe('the first URL (the rows are shown)', () => {
    test.use({ seedConfig: 'newznab_two_stored#wizard-reread-describes-host' });

    test('is described by the message, and not once the message is gone', async ({ page, request, testServer }) => {
      test.info().annotations.push(...combineGroupWriter());
      await openWithRows(page, 'https://placeholder-one.invalid/api');
      const stored = rowsOf(configColumns(testServer.configPath, 'newznab'));
      await otherTabSaves(request, testServer.apiBase, stored.map((row, i) => (i === 1 ? { ...row, custom_tag: 'other-tab-tag' } : row)));

      await urlInput(page, 1).fill(EDITED_URL);
      await continueButton(page).click();

      await expect(errorMessage(page)).toContainText(CHANGED);
      await expect(urlInput(page, 1)).toBeFocused();
      await expect(urlInput(page, 1)).toHaveAttribute('aria-describedby', DESCRIBED);
      // Only the control that took focus: not the second URL, the keys, the switch or Continue.
      await expect(page.locator(`[aria-describedby~="${DESCRIBED}"]`)).toHaveCount(1);
      await expect(page.locator(`#${DESCRIBED}`)).toContainText('changed since this page opened');
      await expectNothingDescribedAfterContinue(page, [urlInput(page, 1)]);
    });
  });

  test.describe('the switch (the fresh read has Newznab off)', () => {
    test.use({ seedConfig: 'newznab_two_stored#wizard-reread-describes-switch' });

    test('takes focus, is described by the message, says Newznab is off, and nothing is written', async ({ page, request, testServer }) => {
      test.info().annotations.push(...combineGroupWriter());
      const requests = await recordWizardRequests(page);
      await openWithRows(page, 'https://placeholder-one.invalid/api');
      const stored = rowsOf(configColumns(testServer.configPath, 'newznab'));
      await otherTabSaves(request, testServer.apiBase, stored.map((row, i) => (i === 1 ? { ...row, custom_tag: 'other-tab-tag' } : row)));
      // The other tab also switches Newznab off, through the real per-column route (`enabled` is not a combine column).
      const off = await request.post(`${testServer.apiBase}/settings.save/`, { form: { section: 'newznab', name: 'enabled', value: '0' } });
      expect((await off.json()).success).toBe(true);
      const enabledBefore = configSection(testServer.configPath, 'newznab').enabled;
      expect(isOn(enabledBefore)).toBe(false);
      const theirs = rowsOf(configColumns(testServer.configPath, 'newznab'));

      await urlInput(page, 1).fill(EDITED_URL);
      await continueButton(page).click();

      const message = errorMessage(page);
      await expect(message).toContainText(/changed since this page opened.*unsaved edits.*discarded/is);
      await expect(message).toContainText('Newznab is now shown switched off. Switch it on to use Newznab, or press Continue to leave it off.');
      await expect(message).not.toContainText('rows shown have been reloaded');
      const toggle = page.getByRole('switch', { name: 'Enable Newznab Indexers' });
      await expect(toggle).toHaveAttribute('aria-checked', 'false');
      await expect(toggle).toBeFocused();
      await expect(toggle).toHaveAttribute('aria-describedby', DESCRIBED);
      await expect(page.locator(`[aria-describedby~="${DESCRIBED}"]`)).toHaveCount(1);
      await expect(urlInput(page, 1)).toBeHidden();
      expect(await requests.pageWrites()).toEqual([]);
      expect(rowsOf(configColumns(testServer.configPath, 'newznab'))).toEqual(theirs);
      expect(configSection(testServer.configPath, 'newznab').enabled).toBe(enabledBefore);

      await expectNothingDescribedAfterContinue(page, [toggle]);
    });
  });

  // Switching Newznab ON answers "now shown switched off": the message is untrue from then on, so it
  // goes (AC-A11Y-17), and with it the description, which would otherwise move to the first URL.
  test.describe('the switch turned back on', () => {
    test.use({ seedConfig: 'newznab_two_stored#wizard-reread-switch-on' });

    test('clears the message and every description', async ({ page, request, testServer }) => {
      test.info().annotations.push(...combineGroupWriter());
      await openWithRows(page, 'https://placeholder-one.invalid/api');
      const stored = rowsOf(configColumns(testServer.configPath, 'newznab'));
      await otherTabSaves(request, testServer.apiBase, stored.map((row, i) => (i === 1 ? { ...row, custom_tag: 'other-tab-tag' } : row)));
      const off = await request.post(`${testServer.apiBase}/settings.save/`, { form: { section: 'newznab', name: 'enabled', value: '0' } });
      expect((await off.json()).success).toBe(true);
      await urlInput(page, 1).fill(EDITED_URL);
      await continueButton(page).click();
      const toggle = page.getByRole('switch', { name: 'Enable Newznab Indexers' });
      await expect(toggle).toHaveAttribute('aria-describedby', DESCRIBED);

      await toggle.click();

      await expect(toggle).toHaveAttribute('aria-checked', 'true');
      await expect(errorMessage(page)).toBeHidden();
      await expect(page.locator(`[aria-describedby~="${DESCRIBED}"]`)).toHaveCount(0);
      await expect(urlInput(page, 1)).toBeVisible();
    });
  });

  test.describe('Continue (the group no longer lines up)', () => {
    test.use({ seedConfig: 'newznab_two_stored#wizard-reread-describes-continue' });

    // The real group route cannot write a misaligned group (it writes every column to one row
    // count), so the second read is the real answer with `combine_state.newznab.misaligned` set.
    test('takes focus, is described by the message, shows no rows, and nothing is written', async ({ page, testServer }) => {
      test.info().annotations.push(...combineGroupWriter());
      const requests = await recordWizardRequests(page);
      await openWithRows(page, 'https://placeholder-one.invalid/api');
      const baseline = configSha(testServer.configPath);
      await page.route(READ_ROUTE, async (route) => {
        const real = await route.fetch();
        const body = await real.json();
        body.combine_state.newznab.misaligned = true;
        await route.fulfill({ response: real, json: body });
      });

      await urlInput(page, 1).fill(EDITED_URL);
      await continueButton(page).click();

      await expect(errorMessage(page)).toContainText('The saved entries now do not line up. Fix the rows in Settings, under Searchers, then Newznab.');
      await expect(page.getByTestId('combine-misaligned-notice')).toBeVisible();
      await expect(urlInput(page, 1)).toHaveCount(0);
      const next = page.locator('[data-wizard-continue]');
      await expect(next).toBeFocused();
      await expect(next).toHaveAttribute('aria-describedby', DESCRIBED);
      await expect(page.locator(`[aria-describedby~="${DESCRIBED}"]`)).toHaveCount(1);
      expect(await requests.pageWrites()).toEqual([]);
      expect(configSha(testServer.configPath)).toBe(baseline);

      // Continue is on every step, so the description holds only while the Newznab card is what the
      // user is on. The message itself stays (it is still true of the store, and a user who comes
      // back to the card should find it), but Continue is not described by a message that is hidden.
      await page.getByRole('radio', { name: /^Torrents/ }).click();
      await expect(next).not.toHaveAttribute('aria-describedby', /./);
      await expect(next).toHaveAccessibleDescription('');
      await page.getByRole('radio', { name: /^Usenet/ }).click();
      await expect(errorMessage(page)).toBeVisible();
      await expect(next).toHaveAttribute('aria-describedby', DESCRIBED);
      await expect(next).toHaveAccessibleDescription(/do not line up/);

      await page.getByRole('button', { name: /Back$/ }).click();
      await expect(providersHeading(page)).toBeHidden();
      await expect(next).not.toHaveAttribute('aria-describedby', /./);
      await expect(next).toHaveAccessibleDescription('');

      // Continue clears the message (as ever): back on the card there is nothing to describe.
      await next.click();
      await expect(providersHeading(page)).toBeVisible();
      await expect(errorMessage(page)).toBeHidden();
      await expect(next).not.toHaveAttribute('aria-describedby', /./);
      await page.unroute(READ_ROUTE);
    });
  });
});
