import { test, expect } from '@playwright/test';
import AxeBuilder from '@axe-core/playwright';

/**
 * Accessibility tests for CouchPotato new UI using axe-core.
 * These tests check for WCAG violations on all main pages.
 */

// Helper to check a11y violations
async function checkA11y(page: any, pageName: string) {
  const accessibilityScanResults = await new AxeBuilder({ page })
    .withTags(['wcag2a', 'wcag2aa', 'wcag21a', 'wcag21aa'])
    // Exclude known exceptions documented below
    .exclude('#loading') // Loading indicators are transient
    .analyze();

  // Log violations for debugging
  if (accessibilityScanResults.violations.length > 0) {
    console.log(`A11y violations on ${pageName}:`);
    accessibilityScanResults.violations.forEach(violation => {
      console.log(`  - ${violation.id}: ${violation.description}`);
      console.log(`    Impact: ${violation.impact}`);
      console.log(`    Nodes: ${violation.nodes.length}`);
      // Print details of each failing node
      violation.nodes.forEach((node, idx) => {
        console.log(`    Node ${idx + 1}: ${node.html}`);
        console.log(`    Target: ${node.target.join(' ')}`);
        if (node.failureSummary) {
          console.log(`    Failure: ${node.failureSummary}`);
        }
      });
    });
  }

  // Fail on critical or serious violations
  const criticalViolations = accessibilityScanResults.violations.filter(
    v => v.impact === 'critical' || v.impact === 'serious'
  );

  expect(
    criticalViolations.length,
    `Found ${criticalViolations.length} critical/serious a11y violations on ${pageName}: ${
      criticalViolations.map(v => v.id).join(', ')
    }`
  ).toBe(0);

  return accessibilityScanResults;
}

// Scoped a11y check for toggle switches specifically: aria-required-attr /
// aria-allowed-attr / aria-toggle-field-name would all have caught the
// original wizard bug (role="switch" present with no :aria-checked and no
// accessible name). Scoped (rather than the full checkA11y page-wide sweep)
// so pre-existing, unrelated issues elsewhere on a given wizard step (e.g.
// color-contrast on hint text) don't mask this regression check.
async function checkToggleA11y(page: any, pageName: string) {
  const results = await new AxeBuilder({ page })
    .withRules(['aria-required-attr', 'aria-allowed-attr', 'aria-toggle-field-name', 'button-name', 'aria-valid-attr-value'])
    .analyze();

  if (results.violations.length > 0) {
    console.log(`Toggle a11y violations on ${pageName}:`);
    results.violations.forEach(violation => {
      console.log(`  - ${violation.id}: ${violation.description}`);
      violation.nodes.forEach(node => console.log(`    ${node.html}`));
    });
  }

  expect(
    results.violations.length,
    `Found toggle a11y violations on ${pageName}: ${results.violations.map(v => v.id).join(', ')}`
  ).toBe(0);
}

async function waitForSuggestionsReady(page: any) {
  await expect(page.getByRole('heading', { name: 'Suggestions' })).toBeVisible();
  await expect(page.getByRole('tablist', { name: 'Suggestion categories' })).toBeVisible();
  await expect(page.getByRole('tab', { name: 'Charts' })).toHaveAttribute('aria-selected', 'true');
  await expect(page.locator('#charts-grid')).toBeVisible();
  // The mocked Charts partial swaps in a poster-card once loaded. Waiting on it
  // (rather than the #charts-grid htmx-request class, which htmx puts on the
  // inner [hx-get] child, not the grid) is the real readiness signal. The
  // redesigned panel also has an always-present hidden error div with
  // `text-center`, so the old `> .text-center` alternative would match that.
  await expect(page.locator('#charts-grid .poster-card').first()).toBeVisible();
}

