import { test, expect } from './fixtures';
import { Page } from '@playwright/test';

/**
 * Comprehensive interaction tests for CouchPotato.
 * Tests every user-interactable element across all pages.
 * 
 * Coverage:
 * - Navigation (sidebar, mobile menu)
 * - Wanted page (filters, search, movie cards, bulk actions)
 * - Available route redirect behavior
 * - Add Movie page (search, add button, profile selection)
 * - Movie Detail page (refresh, trailer, delete, releases)
 * - Suggestions page (charts, add/skip buttons)
 * - Settings page (all tabs, inputs, toggles, test buttons)
 * - Theme toggle
 */

// Helpers are shared (tests/e2e/helpers.ts) rather than copied per spec: the
// duplicate that used to live here waited on `networkidle`, which never settles
// on the suggestions page because /partial/charts fetches external providers.
// See helpers.ts for the full explanation.
import {
  checkNoErrors as sharedCheckNoErrors,
  mockSuggestionsCharts,
  waitForPageReady,
} from './helpers';

// Thin shim so the 19 existing call sites keep their `(page, errors)` signature.
// It DELEGATES rather than reimplementing: a second copy of the filter list is
// exactly the duplication that let a good helper and a broken one coexist in
// this suite. `page` is unused.
function checkNoErrors(_page: Page, errors: string[]) {
  sharedCheckNoErrors(errors);
}

test.describe('Navigation', () => {
  test('sidebar links navigate correctly', async ({ page }) => {
    const errors: string[] = [];
    page.on('console', msg => { if (msg.type() === 'error') errors.push(msg.text()); });

    // This walk includes Suggestions, whose charts partial hits third-party
    // providers. Stub it so the test measures navigation, not the internet.
    await mockSuggestionsCharts(page);

    await page.goto('/');
    await waitForPageReady(page);

    // Test each nav link
    const navLinks = [
      { href: '/wanted/', text: 'Wanted' },
      { href: '/suggestions/', text: 'Suggestions' },
      { href: '/add/', text: 'Add Movie' },
      { href: '/settings/', text: 'Settings' },
    ];

    for (const link of navLinks) {
      await page.click(`a[href*="${link.href}"]`);
      await waitForPageReady(page);
      expect(page.url()).toContain(link.href);
    }

    checkNoErrors(page, errors);
  });

  // 'sidebar collapse button works' used to live here, asserting nothing
  // (`if (await collapseBtn.isVisible()) { click; click; }`, no expect at
  // all). navigation.spec.ts:75 ("sidebar should collapse and expand")
  // covers the identical behaviour AND is the suite's only assertion of the
  // control's accessible name, so it is the one kept (T1.4, decided
  // 2026-08-03) rather than repairing a second copy of the same coverage.

  test('theme toggle switches modes', async ({ page }) => {
    await page.goto('/');
    await waitForPageReady(page);

    // The `chromium` project runs Desktop Chrome and never the mobile
    // viewport the sidebar (and this button, inside it) is hidden on, so the
    // old `if (await themeBtn.isVisible())` guard could never be false here
    // -- it just hid a possible zero-assertion run.
    const themeBtn = page.locator('button:has-text("Light mode"), button:has-text("Dark mode")');
    await expect(themeBtn).toBeVisible();

    const initialText = await themeBtn.textContent();
    await themeBtn.click();
    await page.waitForTimeout(300);
    const newText = await themeBtn.textContent();
    expect(newText).not.toBe(initialText);
    // Toggle back
    await themeBtn.click();
  });

  test('mobile menu works on small viewport', async ({ page }) => {
    await page.setViewportSize({ width: 375, height: 667 });
    await page.goto('/');
    await waitForPageReady(page);

    // The mobile top bar (base.html) is `lg:hidden`, so it is CSS-guaranteed
    // visible at this test's own 375px viewport -- the old
    // `if (await menuBtn.isVisible())` guard could never be false here.
    const menuBtn = page.locator('button[aria-label*="menu"], button[aria-label*="navigation"]');
    await expect(menuBtn).toBeVisible();

    await menuBtn.click();
    await page.waitForTimeout(300);
    // Mobile menu should be visible
    const mobileNav = page.locator('[role="menu"], #mobile-menu');
    await expect(mobileNav).toBeVisible();
  });
});

