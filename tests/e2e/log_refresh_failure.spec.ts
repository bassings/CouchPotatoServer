import { test, expect } from './fixtures';
import type { Locator, Page } from '@playwright/test';

const entry = { time: '10-08 12:00:00', type: 'INFO', message: 'Existing log entry' };
const newerEntry = { ...entry, message: 'Newer log entry' };
const success = (log = [entry]) => JSON.stringify({ success: true, log });

type Surface = 'settings' | 'standalone';

async function openLogs(page: Page, surface: Surface): Promise<Locator> {
  await page.setViewportSize({ width: 393, height: 851 });
  await page.goto(surface === 'settings' ? '/settings/' : '/logs/');
  if (surface === 'settings') await page.getByRole('tab', { name: 'Logs' }).click();
  return page.locator('[x-data="logsPanel()"]');
}

async function retryByKeyboard(page: Page, panel: Locator, surface: Surface) {
  const refresh = panel.getByRole('button', { name: surface === 'settings' ? 'Refresh logs' : 'Refresh', exact: true });
  await refresh.focus();
  await page.keyboard.press('Enter');
}

test('standalone logs start one initial refresh', async ({ page }) => {
  let requests = 0;
  await page.route('**/logging.partial/**', route => {
    requests += 1;
    return route.fulfill({ status: 200, contentType: 'application/json', body: success() });
  });
  const panel = await openLogs(page, 'standalone');
  await expect(panel.getByText(entry.message)).toBeVisible();
  expect(requests).toBe(1);
});

test('settings logs start one initial refresh when the tab opens', async ({ page }) => {
  let requests = 0;
  await page.route('**/logging.partial/**', route => {
    requests += 1;
    return route.fulfill({ status: 200, contentType: 'application/json', body: success() });
  });
  const panel = await openLogs(page, 'settings');
  await expect(panel.getByText(entry.message)).toBeVisible();
  expect(requests).toBe(1);
});

for (const surface of ['settings', 'standalone'] as const) {
  for (const failure of ['http', 'api', 'invalid-json', 'invalid-shape', 'network'] as const) {
    test(`${surface} logs announce an initial ${failure} load failure and retry by keyboard`, async ({ page }) => {
      let requests = 0;
      await page.route('**/logging.partial/**', route => {
        requests += 1;
        if (requests > 1) return route.fulfill({ status: 200, contentType: 'application/json', body: success() });
        if (failure === 'network') return route.abort();
        return route.fulfill({
          status: failure === 'http' ? 503 : 200,
          contentType: 'application/json',
          body: failure === 'invalid-json' ? '{invalid JSON'
            : failure === 'api' ? JSON.stringify({ success: false, log: [] })
              : failure === 'invalid-shape' ? JSON.stringify({ success: true }) : success([]),
        });
      });

      const panel = await openLogs(page, surface);
      await expect(panel.getByRole('alert')).toContainText('Unable to load logs');
      await expect(panel.getByText('No log entries found.')).toBeHidden();
      await retryByKeyboard(page, panel, surface);
      await expect(panel.getByText(entry.message)).toBeVisible();
      await expect(panel.getByRole('alert')).toBeHidden();
    });
  }

  test(`${surface} logs retain entries on failed refresh until a successful retry`, async ({ page }) => {
    let requests = 0;
    await page.route('**/logging.partial/**', route => {
      requests += 1;
      return route.fulfill({
        status: requests === 2 ? 503 : 200, contentType: 'application/json',
        body: requests === 2 ? JSON.stringify({ success: true, log: [] }) : success(),
      });
    });
    const panel = await openLogs(page, surface);
    await expect(panel.getByText(entry.message)).toBeVisible();
    await retryByKeyboard(page, panel, surface);
    await expect(panel.getByRole('alert')).toContainText('Unable to load logs');
    await expect(panel.getByText(entry.message)).toBeVisible();
    await retryByKeyboard(page, panel, surface);
    await expect(panel.getByRole('alert')).toBeHidden();
    await expect(panel.getByText(entry.message)).toBeVisible();
  });

  for (const oldFails of [false, true]) {
    test(`${surface} logs ignore an older ${oldFails ? 'failure' : 'success'} after a newer refresh`, async ({ page }) => {
      let releaseOld!: () => void;
      let signalOld!: () => void;
      const oldStarted = new Promise<void>(resolve => { signalOld = resolve; });
      let requests = 0;
      await page.route('**/logging.partial/**', async route => {
        requests += 1;
        const number = requests;
        if (number === 2) await new Promise<void>(resolve => { releaseOld = resolve; signalOld(); });
        return route.fulfill({
          status: number === 2 && oldFails ? 503 : 200, contentType: 'application/json',
          body: number === 2 ? success([]) : success(number === 3 ? [newerEntry] : [entry]),
        });
      });
      const panel = await openLogs(page, surface);
      await expect(panel.getByText(entry.message)).toBeVisible();
      await page.evaluate(() => {
        const data = (window as any).Alpine.$data(document.querySelector('[x-data="logsPanel()"]'));
        (window as any).__olderRefresh = data.refresh(true);
      });
      await oldStarted;
      await page.evaluate(async () => {
        const data = (window as any).Alpine.$data(document.querySelector('[x-data="logsPanel()"]'));
        await data.refresh(true);
      });
      await expect(panel.getByText(newerEntry.message)).toBeVisible();
      releaseOld();
      await page.evaluate(() => (window as any).__olderRefresh);
      await expect(panel.getByText(newerEntry.message)).toBeVisible();
      await expect(panel.getByRole('alert')).toBeHidden();
    });
  }
}
