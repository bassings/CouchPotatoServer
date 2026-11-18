import { test, expect, type Page } from './fixtures';
import { configSection, openProvidersStep, recordWizardRequests, watchLiveRegions } from './helpers';
import { SETTINGS_PERSISTENCE_ANNOTATION } from './settings_persistence';

/**
 * The Newznab rows are saved as comma-separated strings and the server splits
 * them on every comma (`splitString` in couchpotato/core/helpers/variable.py),
 * so a comma typed INSIDE a URL or an API key turns one row into two
 * positions: with a comma in a key, the text after it is sent to the NEXT
 * indexer. Two guards stand against it and each is proven here on its own:
 *
 *  - the wizard's own check (`assertNewznabHasNoCommas`) refuses a literal comma
 *    before ANY request is made, and
 *  - the server refuses it too (`settings.save_group`), and the wizard shows that
 *    refusal even when its own check is switched off.
 *
 * What the user sees is ONE persistent message in the Newznab card that names the
 * indexer as shown and the field, never the value; the offending input is marked
 * (`aria-invalid`, described by the message) and holds focus; the step does not
 * advance and nothing newznab is written, `newznab.enabled` included. An ENCODED
 * comma (`%2C`) is not a comma: the group is saved as JSON and taken as sent.
 *
 * Saves are intercepted with `page.route` unless a case says it uses the real
 * server; keys and hosts are placeholders.
 */

type Row = { host?: string; key?: string };

const SECRET_PART = 'placeholder-secret-part';
const DEFAULT_ROW_COUNT = 6;

const continueButton = (page: Page) => page.getByRole('button', { name: /^(Continue|Saving…)$/ });
const errorMessage = (page: Page) => page.getByTestId('wizard-newznab-error');
const toastText = (page: Page) => page.locator('[x-text="message"]');
const urlInput = (page: Page, n: number) => page.getByLabel(`Newznab indexer URL ${n}`);
const keyInput = (page: Page, n: number) => page.getByLabel(`Newznab API key ${n}`);
const providersHeading = (page: Page) => page.getByRole('heading', { name: 'Where to Search' });

/** Accept every settings save and record it: the group as its JSON body, the rest as `section.name=value`. */
async function recordSaves(page: Page) {
  const saves: string[] = [];
  const groups: any[] = [];
  await page.route('**/settings.save_group/**', async (route) => {
    groups.push(JSON.parse(route.request().postData() || '{}'));
    await route.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify({ success: true }) });
  });
  await page.route('**/settings.save/**', async (route) => {
    const params = new URLSearchParams(route.request().postData() || '');
    saves.push(`${params.get('section')}.${params.get('name')}=${params.get('value')}`);
    await route.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify({ success: true }) });
  });
  return { saves, groups };
}

/**
 * Count settings saves from INSIDE the page, synchronously at the moment `fetch` is
 * called. The route recorder sees a request only once Playwright has been told about
 * it, so a save issued and then abandoned by a refused step could be missed by it.
 */
async function countFetchedSaves(page: Page) {
  await page.addInitScript(() => {
    const real = window.fetch.bind(window);
    const calls: string[] = [];
    (window as any).__saveFetches = calls;
    window.fetch = (input: RequestInfo | URL, init?: RequestInit) => {
      const url = typeof input === 'string' ? input : input instanceof URL ? input.href : input.url;
      if (url.includes('settings.save')) calls.push(`${url} ${String(init?.body)}`);
      return real(input, init);
    };
  });
}

const fetchedSaves = (page: Page): Promise<string[]> => page.evaluate(() => (window as any).__saveFetches);

/** Every text change in the assertive live region, from before the first script runs (AC-A11Y-4's counting, for the wizard). */
async function watchAssertive(page: Page) {
  await page.addInitScript(() => {
    const texts: string[] = [];
    (window as any).__assertiveTexts = texts;
    new MutationObserver((records) => {
      for (const record of records) {
        const node = record.target instanceof Element ? record.target : record.target.parentElement;
        const region = node?.closest('[data-testid="toast-announcer-assertive"]');
        if (region?.textContent) texts.push(region.textContent);
      }
    }).observe(document, { subtree: true, childList: true, characterData: true });
  });
  return () => page.evaluate(() => (window as any).__assertiveTexts as string[]);
}