test.describe('Wanted Page', () => {
  test('filter buttons work', async ({ page }) => {
    const errors: string[] = [];
    page.on('console', msg => { if (msg.type() === 'error') errors.push(msg.text()); });

    await page.goto('/wanted/');
    await waitForPageReady(page);

    // Click each filter button
    const filterBtns = page.locator('button:has-text("All"), button:has-text("Wanted"), button:has-text("Available")');
    const count = await filterBtns.count();
    
    for (let i = 0; i < count; i++) {
      await filterBtns.nth(i).click();
      await page.waitForTimeout(300);
    }

    checkNoErrors(page, errors);
  });

  test('text filter input works', async ({ page }) => {
    await page.goto('/wanted/');
    await waitForPageReady(page);

    // The filter input is static chrome in wanted.html, rendered
    // unconditionally regardless of what is in the library -- the old
    // `if (await filterInput.isVisible())` guard could never be false, and
    // the test asserted nothing at all either way.
    const filterInput = page.locator('input[placeholder*="Filter"]');
    await expect(filterInput).toBeVisible();

    // Baseline, not a hardcoded count: scripts/seed_e2e_data.py's Wanted-page
    // movie is e2e-seed-movie-004 (WANTED_MOVIE_ID, T1.9) -- the only seeded
    // movie with genuinely zero releases, so it is the only one
    // has_releases=False actually matches. e2e-seed-movie-001/-002 both carry
    // releases and now correctly live on Available instead (T1.9 fixed
    // Release.withStatus dropping with_doc, which had made has_releases
    // inert and let those two show up here too). The "Add Movie" spec can add
    // a second wanted-eligible movie mid-run, so "exactly 1 card" is still
    // not reliable here even though "at least 1" is. A real filter effect
    // (not just "the input accepted text") is the actual behaviour this
    // test's name promises.
    //
    // waitForPageReady only proves the page SHELL rendered, not that
    // #movie-grid's own async `hx-trigger="load"` fetch has landed --
    // `.count()` does not auto-retry the way `toBeVisible()` does, so reading
    // it immediately raced the swap and measured 0 once (verified: the DB
    // still had an 'active' movie at that instant). Wait for a real card
    // first, generously: this is the same htmx-load race
    // interactions.e2e.spec.ts's "Available Page" test documents elsewhere
    // in this file (measured ~1 failure in 4 full runs before that fix).
    const visibleCards = page.locator('#movie-grid .poster-card:visible');
    await expect(
      visibleCards.first(),
      'no movie card in the Wanted grid -- did scripts/seed_e2e_data.py run?',
    ).toBeVisible({ timeout: 10000 });
    const baseline = await visibleCards.count();

    // No seeded title contains this, so this must hide every card.
    await filterInput.fill('zzz-does-not-match-any-seeded-title');
    await page.waitForTimeout(500);
    await expect(visibleCards).toHaveCount(0);

    await filterInput.fill('');
    await page.waitForTimeout(500);
    await expect(visibleCards).toHaveCount(baseline);
  });

  test('select all button works', async ({ page }) => {
    await page.goto('/wanted/');
    await waitForPageReady(page);

    // Static chrome, always rendered on the Wanted page -- the old
    // `if (await selectAllBtn.isVisible())` guard could never be false, and
    // the test asserted nothing at all either way.
    const selectAllBtn = page.locator('button:has-text("Select All")');
    await expect(selectAllBtn).toBeVisible();

    await selectAllBtn.click();
    // toggleSelectAll() (wanted.html) flips `allSelected`, which the button's
    // own label is bound to -- the real, observable effect of the click.
    await expect(selectAllBtn).toContainText('Deselect All');
  });

  test('movie card hover actions visible', async ({ page }) => {
    await page.goto('/wanted/');
    await waitForPageReady(page);

    // scripts/seed_e2e_data.py always seeds two active movies, and the
    // Wanted grid's default filter is "All" (wanted.html), so a card is
    // guaranteed here -- the old `if (await movieCard.isVisible())` guard
    // could never be false, and even inside it nothing was ever asserted.
    const movieCard = page.locator('.poster-card, [data-movie-id]').first();
    await expect(movieCard).toBeVisible({ timeout: 10000 });

    // The refresh button (movie_cards.html) is `opacity-0 group-hover:opacity-100`
    // -- present but transparent until hover, so `toBeVisible()` alone cannot
    // tell "shown on hover" from "always there"; the opacity IS the behaviour.
    const refreshBtn = movieCard.getByRole('button', { name: /refresh metadata/i });
    await expect(refreshBtn).toHaveCSS('opacity', '0');
    await movieCard.hover();
    await expect(refreshBtn).toHaveCSS('opacity', '1');
  });

  test('movie card click navigates to detail', async ({ page }) => {
    await page.goto('/wanted/');
    await waitForPageReady(page);

    // Same guarantee as above: the seeded library always has a card here.
    const movieLink = page.locator('a[href*="/movie/"]').first();
    await expect(movieLink).toBeVisible({ timeout: 10000 });

    await movieLink.click();
    await waitForPageReady(page);
    expect(page.url()).toContain('/movie/');
  });
});

