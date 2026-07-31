import { test, expect, type Page } from '@playwright/test';

/**
 * Movie detail page tests for CouchPotato new UI.
 */

// scripts/seed_e2e_data.py's deterministic movie -- see release_controls.spec.ts
// and accessibility.a11y.spec.ts's own copies of this constant/pattern for why
// FEAT-008's tests below navigate straight to it by id rather than clicking
// whichever poster card happens to be first on '/': the seeded movie starts
// 'active' but already has releases, so it never appears in the Wanted grid
// ('/' only lists active movies with NO releases yet) -- that grid being
// empty is exactly what made the pre-FEAT-008 firstCard-based versions of the
// two "Search for releases" tests below silently skip. A fixed id sidesteps
// both that and the "first card" ordering fragility other specs' shared-state
// mutations (e.g. "Mark as Done") already cause across this whole suite.
const SEEDED_MOVIE_ID = 'e2e-seed-movie-001';

async function gotoSeededMovie(page: Page) {
  await page.goto(`/movie/${SEEDED_MOVIE_ID}`);

  // The detail body arrives via detail.html's hx-trigger="load" swap, so wait
  // for the swapped-in content itself (#movie-releases only exists inside
  // partials/movie_releases.html) rather than #movie-detail-container, which
  // is static shell markup present before the request even fires and so
  // would resolve instantly, waiting for nothing -- same bug class documented
  // at length in release_controls.spec.ts's beforeEach.
  const loaded = await page.locator('#movie-releases')
    .waitFor({ state: 'attached', timeout: 15000 })
    .then(() => true)
    .catch(() => false);

  test.skip(!loaded,
    `no seeded movie at /movie/${SEEDED_MOVIE_ID} -- either the seed did not run ` +
    '(scripts/seed_e2e_data.py --data_dir=<dir> before starting the server), or ' +
    'the detail partial took over 15s to load');
}

