import type { Locator, Page } from '@playwright/test';
import { test, expect } from './fixtures';

/**
 * The setup wizard for keyboard and screen-reader users (WCAG 2.2 AA: 2.1.1
 * Keyboard, 2.4.3 Focus Order, 2.4.7 Focus Visible, 4.1.2 Name, Role, Value,
 * 4.1.3 Status Messages).
 *
 * Every action under test is a REAL key press (`page.keyboard`), and every
 * control is reached with Tab, so reachability is proven rather than assumed.
 * `.focus()` and `evaluate` are used only to set a scene or to read state.
 *
 * Saves and the Jackett sync are held with routes that the test releases
 * explicitly. Nothing here waits for a duration or depends on which request
 * arrives first: a held request is a settled state the test can observe for
 * as long as it likes.
 *
 * What none of this can confirm: whether a screen reader actually ANNOUNCES a
 * status region, in what order, or how it voices a focused heading. What is
 * checked is the exposed role, the live-region properties and the text.
 */

const PHONE = { width: 375, height: 812 };
const STEP_HEADINGS = [
  'Welcome to CouchPotato', 'Server Security', 'Where to Search',
  'Download Clients', 'Movie Library', "You're All Set!",
];

type Held = { saves: string[]; release: () => void };

/** Hold every settings save until `release()`; record each as `section.name=value`. */
async function holdSaves(page: Page): Promise<Held> {
  const saves: string[] = [];
  let release!: () => void;
  const gate = new Promise<void>((resolve) => { release = resolve; });
  await page.route('**/settings.save/**', async (route) => {
    const params = new URLSearchParams(route.request().postData() || '');
    saves.push(`${params.get('section')}.${params.get('name')}=${params.get('value')}`);
    await gate;
    await route.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify({ success: true }) });
  });
  return { saves, release };
}

/** Answer every save at once, so a step advances without the test holding anything. */
async function acceptSaves(page: Page): Promise<void> {
  await page.route('**/settings.save/**', (route) => route.fulfill({
    status: 200, contentType: 'application/json', body: JSON.stringify({ success: true }),
  }));
}

/** The API answers 200 with success:false when it refuses a save. */
async function refuseSaves(page: Page): Promise<void> {
  await page.route('**/settings.save/**', (route) => route.fulfill({
    status: 200, contentType: 'application/json', body: JSON.stringify({ success: false }),
  }));
}

async function openWizard(page: Page, theme: 'light' | 'dark' = 'light') {
  await page.addInitScript((value) => localStorage.setItem('cp-theme', value), theme);
  await page.goto('/wizard/');
  await expect(page.getByRole('heading', { name: STEP_HEADINGS[0] })).toBeVisible();
  await expect.poll(
    () => page.evaluate(() => document.documentElement.classList.contains('light')),
    { message: `${theme} theme was not applied` },
  ).toBe(theme === 'light');
}

/** Mount a step directly. Scene-setting only: the action under test is never this. */
async function mountStep(page: Page, step: number, extra = '') {
  await page.evaluate(({ n, code }) => {
    const root = document.querySelector('[x-data="setupWizard()"]') as HTMLElement;
    const state = (window as any).Alpine.$data(root);
    // eslint-disable-next-line no-new-func
    new Function('state', `state.currentStep = ${n}; ${code}`)(state);
  }, { n: step, code: extra });
  await expect(page.getByRole('heading', { name: STEP_HEADINGS[step] })).toBeVisible();
}

/** Press Tab until `target` has focus; fails (does not hang) if it is never reached. */
async function tabTo(page: Page, target: Locator, limit = 120) {
  for (let i = 0; i < limit; i += 1) {
    if (await target.evaluate((el) => el === document.activeElement)) return;
    await page.keyboard.press('Tab');
  }
  throw new Error(`Tab never reached ${target} in ${limit} presses: it is not keyboard reachable`);
}

const nextButton = (page: Page) => page.getByRole('button', { name: /^(Continue|Finish Setup|Saving…)$/ });
const backButton = (page: Page) => page.getByRole('button', { name: /Back$/ });
const skipButton = (page: Page) => page.getByRole('button', { name: 'Skip', exact: true });
const heading = (page: Page, step: number) => page.getByRole('heading', { name: STEP_HEADINGS[step] });

/** Where focus is, for a failure message that says more than "not focused". */
async function whereIsFocus(page: Page): Promise<string> {
  return page.evaluate(() => {
    const el = document.activeElement;
    return el ? `<${el.tagName.toLowerCase()}> "${(el.textContent || '').trim().slice(0, 40)}"` : 'nothing';
  });
}

