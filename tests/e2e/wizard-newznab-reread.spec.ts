import { test, expect, type APIRequestContext, type Page } from './fixtures';
import { configColumns, configSection, configSha, openProvidersStep, recordWizardRequests, waitForNewznabRead } from './helpers';
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

/** Every text a live region received, from before the first script runs. */
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

      test('writes nothing, does not advance, and shows the read failure with Retry, which brings the stored rows back', async ({ page, testServer }) => {
        test.info().annotations.push(...combineGroupWriter());
        const requests = await recordWizardRequests(page);
        await openWithRows(page, 'https://placeholder-one.invalid/api');
        await urlInput(page, 1).fill(EDITED_URL);
        const baseline = configSha(testServer.configPath);
        await fail(page);

        await continueButton(page).click();

        await expect(errorMessage(page)).toContainText(NOT_LOADED);
        await expect(retryButton(page)).toBeVisible();
        await expect(retryButton(page)).toBeFocused();
        await expect(providersHeading(page)).toBeVisible();
        expect(await requests.pageWrites(), 'a failed re-read was followed by a write').toEqual([]);
        expect(configSha(testServer.configPath), 'config.ini changed').toBe(baseline);

        // The existing Retry path: the stored rows come back, the discarded edit does not.
        await page.unroute(READ_ROUTE);
        await retryButton(page).click();
        await expect(urlInput(page, 1)).toHaveValue('https://placeholder-one.invalid/api');
        await expect(errorMessage(page)).toBeHidden();
        expect(configSha(testServer.configPath)).toBe(baseline);
      });
    });
  }

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
      expect(await requests.pageWrites()).toEqual([]);
      expect(configSha(testServer.configPath)).toBe(baseline);
    });
  });
});
