import { test, expect, Page } from '@playwright/test';

/**
 * E2E coverage for the "Add from a movie site" (add-by-URL / bookmarklet)
 * flow on the Add Movie page.
 *
 * Covers:
 * - The bookmarklet disclosure toggle (couchpotato/ui/templates/add.html):
 *   an Alpine `x-show`/`x-cloak` panel gated behind an
 *   `aria-expanded`/`aria-controls` button.
 * - The `?url=` auto-resolve flow, which htmx-loads
 *   `partial/add-via-url` into `#add-via-url-results`
 *   (couchpotato/ui/__init__.py `partial_add_via_url`) and renders
 *   `partials/add_via_url_result.html`.
 *
 * The URL used below (example.com) matches no userscript provider's
 * `includes` host list (couchpotato/core/media/_base/providers/userscript/base.py
 * `belongsTo`), so resolution fails locally without any outbound HTTP
 * fetch — deterministic and network-free.
 */

// Helper: wait for page to be fully loaded (matches interactions.e2e.spec.ts).
async function waitForPageReady(page: Page) {
  await page.waitForLoadState('networkidle');
  await page.waitForTimeout(500);
}

test.describe('Add by URL', () => {
  test.describe('bookmarklet disclosure', () => {
    test('toggles open and closed, flipping aria-expanded', async ({ page }) => {
      await page.goto('/add/');
      await waitForPageReady(page);

      const toggleButton = page.getByRole('button', { name: 'Add from a movie site' });
      const panel = page.locator('#bookmarklet-disclosure');

      await expect(toggleButton).toBeVisible();
      await expect(toggleButton).toHaveAttribute('aria-expanded', 'false');
      await expect(panel).toBeHidden();

      await toggleButton.click();

      await expect(panel).toBeVisible();
      await expect(toggleButton).toHaveAttribute('aria-expanded', 'true');

      await toggleButton.click();

      await expect(panel).toBeHidden();
      await expect(toggleButton).toHaveAttribute('aria-expanded', 'false');
    });

    test('bookmarklet link is a javascript: URL targeting add/?url=', async ({ page }) => {
      await page.goto('/add/');
      await waitForPageReady(page);

      const toggleButton = page.getByRole('button', { name: 'Add from a movie site' });
      await toggleButton.click();

      const bookmarkletLink = page.locator('#bookmarklet-disclosure a');
      await expect(bookmarkletLink).toBeVisible();

      const href = await bookmarkletLink.getAttribute('href');
      expect(href).toBeTruthy();
      expect(href).toMatch(/^javascript:/);
      expect(href).toContain('add/?url=');
    });

    test('clicking the bookmarklet on this page hints instead of navigating', async ({ page }) => {
      await page.goto('/add/');
      await waitForPageReady(page);

      const toggleButton = page.getByRole('button', { name: 'Add from a movie site' });
      await toggleButton.click();

      const bookmarkletLink = page.locator('#bookmarklet-disclosure a');
      await expect(bookmarkletLink).toBeVisible();

      // @click.prevent on the link stops the javascript: URL from firing, so
      // the page must not self-navigate to ?url= ...
      await bookmarkletLink.click();

      expect(page.url()).toMatch(/\/add\/$/);
      expect(page.url()).not.toContain('?url=');

      // ... and the hint (role="status") is revealed instead.
      const hint = page.locator('#bookmarklet-disclosure [role="status"]');
      await expect(hint).toBeVisible();
      await expect(hint).toContainText("That's a bookmarklet");
    });
  });

  test.describe('resolve from ?url=', () => {
    test('shows the error/empty state for a URL no provider recognizes', async ({ page }) => {
      await page.goto('/add/?url=' + encodeURIComponent('http://example.com/not-a-movie'));
      await waitForPageReady(page);

      const results = page.locator('#add-via-url-results');
      await expect(results).toBeVisible();

      // htmx swaps the loading spinner for the rendered
      // partials/add_via_url_result.html error state once resolution
      // fails (no provider's `includes` matches example.com).
      const errorStatus = results.locator('[role="status"]');
      await expect(errorStatus).toBeVisible({ timeout: 10000 });
      await expect(errorStatus).toContainText("Couldn't find a movie at that URL");
      await expect(errorStatus).toContainText('Failed getting movie info');

      // The default "no url yet" empty state must be suppressed when a
      // url is present (add.html only renders it `{% if not url %}`).
      await expect(page.getByText('Search for a movie to add it to your wanted list')).toHaveCount(0);
    });

    test('keeps the title-search box available alongside the URL flow', async ({ page }) => {
      await page.goto('/add/?url=' + encodeURIComponent('http://example.com/not-a-movie'));
      await waitForPageReady(page);

      await expect(page.locator('#movie-search')).toBeVisible();
    });
  });
});
