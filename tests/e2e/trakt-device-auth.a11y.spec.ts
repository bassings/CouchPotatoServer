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

const WCAG_TAGS = ['wcag2a', 'wcag2aa', 'wcag21a', 'wcag21aa', 'wcag22aa'];

/**
 * Enable the Trakt group with a Client ID (through the real settings.save
 * API), reload, switch to the "Suggestions" tab the group actually renders
 * under (tabRemaps sends `tab: 'automation'` there), start authorisation
 * against mocked endpoints, and wait for the code to display -- so the scan
 * below sees the control in its populated, most complex state rather than
 * its empty resting one.
 */
async function openTraktGroupWithCodeDisplayed(page: Page) {
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

  const suggestionsTab = page.getByRole('tab', { name: /suggestions/i });
  await expect(suggestionsTab).toBeVisible();
  await suggestionsTab.click();

  const startButton = page.locator('[data-testid="trakt-start-auth"]');
  await expect(startButton).toBeVisible({ timeout: 10000 });
  await startButton.click();

  await expect(page.locator('[data-testid="trakt-user-code"]')).toHaveText('ABCD-1234');
}

test.describe('Trakt device authorisation accessibility (FEAT #311)', () => {
  test('the start button and the populated live region have no WCAG violations (light theme)', async ({ page }) => {
    await openTraktGroupWithCodeDisplayed(page);

    const results = await new AxeBuilder({ page })
      .withTags(WCAG_TAGS)
      .include('[data-testid="trakt-start-auth"]')
      .include('[data-testid="trakt-auth-status"]')
      .analyze();

    const detail = results.violations
      .flatMap((v) => v.nodes.map((n) => `${v.id}: ${n.html} — ${n.failureSummary}`))
      .join('\n');
    expect(results.violations.length, `light theme violations:\n${detail}`).toBe(0);
  });

  test('the start button and the populated live region have no WCAG violations (dark theme)', async ({ page }) => {
    await page.addInitScript((t) => {
      localStorage.setItem('cp-theme', t);
    }, 'dark');

    await openTraktGroupWithCodeDisplayed(page);

    // Load-bearing, not decorative: confirms the scan below is actually
    // reading the dark theme rather than silently falling back to light.
    await expect
      .poll(() => page.evaluate(() => document.documentElement.classList.contains('light')))
      .toBe(false);

    const results = await new AxeBuilder({ page })
      .withTags(WCAG_TAGS)
      .include('[data-testid="trakt-start-auth"]')
      .include('[data-testid="trakt-auth-status"]')
      .analyze();

    const detail = results.violations
      .flatMap((v) => v.nodes.map((n) => `${v.id}: ${n.html} — ${n.failureSummary}`))
      .join('\n');
    expect(results.violations.length, `dark theme violations:\n${detail}`).toBe(0);
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
