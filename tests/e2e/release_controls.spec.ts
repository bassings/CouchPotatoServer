import { test, expect } from './fixtures';

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
 * every test below ASSERTS its precondition rather than skipping on it. If the
 * library has no movie, no releases, or not enough variety to exercise a given
 * assertion, that is the seed having failed or the app having regressed, and
 * either way it is a red -- not a routine, expected skip that quietly shrinks
 * the suite. See NOTE ON PRECONDITIONS below for what changed and why.
 */

test.describe('Release list controls', () => {
  /*
   * A LARGER per-test budget than the 30s default, for this file only.
   *
   * beforeEach here waits for a server-rendered release table, and it spends
   * from the same budget the test does, and every run pays seeding plus a
   * first request: fixtures.ts creates a fresh per-worker data dir and seeds
   * it before the server starts. (This used to say verify.sh wipes the data
   * dir. It does not, and did not after T1.7: verify.sh:120-129 now treats a
   * surviving directory as a failure to surface rather than one to clean up.) Shaving the wait does not
   * work: no value is both long enough for a slow cold start and shorter than
   * the budget it comes out of -- at 30s the hook timed out at exactly 30.0s,
   * and at 20s a cold run still lost a test at 28.9s. The budget was the wrong
   * size, so it is the budget that changes.
   */
  test.describe.configure({ timeout: 60000 });

  /*
   * NOTE ON PRECONDITIONS. Six per-test `test.skip(await
   * releases.locator('table').count() === 0, ...)` guards used to live in
   * this file; they were removed as redundant with beforeEach. The
   * remaining ones have now been converted from skips into assertions.
   *
   * The justification for skipping was that someone might run this suite
   * against their own, unseeded instance. T1.7 deleted that path:
   * tests/e2e/fixtures.ts seeds every worker before its server starts and
   * throws if the seed fails, so an unseeded server cannot reach these
   * specs. What was left was a guard that trips on SLOWNESS and silently
   * drops a different test each run while the gate reports green -- the
   * harm this file's own comments already documented ("fired in 3 of 4
   * runs, each time silently dropping a DIFFERENT test"), and which was
   * measured again on this branch: 1 of 3 identical gate runs dropped
   * 'sorting by size marks that column and reorders the rows'.
   */

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

    // Wait for the htmx swap to actually land, not for the always-present
    // shell: #movie-detail-container is STATIC markup in detail.html (it's
    // the hx-get host, present before the request even fires), so a comma
    // selector like '#movie-releases, #movie-detail-container' resolves
    // instantly against the shell and waits for nothing. The skip guard
    // below then ran before htmx had swapped in the release list at all --
    // proven with an artificially delayed partial response (a 400ms delay
    // was enough to make every test in this file skip while reporting "the
    // seed did not run", when in fact it had). Wait on #movie-releases
    // itself instead: that id only exists in the swapped-in content
    // (partials/movie_releases.html), never in the shell.
    const swapped = await page.locator('#movie-releases')
      .waitFor({ state: 'attached', timeout: 15000 })
      .then(() => true)
      .catch(() => false);

    // Distinguish a real load timeout (something is actually wrong/slow --
    // never a routine skip) from the legitimate "seed didn't run" case below.
    // FAIL, do not skip. Every one of this file's skip guards was justified
    // at :20 as covering "someone running this suite against their own,
    // unseeded instance" -- a path T1.7 deleted, because fixtures.ts seeds
    // every worker before its server starts and throws if the seed fails.
    // What survived was a slowness guard that silently drops a DIFFERENT
    // test each run while the gate reports green: measured on this branch,
    // 1 of 3 identical gate runs dropped 'sorting by size'. The readiness
    // probe in fixtures.ts now warms this route so the cold start is paid
    // once by the harness; if it is still not ready here, that is a
    // regression and it should say so.
    expect(swapped, 'timed out after 15s waiting for the movie detail htmx ' +
      'load to swap in #movie-releases -- this is a load/perf problem, not a ' +
      'missing seed').toBe(true);

    // Wait for the TABLE, not just the container. `#movie-releases` is attached
    // as soon as the outer partial swaps in, but its <table> is rendered a beat
    // later -- so a non-retrying `.count() === 0` read here raced the render and
    // skipped the test with "the seed did not run", which was FALSE: sibling
    // tests in the same run passed against the same seeded data.
    //
    // Under parallel workers the server is slower and this fired in 3 of 4 runs,
    // each time silently dropping a DIFFERENT test from the suite while the gate
    // stayed green. A skip that lies is worse than a failure: it erodes coverage
    // invisibly and sends the next person to re-run a seed that already worked.
    // Same bug class as the one fixed 80 lines below -- a non-retrying read
    // standing in for a wait.
    // 20s, not 10s: this must tolerate a COLD START -- but it must also stay
    // UNDER playwright.config.ts's 30s per-test timeout, which beforeEach spends
    // from. Setting it to 30s made the wait unable to ever complete: the hook
    // timed out at exactly 30.0s. Measured cold-start need is ~12-16s. every run pays seeding plus first request:
    // fixtures.ts creates a fresh per-worker data dir and seeds it before the
    // server starts. (An earlier comment here said verify.sh wipes the data
    // dir; it does not -- verify.sh:120-129 now treats a surviving directory
    // as a failure to surface rather than something to clean up.) Measured: the first run after a clean dir skipped one test while
    // the second and third did not -- 5/6/6 passed across three runs. A guard
    // that trips on slowness silently drops coverage and reports green, which
    // is precisely what this file's own comments warn about.
    const hasTable = await page.locator('#movie-releases table')
      .waitFor({ state: 'attached', timeout: 20000 })
      .then(() => true)
      .catch(() => false);

    expect(
      hasTable,
      `no seeded movie with releases at /movie/${SEEDED_MOVIE_ID} -- the seed ` +
      'did not run: scripts/seed_e2e_data.py --data_dir=<dir> before starting the server',
    ).toBe(true);
  });

  test('the release table exposes sortable headers with aria-sort', async ({ page }) => {
    const releases = page.locator('#movie-releases');
    const sortable = releases.locator('th[aria-sort]');
    expect(await sortable.count()).toBeGreaterThan(0);
    // Nothing is sorted until the user asks (B1: defaults reproduce the old page).
    for (const th of await sortable.all()) {
      expect(await th.getAttribute('aria-sort')).toBe('none');
    }
  });

  test('sorting by size marks that column and reorders the rows', async ({ page }) => {
    const releases = page.locator('#movie-releases');
    expect(
      await releases.locator('tbody tr').count(),
      'need at least two releases to observe a reorder -- scripts/seed_e2e_data.py ' +
      'seeds 6, so this indicates the seed did not run rather than a routine skip',
    ).toBeGreaterThanOrEqual(2);

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
    const select = releases.locator('#rel-source');
    const options = await select.locator('option').allInnerTexts();
    expect(
      options.some(o => /NZB/i.test(o)) && options.some(o => /Torrent/i.test(o)),
      'this movie has releases from only one source -- scripts/seed_e2e_data.py ' +
      'seeds both NZB and torrent releases, so this indicates the seed did not ' +
      'run rather than a routine skip',
    ).toBe(true);

    await select.selectOption('nzb');

    // Column order is fixed by SORT_COLUMNS in releases_view.py: Name,
    // Quality, Score, Size, Seeders, Source, Status, Age -- Source is the
    // 6th <td>.
    //
    // The assertion RETRIES until the htmx swap lands. `expect(#movie-releases)
    // .toBeVisible()` used to stand in for that wait, but the container is the
    // swap TARGET and is already visible, so it passed instantly against the
    // pre-filter table and the source check then read stale rows. It only
    // surfaced once the suite ran in parallel and the server got slower —
    // i.e. the wait had never worked, it just usually won the race.
    await expect(async () => {
      const sources = await page
        .locator('#movie-releases tbody tr td:nth-child(6)')
        .allInnerTexts();
      expect(sources.length, 'filter returned no rows at all').toBeGreaterThan(0);
      for (const source of sources) {
        expect(source.trim()).toMatch(/NZB/i);
      }
      // Bounded: an unbounded toPass() is capped only by the 30s test timeout,
      // so a genuine regression takes 30s to report instead of failing fast.
    }).toPass({ timeout: 5000 });
  });

  test('the result count is announced in a live region', async ({ page }) => {
    const releases = page.locator('#movie-releases');
    // The live region lives OUTSIDE #movie-releases now (a sibling,
    // #release-count-announcer): it must, since hx-swap="outerHTML" destroys
    // and recreates #movie-releases wholesale on every filter/sort change,
    // and a screen reader does not announce a brand-new node -- only a
    // mutation to one already registered in the accessibility tree.
    await expect(page.locator('#release-count-announcer')).toContainText(/release/);
  });

  test('Download and Skip still work after a swap (B13)', async ({ page }) => {
    const releases = page.locator('#movie-releases');
    const actionButton = releases.locator('button', { hasText: /Download|Skip/ }).first();
    expect(
      await actionButton.count(),
      'no release in this data has an actionable status (available/ignored) -- ' +
      'scripts/seed_e2e_data.py seeds both, so this indicates the seed did not run, ' +
      'not a routine skip',
    ).toBeGreaterThan(0);

    await releases.getByRole('link', { name: /^Score/ }).click();
    await expect(page.locator('#movie-releases')).toBeVisible();

    // A real check that Alpine rebound releaseDownloader() on the freshly
    // swapped-in #movie-releases node -- NOT the old `toBeEnabled()`
    // assertion, which checked for an HTML `disabled` attribute that is
    // never actually present: the buttons use `:disabled="downloading[...]"`,
    // an Alpine binding, so that assertion passed whether or not Alpine ever
    // reinitialised the component. Alpine.$data() reads the reactive scope
    // Alpine itself attached to the element; if the component failed to
    // rebind, this is undefined rather than the releaseDownloader() shape.
    // Do NOT click Download/Skip themselves -- that would snatch or ignore
    // a real release in whatever library the suite happens to run against.
    const rebound = await page.evaluate(() => {
      const el = document.querySelector('#movie-releases');
      const alpine = (window as any).Alpine; // global exposed by the vendored script, not a module import
      const data = alpine && el ? alpine.$data(el) : null;
      return !!data && typeof data.downloading === 'object' && typeof data.ignoring === 'object';
    });
    expect(rebound, 'Alpine.$data(#movie-releases) should be the rebound releaseDownloader() scope').toBe(true);
  });

  test('a bookmarked filtered URL renders filtered on first paint (B8)', async ({ page }) => {
    const releases = page.locator('#movie-releases');
    const url = new URL(page.url());
    url.searchParams.set('sort', 'size');
    url.searchParams.set('dir', 'desc');

    await page.goto(url.toString());
    await expect(page.locator('#movie-releases table')).toBeVisible({ timeout: 10000 });
    await expect(page.locator('#movie-releases th[aria-sort="descending"]')).toHaveCount(1);
  });
});
