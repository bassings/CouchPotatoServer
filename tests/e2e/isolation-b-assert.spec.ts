import { test, expect } from './fixtures';
import { ISOLATION_CATEGORY_NAME, awaitMutation } from './isolation-sentinel';

/**
 * AC-QA-50, other half of the pair -- see isolation-a-mutate.spec.ts's
 * header for the full rationale, the file-naming/ordering explanation, and
 * how to run this pair deliberately.
 *
 * Asserts the category list is PRISTINE: the category
 * isolation-a-mutate.spec.ts creates (and never deletes) must not be
 * visible from THIS worker's server.
 *
 * The two preconditions below are the whole test; the visibility assertion
 * on its own is worthless. Playwright runs the two spec files concurrently
 * on separate workers, so this spec used to reach `not.toBeVisible()`
 * before the other had created anything -- passing against an empty world,
 * which per-worker isolation being completely broken would not have
 * changed. And at `--workers=1` both halves share one worker, so the
 * mutation legitimately reaches this server and there is nothing to
 * isolate from; that is a misconfigured run, not a leak, and it fails with
 * a message saying so rather than a confusing "leaked category visible".
 */
test('asserts the category list has no leaked mutation from another worker', async ({ page, workerServer }, testInfo) => {
  const mutation = await awaitMutation(testInfo.project.outputDir);

  expect(
    mutation.baseURL,
    `isolation-a-mutate ran on THIS worker's server (${workerServer.baseURL}), so its ` +
    `category is expected here and nothing about isolation is being tested. That ` +
    `happens when the pair is run on a single worker: use \`npm run test:isolation\`, ` +
    `which pins --workers=2.`,
  ).not.toBe(workerServer.baseURL);

  await page.goto('/settings/');
  await expect(page.locator('h1')).toContainText('Settings');

  await page.getByRole('tab', { name: /categories/i }).click();
  const panel = page.locator('#categories-panel');
  await expect(panel).toBeVisible();
  await expect(panel.getByRole('button', { name: /new category/i })).toBeVisible();

  await expect(panel.getByText(ISOLATION_CATEGORY_NAME)).not.toBeVisible();
});
