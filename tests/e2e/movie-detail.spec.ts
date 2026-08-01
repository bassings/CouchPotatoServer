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

/*
 * The movie the DESTRUCTIVE tests use (scripts/seed_e2e_data.py).
 *
 * "Move back to wanted" marks the movie's held releases 'ignored', which
 * permanently destroys what release_controls.spec.ts needs -- measured: all six
 * of its tests fail against a movie whose releases have all been ignored. That
 * went unseen because those tests carried skip guards that stood down silently
 * instead of failing, so the damage read as "no seeded data".
 *
 * Identical fixture, separate movie. Isolation, not a different scenario.
 */
const DESTRUCTIVE_MOVIE_ID = 'e2e-seed-movie-002';

async function gotoDestructiveMovie(page: Page) {
  return gotoMovie(page, DESTRUCTIVE_MOVIE_ID);
}

async function gotoSeededMovie(page: Page) {
  return gotoMovie(page, SEEDED_MOVIE_ID);
}

async function gotoMovie(page: Page, movieId: string) {
  await page.goto(`/movie/${movieId}`);

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

  /*
   * FAIL, don't skip.
   *
   * This used to be test.skip(!loaded, ...), and playwright.config.ts runs the
   * seed with `|| true`. Between them, a broken seed made every FEAT-008 E2E
   * test disappear into a green run -- the feature would look covered while
   * nothing exercised it. The seed is load-bearing now, so its absence is a
   * failure, not a reason to stand down.
   *
   * The message carries the fix, so a genuinely un-seeded environment gets an
   * actionable error rather than a bare timeout.
   */
  expect(
    loaded,
    `No seeded movie at /movie/${movieId}. Run ` +
    '`.venv/bin/python scripts/seed_e2e_data.py --data_dir=.e2e-data` BEFORE ' +
    'starting the server (playwright.config.ts does this for local runs; CI ' +
    'does it in its own step). If the seed did run, the detail partial took ' +
    'over 15s to load.',
  ).toBe(true);
}


/**
 * The seeded movie's CURRENT profile id.
 *
 * The restore picker defaults to the first profile in profile.list, which is a
 * single-quality default profile -- not the seeded one (2160p/1080p/720p). A
 * restore that accepts that default reassigns the movie to a profile none of
 * its seeded releases match, so partials/movie_releases.html renders no table
 * at all and every release_controls test then test.skip()s with "the seed did
 * not run" -- six tests silently dropped from a green run.
 *
 * So the restore tests below pick the movie's existing profile explicitly.
 * That is also the more realistic action: a user moving a movie back to wanted
 * usually keeps its profile.
 */