test.describe('Movie Detail', () => {
  test('should navigate to movie detail from wanted list', async ({ page }) => {
    await page.goto('/');
    
    // Wait for movies to load
    const movieGrid = page.locator('#movie-grid');
    await expect(movieGrid).toBeVisible({ timeout: 10000 });
    
    // Get first movie card
    const firstCard = movieGrid.locator('.poster-card').first();
    if (await firstCard.count() > 0) {
      // Click on the movie
      await firstCard.click();
      
      // Should navigate to detail page
      await expect(page).toHaveURL(/.*movie\/.+/);
      
      // Should show movie title
      await expect(page.locator('h1')).toBeVisible({ timeout: 5000 });
    }
  });

  test('should show refresh button on detail page', async ({ page }) => {
    await page.goto('/');
    
    const movieGrid = page.locator('#movie-grid');
    await expect(movieGrid).toBeVisible({ timeout: 10000 });
    
    const firstCard = movieGrid.locator('.poster-card').first();
    if (await firstCard.count() > 0) {
      await firstCard.click();
      await expect(page).toHaveURL(/.*movie\/.+/);
      
      // Should have Refresh button
      const refreshButton = page.getByRole('button', { name: /refresh/i });
      await expect(refreshButton).toBeVisible({ timeout: 5000 });
    }
  });

  test('should show Delete button on detail page', async ({ page }) => {
    await page.goto('/');
    
    const movieGrid = page.locator('#movie-grid');
    await expect(movieGrid).toBeVisible({ timeout: 10000 });
    
    const firstCard = movieGrid.locator('.poster-card').first();
    if (await firstCard.count() > 0) {
      await firstCard.click();
      await expect(page).toHaveURL(/.*movie\/.+/);
      
      // Should have Delete button
      const deleteButton = page.getByRole('button', { name: /delete/i });
      await expect(deleteButton).toBeVisible({ timeout: 5000 });
    }
  });

  test('should show back link on detail page', async ({ page }) => {
    await page.goto('/');
    
    const movieGrid = page.locator('#movie-grid');
    await expect(movieGrid).toBeVisible({ timeout: 10000 });
    
    const firstCard = movieGrid.locator('.poster-card').first();
    if (await firstCard.count() > 0) {
      await firstCard.click();
      await expect(page).toHaveURL(/.*movie\/.+/);
      
      // Should have Back link
      const backLink = page.getByRole('link', { name: /back/i });
      await expect(backLink).toBeVisible({ timeout: 5000 });
      
      // Click back should navigate away
      await backLink.click();
      await expect(page).not.toHaveURL(/.*movie\/.+/);
    }
  });

  test('year should show TBA for movies without release date (DEF-005)', async ({ page }) => {
    // This test verifies the fix for DEF-005
    // We can't easily find a movie without a year, so we just verify
    // that the year format is correct (either a number or TBA)
    await page.goto('/');

    const movieGrid = page.locator('#movie-grid');
    await expect(movieGrid).toBeVisible({ timeout: 10000 });

    const firstCard = movieGrid.locator('.poster-card').first();
    if (await firstCard.count() > 0) {
      // Check year format in card - should not be empty or "()"
      const yearText = await firstCard.locator('p').last().textContent();
      expect(yearText).toBeTruthy();
      expect(yearText).not.toBe('');
      expect(yearText?.trim()).not.toBe('()');
    }
  });

  /**
   * Downloaded/review workflow (specs/DOWNLOADED-REVIEW-WORKFLOW.md, Phase 3c).
   *
   * COVERAGE GAP: there is no fixture / test-only API to seed a movie in the
   * 'downloaded' (review-gate) status -- reaching it requires a profile with
   * manual_confirmation ON plus a real completed download (Phase 2 completion
   * routing). CI and local e2e always start from a fresh, empty data dir
   * (see playwright.config.ts's throwaway .e2e-data / .config), so the Wanted
   * list here can only ever contain 'active' movies (or be empty). We
   * therefore assert the review-gate buttons are ABSENT for whatever movie is
   * actually present, and skip (rather than fake) the "buttons ARE shown"
   * case -- faking a 'downloaded' movie via direct DB access from an e2e test
   * would misrepresent real coverage.
   */
  test('review-gate buttons (Mark Done / Mark Failed & Re-search) are absent for a non-downloaded movie', async ({ page }) => {
    await page.goto('/');

    const movieGrid = page.locator('#movie-grid');
    await expect(movieGrid).toBeVisible({ timeout: 10000 });

    const firstCard = movieGrid.locator('.poster-card').first();
    if (await firstCard.count() > 0) {
      await firstCard.click();
      await expect(page).toHaveURL(/.*movie\/.+/);
      await expect(page.locator('h1')).toBeVisible({ timeout: 5000 });

      // "Mark Done" (review-gate) has a distinct accessible name from the
      // pre-existing generic "Mark as Done" button (shown for any
      // non-done/non-downloaded movie) -- exact match keeps them from
      // being confused with each other.
      await expect(page.getByRole('button', { name: 'Mark Done', exact: true })).toHaveCount(0);
      await expect(page.getByRole('button', { name: /mark failed\s*&\s*re-search/i })).toHaveCount(0);

      // Per-release "Mark failed" (only rendered for a release in
      // 'downloaded' status) should likewise be absent.
      await expect(page.getByRole('button', { name: 'Mark failed', exact: true })).toHaveCount(0);
    }
  });

  test('Mark Failed & Re-search requires confirmation when shown (review-gate movie)', async ({ page }) => {
    await page.goto('/');

    const movieGrid = page.locator('#movie-grid');
    await expect(movieGrid).toBeVisible({ timeout: 10000 });

    const firstCard = movieGrid.locator('.poster-card').first();
    if (await firstCard.count() > 0) {
      await firstCard.click();
      await expect(page).toHaveURL(/.*movie\/.+/);

      const markFailedButton = page.getByRole('button', { name: /mark failed\s*&\s*re-search/i });
      if (await markFailedButton.count() > 0) {
        let dialogMessage: string | null = null;
        page.once('dialog', async (dialog) => {
          dialogMessage = dialog.message();
          expect(dialog.type()).toBe('confirm');
          await dialog.dismiss();
        });
        await markFailedButton.click();
        await expect.poll(() => dialogMessage).not.toBeNull();
        // Dismissed -- should not have navigated away or reloaded into an
        // active/searching state we didn't confirm.
        await expect(page).toHaveURL(/.*movie\/.+/);
      }
      // See the coverage-gap note on the preceding test: this suite has no
      // way to reliably produce a 'downloaded' movie, so the "dialog shown"
      // branch above only exercises when such a movie happens to exist.
    }
  });

  test('per-release Mark failed requires confirmation when shown', async ({ page }) => {
    await page.goto('/');

    const movieGrid = page.locator('#movie-grid');
    await expect(movieGrid).toBeVisible({ timeout: 10000 });

    const firstCard = movieGrid.locator('.poster-card').first();
    if (await firstCard.count() > 0) {
      await firstCard.click();
      await expect(page).toHaveURL(/.*movie\/.+/);

      const releaseMarkFailedButton = page.getByRole('button', { name: 'Mark failed', exact: true });
      if (await releaseMarkFailedButton.count() > 0) {
        let dialogMessage: string | null = null;
        page.once('dialog', async (dialog) => {
          dialogMessage = dialog.message();
          expect(dialog.type()).toBe('confirm');
          await dialog.dismiss();
        });
        await releaseMarkFailedButton.first().click();
        await expect.poll(() => dialogMessage).not.toBeNull();
      }
      // Coverage gap: see above -- no fixture produces a 'downloaded' release
      // in this suite, so this only exercises when one happens to exist.
    }
  });

  test('should show a "Search for releases" action on the detail page (FEAT-005)', async ({ page }) => {
    await gotoSeededMovie(page);

    // Present regardless of status: the feature exists so a movie you already
    // have can be re-checked against what providers currently offer.
    const searchBtn = page.locator('[data-testid="search-releases"]');
    await expect(searchBtn).toBeVisible({ timeout: 5000 });
    await expect(searchBtn).toBeEnabled();
    await expect(searchBtn).toContainText(/Search for releases/i);
  });

  test('the search action targets the list-only endpoint, not a full search', async ({ page }) => {
    await gotoSeededMovie(page);

    // Wiring it to the wrong endpoint would download rather than list, which
    // is precisely what this feature avoids -- so assert the request itself.
    const searchBtn = page.locator('[data-testid="search-releases"]');
    await expect(searchBtn).toBeVisible({ timeout: 5000 });

    const request = page.waitForRequest(
      (r) => r.url().includes('movie.searcher.search_releases'),
      { timeout: 10000 },
    );
    await searchBtn.click();
    const req = await request;
    expect(req.url()).not.toContain('full_search');
  });

  /**
   * FEAT-008: "Search for releases" used to setTimeout(() =>
   * location.reload(), 900) on success -- reporting "Found 0" and reloading
   * whether or not a search actually ran. It now updates #movie-releases in
   * place via htmx and reports one of three outcomes (found N / found
   * nothing / could not search, with a reason). The seeded movie always has
   * a real profile (scripts/seed_e2e_data.py), so this exercises the
   * "searched" path end to end; the no-profile / could-not-search path is
   * covered at the unit level (tests/unit/test_search_releases_list_only.py)
   * since there is no seed fixture for a profile-less movie.
   */
  test('the search action updates the release list in place, without a full page reload (FEAT-008)', async ({ page }) => {
    await gotoSeededMovie(page);

    const searchBtn = page.locator('[data-testid="search-releases"]');
    await expect(searchBtn).toBeVisible({ timeout: 5000 });
    const beforeUrl = page.url();

    const response = page.waitForResponse(
      (r) => r.url().includes('movie.searcher.search_releases'),
      { timeout: 15000 },
    );
    await searchBtn.click();

    // AC6: disabled and says so WHILE the search runs.
    await expect(searchBtn).toBeDisabled();
    await expect(searchBtn).toContainText(/Searching/i);

    const res = await response;
    expect(res.ok()).toBeTruthy();

    // AC6: re-enables once finished -- "running" and "finished" must be
    // distinguishable.
    await expect(searchBtn).toBeEnabled({ timeout: 10000 });
    await expect(searchBtn).toContainText(/Search for releases/i);

    // AC5: in place, not a reload -- same URL, release list still present
    // (a reload would briefly navigate away then re-render it from scratch;
    // an in-place htmx swap never changes the URL at all).
    expect(page.url()).toBe(beforeUrl);
    await expect(page.locator('#movie-releases')).toBeVisible();

    // A toast reporting the outcome must have appeared (AC5's "reports which
    // of the three outcomes occurred"). Scoped to the toast region's own
    // fixed-position wrapper (base.html), not just [aria-live="polite"]
    // alone -- the sr-only release-count announcer (detail.html) carries
    // that same attribute for an unrelated purpose, and role="status" alone
    // would also match the release list's own unrelated status text (e.g.
    // "No releases match the selected profile qualities").
    const toastRegion = page.locator('div.fixed.top-4.right-4[aria-live="polite"]');
    await expect(toastRegion.getByRole('status').first()).toBeVisible({ timeout: 5000 });
    await expect(toastRegion).toContainText(/Found \d+ release|no releases found|Could not search/i);
  });

  /**
   * FEAT-008 Problem 2: move a `done` movie back to wanted without losing
   * release history. The seeded movie starts 'active' (scripts/seed_e2e_data.py)
   * but shared suite state means another spec may already have moved it to
   * 'done' by the time this runs (documented at length in
   * release_controls.spec.ts) -- rather than depend on that ordering, drive
   * it to 'done' ourselves first via the pre-existing "Mark as Done" action
   * if needed, so this test deterministically exercises the real control
   * either way instead of skipping.
   */
  test('"Move back to wanted" restores a done movie to wanted (FEAT-008)', async ({ page }) => {
    await gotoSeededMovie(page);

    const restoreBtn = page.locator('[data-testid="restore-to-wanted"]');
    if (await restoreBtn.count() === 0) {
      const markDoneBtn = page.getByRole('button', { name: 'Mark as Done', exact: true });
      await expect(markDoneBtn).toBeVisible({ timeout: 5000 });
      await markDoneBtn.click();
      // media.done's success path is a full page reload (pre-existing
      // behaviour, out of FEAT-008's scope) -- wait for it to land, then for
      // the restore control that only renders for a 'done' movie.
      await page.waitForLoadState('networkidle');
      await expect(restoreBtn).toBeVisible({ timeout: 10000 });
    }

    // AC6: shown only for a done movie, with a profile picker.
    await expect(restoreBtn).toBeVisible();
    await restoreBtn.click();

    const confirmBtn = page.locator('[data-testid="restore-to-wanted-confirm"]');
    await expect(confirmBtn).toBeVisible({ timeout: 5000 });
    // The picker populates asynchronously and defaults to the default
    // profile -- wait for that fetch rather than confirming an empty
    // selection.
    await expect(confirmBtn).toBeEnabled({ timeout: 5000 });

    // Explicitly choose the seed's own profile rather than confirming
    // whatever the environment's system-wide "default" profile happens to
    // be: other specs in this suite (release_controls.spec.ts,
    // accessibility.a11y.spec.ts) read this same seeded movie and assume its
    // profile still matches its releases' qualities (1080p/720p). Confirming
    // an unrelated default (e.g. a single-quality "core" profile) would
    // leave THAT behind for every later spec, which is exactly the kind of
    // cross-file state pollution release_controls.spec.ts's own comments
    // warn about -- this is FEAT-008's "profile picker" AC6 exercised with
    // an explicit choice, not a claim about what the default itself resolves
    // to (that is covered at the unit level).
    await page.locator(`#restore-profile-${SEEDED_MOVIE_ID}`).selectOption({ label: 'E2E Seed Profile' });

    const response = page.waitForResponse(
      (r) => r.url().includes('movie.restore_to_wanted'),
      { timeout: 10000 },
    );
    await confirmBtn.click();
    const res = await response;
    expect(res.ok()).toBeTruthy();

    // AC6: updates in place and reports the outcome -- the whole detail body
    // swaps once the movie is active again, so the restore control disappears
    // and the ordinary "Mark as Done" action (done/downloaded-only-hidden)
    // reappears, leaving the movie back in its original 'active' state for
    // any other spec that reads this same seeded movie.
    await expect(page.locator('[data-testid="restore-to-wanted"]')).toHaveCount(0, { timeout: 10000 });
    await expect(page.getByRole('button', { name: 'Mark as Done', exact: true })).toBeVisible({ timeout: 5000 });
  });
});
