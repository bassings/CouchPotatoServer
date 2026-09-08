import { test, expect } from './fixtures';
import AxeBuilder from '@axe-core/playwright';
import { type Page } from '@playwright/test';

/**
 * Accessibility coverage for the Trakt device authorisation control
 * (FEAT #311, see trakt-device-auth.spec.ts for the behavioural tests).
 *
 * The default "Settings page should be accessible" scan in
 * accessibility.a11y.spec.ts never reaches this control: settingsPanel()
 * defaults `activeTab` to 'general' and only renders the active tab's
 * groups, and the Trakt group's `tab: 'automation'` gets remapped to
 * 'display' ("Suggestions") -- a tab nobody switches to in that scan. So
 * this is the only place the code/status region and the start button are
 * ever scanned, in both themes, per this project's WCAG 2.2 AA floor.
 *
 * Follows accessibility.a11y.spec.ts's own dark-theme idiom
 * (addInitScript before goto, then confirm the theme actually took before
 * trusting the scan).
 */

const DEVICE_CODE_ROUTE = /automation\.trakt\.device_code/;
const POLL_ROUTE = /automation\.trakt\.poll_token/;

function deviceCodeResponse() {
  return {
    status: 200,
    contentType: 'application/json',
    body: JSON.stringify({
      success: true,
      user_code: 'ABCD-1234',
      verification_url: 'https://trakt.tv/activate',
      expires_in: 600,
      interval: 30,
    }),
  };
}

