import { expect, Page } from '@playwright/test';

/**
 * Shared E2E helpers.
 *
 * These lived as near-identical copies inside individual specs, which is how the
 * good version and the broken version coexisted: `accessibility.a11y.spec.ts`
 * mocked the slow charts route and waited on concrete elements, while
 * `interactions.e2e.spec.ts` waited on `networkidle` and timed out. One copy, so
 * a fix reaches every caller.
 */

/**
 * Wait until a page is usable.
 *
 * DO NOT use `page.waitForLoadState('networkidle')` here. The suggestions page
 * lazy-loads `/partial/charts` via htmx, which fetches external chart providers
 * (Blu-ray.com and friends) — measured at ~85s to complete against the real
 * services. `networkidle` waits for 500ms of network silence, so it never
 * settles inside Playwright's 30s timeout.
 *
 * That is also why those tests passed in CI and failed locally: CI cannot reach
 * the providers, so the request fails fast and the network goes quiet. The
 * tests were green for the wrong reason — the check was never really running.
 *
 * The app itself is fine: charts are progressively loaded, so the page renders
 * and is interactive long before they arrive. Waiting for the main landmark is
 * both faster and a truer readiness signal than waiting for the network.
 */
export async function waitForPageReady(page: Page): Promise<void> {
  await page.waitForLoadState('domcontentloaded');
  await expect(page.locator('#main-content')).toBeVisible();
}

/**
 * Stub `/partial/charts` with a representative poster card.
 *
 * Any test that visits `/suggestions/` (or navigates through it) should call
 * this first. Without it the test depends on third-party chart providers being
 * reachable and fast — an external dependency in a supposedly hermetic suite,
 * and the difference between an 85s page and an instant one.
 *
 * FIDELITY MATTERS HERE more than for most stubs: `accessibility.a11y.spec.ts`
 * runs axe against this markup, so an a11y-relevant attribute the stub omits is
 * an a11y-relevant attribute nothing checks. It previously dropped `data-imdb`
 * (which charts.html's movie-skipped listener selects on) and the focus-ring
 * classes — i.e. axe was asserting a visible focus indicator that the stub did
 * not have. `tests/unit/test_charts_template.py` pins these against the real
 * template.
 */
export async function mockSuggestionsCharts(page: Page): Promise<void> {
  await page.route('**/partial/charts', route => route.fulfill({
    status: 200,
    contentType: 'text/html',
    body: `
      <div class="mb-8">
        <h2 class="text-sm font-medium mb-3">Featured</h2>
        <button type="button"
                class="poster-card rounded-md overflow-hidden bg-cp-card border border-white/[0.05] group text-left w-full cursor-pointer hover:border-white/[0.12] transition-colors focus:outline-none focus:ring-2 focus:ring-cp-accent/50 focus:ring-offset-2 focus:ring-offset-cp-bg"
                data-imdb="tt0137523"
                aria-label="View details for Example Movie (2026)">
          <div class="relative aspect-[2/3] overflow-hidden bg-white">
            <div class="absolute top-2 left-2">
              <span class="px-1.5 py-0.5 rounded text-[9px] font-medium lowercase bg-cp-warning text-black backdrop-blur-sm">chart</span>
            </div>
          </div>
          <div class="p-2.5">
            <h3 class="font-medium text-xs truncate">Example Movie</h3>
            <p class="text-cp-muted text-[10px] mt-0.5 font-light">2026</p>
          </div>
        </button>
      </div>
    `,
  }));
}

/**
 * Stub `/partial/search` with two representative result cards.
 *
 * Without this, `search.spec.ts` types "The Matrix" and waits on a live TMDB
 * lookup — an external dependency in a suite that is supposed to be hermetic.
 * It made the search tests slow, and under parallel workers the concurrent
 * lookups were slow enough to blow the 10s expectations (3 failures).
 *
 * The markup mirrors `couchpotato/ui/templates/partials/search_results.html`.
 * `tests/unit/test_search_results_template.py` renders that real template and
 * asserts the same structural contract the specs assert here, so this mock
 * cannot quietly drift into testing a shape the app no longer produces.
 */
export async function mockMovieSearch(page: Page): Promise<void> {
  const card = (title: string, year: string, imdb: string) => `
    <div class="rounded-md overflow-hidden bg-cp-card border border-white/[0.05] group"
         data-imdb="${imdb}" x-data="{ added: false, adding: false, profile_id: '' }">
      <button type="button" aria-label="View details for ${title} (${year})">
        <div class="relative aspect-[2/3] overflow-hidden bg-cp-surface"></div>
      </button>
      <div class="p-2.5">
        <h3 class="font-medium text-xs truncate" title="${title}">${title}</h3>
        <p class="text-cp-muted text-[10px] mt-0.5 font-light">${year}</p>
        <p class="text-cp-muted text-[9px] truncate">
          <a href="https://www.imdb.com/title/${imdb}/" target="_blank" rel="noopener">${imdb}</a>
        </p>
        <label for="profile-${imdb}" class="sr-only">Quality profile for ${title}</label>
        <select id="profile-${imdb}" x-model="profile_id"
                class="w-full mt-2 bg-cp-bg border border-white/[0.06] rounded-md px-2 py-1 text-[10px]">
          <option value="">Loading profiles…</option>
        </select>
        <button class="w-full mt-2 py-1.5 rounded-md text-[10px] font-medium">
          <span x-show="!added && !adding">Add</span>
          <span x-show="adding">Adding…</span>
          <span x-show="added">✓ Added</span>
        </button>
      </div>
    </div>`;

  await page.route('**/partial/search*', route => route.fulfill({
    status: 200,
    contentType: 'text/html',
    body: `
      <div class="grid grid-cols-2 sm:grid-cols-3 md:grid-cols-4 lg:grid-cols-5 xl:grid-cols-6 gap-3">
        ${card('The Matrix', '1999', 'tt0133093')}
        ${card('The Matrix Reloaded', '2003', 'tt0234215')}
      </div>`,
  }));
}

/**
 * Wait for the suggestions page to be fully rendered.
 *
 * Requires `mockSuggestionsCharts` to have been installed, since it waits for a
 * poster card to have been swapped into `#charts-grid` — the real readiness
 * signal. (Not the `htmx-request` class: htmx puts that on the inner `[hx-get]`
 * child rather than the grid. Not `> .text-center` either: the redesigned panel
 * has an always-present hidden error div with that class.)
 */
export async function waitForSuggestionsReady(page: Page): Promise<void> {
  await expect(page.getByRole('heading', { name: 'Suggestions' })).toBeVisible();
  await expect(page.getByRole('tablist', { name: 'Suggestion categories' })).toBeVisible();
  await expect(page.getByRole('tab', { name: 'Charts' })).toHaveAttribute('aria-selected', 'true');
  await expect(page.locator('#charts-grid')).toBeVisible();
  await expect(page.locator('#charts-grid .poster-card').first()).toBeVisible();
}

/**
 * Fail the test if the page logged a JS error that indicates a real fault.
 *
 * Kept synchronous on purpose. As an `async` function it was called without
 * `await` at 19 sites; Playwright does still surface the rejection (verified),
 * but a synchronous assertion attributes the failure to the right test with no
 * reliance on unhandled-rejection plumbing.
 */
export function checkNoErrors(errors: string[]): void {
  const criticalErrors = errors.filter(e =>
    e.includes('TypeError') ||
    e.includes('ReferenceError') ||
    e.includes('bytes-like object')
  );
  expect(criticalErrors, `Console errors: ${criticalErrors.join(' | ')}`).toHaveLength(0);
}
