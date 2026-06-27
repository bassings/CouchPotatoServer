import { test, expect, Page } from '@playwright/test';

/**
 * E2E tests for Category management (Settings → Categories tab).
 * Covers: list loads, create, edit-saves-a-change, reorder persists across reload,
 * delete confirm cancel + escape, validation, a11y landmark.
 *
 * Uses condition-based waits (web-first assertions that auto-retry) rather than
 * fixed timeouts, and cleans up any category it creates so the suite is idempotent.
 */

const TEST_CATEGORY_NAME = 'E2E Test Category';
const TEST_CATEGORY_NAME_2 = 'E2E Test Category B';

/** Open the Categories tab and wait for its content to finish loading. */
async function openCategoriesTab(page: Page) {
  await page.goto('/settings/');
  await expect(page.locator('h1')).toContainText('Settings');

  const categoriesTab = page.getByRole('tab', { name: /categories/i });
  await expect(categoriesTab).toBeVisible();
  await categoriesTab.click();

  const panel = page.locator('#categories-panel');
  await expect(panel).toBeVisible();

  // The New Category button only renders in the loaded content block
  // (x-show="!loading && !loadError"), so its visibility is a deterministic
  // "load() resolved successfully" signal — no magic delay needed.
  await expect(panel.getByRole('button', { name: /new category/i })).toBeVisible();

  return panel;
}

/** Create a test category and return the panel. Cleans itself up via afterEach. */
async function createTestCategory(page: Page) {
  const panel = await openCategoriesTab(page);
  await panel.getByRole('button', { name: /new category/i }).click();

  // Scope to the panel's own modal, not any global movie/browser dialog
  const modal = page.getByTestId('category-edit-modal');
  await expect(modal).toBeVisible();

  await modal.locator('input').first().fill(TEST_CATEGORY_NAME);
  await modal.getByRole('button', { name: /create category/i }).click();
  await expect(modal).not.toBeVisible();

  // Wait for the new category to appear in the list
  await expect(panel.getByRole('button', { name: new RegExp('Delete category: ' + TEST_CATEGORY_NAME, 'i') })).toBeVisible();
  return panel;
}

/** Remove the test category via the UI if it exists (idempotent cleanup). */
async function deleteTestCategory(page: Page) {
  try {
    const panel = await openCategoriesTab(page);
    const delBtn = panel.getByRole('button', { name: new RegExp('Delete category: ' + TEST_CATEGORY_NAME, 'i') });
    if (await delBtn.count() === 0) return;
    await delBtn.first().click();

    // Scope the confirm dialog to the panel's own dialog
    const confirmDialog = page.getByTestId('category-delete-dialog');
    await expect(confirmDialog).toBeVisible();
    await confirmDialog.getByRole('button', { name: /^delete$/i }).click();
    await expect(confirmDialog).not.toBeVisible();
  } catch {
    // best-effort cleanup; never fail the suite on teardown
  }
}

