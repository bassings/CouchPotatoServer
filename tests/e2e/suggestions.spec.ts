import { test, expect, Page } from '@playwright/test';

/**
 * E2E tests for the Suggestions loading redesign (the ~60s cold-load fix).
 * Covers the behavioural contract of the change:
 *  - Charts (fast, default tab) loads immediately on page load.
 *  - "For You" (the slow personalized call) is DEFERRED until its tab is opened,
 *    so it never blocks the page — the core of the split-load fix.
 *  - The communicative loading panel (role=status live region, staged status,
 *    progress bar, checklist) renders while a partial is in flight.
 *  - The error state offers "Try again" and re-fetches successfully.
 *
 * /partial/charts and /partial/suggestions pull live external chart sources, so
 * every test mocks them with page.route for determinism. The redesign is pure
 * front-end (no backend change), so the real responses are irrelevant here.
 */

const CHARTS_HTML =
  '<div data-testid="charts-content" class="grid"><div class="poster-card">Chart Movie</div></div>';
const SUGGESTIONS_HTML =
  '<div data-testid="suggestions-content" class="grid"><div class="poster-card">For You Movie</div></div>';

interface MockOpts {
  chartsDelayMs?: number;
  chartsStatus?: number;
  suggestionsDelayMs?: number;
}

/** Mock both partial endpoints. Charts/suggestions HTML is deterministic. */
async function mockPartials(page: Page, opts: MockOpts = {}) {
  const { chartsDelayMs = 0, chartsStatus = 200, suggestionsDelayMs = 0 } = opts;
  await page.route('**/partial/charts', async (route) => {
    if (chartsDelayMs) await new Promise((r) => setTimeout(r, chartsDelayMs));
    if (chartsStatus !== 200) {
      await route.fulfill({ status: chartsStatus, contentType: 'text/html', body: 'error' });
      return;
    }
    await route.fulfill({ status: 200, contentType: 'text/html', body: CHARTS_HTML });
  });
  await page.route('**/partial/suggestions', async (route) => {
    if (suggestionsDelayMs) await new Promise((r) => setTimeout(r, suggestionsDelayMs));
    await route.fulfill({ status: 200, contentType: 'text/html', body: SUGGESTIONS_HTML });
  });
}