async function fillRows(page: Page, rows: Row[]) {
  for (const [i, row] of rows.entries()) {
    if (row.host !== undefined) await urlInput(page, i + 1).fill(row.host);
    if (row.key !== undefined) await keyInput(page, i + 1).fill(row.key);
  }
}

async function openWithRows(page: Page, rows: Row[], source: RegExp = /^Usenet/) {
  await countFetchedSaves(page);
  await openProvidersStep(page, source);
  await page.getByRole('switch', { name: 'Enable Newznab Indexers' }).click();
  for (let i = 1; i < rows.length; i++) {
    await page.getByRole('button', { name: '+ Add another indexer' }).click();
  }
  await fillRows(page, rows);
}

/** Two frames: any request issued before the message would have been recorded by now. */
async function settle(page: Page) {
  await page.evaluate(() => new Promise((resolve) => requestAnimationFrame(() => requestAnimationFrame(resolve))));
}

/**
 * Continue, then assert the step refused: ONE message, naming the row and the field,
 * on the offending input (marked, described by it, focused), still on the step, and
 * the value never repeated on screen or to a screen reader.
 */
async function expectRefused(page: Page, message: string, at: { n: number; field: 'URL' | 'API key' }, notShown: string[] = [SECRET_PART]) {
  await continueButton(page).click();
  await expect(errorMessage(page)).toContainText(message);
  await settle(page);
  // The template of AC-DESIGN-5: no option key, no section.name pair, no "Error:", no HTTP status, nothing URL-shaped.
  expect(await errorMessage(page).innerText()).not.toMatch(/api_key|pass_key|\w\.\w|Error:|HTTP \d/);

  await expect(providersHeading(page)).toBeVisible();
  await expect(continueButton(page)).toHaveAttribute('aria-disabled', 'false');
  const input = at.field === 'URL' ? urlInput(page, at.n) : keyInput(page, at.n);
  await expect(input).toBeFocused();
  await expect(input).toHaveAttribute('aria-invalid', 'true');
  await expect(input).toHaveAttribute('aria-describedby', 'wizard-newznab-error');
  await expect(page.locator('[aria-invalid="true"]')).toHaveCount(1);
  // ONE visible message: no toast beside it, and no "Failed to save" stacked on it. Read at once: a toast clears itself after 3s, so waiting for it to be hidden would pass while it was there.
  expect(await toastText(page).isVisible(), 'a toast is showing beside the inline message').toBe(false);
  await expect(page.locator('body')).not.toContainText('Failed to save');
  // Spoken ONCE: the focused input is described by the message, so a screen reader reads it as
  // the input's description. The assertive region stays silent when an input carries the message.
  await expect(page.getByTestId('toast-announcer-assertive')).toHaveText('');
  for (const value of notShown) {
    await expect(errorMessage(page)).not.toContainText(value);
  }
}

