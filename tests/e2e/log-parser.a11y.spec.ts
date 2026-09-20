import AxeBuilder from '@axe-core/playwright';
import { test, expect } from './fixtures';
import { waitForPageReady } from './helpers';

async function mockLogs(page) {
  await page.route('**/logging.partial/**', route => route.fulfill({
    status: 200,
    contentType: 'application/json',
    body: JSON.stringify({
      success: true,
      log: ['01-02 03:04:05 ERROR [ accessible-source ] visible severity'],
    }),
  }));
}

async function expectNoLogPanelViolations(page, selector: string) {
  const results = await new AxeBuilder({ page }).include(selector).analyze();
  expect(results.violations).toEqual([]);
}

test('standalone rendered logs retain accessible text and controls', async ({ page }) => {
  await mockLogs(page);
  await page.goto('/logs/');
  await waitForPageReady(page);
  await expect(page.getByText('ERROR', { exact: true })).toBeVisible();
  await expect(page.getByText('visible severity', { exact: true })).toBeVisible();
  await expectNoLogPanelViolations(page, '#main-content');
});

test('the visible Settings Logs panel is scanned after activation', async ({ page }) => {
  await mockLogs(page);
  await page.goto('/settings/');
  await waitForPageReady(page);
  await page.getByRole('tab', { name: 'Logs' }).click();
  await expect(page.locator('#panel-logs').getByText('ERROR', { exact: true })).toBeVisible();
  await expectNoLogPanelViolations(page, '#panel-logs');
});