test.describe('Category management', () => {
  test.afterEach(async ({ page }) => {
    await deleteTestCategory(page);
  });

  test('categories tab loads and shows the list (and header chrome is hidden)', async ({ page }) => {
    const panel = await openCategoriesTab(page);

    // Should not be in an error state
    const errEl = panel.locator('[role="alert"]');
    if (await errEl.isVisible()) {
      throw new Error('Categories panel showed error: ' + (await errEl.textContent()));
    }

    await expect(panel.getByRole('button', { name: /new category/i })).toBeVisible();

    // The settings-level header chrome (Advanced toggle, auto-save indicator) MUST
    // NOT render on a custom-panel tab — categories has its own save flow. Guards
    // the header.html customPanelTabs fix: all three template x-if guards key off
    // !customPanelTabs.includes(activeTab); adding 'categories' to that array hides them.
    await expect(page.getByText('Advanced', { exact: true })).toBeHidden();
  });

  test('create a new category', async ({ page }) => {
    const panel = await openCategoriesTab(page);

    await panel.getByRole('button', { name: /new category/i }).click();

    const modal = page.getByTestId('category-edit-modal');
    await expect(modal).toBeVisible();

    // Fill in the label (required) and an optional field
    await modal.locator('input').first().fill(TEST_CATEGORY_NAME);

    await modal.getByRole('button', { name: /create category/i }).click();

    // Modal closes and category appears in list
    await expect(modal).not.toBeVisible();

    // Scope to the panel's own toast ([role=status][aria-live=polite] scoped to the panel)
    const toast = page.locator('#categories-panel [role="status"][aria-live="polite"]').last();
    await expect(toast).toContainText(/created/i);
    await expect(panel.getByText(TEST_CATEGORY_NAME)).toBeVisible();

    // Guard the order-serialisation bug: created category must have a real index
    // order (= count at create time), NOT the backend default 999.
    const createdOrder = await page.evaluate(async (name) => {
      const r = await fetch(window.CP.apiBase + '/category.list/');
      const d = await r.json();
      const c = (d.categories || []).find((x) => x.label === name);
      return c ? c.order : null;
    }, TEST_CATEGORY_NAME);
    expect(createdOrder).not.toBeNull();
    // The backend stores order as the raw form string; coerce to number for comparison.
    expect(Number(createdOrder)).toBeLessThan(999);
  });

  test('edit an existing category saves the change and persists', async ({ page }) => {
    // Create a test category first, then rename it
    const panel = await createTestCategory(page);
    const modal = page.getByTestId('category-edit-modal');
    const renamed = TEST_CATEGORY_NAME + ' Renamed';

    // Open editor, rename, save
    await panel.getByRole('button', { name: new RegExp('Edit category: ' + TEST_CATEGORY_NAME, 'i') }).click();
    await expect(modal).toBeVisible();
    // The modal title should say "Edit Category"
    await expect(modal.locator('h3')).toContainText('Edit Category');

    await modal.locator('input').first().fill(renamed);
    await modal.getByRole('button', { name: /save changes/i }).click();
    await expect(modal).not.toBeVisible();
    await expect(panel.getByText(renamed)).toBeVisible();

    // Rename back so afterEach cleanup (deleteTestCategory by original name) finds it
    await panel.getByRole('button', { name: new RegExp('Edit category: ' + renamed, 'i') }).click();
    await expect(modal).toBeVisible();
    await modal.locator('input').first().fill(TEST_CATEGORY_NAME);
    await modal.getByRole('button', { name: /save changes/i }).click();
    await expect(modal).not.toBeVisible();
    await expect(panel.getByText(TEST_CATEGORY_NAME)).toBeVisible();
  });

  test('reordering a category persists across reload (save_order round-trips)', async ({ page }) => {
    // Create two test categories so this test is self-contained and always runs
    // (a fresh install has 0 categories; unlike quality profiles there are no built-ins).
    // Clean them up in afterEach via deleteTestCategory (which finds by TEST_CATEGORY_NAME);
    // the second is cleaned up inline at the end of the test.
    const panel = await createTestCategory(page);
    {
      // Create second category via the UI (reuse the openNew → save flow)
      await panel.getByRole('button', { name: /new category/i }).click();
      const modal2 = page.getByTestId('category-edit-modal');
      await expect(modal2).toBeVisible();
      await modal2.locator('input').first().fill(TEST_CATEGORY_NAME_2);
      await modal2.getByRole('button', { name: /create category/i }).click();
      await expect(modal2).not.toBeVisible();
      await expect(panel.getByText(TEST_CATEGORY_NAME_2)).toBeVisible();
    }

    // Read the category order from the edit buttons' accessible names
    const orderNames = (p = panel) =>
      p.getByRole('button', { name: /^Edit category:/i }).evaluateAll(
        els => els.map(e => e.getAttribute('aria-label') || ''),
      );

    const before = await orderNames();
    if (before.length < 2) { test.skip(); return; }
    const firstLabel = before[0].replace(/^Edit category:\s*/i, '');

    // Move the first category down. With the ids[] repeated-key bug, save_order
    // returns success:false and the optimistic swap is rolled back — this test guards it.
    await panel.getByRole('button', { name: new RegExp('Move ' + firstLabel + ' down in order', 'i') }).click();

    // Wait for the optimistic swap to land in the DOM
    await expect.poll(() => orderNames()).not.toEqual(before);
    const after = await orderNames();
    expect(after[0]).toBe(before[1]);
    expect(after[1]).toBe(before[0]);

    // Re-open the tab → list re-fetched from the server; order must persist
    const panel2 = await openCategoriesTab(page);
    const persisted = await orderNames(panel2);
    expect(persisted[0]).toBe(before[1]);
    expect(persisted[1]).toBe(before[0]);

    // Restore original order so the suite stays idempotent
    await panel2.getByRole('button', { name: new RegExp('Move ' + firstLabel + ' up in order', 'i') }).click();
    await expect.poll(() => orderNames(panel2)).toEqual(before);

    // Clean up the second test category (first is cleaned by afterEach)
    const delBtn2 = panel2.getByRole('button', { name: new RegExp('Delete category: ' + TEST_CATEGORY_NAME_2, 'i') });
    if (await delBtn2.count() > 0) {
      await delBtn2.first().click();
      const confirmDialog2 = page.getByTestId('category-delete-dialog');
      await expect(confirmDialog2).toBeVisible();
      await confirmDialog2.getByRole('button', { name: /^delete$/i }).click();
      await expect(confirmDialog2).not.toBeVisible();
    }
  });

  test('delete category shows confirm dialog and cancel dismisses it', async ({ page }) => {
    const panel = await createTestCategory(page);

    await panel.getByRole('button', { name: new RegExp('Delete category: ' + TEST_CATEGORY_NAME, 'i') }).click();

    const confirmDialog = page.getByTestId('category-delete-dialog');
    await expect(confirmDialog).toBeVisible();
    await expect(confirmDialog.getByText('Delete Category')).toBeVisible();

    await confirmDialog.getByRole('button', { name: /^cancel$/i }).click();
    await expect(confirmDialog).not.toBeVisible();

    // Category should still be in the list
    await expect(panel.getByText(TEST_CATEGORY_NAME)).toBeVisible();
  });

  test('delete confirm dialog closes on Escape', async ({ page }) => {
    const panel = await createTestCategory(page);

    await panel.getByRole('button', { name: new RegExp('Delete category: ' + TEST_CATEGORY_NAME, 'i') }).click();

    const confirmDialog = page.getByTestId('category-delete-dialog');
    await expect(confirmDialog).toBeVisible();

    await page.keyboard.press('Escape');
    await expect(confirmDialog).not.toBeVisible();
  });

  test('delete category via confirm removes it from the list', async ({ page }) => {
    const panel = await createTestCategory(page);

    const delBtn = panel.getByRole('button', { name: new RegExp('Delete category: ' + TEST_CATEGORY_NAME, 'i') });
    await expect(delBtn).toBeVisible();
    await delBtn.click();

    const confirmDialog = page.getByTestId('category-delete-dialog');
    await expect(confirmDialog).toBeVisible();
    await confirmDialog.getByRole('button', { name: /^delete$/i }).click();
    await expect(confirmDialog).not.toBeVisible();

    const toast = page.locator('#categories-panel [role="status"][aria-live="polite"]').last();
    await expect(toast).toContainText(/deleted/i);
    await expect(panel.getByText(TEST_CATEGORY_NAME)).not.toBeVisible();
  });

  test('validation — cannot save category with empty name', async ({ page }) => {
    const panel = await openCategoriesTab(page);

    await panel.getByRole('button', { name: /new category/i }).click();

    const modal = page.getByTestId('category-edit-modal');
    await expect(modal).toBeVisible();

    // Click save without filling in the name
    await modal.getByRole('button', { name: /create category/i }).click();

    // Validation error appears and modal stays open
    const errorRegion = modal.locator('[role="alert"]');
    await expect(errorRegion).toBeVisible();
    await expect(errorRegion).toContainText(/name/i);
    await expect(modal).toBeVisible();

    await page.keyboard.press('Escape');
    await expect(modal).not.toBeVisible();
  });

  test('edit modal closes on Escape', async ({ page }) => {
    const panel = await openCategoriesTab(page);

    await panel.getByRole('button', { name: /new category/i }).click();
    const modal = page.getByTestId('category-edit-modal');
    await expect(modal).toBeVisible();

    await page.keyboard.press('Escape');
    await expect(modal).not.toBeVisible();
  });

  test('Categories tab renders its heading (basic a11y landmark)', async ({ page }) => {
    const panel = await openCategoriesTab(page);
    // The panel has an h2 visible in the loaded content block
    await expect(panel.locator('h2').first()).toBeVisible();
  });
});
