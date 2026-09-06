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

// A11Y-001, AC-QA-4/AC-QA-5: scoped the same way checkToggleA11y is above,
// and for the same reason. The wizard's later steps have pre-existing,
// unrelated findings this task does not own (e.g. color-contrast on the
// search-type hint text, tracked separately, not in A11Y-001's scope) --
// a full checkA11y sweep on those steps would fail on THOSE and never
// exercise whether label association actually holds once axe can see the
// step at all. These rules are exactly the ones a missing or duplicated
// accessible name trips.
//
// Round 2 (both A11Y-001 reviews found the same three holes in this
// function, so it is rewritten rather than patched):
//
// A1 -- axe's `label` rule accepts a `placeholder` as an accessible name.
// 41 of the wizard's 63 fields carry one. Demonstrated: removing the `for`
// from wizard-renamer-from (Library step, which HAS a placeholder) left this
// whole function green; removing it from wizard-dl-qbittorrent-password (the
// one visited field with no placeholder) correctly went red. So axe alone
// had teeth on roughly one field in twenty. `assertFieldNamesAreReal` below
// is a DOM-level check that does not have that blind spot: it reads each
// visible field's actual label/aria text and rejects it when that text is
// merely the placeholder axe would have accepted.
//
// A2 -- `duplicate-id` and `duplicate-id-active` are BOTH `enabled: false`
// in the installed axe-core (4.13.0; verified via
// `axe._audit.rules.find(r => r.id === '...').enabled`), so neither can ever
// report anything here -- dropped. The real case this was meant to catch
// (two visible fields sharing an id) surfaces as `incomplete`, not
// `violations`, which the old code never inspected either way;
// `assertFieldNamesAreReal` checks id uniqueness directly instead.
// `select-name` and `aria-input-field-name` are also dropped: this page has
// zero `<select>` elements and zero roles either rule applies to (verified:
// `grep -c '<select' wizard.html` is 0, and no `role="textbox|combobox|
// searchbox|spinbutton|slider"` appears anywhere in it), so both rules
// described a check that could never run. `duplicate-id-aria` stays; it IS
// enabled and covers ARIA-referential duplicate ids axe's own way.
async function assertFieldNamesAreReal(page: any, pageName: string, minFields: number) {
  const scan = await page.evaluate(() => {
    const isVisible = (el: Element) => {
      const style = window.getComputedStyle(el);
      if (style.display === 'none' || style.visibility === 'hidden' ||
          parseFloat(style.opacity || '1') === 0) return false;
      const rect = (el as HTMLElement).getBoundingClientRect();
      return rect.width > 0 && rect.height > 0;
    };

    const fields = Array.from(document.querySelectorAll('input, textarea, select'))
      .filter((el) => (el as HTMLInputElement).type !== 'hidden')
      .filter(isVisible) as (HTMLInputElement | HTMLTextAreaElement | HTMLSelectElement)[];

    const idCounts = new Map<string, number>();
    for (const field of fields) {
      const id = field.getAttribute('id');
      if (id) idCounts.set(id, (idCounts.get(id) || 0) + 1);
    }

    const problems: string[] = [];

    for (const field of fields) {
      const id = field.getAttribute('id');
      const describe = () =>
        `<${field.tagName.toLowerCase()} id=${JSON.stringify(id)} ` +
        `x-model=${JSON.stringify(field.getAttribute('x-model'))} ` +
        `placeholder=${JSON.stringify((field as HTMLInputElement).placeholder || null)}>`;

      if (id && (idCounts.get(id) || 0) > 1) {
        problems.push(`${describe()}: id ${JSON.stringify(id)} is shared by ${idCounts.get(id)} visible elements (AC-A11Y-2)`);
      }

      const labelsFor = id ? Array.from(document.querySelectorAll(`label[for="${CSS.escape(id)}"]`)) : [];
      if (labelsFor.length > 1) {
        problems.push(`${describe()}: ${labelsFor.length} <label for> elements point at it, expected exactly 1`);
      }

      const ariaLabel = (field.getAttribute('aria-label') || '').trim();
      const labelledbyIds = (field.getAttribute('aria-labelledby') || '').trim();
      const labelledbyText = labelledbyIds
        ? labelledbyIds.split(/\s+/).map((refId) => document.getElementById(refId)?.textContent?.trim() || '').join(' ').trim()
        : '';

      const accessibleName = labelsFor.length === 1
        ? (labelsFor[0].textContent || '').trim()
        : (ariaLabel || labelledbyText);

      if (!accessibleName) {
        problems.push(`${describe()}: no label[for], aria-label or aria-labelledby resolved to a non-empty name`);
        continue;
      }

      // A1: the accessible name must not be merely the placeholder -- a
      // sighted user already sees the placeholder disappear on input, so a
      // screen reader user told only "Indexer URL (e.g. ...)" once typing
      // starts has lost the one cue they had.
      const placeholder = ((field as HTMLInputElement).placeholder || '').trim();
      if (placeholder && accessibleName === placeholder) {
        problems.push(`${describe()}: accessible name is identical to its own placeholder ("${placeholder}")`);
      }
    }

    return { problems, checked: fields.length };
  });

  // A5: a coverage floor. Without this, a scan that silently degrades to
  // examining zero fields (a broken selector, a step that failed to render,
  // a navigation click that landed on the wrong step) still reports zero
  // problems and reads as clean.
  expect(
    scan.checked,
    `${pageName}: expected at least ${minFields} visible field(s) to examine, found ${scan.checked} -- ` +
    `the scan may be looking at the wrong step, or nothing rendered`,
  ).toBeGreaterThanOrEqual(minFields);

  expect(
    scan.problems,
    `${pageName}: field accessible-name problem(s):\n${scan.problems.join('\n')}`,
  ).toEqual([]);
}

