import type { Locator, Page } from '@playwright/test';

import { test, expect } from './fixtures';
import { mockSettingsSave, openProvidersStep, TARGET_SIZE_MIN } from './helpers';
import {
  DID_NOT_SAVE,
  KEY_ONE,
  OTHER_URL,
  REFUSAL,
  SEEDED_URL,
  STILL_SAVING,
  holdKeySaves,
  stubWizardSyncRefusal,
  THEMES,
  keyField,
  openTorrentCard,
  pressSync,
  refuseByAddressChange,
  resultRegion,
  saveThroughApi,
  syncButton,
} from './jackett-sync-page';
import { SETTINGS_PERSISTENCE_ANNOTATION } from './settings_persistence';

/**
 * SEC-005 P3 (AC-A11Y-8, AC-A11Y-11, AC-ARCH-9 layout): the Sync result and the wizard's Jackett result line
 * at a 320 CSS px viewport, the WCAG 1.4.10 equivalent of 1280px at 400% zoom (Playwright cannot emulate
 * zoom, so the viewport is set explicitly), in both themes. The text reflows with no horizontal scroll,
 * is not clipped, and does not overlap the key input or the Sync button. The refusal comes from the real
 * server (no stub on the Settings sync route); the wizard's is the one stubbed route.
 */

const WIDTH = 320;

type Box = { left: number; right: number; top: number; bottom: number };

const boxOf = async (locator: Locator): Promise<Box> => {
  const box = await locator.boundingBox();
  if (!box) throw new Error('element has no box: it is not on screen');
  return { left: box.x, right: box.x + box.width, top: box.y, bottom: box.y + box.height };
};

const overlaps = (a: Box, b: Box) => a.left < b.right && b.left < a.right && a.top < b.bottom && b.top < a.bottom;

/** The text is wholly inside the viewport, is not clipped by its own box, and the page does not scroll sideways. */
async function expectReflowed(page: Page, message: Locator, label: string) {
  const layout = await page.evaluate(() => ({
    viewport: document.documentElement.clientWidth,
    scroll: document.scrollingElement!.scrollWidth,
  }));
  const clipped = await message.evaluate((element) => element.scrollWidth > element.clientWidth);
  const box = await boxOf(message);
  expect(layout.viewport, `${label}: the viewport is not ${WIDTH}px`).toBe(WIDTH);
  expect(layout.scroll, `${label}: the page scrolls sideways`).toBeLessThanOrEqual(layout.viewport);
  expect(box.left, `${label}: starts off screen`).toBeGreaterThanOrEqual(0);
  expect(box.right, `${label}: ends off screen`).toBeLessThanOrEqual(layout.viewport);
  expect(clipped, `${label}: is clipped`).toBe(false);
  expect(box.bottom - box.top, `${label}: has no height`).toBeGreaterThan(0);
}