test.describe('Available Page', () => {
  test('route redirects to wanted page available filter', async ({ page }) => {
    const errors: string[] = [];
    page.on('console', msg => { if (msg.type() === 'error') errors.push(msg.text()); });

    await page.goto('/available/');
    await waitForPageReady(page);

    // /available now redirects to the wanted page with available filter.
    await expect(page).toHaveURL(/\/wanted\/?\?filter=available/);
    // toBeAttached, not toBeVisible: this asserts the redirect landed on the
    // grid page, not that any movie matches. With `filter=available` every
    // card can legitimately be display:none, leaving the grid zero-height —
    // which Playwright reports as hidden. That made this fail intermittently
    // depending on what earlier specs left in the shared library (measured:
    // 1 failure in 4 full runs, passing in isolation every time).
    await expect(page.locator('#movie-grid')).toBeAttached();
    checkNoErrors(page, errors);
  });
});

test.describe('Add Movie Page', () => {
  test('search input accepts text and shows results', async ({ page }) => {
    const errors: string[] = [];
    page.on('console', msg => { if (msg.type() === 'error') errors.push(msg.text()); });

    await page.goto('/add/');
    await waitForPageReady(page);

    const searchInput = page.locator('input[placeholder*="Search"]');
    await expect(searchInput).toBeVisible();
    
    await searchInput.fill('Matrix');
    await page.waitForTimeout(2000); // Wait for debounced search
    await waitForPageReady(page);

    // Should show some results or loading state
    checkNoErrors(page, errors);
  });

  test('add button on search result works', async ({ page }) => {
    const errors: string[] = [];
    page.on('console', msg => { if (msg.type() === 'error') errors.push(msg.text()); });

    await page.goto('/add/');
    await waitForPageReady(page);

    const searchInput = page.locator('input[placeholder*="Search"]');
    await searchInput.fill('Inception');
    await page.waitForTimeout(2000);
    await waitForPageReady(page);

    const addBtn = page.locator('button:has-text("Add")').first();
    if (await addBtn.isVisible({ timeout: 5000 })) { // vacuous-guard-ok: this search is real/unmocked (unlike search.spec.ts), so a result -- and its Add button -- is not guaranteed; checkNoErrors below is the assertion that always runs.
      await addBtn.click();
      await page.waitForTimeout(2000);
      
      // Should not show TV show error
      const tvError = await page.locator('text=/TV show/i').isVisible().catch(() => false);
      expect(tvError).toBe(false);
    }

    checkNoErrors(page, errors);
  });
});

