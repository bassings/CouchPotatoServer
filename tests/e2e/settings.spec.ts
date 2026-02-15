import { test, expect } from '@playwright/test';

/**
 * Settings page tests for CouchPotato new UI.
 */

test.describe('Settings', () => {
  test.beforeEach(async ({ page }) => {
    await page.goto('/settings/');
    await expect(page.locator('h1')).toContainText('Settings');
  });

  test('should show settings tabs', async ({ page }) => {
    // Should have multiple tabs
    const tabs = page.locator('button').filter({ hasText: /general|searcher|downloader|renamer|notification/i });
    await expect(tabs.first()).toBeVisible({ timeout: 5000 });
  });

  test('should be able to switch tabs', async ({ page }) => {
    // Wait for settings to load
    await page.waitForTimeout(1000);
    
    // Click on Searchers tab if available
    const searcherTab = page.locator('button').filter({ hasText: /searcher/i }).first();
    if (await searcherTab.isVisible()) {
      await searcherTab.click();
      // Content should change (look for searcher-related content)
      await page.waitForTimeout(500);
    }
    
    // Click on Downloaders tab if available
    const downloadersTab = page.locator('button').filter({ hasText: /downloader/i }).first();
    if (await downloadersTab.isVisible()) {
      await downloadersTab.click();
      await page.waitForTimeout(500);
    }
  });

  test('should show Advanced toggle', async ({ page }) => {
    // Wait for settings to load
    await page.waitForTimeout(1000);
    
    // Should have Advanced toggle
    const advancedToggle = page.getByText(/advanced/i);
    await expect(advancedToggle.first()).toBeVisible({ timeout: 5000 });
  });

  test('should show Logs tab', async ({ page }) => {
    // Should have Logs tab
    const logsTab = page.locator('button').filter({ hasText: /logs/i }).first();
    await expect(logsTab).toBeVisible({ timeout: 5000 });
    
    // Click Logs tab
    await logsTab.click();
    
    // Should show log-related controls
    const refreshButton = page.getByRole('button', { name: /refresh/i });
    await expect(refreshButton).toBeVisible({ timeout: 5000 });
  });

  test('Jackett sync button should have description (DEF-003)', async ({ page }) => {
    // Wait for settings to load
    await page.waitForTimeout(1000);
    
    // Navigate to Searchers tab
    const searcherTab = page.locator('button').filter({ hasText: /searcher/i }).first();
    if (await searcherTab.isVisible()) {
      await searcherTab.click();
      await page.waitForTimeout(500);
      
      // Look for Jackett sync button
      const jackettSync = page.locator('button').filter({ hasText: /sync/i }).first();
      if (await jackettSync.isVisible()) {
        // The description should be visible nearby (not "undefined")
        const parent = jackettSync.locator('..');
        const descriptionText = await parent.locator('p').textContent();
        
        // Description should exist and not be "undefined"
        expect(descriptionText).not.toBe('undefined');
        expect(descriptionText).not.toContain('undefined');
      }
    }
  });

  test('should auto-save settings', async ({ page }) => {
    // Wait for settings to load
    await page.waitForTimeout(1000);
    
    // Find a text input and modify it
    const textInputs = page.locator('input[type="text"]');
    const firstInput = textInputs.first();
    
    if (await firstInput.isVisible()) {
      // Type something
      await firstInput.fill('test-value-123');
      
      // Wait for auto-save
      await page.waitForTimeout(1000);
      
      // Should show "Saved" indicator
      const savedIndicator = page.getByText(/saved/i);
      await expect(savedIndicator.first()).toBeVisible({ timeout: 5000 });
    }
  });
});
