import { test, expect } from './fixtures';

/**
 * AC-QA-50: a DIRECT test of per-worker isolation, not just a green suite.
 *
 * This spec mutates global singleton server state (creates a category) and
 * deliberately does NOT clean it up -- unlike every other category-creating
 * test in this suite (categories.spec.ts's own afterEach). The absence of
 * cleanup is the point: isolation-b-assert.spec.ts asserts the category
 * list is pristine, and the only thing that can make that true is a
 * SEPARATE worker with its own database, not test hygiene. Paired with
 * isolation-b-assert.spec.ts; read that file's header too.
 *
 * File naming is load-bearing: Playwright sorts spec files by path,
 * ignoring the order they're passed on the command line, so "a-mutate"
 * before "b-assert" is what guarantees this spec runs BEFORE the other one
 * whenever both land on the SAME worker -- the one ordering that can
 * actually leak. (Reversed names, tried first, always ran assert before
 * mutate regardless of CLI argument order, which passed for the wrong
 * reason: nothing had been created yet.)
 *
 * "Both orders" (per the spec this AC comes from) means varying the WORKER
 * COUNT, not the file order: worker count changes which files land on the
 * same worker vs different ones, which is the actual variable that
 * produced the pre-T1.7 coupling. At `--workers=1` there is only one
 * worker, so this pair necessarily shares it -- that is not a test of
 * isolation, it is a test that isolation cannot apply when there is only
 * one worker to isolate. Run this pair at `--workers` >= 2, e.g.:
 *   npx playwright test tests/e2e/isolation-a-mutate.spec.ts \
 *     tests/e2e/isolation-b-assert.spec.ts --project=chromium --workers=2
 * and again at a different worker count (4, 8), to vary the schedule.
 *
 * The category name is deliberately duplicated in isolation-b-assert.spec.ts
 * rather than imported from here: importing a .spec.ts file executes its
 * module body, which would re-register THIS file's own top-level test()
 * call a second time in the importer.
 */
const ISOLATION_CATEGORY_NAME = 'AC-QA-50 Isolation Leak Probe';

test('mutates global category state and leaves the mutation in place', async ({ page }) => {
  await page.goto('/settings/');
  await expect(page.locator('h1')).toContainText('Settings');

  await page.getByRole('tab', { name: /categories/i }).click();
  const panel = page.locator('#categories-panel');
  await expect(panel).toBeVisible();
  await expect(panel.getByRole('button', { name: /new category/i })).toBeVisible();

  await panel.getByRole('button', { name: /new category/i }).click();
  const modal = page.getByTestId('category-edit-modal');
  await expect(modal).toBeVisible();
  await modal.getByPlaceholder('e.g. Horror, Kids, Documentary').fill(ISOLATION_CATEGORY_NAME);
  await modal.getByRole('button', { name: /create category/i }).click();
  await expect(modal).not.toBeVisible();

  // Confirm the mutation actually landed on THIS worker's server before
  // declaring victory -- a silently-failed create would make the pair pass
  // for the wrong reason (nothing to leak, rather than nothing leaked).
  await expect(
    panel.getByRole('button', { name: new RegExp('Delete category: ' + ISOLATION_CATEGORY_NAME, 'i') }),
  ).toBeVisible();

  // No cleanup. See file header.
});