async function checkFieldNameA11y(page: any, pageName: string, minFields: number) {
  await assertFieldNamesAreReal(page, pageName, minFields);

  // axe as a second opinion for anything the DOM check above does not
  // cover -- e.g. aria-labelledby pointing at a missing id, which
  // assertFieldNamesAreReal treats as an empty name (still a real failure)
  // but axe's `label` rule names more precisely. `button-name` is included
  // here too: B3 added two icon-only buttons that only render once a
  // second Newznab entry / the directory browser is opened, both of which
  // this test now does before scanning the relevant step.
  const results = await new AxeBuilder({ page })
    .withRules(['label', 'duplicate-id-aria', 'button-name'])
    .analyze();

  if (results.violations.length > 0) {
    console.log(`Field-name a11y violations on ${pageName}:`);
    results.violations.forEach(violation => {
      console.log(`  - ${violation.id}: ${violation.description}`);
      violation.nodes.forEach(node => console.log(`    ${node.html}`));
    });
  }

  expect(
    results.violations.length,
    `Found field-name a11y violations on ${pageName}: ${results.violations.map(v => v.id).join(', ')}`
  ).toBe(0);
}

// A3: a step-arrival assertion. Blocking the wizard from advancing to the
// intended step must fail the corresponding scan loudly, rather than the
// scan silently re-examining whichever step is actually showing (every step
// but Welcome shares the same DOM structure enough that a stray field count
// alone would not always catch this). Checks BOTH the step's own heading and
// one field unique to that step, because `x-show` toggles the wrapping div's
// visibility, but a heading alone would still pass if the wizard were stuck
// one step behind (every step after Welcome renders inside a similarly
// shaped card).
async function assertWizardStepShowing(page: any, headingText: string | RegExp, knownFieldSelector: string) {
  await expect(page.getByRole('heading', { name: headingText })).toBeVisible();
  await expect(page.locator(knownFieldSelector).first()).toBeVisible();
}