test.describe('Suggestions loading redesign', () => {
  test('Charts loads immediately on the default tab', async ({ page }) => {
    await mockPartials(page);
    await page.goto('/suggestions');
    await expect(page.getByTestId('charts-content')).toBeVisible();
  });

  test('shows the communicative loading panel while a partial is in flight', async ({ page }) => {
    await mockPartials(page, { chartsDelayMs: 1500 });
    await page.goto('/suggestions');

    const status = page.locator('#charts-grid [role="status"]');
    await expect(status).toBeVisible();
    // role="status" is an implicit polite live region; the per-second elapsed
    // and percentage counters carry aria-hidden so they don't announce a ticker.
    await expect(status.locator('span[aria-hidden="true"]')).toHaveCount(2);
    // Staged status + the "one-time wait" reassurance copy.
    await expect(status).toContainText('Connecting to sources');
    await expect(status).toContainText(/Usually 30.+60s on first load/);

    // …and it resolves to real content once the partial returns.
    await expect(page.getByTestId('charts-content')).toBeVisible();
    await expect(status).toBeHidden();
  });

  test('defers the For You load until its tab is opened (split load)', async ({ page }) => {
    let suggestionsRequested = false;
    page.on('request', (req) => {
      if (req.url().includes('partial/suggestions')) suggestionsRequested = true;
    });
    await mockPartials(page);
    await page.goto('/suggestions');

    // Charts has finished, but the slow For You call has NOT fired — it no
    // longer competes with (or blocks) the page load.
    await expect(page.getByTestId('charts-content')).toBeVisible();
    expect(suggestionsRequested).toBe(false);

    // Opening the tab triggers the deferred fetch.
    await page.getByRole('tab', { name: /for you/i }).click();
    await expect(page.getByTestId('suggestions-content')).toBeVisible();
    expect(suggestionsRequested).toBe(true);
  });

  test('error state offers Try again and re-fetches successfully', async ({ page }) => {
    let calls = 0;
    await page.route('**/partial/charts', async (route) => {
      calls += 1;
      if (calls === 1) {
        await route.fulfill({ status: 500, contentType: 'text/html', body: 'boom' });
        return;
      }
      await route.fulfill({ status: 200, contentType: 'text/html', body: CHARTS_HTML });
    });
    await page.route('**/partial/suggestions', (route) =>
      route.fulfill({ status: 200, contentType: 'text/html', body: SUGGESTIONS_HTML }),
    );

    await page.goto('/suggestions');

    const chartsGrid = page.locator('#charts-grid');
    // Charts tab → tab-accurate error title (the partial is parameterised).
    await expect(chartsGrid.getByText(/Couldn.t load charts/)).toBeVisible();
    // The error panel is an assertive live region so AT users hear the failure.
    await expect(chartsGrid.locator('[role="alert"]')).toBeVisible();

    await chartsGrid.getByRole('button', { name: /try again/i }).click();

    await expect(page.getByTestId('charts-content')).toBeVisible();
    expect(calls).toBeGreaterThanOrEqual(2);
  });

  test('For You error path shows tab-specific copy and retries', async ({ page }) => {
    let calls = 0;
    await page.route('**/partial/charts', (route) =>
      route.fulfill({ status: 200, contentType: 'text/html', body: CHARTS_HTML }),
    );
    await page.route('**/partial/suggestions', async (route) => {
      calls += 1;
      if (calls === 1) {
        await route.fulfill({ status: 500, contentType: 'text/html', body: 'boom' });
        return;
      }
      await route.fulfill({ status: 200, contentType: 'text/html', body: SUGGESTIONS_HTML });
    });

    await page.goto('/suggestions');
    await page.getByRole('tab', { name: /for you/i }).click();

    const personalGrid = page.locator('#suggestions-grid');
    // For You uses its own error title + the cp:retry trigger (vs Charts' load).
    await expect(personalGrid.getByText(/Couldn.t load your suggestions/)).toBeVisible();
    await expect(personalGrid.locator('[role="alert"]')).toBeVisible();

    await personalGrid.getByRole('button', { name: /try again/i }).click();
    await expect(page.getByTestId('suggestions-content')).toBeVisible();
    expect(calls).toBeGreaterThanOrEqual(2);
  });

  test('stall recovery appears after 45s and Keep waiting dismisses it', async ({ page }) => {
    await page.clock.install();
    // Charts never resolves, so the loader runs on into the stall state.
    await page.route('**/partial/charts', () => {
      /* intentionally left pending */
    });

    await page.goto('/suggestions');
    const status = page.locator('#charts-grid [role="status"]');
    await expect(status).toBeVisible();
    await expect(status).toContainText('Connecting to sources');

    // Advance past the 45s stall threshold (controller's _stallAt). runFor (not
    // fastForward) fires the 1s setInterval on every tick so elapsed reaches 46.
    await page.clock.runFor(46000);
    await expect(status).toContainText('Still working');
    // Server-provided stall sub-copy (Charts tab) renders in the stalled state.
    await expect(status).toContainText('Chart sources are taking longer than usual');
    const keepWaiting = status.getByRole('button', { name: /keep waiting/i });
    await expect(keepWaiting).toBeVisible();
    await expect(status.getByRole('link', { name: /skip to library/i })).toBeVisible();

    // Keep waiting clears the stall and returns to the staged status copy.
    await keepWaiting.click();
    await expect(status).not.toContainText('Still working');
    await expect(keepWaiting).toBeHidden();
    // Closed loop: panel returns to normal staged copy (elapsed=46 → stage at=42).
    await expect(status).toContainText('Ranking your matches');

    // keepWaiting pushed _stallAt to elapsed+30 (=76); advancing past it re-stalls.
    await page.clock.runFor(30000);
    await expect(status).toContainText('Still working');
    await expect(status.getByRole('button', { name: /keep waiting/i })).toBeVisible();
  });

  test('For You tab reaches its own stall state when its load hangs', async ({ page }) => {
    await page.clock.install();
    await page.route('**/partial/charts', (route) =>
      route.fulfill({ status: 200, contentType: 'text/html', body: CHARTS_HTML }),
    );
    // The deferred For You load never resolves → its own loader stalls.
    await page.route('**/partial/suggestions', () => {
      /* intentionally left pending */
    });

    await page.goto('/suggestions');
    await page.getByRole('tab', { name: /for you/i }).click();

    const status = page.locator('#suggestions-grid [role="status"]');
    await expect(status).toBeVisible();

    await page.clock.runFor(46000);
    await expect(status).toContainText('Still working');
    // For You gets its own (library-specific) stall sub-copy, not the Charts one.
    await expect(status).toContainText('Personalized picks are taking longer than usual');
    await expect(status.getByRole('button', { name: /keep waiting/i })).toBeVisible();
  });
});