function pollPendingResponse() {
  return {
    status: 200,
    contentType: 'application/json',
    body: JSON.stringify({ success: false, pending: true, interval: 30 }),
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

function pollErrorResponse() {
  return {
    status: 200,
    contentType: 'application/json',
    body: JSON.stringify({
      success: false,
      error: 'Device code expired. Please start authorization again.',
    }),
  };
}

const WCAG_TAGS = ['wcag2a', 'wcag2aa', 'wcag21a', 'wcag21aa', 'wcag22aa'];

/**
 * Confirm the theme actually took before trusting a scan run under it --
 * load-bearing, not decorative, per accessibility.a11y.spec.ts's own
 * dark-theme idiom. Light is `classList.contains('light') === true`: with no
 * `cp-theme` in localStorage, base.html's init falls through to
 * `prefers-color-scheme`, and playwright.config.ts pins the accessibility
 * project's colour scheme to light -- but that pin is what makes the
 * fallthrough land on light, not a fact this file could otherwise see, so a
 * light-theme test must assert the class exists rather than assume it.
 */
async function expectThemeIsInEffect(page: Page, theme: 'light' | 'dark') {
  await expect
    .poll(() => page.evaluate(() => document.documentElement.classList.contains('light')))
    .toBe(theme === 'light');
}

/**
 * Enable the Trakt group with a Client ID (through the real settings.save
 * API), reload, switch to the "Suggestions" tab the group actually renders
 * under (tabRemaps sends `tab: 'automation'` there), start authorisation
 * against a mocked device_code endpoint and the given poll response, and
 * wait for `expectedStatus` to appear in the live region -- so a scan can
 * target whichever state (pending/success/error) it was called for.
 */
async function openTraktGroupInState(
  page: Page,
  pollResponse: ReturnType<typeof pollPendingResponse>,
  expectedStatus: string,
) {
  await page.route(DEVICE_CODE_ROUTE, (route) => route.fulfill(deviceCodeResponse()));
  await page.route(POLL_ROUTE, (route) => route.fulfill(pollResponse));

  await page.goto('/settings/');
  await expect(page.locator('h1')).toContainText('Settings');

  await page.evaluate(async () => {
    await fetch(window.CP.apiBase + '/settings.save/?section=trakt&name=automation_enabled&value=true');
    await fetch(window.CP.apiBase + '/settings.save/?section=trakt&name=automation_client_id&value=e2e-test-client-id');
  });
  await page.reload();
  await expect(page.getByRole('tablist', { name: 'Settings categories' })).toBeVisible();

  const suggestionsTab = page.getByRole('tab', { name: /suggestions/i });
  await expect(suggestionsTab).toBeVisible();
  await suggestionsTab.click();

  const startButton = page.locator('[data-testid="trakt-start-auth"]');
  await expect(startButton).toBeVisible({ timeout: 10000 });
  await startButton.click();

  await expect(page.locator('[data-testid="trakt-auth-status"]')).toContainText(expectedStatus, { timeout: 8000 });
}

async function openTraktGroupWithCodeDisplayed(page: Page) {
  await openTraktGroupInState(page, pollPendingResponse(), 'ABCD-1234');
}

async function openTraktGroupWithSuccess(page: Page) {
  await openTraktGroupInState(page, pollSuccessResponse(), 'Authorization successful! Trakt is now connected.');
}

async function openTraktGroupWithError(page: Page) {
  await openTraktGroupInState(page, pollErrorResponse(), 'Device code expired. Please start authorization again.');
}

/**
 * Run the standard WCAG scan over the start button and the live region,
 * asserting a violation-free result with the violations themselves in the
 * failure message.
 */
async function scanTraktControl(page: Page, label: string) {
  const results = await new AxeBuilder({ page })
    .withTags(WCAG_TAGS)
    .include('[data-testid="trakt-start-auth"]')
    .include('[data-testid="trakt-auth-status"]')
    .analyze();

  const detail = results.violations
    .flatMap((v) => v.nodes.map((n) => `${v.id}: ${n.html} - ${n.failureSummary}`))
    .join('\n');
  expect(results.violations.length, `${label} violations:\n${detail}`).toBe(0);
}

test.describe('Trakt device authorisation accessibility (FEAT #311)', () => {
  // L2: both endpoints are mocked per test below, which is discipline, not a
  // guard -- a forgotten mock (or a future edit that calls Trakt directly
  // from the browser) must fail loudly rather than making a real, slow
  // outbound call during a test run. Load-bearing proof lives with the
  // sibling test in trakt-device-auth.spec.ts, since the mechanism is
  // identical in both files.
  test.beforeEach(async ({ page }) => {
    await page.route('**://api.trakt.tv/**', (route) => route.abort());
  });

  test('the start button and the populated live region have no WCAG violations (light theme)', async ({ page }) => {
    await openTraktGroupWithCodeDisplayed(page);

    // L3: this scan ran under "light theme" in name only -- nothing here
    // ever confirmed light actually rendered, and it only passed because
    // playwright.config.ts pins colorScheme to 'light' for this project. If
    // that pin ever moves, this becomes a silent second dark scan under a
    // "light theme" name.
    await expectThemeIsInEffect(page, 'light');

    await scanTraktControl(page, 'light theme (pending code)');
  });

  test('the start button and the populated live region have no WCAG violations (dark theme)', async ({ page }) => {
    await page.addInitScript((t) => {
      localStorage.setItem('cp-theme', t);
    }, 'dark');

    await openTraktGroupWithCodeDisplayed(page);
    await expectThemeIsInEffect(page, 'dark');

    await scanTraktControl(page, 'dark theme (pending code)');
  });

  // L3: neither pre-existing scan above ever reached the success or error
  // state, both of which use text-cp-success / text-cp-danger
  // (scripts.html's showSuccess()/showError()) -- the same tokens that
  // needed a light-mode override in base.html after a dark success toast
  // shipped at 3.30:1 contrast. Cover both states in both themes.
  test('the success state has no WCAG violations (light theme)', async ({ page }) => {
    await openTraktGroupWithSuccess(page);
    await expectThemeIsInEffect(page, 'light');

    await scanTraktControl(page, 'light theme (success)');
  });

  test('the success state has no WCAG violations (dark theme)', async ({ page }) => {
    await page.addInitScript((t) => {
      localStorage.setItem('cp-theme', t);
    }, 'dark');

    await openTraktGroupWithSuccess(page);
    await expectThemeIsInEffect(page, 'dark');

    await scanTraktControl(page, 'dark theme (success)');
  });

  test('the error state has no WCAG violations (light theme)', async ({ page }) => {
    await openTraktGroupWithError(page);
    await expectThemeIsInEffect(page, 'light');

    await scanTraktControl(page, 'light theme (error)');
  });

  test('the error state has no WCAG violations (dark theme)', async ({ page }) => {
    await page.addInitScript((t) => {
      localStorage.setItem('cp-theme', t);
    }, 'dark');

    await openTraktGroupWithError(page);
    await expectThemeIsInEffect(page, 'dark');

    await scanTraktControl(page, 'dark theme (error)');
  });

  test('the button label leads with its visible text and the button stays focusable while busy (WCAG 2.5.3 / 2.1.1)', async ({ page }) => {
    await page.route(DEVICE_CODE_ROUTE, (route) => route.fulfill(deviceCodeResponse()));
    await page.route(POLL_ROUTE, (route) => route.fulfill(pollPendingResponse()));

    await page.goto('/settings/');
    await expect(page.locator('h1')).toContainText('Settings');
    await page.evaluate(async () => {
      await fetch(window.CP.apiBase + '/settings.save/?section=trakt&name=automation_enabled&value=true');
      await fetch(window.CP.apiBase + '/settings.save/?section=trakt&name=automation_client_id&value=e2e-test-client-id');
    });
    await page.reload();
    await expect(page.getByRole('tablist', { name: 'Settings categories' })).toBeVisible();
    await page.getByRole('tab', { name: /suggestions/i }).click();

    const startButton = page.locator('[data-testid="trakt-start-auth"]');
    await expect(startButton).toBeVisible({ timeout: 10000 });

    // Resting-state accessible name is exactly the visible text, computed
    // from content rather than an aria-label that could drift from it.
    await expect(startButton).toHaveAccessibleName('Start Trakt Authorisation');
    await expect(startButton).not.toHaveAttribute('disabled', '');

    await startButton.click();
    await expect(page.locator('[data-testid="trakt-user-code"]')).toHaveText('ABCD-1234');

    // Busy: aria-disabled (not the disabled attribute), so it stays in the
    // tab order and a keyboard/AT user can still discover and read it.
    await expect(startButton).toHaveAttribute('aria-disabled', 'true');
    await expect(startButton).not.toHaveAttribute('disabled', '');
    await startButton.focus();
    await expect(startButton).toBeFocused();
  });
});