for (const theme of THEMES) {
  test.describe(`at ${WIDTH}px in the ${theme} theme`, () => {
    test.describe('Settings', () => {
      test.use({ seedConfig: `fresh_defaults#jackett-mobile-refusal-${theme}` });

      test('the refusal reflows, is not clipped, and overlaps neither the key input nor the Sync button', async ({ page, testServer }) => {
        test.info().annotations.push({ type: SETTINGS_PERSISTENCE_ANNOTATION });
        await page.setViewportSize({ width: WIDTH, height: 800 });
        await refuseByAddressChange(page, testServer.apiBase, KEY_ONE, OTHER_URL);
        const card = await openTorrentCard(page, { theme });

        const answer = await pressSync(page, card);

        expect(answer.error).toBe(REFUSAL);
        await expect(resultRegion(card)).toHaveText(REFUSAL);
        await expectReflowed(page, resultRegion(card), `${theme} refusal`);
        const region = await boxOf(resultRegion(card));
        expect(overlaps(region, await boxOf(keyField(card))), 'the refusal overlaps the key input').toBe(false);
        expect(overlaps(region, await boxOf(syncButton(card))), 'the refusal overlaps the Sync button').toBe(false);
        // It sits under the button, where the user's eye already is.
        expect(region.top).toBeGreaterThanOrEqual((await boxOf(syncButton(card))).bottom);
      });
    });

    test.describe('Settings, Sync that did not run', () => {
      test.use({ seedConfig: `fresh_defaults#jackett-mobile-notrun-${theme}` });

      test('the "did not save" text reflows the same way, and the Sync button is at least 24 by 24 CSS px', async ({ page, testServer }) => {
        test.info().annotations.push({ type: SETTINGS_PERSISTENCE_ANNOTATION });
        await page.setViewportSize({ width: WIDTH, height: 800 });
        await saveThroughApi(page, testServer.apiBase, 'jackett_url', SEEDED_URL);
        await saveThroughApi(page, testServer.apiBase, 'jackett_api_key', KEY_ONE);
        const card = await openTorrentCard(page, { theme, fakeClock: true });

        await keyField(card).fill('*'.repeat(KEY_ONE.length));
        await syncButton(card).click();

        await expect(resultRegion(card)).toHaveText(DID_NOT_SAVE);
        await expectReflowed(page, resultRegion(card), `${theme} did-not-save`);
        const region = await boxOf(resultRegion(card));
        expect(overlaps(region, await boxOf(keyField(card)))).toBe(false);
        const button = await boxOf(syncButton(card));
        expect(overlaps(region, button)).toBe(false);
        expect(button.right - button.left).toBeGreaterThanOrEqual(TARGET_SIZE_MIN);
        expect(button.bottom - button.top).toBeGreaterThanOrEqual(TARGET_SIZE_MIN);
      });
    });

    test.describe('Settings, Sync that did not run, still saving', () => {
      test.use({ seedConfig: `fresh_defaults#jackett-mobile-unanswered-${theme}` });

      test('the "not finished saving" text reflows at 320px too, and overlaps neither the key input nor the Sync button', async ({ page, testServer }) => {
        test.info().annotations.push({ type: SETTINGS_PERSISTENCE_ANNOTATION });
        await page.setViewportSize({ width: WIDTH, height: 800 });
        await saveThroughApi(page, testServer.apiBase, 'jackett_url', SEEDED_URL);
        await saveThroughApi(page, testServer.apiBase, 'jackett_api_key', KEY_ONE);
        const card = await openTorrentCard(page, { theme, fakeClock: true });
        const held = await holdKeySaves(page);

        await keyField(card).fill('placeholder-typed-key');
        await syncButton(card).click();
        await held.firstSent;
        await page.clock.fastForward(10_000);

        await expect(resultRegion(card)).toHaveText(STILL_SAVING);
        await expectReflowed(page, resultRegion(card), `${theme} still-saving`);
        const region = await boxOf(resultRegion(card));
        expect(overlaps(region, await boxOf(keyField(card)))).toBe(false);
        expect(overlaps(region, await boxOf(syncButton(card)))).toBe(false);
      });
    });

    test('Wizard: the refusal on the Jackett result line reflows and does not overlap the Sync button', async ({ page }) => {
      await page.setViewportSize({ width: WIDTH, height: 800 });
      await mockSettingsSave(page);
      await stubWizardSyncRefusal(page);
      await page.addInitScript((value) => localStorage.setItem('cp-theme', value), theme);
      await openProvidersStep(page, /^Torrents/);
      await expect.poll(() => page.evaluate(() => document.documentElement.classList.contains('light'))).toBe(theme === 'light');
      await page.getByRole('switch', { name: 'Enable Jackett / TorrentPotato' }).click();
      await page.locator('#wizard-jackett-url').fill(SEEDED_URL);
      await page.locator('#wizard-jackett-api-key').fill(KEY_ONE);
      const sync = page.getByRole('button', { name: 'Sync Trackers from Jackett' });

      await sync.click();

      const line = page.locator('p[x-text="jackettSyncResult"]');
      await expect(line).toHaveText(REFUSAL);
      await expectReflowed(page, line, `${theme} wizard refusal`);
      const lineBox = await boxOf(line);
      expect(overlaps(lineBox, await boxOf(sync))).toBe(false);
      expect(overlaps(lineBox, await boxOf(page.locator('#wizard-jackett-api-key')))).toBe(false);
    });
  });
}