/** `aria-disabled="true"` and no native `disabled`: the control keeps its place in focus. */
async function expectBusyButNotDisabled(button: Locator, what: string) {
  await expect(button, `${what} is not exposed as busy with aria-disabled`).toHaveAttribute('aria-disabled', 'true');
  const native = await button.evaluate((el) => el.hasAttribute('disabled'));
  expect(native, `${what} binds the native disabled attribute to a busy flag, so the browser drops focus from it`).toBe(false);
}

test.describe('keyboard focus is kept through every wizard action', () => {
  test.use({ viewport: PHONE });

  test('Continue holds focus while its save is in flight, then lands on the next step heading', async ({ page }) => {
    const held = await holdSaves(page);
    await openWizard(page);
    await tabTo(page, nextButton(page));
    await page.keyboard.press('Enter');                       // Welcome -> Security (no save)
    await expect(heading(page, 1), `focus is on ${await whereIsFocus(page)}, not the new step's heading`).toBeFocused();

    await tabTo(page, page.locator('#wizard-username'));
    await page.keyboard.type('admin');
    await tabTo(page, nextButton(page));
    await page.keyboard.press('Enter');

    await expect.poll(() => held.saves).toEqual(['core.username=admin']);
    await expectBusyButNotDisabled(nextButton(page), 'Continue');
    await expect(nextButton(page), 'focus left Continue while it was busy').toBeFocused();

    held.release();
    await expect(heading(page, 2), `focus is on ${await whereIsFocus(page)}, not the new step's heading`).toBeFocused();
    expect(await page.evaluate(() => document.activeElement === document.body)).toBe(false);
  });

  test('Finish Setup lands on the final step heading although its own button is gone', async ({ page }) => {
    const held = await holdSaves(page);
    await openWizard(page);
    await mountStep(page, 4);
    await tabTo(page, nextButton(page));
    await expect(nextButton(page)).toHaveAccessibleName('Finish Setup');
    await page.keyboard.press('Enter');

    await expect.poll(() => held.saves.length).toBeGreaterThan(0);
    await expectBusyButNotDisabled(nextButton(page), 'Finish Setup');
    await expect(nextButton(page), 'focus left Finish Setup while it was busy').toBeFocused();

    held.release();
    await expect(heading(page, 5), `focus is on ${await whereIsFocus(page)}, not the final step's heading`).toBeFocused();
  });

  test('Back lands on the previous step heading although the Back button is gone', async ({ page }) => {
    await acceptSaves(page);
    await openWizard(page);
    await mountStep(page, 1);
    await tabTo(page, backButton(page));
    await page.keyboard.press('Enter');
    await expect(heading(page, 0), `focus is on ${await whereIsFocus(page)}, not the previous step's heading`).toBeFocused();
  });

  test('Skip lands on the next step heading although the Skip button is gone', async ({ page }) => {
    await acceptSaves(page);
    await openWizard(page);
    await mountStep(page, 1);
    await tabTo(page, skipButton(page));
    await page.keyboard.press('Enter');
    await expect(heading(page, 2), `focus is on ${await whereIsFocus(page)}, not the next step's heading`).toBeFocused();
  });

  test('a failed save keeps the user on the step, shows the existing error and keeps focus on Continue', async ({ page }) => {
    await refuseSaves(page);
    await openWizard(page);
    await mountStep(page, 1, 'state.formData.username = "admin";');
    await tabTo(page, nextButton(page));
    await page.keyboard.press('Enter');

    // Pinned existing behaviour (AC-QA-8): the toast, and no step change.
    await expect(page.locator('[x-text="message"]')).toContainText(/Failed to save/);
    await expect(heading(page, 1)).toBeVisible();
    await expect(page.locator('[x-text="steps[currentStep]"]')).toHaveText('Security');

    await expect(nextButton(page), `focus is on ${await whereIsFocus(page)} after a failed save`).toBeFocused();
    await expect(nextButton(page)).toHaveAttribute('aria-disabled', 'false');
  });

  test('Sync Trackers from Jackett keeps focus while syncing and when the result arrives', async ({ page }) => {
    const held = await holdSaves(page);
    let releaseSync!: () => void;
    const syncGate = new Promise<void>((resolve) => { releaseSync = resolve; });
    let syncRequests = 0;
    await page.route('**/provider.torrentpotato.jackett_sync/**', async (route) => {
      syncRequests += 1;
      await syncGate;
      await route.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify({ success: true, message: 'Synced 3 trackers' }) });
    });
    await openWizard(page);
    await mountStep(page, 2, `
      state.formData.torrentpotato.enabled = true;
      state.formData.torrentpotato.jackett_url = 'http://jackett.invalid:9117';
      state.formData.torrentpotato.jackett_api_key = 'placeholder-key';
    `);
    const sync = page.getByRole('button', { name: /^(Sync Trackers from Jackett|Syncing…)$/ });
    await tabTo(page, sync);
    await page.keyboard.press('Enter');

    await expect.poll(() => held.saves.length).toBe(1);
    await expectBusyButNotDisabled(sync, 'Sync Trackers from Jackett');
    await expect(sync, 'focus left the sync button while it was busy').toBeFocused();

    held.release();
    await expect.poll(() => syncRequests).toBe(1);
    releaseSync();
    await expect(page.getByText('Synced 3 trackers')).toBeVisible();
    await expect(sync, `focus is on ${await whereIsFocus(page)} once the sync finished`).toBeFocused();
    await expect(sync).toHaveAttribute('aria-disabled', 'false');
  });
});

