import { test, expect } from './fixtures';
import { type Page } from '@playwright/test';

/**
 * FEAT #311: the Trakt watchlist automation's OAuth device code flow, which
 * the shipped new UI has never been able to start (the four backend views
 * exist -- automation.trakt.auth_url / device_code / poll_token /
 * credentials -- but their only caller was trakt.js in the unserved legacy
 * UI). This pins the bespoke control added for it
 * (partials/settings/trakt_auth.html + scripts.html's traktDeviceAuth()),
 * a deliberate one-off rather than a mode on the shared buttonField helper,
 * because that helper is single-shot (fetch, show a message, refresh) and
 * this flow needs a start call followed by a bounded poll loop.
 *
 * Mocked at the API boundary (automation.trakt.device_code /
 * automation.trakt.poll_token) via route interception, same idiom as
 * operator-replace-modal.spec.ts uses for renamer.operator_candidates /
 * renamer.operator_replace -- the flow talks to a third party (Trakt) and
 * is only reachable with a Client ID configured, neither of which this
 * suite can or should provide for real.
 *
 * The Trakt group's config declares `tab: 'automation'`, which
 * scripts.html's `tabRemaps` sends to the tab whose internal key is
 * `display` and whose visible label is "Suggestions" -- so the group is
 * reached via that tab, not one literally named "Automation" or "Trakt".
 */

const DEVICE_CODE_ROUTE = /automation\.trakt\.device_code/;
const POLL_ROUTE = /automation\.trakt\.poll_token/;

function deviceCodeResponse(overrides: Record<string, unknown> = {}) {
  return {
    status: 200,
    contentType: 'application/json',
    body: JSON.stringify({
      success: true,
      user_code: 'ABCD-1234',
      verification_url: 'https://trakt.tv/activate',
      expires_in: 600,
      interval: 1,
      ...overrides,
    }),
  };
}

function pollPendingResponse(interval = 1) {
  return {
    status: 200,
    contentType: 'application/json',
    body: JSON.stringify({ success: false, pending: true, interval }),
  };
}

function pollSuccessResponse() {
  return {
    status: 200,
    contentType: 'application/json',
    body: JSON.stringify({
      success: true,
      message: 'Authorization successful! Trakt is now connected.',
    }),
  };
}

function pollErrorResponse(error: string) {
  return {
    status: 200,
    contentType: 'application/json',
    body: JSON.stringify({ success: false, error }),
  };
}

/**
 * Navigate to Settings, enable the Trakt automation group and give it a
 * Client ID (through the real settings.save API, same as
 * operator-replace-modal.spec.ts's gotoReviewMovie flips its own gate),
 * reload so the group renders open, then land on the tab that actually
 * carries it -- "Suggestions", per tabRemaps above, not "Automation".
 * Returns the group's Start Authorisation button.
 */
async function openTraktGroup(page: Page) {
  await page.goto('/settings/');
  await expect(page.locator('h1')).toContainText('Settings');

  await page.evaluate(async () => {
    await fetch(window.CP.apiBase + '/settings.save/?section=trakt&name=automation_enabled&value=true');
    await fetch(window.CP.apiBase + '/settings.save/?section=trakt&name=automation_client_id&value=e2e-test-client-id');
  });
  await page.reload();
  await expect(page.locator('h1')).toContainText('Settings');

  const suggestionsTab = page.getByRole('tab', { name: /suggestions/i });
  await expect(suggestionsTab).toBeVisible();
  await suggestionsTab.click();

  const startButton = page.locator('[data-testid="trakt-start-auth"]');
  await expect(startButton).toBeVisible({ timeout: 10000 });
  return startButton;
}

