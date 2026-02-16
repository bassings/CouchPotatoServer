import { test, expect } from '@playwright/test';

/**
 * Navigation tests for CouchPotato new UI.
 * Tests that all main pages are accessible and navigation works correctly.
 */

test.describe('Navigation', () => {
  // Skip auth if no credentials are set (local dev)
  test.beforeEach(async ({ page }) => {
    // Try to access the page; if redirected to login, handle it
    await page.goto('/');
    if (page.url().includes('/login')) {
      // Check if auth is actually required (might be disabled)
      const loginForm = page.locator('form');
      if (await loginForm.count() > 0) {
        // Fill in test credentials if environment variables are set
        const username = process.env.CP_TEST_USER || '';
        const password = process.env.CP_TEST_PASS || '';
        if (username && password) {
          await page.fill('input[name="username"]', username);
          await page.fill('input[name="password"]', password);
          await page.click('button[type="submit"]');
          await page.waitForURL('**/');
        }
      }
    }
  });

  test('should load the wanted page by default', async ({ page }) => {
    await page.goto('/');
    await expect(page).toHaveTitle(/Wanted.*CouchPotato/);
    await expect(page.locator('h1')).toContainText('Wanted');
  });

  test('should navigate to Available page', async ({ page }) => {
    await page.goto('/');
    await page.click('a[href*="available"]');
    await expect(page).toHaveURL(/.*available/);
    await expect(page.locator('h1')).toContainText('Available');
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

  test('sidebar should collapse and expand', async ({ page }) => {
    await page.goto('/');
    // Wait for sidebar to be visible (desktop only)
    const sidebar = page.locator('aside');
    if (await sidebar.isVisible()) {
      // Click collapse button (last button in sidebar)
      await page.click('aside button[aria-label*="Collapse" i], aside button[aria-label*="Expand" i]');
      // Check that sidebar is collapsed (narrower width)
      await expect(sidebar).toHaveClass(/w-16/);
      // Click again to expand
      await page.click('aside button:last-child');
      await expect(sidebar).toHaveClass(/w-56/);
    }
  });
});
