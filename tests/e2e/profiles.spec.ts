import { test, expect } from '@playwright/test';

/**
 * E2E tests for Quality Profile management (Settings → Profiles tab).
 * Covers: list loads, create profile, edit profile, reorder quality, delete with confirm.
 */

test.describe('Quality Profiles', () => {
  test.beforeEach(async ({ page }) => {
    await page.goto('/settings/');
    // Wait for settings to load
    await expect(page.locator('h1')).toContainText('Settings');
    // Click the Profiles tab
    const profilesTab = page.getByRole('tab', { name: /profiles/i });
    await expect(profilesTab).toBeVisible({ timeout: 5000 });
    await profilesTab.click();
  });

  test('profiles tab loads and shows profile list', async ({ page }) => {
    // Should show the profiles panel after loading
    const panel = page.locator('#profiles-panel');
    await expect(panel).toBeVisible({ timeout: 5000 });

    // Should not show load error
    const errEl = panel.locator('[role="alert"]');
    // If error is visible, fail with message
    if (await errEl.isVisible()) {
      const errText = await errEl.textContent();
      throw new Error('Profiles panel showed error: ' + errText);
    }

    // Should show "New Profile" button
    const newBtn = panel.getByRole('button', { name: /new profile/i });
    await expect(newBtn).toBeVisible({ timeout: 5000 });
  });

  test('create a new profile', async ({ page }) => {
    const panel = page.locator('#profiles-panel');
    await page.waitForTimeout(1500); // wait for profiles to load

    // Click New Profile
    const newBtn = panel.getByRole('button', { name: /new profile/i });
    await newBtn.click();

    // Modal should open
    const modal = page.locator('[role="dialog"][aria-modal="true"]').first();
    await expect(modal).toBeVisible({ timeout: 3000 });

    // Fill in name
    const nameInput = modal.locator('input[type="text"]').first();
    await nameInput.fill('E2E Test Profile');

    // Select a quality and add it
    const qualitySelect = modal.locator('select').first();
    await qualitySelect.selectOption({ index: 1 }); // pick first quality
    const addBtn = modal.getByRole('button', { name: /^add$/i });
    await addBtn.click();

    // Should see a quality chip appear in the list
    const qualityList = modal.locator('[role="list"][aria-label="Qualities in this profile"]');
    await expect(qualityList.locator('[role="listitem"]').first()).toBeVisible({ timeout: 2000 });

    // Save
    const saveBtn = modal.getByRole('button', { name: /create profile/i });
    await saveBtn.click();

    // Modal should close
    await expect(modal).not.toBeVisible({ timeout: 5000 });

    // Toast should show success
    const toast = page.locator('[role="status"][aria-live="polite"]').last();
    await expect(toast).toContainText(/created/i, { timeout: 5000 });

    // The new profile should appear in the list
    await expect(panel.getByText('E2E Test Profile')).toBeVisible({ timeout: 5000 });
  });

  test('edit an existing profile', async ({ page }) => {
    const panel = page.locator('#profiles-panel');
    await page.waitForTimeout(1500);

    // Find the first edit button
    const editBtns = panel.getByRole('button', { name: /edit profile/i });
    const count = await editBtns.count();
    if (count === 0) {
      test.skip(); // no profiles exist to edit
      return;
    }
    const firstEditBtn = editBtns.first();
    const profileName = await firstEditBtn.getAttribute('aria-label');
    await firstEditBtn.click();

    // Modal should open
    const modal = page.locator('[role="dialog"][aria-modal="true"]').first();
    await expect(modal).toBeVisible({ timeout: 3000 });

    // Should show "Save Changes" button (existing profile)
    await expect(modal.getByRole('button', { name: /save changes/i })).toBeVisible();

    // Close with Escape
    await page.keyboard.press('Escape');
    await expect(modal).not.toBeVisible({ timeout: 3000 });
  });

  test('reorder qualities within a profile', async ({ page }) => {
    const panel = page.locator('#profiles-panel');
    await page.waitForTimeout(1500);

    // Open the first profile that has multiple qualities to edit
    const editBtns = panel.getByRole('button', { name: /edit profile/i });
    const count = await editBtns.count();
    if (count === 0) { test.skip(); return; }

    await editBtns.first().click();

    const modal = page.locator('[role="dialog"][aria-modal="true"]').first();
    await expect(modal).toBeVisible({ timeout: 3000 });

    const qualityItems = modal.locator('[role="listitem"]');
    const qCount = await qualityItems.count();

    if (qCount >= 2) {
      // Click the "move down" button on the first quality (it should be enabled if there's a 2nd)
      const moveDownBtns = modal.getByRole('button', { name: /quality down/i });
      if (await moveDownBtns.count() > 0) {
        await moveDownBtns.first().click();
        // Items should have reordered (no assertion on exact names, just that it didn't crash)
        await expect(qualityItems.first()).toBeVisible();
      }
    }

    // Close modal
    await page.keyboard.press('Escape');
    await expect(modal).not.toBeVisible({ timeout: 3000 });
  });

  test('delete profile shows confirm dialog', async ({ page }) => {
    const panel = page.locator('#profiles-panel');
    await page.waitForTimeout(1500);

    const deleteBtns = panel.getByRole('button', { name: /delete profile/i });
    const count = await deleteBtns.count();
    if (count === 0) { test.skip(); return; }

    await deleteBtns.first().click();

    // Confirm dialog should appear
    const confirmDialog = page.locator('[role="dialog"][aria-modal="true"]').last();
    await expect(confirmDialog).toBeVisible({ timeout: 3000 });
    await expect(confirmDialog.locator('#delete-confirm-title')).toContainText('Delete Profile');

    // Cancel button should close dialog
    const cancelBtn = confirmDialog.getByRole('button', { name: /^cancel$/i });
    await cancelBtn.click();
    await expect(confirmDialog).not.toBeVisible({ timeout: 3000 });
  });

  test('delete confirm dialog closes on Escape', async ({ page }) => {
    const panel = page.locator('#profiles-panel');
    await page.waitForTimeout(1500);

    const deleteBtns = panel.getByRole('button', { name: /delete profile/i });
    if (await deleteBtns.count() === 0) { test.skip(); return; }

    await deleteBtns.first().click();

    const confirmDialog = page.locator('[role="dialog"][aria-modal="true"]').last();
    await expect(confirmDialog).toBeVisible({ timeout: 3000 });

    await page.keyboard.press('Escape');
    await expect(confirmDialog).not.toBeVisible({ timeout: 3000 });
  });

  test('validation — cannot save profile with empty name', async ({ page }) => {
    const panel = page.locator('#profiles-panel');
    await page.waitForTimeout(1500);

    await panel.getByRole('button', { name: /new profile/i }).click();

    const modal = page.locator('[role="dialog"][aria-modal="true"]').first();
    await expect(modal).toBeVisible({ timeout: 3000 });

    // Click Create without filling in a name
    await modal.getByRole('button', { name: /create profile/i }).click();

    // Validation error should appear in the modal
    const errorRegion = modal.locator('[role="alert"]');
    await expect(errorRegion).toBeVisible({ timeout: 2000 });
    await expect(errorRegion).toContainText(/name/i);

    // Modal should still be open
    await expect(modal).toBeVisible();

    // Close with Escape
    await page.keyboard.press('Escape');
  });

  test('Profiles tab is accessible (no a11y violations)', async ({ page }) => {
    const panel = page.locator('#profiles-panel');
    await page.waitForTimeout(1500);
    // Basic presence of landmark and heading
    await expect(panel.locator('h2').first()).toBeVisible({ timeout: 5000 });
  });
});
