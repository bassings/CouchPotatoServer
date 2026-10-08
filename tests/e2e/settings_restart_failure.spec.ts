import { test, expect } from './fixtures';
import type { Page, Route } from '@playwright/test';

type Failure = 'http' | 'api-refusal' | 'handler-error' | 'invalid-json' | 'network';

async function openRestartBanner(page: Page) {
  await page.setViewportSize({ width: 393, height: 851 });
  await page.goto('/settings/');
  await page.evaluate(() => {
    const root = document.querySelector('[x-data="settingsPanel()"]');
    if (!root) throw new Error('Settings panel is absent');
    (window as any).Alpine.$data(root).needsRestart = true;
    (window as any).__restartReloads = 0;
    const oldSetTimeout = window.setTimeout.bind(window);
    window.setTimeout = ((handler: TimerHandler, delay?: number, ...args: any[]) => {
      if (delay === 5000) {
        (window as any).__restartReloads += 1;
        return 0;
      }
      return oldSetTimeout(handler, delay, ...args);
    }) as typeof window.setTimeout;
  });
  const banner = page.getByRole('alert').filter({ hasText: 'Some changes need a restart' });
  await expect(banner).toBeVisible();
  return banner;
}

async function pressRestart(page: Page) {
  const button = page.getByRole('button', { name: 'Restart', exact: true });
  await button.focus();
  await page.keyboard.press('Enter');
}

async function fulfilFailure(route: Route, failure: Failure) {
  if (failure === 'network') return route.abort();
  return route.fulfill({
    status: failure === 'http' ? 503 : 200,
    contentType: 'application/json',
    body: failure === 'invalid-json' ? '{invalid JSON'
      : failure === 'handler-error' ? JSON.stringify({ success: false, error: 'private detail' })
        : failure === 'api-refusal' ? JSON.stringify(false) : JSON.stringify('restarting'),
  });
}

for (const failure of ['http', 'api-refusal', 'handler-error', 'invalid-json', 'network'] as const) {
  test(`Settings restart ${failure} keeps its reminder and retries by keyboard on a phone`, async ({ page }) => {
    let requests = 0;
    await page.route('**/app.restart/**', route => {
      requests += 1;
      if (requests === 1) return fulfilFailure(route, failure);
      return route.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify('restarting') });
    });
    const banner = await openRestartBanner(page);
    await pressRestart(page);
    await expect(page.getByTestId('settings-announcer-assertive')).toContainText('Could not confirm restart');
    await expect(banner).toBeVisible();
    await expect(page.getByText('private detail')).toHaveCount(0);
    expect(await page.evaluate(() => (window as any).__restartReloads)).toBe(0);

    await pressRestart(page);
    await expect(page.getByTestId('settings-announcer-polite')).toContainText('Restarting');
    await expect(banner).toBeHidden();
    expect(await page.evaluate(() => (window as any).__restartReloads)).toBe(1);
    expect(requests).toBe(2);
  });
}

test('a second keyboard activation cannot start a conflicting restart request', async ({ page }) => {
  let requests = 0;
  let firstStarted!: () => void;
  let releaseFirst!: () => void;
  const started = new Promise<void>(resolve => { firstStarted = resolve; });
  await page.route('**/app.restart/**', async route => {
    requests += 1;
    if (requests === 1) {
      firstStarted();
      await new Promise<void>(resolve => { releaseFirst = resolve; });
      return route.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify('restarting') });
    }
    return route.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify(false) });
  });
  const banner = await openRestartBanner(page);
  const button = banner.getByRole('button', { name: 'Restart', exact: true });
  await button.focus();
  await page.keyboard.press('Enter');
  await started;
  await expect(banner.locator('button')).toHaveAttribute('aria-disabled', 'true');
  await expect(banner.locator('button')).toHaveAttribute('aria-busy', 'true');
  await expect(banner.locator('button')).toHaveText('Requesting restart…');
  await expect(banner.locator('button')).toBeFocused();
  await page.keyboard.press('Enter');
  // Give a second request time to reach the route while the first stays pending.
  await page.waitForTimeout(250); // wait-for-timeout-ok: forbidden-event=duplicate-restart-request
  expect(requests).toBe(1);
  releaseFirst();
  await expect(banner).toBeHidden();
  await expect(page.getByTestId('settings-announcer-polite')).toContainText('Restarting');
  expect(await page.evaluate(() => (window as any).__restartReloads)).toBe(1);
});