test.describe('Movie Detail Page', () => {
  test.beforeEach(async ({ page }) => {
    // The seeded library always has a movie in the Wanted grid (see the
    // Wanted Page tests above), so this navigation is guaranteed rather than
    // best-effort -- fail loudly if it is not, instead of leaving every test
    // below to silently no-op against '/wanted/'.
    await page.goto('/wanted/');
    await waitForPageReady(page);

    const movieLink = page.locator('a[href*="/movie/"]').first();
    await expect(
      movieLink,
      'no movie card in the Wanted grid -- did scripts/seed_e2e_data.py run?',
    ).toBeVisible({ timeout: 10000 });
    await movieLink.click();
    await waitForPageReady(page);
  });

  test('refresh button works', async ({ page }) => {
    const errors: string[] = [];
    page.on('console', msg => { if (msg.type() === 'error') errors.push(msg.text()); });

    if (page.url().includes('/movie/')) {
      const refreshBtn = page.locator('button:has-text("Refresh")');
      if (await refreshBtn.isVisible({ timeout: 3000 })) {
        await refreshBtn.click();
        await page.waitForTimeout(2000);
      }
    }

    checkNoErrors(page, errors);
  });

  test('trailer button works', async ({ page }) => {
    const errors: string[] = [];
    page.on('console', msg => { if (msg.type() === 'error') errors.push(msg.text()); });

    if (page.url().includes('/movie/')) {
      // Use specific selector for the movie detail page trailer button (has x-ref="trailerBtn")
      const trailerBtn = page.locator('button[x-ref="trailerBtn"]:has-text("Trailer")');
      if (await trailerBtn.isVisible({ timeout: 3000 })) {
        await trailerBtn.click();
        await page.waitForTimeout(2000);
        
        // Modal should open or loading should show
        const modal = page.locator('[role="dialog"]');
        const loading = page.locator('text=/Loading/i');
        
        // Either is acceptable
      }
    }

    checkNoErrors(page, errors);
  });

  test('delete button shows confirmation', async ({ page }) => {
    // beforeEach guarantees a movie detail page, and Delete is unconditional
    // on it (movie-detail.spec.ts's "should show Delete button on detail
    // page" pins that) -- so both the URL and the isVisible() guards this
    // used to have could never be false, and NOTHING was ever asserted even
    // when they passed: a dialog could be replaced with a silent no-op and
    // this test would still pass.
    let dialogMessage: string | null = null;
    let dialogType: string | null = null;
    page.once('dialog', async (dialog) => {
      dialogMessage = dialog.message();
      dialogType = dialog.type();
      await dialog.dismiss();
    });

    const deleteBtn = page.getByRole('button', { name: /delete/i });
    await expect(deleteBtn).toBeVisible({ timeout: 3000 });
    await deleteBtn.click();

    await expect.poll(() => dialogType).not.toBeNull();
    expect(dialogType, 'Delete must ask for confirmation, not act immediately').toBe('confirm');
    expect(dialogMessage, 'the confirm dialog carried no message').toBeTruthy();
    // Dismissed, not accepted: the movie must still be here afterwards.
    await expect(page).toHaveURL(/.*movie\/.+/);
  });
});

