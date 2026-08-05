import { test, expect, Page } from '@playwright/test';
import AxeBuilder from '@axe-core/playwright';

/**
 * Mobile and small-screen coverage — an AGENTS.md high-priority dimension
 * ("Any mobile layout regression that blocks searching, adding, editing,
 * wanted-list management, settings, or library workflows").
 *
 * This file exists because that dimension had never been reviewed on this
 * project. The first review that applied the AGENTS.md rubric found the restore
 * profile picker overflowing the phone viewport within minutes: a native <select>
 * sizes to its WIDEST <option>, the row had no flex-wrap, and the select had no
 * max-width — so a descriptively-named quality profile pushed "Cancel" clean off
 * the screen with no scroll affordance. Measured at the time: a 45-character
 * profile label gave a 441px control row and document.scrollWidth 562 against a 393px viewport.
 *
 * Runs under the `mobile-chrome` project (Pixel 5, 393px), configured in
 * playwright.config.ts and never used.
 */

// The DESTRUCTIVE fixture: this spec opens the restore picker, and restoring
// marks the movie's held releases 'ignored', which would destroy what
// release_controls.spec.ts needs. See scripts/seed_e2e_data.py.
const SEEDED_MOVIE_ID = 'e2e-seed-movie-002';

/** A profile list with a long label — the case that overflows. */
async function stubLongProfiles(page: Page) {
  await page.route(/\/profile\.list/, (route) =>
    route.fulfill({
      status: 200,
      contentType: 'application/json',
      body: JSON.stringify({
        success: true,
        list: [
          { _id: 'p1', label: 'HD 1080p BluRay preferred, no cam or telesync', hide: false },
          { _id: 'p2', label: 'SD', hide: false },
        ],
      }),
    }),
  );
}

/** The page must never scroll sideways — that is what puts controls out of reach. */
async function expectNoHorizontalOverflow(page: Page, context: string) {
  const measured = await page.evaluate(() => ({
    scrollWidth: document.documentElement.scrollWidth,
    clientWidth: document.documentElement.clientWidth,
  }));
  expect(
    measured.scrollWidth,
    `${context}: the page scrolls horizontally (${measured.scrollWidth}px of content in ` +
      `${measured.clientWidth}px) — controls past the right edge cannot be reached`,
  ).toBeLessThanOrEqual(measured.clientWidth);
}

