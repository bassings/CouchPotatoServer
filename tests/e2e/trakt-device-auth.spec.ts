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
      message: 'Authorisation successful! Trakt is now connected.',
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

/**
 * The only sanctioned way to assert that the device code is on screen.
 *
 * `expect(status).toContainText('ABCD-1234')` reads textContent from the
 * region wrapper, which is present whether or not the code box is displayed.
 * Setting the box to never display, so nobody could read the code they are
 * told to type in, left every spec in this file green, twice, in two
 * different rounds. Visibility on the code element itself is the assertion
 * that can actually fail, and `scripts/check_test_traps.py` now enforces
 * that any text assertion on these ids is paired with one.
 */
async function expectCodeShown(page: Page) {
  const code = page.locator('[data-testid="trakt-user-code"]');
  await expect(code).toBeVisible({ timeout: 8000 });
  await expect(code).toContainText('ABCD-1234');
}

test.describe('Trakt device authorisation (FEAT #311)', () => {
  // L2: both endpoints are mocked per test below, which is discipline, not a
  // guard -- a forgotten mock (or a future edit that calls Trakt directly
  // from the browser) must fail loudly rather than making a real, slow
  // outbound call during a test run.
  test.beforeEach(async ({ page }) => {
    await page.route('**://api.trakt.tv/**', (route) => route.abort());
  });

  test('L2: a browser-issued call to the real Trakt API is blocked rather than reaching the network', async ({ page }) => {
    // Both specs mock CouchPotato's own device_code/poll_token routes per
    // test, but that is discipline, not a guard -- nothing stops a future
    // edit (or a test that forgets to mock) from making the browser talk to
    // Trakt directly. This pins the beforeEach guard below: it must turn a
    // real outbound call into a loud, immediate failure rather than a slow
    // real network round trip inside a test run.
    await page.goto('/settings/');

    const outcome = await page.evaluate(async () => {
      try {
        await fetch('https://api.trakt.tv/oauth/device/code', { method: 'POST' });
        return 'reached-the-network';
      } catch (e) {
        return 'blocked: ' + (e as Error).message;
      }
    });

    expect(outcome).not.toBe('reached-the-network');
  });

  test('the busy state is announced in the live region, not only on the button label (WCAG 4.1.3)', async ({ page }) => {
    const startButton = await openTraktGroup(page);
    const status = page.locator('[data-testid="trakt-auth-status"]');

    // Hold the device_code response open so the busy window is observable.
    // Against real Trakt this window is genuinely seconds, not milliseconds:
    // the server handler allows a 30s timeout on its outbound call.
    let release: () => void = () => {};
    const held = new Promise<void>((resolve) => { release = resolve; });
    await page.route(DEVICE_CODE_ROUTE, async (route) => {
      await held;
      return route.fulfill(deviceCodeResponse({ interval: 30 }));
    });
    await page.route(POLL_ROUTE, (route) => route.fulfill(pollPendingResponse(30)));

    // Not toHaveText(''): the code box's own template text is in textContent
    // even while hidden, which is exactly the blindness these specs had.
    await expect(status).not.toContainText('Contacting Trakt');
    await startButton.click();

    // The point of the test: the region a screen reader is listening to says
    // something while we are waiting. The button's own label also changes,
    // but that is only read if focus happens to be on the button.
    // toBeVisible on the message element itself, not toContainText on the
    // region: textContent is present while hidden, so text alone cannot
    // tell a working announcement from one nobody can see.
    const message = page.locator('[data-testid="trakt-auth-message"]');
    await expect(message).toBeVisible({ timeout: 8000 });
    await expect(message).toContainText('Contacting Trakt');

    release();
    await expectCodeShown(page);
  });

  test('the button says what it is doing while it waits, in its NAME (WCAG 4.1.2)', async ({ page }) => {
    const startButton = await openTraktGroup(page);

    // The state has to be in the accessible NAME, not only in a description.
    // Pointing aria-describedby at the whole live region made every focus
    // read the verification URL and the code aloud again for the rest of the
    // session; and leaving the label as "Start Trakt Authorisation" for the
    // entire ten minute wait meant a sighted user saw a greyed-out control
    // labelled Start that would not start.
    await expect(startButton).toHaveAccessibleName('Start Trakt Authorisation');
    expect(await startButton.getAttribute('aria-describedby')).toBeNull();

    await page.route(DEVICE_CODE_ROUTE, (route) =>
      route.fulfill(deviceCodeResponse({ interval: 30 })));
    await page.route(POLL_ROUTE, (route) => route.fulfill(pollPendingResponse(30)));

    await startButton.click();
    await expectCodeShown(page);

    await expect(startButton).toHaveAccessibleName('Waiting for Trakt…');
    await expect(startButton).toHaveAttribute('aria-disabled', 'true');
    // Still reachable: aria-disabled, not disabled, so it keeps its place in
    // the tab order. That is precisely why it must not be dimmed, and why
    // this test exists next to the contrast expectations.
    await startButton.focus();
    await expect(startButton).toBeFocused();
  });

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
    await expectCodeShown(page);
    const codeEl = status.locator('[data-testid="trakt-user-code"]');
    await expect(codeEl).toHaveText('ABCD-1234');
    // VISIBLE, not merely present. toHaveText and toContainText read
    // textContent, which display:none does not affect, so every assertion
    // above this line passes on a control the user cannot see. Proven: with
    // `x-show="userCode"` mutated to `x-show="false"`, so the code a user
    // must type into trakt.tv can never appear and the feature is unusable,
    // all 13 tests across both spec files stayed green. The axe scans miss
    // it too, because axe skips hidden subtrees, so "zero violations"
    // quietly degrades from "this control is clean" to "nothing was
    // scanned". This assertion and its siblings below are the only things
    // in either file that can fail on that mutation.
    await expect(codeEl).toBeVisible();

    const link = status.locator('[data-testid="trakt-verification-url"]');
    await expect(link).toBeVisible();
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

  test('the first poll waits for the interval instead of firing immediately', async ({ page }) => {
    const startButton = await openTraktGroup(page);

    // Trakt's interval is the MINIMUM gap between token requests, and the
    // user cannot have typed a code that appeared a moment ago, so an
    // immediate first poll is guaranteed to fail. It also invites the 429
    // slow-down, which doubles the interval for every later poll, making the
    // one request that could never succeed slow down the rest of the flow.
    await page.route(DEVICE_CODE_ROUTE, (route) =>
      route.fulfill(deviceCodeResponse({ interval: 3 })));

    let pollRequests = 0;
    await page.route(POLL_ROUTE, (route) => {
      pollRequests++;
      return route.fulfill(pollPendingResponse(3));
    });

    await startButton.click();
    await expectCodeShown(page);

    // The code is on screen and no poll has gone out yet. Read after a
    // bounded wait well inside the interval, not at the instant of the click:
    // asserting at the same moment cannot tell "not yet" from "never".
    await page.waitForTimeout(1200);
    expect(pollRequests).toBe(0);

    // And it does start, so this is a delay rather than a wall.
    await expect.poll(() => pollRequests, { timeout: 8000 }).toBeGreaterThanOrEqual(1);
  });

  test('a double click starts ONE authorisation, not two (the guard covers its own await)', async ({ page }) => {
    const startButton = await openTraktGroup(page);

    // The re-entry guard has to be claimed synchronously. If the flag is set
    // after the credential flush, the guard is a no-op across a real network
    // round trip, and a double click, which is an ordinary thing to do and
    // exactly the case the flush exists for, puts two runs on the same
    // component: each overwrites userCode and pollTimer, orphaning whichever
    // poll loop loses. That is the concurrent-loop defect this control was
    // fixed for, one step earlier in the same function.
    let deviceCodeRequests = 0;
    await page.route(DEVICE_CODE_ROUTE, async (route) => {
      deviceCodeRequests++;
      return route.fulfill(deviceCodeResponse({ interval: 30 }));
    });
    await page.route(POLL_ROUTE, (route) => route.fulfill(pollPendingResponse(30)));

    // Type first, so a real flush (a fetch, not a microtask hop) sits inside
    // start() and the window is genuinely open.
    const secretField = page.getByLabel('Client Secret', { exact: true });
    await expect(secretField).toBeVisible({ timeout: 10000 });
    await secretField.fill('typed-just-now-secret');

    // Both clicks dispatched in ONE synchronous block. Playwright's second
    // .click() would wait for the element to be "stable", which the spinner
    // animation prevents, so it cannot express a double click on this control
    // at all: the test would time out on actionability rather than measure
    // the race. Dispatching directly is what a real double click does anyway.
    await page.evaluate(() => {
      const b = document.querySelector('[data-testid="trakt-start-auth"]') as HTMLElement;
      b.click();
      b.click();
    });

    await expectCodeShown(page);
    // Read after a bounded wait, not at the click: a second request that has
    // not been issued yet is indistinguishable from one that never will be.
    await page.waitForTimeout(1500);
    expect(deviceCodeRequests).toBe(1);
  });

  test('a credential typed a moment ago is saved before authorisation starts', async ({ page }) => {
    const startButton = await openTraktGroup(page);

    // Settings save on a 500ms debounce. Someone setting Trakt up types the
    // secret and clicks Start, well inside that window, so without a flush
    // the device code is requested using whatever the server had BEFORE the
    // edit: reported as missing while visibly on screen.
    let sawSecretSave = false;
    let secretSavedBeforeDeviceCode = false;
    let deviceCodeRequested = false;

    await page.route(/settings\.save/, async (route) => {
      const body = route.request().postData() || route.request().url();
      if (body.includes('automation_client_secret')) {
        sawSecretSave = true;
        if (!deviceCodeRequested) secretSavedBeforeDeviceCode = true;
      }
      return route.continue();
    });
    await page.route(DEVICE_CODE_ROUTE, (route) => {
      deviceCodeRequested = true;
      return route.fulfill(deviceCodeResponse({ interval: 30 }));
    });
    await page.route(POLL_ROUTE, (route) => route.fulfill(pollPendingResponse(30)));

    // Password fields carry no name attribute; they are reached by their
    // accessible label (field_types.html binds :aria-label from opt.label),
    // and they save on @change, which fires on blur, so the click below is
    // what commits the edit and starts the 500ms debounce.
    const secretField = page.getByLabel('Client Secret', { exact: true });
    await expect(secretField).toBeVisible({ timeout: 10000 });
    await secretField.fill('typed-just-now-secret');

    // Immediately, inside the debounce window. That is the whole point.
    await startButton.click();

    await expect.poll(() => deviceCodeRequested, { timeout: 8000 }).toBe(true);
    expect(sawSecretSave, 'the typed secret was never saved').toBe(true);
    expect(
      secretSavedBeforeDeviceCode,
      'the device code was requested before the typed credential reached the server',
    ).toBe(true);
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
    await expectCodeShown(page);

    // At least three polls within a few seconds proves the loop keeps
    // going on `pending: true` rather than firing once and stopping.
    await expect.poll(() => pollRequests, { timeout: 8000 }).toBeGreaterThanOrEqual(3);

    // Still displaying the code and still marked busy -- pending is not a
    // terminal state.
    await expectCodeShown(page);
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

    // Deliberately NOT asserting the device code appears here. It is only on
    // screen between device_code returning and the first poll succeeding, and
    // this test's mock answers that poll with success immediately, so the
    // window is vanishingly small. That assertion passed when this spec ran
    // alone and failed inside the full gate on a loaded machine, which is the
    // worst kind of test: green until it matters.
    // The code display has its own test above ('starting authorisation
    // displays the code and URL...'), which mocks a PENDING poll on a 30s
    // interval so the code is genuinely stable while it is asserted. This test
    // is about the success path, so it asserts only that.
    const message = page.locator('[data-testid="trakt-auth-message"]');
    await expect(message).toBeVisible({ timeout: 8000 });
    await expect(message).toContainText('Authorisation successful! Trakt is now connected.');
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
      return route.fulfill(pollErrorResponse('Device code expired. Please start authorisation again.'));
    });

    await startButton.click();

    // Deliberately NOT asserting the device code appears here, same
    // reasoning as the success test above (217872c0c): this test's mock
    // answers the poll with an error immediately, so the window where
    // 'ABCD-1234' is on screen before showError() clears it is often too
    // short to land -- reproduced failing 2 of 5 runs in isolation, not
    // just under gate load. The code display has its own stable-window test
    // above, which mocks a PENDING poll on a 30s interval. This test is
    // about the error path, so it asserts only that.
    const message = page.locator('[data-testid="trakt-auth-message"]');
    await expect(message).toBeVisible({ timeout: 8000 });
    await expect(message).toContainText('Device code expired. Please start authorisation again.');
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

  test('H1: navigating away mid-poll stops the poll loop instead of orphaning it', async ({ page }) => {
    // Regression pin for the security review's H1: switching settings tabs
    // tears down this group's x-data (settings.html's x-for is keyed on
    // currentGroups, which is recomputed on tab change and no longer
    // includes this group), but the pending setTimeout inside poll() used
    // to survive the teardown because clearPoll() was only ever called
    // from start()/showSuccess()/showError(). A second "Start Authorisation"
    // click back on this tab then raced the orphaned chain: whichever one
    // consumed the device code on trakt.tv's side succeeded, and the other
    // read back "No device code. Start authorisation first." -- reporting
    // failure to a user whose authorisation had actually succeeded.
    const startButton = await openTraktGroup(page);
    const status = page.locator('[data-testid="trakt-auth-status"]');

    await page.route(DEVICE_CODE_ROUTE, (route) => route.fulfill(deviceCodeResponse({ interval: 1 })));

    let pollRequests = 0;
    await page.route(POLL_ROUTE, (route) => {
      pollRequests++;
      return route.fulfill(pollPendingResponse(1));
    });

    await startButton.click();
    await expectCodeShown(page);

    // Arm the counter and let at least one real poll land before the trigger,
    // so the wait below is measuring the loop stopping, not merely a request
    // that was already in flight.
    await expect.poll(() => pollRequests, { timeout: 5000 }).toBeGreaterThanOrEqual(1);

    // Navigate away: switch to a different settings tab, which removes this
    // group from currentGroups and tears its component down.
    const generalTab = page.getByRole('tab', { name: /^general$/i });
    await generalTab.click();
    await expect(page.locator('[data-testid="trakt-start-auth"]')).not.toBeAttached();

    const countAtNavigation = pollRequests;

    // Wait long enough for at least two more 1s poll intervals to have
    // elapsed. Read only after the bounded wait, not at the same instant as
    // the navigation -- a request already in flight at navigation time would
    // otherwise be misread as the loop continuing.
    await page.waitForTimeout(3000);

    expect(pollRequests).toBe(countAtNavigation);
  });

  test('H1: a poll still IN FLIGHT at teardown does not resurrect the loop', async ({ page }) => {
    // The sibling test above cannot see this. Its mock answers instantly, so
    // at navigation the component is always in the timer-pending state, and
    // its own comment says an in-flight request "would otherwise be misread
    // as the loop continuing" -- it was written to tolerate the exact case
    // that was broken. destroy() clears pollTimer, which cancels a poll that
    // has not started; it does nothing about a fetch already open. poll()
    // then resumed after its await on a torn-down component and scheduled
    // the next one, restarting the chain. Measured before the fix: three
    // further polls after teardown.
    //
    // In production the in-flight window is most of every cycle, not a
    // sliver: pollForToken makes a blocking outbound call to Trakt with a
    // 30 second timeout against a 5 second poll interval.
    const startButton = await openTraktGroup(page);
    const status = page.locator('[data-testid="trakt-auth-status"]');

    await page.route(DEVICE_CODE_ROUTE, (route) => route.fulfill(deviceCodeResponse({ interval: 1 })));

    let pollRequests = 0;
    let releaseHeldPoll: (() => void) | null = null;
    await page.route(POLL_ROUTE, async (route) => {
      pollRequests++;
      // Hold the SECOND poll open across the navigation, so teardown happens
      // while a request is genuinely in flight. The first is answered
      // normally so the loop is demonstrably running before the trigger.
      if (pollRequests === 2) {
        await new Promise<void>((resolve) => {
          releaseHeldPoll = resolve;
        });
      }
      return route.fulfill(pollPendingResponse(1));
    });

    await startButton.click();
    await expectCodeShown(page);
    await expect.poll(() => pollRequests, { timeout: 5000 }).toBe(2);

    // Tear the component down while poll #2 is still open.
    await page.getByRole('tab', { name: /^general$/i }).click();
    await expect(page.locator('[data-testid="trakt-start-auth"]')).not.toBeAttached();

    // Now let the held response land on the destroyed component.
    expect(releaseHeldPoll).not.toBeNull();
    (releaseHeldPoll as unknown as () => void)();

    const countAtNavigation = pollRequests;

    // Three seconds is at least two more 1s intervals. If the resumed poll
    // schedules another, this goes above countAtNavigation.
    await page.waitForTimeout(3000);

    expect(pollRequests).toBe(countAtNavigation);
  });
});