test.describe('Suggestions Page', () => {
  test('tabs switch content', async ({ page }) => {
    const errors: string[] = [];
    page.on('console', msg => { if (msg.type() === 'error') errors.push(msg.text()); });

    await mockSuggestionsCharts(page);
    await page.goto('/suggestions/');
    await waitForPageReady(page);

    const tabs = page.locator('[role="tab"]');
    const tabCount = await tabs.count();

    for (let i = 0; i < tabCount; i++) {
      await tabs.nth(i).click();
      await page.waitForTimeout(500);
    }

    checkNoErrors(page, errors);
  });

  test('add/skip buttons on suggestions work', async ({ page }) => {
    const errors: string[] = [];
    page.on('console', msg => { if (msg.type() === 'error') errors.push(msg.text()); });

    // Root cause (AC-QA-40): the Skip button lives inside the movie-info
    // modal (movie_info_modal.html), not on the page -- it only opens on
    // click, and the OLD mockSuggestionsCharts stub card had no click
    // handler at all, so `button:has-text("Skip")` could never exist and
    // this test asserted only `checkNoErrors` after burning 5s waiting for
    // it. helpers.ts's stub now carries the same `onclick` charts.html
    // itself ships, so the card is real enough to open the modal.
    //
    // The modal's own open() does a real `fetch(.../search?q=...)`, and
    // Skip does a real `fetch(.../charts.ignore/...)` -- both stubbed here
    // so this stays hermetic rather than depending on TMDB.
    await page.route('**/search?q=tt0137523', route => route.fulfill({
      status: 200,
      contentType: 'application/json',
      body: JSON.stringify({
        success: true,
        movie: [{ imdb: 'tt0137523', titles: ['Example Movie'], year: 2026 }],
      }),
    }));
    let skipRequested = false;
    await page.route('**/charts.ignore/**', route => {
      skipRequested = true;
      return route.fulfill({ status: 200, contentType: 'application/json', body: '{"success": true}' });
    });

    await mockSuggestionsCharts(page);
    await page.goto('/suggestions/');
    await waitForPageReady(page);

    const card = page.locator('.poster-card[data-imdb="tt0137523"]');
    await expect(card).toBeVisible();
    await card.click();

    // Scoped by #movie-modal-close (movie_info_modal.html), not by accessible
    // name: the modal's aria-label is `movie?.title || 'Movie details'`, so
    // it flips from "Movie details" to the loaded title -- a race against a
    // name-based locator. It also is NOT the trailer modal, which is always
    // in the DOM too as global chrome.
    const modal = page.locator('[role="dialog"]:has(#movie-modal-close)');
    await expect(modal).toBeVisible();

    const skipBtn = modal.getByRole('button', { name: 'Skip' });
    await expect(skipBtn).toBeVisible({ timeout: 5000 });
    await skipBtn.click();

    await expect.poll(() => skipRequested, 'Skip never called charts.ignore').toBe(true);
    // skipMovie() (movie_info_modal.html) closes the modal and removes the
    // card from the grid on success -- both are the real, observable effect
    // of a working Skip, not just "the button existed".
    await expect(modal).toBeHidden();
    await expect(card).toHaveCount(0);

    checkNoErrors(page, errors);
  });
});

