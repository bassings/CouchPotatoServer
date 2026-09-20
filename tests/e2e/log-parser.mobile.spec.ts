import { test, expect } from './fixtures';
import { waitForPageReady } from './helpers';

async function mockLogs(page) {
  await page.route('**/logging.partial/**', route => route.fulfill({
    status: 200,
    contentType: 'application/json',
    body: JSON.stringify({
      success: true,
      log: ['01-02 03:04:05 WARNING [ mobile-source ] mobile message'],
    }),
  }));
}

async function expectMobileEntry(page, container) {
  await expect(container.getByText('WARNING', { exact: true })).toBeVisible();
  await expect(container.getByText('mobile message', { exact: true })).toBeVisible();
  const viewportWidth = page.viewportSize()?.width;
  expect(viewportWidth).toBe(393);
  const bounds = await container.boundingBox();
  expect(bounds).not.toBeNull();
  expect(bounds!.x).toBeGreaterThanOrEqual(0);
  expect(bounds!.x + bounds!.width).toBeLessThanOrEqual(viewportWidth!);

  for (const field of [
    container.getByText('WARNING', { exact: true }),
    container.getByText('[mobile-source]', { exact: true }),
    container.getByText('mobile message', { exact: true }),
  ]) {
    const fieldBounds = await field.boundingBox();
    expect(fieldBounds).not.toBeNull();
    expect(fieldBounds!.x).toBeGreaterThanOrEqual(bounds!.x);
    expect(fieldBounds!.x + fieldBounds!.width).toBeLessThanOrEqual(bounds!.x + bounds!.width);
  }

  const documentWidths = await page.evaluate(() => ({
    client: document.documentElement.clientWidth,
    scroll: document.documentElement.scrollWidth,
  }));
  expect(documentWidths.scroll).toBeLessThanOrEqual(documentWidths.client);
}

test('standalone logs remain usable at phone width', async ({ page }) => {
  await mockLogs(page);
  await page.goto('/logs/');
  await waitForPageReady(page);
  await expect(page.getByLabel('Filter by log level')).toBeVisible();
  await expect(page.getByLabel('Auto-refresh')).toBeVisible();
  await expect(page.getByRole('button', { name: 'Refresh', exact: true })).toBeVisible();
  await expect(page.getByRole('button', { name: 'Clear', exact: true })).toBeVisible();
  await expectMobileEntry(page, page.locator('#log-container'));
});

test('Settings Logs remain usable at phone width', async ({ page }) => {
  await mockLogs(page);
  await page.goto('/settings/');
  await waitForPageReady(page);
  await page.getByRole('tab', { name: 'Logs' }).click();
  const panel = page.locator('#panel-logs');
  await expect(panel.getByLabel('Filter by log level')).toBeVisible();
  await expect(panel.getByLabel('Auto-refresh')).toBeVisible();
  await expect(panel.getByRole('button', { name: 'Refresh logs' })).toBeVisible();
  await expect(panel.getByRole('button', { name: 'Clear all logs' })).toBeVisible();
  await expectMobileEntry(page, panel.locator('#log-container'));
});