test.describe('a comma inside a Newznab URL or API key is refused by the wizard', () => {
  test('a comma in an API key: nothing is saved, the user stays and is told which indexer', async ({ page }) => {
    const { saves, groups } = await recordSaves(page);
    await openWithRows(page, [{ host: 'https://indexer-a.invalid', key: `placeholder-key-a,${SECRET_PART}` }]);

    await expectRefused(page, 'Indexer 1: the API key cannot contain a comma', { n: 1, field: 'API key' });

    expect(await fetchedSaves(page), 'a refused step must not even call fetch for a save').toEqual([]);
    expect(saves).toEqual([]);
    expect(groups).toEqual([]);
  });

  test('a comma in a URL: nothing is saved, and the position named is the row as shown', async ({ page }) => {
    const { saves, groups } = await recordSaves(page);
    await openWithRows(page, [
      { host: 'https://indexer-a.invalid', key: 'placeholder-key-a' },
      { host: 'https://indexer-b.invalid,https://indexer-c.invalid', key: 'placeholder-key-b' },
    ]);

    await expectRefused(page, 'Indexer 2: the URL cannot contain a comma', { n: 2, field: 'URL' });

    expect(await fetchedSaves(page)).toEqual([]);
    expect(saves).toEqual([]);
    expect(groups).toEqual([]);
  });

  test('a comma in the key of a row with no URL is dropped with the row and does not block', async ({ page }) => {
    const { groups } = await recordSaves(page);
    await openWithRows(page, [
      { key: `placeholder-orphan,${SECRET_PART}` },
      { host: 'https://indexer-b.invalid', key: 'placeholder-key-b' },
    ]);

    await continueButton(page).click();
    await expect(providersHeading(page)).toBeHidden({ timeout: 10000 });

    expect(groups).toHaveLength(1);
    expect(groups[0].rows.slice(DEFAULT_ROW_COUNT)).toEqual([
      { use: '1', host: 'https://indexer-b.invalid', api_key: 'placeholder-key-b', extra_score: '0', custom_tag: '' },
    ]);
    expect(JSON.stringify(groups)).not.toContain(SECRET_PART);
  });

  test('fixing the field and pressing Continue again saves normally and clears the message', async ({ page }) => {
    const { groups } = await recordSaves(page);
    await openWithRows(page, [{ host: 'https://indexer-a.invalid', key: `placeholder-key-a,${SECRET_PART}` }]);
    await expectRefused(page, 'Indexer 1: the API key cannot contain a comma', { n: 1, field: 'API key' });

    await fillRows(page, [{ key: 'placeholder-key-a' }]);
    await continueButton(page).click();
    await expect(providersHeading(page)).toBeHidden({ timeout: 10000 });

    expect(groups).toHaveLength(1);
    expect(groups[0].rows[DEFAULT_ROW_COUNT].api_key).toBe('placeholder-key-a');
  });

  test('a whitespace-only URL is a dropped row: a comma in its key does not block', async ({ page }) => {
    const { groups } = await recordSaves(page);
    await openWithRows(page, [
      { host: '   ', key: `placeholder-orphan,${SECRET_PART}` },
      { host: 'https://indexer-b.invalid', key: 'placeholder-key-b' },
    ]);

    await continueButton(page).click();
    await expect(providersHeading(page)).toBeHidden({ timeout: 10000 });

    expect(JSON.stringify(groups)).not.toContain(SECRET_PART);
    expect(groups[0].rows.slice(DEFAULT_ROW_COUNT).map((row: any) => row.host)).toEqual(['https://indexer-b.invalid']);
  });

  test('the URL message names the row and field but never repeats the URL', async ({ page }) => {
    await recordSaves(page);
    await openWithRows(page, [{ host: 'https://placeholder-url-marker.invalid/api?x=1,other', key: 'placeholder-key-a' }]);

    await expectRefused(page, 'Indexer 1: the URL cannot contain a comma', { n: 1, field: 'URL' }, ['placeholder-url-marker']);
  });

  // The group is saved as JSON and taken as sent: no second decode applies, so an
  // encoded comma is three ordinary characters and is stored exactly as typed.
  for (const encoded of ['%2C', '%2c']) {
    test(`an encoded comma (${encoded}) in an API key is saved as typed, not refused`, async ({ page }) => {
      const { groups } = await recordSaves(page);
      await openWithRows(page, [{ host: 'https://indexer-a.invalid', key: `placeholder-key-a${encoded}${SECRET_PART}` }]);

      await continueButton(page).click();
      await expect(providersHeading(page)).toBeHidden({ timeout: 10000 });

      expect(groups[0].rows[DEFAULT_ROW_COUNT].api_key).toBe(`placeholder-key-a${encoded}${SECRET_PART}`);
    });

    test(`an encoded comma (${encoded}) in a URL is saved as typed, not refused`, async ({ page }) => {
      const { groups } = await recordSaves(page);
      await openWithRows(page, [{ host: `https://indexer-b.invalid/api?x=1${encoded}marker`, key: 'placeholder-key-b' }]);

      await continueButton(page).click();
      await expect(providersHeading(page)).toBeHidden({ timeout: 10000 });

      expect(groups[0].rows[DEFAULT_ROW_COUNT].host).toBe(`https://indexer-b.invalid/api?x=1${encoded}marker`);
    });
  }

  test('in Both mode a refused step saves nothing on the torrent side either', async ({ page }) => {
    const { saves, groups } = await recordSaves(page);
    await openWithRows(page, [{ host: 'https://indexer-a.invalid', key: `placeholder-key-a,${SECRET_PART}` }], /^Both/);
    await page.getByRole('switch', { name: 'Enable ThePirateBay' }).click();
    await page.getByRole('switch', { name: 'Enable Jackett / TorrentPotato' }).click();
    await page.locator('#wizard-jackett-url').fill('http://jackett.invalid:9117');
    await page.locator('#wizard-jackett-api-key').fill('placeholder-jackett-key');

    await expectRefused(page, 'Indexer 1: the API key cannot contain a comma', { n: 1, field: 'API key' });

    expect(await fetchedSaves(page)).toEqual([]);
    expect(saves).toEqual([]);
    expect(groups).toEqual([]);
  });
});

