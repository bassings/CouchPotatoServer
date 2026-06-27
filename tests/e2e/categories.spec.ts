import { test, expect, Page, Locator } from '@playwright/test';

/**
 * E2E tests for Category management (Settings → Categories tab).
 * Covers: list loads, create, edit-saves-a-change, reorder persists across reload,
 * delete confirm cancel + escape, validation, a11y landmark.
 *
 * Uses condition-based waits (web-first assertions that auto-retry) rather than
 * fixed timeouts, and cleans up any category it creates so the suite is idempotent.
 */

const TEST_CATEGORY_NAME = 'E2E Test Category';
// Deliberately NOT prefixed by TEST_CATEGORY_NAME: the reorder test matches edit
// buttons by exact aria-label, but a name-prefix would still trip substring-based
// helpers (Delete/Edit regexes) and the cleanup, so keep the two names disjoint.
const TEST_CATEGORY_NAME_2 = 'E2E Reorder Category B';

// The Name field is the only required input; target it by its placeholder so the
// selector survives field reordering (a positional input.first() does not).
const NAME_PLACEHOLDER = 'e.g. Horror, Kids, Documentary';

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

  await modal.getByPlaceholder(NAME_PLACEHOLDER).fill(TEST_CATEGORY_NAME);
  await modal.getByRole('button', { name: /create category/i }).click();
  await expect(modal).not.toBeVisible();

  // Wait for the new category to appear in the list
  await expect(panel.getByRole('button', { name: new RegExp('Delete category: ' + TEST_CATEGORY_NAME, 'i') })).toBeVisible();
  return panel;
}

/** Create an additional category by name within an already-open Categories panel. */
async function addCategoryNamed(page: Page, panel: Locator, name: string) {
  await panel.getByRole('button', { name: /new category/i }).click();
  const modal = page.getByTestId('category-edit-modal');
  await expect(modal).toBeVisible();
  await modal.getByPlaceholder(NAME_PLACEHOLDER).fill(name);
  await modal.getByRole('button', { name: /create category/i }).click();
  await expect(modal).not.toBeVisible();
  await expect(panel.getByRole('button', { name: new RegExp('Delete category: ' + name, 'i') })).toBeVisible();
}

/** Delete a single category by exact name via the UI (best-effort, idempotent). */
async function deleteCategoryNamed(page: Page, panel: Locator, name: string) {
  const delBtn = panel.getByRole('button', { name: 'Delete category: ' + name });
  if (await delBtn.count() === 0) return;
  await delBtn.first().click();
  const confirmDialog = page.getByTestId('category-delete-dialog');
  await expect(confirmDialog).toBeVisible();
  await confirmDialog.getByRole('button', { name: /^delete$/i }).click();
  await expect(confirmDialog).not.toBeVisible();
}

