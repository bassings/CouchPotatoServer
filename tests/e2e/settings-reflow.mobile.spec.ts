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

// Owner decision 2026-11-18: the removal line and its Undo at phone width. A removal and its
// Undo write nothing (Undo cancels the save that was waiting out its window).
for (const theme of ['light', 'dark'] as const) {
  test.describe(`the removal line at 375px in ${theme} theme`, () => {
    test.use({ seedConfig: `newznab_aligned#mobile-removal-line-${theme}` });

    test('shows in full inside the viewport, Undo is a target of at least 24px, and nothing scrolls sideways', async ({ page }) => {
      await page.setViewportSize({ width: 375, height: 800 });
      await page.addInitScript((selectedTheme) => {
        localStorage.setItem('cp-theme', selectedTheme);
      }, theme);
      await page.goto('/settings/');
      await page.getByRole('tab', { name: 'Searchers' }).click();
      const card = page.locator('.bg-cp-card', { has: page.getByRole('heading', { name: 'Newznab', exact: true }) });
      await card.getByRole('button', { name: 'Remove row 2', exact: true }).click();
      const line = card.getByTestId('combine-removed-line');
      await expect(line).toContainText('Row 2 removed.');
      const undo = card.getByRole('button', { name: 'Undo', exact: true });

      await expectNoHorizontalDocumentOverflow(page, `removal line, ${theme}`);
      const fits = await line.evaluate((element) => {
        const rect = element.getBoundingClientRect();
        return { inside: rect.left >= 0 && rect.right <= document.documentElement.clientWidth };
      });
      expect(fits).toEqual({ inside: true });
      const box = await undo.boundingBox();
      expect(box!.width).toBeGreaterThanOrEqual(24);
      expect(box!.height).toBeGreaterThanOrEqual(24);
      expect(box!.x + box!.width).toBeLessThanOrEqual(375);
      // End with nothing waiting to be saved: a pending removal is sent when the page goes.
      await undo.click();
      await expect(line).toHaveCount(0);
    });
  });
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

  test.describe(`locked rows during a button action at 375px in ${theme} theme`, () => {
    test.use({ seedConfig: `torrentpotato_aligned#mobile-locked-${theme}` });

    test('the lock note fits, the inputs are readonly, and nothing overflows', async ({ page }) => {
      await page.setViewportSize({ width: 375, height: 800 });
      await page.addInitScript((selectedTheme) => {
        localStorage.setItem('cp-theme', selectedTheme);
      }, theme);
      let release!: () => void;
      const gate = new Promise<void>((resolve) => { release = resolve; });
      await page.route('**/torrentpotato.jackett_sync/**', async (route) => {
        await gate;
        await route.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify({ success: false, error: 'Jackett refused' }) });
      });
      await page.goto('/settings/');
      await page.getByRole('tab', { name: 'Searchers' }).click();
      const card = page.locator('.bg-cp-card', { has: page.getByRole('heading', { name: 'TorrentPotato', exact: true }) });
      await card.locator('h3 button[aria-expanded="false"]').click();

      await card.getByRole('button', { name: /Sync Indexers/ }).click();
      const note = card.getByTestId('combine-locked-note');
      await expect(note).toBeVisible();
      await expect(card.getByLabel('name for row 1', { exact: true })).toHaveJSProperty('readOnly', true);
      await expectNoHorizontalDocumentOverflow(page, `locked combined field, ${theme}`);
      const fits = await note.evaluate((element) => {
        const rect = element.getBoundingClientRect();
        return rect.left >= 0 && rect.right <= document.documentElement.clientWidth && element.scrollWidth <= element.clientWidth;
      });
      expect(fits).toBe(true);
      release();
      await expect(card.locator('[aria-busy="true"]')).toHaveCount(0);
    });
  });
}