test.describe('Settings Page', () => {
  test('all tabs are clickable', async ({ page }) => {
    const errors: string[] = [];
    page.on('console', msg => { if (msg.type() === 'error') errors.push(msg.text()); });

    await page.goto('/settings/');
    await waitForPageReady(page);

    const tabs = page.locator('[role="tab"]');
    const tabCount = await tabs.count();

    for (let i = 0; i < tabCount; i++) {
      await tabs.nth(i).click();
      await page.waitForTimeout(500);
    }

    checkNoErrors(page, errors);
  });

  test('text inputs accept values', async ({ page }) => {
    const errors: string[] = [];
    page.on('console', msg => { if (msg.type() === 'error') errors.push(msg.text()); });

    await page.goto('/settings/');
    await waitForPageReady(page);

    const textInput = page.locator('input[type="text"]').first();
    if (await textInput.isVisible()) {
      const original = await textInput.inputValue();
      await textInput.fill('test_value');
      await page.waitForTimeout(500);
      await textInput.fill(original);
    }

    checkNoErrors(page, errors);
  });

  test('checkboxes toggle', async ({ page }) => {
    const errors: string[] = [];
    page.on('console', msg => { if (msg.type() === 'error') errors.push(msg.text()); });

    await page.goto('/settings/');
    await waitForPageReady(page);

    const checkbox = page.locator('input[type="checkbox"]').first();
    if (await checkbox.isVisible()) {
      const original = await checkbox.isChecked();
      await checkbox.click();
      await page.waitForTimeout(500);
      if (await checkbox.isChecked() !== original) {
        await checkbox.click(); // Restore
      }
    }

    checkNoErrors(page, errors);
  });

  test('select dropdowns work', async ({ page }) => {
    const errors: string[] = [];
    page.on('console', msg => { if (msg.type() === 'error') errors.push(msg.text()); });

    await page.goto('/settings/');
    await waitForPageReady(page);

    const select = page.locator('select').first();
    if (await select.isVisible()) {
      await select.click();
      await page.waitForTimeout(300);
    }

    checkNoErrors(page, errors);
  });

  test('advanced toggle shows/hides options', async ({ page }) => {
    await page.goto('/settings/');
    await waitForPageReady(page);

    // header.html renders this unconditionally for any tab outside
    // customPanelTabs, and General (the default active tab) is not one of
    // them -- settings.spec.ts's own "should show Advanced toggle" test
    // already pins that it is always there. The old
    // `if (await advancedToggle.isVisible())` guard could never be false,
    // and nothing was asserted even when it passed.
    const advancedToggle = page.getByRole('switch', { name: /show advanced settings/i });
    await expect(advancedToggle).toBeVisible();
    await expect(advancedToggle).toHaveAttribute('aria-checked', 'false');

    await advancedToggle.click();
    await expect(advancedToggle).toHaveAttribute('aria-checked', 'true');

    await advancedToggle.click();
    await expect(advancedToggle).toHaveAttribute('aria-checked', 'false');
  });

  test('Jackett sync button works', async ({ page }) => {
    const errors: string[] = [];
    page.on('console', msg => { if (msg.type() === 'error') errors.push(msg.text()); });

    await page.goto('/settings/');
    await waitForPageReady(page);

    // Go to Searchers tab
    const searchersTab = page.locator('[role="tab"]:has-text("Searchers")');
    if (await searchersTab.isVisible()) {
      await searchersTab.click();
      await page.waitForTimeout(500);
    }

    const syncBtn = page.locator('button:has-text("Sync")');
    if (await syncBtn.isVisible({ timeout: 3000 })) {
      await syncBtn.click();
      await page.waitForTimeout(2000);
    }

    checkNoErrors(page, errors);
  });

  test('provider test buttons return valid response', async ({ page }) => {
    const errors: string[] = [];
    page.on('console', msg => { if (msg.type() === 'error') errors.push(msg.text()); });

    await page.goto('/settings/');
    await waitForPageReady(page);

    // Go to Searchers tab
    const searchersTab = page.locator('[role="tab"]:has-text("Searchers")');
    if (await searchersTab.isVisible()) {
      await searchersTab.click();
      await page.waitForTimeout(500);
    }

    // Click first visible Test button
    const testBtn = page.locator('button:has-text("Test")').first();
    if (await testBtn.isVisible({ timeout: 3000 })) { // vacuous-guard-ok: whether a Test button exists at all depends on which searcher providers are registered, which this test does not control; checkNoErrors below is the assertion that always runs.
      const responsePromise = page.waitForResponse(
        resp => resp.url().includes('test'),
        { timeout: 15000 }
      ).catch(() => null);

      await testBtn.click();
      const response = await responsePromise;

      if (response) {
        expect(response.status()).toBe(200);
      }
    }

    checkNoErrors(page, errors);
  });
});