// The server's refusal reaches the wizard in the structured form of the group-save
// response: `invalid: [{row, column, reason}]`, `row` the 0-based row AS SENT. The
// wizard sends hidden rows at their stored positions, so that number is not the
// number on screen, and it is mapped back before anything is named, marked or focused.
test.describe('a refusal from the server is shown on the row it is about', () => {
  const refusal = (row: number, column: string, reason = 'comma') => ({
    success: false,
    error: 'A value contains a comma, which would split it across rows. Nothing was saved.',
    invalid: [{ row, column, reason }],
  });

  test('with blank rows above, the row numbered by the server is the one shown as Indexer 2', async ({ page }) => {
    const bodies: any[] = [];
    await page.route('**/settings.save_group/**', async (route) => {
      bodies.push(JSON.parse(route.request().postData() || '{}'));
      // The first row the wizard adds follows the six hidden defaults.
      await route.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify(refusal(DEFAULT_ROW_COUNT, 'host')) });
    });
    await page.route('**/settings.save/**', (route) => route.fulfill({
      status: 200, contentType: 'application/json', body: JSON.stringify({ success: true }),
    }));
    await openWithRows(page, [{}, { host: 'https://indexer-b.invalid', key: 'placeholder-key-b' }]);

    await expectRefused(page, 'Indexer 2: the URL cannot contain a comma. Remove it to save.', { n: 2, field: 'URL' });

    expect(bodies).toHaveLength(1);
  });

  test.describe('the interleaved fixture', () => {
    test.use({ seedConfig: 'newznab_interleaved#wizard-refusal-mapping' });

    test('a refusal naming row 3 is indexer B, the second row on screen, and not the hidden row at 3', async ({ page }) => {
      await page.route('**/settings.save_group/**', (route) => route.fulfill({
        status: 200, contentType: 'application/json', body: JSON.stringify(refusal(3, 'api_key')),
      }));
      await openProvidersStep(page);
      await urlInput(page, 2).fill('https://placeholder-bravo-edited.invalid/api');

      await expectRefused(page, 'Indexer 2: the API key cannot contain a comma. Remove it to save.', { n: 2, field: 'API key' });
    });

    test('a refusal naming a hidden row is not pinned on any indexer: the server\'s own text is shown', async ({ page }) => {
      await page.route('**/settings.save_group/**', (route) => route.fulfill({
        status: 200, contentType: 'application/json', body: JSON.stringify(refusal(0, 'host')),
      }));
      await openProvidersStep(page);
      await urlInput(page, 2).fill('https://placeholder-bravo-edited.invalid/api');

      await continueButton(page).click();

      await expect(errorMessage(page)).toContainText('A value contains a comma');
      // No input to carry it: the message says where it CAN be fixed, and is announced assertively once.
      await expect(errorMessage(page)).toContainText('Check them in Settings, under Searchers, then Newznab.');
      await expect(page.getByTestId('toast-announcer-assertive')).toContainText('Check them in Settings');
      await expect(page.locator('[aria-invalid="true"]')).toHaveCount(0);
      await expect(providersHeading(page)).toBeVisible();
    });
  });

  test.describe('the real server, with the wizard\'s own check switched off', () => {
    test.use({ seedConfig: 'newznab_two_stored#wizard-real-refusal' });

    test('refuses the comma itself: shows its row and field, advances nowhere and leaves every newznab line alone', async ({ page, testServer }) => {
      test.info().annotations.push({ type: SETTINGS_PERSISTENCE_ANNOTATION });
      const requests = await recordWizardRequests(page);
      const before = configSection(testServer.configPath, 'newznab');
      await openProvidersStep(page);
      await expect(urlInput(page, 2)).toHaveValue('https://placeholder-two.invalid/api');
      await page.evaluate(() => {
        const root = document.querySelector('[x-data="setupWizard()"]') as HTMLElement;
        (window as any).Alpine.$data(root).assertNewznabHasNoCommas = () => undefined;
      });
      await urlInput(page, 2).fill(`https://placeholder-two.invalid/api,${SECRET_PART}`);

      await expectRefused(page, 'Indexer 2: the URL cannot contain a comma. Remove it to save.', { n: 2, field: 'URL' });

      expect(requests.groupSaves()).toHaveLength(1);
      const sections = requests.columnSaves().map((request) => `${new URLSearchParams(request.body).get('section')}`);
      expect(sections, 'newznab.enabled was written beside a refused group').not.toContain('newznab');
      expect(configSection(testServer.configPath, 'newznab')).toEqual(before);
    });
  });
});