async function seededMovieProfileId(page: Page, movieId: string = SEEDED_MOVIE_ID): Promise<string> {
  const id = await page.evaluate(async (movieId) => {
    const res = await fetch(`${(window as any).CP.apiBase}/media.get/?id=${movieId}`);
    const data = await res.json();
    return (data?.media ?? data)?.profile_id ?? '';
  }, movieId);
  expect(id, 'seeded movie has no profile to preserve').toBeTruthy();
  return id;
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
   * nothing / could not search, with a reason).
   *
   * WHICH outcome this produces depends on the environment, and in CI/local
   * it is the could-not-search one: no downloader is enabled, so
   * _searchReleases returns searched:false before contacting any provider.
   * An earlier version of this comment claimed the seeded movie's real
   * profile made this exercise the "searched" path end to end -- it does
   * not, and the "Found N new releases" / "No new releases" message
   * construction has no E2E coverage in any environment. It is covered at the
   * unit level (tests/unit/test_search_releases_list_only.py). The assertions
   * below therefore check the toast against whatever the API actually
   * returned rather than assuming a branch.
   */
  test('the search action updates the release list in place, without a full page reload (FEAT-008)', async ({ page }) => {
    await gotoSeededMovie(page);

    const searchBtn = page.locator('[data-testid="search-releases"]');
    await expect(searchBtn).toBeVisible({ timeout: 5000 });
    const beforeUrl = page.url();

    /*
     * AC5 needs two things proved, and the URL cannot prove either:
     * location.reload() does not change the URL, and #movie-releases exists
     * from the initial render, so `url unchanged` + `#movie-releases visible`
     * were both satisfied by a full reload AND by no update happening at all.
     * Deleting the htmx.ajax call entirely, and replacing it with the old
     * setTimeout(() => location.reload(), 900), both used to pass.
     *
     * 1. A sentinel on window: any document-level navigation wipes it.
     * 2. A handle to the CURRENT #movie-releases node: the swap is
     *    hx-swap="outerHTML", so a real in-place update REPLACES that node
     *    and the old handle becomes detached.
     */
    await page.evaluate(() => { (window as any).__noReloadSentinel = 'alive'; });
    const listNodeBefore = await page.locator('#movie-releases').elementHandle();
    expect(listNodeBefore, 'no #movie-releases to swap').not.toBeNull();

    /*
     * Hold the search response open so the running state is OBSERVABLE.
     * Against a local server with no providers configured the search returns
     * in a few ms -- faster than an assertion can start polling -- so
     * asserting the transient state directly was a race that failed most
     * runs. Delaying the response is what makes "disabled while running" a
     * real assertion rather than a coin flip.
     */
    const SEARCH_HOLD_MS = 1500;
    // Regex, NOT a glob: the request path ends '/movie.searcher.search_releases/
    // ?media_id=N', and in a Playwright glob a single `*` does not cross `/`,
    // so '**/movie.searcher.search_releases*' silently matched nothing and the
    // hold never applied -- leaving in place the exact race it exists to remove.
    let held = false;
    await page.route(/movie\.searcher\.search_releases/, async (route) => {
      held = true;
      await new Promise((resolve) => setTimeout(resolve, SEARCH_HOLD_MS));
      await route.continue();
    });

    const response = page.waitForResponse(
      (r) => r.url().includes('movie.searcher.search_releases'),
      { timeout: 15000 },
    );
    await searchBtn.click();

    // AC6: marked busy/disabled and says so WHILE the search runs.
    // aria-disabled, not the `disabled` attribute: a focused button that
    // becomes disabled is blurred by the browser, which dropped a keyboard
    // user back to <body>. The attribute assertions are what the a11y
    // behaviour now rests on.
    await expect(searchBtn).toHaveAttribute('aria-disabled', 'true');
    await expect(searchBtn).toHaveAttribute('aria-busy', 'true');
    // getByText + toBeVisible, NOT toContainText: textContent includes the
    // x-show-hidden "Searching…" span, so toContainText(/Searching/i) passed
    // while the button was idle AND enabled — it asserted nothing.
    await expect(searchBtn.getByText('Searching…')).toBeVisible();

    const res = await response;
    expect(res.ok()).toBeTruthy();
    // Pins that the hold above actually applied. Without this a broken
    // route pattern makes the running-state assertions a coin flip that
    // mostly passes -- which is how the bad glob went unnoticed.
    expect(held, 'the search request was never intercepted, so the running-state assertions were a race').toBe(true);

    // AC6: re-enables once finished -- "running" and "finished" must be
    // distinguishable.
    await expect(searchBtn).toHaveAttribute('aria-disabled', 'false', { timeout: 10000 });
    // getByText + toBeVisible for the SAME reason as the "Searching…" check
    // above: toContainText reads textContent, which includes the x-show-hidden
    // sibling span, so it passed with the label permanently stuck on
    // "Searching…". Fixing one instance and leaving the other was an oversight.
    await expect(searchBtn.getByText('Search for releases')).toBeVisible();

    // AC5, for real this time: no navigation occurred...
    expect(page.url()).toBe(beforeUrl);
    expect(
      await page.evaluate(() => (window as any).__noReloadSentinel),
      'the page navigated/reloaded — AC5 requires an in-place update',
    ).toBe('alive');

    // ...and the release list node was genuinely replaced by the outerHTML
    // swap, so "in place" means updated, not merely "still there".
    await expect
      .poll(() => listNodeBefore!.evaluate((n) => n.isConnected), { timeout: 10000 })
      .toBe(false);
    await expect(page.locator('#movie-releases')).toBeVisible();

    // A toast reporting the outcome must have appeared (AC5's "reports which
    // of the three outcomes occurred"). Scoped to the toast region's own
    // own wrapper (base.html), addressed by data-testid. role="status" alone
    // would also match the release list's own unrelated status text (e.g.
    // "No releases match the selected profile qualities"), and the toasts
    // themselves deliberately carry no role at all -- announcement happens
    // through the persistent sr-only regions in the shell, not these nodes.
    const toastRegion = page.locator('[data-testid="toast-region"]');
    // The visual toasts have no role -- they are addressed by data-testid.
    const anyToast = toastRegion.locator('[data-testid="toast"]');
    await expect(anyToast.first()).toBeVisible({ timeout: 5000 });
    /*
     * Assert against the outcome the API ACTUALLY reported, not a fixed
     * regex. AC3's whole point is that the three outcomes are distinguishable,
     * so the meaningful check is that the toast matches THIS response --
     * a hardcoded pattern silently went stale the moment a new `reason`
     * string was added (it expected /Could not search/ and the server had
     * begun returning the specific "no enabled downloader" reason).
     *
     * Which outcome occurs depends on the environment: with no downloader
     * configured (the usual E2E case) it is the not-searched branch; with one
     * configured it is searched/found-nothing. Both are correct, and both are
     * checked here against what the server said.
     */
    const body = await res.json();
    if (body.searched) {
      await expect(toastRegion).toContainText(
        body.found ? new RegExp(`Found ${body.found} new release`) : /No new releases/,
      );
    } else {
      expect(body.reason, 'a not-searched response must carry a reason').toBeTruthy();
      await expect(toastRegion).toContainText(body.reason);
    }
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
    await gotoDestructiveMovie(page);

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

    const keepProfile = await seededMovieProfileId(page, DESTRUCTIVE_MOVIE_ID);
    await page.locator('select[id^="restore-profile-"]').selectOption(keepProfile);

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
    await page.locator(`#restore-profile-${DESTRUCTIVE_MOVIE_ID}`).selectOption({ label: 'E2E Seed Profile' });

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
    // NOT toHaveCount(0) on the trigger: it lives inside
    // <template x-if="!showPicker">, so it had already left the DOM when the
    // picker opened -- that assertion was satisfied before the request was
    // even sent. The reappearing "Mark as Done" action is the real signal
    // that the detail body swapped and the movie is active again.
    await expect(page.getByRole('button', { name: 'Mark as Done', exact: true })).toBeVisible({ timeout: 10000 });
    await expect(page.locator('[data-testid="restore-to-wanted"]')).toHaveCount(0);
  });

  /*
   * FEAT-008 a11y. Both behaviours below were broken and unguarded: activating
   * either control deleted the element that had focus, and the running state
   * of the search was conveyed only visually.
   */
  test('the search control keeps focus and announces that it started (FEAT-008 a11y)', async ({ page }) => {
    await gotoSeededMovie(page);

    const searchBtn = page.locator('[data-testid="search-releases"]');
    await expect(searchBtn).toBeVisible({ timeout: 5000 });

    // Hold the response open so the running state is observable at all.
    let held = false;
    await page.route(/movie\.searcher\.search_releases/, async (route) => {
      held = true;
      await new Promise((resolve) => setTimeout(resolve, 1500));
      await route.continue();
    });

    await searchBtn.focus();
    await page.keyboard.press('Enter');

    /*
     * Focus must SURVIVE. The button used to take the `disabled` attribute
     * while searching; the browser blurs a focused element when it becomes
     * disabled, so activeElement fell back to <body> and the next Tab
     * resumed from the top of the document. aria-disabled conveys the same
     * state without moving focus.
     */
    const focused = await page.evaluate(
      () => document.activeElement?.getAttribute('data-testid') ?? document.activeElement?.tagName,
    );
    expect(focused, 'focus was destroyed by activating the search control').toBe('search-releases');

    // And the start of the search must be ANNOUNCED, not just shown: the
    // label swapping to "Searching…" is invisible to a screen reader.
    const announcer = page.locator('[data-testid="search-announcer"]');
    await expect(announcer).toHaveText(/searching/i);
    await expect(searchBtn).toHaveAttribute('aria-busy', 'true');

    expect(held, 'the search response was never held, so this raced').toBe(true);
    await expect(searchBtn).toHaveAttribute('aria-disabled', 'false', { timeout: 10000 });
  });

  test('the restore picker moves focus in, and Escape returns it (FEAT-008 a11y)', async ({ page }) => {
    await gotoDestructiveMovie(page);

    /*
     * Drive the movie to 'done' if it is not already, exactly as the sibling
     * restore test does. Skipping instead (the first version of this test did)
     * makes the whole a11y guard vanish green whenever suite ordering leaves
     * the movie active -- which is what happened on its very first run.
     */
    const trigger = page.locator('[data-testid="restore-to-wanted"]');
    if ((await trigger.count()) === 0) {
      const markDoneBtn = page.getByRole('button', { name: 'Mark as Done', exact: true });
      await expect(markDoneBtn).toBeVisible({ timeout: 5000 });
      await markDoneBtn.click();
      await page.waitForLoadState('networkidle');
      await expect(trigger).toBeVisible({ timeout: 10000 });
    }

    await trigger.focus();
    await page.keyboard.press('Enter');

    // Opening removes the trigger (it is inside <template x-if="!showPicker">),
    // so focus has to be moved deliberately or it lands on <body>.
    const picker = page.locator('select[id^="restore-profile-"]');
    await expect(picker).toBeVisible({ timeout: 5000 });
    await expect(picker).toBeFocused();

    // Escape must close it AND put focus back where it came from.
    await page.keyboard.press('Escape');
    await expect(picker).toHaveCount(0, { timeout: 5000 });
    await expect(trigger).toBeFocused();
  });

  /*
   * Both error-recovery paths were DEAD CODE until cpSwap() was introduced:
   * htmx.ajax() resolves on an HTTP error rather than rejecting (measured
   * directly against a stubbed 500), so `htmx.ajax(...).catch(...)` never ran
   * and the failure each catch was written to handle happened anyway.
   */
  test('a failed release-list refresh is reported, not silently ignored (FEAT-008)', async ({ page }) => {
    await gotoSeededMovie(page);
    const searchBtn = page.locator('[data-testid="search-releases"]');
    await expect(searchBtn).toBeVisible({ timeout: 5000 });

    // The search itself succeeds; only the follow-up list refresh fails.
    await page.route(/partial\/movie\/[^/]+\/releases/, (route) =>
      route.fulfill({ status: 500, body: 'boom' }));

    await searchBtn.click();

    // The user must be told the list is stale rather than shown a stale list
    // as though it were fresh.
    const toastRegion = page.locator('[data-testid="toast-region"]');
    await expect(toastRegion).toContainText(/could not refresh/i, { timeout: 15000 });

    // And the control must not be left stuck in its busy state.
    await expect(searchBtn).toHaveAttribute('aria-disabled', 'false', { timeout: 10000 });
  });

  test('a failed post-restore refresh does not leave the control stuck (FEAT-008)', async ({ page }) => {
    await gotoDestructiveMovie(page);

    const trigger = page.locator('[data-testid="restore-to-wanted"]');
    if ((await trigger.count()) === 0) {
      const markDoneBtn = page.getByRole('button', { name: 'Mark as Done', exact: true });
      await expect(markDoneBtn).toBeVisible({ timeout: 5000 });
      await markDoneBtn.click();
      await page.waitForLoadState('networkidle');
      await expect(trigger).toBeVisible({ timeout: 10000 });
    }
    await trigger.click();

    const keepProfile = await seededMovieProfileId(page, DESTRUCTIVE_MOVIE_ID);
    await page.locator('select[id^="restore-profile-"]').selectOption(keepProfile);

    const confirmBtn = page.locator('[data-testid="restore-to-wanted-confirm"]');
    await expect(confirmBtn).toBeEnabled({ timeout: 10000 });

    // The restore succeeds server-side; only the detail refresh fails. This is
    // the dangerous case: the movie HAS moved, so a stuck spinner hides a
    // change that already happened.
    await page.route(/partial\/movie\/[^/]+(\?|$)/, (route) =>
      route.fulfill({ status: 500, body: 'boom' }));

    await confirmBtn.click();

    await expect(page.locator('[data-testid="restore-to-wanted-confirm"]'))
      .toBeEnabled({ timeout: 15000 });
    await expect(page.locator('[data-testid="toast-region"]'))
      .toContainText(/could not refresh|reload/i, { timeout: 5000 });
  });

  test('confirming a restore keeps keyboard focus (FEAT-008 a11y)', async ({ page }) => {
    /*
     * The Confirm button used the `disabled` attribute while restoring, and
     * the browser BLURS a focused element when it becomes disabled --
     * measured: focus went to BODY mid-flight and stayed there. This is the
     * third instance of the same defect on this branch (search button, picker
     * trigger), and the only one that runs on every SUCCESSFUL restore.
     *
     * The response is held open so the busy state is observable at all.
     */
    await gotoDestructiveMovie(page);

    const trigger = page.locator('[data-testid="restore-to-wanted"]');
    if ((await trigger.count()) === 0) {
      const markDoneBtn = page.getByRole('button', { name: 'Mark as Done', exact: true });
      await expect(markDoneBtn).toBeVisible({ timeout: 5000 });
      await markDoneBtn.click();
      await page.waitForLoadState('networkidle');
      await expect(trigger).toBeVisible({ timeout: 10000 });
    }
    await trigger.click();

    const keepProfile = await seededMovieProfileId(page, DESTRUCTIVE_MOVIE_ID);
    await page.locator('select[id^="restore-profile-"]').selectOption(keepProfile);

    let held = false;
    await page.route(/movie\.restore_to_wanted/, async (route) => {
      held = true;
      await new Promise((resolve) => setTimeout(resolve, 1500));
      await route.continue();
    });

    const confirmBtn = page.locator('[data-testid="restore-to-wanted-confirm"]');
    await confirmBtn.focus();
    await page.keyboard.press('Enter');

    const focused = await page.evaluate(
      () => document.activeElement?.getAttribute('data-testid') ?? document.activeElement?.tagName,
    );
    expect(focused, 'focus was destroyed by confirming the restore').toBe('restore-to-wanted-confirm');
    await expect(confirmBtn).toHaveAttribute('aria-busy', 'true');
    expect(held, 'the restore response was never held, so this raced').toBe(true);
  });
});
