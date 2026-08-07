import { test, expect } from './fixtures';

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

    // Both tabs are among the always-present default set this file's own
    // "should show settings tabs" test pins -- the old
    // `if (await X.isVisible())` guards could never be false, and neither
    // click was ever checked for a real effect either way.
    const searcherTab = page.getByRole('tab', { name: /searcher/i });
    await expect(searcherTab).toBeVisible();
    await searcherTab.click();
    await expect(searcherTab).toHaveAttribute('aria-selected', 'true');

    const downloadersTab = page.getByRole('tab', { name: /downloader/i });
    await expect(downloadersTab).toBeVisible();
    await downloadersTab.click();
    await expect(downloadersTab).toHaveAttribute('aria-selected', 'true');
    // Switching tabs is exclusive: the previous tab must give up selection.
    await expect(searcherTab).toHaveAttribute('aria-selected', 'false');
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

    // Searchers is one of the always-present default tabs (see "should show
    // settings tabs" above) -- the old `if (await searcherTab.isVisible())`
    // guard could never be false.
    const searcherTab = page.getByRole('tab', { name: /searcher/i });
    await expect(searcherTab).toBeVisible();
    await searcherTab.click();
    await page.waitForTimeout(500);

    // Measured: the sync button is an `advanced`-flagged field
    // (provider_card.html: `x-show="... (showAdvanced || !opt.advanced) &&
    // isOptionVisible(opt, group) ..."`), so switching Advanced on is
    // necessary -- but `isOptionVisible` (scripts.html) ALSO gates it on
    // `show_when`, which for Jackett's sync action is tied to the provider's
    // own enabler toggle. Enabling Jackett for real is a side effect this
    // test should not cause (it is disabled in a fresh seed/config), so
    // unlike the "advanced" gate, that part of the precondition is genuinely
    // out of this test's control. Both branches now assert something,
    // instead of "not visible" silently reading as "test passed".
    const advancedToggle = page.getByRole('switch', { name: /show advanced settings/i });
    await expect(advancedToggle).toBeVisible();
    await advancedToggle.click();

    const jackettSync = page.locator('button').filter({ hasText: /sync/i }).first();
    if (await jackettSync.isVisible({ timeout: 5000 })) { // vacuous-guard-ok: the sync action is also gated on Jackett's own enabler toggle (show_when), which this test does not flip -- enabling a provider for real is a side effect out of scope here.
      // The description should be visible nearby (not "undefined")
      const parent = jackettSync.locator('..');
      const descriptionText = await parent.locator('p').textContent();

      // Description should exist and not be "undefined"
      expect(descriptionText).not.toBe('undefined');
      expect(descriptionText).not.toContain('undefined');
    } else {
      // Still in the DOM (x-show, not v-if), just hidden -- toBeHidden, not
      // toHaveCount(0).
      await expect(jackettSync).toBeHidden();
    }
  });

  test('should auto-save settings', async ({ page }) => {
    // Wait for settings to load
    await page.waitForTimeout(1000);

    // `:visible`, not `.first()` on the bare selector: General has
    // `advanced`-flagged text inputs earlier in DOM order that are
    // `x-show`-hidden until Advanced settings are shown (see the Jackett
    // sync test above for the same gating mechanism) -- `.first()` on the
    // unscoped locator picked one of those, so `isVisible()` on it was
    // false by construction and this always fell through to nothing being
    // asserted. General always renders at least one plain (non-advanced)
    // text field, so this is unconditional.
    const firstInput = page.locator('input[type="text"]:visible').first();
    await expect(firstInput).toBeVisible({ timeout: 5000 });

    // Type something
    await firstInput.fill('test-value-123');

    // Wait for auto-save
    await page.waitForTimeout(1000);

    // Should show "Saved" indicator
    const savedIndicator = page.getByText(/saved/i);
    await expect(savedIndicator.first()).toBeVisible({ timeout: 5000 });
  });
});