/** Remove BOTH test categories via the UI if they exist (idempotent cleanup). */
async function deleteTestCategory(page: Page) {
  try {
    const panel = await openCategoriesTab(page);
    // Exact-name match, not regex: TEST_CATEGORY_NAME would otherwise also match
    // any "… Renamed" leftover, but exact names keep cleanup unambiguous.
    for (const name of [TEST_CATEGORY_NAME, TEST_CATEGORY_NAME + ' Renamed', TEST_CATEGORY_NAME_2]) {
      // Per-entry guard: a stalled delete must not abandon the remaining
      // entries, or a leftover (e.g. TEST_CATEGORY_NAME_2) corrupts the next
      // run's relative-order assertion in the reorder test.
      try {
        await deleteCategoryNamed(page, panel, name);
      } catch {
        // best-effort: skip this entry, continue cleaning the rest
      }
    }
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

    // Fill in the label (required) — target by placeholder, not position
    await modal.getByPlaceholder(NAME_PLACEHOLDER).fill(TEST_CATEGORY_NAME);

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

    await modal.getByPlaceholder(NAME_PLACEHOLDER).fill(renamed);
    await modal.getByRole('button', { name: /save changes/i }).click();
    await expect(modal).not.toBeVisible();
    await expect(panel.getByText(renamed)).toBeVisible();

    // Rename back so afterEach cleanup (deleteTestCategory by original name) finds it
    await panel.getByRole('button', { name: new RegExp('Edit category: ' + renamed, 'i') }).click();
    await expect(modal).toBeVisible();
    await modal.getByPlaceholder(NAME_PLACEHOLDER).fill(TEST_CATEGORY_NAME);
    await modal.getByRole('button', { name: /save changes/i }).click();
    await expect(modal).not.toBeVisible();
    await expect(panel.getByText(TEST_CATEGORY_NAME)).toBeVisible();
  });

  test('reordering a category persists across reload (save_order round-trips)', async ({ page }) => {
    // Create two test categories so this test is self-contained and always runs
    // (a fresh install has 0 categories; unlike quality profiles there are no
    // built-ins). Created A then B → A receives the lower order, so A precedes B.
    const panel = await createTestCategory(page);            // A = TEST_CATEGORY_NAME
    await addCategoryNamed(page, panel, TEST_CATEGORY_NAME_2); // B = TEST_CATEGORY_NAME_2

    // Read the category order from the edit buttons' accessible names (DOM order).
    const orderNames = (p = panel) =>
      p.getByRole('button', { name: /^Edit category:/i }).evaluateAll(
        els => els.map(e => e.getAttribute('aria-label') || ''),
      );
    // Position of a specific test category within the order list, matched on the
    // EXACT aria-label (not substring): TEST_CATEGORY_NAME is a prefix of nothing
    // here, but exact match is the robust contract regardless of other rows.
    const indexOf = async (name: string, p = panel) =>
      (await orderNames(p)).indexOf('Edit category: ' + name);

    // Operate only on the two test rows; never assert on absolute positions, since
    // a non-fresh server may have pre-existing categories above them.
    let idxA = await indexOf(TEST_CATEGORY_NAME);
    let idxB = await indexOf(TEST_CATEGORY_NAME_2);
    expect(idxA).toBeGreaterThanOrEqual(0);
    expect(idxB).toBeGreaterThanOrEqual(0);
    expect(idxA).toBeLessThan(idxB); // A created first → lower order

    // Move A down. With the ids[] repeated-key bug, save_order returns
    // success:false and the optimistic swap is rolled back — this test guards it.
    await panel.getByRole('button', { name: 'Move ' + TEST_CATEGORY_NAME + ' down in order' }).click();

    // A must now come AFTER B (relative order, robust to other rows).
    await expect.poll(async () => (await indexOf(TEST_CATEGORY_NAME)) > (await indexOf(TEST_CATEGORY_NAME_2))).toBe(true);

    // Re-open the tab → list re-fetched from the server; the swap must persist.
    // THIS is the real wire-format guard: a rolled-back optimistic swap would
    // show A before B again here.
    const panel2 = await openCategoriesTab(page);
    expect(await indexOf(TEST_CATEGORY_NAME, panel2)).toBeGreaterThan(await indexOf(TEST_CATEGORY_NAME_2, panel2));

    // Restore original order (A before B) so the suite stays idempotent.
    await panel2.getByRole('button', { name: 'Move ' + TEST_CATEGORY_NAME + ' up in order' }).click();
    await expect.poll(async () => (await indexOf(TEST_CATEGORY_NAME, panel2)) < (await indexOf(TEST_CATEGORY_NAME_2, panel2))).toBe(true);

    // Clean up the second test category (first is cleaned by afterEach).
    await deleteCategoryNamed(page, panel2, TEST_CATEGORY_NAME_2);
  });

  test('reorder failure rolls back the optimistic swap and shows an error toast', async ({ page }) => {
    // The rollback path is where a silent bug would corrupt the list, so force the
    // server to reject the reorder and assert the client reverts cleanly.
    const panel = await createTestCategory(page);            // A
    await addCategoryNamed(page, panel, TEST_CATEGORY_NAME_2); // B

    const orderNames = (p = panel) =>
      p.getByRole('button', { name: /^Edit category:/i }).evaluateAll(
        els => els.map(e => e.getAttribute('aria-label') || ''),
      );
    const indexOf = async (name: string, p = panel) =>
      (await orderNames(p)).indexOf('Edit category: ' + name);

    expect(await indexOf(TEST_CATEGORY_NAME)).toBeLessThan(await indexOf(TEST_CATEGORY_NAME_2));

    // Force save_order to fail (HTTP 200 but success:false — the soft-failure the
    // component checks for after resp.ok). The optimistic swap must roll back.
    await page.route('**/category.save_order/**', route =>
      route.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify({ success: false, message: 'DB locked' }) }),
    );

    await panel.getByRole('button', { name: 'Move ' + TEST_CATEGORY_NAME + ' down in order' }).click();

    // (a) Order reverts to the original (A before B) after the failed save.
    await expect.poll(async () => (await indexOf(TEST_CATEGORY_NAME)) < (await indexOf(TEST_CATEGORY_NAME_2))).toBe(true);

    // (b) An error toast surfaces the failure (error toasts are alert/assertive).
    const toast = page.locator('#categories-panel [role="alert"][aria-live="assertive"]').last();
    await expect(toast).toContainText(/order/i);

    // Stop intercepting before cleanup so the inline delete + afterEach work.
    await page.unroute('**/category.save_order/**');
    await deleteCategoryNamed(page, panel, TEST_CATEGORY_NAME_2);
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

  test('save failure keeps the modal open and shows an error toast', async ({ page }) => {
    const panel = await openCategoriesTab(page);

    await panel.getByRole('button', { name: /new category/i }).click();
    const modal = page.getByTestId('category-edit-modal');
    await expect(modal).toBeVisible();
    await modal.getByPlaceholder(NAME_PLACEHOLDER).fill('Should Not Persist');

    // Force category.save to soft-fail; the modal must stay open and a toast appear.
    await page.route('**/category.save/**', route =>
      route.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify({ success: false, message: 'boom' }) }),
    );

    await modal.getByRole('button', { name: /create category/i }).click();

    const toast = page.locator('#categories-panel [role="alert"][aria-live="assertive"]').last();
    await expect(toast).toContainText(/save failed/i);
    await expect(modal).toBeVisible(); // not closed on failure

    await page.unroute('**/category.save/**');
    await page.keyboard.press('Escape');
    await expect(modal).not.toBeVisible();
    // Nothing was persisted (save was intercepted), so afterEach has nothing extra to clean.
  });

  test('load failure shows the error state', async ({ page }) => {
    // Force category.list to soft-fail BEFORE the tab loads, so load() takes its
    // error branch (loadError set, loaded reset to allow retry).
    await page.route('**/category.list/**', route =>
      route.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify({ success: false }) }),
    );

    await page.goto('/settings/');
    await expect(page.locator('h1')).toContainText('Settings');
    await page.getByRole('tab', { name: /categories/i }).click();

    const panel = page.locator('#categories-panel');
    await expect(panel).toBeVisible();

    // The error block (x-show="!loading && loadError", role="alert") is the only
    // alert in the accessibility tree while the modal is closed.
    const alert = panel.getByRole('alert').filter({ hasText: /failed to load/i });
    await expect(alert).toBeVisible();

    // The New Category button lives in the success-only block and must stay hidden.
    await expect(panel.getByRole('button', { name: /new category/i })).toBeHidden();

    // Unroute so the afterEach cleanup can open the tab normally.
    await page.unroute('**/category.list/**');
  });

  test('new-category modal closes on Escape', async ({ page }) => {
    const panel = await openCategoriesTab(page);

    await panel.getByRole('button', { name: /new category/i }).click();
    const modal = page.getByTestId('category-edit-modal');
    await expect(modal).toBeVisible();
    await expect(modal.locator('h3')).toContainText('New Category');

    await page.keyboard.press('Escape');
    await expect(modal).not.toBeVisible();
  });

  test('edit modal closes on Escape', async ({ page }) => {
    const panel = await createTestCategory(page);

    // Open the edit modal on an existing category (openEdit), not the create flow
    await panel.getByRole('button', { name: new RegExp('Edit category: ' + TEST_CATEGORY_NAME, 'i') }).click();
    const modal = page.getByTestId('category-edit-modal');
    await expect(modal).toBeVisible();
    await expect(modal.locator('h3')).toContainText('Edit Category');

    await page.keyboard.press('Escape');
    await expect(modal).not.toBeVisible();
  });

  test('focus returns to the Edit trigger after closing the edit modal (WCAG 2.4.3)', async ({ page }) => {
    const panel = await createTestCategory(page);
    const editBtn = panel.getByRole('button', { name: new RegExp('Edit category: ' + TEST_CATEGORY_NAME, 'i') });
    await editBtn.click();
    const modal = page.getByTestId('category-edit-modal');
    await expect(modal).toBeVisible();

    await page.keyboard.press('Escape');
    await expect(modal).not.toBeVisible();
    await expect(editBtn).toBeFocused();
  });

  test('focus returns to the Delete trigger after cancelling the delete dialog (WCAG 2.4.3)', async ({ page }) => {
    const panel = await createTestCategory(page);
    const delBtn = panel.getByRole('button', { name: new RegExp('Delete category: ' + TEST_CATEGORY_NAME, 'i') });
    await delBtn.click();
    const dialog = page.getByTestId('category-delete-dialog');
    await expect(dialog).toBeVisible();

    await dialog.getByRole('button', { name: /^cancel$/i }).click();
    await expect(dialog).not.toBeVisible();
    await expect(delBtn).toBeFocused();
  });

  test('focus lands on New Category after a confirmed delete (WCAG 2.4.3)', async ({ page }) => {
    const panel = await createTestCategory(page);
    await panel.getByRole('button', { name: new RegExp('Delete category: ' + TEST_CATEGORY_NAME, 'i') }).click();
    const dialog = page.getByTestId('category-delete-dialog');
    await expect(dialog).toBeVisible();

    await dialog.getByRole('button', { name: /^delete$/i }).click();
    await expect(dialog).not.toBeVisible();
    // The deleted row's trigger is gone, so focus must land on the always-present
    // New Category button rather than dropping to <body>.
    await expect(panel.getByRole('button', { name: /new category/i })).toBeFocused();
    // Nothing left to clean — the category was deleted in-test.
  });

  test('Categories tab renders its heading (basic a11y landmark)', async ({ page }) => {
    const panel = await openCategoriesTab(page);
    // The panel has an h2 visible in the loaded content block
    await expect(panel.locator('h2').first()).toBeVisible();
  });
});
