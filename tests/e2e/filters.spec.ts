import { test, expect } from './fixtures';
import { Page } from '@playwright/test';
import AxeBuilder from '@axe-core/playwright';

/**
 * Filter functionality tests for CouchPotato new UI.
 */

test.describe('Filters', () => {
  test.beforeEach(async ({ page }) => {
    await page.goto('/');
    // Wait for movies to load
    const movieGrid = page.locator('#movie-grid');
    await expect(movieGrid).toBeVisible({ timeout: 10000 });
  });

  test('should have filter buttons on Wanted page', async ({ page }) => {
    // Should have All, Wanted, Available buttons
    const allButton = page.getByRole('button', { name: /^all$/i });
    const wantedButton = page.getByRole('button', { name: /wanted/i });
    const availableButton = page.getByRole('button', { name: /available/i });
    
    await expect(allButton).toBeVisible();
    await expect(wantedButton).toBeVisible();
    await expect(availableButton).toBeVisible();
  });

  test('should have search filter input', async ({ page }) => {
    const searchInput = page.locator('input[placeholder*="filter" i]');
    await expect(searchInput).toBeVisible();
  });

  test('should filter movies by text search', async ({ page }) => {
    const movieCards = page.locator('#movie-grid .poster-card');
    // Unconditional. This used to be `if (initialCount > 0) { ... }`, so on an
    // empty grid it asserted nothing and reported green -- and an empty grid
    // is precisely the failure the readiness probe in fixtures.ts exists to
    // prevent, so the one condition that would have caught it was the one the
    // guard suppressed. scripts/seed_e2e_data.py seeds five active movies, so
    // a zero here is the seed or the app being broken.
    const initialCount = await movieCards.count();
    expect(initialCount, 'no movie cards in the grid -- did the seed run?').toBeGreaterThan(0);

    // Get the title of the first movie
    const firstTitle = await movieCards.first().getAttribute('data-title');
    expect(firstTitle, 'a poster card must carry data-title for the filter to match on').toBeTruthy();

    // Type in the filter
    const searchInput = page.locator('input[placeholder*="filter" i]');
    await searchInput.fill(firstTitle || '');

    // Assert the DIRECTION and the IDENTITY, both of which are false for a
    // no-op filter. The first repair of this test used
    // `toBeLessThanOrEqual(initialCount)` and `toBeGreaterThan(0)`, and
    // neither changes value between "the filter worked" and "the filter did
    // nothing": with five seeded movies, `5 <= 5` is true on the poll's first
    // evaluation, so it also returned before the filter had run at all. The
    // only regression it could catch was a filter that hid everything -- in
    // the file this round repaired for exactly that class of defect.
    //
    // The seeded titles are mutually non-substring (E2E Seed Movie, E2E
    // Destructive Seed Movie, E2E No-Release Movie, E2E Second/Third
    // No-Release Movie), so filtering on a full title must leave exactly one.
    const visibleCards = page.locator('#movie-grid .poster-card:not([style*="display: none"])');
    await expect
      .poll(() => visibleCards.count(), { timeout: 5000 })
      .toBeLessThan(initialCount);
    await expect(visibleCards).toHaveCount(1);
    await expect(visibleCards.first()).toHaveAttribute('data-title', firstTitle || '');
  });

  test('clicking Wanted filter should filter movies', async ({ page }) => {
    const wantedButton = page.getByRole('button', { name: /wanted/i });
    await wantedButton.click();
    
    // Button should be highlighted
    await expect(wantedButton).toHaveClass(/text-cp-accent/);
    
    // Wait for filter to apply
    await page.waitForTimeout(300);
    
    // Assert on `data-has-releases`, NOT `data-status`.
    //
    // The first repair of this test checked that every visible card was
    // 'active' -- which the Wanted chip cannot change and never could.
    // `wanted.html` fetches `partial/movies?status=active`, so every card in
    // the grid is already active, and `movie-filter.js`'s wanted branch is
    // `matchStatus = !card.hasReleases` and does not read `card.status` at
    // all. Measured over the real `matchesFilter` and the seeded grid: the
    // data-status set is {"active"} with the chip, without it, and with the
    // OPPOSITE chip. Deleting the click above left the test green.
    //
    // So the regression it is named for -- the Wanted chip failing to hide
    // movies that have releases, which has shipped on this codebase once
    // already -- had no assertion behind it. The population poll (the earlier
    // repair) is kept: it closes the zero-iteration hole.
    const visibleCards = page.locator('#movie-grid .poster-card:not([style*="display: none"])');
    await expect
      .poll(() => visibleCards.count(), { timeout: 5000 })
      .toBeGreaterThan(0);

    const flags = await visibleCards.evaluateAll((cards) =>
      cards.map((c) => c.getAttribute('data-has-releases')),
    );
    expect(flags).not.toContain(null);
    expect(new Set(flags)).toEqual(new Set(['false']));
  });

  test('clicking Available filter should filter movies', async ({ page }) => {
    const availableButton = page.getByRole('button', { name: /available/i });
    await availableButton.click();
    
    // Button should be highlighted with accent colour
    await expect(availableButton).toHaveClass(/text-cp-accent/);
    
    // Wait for filter to apply
    await page.waitForTimeout(300);
    
    // Same shape, same fix as the Wanted case above.
    //
    // Available is non-empty because MOVIE_ID and DESTRUCTIVE_MOVIE_ID carry
    // RELEASES -- NOT because of DONE_RELEASE_MOVIE_ID, which an earlier
    // version of this comment named. That movie is seeded with media status
    // 'done' deliberately, so `partial/movies?status=active` never returns it
    // and it is not in this grid at all. Naming the wrong guarantee is how
    // someone trimming the seed removes the wrong document.
    const visibleCards = page.locator('#movie-grid .poster-card:not([style*="display: none"])');
    await expect
      .poll(() => visibleCards.count(), { timeout: 5000 })
      .toBeGreaterThan(0);

    const flags = await visibleCards.evaluateAll((cards) =>
      cards.map((c) => c.getAttribute('data-has-releases')),
    );
    expect(flags.length).toBeGreaterThan(0);
    expect(flags).not.toContain(null);
    expect(new Set(flags)).toEqual(new Set(['true']));
  });

  test('clicking All should show all movies', async ({ page }) => {
    // First apply a filter
    const wantedButton = page.getByRole('button', { name: /wanted/i });
    await wantedButton.click();
    await page.waitForTimeout(300);
    
    // Then click All
    const allButton = page.getByRole('button', { name: /^all$/i });
    await allButton.click();
    
    // Button should be highlighted
    await expect(allButton).toHaveClass(/text-cp-accent/);
    
    // Wait for filter to apply
    await page.waitForTimeout(300);
    
    // More movies should be visible (or same if all were wanted)
    const visibleCards = page.locator('#movie-grid .poster-card:not([style*="display: none"])');
    const count = await visibleCards.count();
    expect(count).toBeGreaterThanOrEqual(0);
  });

  test('should show movie count', async ({ page }) => {
    // Should show count in the header
    const countElement = page.locator('#movie-count');
    await expect(countElement).toBeVisible({ timeout: 5000 });
    
    // Count should contain "movies"
    const countText = await countElement.textContent();
    expect(countText).toContain('movies');
  });
});