// Owner decision 2026-11-18 (AC-A11Y-17): a refusal stays, message and marks, while the user
// edits. It goes when Continue next runs its check (and comes back if the problem remains),
// when Newznab is switched off, and when a row is added or removed.
test.describe('the message and the marks stay until the next Continue', () => {
  const REFUSED_KEY = 'Indexer 1: the API key cannot contain a comma';

  test('typing in the marked input changes neither the mark nor the message, and announces nothing', async ({ page }) => {
    await recordSaves(page);
    const liveTexts = await watchLiveRegions(page);
    await openWithRows(page, [{ host: 'https://indexer-a.invalid', key: `placeholder-key-a,${SECRET_PART}` }]);
    await expectRefused(page, REFUSED_KEY, { n: 1, field: 'API key' });
    const before = await liveTexts();

    await keyInput(page, 1).fill('placeholder-key-a');
    await keyInput(page, 1).pressSequentially('-more');
    await settle(page);

    await expect(keyInput(page, 1)).toHaveAttribute('aria-invalid', 'true');
    await expect(keyInput(page, 1)).toHaveAttribute('aria-describedby', 'wizard-newznab-error');
    await expect(errorMessage(page)).toContainText(REFUSED_KEY);
    expect(await liveTexts(), 'typing made a live region speak').toEqual(before);
  });

  test('typing in another input leaves the marked one marked and the message in place', async ({ page }) => {
    await recordSaves(page);
    await openWithRows(page, [{ host: 'https://indexer-a.invalid', key: `placeholder-key-a,${SECRET_PART}` }]);
    await continueButton(page).click();
    await expect(errorMessage(page)).toContainText(REFUSED_KEY);

    await urlInput(page, 1).fill('https://indexer-z.invalid');

    await expect(keyInput(page, 1)).toHaveAttribute('aria-invalid', 'true');
    await expect(errorMessage(page)).toContainText(REFUSED_KEY);
  });

  test('Continue replaces the old message and marks with what is now wrong', async ({ page }) => {
    await recordSaves(page);
    await openWithRows(page, [{ host: 'https://indexer-a.invalid', key: `placeholder-key-a,${SECRET_PART}` }]);
    await continueButton(page).click();
    await expect(keyInput(page, 1)).toHaveAttribute('aria-invalid', 'true');

    await keyInput(page, 1).fill('placeholder-key-a');
    await urlInput(page, 1).fill('https://indexer-a.invalid,https://indexer-b.invalid');
    await continueButton(page).click();

    await expect(errorMessage(page)).toContainText('Indexer 1: the URL cannot contain a comma');
    await expect(errorMessage(page)).not.toContainText('API key');
    await expect(urlInput(page, 1)).toHaveAttribute('aria-invalid', 'true');
    await expect(keyInput(page, 1)).not.toHaveAttribute('aria-invalid', 'true');
    await expect(page.locator('[aria-invalid="true"]')).toHaveCount(1);
  });

  test('a Continue that goes through leaves no message or mark behind when the user comes back', async ({ page }) => {
    await recordSaves(page);
    await openWithRows(page, [{ host: 'https://indexer-a.invalid', key: `placeholder-key-a,${SECRET_PART}` }]);
    await continueButton(page).click();
    await expect(errorMessage(page)).toBeVisible();

    await keyInput(page, 1).fill('placeholder-key-a');
    await continueButton(page).click();
    await expect(providersHeading(page)).toBeHidden({ timeout: 10000 });
    await page.getByRole('button', { name: /Back/ }).click();
    await expect(providersHeading(page)).toBeVisible();

    await expect(errorMessage(page)).toBeHidden();
    await expect(page.locator('[aria-invalid="true"]')).toHaveCount(0);
    await expect(page.locator('[data-newznab-card] [aria-describedby="wizard-newznab-error"]')).toHaveCount(0);
  });

  test('switching Newznab off clears it', async ({ page }) => {
    await recordSaves(page);
    await openWithRows(page, [{ host: 'https://indexer-a.invalid', key: `placeholder-key-a,${SECRET_PART}` }]);
    await continueButton(page).click();
    await expect(errorMessage(page)).toBeVisible();

    await page.getByRole('switch', { name: 'Enable Newznab Indexers' }).click();

    await expect(errorMessage(page)).toBeHidden();
  });

  // Marks and the "Indexer N" wording are by row position, and a removed or added row shifts or
  // adds positions, so ANY add or remove clears the message and every mark (a message must never
  // name the wrong row, and a mark on a removed row has nothing to mark).
  test('removing a row clears the message and every mark, so it never names the wrong row', async ({ page }) => {
    await recordSaves(page);
    await openWithRows(page, [
      { host: 'https://indexer-a.invalid', key: 'placeholder-key-a' },
      { host: 'https://indexer-b.invalid', key: `placeholder-key-b,${SECRET_PART}` },
    ]);
    await continueButton(page).click();
    await expect(errorMessage(page)).toContainText('Indexer 2: the API key cannot contain a comma');

    await page.getByRole('button', { name: /^Remove indexer 1$/i }).click();

    await expect(errorMessage(page)).toBeHidden();
    await expect(page.locator('[aria-invalid="true"]')).toHaveCount(0);
  });

  test('adding a row clears the message and every mark', async ({ page }) => {
    await recordSaves(page);
    await openWithRows(page, [{ host: 'https://indexer-a.invalid', key: `placeholder-key-a,${SECRET_PART}` }]);
    await continueButton(page).click();
    await expect(errorMessage(page)).toBeVisible();

    await page.getByRole('button', { name: '+ Add another indexer' }).click();

    await expect(errorMessage(page)).toBeHidden();
    await expect(page.locator('[aria-invalid="true"]')).toHaveCount(0);
  });
});

