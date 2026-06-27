import { test, expect, Page } from '@playwright/test';

/**
 * E2E tests for Quality Profile management (Settings → Profiles tab).
 * Covers: list loads, create profile, edit profile, reorder quality, delete with confirm.
 *
 * Uses condition-based waits (web-first assertions that auto-retry) rather than
 * fixed timeouts, and cleans up any profile it creates so the suite is idempotent.
 */

const TEST_PROFILE_NAME = 'E2E Test Profile';

/** Open the Profiles tab and wait for its content to finish loading. */
async function openProfilesTab(page: Page) {
  await page.goto('/settings/');
  await expect(page.locator('h1')).toContainText('Settings');

  const profilesTab = page.getByRole('tab', { name: /profiles/i });
  await expect(profilesTab).toBeVisible();
  await profilesTab.click();

  const panel = page.locator('#profiles-panel');
  await expect(panel).toBeVisible();

  // The New Profile button only renders in the loaded content block
  // (x-show="!loading && !loadError"), so its visibility is a deterministic
  // "init() resolved successfully" signal — no magic delay needed.
  // (Avoid .or([role="alert"]): the error alert is always in the DOM, just
  // hidden, so an .or() would match two elements and trip strict mode.)
  await expect(panel.getByRole('button', { name: /new profile/i })).toBeVisible();

  return panel;
}

/** Remove the test profile via the UI if it exists (idempotent cleanup). */
async function deleteTestProfile(page: Page) {
  try {
    const panel = await openProfilesTab(page);
    const delBtn = panel.getByRole('button', { name: new RegExp('Delete profile: ' + TEST_PROFILE_NAME, 'i') });
    if (await delBtn.count() === 0) return;
    await delBtn.first().click();

    const confirmDialog = page.locator('#profiles-panel [role="dialog"][aria-modal="true"]').last();
    await expect(confirmDialog).toBeVisible();
    await confirmDialog.getByRole('button', { name: /^delete$/i }).click();
    await expect(confirmDialog).not.toBeVisible();
  } catch {
    // best-effort cleanup; never fail the suite on teardown
  }
}

