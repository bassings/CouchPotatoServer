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
    await expect(status).toHaveAttribute('aria-live', 'polite');
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
    await expect(chartsGrid.getByText(/Couldn.t load suggestions/)).toBeVisible();
    // The error panel is an assertive live region so AT users hear the failure.
    await expect(chartsGrid.locator('[role="alert"]')).toBeVisible();

    await chartsGrid.getByRole('button', { name: /try again/i }).click();

    await expect(page.getByTestId('charts-content')).toBeVisible();
    expect(calls).toBeGreaterThanOrEqual(2);
  });
});