test.describe('Accessibility', () => {
  test('Wanted page should be accessible', async ({ page }) => {
    await page.goto('/');
    await page.waitForLoadState('networkidle');
    // #movie-count starts empty and is only populated once the grid's htmx
    // load has swapped in and filterMovies() has run on it (wanted.html) --
    // real content-loaded signal rather than a guessed duration.
    await expect(page.locator('#movie-count')).not.toBeEmpty();

    await checkA11y(page, 'Wanted');
  });

  test('Available page should be accessible', async ({ page }) => {
    await page.goto('/available/');
    await page.waitForLoadState('networkidle');
    // /available/ redirects to /wanted?filter=available and renders the
    // same wanted.html grid, so the same readiness signal applies.
    await expect(page.locator('#movie-count')).not.toBeEmpty();

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
    // Nothing loads via htmx on this page until a search is typed, so the
    // real readiness signal is the search field the test's own scan
    // depends on being there.
    await expect(page.locator('#movie-search')).toBeVisible();

    await checkA11y(page, 'Add Movie');
  });

  test('Settings page should be accessible', async ({ page }) => {
    await page.goto('/settings/');
    await page.waitForLoadState('networkidle');
    // Settings loads via Alpine's own `loading` flag, not htmx -- the tabs
    // are gated behind `x-show="!loading"`, so waiting for them is the real
    // signal settings finished loading.
    await expect(page.getByRole('tablist', { name: 'Settings categories' })).toBeVisible();

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
    await expect(page.locator('#movie-count')).not.toBeEmpty();

    // Pin that dark theme really took effect -- load-bearing, not decorative:
    // a broken theme pipeline must red this test loudly rather than silently
    // scanning the light theme under a "dark theme" test name.
    await expect
      .poll(() => page.evaluate(() => document.documentElement.classList.contains('light')))
      .toBe(false);

    await checkA11y(page, 'Wanted (dark theme)');

    await page.goto('/settings/');
    await page.waitForLoadState('networkidle');
    await expect(page.getByRole('tablist', { name: 'Settings categories' })).toBeVisible();

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
    await expect(page.getByRole('button', { name: 'Continue' })).toBeVisible();

    // Step 1: Welcome -> Continue
    await page.getByRole('button', { name: 'Continue' }).click();
    await expect(page.getByRole('heading', { name: 'Server Security' })).toBeVisible();

    // Step 2: Security -> Skip (no credentials needed for this check)
    await page.getByRole('button', { name: 'Skip' }).click();
    await expect(page.getByRole('heading', { name: 'Where to Search' })).toBeVisible();

    // Step 3: Providers -> choose a search type so the provider toggles render.
    // Each source button's accessible name is "<Type> <hint>" (e.g. "Both
    // Maximum coverage"), so match on a name starting with the type.
    await page.getByRole('button', { name: new RegExp('^' + searchType) }).click();
    await expect(page.locator('button[role="switch"]:visible').first()).toBeVisible();
  }

  test('Setup Wizard page should be accessible', async ({ page }) => {
    await page.goto('/wizard/');
    await page.waitForLoadState('networkidle');
    await expect(page.getByRole('heading', { name: 'Welcome to CouchPotato' })).toBeVisible();

    // Regression guard for UI-CONFORM-01: the wizard used to render its 8
    // toggle switches at a non-canonical size (w-10 h-5) and without
    // role="switch"/:aria-checked/aria-label, which axe's aria-required-attr /
    // aria-allowed-attr rules would catch on any toggle actually in view.
    await checkA11y(page, 'Setup Wizard (Welcome)');

    // AC-QA-5 (A11Y-001): every step below this point used to go unscanned.
    // The wizard is `x-show`-gated per step, so axe -- which correctly
    // ignores hidden elements -- only ever saw the Welcome step above.
    // specs/A11Y-001-form-labels-not-associated.md measured the gap this
    // left: 118 SonarQube findings against 0 from axe, because SonarQube
    // reads template source and axe reads the rendered DOM at a moment most
    // of that source was not visible. Walk the real flow, the same shape
    // navigateWizardToProviders above uses, and scan each step once its
    // fields are actually visible -- opening the nested toggles too, so the
    // fields that only render once a section is enabled (Newznab entries,
    // Jackett credentials, a private tracker's fields, the chosen
    // downloader's fields) are in the DOM when the scan runs, not skipped
    // the same way the Welcome-only scan skipped everything below it.

    // Step 2: Security -- username/password.
    await page.getByRole('button', { name: 'Continue' }).click();
    // A3: assert the wizard actually reached this step before scanning it --
    // demonstrated to matter: blocking `nextStep()` from advancing left the
    // Welcome step showing while this scan ran unaware, and reported clean.
    await assertWizardStepShowing(page, 'Server Security', '#wizard-username');
    // A5: floor measured directly against this markup -- 2 fields
    // (username, password).
    await checkFieldNameA11y(page, 'Setup Wizard (Security)', 2);

    // Security -> Providers (Skip, no credentials needed for this scan).
    await page.getByRole('button', { name: 'Skip' }).click();
    await expect(page.getByRole('heading', { name: 'Where to Search' })).toBeVisible();

    // Step 3: Providers -- "Both" renders usenet and torrent sections
    // together; enabling Newznab and Jackett reveals their credential
    // fields, and expanding + enabling one private tracker reveals the
    // `x-for` field loop (AC-A11Y-2's bound-id case).
    await page.getByRole('button', { name: /^Both/ }).click();
    await expect(page.getByRole('switch', { name: 'Enable Newznab Indexers' })).toBeVisible();
    await page.getByRole('switch', { name: 'Enable Newznab Indexers' }).click();
    await page.getByRole('switch', { name: 'Enable Jackett / TorrentPotato' }).click();
    await page.getByRole('button', { name: /Private Trackers/ }).click();
    await expect(page.getByRole('switch', { name: 'Enable PassThePopcorn' })).toBeVisible();
    // TWO trackers enabled, not one: a single enabled tracker cannot prove
    // B2's fix, because a static id/for pair inside the field loop would
    // never collide with itself -- it only collides once a second tracker's
    // identically-named "Username"/"Passkey" fields are ALSO visible.
    await page.getByRole('switch', { name: 'Enable PassThePopcorn' }).click();
    await page.getByRole('switch', { name: 'Enable HDBits' }).click();
    // Both trackers' field groups must be rendered before the scan below
    // counts fields against them -- assertFieldNamesAreReal reads the DOM
    // once, with no retry, so this has to be a real wait, not a guess.
    await expect(
      page.getByRole('group', { name: 'PassThePopcorn' }).getByLabel('Username'),
    ).toBeVisible();
    await expect(
      page.getByRole('group', { name: 'HDBits' }).getByLabel('Username'),
    ).toBeVisible();
    await assertWizardStepShowing(page, 'Where to Search', '#wizard-jackett-url');
    // A5: floor measured directly -- 9 fields (2 Newznab entry, 2 Jackett,
    // 3 PassThePopcorn, 2 HDBits), before B1's second indexer entry below
    // adds 2 more.
    await checkFieldNameA11y(page, 'Setup Wizard (Providers)', 9);

    // B2 regression coverage: PassThePopcorn's and HDBits' "Username" fields
    // are identically named but grouped by tracker name, so assistive tech
    // can tell them apart the same way the Usenet/Torrent client groups
    // (checked further below) disambiguate two "Host" fields.
    await expect(
      page.getByRole('group', { name: 'PassThePopcorn' }).getByLabel('Username'),
    ).toBeVisible();
    await expect(
      page.getByRole('group', { name: 'HDBits' }).getByLabel('Username'),
    ).toBeVisible();

    // B1/B3 regression coverage: add a second Newznab indexer entry so the
    // `x-for`-bound aria-labels (B1) and the per-row remove button (B3) both
    // render a second time, then re-scan. Two DISTINCT accessible names are
    // asserted directly (not just "no violation") because axe's `label` rule
    // is satisfied by two fields both named "Newznab indexer URL" -- it
    // checks presence, not uniqueness -- so only a direct read of the two
    // names can catch the static-aria-label regression B1 fixed.
    await page.getByRole('button', { name: '+ Add another indexer' }).click();
    const indexerUrlInputs = page.getByLabel(/Newznab indexer URL \d+/);
    await expect(indexerUrlInputs).toHaveCount(2);
    const firstName = await indexerUrlInputs.nth(0).getAttribute('aria-label');
    const secondName = await indexerUrlInputs.nth(1).getAttribute('aria-label');
    expect(
      firstName,
      'two Newznab indexer rows must not share one accessible name',
    ).not.toBe(secondName);
    const removeButtons = page.getByRole('button', { name: /^Remove indexer \d+$/ });
    await expect(removeButtons).toHaveCount(2);
    await checkFieldNameA11y(page, 'Setup Wizard (Providers, two indexers)', 11);

    // Step 4: Downloader -- pick one client from each list so
    // getDownloaderFields()'s x-html-injected markup actually renders, and
    // enable Black Hole for its own folder fields.
    await page.getByRole('button', { name: 'Continue' }).click();
    await expect(page.getByRole('heading', { name: 'Download Clients' })).toBeVisible();
    await page.getByRole('button', { name: 'SABnzbd' }).click();
    await page.getByRole('button', { name: 'qBittorrent' }).click();
    await page.getByRole('switch', { name: 'Enable Black Hole' }).click();
    // Black Hole's own folder fields render behind `x-show="blackholeEnabled"`
    // -- wait for the field the scan below counts before it runs.
    await expect(page.locator('#wizard-blackhole-nzb-dir')).toBeVisible();
    await assertWizardStepShowing(page, 'Download Clients', '#wizard-dl-sabnzbd-host');
    // A5: floor measured directly -- 8 fields (3 SABnzbd, 3 qBittorrent, 2
    // Black Hole).
    await checkFieldNameA11y(page, 'Setup Wizard (Downloader)', 8);

    // B2 regression coverage: with one Usenet client (SABnzbd) and one
    // Torrent client (qBittorrent) both configured, "Host" is the visible
    // label on two different fields. Distinguishing them is the GROUP each
    // sits in (aria-labelledby the section heading), not the field's own
    // name -- getByRole('group', ...) is the direct way to prove that
    // grouping is real rather than decorative.
    await expect(
      page.getByRole('group', { name: 'Usenet Client' }).getByLabel('Host'),
    ).toBeVisible();
    await expect(
      page.getByRole('group', { name: 'Torrent Client' }).getByLabel('Host'),
    ).toBeVisible();

    // Step 5: Library -- renamer fields, on by default.
    await page.getByRole('button', { name: 'Continue' }).click();
    await assertWizardStepShowing(page, 'Movie Library', '#wizard-renamer-from');
    // A5: floor measured directly -- 4 fields (download folder, movie
    // library, folder naming, file naming).
    await checkFieldNameA11y(page, 'Setup Wizard (Library)', 4);

    // B3 regression coverage: the directory browser's close button is the
    // only visible way to dismiss it and is icon-only. It only exists in the
    // DOM once opened, so open it here rather than relying on a full-page
    // scan that would never have found it hidden behind `x-show`.
    await page.getByRole('button', { name: 'Browse' }).first().click();
    const closeBrowser = page.getByRole('button', { name: 'Close directory browser' });
    await expect(closeBrowser).toBeVisible();
    const browserResults = await new AxeBuilder({ page })
      .include('.fixed.inset-0.z-50')
      .withRules(['button-name'])
      .analyze();
    expect(
      browserResults.violations.map(v => v.nodes.map(n => n.html).join('; ')),
      'directory browser button(s) with no accessible name',
    ).toEqual([]);
    await closeBrowser.click();
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

    // Black Hole toggle is always visible on the Downloader step.
    const blackholeToggle = page.getByRole('switch', { name: 'Enable Black Hole' });
    await expect(blackholeToggle).toBeVisible();
    await expect(blackholeToggle).toHaveAttribute('aria-checked', /true|false/);
    let trackClass = await blackholeToggle.getAttribute('class');
    expect(trackClass).toContain('w-8 h-4');
    expect(trackClass).not.toContain('w-10 h-5');

    // Step 4: Downloader -> Continue to Library
    await page.getByRole('button', { name: 'Continue' }).click();

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
    await expect(page.locator('#movie-count')).not.toBeEmpty();

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

  /*
   * A11Y-002: the ring itself, not merely its presence.
   *
   * Every check above this point, checkA11y's page-wide axe sweeps included,
   * only asserts that AN outline exists. It does: base.html's `:focus-visible`
   * rule sets one on every element. Tailwind's `focus:outline-none` utility
   * compiles to `outline: 2px solid transparent` at specificity 0,2,0, against
   * base.html's 0,1,0, so on any control carrying that utility Tailwind wins
   * the colour and the outline paints fully transparent. `:focus-visible`
   * still matches, `outline-style` is still `solid`, only the paint is gone --
   * exactly the shape no "outline is present" check can catch.
   *
   * `:root.light :focus-visible { outline-color: #0e7490 }` (base.html) wins
   * the colour back in the light theme by accident, at specificity 0,3,0.
   * There is no `:root.dark` equivalent, and dark is the default theme
   * (base.html's `<html class="dark">`), so this test is expected to fail in
   * the dark iteration only, and pass already in the light one -- proving the
   * light theme is genuinely fine rather than the assertion being vacuous in
   * both directions.
   *
   * #wizard-username is used (not the two FOCUS_INDICATOR_PROBE controls
   * above) because it actually carries `focus:outline-none`
   * (wizard.html:100); `#filter-movies` and the Add-movie search input use
   * `focus-visible:outline-*` utilities instead and never exercise this bug.
   *
   * Real focus, verified rather than assumed (HAZARD 2): a mouse `.click()`
   * on a text `<input>` in Chromium still satisfies `:focus-visible` -- typing
   * is expected next, so the UA treats it like keyboard focus regardless of
   * pointer origin -- but that is asserted explicitly with
   * `el.matches(':focus-visible')` BEFORE any style is read, so a click that
   * landed without it (a future engine change, a disabled/covered element)
   * fails loudly here instead of silently reading a stale outline.
   *
   * Alpha, not string (HAZARD 3): the colour is read as `rgba(...)` and only
   * the alpha channel is asserted against zero, never the string, because a
   * `solid` `outline-style` with a colour computes to a real rgba() string in
   * every engine regardless of whether that colour is paintable.
   *
   * Background (HAZARD 4): `outline-offset: 2px` paints the ring outside the
   * input's own border box, over whatever surrounds it. Neither the input nor
   * its wrapping `<div>`s carry a background of their own -- the nearest
   * opaque ancestor is the wizard card (`bg-cp-card`), so that, not the
   * input's own fill or the page body, is the surface contrast is measured
   * against. Found by walking up the real DOM rather than assumed, so this
   * keeps working if the markup grows another wrapper.
   */
  for (const theme of ['dark', 'light'] as const) {
    test(`the wizard username field's focus ring is visible in the ${theme} theme`, async ({ page }) => {
      await page.addInitScript((t) => {
        localStorage.setItem('cp-theme', t);
      }, theme);

      await page.goto('/wizard/');
      await page.waitForLoadState('networkidle');
      await expect(page.getByRole('heading', { name: 'Welcome to CouchPotato' })).toBeVisible();

      // Pin the theme really took effect, same guard the toast contrast test
      // uses, so a broken theme pipeline reds this loudly rather than
      // quietly scanning the wrong theme under the right test name.
      await expect
        .poll(() => page.evaluate(() => document.documentElement.classList.contains('light')))
        .toBe(theme === 'light');

      // Welcome -> Server Security, the same step-advance
      // navigateWizardToProviders/the wizard a11y test above use.
      await page.getByRole('button', { name: 'Continue' }).click();
      await assertWizardStepShowing(page, 'Server Security', '#wizard-username');

      const input = page.locator('#wizard-username');
      await input.click();

      const measured = await input.evaluate((el: HTMLElement) => {
        const isFocusVisible = el.matches(':focus-visible');
        const outlineColor = window.getComputedStyle(el).outlineColor;
        const outlineStyle = window.getComputedStyle(el).outlineStyle;

        const parseColor = (s: string) => {
          const m = s.match(/rgba?\(([^)]+)\)/);
          if (!m) return null;
          const parts = m[1].split(',').map((p) => parseFloat(p.trim()));
          return { r: parts[0], g: parts[1], b: parts[2], a: parts.length > 3 ? parts[3] : 1 };
        };

        const luminance = (c: { r: number; g: number; b: number }) => {
          const chan = (v: number) => {
            const s = v / 255;
            return s <= 0.04045 ? s / 12.92 : Math.pow((s + 0.055) / 1.055, 2.4);
          };
          return 0.2126 * chan(c.r) + 0.7152 * chan(c.g) + 0.0722 * chan(c.b);
        };

        // The surface under the ring, composited. Three things this has to get
        // right, each of which was wrong in an earlier version of this helper
        // and each of which was caught by review rather than by running it.
        //
        // 1. START AT THE PARENT, not at `el`. `outline-offset: 2px` paints the
        //    ring OUTSIDE the element's border box, and an element's own
        //    background is clipped to that box, so the element's own fill is
        //    never under its own ring. Starting at `el` produces a false PASS,
        //    demonstrated: a control with an opaque dark fill sitting on a
        //    #35c5f4 parent has no visible ring at all and measured 9.67:1.
        //    It also produces a false FAIL on the wizard's Continue button,
        //    whose fill is the ring colour: 1.00:1 for a ring you can plainly
        //    see.
        // 2. COMPOSITE the layers rather than taking the first with any colour
        //    in it. The fields are `bg-white/[0.03]` over `bg-cp-card`, so
        //    reading the first layer raw treats a 3 per cent white veil as
        //    solid WHITE and measured the ring at 2.01:1, failing a fix that
        //    was correct.
        // 3. If the walk reaches the top without ever finding an opaque layer,
        //    THROW. Seeding the composite from a faint layer as though it were
        //    solid paint reported 10.44:1 for a ring measuring about 2:1 on a
        //    white canvas. Not reachable while `body` carries an opaque
        //    background, which it does, but a guard must not guess.
        //
        // Known limit, stated rather than implied: this walks DOM ancestry,
        // which is not paint order. An absolutely positioned sibling, such as
        // the gradient overlays at partials/movie_detail.html:56-57, can be
        // the real backdrop and this will step past it. Valid only for
        // elements whose backdrop comes from their own ancestors.
        let node: HTMLElement | null = el.parentElement;
        const layers: { r: number; g: number; b: number; a: number }[] = [];
        let bg: { r: number; g: number; b: number } | null = null;
        let bgOwner = '';
        let foundOpaque = false;
        while (node) {
          const c = parseColor(window.getComputedStyle(node).backgroundColor);
          if (c && c.a > 0) {
            if (!bgOwner) {
              bgOwner = node.id ? `#${node.id}` : (node.className.toString().split(/\s+/)[0] || node.tagName);
            }
            layers.push(c);
            if (c.a >= 1) {
              foundOpaque = true;
              break;
            }
          }
          node = node.parentElement;
        }
        if (!foundOpaque) {
          throw new Error(
            `no opaque backdrop found above ${el.id ? '#' + el.id : el.tagName}; ` +
            'the contrast below the ring cannot be computed, so this check cannot report a verdict',
          );
        }
        // Composite bottom-up: the last layer collected is the lowest, and it
        // is opaque, so it seeds the stack.
        for (let i = layers.length - 1; i >= 0; i--) {
          const c = layers[i];
          bg = bg === null
            ? { r: c.r, g: c.g, b: c.b }
            : {
                r: c.a * c.r + (1 - c.a) * bg.r,
                g: c.a * c.g + (1 - c.a) * bg.g,
                b: c.a * c.b + (1 - c.a) * bg.b,
              };
        }

        const ring = parseColor(outlineColor);
        const contrast = ring && bg
          ? (() => {
              const l1 = luminance(ring);
              const l2 = luminance(bg);
              return (Math.max(l1, l2) + 0.05) / (Math.min(l1, l2) + 0.05);
            })()
          : null;

        return {
          isFocusVisible,
          outlineStyle,
          outlineColor,
          ringAlpha: ring ? ring.a : null,
          bgOwner,
          contrast,
        };
      });

      expect(
        measured.isFocusVisible,
        `#wizard-username did not match :focus-visible after a click in the ` +
        `${theme} theme (outline-style computed as ${measured.outlineStyle}) ` +
        `-- the probe below would prove nothing about a real keyboard user`,
      ).toBe(true);

      // AC-A11Y-1: not transparent, in BOTH themes.
      expect(
        measured.ringAlpha,
        `${theme} theme: computed outline-color on #wizard-username is ` +
        `${measured.outlineColor} (alpha ${measured.ringAlpha}) -- present ` +
        `and invisible, exactly the shape "an outline exists" checks miss`,
      ).toBeGreaterThan(0);

      // AC-A11Y-2: at least 3:1 against the surface it actually sits on,
      // computed with the WCAG formula rather than compared to a hex literal
      // so a future palette change must fail this too.
      expect(
        measured.contrast,
        `${theme} theme: focus ring ${measured.outlineColor} against ` +
        `${measured.bgOwner}'s background measures ` +
        `${measured.contrast?.toFixed(2)}:1, below the WCAG 1.4.11 floor of 3:1`,
      ).toBeGreaterThanOrEqual(3);
    });
  }

  test('Images should have alt text', async ({ page }) => {
    await page.goto('/');
    await page.waitForLoadState('networkidle');
    // Poster <img>s only exist once the grid's htmx load has swapped in.
    await expect(page.locator('#movie-count')).not.toBeEmpty();

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
    await expect(page.locator('#movie-count')).not.toBeEmpty();

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
