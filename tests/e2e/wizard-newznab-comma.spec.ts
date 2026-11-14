import { test, expect, type Page } from './fixtures';

/**
 * The Newznab lists are saved as comma-separated strings and the server splits
 * them on every comma (`splitString` in couchpotato/core/helpers/variable.py),
 * so a comma typed INSIDE a URL or an API key turns one row into two
 * positions: with a comma in a key, the text after it is sent to the NEXT
 * indexer. The wizard rejects it at the source.
 *
 * The contract these cases pin: when any KEPT row (one with a URL, see
 * wizard-newznab-pairing.spec.ts) has a comma in its URL or its key, the step
 * saves NOTHING, the user stays on the step, and the existing error toast
 * names the row and the field, never the value. A row with no URL is dropped
 * whole, so a comma in its key does not block anything.
 *
 * Saves are intercepted with `page.route`; keys and hosts are placeholders.
 */

type Row = { host?: string; key?: string };

const SECRET_PART = 'placeholder-secret-part';

/** Record every settings save as `section.name=value` and accept it. */
async function recordSaves(page: Page): Promise<string[]> {
  const saves: string[] = [];
  await page.route('**/settings.save/**', async (route) => {
    const params = new URLSearchParams(route.request().postData() || '');
    saves.push(`${params.get('section')}.${params.get('name')}=${params.get('value')}`);
    await route.fulfill({
      status: 200,
      contentType: 'application/json',
      body: JSON.stringify({ success: true }),
    });
  });
  return saves;
}

async function openProviders(page: Page, rows: Row[]) {
  await page.goto('/wizard/');
  await page.getByRole('button', { name: /Continue/i }).click();           // Welcome -> Security
  await page.getByRole('button', { name: /Continue/i }).click();           // Security -> Providers
  await expect(page.getByRole('heading', { name: 'Where to Search' })).toBeVisible({ timeout: 10000 });
  await page.getByRole('radio', { name: /^Usenet/ }).click();
  await page.getByRole('switch', { name: 'Enable Newznab Indexers' }).click();
  for (let i = 1; i < rows.length; i++) {
    await page.getByRole('button', { name: '+ Add another indexer' }).click();
  }
  await fillRows(page, rows);
}

async function fillRows(page: Page, rows: Row[]) {
  for (const [i, row] of rows.entries()) {
    if (row.host !== undefined) await page.getByLabel(`Newznab indexer URL ${i + 1}`).fill(row.host);
    if (row.key !== undefined) await page.getByLabel(`Newznab API key ${i + 1}`).fill(row.key);
  }
}

const continueButton = (page: Page) => page.getByRole('button', { name: /^(Continue|Saving…)$/ });
const toastText = (page: Page) => page.locator('[x-text="message"]');

/** Two frames: any request issued before the toast would have been recorded by now. */
async function settle(page: Page) {
  await page.evaluate(() => new Promise((resolve) => requestAnimationFrame(() => requestAnimationFrame(resolve))));
}

/** Continue, then assert the step refused: error shown, still on the step, no save of any kind. */
async function expectRefused(page: Page, saves: string[], message: string) {
  await continueButton(page).click();
  await expect(toastText(page)).toContainText(message);
  await settle(page);

  expect(saves, 'a refused step must issue no save requests at all').toEqual([]);
  await expect(page.getByRole('heading', { name: 'Where to Search' })).toBeVisible();
  await expect(continueButton(page)).toBeFocused();
  await expect(continueButton(page)).toHaveAttribute('aria-disabled', 'false');

  // The value typed is never repeated, on screen or to a screen reader.
  await expect(toastText(page)).not.toContainText(SECRET_PART);
  await expect(page.getByTestId('toast-announcer-assertive')).toContainText(message);
  await expect(page.getByTestId('toast-announcer-assertive')).not.toContainText(SECRET_PART);
}

test.describe('a comma inside a Newznab URL or API key is refused by the wizard', () => {
  test('a comma in an API key: nothing is saved, the user stays and is told which indexer', async ({ page }) => {
    const saves = await recordSaves(page);
    await openProviders(page, [
      { host: 'https://indexer-a.invalid', key: `placeholder-key-a,${SECRET_PART}` },
    ]);

    await expectRefused(page, saves, 'Indexer 1: the API key cannot contain a comma');
  });

  test('a comma in a URL: nothing is saved, and the position named is the row as shown', async ({ page }) => {
    const saves = await recordSaves(page);
    await openProviders(page, [
      { host: 'https://indexer-a.invalid', key: 'placeholder-key-a' },
      { host: 'https://indexer-b.invalid,https://indexer-c.invalid', key: 'placeholder-key-b' },
    ]);

    await expectRefused(page, saves, 'Indexer 2: the URL cannot contain a comma');
  });

  test('a comma in the key of a row with no URL is dropped with the row and does not block', async ({ page }) => {
    const saves = await recordSaves(page);
    await openProviders(page, [
      { key: `placeholder-orphan,${SECRET_PART}` },
      { host: 'https://indexer-b.invalid', key: 'placeholder-key-b' },
    ]);

    await continueButton(page).click();
    await expect(page.getByRole('heading', { name: 'Where to Search' })).toBeHidden({ timeout: 10000 });

    expect(saves).toContain('newznab.host=https://indexer-b.invalid');
    expect(saves).toContain('newznab.api_key=placeholder-key-b');
    expect(saves).toContain('newznab.use=1');
    expect(saves.join('\n')).not.toContain(SECRET_PART);
  });

  test('fixing the field and pressing Continue again saves normally', async ({ page }) => {
    const saves = await recordSaves(page);
    await openProviders(page, [
      { host: 'https://indexer-a.invalid', key: `placeholder-key-a,${SECRET_PART}` },
    ]);
    await expectRefused(page, saves, 'Indexer 1: the API key cannot contain a comma');

    await fillRows(page, [{ key: 'placeholder-key-a' }]);
    await continueButton(page).click();
    await expect(page.getByRole('heading', { name: 'Where to Search' })).toBeHidden({ timeout: 10000 });

    expect(saves).toContain('newznab.host=https://indexer-a.invalid');
    expect(saves).toContain('newznab.api_key=placeholder-key-a');
    expect(saves).toContain('newznab.use=1');
  });
});