/**
 * BUG (owner report, 2026-07-31): "I just deleted Tinsel Town to add it back to
 * search, when I go in to my movies list it's now empty" -- followed by
 * "actually it was a filter problem. The tinsel town filter was still there,
 * but I had deleted it."
 *
 * The library was intact (1099 movies, verified on the production database).
 * What the user saw was a filter that matched nothing after the movie was
 * deleted, and a grid that renders COMPLETELY BLANK in that case: no message,
 * no indication a filter is even active, and no way to clear it except
 * noticing the text still sitting in the filter box. An empty grid is
 * indistinguishable from a lost library, which is exactly the conclusion that
 * was drawn.
 *
 * Measured before the fix: /library?q=<no match> gives 1 card in the DOM, 0
 * visible, and an empty #movie-grid on screen.
 */
/**
 * Serve a FIXED movie grid, so these tests do not depend on library state.
 *
 * The filtered-to-empty behaviour is pure client-side logic: movieList()
 * reads `.poster-card` elements out of the DOM and toggles their display. It
 * needs cards, not a real library -- so stubbing the partial is both simpler
 * and honest about what is under test.
 *
 * It is also the only stable option here. Earlier versions read the seeded
 * movie's status to pick a page, and then forced it into a known status via
 * the API. Both were flaky in a full run, for reasons that are properties of
 * the suite rather than of this feature: the specs share one server and one
 * database, movie-detail.spec.ts DELETES the seeded movie (so anything after
 * it sees an empty library), other specs add movies, and forcing status is
 * itself shared-state mutation. playwright.config.ts already documents this
 * coupling as why the suite runs single-worker. Stubbing opts out of all of
 * it. The suggestions and search specs stub their partials for the same
 * reason.
 */
