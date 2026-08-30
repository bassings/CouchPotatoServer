import { test, expect } from './fixtures';
import { type Page } from '@playwright/test';
import AxeBuilder from '@axe-core/playwright';

/**
 * FEAT-011 (specs/FEAT-011-replace-with-this-file.md) -- the accessibility
 * criteria for the "Replace with this file" operator modal that specifically
 * require the real mobile-chrome project (Pixel 5, 393px, touch emulated --
 * playwright.config.ts), not merely a resized desktop viewport: AC-A11Y-13
 * (no horizontal overflow, a long candidate name included) and the 393px
 * half of AC-A11Y-14 (target size).
 *
 * playwright.config.ts scopes this project to `*.mobile.spec.ts` files only
 * -- an assertion in operator-replace-modal.a11y.spec.ts or
 * operator-replace-modal.spec.ts would simply never run under
 * `--project=mobile-chrome`. This repo has already shipped the exact
 * failure mode point 8 exists to catch once: a native <select> sizing to
 * its widest option at 441px inside a 393px viewport
 * (tests/e2e/small-screen.mobile.spec.ts). A candidate file name is
 * routinely far longer than a quality-profile label, so the risk here is
 * larger, not smaller.
 *
 * TDD RED phase: no production template or script has been touched by this
 * task.
 */

const REVIEW_MOVIE_ID = 'e2e-seed-movie-007';

const CANDIDATE_ROUTE = /renamer\.operator_candidates/;

// At least 60 characters, per the task's own point 8 -- long enough that a
// naive fixed-width or non-wrapping row would overflow a 393px viewport.
const LONG_CANDIDATE = 'Minions.and.Monsters.2024.2160p.UHD.HDR10Plus.DoVi.Atmos.TrueHD-VERY-LONG-RELEASE-GROUP-NAME-INDEED.mkv';
const CANDIDATES = [LONG_CANDIDATE, 'Some.Other.Placed.File.2024.mkv'];

function candidatesResponse(candidates: string[]) {
  return {
    status: 200,
    contentType: 'application/json',
    body: JSON.stringify({ success: true, candidates }),
  };
}

async function gotoReviewMovie(page: Page, movieId: string) {
  await page.goto(`/movie/${movieId}`);
  const loaded = await page.locator('#movie-releases')
    .waitFor({ state: 'attached', timeout: 15000 })
    .then(() => true)
    .catch(() => false);
  expect(
    loaded,
    `No seeded movie at /movie/${movieId}. Run ` +
    '`.venv/bin/python scripts/seed_e2e_data.py --data_dir=.e2e-data` before ' +
    'starting the server.',
  ).toBe(true);
}

async function openReplaceModal(page: Page, movieId: string, candidates: string[] = CANDIDATES) {
  await page.route(CANDIDATE_ROUTE, (route) => route.fulfill(candidatesResponse(candidates)));

  await gotoReviewMovie(page, movieId);

  const trigger = page.locator('[data-testid="operator-replace-trigger"]');
  await expect(
    trigger,
    'operator-replace trigger did not render -- did scripts/seed_e2e_data.py ' +
    'seed a files.movie entry for this release?',
  ).toBeVisible({ timeout: 10000 });
  await trigger.click();

  const modal = page.locator('[data-testid="operator-replace-modal"]');
  await expect(modal).toBeVisible({ timeout: 5000 });
  await expect(modal.getByRole('radio', { name: candidates[0], exact: true })).toBeVisible({ timeout: 5000 });
  return modal;
}

