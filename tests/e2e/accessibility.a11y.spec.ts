import { test, expect } from './fixtures';
import AxeBuilder from '@axe-core/playwright';
import { mockSuggestionsCharts, waitForSuggestionsReady } from './helpers';

/**
 * Accessibility tests for CouchPotato new UI using axe-core.
 * These tests check for WCAG violations on all main pages.
 */

// Helper to check a11y violations
async function checkA11y(page: any, pageName: string) {
  const accessibilityScanResults = await new AxeBuilder({ page })
    // wcag22aa added (T1.4b/AC-A11Y-9): the project standard is WCAG 2.2 AA,
    // and without this tag 2.5.8 (target-size) and 2.4.11
    // (focus-not-obscured) were never evaluated at all.
    .withTags(['wcag2a', 'wcag2aa', 'wcag21a', 'wcag21aa', 'wcag22aa'])
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

  // Fail on ANY WCAG-tagged violation, not just critical/serious.
  //
  // T1.4b/AC-A11Y-8: this used to filter to `impact === 'critical' ||
  // 'serious'` before asserting, which meant a `moderate`-impact violation
  // (e.g. many WCAG 2.2 `target-size` findings, or `color-contrast` at
  // certain ratios) could never fail this function -- and it backs 5 of the
  // 18 tests in this file (Wanted, Available, Add Movie, Movie Detail, Setup
  // Wizard directly, plus Suggestions and Settings). The identical bug, one
  // notch tighter (`impact === 'critical'` alone), lived in the standalone
  // "Color contrast should be sufficient" test further down -- already fixed.
  const violations = accessibilityScanResults.violations;

  expect(
    violations.length,
    `Found ${violations.length} a11y violations on ${pageName}: ${
      violations.map(v => v.id).join(', ')
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

  /*
   * T1.4b/AC-A11Y-10: every page-level checkA11y sweep above runs in the
   * LIGHT theme. With no localStorage seeded, base.html's own init leaves
   * `document.documentElement` without the `light` class removed --
   * measured: `classList.contains('light')` is true by default -- so dark
   * mode has never been scanned page-wide. The toast contrast test below is
   * the only place dark theme gets exercised at all, and that is exactly the
   * blind spot that let the dark success toast ship at 3.30:1 (see the
   * comment above that test). Cover one plain content page (Wanted) and one
   * form-bearing page (Settings) in dark, following the same
   * addInitScript-before-goto pattern the toast test uses.
   */
  test('Wanted and Settings pages should be accessible in the dark theme', async ({ page }) => {
    await page.addInitScript((t) => {
      localStorage.setItem('cp-theme', t);
    }, 'dark');

    await page.goto('/');
    await page.waitForLoadState('networkidle');
    await page.waitForTimeout(1000); // Wait for htmx to load content

    // Pin that dark theme really took effect -- load-bearing, not decorative:
    // a broken theme pipeline must red this test loudly rather than silently
    // scanning the light theme under a "dark theme" test name.
    await expect
      .poll(() => page.evaluate(() => document.documentElement.classList.contains('light')))
      .toBe(false);

    await checkA11y(page, 'Wanted (dark theme)');

    await page.goto('/settings/');
    await page.waitForLoadState('networkidle');
    await page.waitForTimeout(2000); // Settings takes longer to load

    await expect
      .poll(() => page.evaluate(() => document.documentElement.classList.contains('light')))
      .toBe(false);

    await checkA11y(page, 'Settings (dark theme)');
  });

  // FEAT-007 Part B: the release list's filter/sort controls (B12). Follows
  // movie-detail.spec.ts's own pattern for reaching the detail page.
  // scripts/seed_e2e_data.py seeds a movie with releases (wired into
  // playwright.config.ts's webServer for local runs, and into the
  // ui-e2e-tests/accessibility CI jobs) so this normally runs rather than
  // skipping; the skips below stay so this suite still works against an
  // unseeded instance, but say plainly that the seed didn't run rather than
  // looking like a routine, expected skip.
  test('Movie Detail page with a release filter applied should be accessible', async ({ page }) => {
    // Navigate straight to the seeded movie, like release_controls.spec.ts
    // does, rather than clicking whichever poster card happens to be first.
    // "First card" is not stable across a full run: another spec clicks
    // "Mark as Done", which moves the seeded movie out of the Wanted view
    // that '/' renders, and search.spec.ts adds real movies that have no
    // releases -- so this test would land on the wrong movie and skip with
    // "this movie has no releases". It only passed at all because
    // 'accessibility' happens to sort first alphabetically; that is luck, not
    // a design. A fixed id removes the dependency on both ordering and
    // library state.
    await page.goto('/movie/e2e-seed-movie-001');

    // The release table arrives via detail.html's hx-trigger="load" swap, so
    // wait for the swapped-in content itself -- never for #movie-detail-container,
    // which is in the static shell and so resolves instantly, waiting for
    // nothing.
    const releasesLoaded = await page.locator('#movie-releases table')
      .waitFor({ state: 'attached', timeout: 15000 })
      .then(() => true)
      .catch(() => false);

    /*
     * FAIL, don't skip (AC-A11Y-1, same pattern as movie-detail.spec.ts:55).
     *
     * This used to be test.skip(!releasesLoaded, ...). A skip here reads as
     * "the a11y suite is clean" while the one case in this file that
     * actually scans a filtered, data-bearing release table never ran at
     * all -- a broken seed silently deleted coverage rather than failing
     * the run that lost it.
     */
    expect(
      releasesLoaded,
      'no seeded movie with releases at /movie/e2e-seed-movie-001 -- either ' +
      'the seed did not run (scripts/seed_e2e_data.py --data_dir=<dir> before ' +
      'starting the server), or the detail partial took over 15s to load',
    ).toBe(true);

    const releases = page.locator('#movie-releases');

    // Apply a sort so the active-column aria-sort state is exercised too.
    await releases.getByRole('link', { name: /^Score/ }).click();
    await expect(page.locator('#movie-releases')).toBeVisible();

    await checkA11y(page, 'Movie Detail (filtered release list)');
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

/**
   * Is there a focus indicator a sighted keyboard user can actually see?
   *
   * ONE definition, used by both the tab-sweep and the named-control tests.
   * They were written separately and each ended up with the hole the other had
   * closed, which review demonstrated by driving both against Chromium-shaped
   * values:
   *
   *   focus:ring-transparent   named-control PASSED, sweep failed
   *   focus:ring-0 (coloured)  named-control PASSED, sweep failed
   *   permanent shadow-md      named-control failed, sweep PASSED
   *
   * Both properties are needed, so both are required here:
   *
   *  - VISIBLE: an outline or shadow with a colour whose alpha is not 0 and
   *    geometry that is not all zeros. Tailwind's `outline-none` compiles to
   *    `outline: 2px solid transparent`, and `ring-0`/`ring-transparent` are
   *    the shadow-side spellings of the same nothing.
   *  - CHANGED ON FOCUS: Tailwind composes every ring/shadow utility as a
   *    permanent, non-'none' box-shadow, so an element carrying `shadow-md`
   *    reports a real shadow with real geometry whether it is focused or not.
   *    An indicator that does not appear on focus is decoration.
   *
   * Runs inside page.evaluate, so it is stringified: keep it dependency-free.
   */
  const FOCUS_INDICATOR_PROBE = (el: Element) => {
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
      !colour ||
      colour === 'transparent' ||
      /rgba\(\s*[\d.]+\s*,\s*[\d.]+\s*,\s*[\d.]+\s*,\s*0\s*\)/.test(colour);
    const shadowHasSubstance = (shadow: string) =>
      shadow !== 'none' &&
      shadow !== '' &&
      // Split on commas that are not inside rgb()/rgba().
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
      focused.outlineStyle !== 'none' &&
      parseFloat(focused.outlineWidth || '0') > 0 &&
      !invisible(focused.outlineColor);
    const shadowVisible =
      shadowHasSubstance(focused.boxShadow) && focused.boxShadow !== blurred.boxShadow;
    const changedOnFocus =
      focused.outlineStyle !== blurred.outlineStyle ||
      focused.outlineWidth !== blurred.outlineWidth ||
      focused.outlineColor !== blurred.outlineColor ||
      focused.boxShadow !== blurred.boxShadow;
  
    return {
      ...focused,
      blurredBoxShadow: blurred.boxShadow,
      changedOnFocus,
      visible: (outlineVisible || shadowVisible) && changedOnFocus,
    };
  };

  /**
   * Named controls that must show a focus ring, checked directly rather than
   * hoped for by tabbing.
   *
   * The test below presses Tab exactly once from a fresh `/`, which lands
   * deterministically on the skip link and nothing else -- so it guarded
   * base.html's global `:focus-visible` rule and not one control in the app.
   * Every per-component override, which is where the defects are, was outside
   * its reach: both of these carried `focus:outline-none`, i.e.
   * `outline: 2px solid TRANSPARENT`, and had no visible keyboard focus at all.
   */
  //
  // SCOPE, stated rather than left to be discovered: text inputs only, and
  // two of them out of ~100 `focus:outline-none` sites across 17 templates.
  // The probe focuses PROGRAMMATICALLY with no prior keyboard event, and
  // base.html has `:focus:not(:focus-visible) { outline: none }`, so these
  // pass only because Chromium always matches `:focus-visible` on a text
  // field. Adding a button or a link here -- movie_releases.html has several
  // -- would report "no visible focus indicator" for a compliant control.
  // Tab to such a control instead of calling focus().
  //
  // Known remaining limits of the probe itself, none reachable in these
  // templates today: `visible` ANDs across properties, so a permanently
  // visible outline plus any shadow change on focus passes; alpha is only
  // detected in legacy `rgba()`, not `oklab()`/`color()`; `outline-offset` is
  // never read, so a ring pushed off-screen passes; and sub-pixel widths or
  // near-zero alphas count as visible.
  const FOCUSABLE_CONTROLS = [
    { path: '/', selector: '#filter-movies', what: 'the Wanted filter input' },
    { path: '/add/', selector: 'input[placeholder*="search" i]', what: 'the Add-movie search input' },
  ];

  for (const { path, selector, what } of FOCUSABLE_CONTROLS) {
    test(`${what} has a visible focus indicator`, async ({ page }) => {
      await page.goto(path);
      const control = page.locator(selector).first();
      await expect(control, `${what} did not render at ${path}`).toBeVisible();
      const indicator = await control.evaluate(FOCUS_INDICATOR_PROBE);

      expect(
        indicator.visible,
        `${what} has no visible focus indicator (WCAG 2.2 AA 2.4.7). Computed ` +
        `focused: outline ${indicator.outlineStyle} ${indicator.outlineWidth} ` +
        `${indicator.outlineColor}, box-shadow ${indicator.boxShadow}; ` +
        `unfocused box-shadow ${indicator.blurredBoxShadow}; ` +
        `changedOnFocus=${indicator.changedOnFocus}. Note that Tailwind's ` +
        `\`outline-none\`, \`ring-0\` and \`ring-transparent\` all compile to ` +
        `something that is present but invisible, and a permanent ` +
        `\`shadow-*\` is decoration rather than a focus indicator.`,
      ).toBe(true);
    });
  }

  test('Interactive elements should be keyboard accessible', async ({ page }) => {
    await page.goto('/');
    await page.waitForLoadState('networkidle');
    await page.waitForTimeout(1000);

    // Tab through the page
    await page.keyboard.press('Tab');

    // Something should be focused
    const focusedElement = page.locator(':focus');
    await expect(focusedElement.first()).toBeVisible();

    // Focused element must have a visible focus indicator (WCAG 2.4.7).
    // Same single definition as the named-control tests above: previously
    // these two predicates were written separately and each accepted what
    // the other rejected.
    const sweep = await focusedElement.first().evaluate(FOCUS_INDICATOR_PROBE);
    const hasVisibleFocusIndicator = sweep.visible;

    expect(
      hasVisibleFocusIndicator,
      `the first Tab-focused element has no visible focus indicator ` +
      `(WCAG 2.4.7). Computed focused: outline ${sweep.outlineStyle} ` +
      `${sweep.outlineWidth} ${sweep.outlineColor}, box-shadow ` +
      `${sweep.boxShadow}; unfocused box-shadow ${sweep.blurredBoxShadow}; ` +
      `changedOnFocus=${sweep.changedOnFocus}.`,
    ).toBe(true);
  });

  test('Images should have alt text', async ({ page }) => {
    await page.goto('/');
    await page.waitForLoadState('networkidle');
    await page.waitForTimeout(1000);

    // Get all images
    const images = page.locator('img');
    const count = await images.count();
    // Verified: `expect(null).toBeDefined()` PASSES, and `getAttribute`
    // returns `null` for a missing attribute -- so the old
    // `expect(await img.getAttribute('alt')).toBeDefined()` could not fail
    // even for an <img> with no `alt` at all. It also silently asserted
    // nothing whenever `count` was 0. Both fixed: a real image count first,
    // then a real type check on the attribute (a string, including '' for
    // decorative images, not null).
    expect(count, 'expected at least one <img> on the page to check alt text on').toBeGreaterThan(0);

    for (let i = 0; i < Math.min(count, 10); i++) {
      const img = images.nth(i);
      const alt = await img.getAttribute('alt');
      // All images should have an alt attribute (even if empty for decorative)
      expect(typeof alt, `image ${i} (src="${await img.getAttribute('src')}") has no alt attribute`).toBe('string');
    }
  });

  /*
   * The contrast test above loads '/' and never renders a toast, so it could
   * not have caught the two failing toast types even once the `critical`
   * filter was fixed. FEAT-008 routes both success and error outcomes through
   * this component, so every type is rendered here, in BOTH themes, and
   * checked with axe.
   *
   * Measured before the fix: error 3.60:1 in light (the `:root.light
   * .text-white` override re-pointed `text-white` at the dark body colour on
   * top of bg-red-600), success 3.30:1 in dark. Both are real 1.4.3 failures.
   */
  for (const theme of ['dark', 'light'] as const) {
    test(`Toasts of every type meet contrast in the ${theme} theme`, async ({ page }) => {
      /*
       * Seed localStorage BEFORE navigation. Toggling the `light` class after
       * load does not work: base.html's own init reads `cp-theme` from
       * localStorage and re-applies it, silently undoing the toggle -- so the
       * "dark" case actually ran in the light theme and could not observe the
       * dark-only success-toast failure at all.
       */
      await page.addInitScript((t) => {
        localStorage.setItem('cp-theme', t);
      }, theme);
      await page.goto('/');
      await page.waitForLoadState('domcontentloaded');

      // Pin that the theme really took effect, so a future regression in the
      // theme plumbing surfaces here rather than quietly making this vacuous.
      await expect
        .poll(() => page.evaluate(() => document.documentElement.classList.contains('light')))
        .toBe(theme === 'light');

      // All three at once: they stack, so one axe pass covers every variant.
      await page.evaluate(() => {
        for (const type of ['success', 'error', 'info']) {
          window.dispatchEvent(new CustomEvent('cp-toast', {
            detail: { message: `A ${type} message long enough to read`, type, duration: 60000 },
          }));
        }
      });

      // Scoped to the toast region's own wrapper: the loading skeleton
      // (#loading) also carries role="status", so a bare [role="status"]
      // matched 4 elements and the count assertion failed for the wrong reason.
      const region = '[data-testid="toast-region"]';
      await expect(
        page.locator(`${region} [data-testid="toast"]`),
      ).toHaveCount(3, { timeout: 5000 });

      /*
       * Measure the ratio directly rather than relying on axe alone.
       *
       * axe's node selection turned out not to be dependable for this
       * component: with a deliberately-failing success toast (bg-green-600 +
       * white, 3.30:1) it reported one violation in a standalone probe and
       * ZERO from inside this test, under conditions verified identical
       * (theme asserted dark, computed colours asserted white-on-green). A
       * guard whose detection depends on that is not a guard, so the ratio is
       * computed here from the two colours actually rendered. axe still runs
       * below as a second opinion.
       */
      const measured = await page.$$eval(`${region} [data-testid="toast"]`, (els) => {
        const rgb = (s: string) => (s.match(/\d+(\.\d+)?/g) || []).slice(0, 3).map(Number);
        const lum = (c: number[]) => {
          const [r, g, b] = c.map((v) => {
            const s = v / 255;
            return s <= 0.04045 ? s / 12.92 : Math.pow((s + 0.055) / 1.055, 2.4);
          });
          return 0.2126 * r + 0.7152 * g + 0.0722 * b;
        };
        return els.map((el) => {
          const label = el.querySelector('span') as HTMLElement;
          const bg = lum(rgb(getComputedStyle(el).backgroundColor));
          const fg = lum(rgb(getComputedStyle(label).color));
          const ratio = (Math.max(bg, fg) + 0.05) / (Math.min(bg, fg) + 0.05);
          return {
            cls: (el.className.match(/bg-\S+/) || ['?'])[0],
            bg: getComputedStyle(el).backgroundColor,
            fg: getComputedStyle(label).color,
            ratio: Math.round(ratio * 100) / 100,
          };
        });
      });

      // The toast label is 14px / weight 500 -- not "large text", so WCAG
      // 1.4.3 AA requires 4.5:1, not 3:1.
      const failing = measured.filter((m) => m.ratio < 4.5);
      expect(
        failing,
        `${theme} theme toast contrast below 4.5:1 — ${JSON.stringify(measured)}`,
      ).toEqual([]);

      const results = await new AxeBuilder({ page })
        .include(region)
        .withRules(['color-contrast'])
        .analyze();

      const detail = results.violations
        .flatMap(v => v.nodes.map(n => `${n.html} — ${n.failureSummary}`))
        .join('\n');
      expect(results.violations.length, `${theme} theme toast contrast:\n${detail}`).toBe(0);
    });
  }


  /*
   * Toast messages must land in a live region that ALREADY EXISTS.
   *
   * Two earlier shapes failed this: aria-live on the toast wrapper (which
   * nested an error toast's role="alert" inside a polite region), and
   * aria-live on each toast (which made the live element itself ephemeral --
   * a screen reader announces a mutation to an element already in the
   * accessibility tree, not a brand-new node; the same rule
   * tests/unit/test_releases_partial_route.py pins for the release-count
   * announcer). Neither could be caught by asserting on roles alone, which is
   * all the suite did.
   */
  test('toast messages are announced through a persistent live region', async ({ page }) => {
    await page.goto('/');
    await page.waitForLoadState('domcontentloaded');

    const polite = page.locator('[data-testid="toast-announcer-polite"]');
    const assertive = page.locator('[data-testid="toast-announcer-assertive"]');

    // Present BEFORE any toast exists — this is the whole point.
    await expect(polite).toBeAttached();
    await expect(assertive).toBeAttached();
    await expect(polite).toHaveAttribute('aria-live', 'polite');
    await expect(assertive).toHaveAttribute('aria-live', 'assertive');
    await expect(polite).toBeEmpty();

    await page.evaluate(() => {
      window.dispatchEvent(new CustomEvent('cp-toast', {
        detail: { message: 'Found 3 new releases', type: 'success' },
      }));
    });
    await expect(polite).toHaveText('Found 3 new releases');

    // Errors go to the assertive region so an actionable failure interrupts.
    await page.evaluate(() => {
      window.dispatchEvent(new CustomEvent('cp-toast', {
        detail: { message: 'No enabled downloader', type: 'error' },
      }));
    });
    await expect(assertive).toHaveText('No enabled downloader');

    // The visual stack must not also be announced, or every message is
    // spoken twice -- but it must NOT be aria-hidden either, because it
    // contains a focusable Dismiss button and aria-hidden does not remove
    // anything from the tab order (axe aria-hidden-focus, WCAG 4.1.2).
    // Silence comes from carrying no role and no live region at all.
    const region = page.locator('[data-testid="toast-region"]');
    await expect(region).not.toHaveAttribute('aria-hidden', 'true');
    const toast = region.locator('[data-testid="toast"]').first();
    await expect(toast).not.toHaveAttribute('role', /.+/);
    await expect(toast).not.toHaveAttribute('aria-live', /.+/);

    // And prove it with axe, which is what would catch the aria-hidden-focus
    // regression: scan with toasts actually on screen.
    const results = await new AxeBuilder({ page })
      .include('[data-testid="toast-region"]')
      .withRules(['aria-hidden-focus'])
      .analyze();
    expect(
      results.violations.map(v => v.nodes.map(n => n.html).join('; ')),
      'a focusable control is hidden from assistive tech',
    ).toEqual([]);
  });


  test('a repeated identical toast is announced every time', async ({ page }) => {
    /*
     * Assigning the same string to the announcement state is a no-op under
     * Alpine's reactivity, so x-text never mutates and the live region stays
     * silent. Measured before the fix: two identical messages produced ONE
     * live-region mutation.
     *
     * Reachable in one click-click: press "Search for releases" twice with no
     * downloader enabled and the same error toast renders twice. The previous
     * shape (a new node per toast) mutated on every message including repeats,
     * so this was a regression on the very axis the persistent region was
     * meant to improve.
     */
    await page.goto('/');
    await page.waitForLoadState('domcontentloaded');
    const polite = page.locator('[data-testid="toast-announcer-polite"]');
    await expect(polite).toBeAttached();

    await page.evaluate(() => {
      (window as any).__liveMutations = 0;
      const el = document.querySelector('[data-testid="toast-announcer-polite"]')!;
      new MutationObserver(() => { (window as any).__liveMutations++; })
        .observe(el, { childList: true, characterData: true, subtree: true });
    });

    const say = () => page.evaluate(() => {
      window.dispatchEvent(new CustomEvent('cp-toast', {
        detail: { message: 'No new releases', type: 'success' },
      }));
    });

    await say();
    await expect(polite).toHaveText('No new releases');
    await say();
    // Two identical announcements must produce more than one mutation, or the
    // second is never spoken.
    await expect
      .poll(() => page.evaluate(() => (window as any).__liveMutations), { timeout: 5000 })
      .toBeGreaterThan(1);
    await expect(polite).toHaveText('No new releases');
  });


  test('the restore-to-wanted control has no accessibility violations', async ({ page }) => {
    /*
     * PR review: this CI-gated suite only ever visits `e2e-seed-movie-001`, but
     * the restore control renders only for a done/downloaded movie -- and the
     * restore E2E tests deliberately use a SEPARATE fixture
     * (`e2e-seed-movie-002`) so they do not mutate the movie this suite depends
     * on. So the picker's markup was structurally never present when axe ran
     * anywhere in this file. It was reviewed by hand, never scanned in CI.
     */
    const DESTRUCTIVE_MOVIE_ID = 'e2e-seed-movie-002';
    await page.goto(`/movie/${DESTRUCTIVE_MOVIE_ID}`);
    await page.locator('#movie-releases').waitFor({ state: 'attached', timeout: 20000 });

    const trigger = page.locator('[data-testid="restore-to-wanted"]');
    if ((await trigger.count()) === 0) { // vacuous-guard-ok: primes the shared FEAT-008 fixture into 'done' status if an earlier spec has not already -- suite ordering, not something this test controls; the block's own assertions (Mark as Done becomes visible, then the restore trigger) are real either way.
      const markDone = page.getByRole('button', { name: 'Mark as Done', exact: true });
      await expect(markDone).toBeVisible({ timeout: 5000 });
      await markDone.click();
      await page.waitForLoadState('networkidle');
      await expect(trigger).toBeVisible({ timeout: 10000 });
    }

    // Open the picker so the select, its label and both buttons are present.
    await trigger.click();
    await expect(page.locator('select[id^="restore-profile-"]')).toBeVisible({ timeout: 5000 });

    const results = await new AxeBuilder({ page })
      .include('#movie-detail-container')
      .withTags(['wcag2a', 'wcag2aa', 'wcag21a', 'wcag21aa', 'wcag22aa'])
      .analyze();
    const detail = results.violations
      .flatMap((v) => v.nodes.map((n) => `${v.id}: ${n.html}`))
      .join('\n');
    expect(results.violations.length, `restore control violations:\n${detail}`).toBe(0);
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
    
    /*
     * Fail on ANY color-contrast violation, not just `critical`.
     *
     * This used to be `violations.filter(v => v.impact === 'critical')`, and
     * axe reports color-contrast with impact `serious` — never `critical`. So
     * a test whose entire purpose is contrast, and which runs axe with
     * `.withRules(['color-contrast'])` so it can report nothing else, could
     * not fail. It was green while the error toast rendered at 3.60:1 in the
     * light theme and the success toast at 3.30:1 in dark.
     *
     * The filter is kept (rather than asserting on violations.length) purely
     * so the failure message names the rule.
     */
    const contrast = results.violations.filter(v => v.id === 'color-contrast');
    const detail = contrast
      .flatMap(v => v.nodes.map(n => `${n.html} — ${n.failureSummary}`))
      .join('\n');
    expect(contrast.length, `WCAG 1.4.3 contrast failures:\n${detail}`).toBe(0);
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