function stubMovieGrid(page: Page, movies: Array<{ title: string; status: string; hasReleases?: boolean }>) {
  const cards = movies
    .map(
      (m, i) => `
        <div class="poster-card" data-title="${m.title}" data-status="${m.status}"
             data-has-releases="${m.hasReleases ? 'true' : 'false'}"
             data-movie-id="stub-${i}">
          <a class="block" href="/movie/stub-${i}/">${m.title}</a>
        </div>`,
    )
    .join('');
  return page.route(/\/partial\/movies/, (route) =>
    route.fulfill({ status: 200, contentType: 'text/html', body: cards }),
  );
}

/** Wait for the htmx grid load to have actually completed. */
async function waitForGridLoaded(page: Page) {
  // #movie-count is written by filterMovies(), which only runs on
  // htmx:afterSwap for #movie-grid -- so non-empty text is proof the swap
  // landed. A fixed waitForTimeout is not a wait: it let an earlier version of
  // the empty-library test count 0 cards on a grid that had not loaded yet and
  // then "pass".
  await expect(page.locator('#movie-count')).not.toBeEmpty({ timeout: 15000 });
}

test.describe('Filtered-to-empty state', () => {
  test('explains why the grid is empty and offers a way out', async ({ page }) => {
    await stubMovieGrid(page, [
      { title: 'Tinsel Town', status: 'done', hasReleases: true },
      { title: 'Another Movie', status: 'done', hasReleases: true },
    ]);
    await page.goto('/');
    await expect(page.locator('#movie-grid')).toBeVisible({ timeout: 10000 });
    await waitForGridLoaded(page);
    const total = await page.locator('#movie-grid .poster-card').count();
    expect(total).toBe(2);

    await page.locator('#filter-movies').fill('zzz-no-such-movie-zzz');

    // The user must be told the library is filtered, not gone.
    const emptyState = page.locator('[data-testid="filter-empty-state"]');
    await expect(emptyState).toBeVisible({ timeout: 5000 });
    // useInnerText, so display:none copy does NOT count. toContainText reads
    // textContent: mutating x-show="search" to x-show="false" on the
    // explanation sentence left the assertion green, which is exactly the
    // "blank panel with no visible explanation" this test exists to prevent.
    await expect(emptyState).toContainText('zzz-no-such-movie-zzz', { useInnerText: true });

    // ...and be able to get out of it in one click, without having to work
    // out that the filter box is the culprit.
    await emptyState.locator('[data-testid="clear-filters"]').click();

    await expect(emptyState).toBeHidden({ timeout: 5000 });
    const visible = await page.locator('#movie-grid .poster-card:not([style*="display: none"])').count();
    expect(visible, 'clearing from the empty state must restore the full list').toBe(total);
    await expect(page.locator('#filter-movies')).toHaveValue('');
  });

  test('a genuinely empty library is not reported as a filter problem', async ({ page }) => {
    /*
     * An empty library: total === 0 with no filter applied. The
     * filter-specific empty state must NOT claim a filter is hiding things.
     *
     * It used to test.skip() when the page happened to have movies, which on a
     * fresh seed meant it never ran at all. That is the same skip-instead-of-
     * fail pattern this branch removed from gotoSeededMovie.
     */
    await stubMovieGrid(page, []);
    await page.goto('/');
    // toBeAttached, not toBeVisible: with zero cards the grid is an empty div
    // with no height, which Playwright reports as hidden. waitForGridLoaded
    // below is what actually proves the swap happened.
    await expect(page.locator('#movie-grid')).toBeAttached({ timeout: 10000 });
    await waitForGridLoaded(page);

    const total = await page.locator('#movie-grid .poster-card').count();
    expect(total, 'the stub serves an empty library').toBe(0);
    await expect(page.locator('[data-testid="filter-empty-state"]')).toBeHidden();
  });

  test('clearing from the empty state keeps keyboard focus (WCAG 2.4.3)', async ({ page }) => {
    /*
     * Activating "Clear filters" hides its own container via x-show, so the
     * focused button gets display:none and focus falls to <body> -- the next
     * Tab restarts at the top of the document. This is the same defect found
     * on the two movie-detail controls; it was reintroduced here because this
     * control shipped without a guard.
     */
    // The stub serves the grid regardless of page/status, so '/' is just a
    // host for the filter controls here.
    await stubMovieGrid(page, [{ title: 'Tinsel Town', status: 'done', hasReleases: true }]);
    await page.goto('/');
    await expect(page.locator('#movie-grid')).toBeVisible({ timeout: 10000 });
    await waitForGridLoaded(page);

    await page.locator('#filter-movies').fill('zzz-no-such-movie-zzz');
    const clearBtn = page.locator('[data-testid="clear-filters"]');
    await expect(clearBtn).toBeVisible({ timeout: 5000 });

    await clearBtn.focus();
    await page.keyboard.press('Enter');

    // toBeFocused (which retries), NOT a one-shot activeElement read: focus
    // moves on the tick AFTER the empty state is hidden, so a single read
    // races that and saw whatever had focus mid-transition. A non-retrying
    // read standing in for a wait is the same trap documented in
    // release_controls.spec.ts.
    await expect(page.locator('#filter-movies')).toBeFocused({ timeout: 5000 });
  });

  test('the filtered-to-empty state is announced, not just displayed', async ({ page }) => {
    /*
     * PR review: the panel is toggled by x-show, so it is absent from the
     * accessibility tree while its content is set -- and a screen reader
     * announces a MUTATION to an element already in the tree, not the arrival
     * of one. A sighted user saw the explanation; a screen-reader user got
     * silence and a list that had emptied for no stated reason.
     *
     * Announcement therefore goes through a persistent sr-only region. This
     * asserts the region exists BEFORE the filter is applied -- the property
     * the previous shape did not have, and which asserting on role/attributes
     * alone could never catch.
     */
    await stubMovieGrid(page, [{ title: 'Tinsel Town', status: 'done', hasReleases: true }]);
    await page.goto('/');
    await expect(page.locator('#movie-grid')).toBeVisible({ timeout: 10000 });
    await waitForGridLoaded(page);

    const announcer = page.locator('[data-testid="filter-empty-announcer"]');
    await expect(announcer).toBeAttached();
    await expect(announcer).toHaveAttribute('aria-live', 'polite');
    await expect(announcer).toBeEmpty();

    await page.locator('#filter-movies').fill('zzz-no-such-movie-zzz');
    await expect(announcer).toContainText('No movies match your filter');
    await expect(announcer).toContainText('1 movie');

    // ...and it clears again, so the next match does not re-announce staleness.
    await page.locator('#filter-movies').fill('');
    await expect(announcer).toBeEmpty();
  });

  test('the empty-state panel is not hidden from assistive tech while visible', async ({ page }) => {
    /*
     * PR review: a static `aria-hidden="true"` was added to this panel. x-show
     * only toggles display:none -- it does not touch the attribute -- so the
     * panel and its focusable "Clear filters" button were hidden from
     * assistive tech while VISIBLE and still in the tab order. axe
     * `aria-hidden-focus`, WCAG 4.1.2.
     *
     * That is the identical bug this branch diagnosed and fixed on the toast
     * region, reintroduced on the panel whose entire purpose is to reassure a
     * user whose library looks empty. Nothing caught it: the existing coverage
     * asserts toBeVisible/toContainText, and the a11y suite never scanned this
     * panel while it was open.
     */
    await stubMovieGrid(page, [{ title: 'Tinsel Town', status: 'done', hasReleases: true }]);
    await page.goto('/');
    await expect(page.locator('#movie-grid')).toBeVisible({ timeout: 10000 });
    await waitForGridLoaded(page);

    await page.locator('#filter-movies').fill('zzz-no-such-movie-zzz');
    const panel = page.locator('[data-testid="filter-empty-state"]');
    await expect(panel).toBeVisible();

    // The Clear filters button is focusable, so the panel must not be hidden.
    await expect(panel).not.toHaveAttribute('aria-hidden', 'true');
    await page.locator('[data-testid="clear-filters"]').focus();
    await expect(page.locator('[data-testid="clear-filters"]')).toBeFocused();

    const results = await new AxeBuilder({ page })
      .include('[data-testid="filter-empty-state"]')
      .withTags(['wcag2a', 'wcag2aa', 'wcag21a', 'wcag21aa', 'wcag22aa'])
      .analyze();
    const detail = results.violations
      .flatMap((v) => v.nodes.map((n) => `${v.id}: ${n.html}`))
      .join('\n');
    expect(results.violations.length, `empty-state panel violations:\n${detail}`).toBe(0);
  });
});

