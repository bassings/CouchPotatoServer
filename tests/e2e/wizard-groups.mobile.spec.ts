import { test, expect } from './fixtures';
import { Locator, Page } from '@playwright/test';
import { expectVisualTransitionsToSettle, mockSettingsSave, openProvidersStep, showWizardRefusal } from './helpers';


async function expectGroupFitsPhone(group: Locator, page: Page, name: string) {
  await expect(group).toBeVisible();
  const borderWidths = await group.evaluate((element) => {
    const style = getComputedStyle(element);
    return [style.borderTopWidth, style.borderRightWidth, style.borderBottomWidth, style.borderLeftWidth];
  });
  expect(borderWidths, `${name} gained native fieldset border chrome`).toEqual([
    '0px', '0px', '0px', '0px',
  ]);
  const box = await group.boundingBox();
  const viewportWidth = page.viewportSize()!.width;
  const documentWidth = await page.evaluate(() => ({
    client: document.documentElement.clientWidth,
    scroll: document.documentElement.scrollWidth,
  }));

  expect(
    documentWidth.scroll,
    `${name} makes the wizard ${documentWidth.scroll}px wide in a ` +
      `${documentWidth.client}px layout viewport`,
  ).toBeLessThanOrEqual(documentWidth.client);

  expect(box, `${name} has no rendered box`).not.toBeNull();
  expect(Math.floor(box!.x), `${name} starts outside the phone viewport`).toBeGreaterThanOrEqual(0);
  expect(
    Math.ceil(box!.x + box!.width),
    `${name} extends past the ${viewportWidth}px phone viewport`,
  ).toBeLessThanOrEqual(viewportWidth);

  const overflowingDescendant = await group.locator('input, select, button').evaluateAll(
    (elements, width) => elements.find((element) => {
      const box = element.getBoundingClientRect();
      return box.left < 0 || box.right > width;
    })?.outerHTML || null,
    viewportWidth,
  );
  expect(
    overflowingDescendant,
    `${name} has a control outside the phone viewport: ${overflowingDescendant}`,
  ).toBeNull();
}


for (const theme of ['light', 'dark'] as const) {
  test(`wizard provider and downloader groups fit a phone viewport in ${theme} theme`, async ({ page }) => {
    await mockSettingsSave(page);
    await page.addInitScript((selectedTheme) => {
      localStorage.setItem('cp-theme', selectedTheme);
    }, theme);
    await page.goto('/wizard/');
    await expect(page.getByRole('heading', { name: 'Welcome to CouchPotato' })).toBeVisible();
    await expect.poll(
      () => page.evaluate(() => document.documentElement.classList.contains('light')),
      { message: `${theme} theme was not applied before mobile layout checks` },
    ).toBe(theme === 'light');

    await page.getByRole('button', { name: 'Continue' }).click();
    await expect(page.getByRole('heading', { name: 'Server Security' })).toBeVisible();
    await page.getByRole('button', { name: 'Skip' }).click();
    await expect(page.getByRole('heading', { name: 'Where to Search' })).toBeVisible();

    await page.getByRole('radio', { name: /^Both/ }).click();
    await page.getByRole('button', { name: /Private Trackers/ }).click();
    await page.getByRole('switch', { name: 'Enable PassThePopcorn' }).click();
    await page.getByRole('switch', { name: 'Enable HDBits' }).click();

    const passThePopcorn = page.getByRole('group', { name: 'PassThePopcorn' });
    const hdBits = page.getByRole('group', { name: 'HDBits' });
    await expect(passThePopcorn.getByLabel('Username')).toBeVisible();
    await expect(hdBits.getByLabel('Username')).toBeVisible();
    await expectGroupFitsPhone(passThePopcorn, page, 'PassThePopcorn tracker group');
    await expectGroupFitsPhone(hdBits, page, 'HDBits tracker group');

    await page.getByRole('button', { name: 'Continue' }).click();
    await expect(page.getByRole('heading', { name: 'Download Clients' })).toBeVisible();
    await page.getByRole('button', { name: 'SABnzbd' }).click();
    await page.getByRole('button', { name: 'qBittorrent' }).click();

    const usenet = page.getByRole('group', { name: 'Usenet Client' });
    const torrent = page.getByRole('group', { name: 'Torrent Client' });
    await expect(usenet.getByLabel('Host')).toBeVisible();
    await expect(torrent.getByLabel('Host')).toBeVisible();
    await expectGroupFitsPhone(usenet, page, 'Usenet client group');
    await expectGroupFitsPhone(torrent, page, 'Torrent client group');
  });
}