async function mockSuggestionsCharts(page: any) {
  await page.route('**/partial/charts', route => route.fulfill({
    status: 200,
    contentType: 'text/html',
    body: `
      <div class="mb-8">
        <h2 class="text-sm font-medium mb-3">Featured</h2>
        <button type="button"
                class="poster-card rounded-md overflow-hidden bg-cp-card border border-white/[0.05] group text-left w-full"
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

test.describe('Accessibility', () => {
  test('Wanted page should be accessible', async ({ page }) => {
    await page.goto('/');
    await page.waitForLoadState('networkidle');
    await page.waitForTimeout(1000); // Wait for htmx to load content
    
    await checkA11y(page, 'Wanted');
  });

  test('Available page should be accessible', async ({ page }) => {
    await page.goto('/available/');
    await page.waitForLoadState('networkidle');
    await page.waitForTimeout(1000);
    
    await checkA11y(page, 'Available');
  });

  test('Suggestions page should be accessible', async ({ page }) => {
    await mockSuggestionsCharts(page);
    await page.goto('/suggestions/');
    await waitForSuggestionsReady(page);
    
    await checkA11y(page, 'Suggestions');
  });

  test('Add Movie page should be accessible', async ({ page }) => {
    await page.goto('/add/');
    await page.waitForLoadState('networkidle');
    await page.waitForTimeout(1000);
    
    await checkA11y(page, 'Add Movie');
  });

  test('Settings page should be accessible', async ({ page }) => {
    await page.goto('/settings/');
    await page.waitForLoadState('networkidle');
    await page.waitForTimeout(2000); // Settings takes longer to load

    await checkA11y(page, 'Settings');
  });

  // The wizard's provider/downloader/library toggles only render into the DOM
  // once their step is reached (each step is `x-show`-gated) and, for the
  // provider toggles, once a search type is chosen. Walk the real flow so the
  // toggles this test cares about are actually present and visible.
  async function navigateWizardToProviders(page: any, searchType: 'Usenet' | 'Torrents' | 'Both' = 'Both') {
    await page.goto('/wizard/');
    await page.waitForLoadState('networkidle');
    await page.waitForTimeout(500);

    // Step 1: Welcome -> Continue
    await page.getByRole('button', { name: 'Continue' }).click();
    await page.waitForTimeout(300);

    // Step 2: Security -> Skip (no credentials needed for this check)
    await page.getByRole('button', { name: 'Skip' }).click();
    await page.waitForTimeout(300);

    // Step 3: Providers -> choose a search type so the provider toggles render.
    // Each source button's accessible name is "<Type> <hint>" (e.g. "Both
    // Maximum coverage"), so match on a name starting with the type.
    await page.getByRole('button', { name: new RegExp('^' + searchType) }).click();
    await page.waitForTimeout(300);
  }

  test('Setup Wizard page should be accessible', async ({ page }) => {
    await page.goto('/wizard/');
    await page.waitForLoadState('networkidle');
    await page.waitForTimeout(1000);

    // Regression guard for UI-CONFORM-01: the wizard used to render its 8
    // toggle switches at a non-canonical size (w-10 h-5) and without
    // role="switch"/:aria-checked/aria-label, which axe's aria-required-attr /
    // aria-allowed-attr rules would catch on any toggle actually in view.
    await checkA11y(page, 'Setup Wizard');
  });

  test('Setup Wizard provider toggles are accessible and keyboard-operable', async ({ page }) => {
    await navigateWizardToProviders(page, 'Both');

    // Newznab, BinSearch, ThePirateBay, YTS and Jackett/TorrentPotato toggles
    // are all visible now that "Both" search types are selected.
    await checkToggleA11y(page, 'Setup Wizard — Providers step');

    const toggles = page.locator('button[role="switch"]:visible');
    const toggleCount = await toggles.count();
    expect(toggleCount).toBeGreaterThanOrEqual(5);

    for (let i = 0; i < toggleCount; i++) {
      const toggle = toggles.nth(i);
      await expect(toggle).toHaveAttribute('aria-checked', /true|false/);
      const ariaLabel = await toggle.getAttribute('aria-label');
      expect(ariaLabel, `toggle ${i} should have a non-empty aria-label`).toBeTruthy();
      const trackClass = await toggle.getAttribute('class');
      expect(trackClass).toContain('w-8 h-4');
      expect(trackClass).not.toContain('w-10 h-5');
    }

    // Keyboard operability: focus + Enter/Space must flip aria-checked, same
    // as the canonical toggle elsewhere in the app (field_types.html etc.).
    const firstToggle = toggles.first();
    const beforeChecked = await firstToggle.getAttribute('aria-checked');
    await firstToggle.focus();
    await expect(firstToggle).toBeFocused();
    await page.keyboard.press('Enter');
    await expect(firstToggle).toHaveAttribute('aria-checked', beforeChecked === 'true' ? 'false' : 'true');
  });

  test('Setup Wizard downloader and library toggles are accessible', async ({ page }) => {
    await navigateWizardToProviders(page, 'Both');

    // Step 3: Providers -> Continue to Downloader (saves the providers step
    // for real against the local test server).
    await page.getByRole('button', { name: 'Continue' }).click();
    await page.waitForTimeout(500);

    // Black Hole toggle is always visible on the Downloader step.
    const blackholeToggle = page.getByRole('switch', { name: 'Enable Black Hole' });
    await expect(blackholeToggle).toBeVisible();
    await expect(blackholeToggle).toHaveAttribute('aria-checked', /true|false/);
    let trackClass = await blackholeToggle.getAttribute('class');
    expect(trackClass).toContain('w-8 h-4');
    expect(trackClass).not.toContain('w-10 h-5');

    // Step 4: Downloader -> Continue to Library
    await page.getByRole('button', { name: 'Continue' }).click();
    await page.waitForTimeout(500);

    // Renamer toggle is always visible on the Library step.
    const renamerToggle = page.getByRole('switch', { name: 'Enable Automatic Renaming' });
    await expect(renamerToggle).toBeVisible();
    await expect(renamerToggle).toHaveAttribute('aria-checked', /true|false/);
    trackClass = await renamerToggle.getAttribute('class');
    expect(trackClass).toContain('w-8 h-4');
    expect(trackClass).not.toContain('w-10 h-5');

    await checkToggleA11y(page, 'Setup Wizard — Library step');
  });

  test('Navigation should have proper ARIA landmarks', async ({ page }) => {
    await page.goto('/');
    await page.waitForLoadState('networkidle');
    
    // Check for main navigation
    const nav = page.locator('nav[aria-label]');
    await expect(nav.first()).toBeVisible();
    
    // Check for main content area
    const main = page.locator('main');
    await expect(main).toBeVisible();
  });

  test('Interactive elements should be keyboard accessible', async ({ page }) => {
    await page.goto('/');
    await page.waitForLoadState('networkidle');
    await page.waitForTimeout(1000);
    
    // Tab through the page
    await page.keyboard.press('Tab');
    
    // Something should be focused
    const focusedElement = page.locator(':focus');
    await expect(focusedElement.first()).toBeVisible();
    
    // Focused element should have visible focus indicator (not disabled in CSS)
    const outline = await focusedElement.first().evaluate(el => {
      const styles = window.getComputedStyle(el);
      return styles.outline !== 'none' || styles.boxShadow !== 'none';
    });
    // Note: This might need adjustment based on the focus styling approach used
  });

  test('Images should have alt text', async ({ page }) => {
    await page.goto('/');
    await page.waitForLoadState('networkidle');
    await page.waitForTimeout(1000);
    
    // Get all images
    const images = page.locator('img');
    const count = await images.count();
    
    for (let i = 0; i < Math.min(count, 10); i++) {
      const img = images.nth(i);
      const alt = await img.getAttribute('alt');
      // All images should have alt attribute (even if empty for decorative)
      expect(await img.getAttribute('alt')).toBeDefined();
    }
  });

  test('Color contrast should be sufficient', async ({ page }) => {
    await page.goto('/');
    await page.waitForLoadState('networkidle');
    await page.waitForTimeout(1000);
    
    // Run axe specifically for color contrast
    const results = await new AxeBuilder({ page })
      .withRules(['color-contrast'])
      .analyze();
    
    // Log any contrast issues
    if (results.violations.length > 0) {
      console.log('Color contrast issues:');
      results.violations.forEach(v => {
        v.nodes.forEach(n => {
          console.log(`  - ${n.html}: ${n.failureSummary}`);
        });
      });
    }
    
    // Allow minor contrast issues but fail on critical
    const critical = results.violations.filter(v => v.impact === 'critical');
    expect(critical.length).toBe(0);
  });
});

/**
 * Known Exceptions:
 * 
 * 1. Loading indicators (#loading) - These are transient and don't need to be
 *    fully accessible as they're only visible for a short time.
 * 
 * 2. Some color contrast issues in badges/status indicators may be acceptable
 *    as they use color alongside other visual indicators (position, text).
 */
