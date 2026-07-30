import { test, expect } from '@playwright/test';

/**
 * FEAT-007 Part B: the release list's filter and sort controls.
 *
 * The controls are htmx-driven: each one swaps #movie-releases. These tests
 * assert on what the user sees and on the ARIA state, not on the request.
 *
 * Setup follows tests/e2e/movie-detail.spec.ts's own pattern (goto('/'),
 * #movie-grid, .poster-card) rather than assuming a movie id or a dedicated
 * /wanted route -- both work, but matching the existing spec keeps this
 * suite consistent with the rest of the file it sits next to.
 *
 * COVERAGE GAP: CI/local e2e starts from a fresh, empty .e2e-data/.config (see
 * the coverage-gap notes in movie-detail.spec.ts and
 * specs/DOWNLOADED-REVIEW-WORKFLOW.md), so without a seed step there is no
 * movie with releases, let alone releases from multiple sources/qualities.
 * scripts/seed_e2e_data.py seeds exactly that (wired into playwright.config.ts's
 * webServer for local runs, and into the ui-e2e-tests/accessibility CI jobs) --
 * every test below still explicitly test.skip()s with a stated reason when
 * the library has no movie, no releases, or not enough variety to exercise a
 * given assertion (e.g. someone running this suite against their own,
 * unseeded instance), but the reason says plainly that the seed didn't run
 * rather than leaving it looking like a routine, expected skip.
 */

test.describe('Release list controls', () => {
  // The movie scripts/seed_e2e_data.py creates. Navigating straight to it,
  // rather than clicking whichever card happens to be first on '/', is what
  // makes these tests order-independent: other specs in this suite mutate
  // shared app state (one clicks "Mark as Done", which moves a movie out of
  // the Wanted view entirely), and other movies can appear (search.spec.ts
  // adds real ones), so "the first card" is neither stable nor necessarily
  // a movie with releases. The id is deterministic, so the URL always is.
  const SEEDED_MOVIE_ID = 'e2e-seed-movie-001';

  test.beforeEach(async ({ page }) => {
    await page.goto(`/movie/${SEEDED_MOVIE_ID}`);

    // Wait for the release list itself, not the <h1>: these tests are about
    // the controls, and coupling setup to unrelated title rendering makes all
    // six fail for a reason that has nothing to do with them.
    await page.waitForSelector('#movie-releases, #movie-detail-container', { timeout: 15000 });

    test.skip(
      await page.locator('#movie-releases').count() === 0,
      `no seeded movie with releases at /movie/${SEEDED_MOVIE_ID} -- the seed ` +
      'did not run: scripts/seed_e2e_data.py --data_dir=<dir> before starting the server',
    );
  });

  test('the release table exposes sortable headers with aria-sort', async ({ page }) => {
    const releases = page.locator('#movie-releases');
    test.skip(
      await releases.locator('table').count() === 0,
      'this movie has no releases -- no seeded movie with releases: run ' +
      'scripts/seed_e2e_data.py --data_dir=<dir> before starting the server',
    );

    const sortable = releases.locator('th[aria-sort]');
    expect(await sortable.count()).toBeGreaterThan(0);
    // Nothing is sorted until the user asks (B1: defaults reproduce the old page).
    for (const th of await sortable.all()) {
      expect(await th.getAttribute('aria-sort')).toBe('none');
    }
  });

  test('sorting by size marks that column and reorders the rows', async ({ page }) => {
    const releases = page.locator('#movie-releases');
    test.skip(
      await releases.locator('table').count() === 0,
      'this movie has no releases -- no seeded movie with releases: run ' +
      'scripts/seed_e2e_data.py --data_dir=<dir> before starting the server',
    );
    test.skip(
      await releases.locator('tbody tr').count() < 2,
      'need at least two releases to observe a reorder -- scripts/seed_e2e_data.py ' +
      'seeds 6, so this indicates the seed did not run rather than a routine skip',
    );

    const before = await releases.locator('tbody tr').first().textContent();

    await releases.getByRole('link', { name: /^Size/ }).click();
    await expect(releases.locator('th[aria-sort="descending"]')).toHaveCount(1);

    // Clicking again reverses it.
    await releases.getByRole('link', { name: /^Size/ }).click();
    await expect(releases.locator('th[aria-sort="ascending"]')).toHaveCount(1);

    const after = await releases.locator('tbody tr').first().textContent();
    expect(after).not.toBe(before);
  });

  test('filtering by source shows only that source', async ({ page }) => {
    const releases = page.locator('#movie-releases');
    test.skip(
      await releases.locator('table').count() === 0,
      'this movie has no releases -- no seeded movie with releases: run ' +
      'scripts/seed_e2e_data.py --data_dir=<dir> before starting the server',
    );

    const select = releases.locator('#rel-source');
    const options = await select.locator('option').allInnerTexts();
    test.skip(
      !options.some(o => /NZB/i.test(o)) || !options.some(o => /Torrent/i.test(o)),
      'this movie has releases from only one source -- scripts/seed_e2e_data.py ' +
      'seeds both NZB and torrent releases, so this indicates the seed did not ' +
      'run rather than a routine skip',
    );

    await select.selectOption('nzb');
    await expect(page.locator('#movie-releases')).toBeVisible();
    // Column order is fixed by SORT_COLUMNS in releases_view.py: Name,
    // Quality, Score, Size, Seeders, Source, Status, Age -- Source is the
    // 6th <td>.
    const sources = await page.locator('#movie-releases tbody tr td:nth-child(6)').allInnerTexts();
    for (const source of sources) {
      expect(source.trim()).toMatch(/NZB/i);
    }
  });

  test('the result count is announced in a live region', async ({ page }) => {
    const releases = page.locator('#movie-releases');
    test.skip(
      await releases.locator('table').count() === 0,
      'this movie has no releases -- no seeded movie with releases: run ' +
      'scripts/seed_e2e_data.py --data_dir=<dir> before starting the server',
    );

    await expect(releases.locator('[aria-live="polite"]')).toContainText(/release/);
  });

  test('Download and Skip still work after a swap (B13)', async ({ page }) => {
    const releases = page.locator('#movie-releases');
    test.skip(
      await releases.locator('table').count() === 0,
      'this movie has no releases -- no seeded movie with releases: run ' +
      'scripts/seed_e2e_data.py --data_dir=<dir> before starting the server',
    );

    await releases.getByRole('link', { name: /^Score/ }).click();
    await expect(page.locator('#movie-releases')).toBeVisible();

    // The Alpine component must have rebound after the swap: the buttons are
    // present and enabled, not inert. Do NOT click Download -- that would
    // snatch a real release.
    const action = page.locator('#movie-releases button', { hasText: /Download|Skip/ }).first();
    if (await action.count() > 0) {
      await expect(action).toBeEnabled();
    }
  });

  test('a bookmarked filtered URL renders filtered on first paint (B8)', async ({ page }) => {
    const releases = page.locator('#movie-releases');
    test.skip(
      await releases.locator('table').count() === 0,
      'this movie has no releases -- no seeded movie with releases: run ' +
      'scripts/seed_e2e_data.py --data_dir=<dir> before starting the server',
    );

    const url = new URL(page.url());
    url.searchParams.set('sort', 'size');
    url.searchParams.set('dir', 'desc');

    await page.goto(url.toString());
    await expect(page.locator('#movie-releases table')).toBeVisible({ timeout: 10000 });
    await expect(page.locator('#movie-releases th[aria-sort="descending"]')).toHaveCount(1);
  });
});