// ─────────────────────────────────────────────────────────────────────────────
// SEC-004 P5 (AC-A11Y-12): the Newznab messages at 320 CSS px and at 640 CSS px (the
// layout width of 200% zoom on a 1280px window, which Playwright cannot set directly),
// in both themes. The full text is shown, nothing scrolls sideways, and the message's
// box lies inside the viewport.
// ─────────────────────────────────────────────────────────────────────────────

async function expectMessageFits(page: Page, message: Locator, label: string) {
  await expect(message).toBeVisible();
  // The card fades in with a scale: measured mid-animation every box is a few percent short.
  await expectVisualTransitionsToSettle(page, label);
  const text = (await message.textContent())?.trim() ?? '';
  expect(text.length, `${label} has no text`).toBeGreaterThan(20);
  const box = await message.boundingBox();
  const width = page.viewportSize()!.width;
  expect(box, `${label} has no box`).not.toBeNull();
  expect(Math.floor(box!.x), `${label} starts left of the viewport`).toBeGreaterThanOrEqual(0);
  expect(Math.ceil(box!.x + box!.width), `${label} runs past the ${width}px viewport`).toBeLessThanOrEqual(width);
  const scroll = await page.evaluate(() => ({ client: document.scrollingElement!.clientWidth, scroll: document.scrollingElement!.scrollWidth }));
  expect(scroll.scroll, `${label} makes the page scroll sideways`).toBeLessThanOrEqual(scroll.client);
  // Every word of it is rendered: nothing is clipped by an ancestor with overflow hidden.
  const clipped = await message.evaluate((element) => element.scrollWidth > element.clientWidth + 1 || element.scrollHeight > element.clientHeight + 1);
  expect(clipped, `${label} is clipped`).toBe(false);
}

for (const theme of ['light', 'dark'] as const) {
  for (const width of [320, 640]) {
    test.describe(`the Newznab card's messages at ${width}px (${theme} theme)`, () => {
      test.use({ viewport: { width, height: 800 } });

      test('a refused save shows its whole text inside the viewport', async ({ page }) => {
        await showWizardRefusal(page, theme);

        await expectMessageFits(page, page.locator('#wizard-newznab-error'), 'refusal');
        await expect(page.getByLabel('Newznab indexer URL 1')).toBeFocused();
      });

      test.describe('a failed read', () => {
        test.use({ seedConfig: `newznab_two_stored#wizard-reflow-read-failed-${theme}-${width}` });

        test('shows its whole text and its retry button inside the viewport', async ({ page }) => {
          await page.addInitScript((value) => localStorage.setItem('cp-theme', value), theme);
          await page.route(/\/settings\/(\?.*)?$/, (route) => route.fulfill({ status: 500, contentType: 'application/json', body: '{}' }));
          await openProvidersStep(page);

          await expectMessageFits(page, page.locator('#wizard-newznab-error'), 'load error');
          const retry = await page.getByRole('button', { name: 'Try loading saved indexers again' }).boundingBox();
          expect(retry!.x + retry!.width).toBeLessThanOrEqual(width);
          expect(retry!.height, 'the retry target is under 44px').toBeGreaterThanOrEqual(44);
        });
      });

      test.describe('a read still pending when Continue is pressed', () => {
        test.use({ seedConfig: `newznab_two_stored#wizard-reflow-pending-${theme}-${width}` });

        test('shows its whole message inside the viewport', async ({ page }) => {
          await page.addInitScript((value) => localStorage.setItem('cp-theme', value), theme);
          await page.route(/\/settings\/(\?.*)?$/, () => new Promise(() => undefined));
          await openProvidersStep(page);
          await page.getByRole('button', { name: /^Continue$/ }).click();

          await expectMessageFits(page, page.locator('#wizard-newznab-error'), 'pending message');
        });
      });

      test.describe('a misaligned stored group', () => {
        test.use({ seedConfig: `newznab_misaligned_key_short#wizard-reflow-notice-${theme}-${width}` });

        test('shows its whole notice inside the viewport', async ({ page }) => {
          await page.addInitScript((value) => localStorage.setItem('cp-theme', value), theme);
          await openProvidersStep(page);

          await expectMessageFits(page, page.getByTestId('combine-misaligned-notice').locator('p'), 'notice');
        });
      });
    });
  }
}
