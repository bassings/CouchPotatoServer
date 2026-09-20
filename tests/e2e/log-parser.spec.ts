import { test, expect } from './fixtures';
import { waitForPageReady } from './helpers';

const LOG_RESPONSE = {
  success: true,
  log: [
    { time: '01-02 03:04:05', type: 'debug', message: '[ structured ] object message' },
    '02-03 04:05:06 WARNING [ raw ] legacy message',
    'malformed ERROR <img src=x onerror=globalThis.logParserPwned=true>',
  ],
};

const FILTERED_RESPONSE = {
  success: true,
  lines: ['06-07 08:09:10 WARNING [ filtered ] filtered warning result'],
};

async function mockLogs(page) {
  const requests: string[] = [];
  await page.route('**/logging.partial/**', route => {
    const url = new URL(route.request().url());
    requests.push(url.href);
    return route.fulfill({
      status: 200,
      contentType: 'application/json',
      body: JSON.stringify(url.searchParams.get('type') === 'warning'
        ? FILTERED_RESPONSE
        : LOG_RESPONSE),
    });
  });
  return requests;
}

async function expectParsedEntries(container) {
  await expect(container.getByText('01-02 03:04:05', { exact: true })).toBeVisible();
  await expect(container.getByText('DEBUG', { exact: true })).toBeVisible();
  await expect(container.getByText('[structured]', { exact: true })).toBeVisible();
  await expect(container.getByText('object message', { exact: true })).toBeVisible();
  await expect(container.getByText('02-03 04:05:06', { exact: true })).toBeVisible();
  await expect(container.getByText('WARNING', { exact: true })).toBeVisible();
  await expect(container.getByText('[raw]', { exact: true })).toBeVisible();
  await expect(container.getByText('legacy message', { exact: true })).toBeVisible();
  await expect(container.getByText(
    'malformed ERROR <img src=x onerror=globalThis.logParserPwned=true>',
    { exact: true },
  )).toBeVisible();
}

async function expectFilteredResult(container) {
  await expect(container.getByText('filtered warning result', { exact: true })).toBeVisible();
  await expect(container.getByText('object message', { exact: true })).toHaveCount(0);
}

test('standalone logs render structured, raw, and malformed entries as text', async ({ page }) => {
  const errors: string[] = [];
  page.on('pageerror', error => errors.push(error.message));
  const requests = await mockLogs(page);

  await page.goto('/logs/');
  await waitForPageReady(page);
  const container = page.locator('#log-container');
  await expectParsedEntries(container);

  await expect(page.locator('img[src="x"]')).toHaveCount(0);
  expect(await page.evaluate(() => globalThis.logParserPwned)).toBeUndefined();
  await page.locator('#log-level-filter').selectOption('warning');
  await expect.poll(() => requests.some(url => new URL(url).searchParams.get('type') === 'warning')).toBe(true);
  await expectFilteredResult(container);
  expect(errors).toEqual([]);
});

test('Settings Logs delegates to the same parser and keeps the level query', async ({ page }) => {
  const errors: string[] = [];
  page.on('pageerror', error => errors.push(error.message));
  const requests = await mockLogs(page);

  await page.goto('/settings/');
  await waitForPageReady(page);
  await page.getByRole('tab', { name: 'Logs' }).click();
  const panel = page.locator('#panel-logs');
  await expectParsedEntries(panel.locator('#log-container'));

  await panel.locator('#settings-log-level').selectOption('warning');
  await expect.poll(() => requests.some(url => new URL(url).searchParams.get('type') === 'warning')).toBe(true);
  await expectFilteredResult(panel.locator('#log-container'));
  expect(errors).toEqual([]);
});