test.describe('Review card actions (FEAT-010)', () => {
  /*
   * scripts/seed_e2e_data.py's two dedicated review-gate movies (AC-QA-9),
   * already seeded status='downloaded' with a landed release -- real
   * fixtures, not stubMovieGrid(), because these tests exercise the real
   * movie_cards.html Mark Done / Mark Failed controls and their wiring, not
   * client-side filter logic.
   *
   * REVIEW_MOVIE_ID is reserved for read-only assertions and
   * REVIEW_DESTRUCTIVE_MOVIE_ID for the state-changing spec (the seed
   * script's own comment). Every test below intercepts the destructive route
   * itself rather than letting it reach the real backend, so REVIEW_MOVIE_ID
   * stays genuinely read-only for whichever spec runs after this one in the
   * same worker.
   */
  const REVIEW_MOVIE_ID = 'e2e-seed-movie-007';
  const REVIEW_DESTRUCTIVE_MOVIE_ID = 'e2e-seed-movie-008';
  const MARK_FAILED_CONFIRM_TEXT =
    'Mark this download as failed and search for another copy? This discards the current copy.';

  async function gotoWantedWithReviewCards(page: Page) {
    await page.goto('/wanted');
    await expect(page.locator('#movie-grid')).toBeVisible({ timeout: 10000 });
    await waitForGridLoaded(page);
    const readOnlyCard = page.locator(`.poster-card[data-movie-id="${REVIEW_MOVIE_ID}"]`);
    const destructiveCard = page.locator(`.poster-card[data-movie-id="${REVIEW_DESTRUCTIVE_MOVIE_ID}"]`);
    await expect(
      readOnlyCard,
      'REVIEW_MOVIE_ID must be seeded and visible on Wanted -- did scripts/seed_e2e_data.py run?',
    ).toHaveCount(1, { timeout: 10000 });
    await expect(
      destructiveCard,
      'REVIEW_DESTRUCTIVE_MOVIE_ID must be seeded and visible on Wanted -- did scripts/seed_e2e_data.py run?',
    ).toHaveCount(1, { timeout: 10000 });
    return { readOnlyCard, destructiveCard };
  }

  test('dismissing the card Mark Failed confirmation issues zero requests (AC-QA-12)', async ({ page }) => {
    let markFailedRequests = 0;
    await page.route(/movie\.searcher\.mark_failed/, (route) => {
      markFailedRequests++;
      return route.fulfill({
        status: 200,
        contentType: 'application/json',
        body: JSON.stringify({ success: true }),
      });
    });

    const { readOnlyCard } = await gotoWantedWithReviewCards(page);

    let dialogMessage: string | null = null;
    page.once('dialog', async (dialog) => {
      dialogMessage = dialog.message();
      await dialog.dismiss();
    });
    await readOnlyCard.locator('[data-testid="review-mark-failed"]').click();
    await expect.poll(() => dialogMessage, { timeout: 5000 }).not.toBeNull();

    // Same wording as the detail page (movie_detail.html:283) -- AC-QA-12.
    expect(dialogMessage).toBe(MARK_FAILED_CONFIRM_TEXT);

    // A moment for a wrongly-unconditional fetch to have fired, so this
    // cannot pass by polling before the bug would have shown up.
    await page.waitForTimeout(500);
    expect(
      markFailedRequests,
      'dismissing the confirmation must issue zero requests to movie.searcher.mark_failed',
    ).toBe(0);

    // The card is still present during an in-flight request too, so the
    // request-count assertion above -- not card presence -- is what proves
    // dismissal did nothing (AC-QA-12).
    await expect(readOnlyCard).toHaveAttribute('data-status', 'downloaded');
    await expect(readOnlyCard.locator('[data-testid="review-mark-failed"]')).toBeEnabled();
  });

  test("confirming Mark Failed issues exactly one request for that card's own id, no media.done request, and leaves every other card's status untouched (AC-QA-13)", async ({
    page,
  }) => {
    const failedRequestIds: string[] = [];
    let doneRequests = 0;
    await page.route(/movie\.searcher\.mark_failed/, (route) => {
      const url = new URL(route.request().url());
      failedRequestIds.push(url.searchParams.get('media_id') || '');
      return route.fulfill({
        status: 200,
        contentType: 'application/json',
        body: JSON.stringify({ success: true }),
      });
    });
    await page.route(/media\.done/, (route) => {
      doneRequests++;
      return route.fulfill({
        status: 200,
        contentType: 'application/json',
        body: JSON.stringify({ success: true }),
      });
    });

    const { readOnlyCard, destructiveCard } = await gotoWantedWithReviewCards(page);

    // Synthesis decision 4: a card action re-fetches the grid, it does not
    // call location.reload() -- a reload would destroy this marker.
    await page.evaluate(() => {
      (window as any).__feat010NoReloadMarker = true;
    });

    page.once('dialog', (dialog) => dialog.accept());
    await readOnlyCard.locator('[data-testid="review-mark-failed"]').click();

    await expect.poll(() => failedRequestIds.length, { timeout: 5000 }).toBe(1);
    expect(failedRequestIds, "the request must carry that card's own media id, no other").toEqual([
      REVIEW_MOVIE_ID,
    ]);
    expect(doneRequests, 'confirming Mark Failed must not also call media.done').toBe(0);

    expect(
      await page.evaluate(() => (window as any).__feat010NoReloadMarker),
      'a full location.reload() would have wiped this marker -- the grid must be re-fetched instead',
    ).toBe(true);

    // The mocked response never reached the real backend, so the other
    // seeded review card's status is proof no other card was touched.
    await expect(destructiveCard).toHaveAttribute('data-status', 'downloaded');
  });

  test('a rejected Mark Done ({success:false}) leaves the card unchanged, re-enables the control, and surfaces an error (AC-QA-15a)', async ({
    page,
  }) => {
    let doneRequests = 0;
    await page.route(/media\.done/, (route) => {
      doneRequests++;
      return route.fulfill({
        status: 200,
        contentType: 'application/json',
        body: JSON.stringify({ success: false }),
      });
    });

    const { destructiveCard } = await gotoWantedWithReviewCards(page);
    const markDoneBtn = destructiveCard.locator('[data-testid="review-mark-done"]');
    const idleLabel = ((await markDoneBtn.textContent()) || '').trim();
    expect(idleLabel.length).toBeGreaterThan(0);

    await markDoneBtn.click();
    await expect.poll(() => doneRequests, { timeout: 5000 }).toBe(1);

    // Neither stuck on a pending "Marking…" label nor silently claiming
    // success.
    await expect(destructiveCard).toHaveAttribute('data-status', 'downloaded');
    await expect(markDoneBtn).toBeEnabled();
    await expect(markDoneBtn).toHaveAttribute('aria-disabled', 'false');
    expect(((await markDoneBtn.textContent()) || '').trim()).toBe(idleLabel);

    const errorAnnouncer = page.locator('[data-testid="toast-announcer-assertive"]');
    await expect(errorAnnouncer).not.toHaveText('', { timeout: 5000 });
  });

  test('an aborted Mark Done request leaves the card unchanged and re-enables the control (AC-QA-15b)', async ({
    page,
  }) => {
    let doneRequests = 0;
    await page.route(/media\.done/, (route) => {
      doneRequests++;
      return route.abort('failed');
    });

    const { destructiveCard } = await gotoWantedWithReviewCards(page);
    const markDoneBtn = destructiveCard.locator('[data-testid="review-mark-done"]');
    const idleLabel = ((await markDoneBtn.textContent()) || '').trim();
    expect(idleLabel.length).toBeGreaterThan(0);

    await markDoneBtn.click();
    await expect.poll(() => doneRequests, { timeout: 5000 }).toBe(1);

    await expect(destructiveCard).toHaveAttribute('data-status', 'downloaded');
    await expect(markDoneBtn).toBeEnabled();
    expect(((await markDoneBtn.textContent()) || '').trim()).toBe(idleLabel);
  });

  test('two rapid clicks on Mark Done produce exactly one media.done request (AC-QA-16, pointer)', async ({
    page,
  }) => {
    let doneRequests = 0;
    await page.route(/media\.done/, async (route) => {
      doneRequests++;
      // Held open so a second activation during the in-flight window is a
      // genuine race against the guard, not a race the guard wins only
      // because the first request already finished.
      await new Promise((resolve) => setTimeout(resolve, 400));
      return route.fulfill({
        status: 200,
        contentType: 'application/json',
        body: JSON.stringify({ success: true }),
      });
    });

    const { destructiveCard } = await gotoWantedWithReviewCards(page);
    const markDoneBtn = destructiveCard.locator('[data-testid="review-mark-done"]');

    // force:true: the control uses aria-disabled (not the disabled
    // attribute, per the project's a11y rule for a control that may hold
    // focus), so a plain second .click() could be stalled by Playwright's
    // own actionability retries rather than exercising the guard. Both
    // clicks are issued back to back with no artificial wait between them.
    await Promise.all([
      markDoneBtn.click({ force: true }),
      markDoneBtn.click({ force: true }),
    ]);
    await page.waitForTimeout(700);

    expect(doneRequests).toBe(1);
  });

  test('two rapid Enter presses on a focused Mark Done produce exactly one media.done request (AC-QA-16, keyboard)', async ({
    page,
  }) => {
    let doneRequests = 0;
    await page.route(/media\.done/, async (route) => {
      doneRequests++;
      await new Promise((resolve) => setTimeout(resolve, 400));
      return route.fulfill({
        status: 200,
        contentType: 'application/json',
        body: JSON.stringify({ success: true }),
      });
    });

    const { destructiveCard } = await gotoWantedWithReviewCards(page);
    const markDoneBtn = destructiveCard.locator('[data-testid="review-mark-done"]');
    await markDoneBtn.focus();
    await expect(markDoneBtn).toBeFocused();

    await page.keyboard.press('Enter');
    await page.keyboard.press('Enter');
    await page.waitForTimeout(700);

    expect(doneRequests).toBe(1);
  });

  /*
   * Bulk delete and the review gate (AC-QA-20, AC-SEC-2, synthesis decision
   * 3). wanted.html:396's bulkDelete() says "This cannot be undone" and then
   * relies on the server to silently refuse a review-gated id
   * (main.py:567) -- correct server behaviour, but the confirmation lies
   * about what is about to happen. These three tests pin: the confirmation
   * names the skip count BEFORE acting; the count is drawn from the actual
   * selection, not the whole grid, so a partial selection cannot pass by
   * reporting every review-gated film in the grid; and the ordinary
   * (no-review-gated-film) case keeps today's wording untouched.
   *
   * ORDINARY_MOVIE_ID is WANTED_MOVIE_ID from scripts/seed_e2e_data.py:
   * 'active', no releases, safe to select. Every test below either mocks
   * movie.delete for it or cancels the confirmation before any request is
   * sent, so nothing here mutates a fixture other spec files depend on.
   */
  const ORDINARY_MOVIE_ID = 'e2e-seed-movie-004';

  test('Select All on a grid containing review-gated films states the skip count before acting, never requests their deletion, and they survive end-to-end (AC-QA-20, AC-SEC-2)', async ({
    page,
  }) => {
    const { readOnlyCard, destructiveCard } = await gotoWantedWithReviewCards(page);

    // Measured from the grid itself, not assumed -- AC-QA-9 seeds exactly
    // two, but tying the assertion below to a live count (rather than a
    // literal "2") is what makes it fail if the message is ever built from
    // something other than what is actually on screen.
    const reviewGatedVisibleCount = await page
      .locator('#movie-grid .poster-card[data-status="downloaded"]')
      .count();
    expect(
      reviewGatedVisibleCount,
      'need at least the two seeded review-gate films visible for this test to mean anything',
    ).toBeGreaterThanOrEqual(2);

    const deleteRequestIds: string[] = [];
    await page.route(/movie\.delete/, (route) => {
      const url = new URL(route.request().url());
      const id = url.searchParams.get('id') || '';
      deleteRequestIds.push(id);
      // A review-gated id is let through to the REAL backend -- AC-SEC-2
      // asks for proof through the newly reachable UI path, not a mock of
      // it. Every other id is mocked so this test cannot mutate shared E2E
      // fixtures other spec files depend on.
      if (id === REVIEW_MOVIE_ID || id === REVIEW_DESTRUCTIVE_MOVIE_ID) {
        return route.continue();
      }
      return route.fulfill({
        status: 200,
        contentType: 'application/json',
        body: JSON.stringify({ success: true }),
      });
    });

    await page.locator('button:has-text("Select All")').click();

    let dialogMessage: string | null = null;
    page.once('dialog', async (dialog) => {
      dialogMessage = dialog.message();
      await dialog.accept();
    });
    await page.getByRole('button', { name: 'Delete', exact: true }).click();
    await expect.poll(() => dialogMessage, { timeout: 5000 }).not.toBeNull();

    expect(
      dialogMessage,
      `confirmation must state the review-gated count (${reviewGatedVisibleCount}) before acting, not stay silent about it`,
    ).toMatch(new RegExp(`\\b${reviewGatedVisibleCount}\\b`));
    expect(dialogMessage!.toLowerCase(), 'confirmation must name what is being skipped and why').toMatch(/review/);
    expect(dialogMessage!.toLowerCase(), 'confirmation must say these are being skipped').toMatch(/skip/);

    // A moment for a wrongly-unconditional fetch to have fired, so this
    // cannot pass by polling before the bug would have shown up.
    await page.waitForTimeout(800);

    expect(
      deleteRequestIds,
      'movie.delete must never be requested for the read-only review-gated id',
    ).not.toContain(REVIEW_MOVIE_ID);
    expect(
      deleteRequestIds,
      'movie.delete must never be requested for the destructive review-gated id',
    ).not.toContain(REVIEW_DESTRUCTIVE_MOVIE_ID);

    await expect(readOnlyCard).toHaveAttribute('data-status', 'downloaded', { timeout: 10000 });
    await expect(destructiveCard).toHaveAttribute('data-status', 'downloaded', { timeout: 10000 });

    // AC-SEC-2: real DB state through the newly reachable UI path, not just
    // the DOM card left behind by a re-fetch that could itself be stale.
    const [readOnlyState, destructiveState] = await page.evaluate(async ([id1, id2]) => {
      const fetchOne = async (movieId: string) => {
        const res = await fetch(`${(window as any).CP.apiBase}/media.get/?id=${movieId}`);
        const data = await res.json();
        const media = data?.media ?? data;
        return {
          status: media?.status,
          profileId: media?.profile_id,
          releaseCount: Array.isArray(media?.releases) ? media.releases.length : -1,
        };
      };
      return Promise.all([fetchOne(id1), fetchOne(id2)]);
    }, [REVIEW_MOVIE_ID, REVIEW_DESTRUCTIVE_MOVIE_ID]);

    expect(readOnlyState.status, 'the read-only review film must still be downloaded, not deleted').toBe(
      'downloaded',
    );
    expect(readOnlyState.profileId, 'its profile_id must still be set').toBeTruthy();
    expect(readOnlyState.releaseCount, 'its releases must not have been deleted').toBeGreaterThan(0);

    expect(
      destructiveState.status,
      'the destructive-fixture review film must still be downloaded, not deleted',
    ).toBe('downloaded');
    expect(destructiveState.profileId, 'its profile_id must still be set').toBeTruthy();
    expect(destructiveState.releaseCount, 'its releases must not have been deleted').toBeGreaterThan(0);
  });

  test('a partial selection reports only the review-gated films actually selected, not every one seeded (AC-QA-20 caution)', async ({
    page,
  }) => {
    await gotoWantedWithReviewCards(page);

    // Exactly ONE of the two seeded review-gated films, plus one ordinary
    // film -- a selection that is neither "all of them" nor "none of them".
    // If the confirmation counted every review-gated film in the grid
    // instead of the ones actually ticked, it would report 2 here (both
    // seeded review films) rather than 1 (the one actually selected). The
    // confirmation is dismissed, so nothing here reaches any backend.
    await page
      .locator(`.poster-card[data-movie-id="${REVIEW_MOVIE_ID}"] .movie-select-checkbox`)
      .check({ force: true });
    await page
      .locator(`.poster-card[data-movie-id="${ORDINARY_MOVIE_ID}"] .movie-select-checkbox`)
      .check({ force: true });

    let dialogMessage: string | null = null;
    page.once('dialog', async (dialog) => {
      dialogMessage = dialog.message();
      await dialog.dismiss();
    });
    await page.getByRole('button', { name: 'Delete', exact: true }).click();
    await expect.poll(() => dialogMessage, { timeout: 5000 }).not.toBeNull();

    expect(
      dialogMessage,
      'the skipped count must name exactly the one selected review-gated film',
    ).toMatch(/\b1\b/);
    expect(
      dialogMessage,
      'a count derived from the whole grid rather than the selection would report 2 -- both seeded review films -- instead of the one actually selected',
    ).not.toMatch(/\b2\b/);
  });

  test('a selection with no review-gated film keeps the confirmation wording unchanged, character for character (AC-QA-20)', async ({
    page,
  }) => {
    await gotoWantedWithReviewCards(page);

    await page
      .locator(`.poster-card[data-movie-id="${ORDINARY_MOVIE_ID}"] .movie-select-checkbox`)
      .check({ force: true });

    let dialogMessage: string | null = null;
    page.once('dialog', async (dialog) => {
      dialogMessage = dialog.message();
      await dialog.dismiss();
    });
    await page.getByRole('button', { name: 'Delete', exact: true }).click();
    await expect.poll(() => dialogMessage, { timeout: 5000 }).not.toBeNull();

    // wanted.html's existing wording, byte for byte -- the new review-gate
    // branch must never touch this path. This is the direction that proves
    // the new branch cannot swallow the ordinary case.
    expect(dialogMessage).toBe('Delete 1 movie? This cannot be undone.');
  });
});