test.describe('a busy control ignores a second activation', () => {
  test.use({ viewport: PHONE });

  test('pressing Enter twice on a busy Continue sends one set of saves', async ({ page }) => {
    const held = await holdSaves(page);
    await openWizard(page);
    await mountStep(page, 1, 'state.formData.username = "admin"; state.formData.password = "placeholder-secret";');
    await tabTo(page, nextButton(page));
    await page.keyboard.press('Enter');
    await expect.poll(() => held.saves.length).toBe(2);
    await expectBusyButNotDisabled(nextButton(page), 'Continue');

    await page.keyboard.press('Enter');                       // the double activation
    await page.keyboard.press('Space');                       // and the other activation key

    held.release();
    await expect(heading(page, 2)).toBeFocused();
    expect(held.saves.sort(), 'a second activation while busy sent a second set of saves').toEqual([
      'core.password=placeholder-secret', 'core.username=admin',
    ]);
  });

  test('pressing Enter twice on a busy Sync sends one set of requests', async ({ page }) => {
    const held = await holdSaves(page);
    let releaseSync!: () => void;
    const syncGate = new Promise<void>((resolve) => { releaseSync = resolve; });
    let syncRequests = 0;
    await page.route('**/provider.torrentpotato.jackett_sync/**', async (route) => {
      syncRequests += 1;
      await syncGate;
      await route.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify({ success: true, message: 'Synced' }) });
    });
    await openWizard(page);
    await mountStep(page, 2, 'state.formData.torrentpotato.enabled = true;');
    const sync = page.getByRole('button', { name: /^(Sync Trackers from Jackett|Syncing…)$/ });
    await tabTo(page, sync);
    await page.keyboard.press('Enter');
    await expect.poll(() => held.saves.length).toBe(1);
    await expectBusyButNotDisabled(sync, 'Sync Trackers from Jackett');

    await page.keyboard.press('Enter');
    await page.keyboard.press('Space');

    held.release();
    await expect.poll(() => syncRequests).toBe(1);
    releaseSync();
    await expect(page.getByText('Synced', { exact: true })).toBeVisible();
    expect(held.saves, 'a second activation while syncing repeated the saves').toHaveLength(3);
    expect(syncRequests, 'a second activation while syncing started a second sync').toBe(1);
  });

  test('Back, Skip and the step buttons do nothing while a save is in flight', async ({ page }) => {
    const held = await holdSaves(page);
    await openWizard(page);
    await mountStep(page, 1, 'state.formData.username = "admin";');
    await tabTo(page, nextButton(page));
    await page.keyboard.press('Enter');
    await expect.poll(() => held.saves.length).toBe(1);

    // Moving elsewhere mid-save would let the save's own advance skip a step.
    // The controls are focused to set the scene; the Enter is the action.
    await skipButton(page).focus();
    await page.keyboard.press('Enter');
    await backButton(page).focus();
    await page.keyboard.press('Enter');
    await page.locator('[x-data="setupWizard()"] .mb-8 button').first().focus();   // the step-1 indicator
    await page.keyboard.press('Enter');
    await expect(page.locator('[x-text="steps[currentStep]"]'), 'a control moved the wizard while its save was in flight').toHaveText('Security');

    held.release();
    await expect(heading(page, 2)).toBeFocused();
    await expect(page.locator('[x-text="steps[currentStep]"]')).toHaveText('Providers');
  });
});
