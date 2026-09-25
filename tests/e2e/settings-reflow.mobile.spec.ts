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