test.describe('Logs Page', () => {
  test('logs page loads and shows content', async ({ page }) => {
    const errors: string[] = [];
    page.on('console', msg => { if (msg.type() === 'error') errors.push(msg.text()); });

    await page.goto('/settings/');
    await waitForPageReady(page);

    const logsTab = page.locator('[role="tab"]:has-text("Logs")');
    if (await logsTab.isVisible()) {
      await logsTab.click();
      await waitForPageReady(page);
      
      // Should show log content
      await page.waitForTimeout(1000);
    }

    checkNoErrors(page, errors);
  });

  test('log filter dropdown works', async ({ page }) => {
    await page.goto('/settings/');
    await waitForPageReady(page);

    // The Logs tab is static chrome (settings.spec.ts's "should show Logs
    // tab" pins it), and its level filter (logs_tab.html) always ships the
    // same 5 static <option>s -- neither guard here could ever be false, and
    // nothing was asserted even when both passed.
    const logsTab = page.locator('[role="tab"]:has-text("Logs")');
    await expect(logsTab).toBeVisible();
    await logsTab.click();
    await page.waitForTimeout(500);

    // #settings-log-level, not `select` .first(): Alpine's x-show hides
    // inactive tabs without removing them from the DOM, so "the first
    // <select> in document order" is not reliably "the one on this tab".
    const logFilter = page.locator('#settings-log-level');
    await expect(logFilter).toBeVisible();
    await expect(logFilter).toHaveValue('all');

    await logFilter.selectOption({ index: 1 });
    await expect(logFilter).toHaveValue('error');
  });

  test('clear logs button works', async ({ page }) => {
    const errors: string[] = [];
    page.on('console', msg => { if (msg.type() === 'error') errors.push(msg.text()); });

    await page.goto('/settings/');
    await waitForPageReady(page);

    const logsTab = page.locator('[role="tab"]:has-text("Logs")');
    if (await logsTab.isVisible()) {
      await logsTab.click();
      await page.waitForTimeout(500);

      const clearBtn = page.locator('button:has-text("Clear")');
      if (await clearBtn.isVisible()) {
        await clearBtn.click();
        await page.waitForTimeout(500);
      }
    }

    checkNoErrors(page, errors);
  });
});

test.describe('Wizard Page', () => {
  test('wizard page loads', async ({ page }) => {
    const errors: string[] = [];
    page.on('console', msg => { if (msg.type() === 'error') errors.push(msg.text()); });

    await page.goto('/wizard/');
    await waitForPageReady(page);

    // Should have wizard content
    await expect(page.locator('body')).toBeVisible();
    checkNoErrors(page, errors);
  });
});

