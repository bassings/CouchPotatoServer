import { test, expect } from './fixtures';
import { Page } from '@playwright/test';
import AxeBuilder from '@axe-core/playwright';

/**
 * FEAT-010 (specs/FEAT-010-review-queue-in-wanted.md) -- accessibility
 * criteria AC-A11Y-1 through AC-A11Y-14 for the Wanted-page review queue
 * (the Review filter chip in wanted.html, and the card-level Mark Done /
 * Mark Failed controls in partials/movie_cards.html).
 *
 * Runs in the `accessibility` project (playwright.config.ts), which pins
 * `colorScheme: 'light'` and Desktop Chrome's default 1280x720 viewport --
 * the AC-A11Y-1/1280px-width numbers below are measured against that, not
 * assumed. Dark-theme cases seed `cp-theme` into localStorage BEFORE
 * navigation, same pattern as accessibility.a11y.spec.ts's toast-contrast
 * tests, and assert the theme actually took effect before trusting anything
 * measured under it.
 *
 * TDD RED phase (see the task this file was written for): no production
 * template or script has been touched. Every test here is expected to fail,
 * and the specific failure it must show is recorded in this session's
 * report, not in this file -- a test file is not the place to assert what
 * its own current run will do.
 *
 * Fixtures: scripts/seed_e2e_data.py's two dedicated review-gate movies
 * (AC-QA-9). Deliberately duplicated as string constants rather than
 * imported (fixtures.ts's own SEEDED_MOVIE_ID does the same, and explains
 * why in its comment: this file must not import a .spec.ts, and the seed
 * script is Python).
 *
 *   REVIEW_MOVIE_ID              -- read-only assertions only. Every test
 *                                    that could mutate it intercepts the
 *                                    network route instead of letting the
 *                                    request reach the real backend, so it
 *                                    stays 'downloaded' for whichever test
 *                                    in this file (or a later one sharing
 *                                    this worker's server) runs next.
 *   REVIEW_DESTRUCTIVE_MOVIE_ID   -- the ONE real, unmocked Mark Done call
 *                                    in this file (the "others remain"
 *                                    case of AC-A11Y-9/10/11, run LAST).
 *                                    Once that test runs, this movie is
 *                                    'done', not 'downloaded' -- so nothing
 *                                    after it in this file may depend on it
 *                                    still being in the review queue.
 */

const REVIEW_MOVIE_ID = 'e2e-seed-movie-007';
const REVIEW_MOVIE_TITLE = 'E2E Review Gate Movie';
const REVIEW_DESTRUCTIVE_MOVIE_ID = 'e2e-seed-movie-008';
const REVIEW_DESTRUCTIVE_MOVIE_TITLE = 'E2E Review Gate Destructive Movie';
// An ordinary active movie with no releases (scripts/seed_e2e_data.py's
// WANTED_MOVIE_ID), used only as "some other, unrelated card" for the
// grid-confinement check in AC-A11Y-11 -- never clicked, never mutated.
const ORDINARY_MOVIE_ID = 'e2e-seed-movie-004';
// Search text that matches ONLY MOVIE_ID ('E2E Seed Movie', status
// 'active') and neither review-gate title, used by AC-A11Y-4 to make the
// Review chip's own activation the thing that empties the grid.
const SEARCH_MATCHING_ONLY_AN_ACTIVE_MOVIE = 'E2E Seed Movie';

/** Same wait-for-swap idiom as filters.spec.ts's waitForGridLoaded: #movie-count
 *  is written by filterMovies(), which only runs on htmx:afterSwap. */
async function waitForGridLoaded(page: Page) {
  await expect(page.locator('#movie-count')).not.toBeEmpty({ timeout: 15000 });
}

async function gotoWantedWithReviewCards(page: Page) {
  await page.goto('/wanted');
  await waitForGridLoaded(page);
  const readOnlyCard = page.locator(`.poster-card[data-movie-id="${REVIEW_MOVIE_ID}"]`);
  await expect(
    readOnlyCard,
    'REVIEW_MOVIE_ID must be seeded and visible on Wanted -- did scripts/seed_e2e_data.py run?',
  ).toHaveCount(1, { timeout: 10000 });
  return { readOnlyCard };
}

async function setDarkTheme(page: Page) {
  await page.addInitScript(() => localStorage.setItem('cp-theme', 'dark'));
}

async function assertThemeIs(page: Page, light: boolean) {
  await expect
    .poll(() => page.evaluate(() => document.documentElement.classList.contains('light')))
    .toBe(light);
}

