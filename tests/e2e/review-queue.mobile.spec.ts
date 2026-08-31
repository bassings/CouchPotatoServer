import { test, expect } from './fixtures';
import { layoutPx, TARGET_SIZE_MIN } from './helpers';
import { Page } from '@playwright/test';
import AxeBuilder from '@axe-core/playwright';

/**
 * FEAT-010 (specs/FEAT-010-review-queue-in-wanted.md) -- the accessibility
 * criteria that specifically require the real mobile-chrome project
 * (Pixel 5, 393px, touch emulated -- playwright.config.ts), not merely a
 * resized desktop viewport:
 *
 *   AC-A11Y-7:  hover does not exist on touch, so "visible without hover"
 *               has to be checked where hover genuinely cannot fire.
 *   AC-A11Y-8:  target size at the 393px half of its two required widths.
 *   AC-A11Y-14: reflow at the 393px half of its two required widths.
 *
 * playwright.config.ts scopes this project to `*.mobile.spec.ts` files
 * only -- an assertion in review-queue.a11y.spec.ts or filters.spec.ts
 * would simply never run under `--project=mobile-chrome`.
 *
 * TDD RED phase: no production file has been touched by this task. See the
 * accompanying a11y spec file's header comment for the same note.
 */

const REVIEW_MOVIE_ID = 'e2e-seed-movie-007';

async function waitForGridLoaded(page: Page) {
  await expect(page.locator('#movie-count')).not.toBeEmpty({ timeout: 15000 });
}

async function gotoWantedWithReviewCard(page: Page) {
  await page.goto('/wanted');
  await waitForGridLoaded(page);
  const card = page.locator(`.poster-card[data-movie-id="${REVIEW_MOVIE_ID}"]`);
  await expect(
    card,
    'REVIEW_MOVIE_ID must be seeded and visible on Wanted -- did scripts/seed_e2e_data.py run?',
  ).toHaveCount(1, { timeout: 10000 });
  return card;
}

test.describe('FEAT-010 Review queue -- mobile (393px)', () => {
  test('Mark Done and Mark Failed are visible on first paint with no hover applied (AC-A11Y-7, mobile)', async ({ page }) => {
    const card = await gotoWantedWithReviewCard(page);

    // No .hover(), no pointer move -- this project has no pointer that can
    // hover at all (Pixel 5 device profile), which is the whole point: a
    // control that only appears on hover/focus (group-hover:opacity-100,
    // the pattern the pre-existing refresh button at movie_cards.html:105
    // deliberately uses) would be permanently invisible here.
    const markDone = card.locator('[data-testid="review-mark-done"]');
    const markFailed = card.locator('[data-testid="review-mark-failed"]');

    await expect(markDone).toBeVisible();
    await expect(markFailed).toBeVisible();

    const opacityDone = await markDone.evaluate((el) => window.getComputedStyle(el).opacity);
    const opacityFailed = await markFailed.evaluate((el) => window.getComputedStyle(el).opacity);
    expect(opacityDone, 'Mark Done must render fully opaque with no hover/focus applied').toBe('1');
    expect(opacityFailed, 'Mark Failed must render fully opaque with no hover/focus applied').toBe('1');
  });

  test('Review chip and card review control meet the 24x24 CSS px target size at 393px (AC-A11Y-8, mobile)', async ({ page }) => {
    const card = await gotoWantedWithReviewCard(page);
    expect(page.viewportSize()!.width, 'this project must run at the 393px device width').toBe(393);

    const chipBox = await page.getByRole('button', { name: 'Review', exact: true }).boundingBox();
    const controlBox = await card.locator('[data-testid="review-mark-done"]').boundingBox();

    for (const [name, box] of [['Review chip', chipBox], ['Mark Done control', controlBox]] as const) {
      expect(box, `${name} has no bounding box at 393px`).not.toBeNull();
      expect(layoutPx(box!.width), `${name} width at 393px`).toBeGreaterThanOrEqual(TARGET_SIZE_MIN);
      expect(layoutPx(box!.height), `${name} height at 393px`).toBeGreaterThanOrEqual(TARGET_SIZE_MIN);
    }

    const results = await new AxeBuilder({ page })
      .include('#movie-grid')
      .withRules(['target-size'])
      .analyze();
    const detail = results.violations.flatMap((v) => v.nodes.map((n) => n.html)).join('\n');
    expect(results.violations.length, `axe target-size violations at 393px:\n${detail}`).toBe(0);
  });

  test('no horizontal reflow at 393px, and the review control stays reachable once focused (AC-A11Y-14, mobile)', async ({ page }) => {
    const card = await gotoWantedWithReviewCard(page);

    const overflow = await page.evaluate(() => ({
      scrollWidth: document.documentElement.scrollWidth,
      clientWidth: document.documentElement.clientWidth,
    }));
    expect(
      overflow.scrollWidth,
      `document scrolls horizontally at 393px (${overflow.scrollWidth}px content in ${overflow.clientWidth}px) -- WCAG 1.4.10 reflow`,
    ).toBeLessThanOrEqual(overflow.clientWidth);

    const markDone = card.locator('[data-testid="review-mark-done"]');
    await markDone.focus();
    await expect(markDone).toBeFocused();
    const box = await markDone.boundingBox();
    expect(box).not.toBeNull();
    const device = page.viewportSize()!.width;
    expect(box!.x, `Mark Done's left edge is off-screen at ${device}px once focused`).toBeGreaterThanOrEqual(0);
    expect(box!.x + box!.width, `Mark Done extends past the ${device}px device viewport once focused`).toBeLessThanOrEqual(device);
  });
});