test.describe('Quality Profiles', () => {
  test.afterEach(async ({ page }) => {
    await deleteTestProfile(page);
  });

  test('profiles tab loads and shows profile list', async ({ page }) => {
    const panel = await openProfilesTab(page);

    // Should not be in an error state
    const errEl = panel.locator('[role="alert"]');
    if (await errEl.isVisible()) {
      throw new Error('Profiles panel showed error: ' + (await errEl.textContent()));
    }

    await expect(panel.getByRole('button', { name: /new profile/i })).toBeVisible();
  });

  test('create a new profile', async ({ page }) => {
    const panel = await openProfilesTab(page);

    await panel.getByRole('button', { name: /new profile/i }).click();

    const modal = page.locator('#profiles-panel [role="dialog"][aria-modal="true"]').first();
    await expect(modal).toBeVisible();

    await modal.locator('input[type="text"]').first().fill(TEST_PROFILE_NAME);

    // Pick a quality and add it
    await modal.locator('select').first().selectOption({ index: 1 });
    await modal.getByRole('button', { name: /^add$/i }).click();

    const qualityList = modal.locator('[role="list"][aria-label="Qualities in this profile"]');
    await expect(qualityList.locator('[role="listitem"]').first()).toBeVisible();

    await modal.getByRole('button', { name: /create profile/i }).click();

    // Modal closes, success toast appears, profile shows in list
    await expect(modal).not.toBeVisible();
    // Scope to the panel's own toast (x-text="toastMessage"); a global toast
    // (x-text="message") also matches [role=status][aria-live=polite].
    const toast = page.locator('#profiles-panel [role="status"][aria-live="polite"]').last();
    await expect(toast).toContainText(/created/i);
    await expect(panel.getByText(TEST_PROFILE_NAME)).toBeVisible();
  });

  test('edit an existing profile', async ({ page }) => {
    const panel = await openProfilesTab(page);

    const editBtns = panel.getByRole('button', { name: /edit profile/i });
    if (await editBtns.count() === 0) { test.skip(); return; }

    await editBtns.first().click();

    const modal = page.locator('#profiles-panel [role="dialog"][aria-modal="true"]').first();
    await expect(modal).toBeVisible();
    await expect(modal.getByRole('button', { name: /save changes/i })).toBeVisible();

    await page.keyboard.press('Escape');
    await expect(modal).not.toBeVisible();
  });

  test('reorder qualities within a profile', async ({ page }) => {
    const panel = await openProfilesTab(page);

    const editBtns = panel.getByRole('button', { name: /edit profile/i });
    if (await editBtns.count() === 0) { test.skip(); return; }

    await editBtns.first().click();

    const modal = page.locator('#profiles-panel [role="dialog"][aria-modal="true"]').first();
    await expect(modal).toBeVisible();

    const qualityItems = modal.locator('[role="listitem"]');
    await expect(qualityItems.first()).toBeVisible();

    if (await qualityItems.count() >= 2) {
      const firstLabel = await qualityItems.first().locator('span.flex-1').textContent();
      const moveDownBtns = modal.getByRole('button', { name: /quality down/i });
      if (await moveDownBtns.count() > 0) {
        await moveDownBtns.first().click();
        // The previously-first quality should no longer be first.
        await expect(qualityItems.first().locator('span.flex-1')).not.toHaveText(firstLabel || '');
      }
    }

    await page.keyboard.press('Escape');
    await expect(modal).not.toBeVisible();
  });

  test('delete profile shows confirm dialog and cancels', async ({ page }) => {
    const panel = await openProfilesTab(page);

    const deleteBtns = panel.getByRole('button', { name: /delete profile/i });
    if (await deleteBtns.count() === 0) { test.skip(); return; }

    await deleteBtns.first().click();

    const confirmDialog = page.locator('#profiles-panel [role="dialog"][aria-modal="true"]').last();
    await expect(confirmDialog).toBeVisible();
    await expect(confirmDialog.getByText('Delete Profile')).toBeVisible();

    await confirmDialog.getByRole('button', { name: /^cancel$/i }).click();
    await expect(confirmDialog).not.toBeVisible();
  });

  test('delete confirm dialog closes on Escape', async ({ page }) => {
    const panel = await openProfilesTab(page);

    const deleteBtns = panel.getByRole('button', { name: /delete profile/i });
    if (await deleteBtns.count() === 0) { test.skip(); return; }

    await deleteBtns.first().click();

    const confirmDialog = page.locator('#profiles-panel [role="dialog"][aria-modal="true"]').last();
    await expect(confirmDialog).toBeVisible();

    await page.keyboard.press('Escape');
    await expect(confirmDialog).not.toBeVisible();
  });

  test('validation — cannot save profile with empty name', async ({ page }) => {
    const panel = await openProfilesTab(page);

    await panel.getByRole('button', { name: /new profile/i }).click();

    const modal = page.locator('#profiles-panel [role="dialog"][aria-modal="true"]').first();
    await expect(modal).toBeVisible();

    await modal.getByRole('button', { name: /create profile/i }).click();

    const errorRegion = modal.locator('[role="alert"]');
    await expect(errorRegion).toBeVisible();
    await expect(errorRegion).toContainText(/name/i);
    await expect(modal).toBeVisible(); // still open

    await page.keyboard.press('Escape');
  });

  test('Profiles tab renders its heading (basic a11y landmark)', async ({ page }) => {
    const panel = await openProfilesTab(page);
    await expect(panel.locator('h2').first()).toBeVisible();
  });

  test('delete profile via confirm removes it from the list', async ({ page }) => {
    const panel = await openProfilesTab(page);

    // Create the profile we will delete.
    await panel.getByRole('button', { name: /new profile/i }).click();
    const modal = page.locator('#profiles-panel [role="dialog"][aria-modal="true"]').first();
    await modal.locator('input[type="text"]').first().fill(TEST_PROFILE_NAME);
    await modal.locator('select').first().selectOption({ index: 1 });
    await modal.getByRole('button', { name: /^add$/i }).click();
    await modal.getByRole('button', { name: /create profile/i }).click();
    await expect(modal).not.toBeVisible();

    // Delete it via the confirm dialog (exercises the success path + list refresh).
    const delBtn = panel.getByRole('button', { name: new RegExp('Delete profile: ' + TEST_PROFILE_NAME, 'i') });
    await expect(delBtn).toBeVisible();
    await delBtn.click();

    const confirmDialog = page.locator('#profiles-panel [role="dialog"][aria-modal="true"]').last();
    await expect(confirmDialog).toBeVisible();
    await confirmDialog.getByRole('button', { name: /^delete$/i }).click();
    await expect(confirmDialog).not.toBeVisible();

    const toast = page.locator('#profiles-panel [role="status"][aria-live="polite"]').last();
    await expect(toast).toContainText(/deleted/i);
    await expect(panel.getByText(TEST_PROFILE_NAME)).not.toBeVisible();
  });

  test('reordering a profile persists across reload (save_order round-trips)', async ({ page }) => {
    const panel = await openProfilesTab(page);

    // Read the profile order from the edit buttons' accessible names.
    const orderNames = (p = panel) =>
      p.getByRole('button', { name: /^Edit profile:/i }).evaluateAll(
        els => els.map(e => e.getAttribute('aria-label') || ''),
      );

    const before = await orderNames();
    if (before.length < 2) { test.skip(); return; }
    const firstLabel = before[0].replace(/^Edit profile:\s*/i, '');

    // Move the first profile down. With the ids[]/hidden[] repeated-key bug the
    // save_order POST returns success:false and the optimistic swap is rolled
    // back, so the post-request order would still equal `before` — this guards it.
    await panel.getByRole('button', { name: new RegExp('Move ' + firstLabel + ' down in order', 'i') }).click();
    await expect.poll(() => orderNames()).not.toEqual(before);
    const after = await orderNames();
    expect(after[0]).toBe(before[1]);
    expect(after[1]).toBe(before[0]);

    // Re-open the tab → list is re-fetched from the server; order must persist.
    const panel2 = await openProfilesTab(page);
    const persisted = await orderNames(panel2);
    expect(persisted[0]).toBe(before[1]);
    expect(persisted[1]).toBe(before[0]);

    // Restore the original order so the suite stays idempotent.
    await panel2.getByRole('button', { name: new RegExp('Move ' + firstLabel + ' up in order', 'i') }).click();
    await expect.poll(() => orderNames(panel2)).toEqual(before);
  });
});
