import { test, expect } from './fixtures';

// Deliberately duplicated, NOT imported from isolation-a-mutate.spec.ts:
// importing a .spec.ts file executes its module body, which would
// re-register that file's OWN top-level test() call a second time here.
// Keep this in sync with isolation-a-mutate.spec.ts's ISOLATION_CATEGORY_NAME.
const ISOLATION_CATEGORY_NAME = 'AC-QA-50 Isolation Leak Probe';

/**
 * AC-QA-50, other half of the pair -- see isolation-a-mutate.spec.ts's
 * header for the full rationale, the file-naming/ordering explanation, and
 * how to run this pair deliberately.
 *
 * Asserts the category list is PRISTINE: the category
 * isolation-a-mutate.spec.ts creates (and never deletes) must not be
 * visible from THIS worker's server. Passing at `--workers` >= 2 proves
 * the two specs got separate, isolated servers. It is NOT meaningful at
 * `--workers=1` -- with one worker, this spec and the mutating one
 * necessarily share it (a worker's server persists across every file that
 * worker runs), and per-worker isolation has nothing to isolate from in
 * that case by construction, not by luck.
 */
test('asserts the category list has no leaked mutation from another worker', async ({ page }) => {
  await page.goto('/settings/');
  await expect(page.locator('h1')).toContainText('Settings');

  await page.getByRole('tab', { name: /categories/i }).click();
  const panel = page.locator('#categories-panel');
  await expect(panel).toBeVisible();
  await expect(panel.getByRole('button', { name: /new category/i })).toBeVisible();

  await expect(panel.getByText(ISOLATION_CATEGORY_NAME)).not.toBeVisible();
});