/**
 * The SAME single visibility+focus-ring definition accessibility.a11y.spec.ts
 * already uses (FOCUS_INDICATOR_PROBE there). Duplicated rather than
 * imported for the same reason every helper in that file is local: spec
 * files do not import each other.
 */
const FOCUS_RING_PROBE = (el: Element) => {
  const read = () => {
    const s = window.getComputedStyle(el);
    return {
      outlineStyle: s.outlineStyle,
      outlineWidth: s.outlineWidth,
      outlineColor: s.outlineColor,
      boxShadow: s.boxShadow,
    };
  };
  const invisible = (colour: string) =>
    !colour || colour === 'transparent' ||
    /rgba\(\s*[\d.]+\s*,\s*[\d.]+\s*,\s*[\d.]+\s*,\s*0\s*\)/.test(colour);
  const shadowHasSubstance = (shadow: string) =>
    shadow !== 'none' && shadow !== '' &&
    shadow.split(/,(?![^(]*\))/).some((layer) => {
      const colour = (layer.trim().match(/^(rgba?\([^)]*\)|#[0-9a-f]+|[a-z]+)/i) || [''])[0];
      const lengths = (layer.match(/-?[\d.]+px/g) || []).map(parseFloat);
      return !invisible(colour) && lengths.some((n) => n !== 0);
    });
  const hadFocus = document.activeElement === el;
  (el as HTMLElement).blur();
  const blurred = read();
  (el as HTMLElement).focus();
  const focused = read();
  if (!hadFocus) (el as HTMLElement).blur();
  const outlineVisible =
    focused.outlineStyle !== 'none' && parseFloat(focused.outlineWidth || '0') > 0 && !invisible(focused.outlineColor);
  const shadowVisible = shadowHasSubstance(focused.boxShadow) && focused.boxShadow !== blurred.boxShadow;
  const changedOnFocus =
    focused.outlineStyle !== blurred.outlineStyle ||
    focused.outlineWidth !== blurred.outlineWidth ||
    focused.outlineColor !== blurred.outlineColor ||
    focused.boxShadow !== blurred.boxShadow;
  return { ...focused, changedOnFocus, visible: (outlineVisible || shadowVisible) && changedOnFocus };
};

/**
 * Colour-contrast measurement, computed directly from getComputedStyle
 * rather than trusted to axe (which reports contrast over an image as
 * "incomplete", never a violation -- AC-A11Y-12 says so explicitly).
 *
 * Unlike the toast contrast test in accessibility.a11y.spec.ts (which reads
 * two OPAQUE colours straight off getComputedStyle), the elements here use
 * translucent Tailwind backgrounds (bg-cp-warning/20, bg-cp-accent/10,
 * bg-cp-success/10 ...), so the rendered pixel colour depends on whatever is
 * behind them. This composites the parsed rgba() foreground over a given
 * opaque backdrop colour first -- alpha blending, not a screenshot -- which
 * holds regardless of backdrop-filter blur, because blurring a uniform
 * colour yields the same uniform colour.
 */
function contrastAgainstBackdrop(fgRgba: string, textRgba: string, backdrop: [number, number, number]): number {
  const parse = (s: string) => {
    const m = s.match(/rgba?\(([\d.]+),\s*([\d.]+),\s*([\d.]+)(?:,\s*([\d.]+))?\)/);
    if (!m) throw new Error(`unparseable colour: ${s}`);
    return { r: +m[1], g: +m[2], b: +m[3], a: m[4] !== undefined ? +m[4] : 1 };
  };
  const composite = (fg: { r: number; g: number; b: number; a: number }, bg: [number, number, number]) => ({
    r: fg.r * fg.a + bg[0] * (1 - fg.a),
    g: fg.g * fg.a + bg[1] * (1 - fg.a),
    b: fg.b * fg.a + bg[2] * (1 - fg.a),
  });
  const luminance = (c: { r: number; g: number; b: number }) => {
    const [R, G, B] = [c.r, c.g, c.b].map((v) => {
      const s = v / 255;
      return s <= 0.04045 ? s / 12.92 : Math.pow((s + 0.055) / 1.055, 2.4);
    });
    return 0.2126 * R + 0.7152 * G + 0.0722 * B;
  };
  const bgEffective = composite(parse(fgRgba), backdrop);
  const textEffective = composite(parse(textRgba), [bgEffective.r, bgEffective.g, bgEffective.b]);
  const l1 = luminance(bgEffective);
  const l2 = luminance(textEffective);
  return (Math.max(l1, l2) + 0.05) / (Math.min(l1, l2) + 0.05);
}

test.describe('FEAT-010 Review queue accessibility', () => {
  // ---------------------------------------------------------------------
  // AC-A11Y-1: Review chip keyboard reachable and operable (Enter + Space),
  // with a >=3:1 focus indicator in BOTH themes.
  // ---------------------------------------------------------------------
  for (const theme of ['light', 'dark'] as const) {
    test(`Review chip is keyboard-operable with a visible focus indicator (${theme} theme, AC-A11Y-1)`, async ({ page }) => {
      if (theme === 'dark') await setDarkTheme(page);
      await gotoWantedWithReviewCards(page);
      await assertThemeIs(page, theme === 'light');

      const chip = page.getByRole('button', { name: 'Review', exact: true });
      await expect(chip).toBeVisible();

      // Reachable and operable by keyboard alone: focus it directly (the
      // established pattern in this suite -- see accessibility.a11y.spec.ts's
      // FOCUSABLE_CONTROLS, which focuses programmatically rather than
      // walking Tab from page top), then prove BOTH activation keys work.
      await chip.focus();
      await expect(chip).toBeFocused();

      const indicator = await chip.evaluate(FOCUS_RING_PROBE);
      expect(
        indicator.visible,
        `Review chip has no visible focus indicator in the ${theme} theme (WCAG 2.2 AA 1.4.11 non-text contrast). ` +
          `Computed: outline ${indicator.outlineStyle} ${indicator.outlineWidth} ${indicator.outlineColor}, ` +
          `box-shadow ${indicator.boxShadow}, changedOnFocus=${indicator.changedOnFocus}.`,
      ).toBe(true);

      await page.keyboard.press('Enter');
      await expect(chip).toHaveAttribute('aria-pressed', 'true');

      // Reset and prove Space activates it too.
      await page.getByRole('button', { name: 'All', exact: true }).click();
      await chip.focus();
      await page.keyboard.press(' ');
      await expect(chip).toHaveAttribute('aria-pressed', 'true');
    });
  }

  // ---------------------------------------------------------------------
  // AC-A11Y-2: all four chips expose selected state via role+pressed, not
  // colour alone.
  // ---------------------------------------------------------------------
  test('all four Wanted chips expose pressed state programmatically (AC-A11Y-2)', async ({ page }) => {
    await gotoWantedWithReviewCards(page);

    const labels = ['All', 'Wanted', 'Available', 'Review'];
    for (const active of labels) {
      await page.getByRole('button', { name: active, exact: true }).click();

      await expect(
        page.getByRole('button', { name: active, exact: true, pressed: true }),
        `clicking "${active}" must resolve it under getByRole(..., { pressed: true }) -- ` +
          `selection is currently signalled only by a class swap (wanted.html), which is invisible to a screen reader`,
      ).toHaveCount(1);

      for (const other of labels.filter((l) => l !== active)) {
        await expect(
          page.getByRole('button', { name: other, exact: true, pressed: false }),
          `"${other}" must resolve under pressed: false while "${active}" is selected`,
        ).toHaveCount(1);
      }
    }
  });

  // ---------------------------------------------------------------------
  // AC-A11Y-3: chip accessible name contains its label; the filtered-to-
  // empty panel and its announcer name the CHIP'S label, not the raw
  // 'downloaded' status token.
  // ---------------------------------------------------------------------
  test('Review chip accessible name and the empty-state text both say "Review", never the raw status token (AC-A11Y-3)', async ({ page }) => {
    await gotoWantedWithReviewCards(page);

    const chip = page.getByRole('button', { name: 'Review', exact: true });
    // SC 2.5.3: accessible name must CONTAIN the visible label. Visible
    // label is exactly "Review", so this only fails if something (e.g. an
    // aria-label overriding the text node) removes it.
    await expect(chip).toHaveAccessibleName(/review/i);

    await chip.click();
    await page.locator('#filter-movies').fill('zzz-nothing-matches-zzz');

    const panel = page.locator('[data-testid="filter-empty-state"]');
    await expect(panel).toBeVisible({ timeout: 5000 });
    const announcer = page.locator('[data-testid="filter-empty-announcer"]');

    const panelText = (await panel.textContent()) || '';
    const announcerText = (await announcer.textContent()) || '';

    expect(
      panelText,
      `the empty-state panel must name the chip's own label ("Review"), not leave the user guessing: "${panelText}"`,
    ).toMatch(/review/i);
    expect(
      announcerText,
      `the empty-state announcer must name the chip's own label ("Review"): "${announcerText}"`,
    ).toMatch(/review/i);

    // wanted.html:176 renders x-text="filterStatus" verbatim, which is the
    // raw internal token 'downloaded' -- a user-facing term the user never
    // chose (AC-PROD-8's own wording). \bdownloaded\b so a future correct
    // rendering ("...are downloaded...") could not be mistaken for this bug,
    // though the current one IS a bare status label.
    expect(panelText, `the panel must not surface the raw status token: "${panelText}"`).not.toMatch(/\bdownloaded\b/i);
  });

  // ---------------------------------------------------------------------
  // AC-A11Y-4: chip activation announces the result exactly once.
  // ---------------------------------------------------------------------
  test('activating the Review chip mutates the empty-announcer exactly once when it empties the grid (AC-A11Y-4)', async ({ page }) => {
    await gotoWantedWithReviewCards(page);

    // Search text that matches ONLY an active (non-review) movie, so
    // clicking Review is what causes the transition from 1 visible card to
    // 0 -- not the keystroke, and not an already-empty state.
    await page.locator('#filter-movies').fill(SEARCH_MATCHING_ONLY_AN_ACTIVE_MOVIE);
    await expect(page.locator('#movie-grid .poster-card:not([style*="display: none"])')).toHaveCount(1);

    await page.evaluate(() => {
      (window as any).__reviewA11yMutations = 0;
      const el = document.querySelector('[data-testid="filter-empty-announcer"]')!;
      new MutationObserver(() => { (window as any).__reviewA11yMutations++; })
        .observe(el, { childList: true, characterData: true, subtree: true });
    });

    await page.getByRole('button', { name: 'Review', exact: true }).click();
    await expect(page.locator('[data-testid="filter-empty-state"]')).toBeVisible({ timeout: 5000 });

    await expect
      .poll(() => page.evaluate(() => (window as any).__reviewA11yMutations))
      .toBe(1);
  });

  test('activating the Review chip mutates nothing when films awaiting review are present (AC-A11Y-4)', async ({ page }) => {
    await gotoWantedWithReviewCards(page);

    await page.evaluate(() => {
      (window as any).__reviewA11yMutations = 0;
      const el = document.querySelector('[data-testid="filter-empty-announcer"]')!;
      new MutationObserver(() => { (window as any).__reviewA11yMutations++; })
        .observe(el, { childList: true, characterData: true, subtree: true });
    });

    await page.getByRole('button', { name: 'Review', exact: true }).click();
    // Both review-gate fixtures are 'downloaded', so this must NOT empty.
    await expect(page.locator(`.poster-card[data-movie-id="${REVIEW_MOVIE_ID}"]`)).toBeVisible();

    await page.waitForTimeout(500);
    expect(await page.evaluate(() => (window as any).__reviewA11yMutations)).toBe(0);
  });

  // ---------------------------------------------------------------------
  // AC-A11Y-5: card control accessible name includes the title, and names
  // are unique across the grid. Read-only: both fixtures must still be
  // 'downloaded' for this to be non-vacuous (AC-QA-9), so this runs before
  // the destructive test at the bottom of the file.
  // ---------------------------------------------------------------------
  test('each review card’s Mark Done control has a unique, title-bearing accessible name (AC-A11Y-5)', async ({ page }) => {
    await gotoWantedWithReviewCards(page);
    await expect(page.locator(`.poster-card[data-movie-id="${REVIEW_DESTRUCTIVE_MOVIE_ID}"]`)).toBeVisible();

    const controls = page.getByRole('button', { name: /mark .* as done/i });
    const count = await controls.count();
    expect(count, 'expected one Mark Done control per review-gated card').toBe(2);

    const names = await controls.evaluateAll((els) => els.map((el) => el.getAttribute('aria-label') || el.textContent));
    expect(new Set(names).size, `accessible names must be unique across cards, got: ${JSON.stringify(names)}`).toBe(names.length);
    expect(names.some((n) => n?.includes(REVIEW_MOVIE_TITLE))).toBe(true);
    expect(names.some((n) => n?.includes(REVIEW_DESTRUCTIVE_MOVIE_TITLE))).toBe(true);
  });

  // ---------------------------------------------------------------------
  // AC-A11Y-6: keyboard reachable from the poster link, not nested inside
  // it, visible (not opacity-hidden). Read-only fixture, no click.
  // ---------------------------------------------------------------------
  test('Mark Done is reachable by Tab from the poster link, not nested in it, and visible without pointer interaction (AC-A11Y-6)', async ({ page }) => {
    const { readOnlyCard } = await gotoWantedWithReviewCards(page);

    const posterLink = readOnlyCard.locator('a').first();
    await posterLink.focus();
    await expect(posterLink).toBeFocused();

    await page.keyboard.press('Tab');
    const markDone = readOnlyCard.locator('[data-testid="review-mark-done"]');
    await expect(
      markDone,
      'Tab from the poster link must reach Mark Done next, with no pointer interaction required',
    ).toBeFocused();

    const opacity = await markDone.evaluate((el) => window.getComputedStyle(el).opacity);
    expect(opacity, 'Mark Done must be visible (opacity 1) with no hover applied').toBe('1');

    const box = await markDone.boundingBox();
    expect(box, 'Mark Done must have a bounding box').not.toBeNull();
    const viewport = page.viewportSize()!;
    expect(box!.x).toBeGreaterThanOrEqual(0);
    expect(box!.y).toBeGreaterThanOrEqual(0);
    expect(box!.x + box!.width).toBeLessThanOrEqual(viewport.width);
    expect(box!.y + box!.height).toBeLessThanOrEqual(viewport.height);

    const nestedCount = await page.locator('#movie-grid a button').count();
    expect(nestedCount, 'no interactive control may be nested inside a card’s poster <a>').toBe(0);
  });

  // ---------------------------------------------------------------------
  // AC-A11Y-7 (desktop half; the mobile half lives in review-queue.mobile.spec.ts
  // because hover does not exist on touch and must be checked under a real
  // touch-emulated project, not merely a different viewport width here).
  // ---------------------------------------------------------------------
  test('the review controls carry no hover-only opacity classes and are visible on first paint (AC-A11Y-7, desktop)', async ({ page }) => {
    const { readOnlyCard } = await gotoWantedWithReviewCards(page);

    const markDone = readOnlyCard.locator('[data-testid="review-mark-done"]');
    const markFailed = readOnlyCard.locator('[data-testid="review-mark-failed"]');

    for (const [name, control] of [['Mark Done', markDone], ['Mark Failed', markFailed]] as const) {
      const cls = (await control.getAttribute('class')) || '';
      for (const forbidden of ['opacity-0', 'group-hover:opacity-100', 'focus:opacity-100']) {
        expect(cls, `${name} must not use the hover-reveal pattern ("${forbidden}") -- it would be invisible until hovered/focused`).not.toContain(forbidden);
      }
      await expect(control).toBeVisible();
    }
  });

  // ---------------------------------------------------------------------
  // AC-A11Y-8 (desktop half, 1280px). The 393px half lives in the mobile
  // spec, run under the real mobile-chrome project.
  // ---------------------------------------------------------------------
  test('Review chip and card review control meet the 24x24 CSS px target size at 1280px (AC-A11Y-8, desktop)', async ({ page }) => {
    const { readOnlyCard } = await gotoWantedWithReviewCards(page);
    expect(page.viewportSize()!.width, 'this test measures the 1280px case of AC-A11Y-8').toBe(1280);

    const chipBox = await page.getByRole('button', { name: 'Review', exact: true }).boundingBox();
    const controlBox = await readOnlyCard.locator('[data-testid="review-mark-done"]').boundingBox();

    for (const [name, box] of [['Review chip', chipBox], ['Mark Done control', controlBox]] as const) {
      expect(box, `${name} has no bounding box`).not.toBeNull();
      expect(box!.width, `${name} width at 1280px`).toBeGreaterThanOrEqual(24);
      expect(box!.height, `${name} height at 1280px`).toBeGreaterThanOrEqual(24);
    }

    const results = await new AxeBuilder({ page })
      .include('#movie-grid')
      .withRules(['target-size'])
      .analyze();
    const detail = results.violations.flatMap((v) => v.nodes.map((n) => n.html)).join('\n');
    expect(results.violations.length, `axe target-size violations at 1280px:\n${detail}`).toBe(0);
  });

  // ---------------------------------------------------------------------
  // AC-A11Y-12: colour contrast in both themes, for the badge (over a real
  // poster fixture, both black and white), the chip, and the card control.
  // ---------------------------------------------------------------------
  for (const theme of ['light', 'dark'] as const) {
    test(`badge, chip and card-control contrast meet WCAG 1.4.3/1.4.11 in the ${theme} theme (AC-A11Y-12)`, async ({ page }) => {
      if (theme === 'dark') await setDarkTheme(page);
      const { readOnlyCard } = await gotoWantedWithReviewCards(page);
      await assertThemeIs(page, theme === 'light');

      // -- Badge over a real poster fixture --
      //
      // The seeded fixtures carry no poster (info.images.poster = []), so
      // the "downloaded / review" badge sits over the placeholder gradient
      // today, never over arbitrary poster art. AC-A11Y-12 requires the
      // measurement not depend on what's behind it, so the poster container
      // is forced to a flat colour here -- alpha-composited maths, not a
      // screenshot, so this holds regardless of backdrop-blur.
      for (const posterHex of ['#000000', '#ffffff'] as const) {
        const measured = await page.evaluate(
          ({ movieId, hex }) => {
            const card = document.querySelector(`.poster-card[data-movie-id="${movieId}"]`) as HTMLElement;
            const posterBox = card.querySelector('.aspect-\\[2\\/3\\]') as HTMLElement;
            posterBox.style.setProperty('background', hex, 'important');
            posterBox.style.setProperty('background-image', 'none', 'important');
            const badge = Array.from(card.querySelectorAll('span')).find((s) => (s.textContent || '').includes('review')) as HTMLElement;
            const s = window.getComputedStyle(badge);
            return { bg: s.backgroundColor, fg: s.color };
          },
          { movieId: REVIEW_MOVIE_ID, hex: posterHex },
        );
        const backdrop: [number, number, number] = posterHex === '#000000' ? [0, 0, 0] : [255, 255, 255];
        const ratio = contrastAgainstBackdrop(measured.bg, measured.fg, backdrop);
        expect(
          ratio,
          `"downloaded / review" badge contrast in ${theme} theme over a ${posterHex} poster: ${ratio.toFixed(2)}:1 ` +
            `(bg=${measured.bg}, fg=${measured.fg}) -- WCAG 1.4.3 requires >= 4.5:1`,
        ).toBeGreaterThanOrEqual(4.5);
      }

      // -- Review chip, selected and unselected --
      const bodyBg = await page.evaluate(() => window.getComputedStyle(document.body).backgroundColor);
      const parseTriplet = (s: string): [number, number, number] => {
        const m = s.match(/(\d+),\s*(\d+),\s*(\d+)/)!;
        return [+m[1], +m[2], +m[3]];
      };
      for (const selected of [false, true]) {
        if (selected) await page.getByRole('button', { name: 'Review', exact: true }).click();
        else await page.getByRole('button', { name: 'All', exact: true }).click();
        const chipColours = await page.evaluate(() => {
          const el = Array.from(document.querySelectorAll('button')).find((b) => b.textContent?.trim() === 'Review')!;
          const s = window.getComputedStyle(el);
          return { bg: s.backgroundColor, fg: s.color };
        });
        const ratio = contrastAgainstBackdrop(chipColours.bg, chipColours.fg, parseTriplet(bodyBg));
        expect(
          ratio,
          `Review chip (${selected ? 'selected' : 'unselected'}) contrast in ${theme} theme: ${ratio.toFixed(2)}:1 ` +
            `(bg=${chipColours.bg}, fg=${chipColours.fg})`,
        ).toBeGreaterThanOrEqual(4.5);
      }

      // -- Card control text against the card surface it actually sits on --
      const cardBg = await readOnlyCard.evaluate((el) => window.getComputedStyle(el).backgroundColor);
      for (const testid of ['review-mark-done', 'review-mark-failed']) {
        const colours = await readOnlyCard.locator(`[data-testid="${testid}"]`).evaluate((el) => {
          const s = window.getComputedStyle(el);
          return { bg: s.backgroundColor, fg: s.color };
        });
        const ratio = contrastAgainstBackdrop(colours.bg, colours.fg, parseTriplet(cardBg));
        expect(
          ratio,
          `${testid} contrast in ${theme} theme: ${ratio.toFixed(2)}:1 (bg=${colours.bg}, fg=${colours.fg}, card=${cardBg})`,
        ).toBeGreaterThanOrEqual(4.5);
      }
    });
  }

  // ---------------------------------------------------------------------
  // AC-A11Y-13: full axe scan, both themes, must FAIL (not skip) if no
  // review card is present.
  // ---------------------------------------------------------------------
  for (const theme of ['light', 'dark'] as const) {
    test(`Wanted page with a review card has zero WCAG 2.2 AA violations (${theme} theme, AC-A11Y-13)`, async ({ page }) => {
      if (theme === 'dark') await setDarkTheme(page);
      await gotoWantedWithReviewCards(page);
      await assertThemeIs(page, theme === 'light');

      const reviewCards = page.locator('#movie-grid .poster-card[data-status="downloaded"]');
      await expect(
        reviewCards.first(),
        'no review-gated card is present -- the seed did not run, or this must FAIL rather than scan nothing (AC-A11Y-13)',
      ).toBeVisible({ timeout: 10000 });

      const results = await new AxeBuilder({ page })
        .withTags(['wcag2a', 'wcag2aa', 'wcag21a', 'wcag21aa', 'wcag22aa'])
        .analyze();
      const detail = results.violations
        .flatMap((v) => v.nodes.map((n) => `${v.id}: ${n.html} -- ${n.failureSummary}`))
        .join('\n');
      expect(results.violations.length, `WCAG violations on Wanted (${theme} theme) with a review card present:\n${detail}`).toBe(0);
    });
  }

  // ---------------------------------------------------------------------
  // AC-A11Y-14 (desktop/zoom half: 640px CSS width, the 200% zoom
  // equivalent of 1280px). The 393px half lives in the mobile spec.
  // ---------------------------------------------------------------------
  test('no horizontal reflow at 640px CSS width, and the review control stays reachable once focused (AC-A11Y-14, zoom-equivalent)', async ({ page }) => {
    const { readOnlyCard } = await gotoWantedWithReviewCards(page);
    await page.setViewportSize({ width: 640, height: 800 });
    await page.waitForTimeout(200);

    const overflow = await page.evaluate(() => ({
      scrollWidth: document.documentElement.scrollWidth,
      clientWidth: document.documentElement.clientWidth,
    }));
    expect(
      overflow.scrollWidth,
      `document scrolls horizontally at 640px (${overflow.scrollWidth}px content in ${overflow.clientWidth}px) -- WCAG 1.4.10 reflow`,
    ).toBeLessThanOrEqual(overflow.clientWidth);

    const markDone = readOnlyCard.locator('[data-testid="review-mark-done"]');
    await markDone.focus();
    await expect(markDone).toBeFocused();
    const box = await markDone.boundingBox();
    expect(box).not.toBeNull();
    expect(box!.x).toBeGreaterThanOrEqual(0);
    expect(box!.x + box!.width).toBeLessThanOrEqual(640);
  });

  // =======================================================================
  // AC-A11Y-9 / AC-A11Y-10 / AC-A11Y-11 -- the core of this task.
  //
  // Two scenarios, per AC-A11Y-9's own wording ("Asserted both where the
  // acted-on card is the last remaining card in the grid and where others
  // remain"). Only ONE state-changing fixture exists per worker
  // (REVIEW_DESTRUCTIVE_MOVIE_ID, AC-QA-9), so only one of the two can be a
  // real, unmocked backend action -- the "others remain" case, since it is
  // also what proves AC-A11Y-10 (a real toast, a real persistent announcer)
  // and AC-A11Y-11 (a real htmx swap) against the genuine server response,
  // not a fixture I wrote myself. It runs LAST in this file because it
  // permanently moves REVIEW_DESTRUCTIVE_MOVIE_ID out of the review queue.
  //
  // The "last remaining card" case reuses REVIEW_MOVIE_ID with the network
  // intercepted (never reaching the real backend, so the read-only fixture
  // stays read-only) -- this is the "stub the far side" exception
  // AGENTS.md/CLAUDE.md ask to be justified rather than done by default:
  // there is no second seeded fixture to spend on it, and what is under
  // test here is the client-side focus-management logic, which does not
  // know or care whether the JSON it received came from the real backend.
  // =======================================================================

  test('Mark Done on the LAST visible card still lands focus on a named, present element -- not <body> (AC-A11Y-9, last-remaining case)', async ({ page }) => {
    const { readOnlyCard } = await gotoWantedWithReviewCards(page);

    // Never reaches the real backend for REVIEW_MOVIE_ID.
    await page.route(/media\.done/, (route) =>
      route.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify({ success: true }) }),
    );
    // The FIRST /partial/movies request is the real initial page load --
    // let it through. Only the RELOAD triggered by the click (the second
    // request) is faked, as an entirely empty grid: the exact shape
    // movie_cards.html itself renders for zero movies (fidelity matters for
    // an a11y-scanned stub, same rule mockSuggestionsCharts documents).
    let gridRequests = 0;
    await page.route(/\/partial\/movies/, (route) => {
      gridRequests++;
      if (gridRequests === 1) return route.continue();
      return route.fulfill({
        status: 200,
        contentType: 'text/html',
        body: `
          <div class="col-span-full text-center text-cp-muted py-20" role="status">
            <p class="text-xs">No movies found</p>
          </div>`,
      });
    });

    // Narrow the visible set to exactly this one card, so it really is the
    // last one left when the (faked) empty response lands.
    await page.locator('#filter-movies').fill(REVIEW_MOVIE_TITLE);
    await expect(page.locator('#movie-grid .poster-card:not([style*="display: none"])')).toHaveCount(1);

    await readOnlyCard.locator('[data-testid="review-mark-done"]').click();
    await expect(page.locator('#movie-grid .poster-card')).toHaveCount(0, { timeout: 10000 });

    const activeInfo = await page.evaluate(() => {
      const el = document.activeElement;
      return {
        isBody: el === document.body,
        isDocumentElement: el === document.documentElement,
        stillInDocument: !!el && document.contains(el),
        hasAccessibleName: !!(el && ((el as HTMLElement).getAttribute?.('aria-label') || el.textContent?.trim() || (el as HTMLElement).id)),
        tag: el?.tagName,
      };
    });
    expect(activeInfo.isBody, `focus fell to <body> with no cards left -- activeElement was ${JSON.stringify(activeInfo)}`).toBe(false);
    expect(activeInfo.isDocumentElement, `focus fell to <html> with no cards left`).toBe(false);
    expect(activeInfo.stillInDocument, 'the focused element must still be attached to the document').toBe(true);
    expect(activeInfo.hasAccessibleName, `focus landed on an unnamed element (${activeInfo.tag}) -- must be a NAMED destination`).toBe(true);
  });

  test('Mark Done on a card with others remaining: defined focus, a real Library-naming announcement, and a confined grid update (AC-A11Y-9/10/11, others-remain case, REAL backend)', async ({ page }) => {
    await gotoWantedWithReviewCards(page);
    const destructiveCard = page.locator(`.poster-card[data-movie-id="${REVIEW_DESTRUCTIVE_MOVIE_ID}"]`);
    await expect(destructiveCard).toHaveAttribute('data-status', 'downloaded');

    // AC-A11Y-10's "no full reload" half: a location.reload() would wipe
    // both this marker and window entirely.
    await page.evaluate(() => { (window as any).__reviewA11yNoReloadMarker = true; });
    // AC-A11Y-11's node-identity half: mark an UNRELATED, untouched card's
    // real DOM node before acting. If the grid update genuinely confines
    // itself to the acted-on card, this reference survives; if the whole
    // #movie-grid is replaced (today's hx-swap="innerHTML" on the whole
    // container), a fresh node exists at the same query and this reference
    // goes stale.
    await page.evaluate((otherId) => {
      (window as any).__reviewA11yOtherCardRef = document.querySelector(`.poster-card[data-movie-id="${otherId}"]`);
    }, ORDINARY_MOVIE_ID);

    await destructiveCard.locator('[data-testid="review-mark-done"]').click();

    // Real backend round trip: the movie leaves status=active,downloaded.
    await expect(page.locator(`.poster-card[data-movie-id="${REVIEW_DESTRUCTIVE_MOVIE_ID}"]`)).toHaveCount(0, { timeout: 10000 });

    // --- AC-A11Y-9 ---
    const activeInfo = await page.evaluate(() => {
      const el = document.activeElement;
      return {
        isBody: el === document.body,
        isDocumentElement: el === document.documentElement,
        stillInDocument: !!el && document.contains(el),
        hasAccessibleName: !!(el && ((el as HTMLElement).getAttribute?.('aria-label') || el.textContent?.trim() || (el as HTMLElement).id)),
      };
    });
    expect(activeInfo.isBody, `focus fell to <body> after the card was removed -- ${JSON.stringify(activeInfo)}`).toBe(false);
    expect(activeInfo.isDocumentElement).toBe(false);
    expect(activeInfo.stillInDocument).toBe(true);
    expect(activeInfo.hasAccessibleName).toBe(true);

    // --- AC-A11Y-10 ---
    const politeAnnouncer = page.locator('[data-testid="toast-announcer-polite"]');
    await expect
      .poll(async () => (await politeAnnouncer.textContent()) || '', { timeout: 2000 })
      .toMatch(/library/i);
    expect(
      await page.evaluate(() => (window as any).__reviewA11yNoReloadMarker),
      'a location.reload() would have wiped this marker -- the outcome must be spoken through the SURVIVING announcer, not a reload',
    ).toBe(true);
    await page.waitForTimeout(1000);
    await expect(politeAnnouncer, 'the announcer must still be attached 1s after the outcome was announced').toBeAttached();

    // --- AC-A11Y-11 ---
    const grid = page.locator('#movie-grid');
    const noAriaLive = (await grid.getAttribute('aria-live')) === null;
    const otherCardStillSameNode = await page.evaluate((otherId) => {
      const now = document.querySelector(`.poster-card[data-movie-id="${otherId}"]`);
      return now === (window as any).__reviewA11yOtherCardRef;
    }, ORDINARY_MOVIE_ID);
    expect(
      noAriaLive || otherCardStillSameNode,
      `either #movie-grid must carry no aria-live (it does: ${!noAriaLive}), or the untouched card's DOM node must ` +
        `survive the update unchanged (it did not: node identity preserved=${otherCardStillSameNode}) -- a full-grid ` +
        `re-render under aria-live="polite" re-announces every unrelated card`,
    ).toBe(true);
  });
});
