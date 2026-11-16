import { Page } from '@playwright/test';
import { test, expect } from './fixtures';


async function expectNoHorizontalDocumentOverflow(page: Page, context: string) {
  const layout = await page.evaluate(() => {
    const viewportWidth = document.documentElement.clientWidth;
    const offenders = [...document.querySelectorAll<HTMLElement>('body *')]
      .map((element) => {
        const box = element.getBoundingClientRect();
        return {
          tag: element.tagName.toLowerCase(),
          id: element.id,
          classes: element.className?.toString().slice(0, 120) || '',
          left: Math.round(box.left),
          right: Math.round(box.right),
        };
      })
      .filter(({ left, right }) => left < -1 || right > viewportWidth + 1)
      .slice(0, 8);

    return {
      viewportWidth,
      scrollWidth: document.documentElement.scrollWidth,
      offenders,
    };
  });

  expect(
    layout.scrollWidth,
    `${context}: document is ${layout.scrollWidth}px wide in a ${layout.viewportWidth}px viewport; ` +
      `overflowing elements: ${JSON.stringify(layout.offenders)}`,
  ).toBeLessThanOrEqual(layout.viewportWidth);
}


async function expectActivatedTabReady(page: Page, name: string) {
  if (name === 'Logs') {
    await expect(page.getByText('Loading logs…')).toBeVisible();
    await expect(page.getByText('Loading logs…')).toBeHidden({ timeout: 10_000 });
    await expect(page.getByRole('region', { name: 'Application logs' })).toBeVisible();
  } else if (name === 'Profiles') {
    await expect(page.getByText('Loading profiles…')).toBeVisible();
    await expect(page.getByRole('button', { name: 'New Profile' })).toBeVisible();
  } else if (name === 'Categories') {
    await expect(page.getByText('Loading categories…')).toBeVisible();
    await expect(page.getByRole('button', { name: 'New Category' })).toBeVisible();
  }
}


for (const theme of ['light', 'dark'] as const) {
  for (const width of [320, 375] as const) {
    test(`every settings tab reflows at ${width}px in ${theme} theme`, async ({ page }) => {
      await page.setViewportSize({ width, height: 800 });
      await page.addInitScript((selectedTheme) => {
        localStorage.setItem('cp-theme', selectedTheme);
      }, theme);
      for (const endpoint of ['profile.list', 'category.list']) {
        await page.route(`**/${endpoint}/**`, async (route) => {
          await new Promise((resolve) => setTimeout(resolve, 1000));
          await route.continue();
        });
      }
      await page.route('**/logging.partial/**', async (route) => {
        await new Promise((resolve) => setTimeout(resolve, 5000));
        await route.continue();
      });
      await page.goto('/settings/');

      const tablist = page.getByRole('tablist', { name: 'Settings categories' });
      await expect(tablist).toBeVisible();
      const tabs = tablist.getByRole('tab');
      const tabCount = await tabs.count();
      expect(tabCount, 'settings rendered no tabs').toBeGreaterThan(0);

      for (let index = 0; index < tabCount; index++) {
        const tab = tabs.nth(index);
        const name = (await tab.textContent())?.trim() || `tab ${index}`;
        await tab.click();
        await expect(tab).toHaveAttribute('aria-selected', 'true');
        await expectActivatedTabReady(page, name);
        await expectNoHorizontalDocumentOverflow(page, `${name} tab`);
      }
    });
  }
}

// SEC-004 P3: the refused combined field and the misaligned-group notice at phone
// width. The refusal is stubbed in the server's own shape; nothing is written.
for (const theme of ['light', 'dark'] as const) {
  test.describe(`a refused combined field at 375px in ${theme} theme`, () => {
    test.use({ seedConfig: `newznab_misaligned_key_short#mobile-reflow-${theme}` });

    test('the notice and the inline refusal show in full inside the viewport', async ({ page }) => {
      await page.setViewportSize({ width: 375, height: 800 });
      await page.addInitScript((selectedTheme) => {
        localStorage.setItem('cp-theme', selectedTheme);
      }, theme);
      await page.route('**/settings.save_group/**', (route) => route.fulfill({
        status: 200,
        contentType: 'application/json',
        body: JSON.stringify({
          success: false, error: 'A cell cannot contain a comma.',
          invalid: [{ row: 1, column: 'host', reason: 'comma' }],
        }),
      }));
      await page.goto('/settings/');
      await page.getByRole('tab', { name: 'Searchers' }).click();
      const card = page.locator('.bg-cp-card', { has: page.getByRole('heading', { name: 'Newznab', exact: true }) });
      const notice = card.getByTestId('combine-misaligned-notice');
      await expect(notice).toBeVisible();
      // The notice is what describes each cell, at phone width as everywhere.
      await expect(card.getByLabel('host for row 1', { exact: true })).toHaveAttribute('aria-describedby', await notice.getAttribute('id') ?? 'missing');

      await card.getByLabel('host for row 2', { exact: true }).fill('https://placeholder-two.invalid/api,x');
      const error = card.getByTestId('combine-row-error');
      await expect(error).toBeVisible();
      await expect(card.locator('[aria-invalid="true"]')).toHaveCount(1);

      await expectNoHorizontalDocumentOverflow(page, `refused combined field, ${theme}`);
      for (const box of [notice, error]) {
        const fits = await box.evaluate((element) => {
          const rect = element.getBoundingClientRect();
          const text = element.querySelector('p') as HTMLElement;
          return {
            inside: rect.left >= 0 && rect.right <= document.documentElement.clientWidth,
            clipped: text.scrollWidth > text.clientWidth,
          };
        });
        expect(fits).toEqual({ inside: true, clipped: false });
      }
    });
  });
}