test.describe('Trakt device authorisation (FEAT #311)', () => {
  test('starting authorisation displays the code and URL inside a persistent live region', async ({ page }) => {
    const startButton = await openTraktGroup(page);

    // The live region exists, and carries its ARIA contract, BEFORE any
    // action -- this is the whole point of "persistent": nothing conjures
    // it into existence alongside the code it will later show.
    const status = page.locator('[data-testid="trakt-auth-status"]');
    await expect(status).toBeAttached();
    await expect(status).toHaveAttribute('role', 'status');
    await expect(status).toHaveAttribute('aria-live', 'polite');
    await expect(status).not.toContainText('ABCD-1234');

    let deviceCodeRequests = 0;
    await page.route(DEVICE_CODE_ROUTE, (route) => {
      deviceCodeRequests++;
      return route.fulfill(deviceCodeResponse());
    });
    // Never resolves in this test: asserts only the code/URL display step.
    await page.route(POLL_ROUTE, (route) => route.fulfill(pollPendingResponse(30)));

    await startButton.click();

    // The code and the verification link land INSIDE the live region, not
    // merely somewhere on the page -- so a mutation to this element is what
    // a screen reader is asked to announce.
    await expect(status).toContainText('ABCD-1234');
    const codeEl = status.locator('[data-testid="trakt-user-code"]');
    await expect(codeEl).toHaveText('ABCD-1234');

    const link = status.locator('[data-testid="trakt-verification-url"]');
    await expect(link).toHaveAttribute('href', 'https://trakt.tv/activate');
    await expect(link).toHaveAttribute('target', '_blank');
    await expect(link).toHaveAttribute('rel', /noopener/);

    expect(deviceCodeRequests).toBe(1);

    // Re-entry guard: the button is aria-disabled (not disabled) while
    // polling is live, so it stays keyboard-focusable but a click while
    // polling must not fire a second device_code request.
    await expect(startButton).toHaveAttribute('aria-disabled', 'true');
    await startButton.click({ force: true });
    expect(deviceCodeRequests).toBe(1);
  });

  test('a pending poll response keeps the control polling', async ({ page }) => {
    const startButton = await openTraktGroup(page);
    const status = page.locator('[data-testid="trakt-auth-status"]');

    await page.route(DEVICE_CODE_ROUTE, (route) => route.fulfill(deviceCodeResponse({ interval: 1 })));

    let pollRequests = 0;
    await page.route(POLL_ROUTE, (route) => {
      pollRequests++;
      return route.fulfill(pollPendingResponse(1));
    });

    await startButton.click();
    await expect(status).toContainText('ABCD-1234');

    // At least three polls within a few seconds proves the loop keeps
    // going on `pending: true` rather than firing once and stopping.
    await expect.poll(() => pollRequests, { timeout: 8000 }).toBeGreaterThanOrEqual(3);

    // Still displaying the code and still marked busy -- pending is not a
    // terminal state.
    await expect(status).toContainText('ABCD-1234');
    await expect(startButton).toHaveAttribute('aria-disabled', 'true');
  });

  test('a successful poll reports success and refreshes the settings panel', async ({ page }) => {
    const startButton = await openTraktGroup(page);
    const status = page.locator('[data-testid="trakt-auth-status"]');

    await page.route(DEVICE_CODE_ROUTE, (route) => route.fulfill(deviceCodeResponse({ interval: 1 })));

    let pollRequests = 0;
    await page.route(POLL_ROUTE, (route) => {
      pollRequests++;
      return route.fulfill(pollSuccessResponse());
    });

    let settingsReloads = 0;
    await page.route('**/settings/', async (route) => {
      settingsReloads++;
      await route.continue();
    });

    await startButton.click();
    await expect(status).toContainText('ABCD-1234');

    await expect(status).toContainText('Authorization successful! Trakt is now connected.', { timeout: 8000 });
    // The device code is no longer relevant once authorisation succeeded.
    await expect(status).not.toContainText('ABCD-1234');
    expect(pollRequests).toBeGreaterThanOrEqual(1);

    // buttonField.execute()'s re-init approach: panel.init() re-fetches
    // /settings/ so the (now-populated) token fields reflect what the
    // server actually stored, rather than the stale pre-auth values.
    await expect.poll(() => settingsReloads, { timeout: 5000 }).toBeGreaterThanOrEqual(1);

    // Polling has stopped and the control is free to be used again.
    await expect(startButton).toHaveAttribute('aria-disabled', 'false');
  });

  test('an error poll response reports the error and stops polling', async ({ page }) => {
    const startButton = await openTraktGroup(page);
    const status = page.locator('[data-testid="trakt-auth-status"]');

    let deviceCodeRequests = 0;
    await page.route(DEVICE_CODE_ROUTE, (route) => {
      deviceCodeRequests++;
      return route.fulfill(deviceCodeResponse({ interval: 1 }));
    });

    let pollRequests = 0;
    await page.route(POLL_ROUTE, (route) => {
      pollRequests++;
      return route.fulfill(pollErrorResponse('Device code expired. Please start authorization again.'));
    });

    await startButton.click();
    await expect(status).toContainText('ABCD-1234');

    await expect(status).toContainText('Device code expired. Please start authorization again.', { timeout: 8000 });
    await expect(status).not.toContainText('ABCD-1234');

    const requestsAtError = pollRequests;
    expect(requestsAtError).toBeGreaterThanOrEqual(1);

    // Polling stopped: no further poll_token calls arrive after the error.
    await page.waitForTimeout(2500);
    expect(pollRequests).toBe(requestsAtError);

    // The control is usable again -- the user can start over, which begins
    // a fresh device_code call rather than resuming the dead poll loop.
    // (The mocked poll_token route still errors immediately, so the retry
    // is asserted by its request counts, not by the code staying on
    // screen -- it is cleared again the moment the second poll errors,
    // which is correct behaviour, not something to race against.)
    await expect(startButton).toHaveAttribute('aria-disabled', 'false');
    expect(deviceCodeRequests).toBe(1);
    await startButton.click();
    await expect.poll(() => deviceCodeRequests, { timeout: 5000 }).toBe(2);
    await expect.poll(() => pollRequests, { timeout: 5000 }).toBeGreaterThanOrEqual(requestsAtError + 1);
  });
});
