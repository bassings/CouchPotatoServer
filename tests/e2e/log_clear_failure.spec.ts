import { test, expect } from './fixtures';

const entry = { time: '10-08 12:00:00', type: 'INFO', message: 'Test log entry to preserve' };

test('settings logs retain entries on an API refusal and clear after keyboard retry on a phone', async ({ page }) => {
  await page.setViewportSize({ width: 393, height: 851 });
  let attempts = 0;
  let cleared = false;
  await page.route('**/logging.partial/**', route => route.fulfill({
    status: 200, contentType: 'application/json',
    body: JSON.stringify({ success: true, log: cleared ? [] : [entry] }),
  }));
  await page.route('**/logging.clear/**', route => {
    attempts += 1;
    if (attempts > 1) cleared = true;
    return route.fulfill({
      status: 200, contentType: 'application/json',
      body: JSON.stringify(attempts === 1
        ? { success: false, error: 'Unable to clear all logs' } : { success: true }),
    });
  });
  await page.goto('/settings/');
  await page.getByRole('tab', { name: 'Logs' }).click();
  const panel = page.getByRole('tabpanel', { name: 'Logs' });
  await expect(panel.getByText(entry.message)).toBeVisible();
  const clear = panel.getByRole('button', { name: 'Clear all logs' });
  await clear.focus();
  await page.keyboard.press('Enter');
  await expect(panel.getByRole('alert')).toContainText('Unable to clear logs');
  await expect(panel.getByText(entry.message)).toBeVisible();

  await clear.focus();
  await page.keyboard.press('Enter');
  await expect(panel.getByText(entry.message)).toBeHidden();
  await expect(panel.getByText('No log entries found.')).toBeVisible();
  await expect(panel.getByRole('alert')).toBeHidden();
});

test('standalone logs retain entries on HTTP failure and clear after retry on a phone', async ({ page }) => {
  await page.setViewportSize({ width: 393, height: 851 });
  let attempts = 0;
  let cleared = false;
  await page.route('**/logging.partial/**', route => route.fulfill({
    status: 200, contentType: 'application/json',
    body: JSON.stringify({ success: true, log: cleared ? [] : [entry] }),
  }));
  await page.route('**/logging.clear/**', route => {
    attempts += 1;
    if (attempts > 1) cleared = true;
    return route.fulfill({
      status: attempts === 1 ? 503 : 200, contentType: 'application/json',
      body: JSON.stringify({ success: true }),
    });
  });
  await page.goto('/logs/');
  await expect(page.getByText(entry.message)).toBeVisible();
  const clear = page.getByRole('button', { name: 'Clear', exact: true });
  await clear.focus();
  await page.keyboard.press('Enter');
  await expect(page.getByRole('alert').filter({ hasText: 'Unable to clear logs' })).toBeVisible();
  await expect(page.getByText(entry.message)).toBeVisible();

  await clear.focus();
  await page.keyboard.press('Enter');
  await expect(page.getByText(entry.message)).toBeHidden();
  await expect(page.getByText('No log entries found.')).toBeVisible();
  await expect(page.getByRole('alert').filter({ hasText: 'Unable to clear logs' })).toBeHidden();
});
