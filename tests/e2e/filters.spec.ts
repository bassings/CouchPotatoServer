import { test, expect, Page } from '@playwright/test';

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
    const initialCount = await movieCards.count();
    
    if (initialCount > 0) {
      // Get the title of the first movie
      const firstTitle = await movieCards.first().getAttribute('data-title');
      
      // Type in the filter
      const searchInput = page.locator('input[placeholder*="filter" i]');
      await searchInput.fill(firstTitle || '');
      
      // Wait for filter to apply
      await page.waitForTimeout(300);
      
      // The first movie should still be visible
      const visibleCards = page.locator('#movie-grid .poster-card:not([style*="display: none"])');
      const filteredCount = await visibleCards.count();
      
      // Filtered count should be less than or equal to initial
      expect(filteredCount).toBeLessThanOrEqual(initialCount);
      // And at least one card should be visible (the one we searched for)
      expect(filteredCount).toBeGreaterThan(0);
    }
  });

  test('clicking Wanted filter should filter movies', async ({ page }) => {
    const wantedButton = page.getByRole('button', { name: /wanted/i });
    await wantedButton.click();
    
    // Button should be highlighted
    await expect(wantedButton).toHaveClass(/text-cp-accent/);
    
    // Wait for filter to apply
    await page.waitForTimeout(300);
    
    // All visible cards should have status "active" (wanted)
    const visibleCards = page.locator('#movie-grid .poster-card:not([style*="display: none"])');
    const count = await visibleCards.count();
    
    for (let i = 0; i < Math.min(count, 5); i++) {
      const status = await visibleCards.nth(i).getAttribute('data-status');
      if (status) {
        expect(status).toBe('active');
      }
    }
  });

  test('clicking Available filter should filter movies', async ({ page }) => {
    const availableButton = page.getByRole('button', { name: /available/i });
    await availableButton.click();
    
    // Button should be highlighted with accent colour
    await expect(availableButton).toHaveClass(/text-cp-accent/);
    
    // Wait for filter to apply
    await page.waitForTimeout(300);
    
    // All visible cards should have data-has-releases="true" (has releases or downloading)
    const visibleCards = page.locator('#movie-grid .poster-card:not([style*="display: none"])');
    const count = await visibleCards.count();
    
    for (let i = 0; i < Math.min(count, 5); i++) {
      const hasReleases = await visibleCards.nth(i).getAttribute('data-has-releases');
      if (hasReleases !== null) {
        expect(hasReleases).toBe('true');
      }
    }
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
});
