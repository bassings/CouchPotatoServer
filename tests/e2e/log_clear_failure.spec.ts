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
  await expect(panel.getByRole('alert')).toContainText('Unable to clear all logs');
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
  await expect(page.getByRole('alert').filter({ hasText: 'Unable to clear all logs' })).toBeVisible();
  await expect(page.getByText(entry.message)).toBeVisible();

  await clear.focus();
  await page.keyboard.press('Enter');
  await expect(page.getByText(entry.message)).toBeHidden();
  await expect(page.getByText('No log entries found.')).toBeVisible();
  await expect(page.getByRole('alert').filter({ hasText: 'Unable to clear all logs' })).toBeHidden();
});

for (const surface of ['settings', 'standalone']) {
  test(`${surface} logs retain entries and warning when explicit refresh returns HTTP error`, async ({ page }) => {
    let refreshFails = false;
    await page.route('**/logging.partial/**', route => route.fulfill({
      status: refreshFails ? 503 : 200, contentType: 'application/json',
      body: JSON.stringify(refreshFails ? { success: true, log: [] } : { success: true, log: [entry] }),
    }));
    await page.route('**/logging.clear/**', route => route.fulfill({
      status: 200, contentType: 'application/json',
      body: JSON.stringify({ success: false, error: 'Unable to clear all logs' }),
    }));
    await page.goto(surface === 'settings' ? '/settings/' : '/logs/');
    if (surface === 'settings') await page.getByRole('tab', { name: 'Logs' }).click();
    await expect(page.getByText(entry.message)).toBeVisible();
    await page.getByRole('button', { name: surface === 'settings' ? 'Clear all logs' : 'Clear', exact: true }).click();
    const error = page.locator('[x-show="clearError"]');
    await expect(error).toContainText('Unable to clear all logs');
    refreshFails = true;
    await page.evaluate(async () => {
      const panel = (window as any).Alpine.$data(document.querySelector('[x-data="logsPanel()"]'));
      await panel.refresh(true); // Same forced call used by the Refresh button.
    });
    await expect(page.getByText(entry.message)).toBeVisible();
    await expect(error).toBeVisible();
  });

  test(`${surface} logs ignore a refresh started before a successful clear`, async ({ page }) => {
    let releaseStale!: () => void;
    let signalStale!: () => void;
    const staleStarted = new Promise<void>(resolve => { signalStale = resolve; });
    let holdRefresh = false;
    await page.route('**/logging.partial/**', async route => {
      if (holdRefresh) {
        holdRefresh = false;
        await new Promise<void>(resolve => { releaseStale = resolve; signalStale(); });
      }
      await route.fulfill({ status: 200, contentType: 'application/json',
        body: JSON.stringify({ success: true, log: [entry] }),
      });
    });
    await page.route('**/logging.clear/**', route => route.fulfill({
      status: 200, contentType: 'application/json', body: JSON.stringify({ success: true }),
    }));
    await page.goto(surface === 'settings' ? '/settings/' : '/logs/');
    if (surface === 'settings') await page.getByRole('tab', { name: 'Logs' }).click();
    await expect(page.getByText(entry.message)).toBeVisible();
    holdRefresh = true;
    await page.evaluate(() => {
      const panel = (window as any).Alpine.$data(document.querySelector('[x-data="logsPanel()"]'));
      (window as any).__staleLogRefresh = panel.refresh();
    });
    await staleStarted;
    const clear = page.getByRole('button', { name: surface === 'settings' ? 'Clear all logs' : 'Clear', exact: true });
    await clear.click();
    await expect(page.getByText(entry.message)).toBeHidden();
    releaseStale();
    await page.evaluate(() => (window as any).__staleLogRefresh);
    await expect(page.getByText(entry.message)).toBeHidden();
    await expect(page.getByText('No log entries found.')).toBeVisible();
  });

  test(`${surface} logs keep the pre-clear display until an explicit refresh after failure`, async ({ page }) => {
    let afterFailure = false;
    await page.route('**/logging.partial/**', route => route.fulfill({
      status: 200, contentType: 'application/json',
      body: JSON.stringify({ success: true, log: afterFailure ? [] : [entry] }),
    }));
    await page.route('**/logging.clear/**', route => route.fulfill({
      status: 200, contentType: 'application/json',
      body: JSON.stringify({ success: false, error: 'Unable to clear all logs' }),
    }));
    await page.goto(surface === 'settings' ? '/settings/' : '/logs/');
    if (surface === 'settings') await page.getByRole('tab', { name: 'Logs' }).click();
    await expect(page.getByText(entry.message)).toBeVisible();
    afterFailure = true;
    const clear = page.getByRole('button', { name: surface === 'settings' ? 'Clear all logs' : 'Clear', exact: true });
    await clear.click();
    const error = page.locator('[x-show="clearError"]');
    await expect(error).toContainText('Unable to clear all logs');
    await page.evaluate(async () => {
      const panel = (window as any).Alpine.$data(document.querySelector('[x-data="logsPanel()"]'));
      await panel.refresh(); // Same default call used by the automatic timer.
    });
    await expect(page.getByText(entry.message)).toBeVisible();
    await expect(error).toBeVisible();

    await page.getByRole('button', { name: surface === 'settings' ? 'Refresh logs' : 'Refresh', exact: true }).click();
    await expect(page.getByText('No log entries found.')).toBeVisible();
    await expect(error).toBeHidden();
  });
}
