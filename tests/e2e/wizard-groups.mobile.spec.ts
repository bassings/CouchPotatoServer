import { test, expect } from './fixtures';
import { Locator, Page } from '@playwright/test';


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
    await page.addInitScript((selectedTheme) => {
      localStorage.setItem('cp-theme', selectedTheme);
    }, theme);
    await page.goto('/wizard/');
    await expect(page.getByRole('heading', { name: 'Welcome to CouchPotato' })).toBeVisible();

    await page.getByRole('button', { name: 'Continue' }).click();
    await expect(page.getByRole('heading', { name: 'Server Security' })).toBeVisible();
    await page.getByRole('button', { name: 'Skip' }).click();
    await expect(page.getByRole('heading', { name: 'Where to Search' })).toBeVisible();

    await page.getByRole('button', { name: /^Both/ }).click();
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