test.describe('Small-screen layout', () => {
  test('the restore profile picker fits the viewport, long labels included', async ({ page }) => {
    await stubLongProfiles(page);

    /*
     * No release-list stub here, deliberately.
     *
     * An earlier version stubbed /partial/movie/<id>/releases and called it
     * load-bearing. Instrumented with a hit counter it fired ZERO times: the
     * release table is server-rendered inline on this route, so the stub never
     * intercepted anything. Its stated mechanism was wrong too -- the table
     * does not stretch the LAYOUT viewport (measured clientWidth 393,
     * scrollWidth 562; only scroll width grows).
     *
     * None of that matters to this test, which is the point: the assertion
     * measures the control row against the DEVICE width, so it holds whatever
     * else is on the page. Verified by deleting the stub and re-running the
     * both-fixes-reverted mutation -- still fails at 441px.
     */
    await page.goto(`/movie/${SEEDED_MOVIE_ID}`);
    await page.locator('#movie-releases').waitFor({ state: 'attached', timeout: 15000 });

    // The layout viewport matches the device (Pixel 5 is 393px, not 375).
    // Kept as a sanity check on the device profile, NOT as proof of anything
    // about the release table -- an earlier comment claimed the latter and was
    // wrong; scrollWidth grows, clientWidth does not.
    const layoutWidth = await page.evaluate(() => document.documentElement.clientWidth);
    expect(layoutWidth, 'unexpected layout viewport for this device profile')
      .toBe(page.viewportSize()!.width);

    const trigger = page.locator('[data-testid="restore-to-wanted"]');
    if ((await trigger.count()) === 0) { // vacuous-guard-ok: primes the shared FEAT-008 fixture into 'done' status if an earlier spec has not already -- suite ordering, not something this test controls; the block's own assertions (Mark as Done becomes visible, then the restore trigger) are real either way.
      const markDone = page.getByRole('button', { name: 'Mark as Done', exact: true });
      await expect(markDone).toBeVisible({ timeout: 5000 });
      await markDone.click();
      await page.waitForLoadState('networkidle');
      await expect(trigger).toBeVisible({ timeout: 10000 });
    }
    await trigger.click();

    const picker = page.locator('select[id^="restore-profile-"]');
    await expect(picker).toBeVisible({ timeout: 5000 });

    /*
     * Assert against the DEVICE width, not the current layout width.
     *
     * This page renders the release table inline, and that table is ~940px in
     * an overflow container on master — which stretches the layout viewport to
     * ~562px and makes the picker row *happen* to fit. That overflow is
     * pre-existing and not this branch's to fix, but it must not be what makes
     * this test pass: the control has to fit the phone on its own, because a
     * movie with no matching releases renders no table and gets no stretch.
     *
     * So the invariant is: the picker row fits within the device viewport.
     * Measured before the fix: 441px row inside a 393px device.
     */
    const device = page.viewportSize()!.width;
    const rowWidth = await picker.evaluate(
      (el) => Math.round((el.parentElement as HTMLElement).getBoundingClientRect().width),
    );
    expect(
      rowWidth,
      `the restore control row is ${rowWidth}px on a ${device}px device, so part of ` +
        'it is unreachable on a page that is not stretched by something else',
    ).toBeLessThanOrEqual(device);

    // Every control in the row, Cancel included. An earlier version checked
    // only the picker and Confirm — and Confirm's right edge happened to land
    // 2px inside the viewport while Cancel sat well outside it, so the test
    // passed with the control unreachable.
    const confirm = page.locator('[data-testid="restore-to-wanted-confirm"]');
    const cancel = page.getByRole('button', { name: 'Cancel', exact: true });
    for (const [name, locator] of [
      ['picker', picker], ['confirm', confirm], ['cancel', cancel],
    ] as const) {
      const box = await locator.boundingBox();
      expect(box, `${name} has no box`).not.toBeNull();
      expect(
        Math.round(box!.x + box!.width),
        `${name} extends past the ${device}px device viewport`,
      ).toBeLessThanOrEqual(device);
    }
  });

  test('the wanted list has no reach-blocking accessibility failures', async ({ page }) => {
    await page.goto('/');
    await expect(page.locator('#movie-grid')).toBeAttached({ timeout: 10000 });
    await page.locator('#filter-movies').fill('zzz-no-such-movie-zzz');

    // Wait for the control under test to be VISIBLE before scanning. axe skips
    // hidden nodes, and Alpine's x-show had not flushed in 6 of 8 measured
    // iterations immediately after fill() -- so a fast analyze() would pass
    // with zero coverage, and only ever green. A silent false pass.
    await expect(page.locator('#filter-movies ~ button')).toBeVisible();

    await expectNoHorizontalOverflow(page, 'wanted list with a filter applied');

    const results = await new AxeBuilder({ page })
      .withTags(['wcag2a', 'wcag2aa', 'wcag21a', 'wcag21aa', 'wcag22aa'])
      .analyze();

    // button-name is critical; target-size is WCAG 2.2 AA (2.5.8) and is the
    // difference between a control a thumb can hit and one it cannot.
    const blocking = results.violations.filter(
      (v) => v.id === 'button-name' || v.id === 'target-size',
    );
    const detail = blocking
      .flatMap((v) => v.nodes.map((n) => `${v.id}: ${n.html}`))
      .join('\n');
    expect(blocking.length, `reach-blocking violations:\n${detail}`).toBe(0);
  });
});
