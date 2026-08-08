import { test, expect } from './fixtures';

/**
 * Navigation tests for CouchPotato new UI.
 * Tests that all main pages are accessible and navigation works correctly.
 */

test.describe('Navigation', () => {
  // AC-QA-27: the login `beforeEach` that used to sit here is GONE, not fixed.
  //
  // It navigated to `/`, and then did nothing at all unless the URL contained
  // `/login`, AND a form existed, AND both CP_TEST_USER and CP_TEST_PASS were
  // set in the environment. Every worker in this suite is seeded with no
  // password, so `auth_is_required()` is False and none of those three
  // conditions has ever held: three nested `if`s that could only pass
  // silently. It read as authentication coverage and was not any.
  //
  // The real thing now lives in `authenticated-session.a11y.spec.ts`, which
  // starts a server WITH a password and fails -- rather than skipping -- if
  // the login form is not there. Every test below does its own `page.goto`,
  // so nothing here depended on the navigation this hook also performed.

  test('should load the wanted page by default', async ({ page }) => {
    await page.goto('/');
    await expect(page).toHaveTitle(/Wanted.*CouchPotato/);
    await expect(page.locator('h1')).toContainText('Wanted');
  });

  test('should redirect /available to /wanted?filter=available', async ({ page }) => {
    // /available was removed from the sidebar and is now a redirect
    await page.goto('/available');
    await expect(page).toHaveURL(/.*wanted.*filter=available/);
    await expect(page.locator('h1')).toContainText('Wanted');
  });

  test('should navigate to Suggestions page', async ({ page }) => {
    await page.goto('/');
    await page.click('a[href*="suggestions"]');
    await expect(page).toHaveURL(/.*suggestions/);
    await expect(page.locator('h1')).toContainText('Suggestions');
  });

  test('should navigate to Add Movie page', async ({ page }) => {
    await page.goto('/');
    await page.click('a[href*="add"]');
    await expect(page).toHaveURL(/.*add/);
    await expect(page.locator('h1')).toContainText('Add');
  });

  test('should navigate to Settings page', async ({ page }) => {
    await page.goto('/');
    await page.click('a[href*="settings"]');
    await expect(page).toHaveURL(/.*settings/);
    await expect(page.locator('h1')).toContainText('Settings');
  });

  test('Settings exposes a reachable Categories tab', async ({ page }) => {
    // Smoke test for tab wiring — catches 'categories' being dropped from
    // tabOrder/customPanelTabs independently of the categories.spec.ts suite.
    await page.goto('/settings/');
    await expect(page.locator('h1')).toContainText('Settings');
    const categoriesTab = page.getByRole('tab', { name: /categories/i });
    await expect(categoriesTab).toBeVisible();
    await categoriesTab.click();
    await expect(page.locator('#categories-panel')).toBeVisible();
  });

  test('sidebar should collapse and expand', async ({ page }) => {
    await page.goto('/');
    // The `chromium` project runs Desktop Chrome and playwright.config.ts's
    // `testIgnore` excludes `*.mobile.spec.ts` from it, so this viewport is
    // never the narrow one the sidebar hides on -- the guard this used to
    // have (`if (await sidebar.isVisible())`) could never be false here and
    // protected nothing while hiding a possible zero-assertion run.
    const sidebar = page.locator('aside');
    await expect(sidebar).toBeVisible();

    // The collapse control's accessible name -- the suite's only assertion of
    // it (the near-duplicate in interactions.e2e.spec.ts asserted nothing).
    const collapseBtn = page.locator('aside button[aria-label*="Collapse" i], aside button[aria-label*="Expand" i]');
    await expect(collapseBtn).toBeVisible();

    // Click collapse button (last button in sidebar)
    await collapseBtn.click();
    // Check that sidebar is collapsed (narrower width)
    await expect(sidebar).toHaveClass(/w-16/);
    // Click the SAME named control again rather than `aside button:last-child`.
    // That selector means "any button that is the last child of its parent",
    // not "the last button in the sidebar" -- so the D8 sign-out button, the
    // only child of its <form>, matches it too. It does not bite today only
    // because the seeded E2E instance has no password and the control is not
    // rendered (see the test below); it would become a strict-mode violation
    // the moment AC-QA-27 turns authentication on.
    await collapseBtn.click();
    await expect(sidebar).toHaveClass(/w-56/);
  });

  /*
   * D8's negative half, asserted UNCONDITIONALLY.
   *
   * scripts/seed_e2e_data.py seeds no password, so `auth_is_required()` is
   * false on every worker's instance and there is no session for a sign-out
   * control to end. Rendering one anyway would be a button that signs the
   * operator out of nothing.
   *
   * Deliberately not written as `if (authOn) { ... }`: that shape passes
   * silently in exactly the configuration this suite runs in, which is the
   * vacuous-guard pattern `make check-traps` exists to stop. It fails if the
   * `{% if auth_required %}` guard in base.html is dropped, and it fails if
   * this instance ever starts requiring a login -- at which point AC-QA-27's
   * authenticated E2E is the test that should replace it.
   */
  test('with authentication off, the shell renders no sign-out control', async ({ page }) => {
    await page.goto('/');
    await expect(page).not.toHaveURL(/login/);
    await expect(page.locator('aside')).toBeVisible();

    await expect(page.locator('form[action$="logout/"]')).toHaveCount(0);
    await expect(page.getByRole('button', { name: /sign out|log out/i })).toHaveCount(0);
  });
});