test.describe('FEAT-011 Operator replace modal -- mobile (393px)', () => {
  // -------------------------------------------------------------------
  // Point 8: no horizontal document overflow, with a long candidate name.
  // -------------------------------------------------------------------
  test('the modal introduces no horizontal document overflow with a long candidate name (point 8, AC-A11Y-13)', async ({ page }) => {
    expect(page.viewportSize()!.width, 'this project must run at the 393px device width').toBe(393);
    await openReplaceModal(page, REVIEW_MOVIE_ID);

    const overflow = await page.evaluate(() => ({
      scrollWidth: document.documentElement.scrollWidth,
      clientWidth: document.documentElement.clientWidth,
    }));
    expect(
      overflow.scrollWidth,
      `document scrolls horizontally with the modal open (${overflow.scrollWidth}px content in ` +
      `${overflow.clientWidth}px) -- WCAG 1.4.10 reflow`,
    ).toBeLessThanOrEqual(overflow.clientWidth);
  });

  // -------------------------------------------------------------------
  // Point 8: the dialog, every candidate row and both footer controls are
  // fully inside the device width.
  // -------------------------------------------------------------------
  test('the dialog, every candidate row and both footer controls stay inside the 393px device width (point 8, AC-A11Y-13)', async ({ page }) => {
    const modal = await openReplaceModal(page, REVIEW_MOVIE_ID);
    const device = page.viewportSize()!.width;

    const dialogBox = await modal.boundingBox();
    expect(dialogBox, 'dialog has no bounding box').not.toBeNull();
    expect(
      Math.round(dialogBox!.x + dialogBox!.width),
      `dialog extends past the ${device}px device viewport`,
    ).toBeLessThanOrEqual(device);
    expect(dialogBox!.x, 'dialog left edge is off-screen').toBeGreaterThanOrEqual(0);

    const radios = modal.getByRole('radio');
    const radioCount = await radios.count();
    expect(radioCount, 'expected both seeded candidates to render as radios').toBe(CANDIDATES.length);
    for (let i = 0; i < radioCount; i++) {
      const box = await radios.nth(i).boundingBox();
      expect(box, `candidate row ${i} has no bounding box`).not.toBeNull();
      expect(
        Math.round(box!.x + box!.width),
        `candidate row ${i} extends past the ${device}px device viewport`,
      ).toBeLessThanOrEqual(device);
      expect(box!.x, `candidate row ${i} left edge is off-screen`).toBeGreaterThanOrEqual(0);
    }

    const confirm = modal.locator('[data-testid="operator-replace-confirm"]');
    const cancel = modal.getByRole('button', { name: 'Cancel', exact: true });
    for (const [name, locator] of [['confirm', confirm], ['cancel', cancel]] as const) {
      const box = await locator.boundingBox();
      expect(box, `${name} control has no bounding box`).not.toBeNull();
      expect(
        Math.round(box!.x + box!.width),
        `${name} control extends past the ${device}px device viewport`,
      ).toBeLessThanOrEqual(device);
      expect(box!.x, `${name} control left edge is off-screen`).toBeGreaterThanOrEqual(0);
    }
  });

  // -------------------------------------------------------------------
  // Point 8: the candidate list scrolls rather than being clipped. Proven
  // by making the list definitely taller than its max-height (many
  // candidates) and driving a REAL wheel gesture over it, not
  // `scrollIntoViewIfNeeded()`.
  //
  // `scrollIntoViewIfNeeded` was tried first and is NOT load-bearing here:
  // mutated to `overflow-y-hidden` in movie_detail.html (confirmed applied
  // via md5, confirmed restored to the identical byte content afterwards),
  // the suite stayed green -- `overflow: hidden` still lets *script* move
  // `scrollTop`, it only stops a real user's wheel/touch gesture, and
  // `scrollIntoViewIfNeeded` scrolls via script. A real `page.mouse.wheel`
  // over the list, by contrast, measurably fails to move `scrollTop` under
  // the same mutation (0 -> 0) and measurably succeeds against the real
  // template (0 -> 620) -- that is what this test drives instead.
  // -------------------------------------------------------------------
  test('the candidate list is scrollable by a real wheel gesture, not clipped, when candidates overflow it (point 8)', async ({ page }) => {
    const manyCandidates = Array.from({ length: 30 }, (_, i) => `Candidate.File.${i.toString().padStart(2, '0')}.2024.mkv`);
    const modal = await openReplaceModal(page, REVIEW_MOVIE_ID, manyCandidates);

    const list = modal.locator('[role="radiogroup"]');
    await expect(list).toBeVisible();

    const metrics = await list.evaluate((el) => ({
      overflowY: getComputedStyle(el).overflowY,
      scrollHeight: el.scrollHeight,
      clientHeight: el.clientHeight,
    }));
    expect(
      metrics.scrollHeight,
      'the fixture must make the candidate list taller than its box for this test to mean anything -- it did not overflow',
    ).toBeGreaterThan(metrics.clientHeight);
    expect(
      ['auto', 'scroll'].includes(metrics.overflowY),
      `the candidate list's overflow-y is "${metrics.overflowY}" -- it must be "auto" or "scroll" so candidates past ` +
      'the visible height stay reachable, not "hidden" (silently clips them)',
    ).toBe(true);

    const box = await list.boundingBox();
    expect(box, 'candidate list has no bounding box').not.toBeNull();
    await page.mouse.move(box!.x + box!.width / 2, box!.y + box!.height / 2);
    const scrollTopBefore = await list.evaluate((el) => el.scrollTop);
    await page.mouse.wheel(0, 2000);
    await expect
      .poll(() => list.evaluate((el) => el.scrollTop), { timeout: 5000 })
      .toBeGreaterThan(scrollTopBefore);

    const lastCandidate = modal.getByRole('radio', { name: manyCandidates[manyCandidates.length - 1], exact: true });
    await expect(
      lastCandidate,
      'the last candidate must be visible after wheel-scrolling the list -- a clipped list would leave it permanently unreachable',
    ).toBeVisible();

    const lastBox = await lastCandidate.boundingBox();
    expect(lastBox, 'last candidate has no bounding box once scrolled into view').not.toBeNull();
    const device = page.viewportSize()!.width;
    expect(lastBox!.y, 'last candidate must be within the viewport vertically once scrolled to').toBeGreaterThanOrEqual(0);
    expect(lastBox!.x + lastBox!.width, 'last candidate must stay inside the device width even when scrolled').toBeLessThanOrEqual(device);
  });

  // -------------------------------------------------------------------
  // Point 8 / AC-A11Y-14: every control meets the 24x24 target-size
  // floor at 393px, and the confirm control (which commits the deletion)
  // meets 44x44.
  // -------------------------------------------------------------------
  test('confirm, cancel and every candidate radio meet the 24x24 target size floor at 393px (point 8, AC-A11Y-14)', async ({ page }) => {
    const modal = await openReplaceModal(page, REVIEW_MOVIE_ID);
    expect(page.viewportSize()!.width, 'this test measures the 393px case of AC-A11Y-14').toBe(393);

    await modal.getByRole('radio', { name: CANDIDATES[0], exact: true }).click();
    const confirmBtn = modal.locator('[data-testid="operator-replace-confirm"]');
    const cancelBtn = modal.getByRole('button', { name: 'Cancel', exact: true });

    const boxes: Array<[string, { width: number; height: number } | null]> = [
      ['confirm', await confirmBtn.boundingBox()],
      ['cancel', await cancelBtn.boundingBox()],
    ];
    const radios = modal.getByRole('radio');
    const radioCount = await radios.count();
    for (let i = 0; i < radioCount; i++) {
      boxes.push([`radio ${i}`, await radios.nth(i).boundingBox()]);
    }

    for (const [name, box] of boxes) {
      expect(box, `${name} has no bounding box at 393px`).not.toBeNull();
      expect(box!.width, `${name} width at 393px`).toBeGreaterThanOrEqual(24);
      expect(box!.height, `${name} height at 393px`).toBeGreaterThanOrEqual(24);
    }

    const results = await new AxeBuilder({ page })
      .include('[data-testid="operator-replace-modal"]')
      .withRules(['target-size'])
      .analyze();
    const detail = results.violations.flatMap((v) => v.nodes.map((n) => n.html)).join('\n');
    expect(results.violations.length, `axe target-size violations at 393px:\n${detail}`).toBe(0);
  });

  test('the confirm control meets the 44x44 target size floor at 393px (point 8, AC-A11Y-14)', async ({ page }) => {
    const modal = await openReplaceModal(page, REVIEW_MOVIE_ID);
    await modal.getByRole('radio', { name: CANDIDATES[0], exact: true }).click();

    const confirmBtn = modal.locator('[data-testid="operator-replace-confirm"]');
    const box = await confirmBtn.boundingBox();
    expect(box, 'confirm control has no bounding box at 393px').not.toBeNull();
    expect(
      box!.width,
      'confirm control width at 393px -- a mis-tap on a phone destroys an irreplaceable file',
    ).toBeGreaterThanOrEqual(44);
    expect(box!.height, 'confirm control height at 393px').toBeGreaterThanOrEqual(44);
  });
});