test.describe('Keyboard Navigation', () => {
  test('can tab through interactive elements', async ({ page }) => {
    await page.goto('/');
    await waitForPageReady(page);

    // Tab through first 10 elements
    for (let i = 0; i < 10; i++) {
      await page.keyboard.press('Tab');
      await page.waitForTimeout(100);
    }

    // Something should be focused
    const focused = page.locator(':focus');
    await expect(focused.first()).toBeVisible();
  });

  test('escape closes modals', async ({ page }) => {
    // The trailer lookup (themoviedb.py's `movie.trailer`) hits a real
    // provider; without a video_id the modal never opens (movie_detail.html:
    // `if(videoId) { showTrailer = true; }`) and the old version of this test
    // would then "pass" on Escape doing nothing to a modal that was never
    // there. Stub it so the modal is guaranteed to open.
    await page.route(/movie\.trailer/, (route) => route.fulfill({
      status: 200,
      contentType: 'application/json',
      body: JSON.stringify({ success: true, video_id: 'dQw4w9WgXcQ' }),
    }));

    await page.goto('/wanted/');
    await waitForPageReady(page);

    // The seeded library always has a card here (see the Wanted Page tests).
    const movieLink = page.locator('a[href*="/movie/"]').first();
    await expect(movieLink).toBeVisible({ timeout: 10000 });
    await movieLink.click();
    await waitForPageReady(page);

    // Trailer is unconditional on the detail page (movie_detail.html has no
    // `{% if %}` around it) -- confirmed by movie-detail.spec.ts's own tests.
    const trailerBtn = page.locator('button[x-ref="trailerBtn"]:has-text("Trailer")');
    await expect(trailerBtn).toBeVisible({ timeout: 3000 });
    await trailerBtn.click();

    // Scoped by accessible name, not a bare `[role="dialog"]`: the movie-info
    // modal (movie_info_modal.html) is ALSO always in the DOM as global
    // chrome (x-show hidden, not absent), so an unscoped locator resolves to
    // two dialogs and Playwright's strict mode rejects it.
    const modal = page.getByRole('dialog', { name: 'Movie trailer' });
    await expect(modal).toBeVisible({ timeout: 5000 });

    await page.keyboard.press('Escape');

    await expect(modal).toBeHidden();
  });

  test('arrow keys navigate movie cards', async ({ page }) => {
    await page.goto('/wanted/');
    await waitForPageReady(page);

    // wanted.html's roving-focus handler moves focus among the <a> links
    // inside .poster-card (`#movie-grid .poster-card ... a`), not the card
    // wrapper -- the old test called `.focus()` on the wrapper div, which
    // has no tabindex, so the browser never actually moved focus there, the
    // keydown handler's `cards.indexOf(document.activeElement)` was always
    // -1, and it returned before doing anything. Nothing was asserted
    // either way.
    const cardLinks = page.locator('#movie-grid .poster-card a[href*="/movie/"]');

    // TWO cards are guaranteed, so this is unconditional. The seed creates
    // five 'active' movies (MOVIE_ID, DESTRUCTIVE_MOVIE_ID and the three
    // WANTED_MOVIE_IDS), and (T1.7a) none of them carries an already-'done'
    // release, so the app's own `app.load` -> searchAll restatus pass
    // (searcher.py) cannot self-promote them out of the grid. Only
    // e2e-seed-movie-002 can be driven to 'done' by another spec's "Mark as
    // Done", which still leaves four.
    //
    // This used to read `if (count > 1) { ...arrows... } else { ...one
    // assertion... }`, justified by a comment describing the OLD two-movie
    // fixture. The else branch had become dead -- and the hoisted `count`
    // also slipped past check_test_traps' Rule 6, which only knew the inline
    // `if (await x.count() ...)` shape, so the first code written after that
    // rule landed defeated it. Both are fixed: the rule now follows hoisted
    // names, and this is no longer conditional.
    await expect(
      cardLinks.first(),
      'no movie card in the Wanted grid -- did scripts/seed_e2e_data.py run?',
    ).toBeVisible({ timeout: 10000 });
    expect(
      await cardLinks.count(),
      'the arrow-key roving focus needs at least two cards to move between',
    ).toBeGreaterThan(1);

    const first = cardLinks.nth(0);
    const second = cardLinks.nth(1);
    await first.focus();
    await expect(first).toBeFocused();

    await page.keyboard.press('ArrowRight');
    await expect(second).toBeFocused();
    await page.keyboard.press('ArrowLeft');
    await expect(first).toBeFocused();
  });
});

test.describe('Error Handling', () => {
  test('404 page shows gracefully', async ({ page }) => {
    // NOT `expect(body).toBeVisible()`: <body> is visible for any response
    // with content, including a FastAPI JSON error payload or a rendered
    // Python traceback. The app could start serving a raw 500 with a stack
    // trace on every unknown path and that assertion would stay green -- in
    // the one test named for error handling.
    const response = await page.goto('/nonexistent-page-12345/');
    expect(response, 'no response at all for the unknown path').not.toBeNull();
    expect(
      response!.status(),
      'an unknown path must be a client error, not a server error',
    ).toBe(404);
    // Measured 2026-08-06: the app answers `{"detail":"Not Found"}` -- FastAPI's
    // default JSON handler, with no HTML and no navigation. That is a real gap
    // (a user who mistypes a URL gets a raw payload), recorded in
    // docs/technical-debt.md rather than fixed here: an HTML error page is new
    // product surface, not a safety net.
    //
    // What this test can and must pin is that the failure stays a clean,
    // client-side 404 and never becomes a server error with a Python traceback
    // in the response -- which is what the previous `expect(body).toBeVisible()`
    // would have sailed straight past.
    const body = await page.textContent('body');
    expect(body).not.toContain('Traceback (most recent call last)');
    expect(body).not.toContain('couchpotato/');
    expect(body).toContain('Not Found');
  });

  test('invalid movie ID handles gracefully', async ({ page }) => {
    const errors: string[] = [];
    page.on('console', msg => { if (msg.type() === 'error') errors.push(msg.text()); });

    await page.goto('/movie/invalid-id-12345/');
    await waitForPageReady(page);

    // Should not have critical JS errors
    checkNoErrors(page, errors);
  });
});