// AC-OPS-4: the route is missing (a page on the new version talking to a rolled-back
// server) or the server fails. Never "saved", never advance, rows kept as typed.
test.describe('any other answer from the group-save route is a visible error', () => {
  // `null` is a dropped connection: the request never gets an answer at all.
  const ANSWERS: [string, { status: number; body: string } | null][] = [
    ['the API call does not exist', { status: 200, body: '{"success": false, "error": "API call doesn\'t exist"}' }],
    ['an HTTP 500', { status: 500, body: '{"success": false, "error": "boom"}' }],
    ['an answer that is not JSON', { status: 502, body: '<html>bad gateway</html>' }],
    ['a dropped connection', null],
  ];

  for (const [name, reply] of ANSWERS) {
    test(`${name}: an error stays on screen, the rows stay as typed, nothing else is saved`, async ({ page }) => {
      const singles: string[] = [];
      const liveTexts = await watchAssertive(page);
      await page.route('**/settings.save_group/**', (route) => (reply
        ? route.fulfill({ status: reply.status, contentType: 'application/json', body: reply.body })
        : route.abort('connectionreset')));
      await page.route('**/settings.save/**', async (route) => {
        singles.push(new URLSearchParams(route.request().postData() || '').get('name') || '');
        await route.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify({ success: true }) });
      });
      await openWithRows(page, [{ host: 'https://indexer-a.invalid', key: 'placeholder-key-a' }]);

      await continueButton(page).click();

      await expect(errorMessage(page)).toContainText('Newznab indexers were not saved');
      await expect(errorMessage(page)).toContainText('Check them in Settings, under Searchers, then Newznab.');
      await expect(page.getByTestId('toast-announcer-assertive')).toContainText('were not saved');
      await settle(page);
      // Announced once: a message no input carries is spoken a single time.
      expect((await liveTexts()).filter((text) => text.includes('were not saved')), 'the failure was announced more than once').toHaveLength(1);
      await expect(providersHeading(page)).toBeVisible();
      await expect(urlInput(page, 1)).toHaveValue('https://indexer-a.invalid');
      await expect(keyInput(page, 1)).toHaveValue('placeholder-key-a');
      expect(await toastText(page).isVisible(), 'a toast is showing beside the inline message').toBe(false);
      expect(singles, 'something was saved beside a group that was not').toEqual([]);
      await expect(page.getByTestId('toast-announcer-polite')).not.toContainText('Saved');
    });
  }
});
