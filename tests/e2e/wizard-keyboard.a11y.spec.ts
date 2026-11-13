import type { Locator, Page } from '@playwright/test';
import { test, expect } from './fixtures';
import { expectDialogNamedByUniqueHeading, expectVisualTransitionsToSettle } from './helpers';

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
  // Say so at once if there is nothing to reach, rather than waiting out the test timeout on `evaluate`.
  await expect(target, `there is nothing matching ${target} to Tab to`).toHaveCount(1);
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
    await expect(page.locator('p[x-text="jackettSyncResult"]')).toHaveText('Synced 3 trackers');
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
    // The request count is asserted BEFORE anything about focus, so that removing the re-entry guard
    // fails on the extra requests it sends (it would otherwise also fail on the heading, which the
    // second activation's extra step change moves on).
    await expect(page.locator('[x-text="steps[currentStep]"]')).not.toHaveText('Security');
    await expect(nextButton(page)).toHaveAttribute('aria-disabled', 'false');
    expect(held.saves.sort(), 'a second activation while busy sent a second set of saves').toEqual([
      'core.password=placeholder-secret', 'core.username=admin',
    ]);
    await expect(heading(page, 2)).toBeFocused();
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
    await expect(page.locator('p[x-text="jackettSyncResult"]')).toHaveText('Synced');
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

  test('Back, Skip and the reachable step buttons say they are busy while a save is in flight, and say it no longer once it ends', async ({ page }) => {
    const held = await holdSaves(page);
    await openWizard(page);
    await mountStep(page, 1, 'state.formData.username = "admin";');
    const reachable = [backButton(page), skipButton(page), page.locator('[x-data="setupWizard()"] .mb-8 button').nth(0), page.locator('[x-data="setupWizard()"] .mb-8 button').nth(1)];
    for (const control of reachable) await expect(control).toHaveAttribute('aria-disabled', 'false');

    await tabTo(page, nextButton(page));
    await page.keyboard.press('Enter');
    await expect.poll(() => held.saves.length).toBe(1);
    for (const control of reachable) {
      await expect(control, 'an inert control during a save is not exposed as aria-disabled').toHaveAttribute('aria-disabled', 'true');
    }
    // Still focusable, never natively disabled: they must not drop focus either.
    expect(await backButton(page).evaluate((el) => el.hasAttribute('disabled'))).toBe(false);

    held.release();
    await expect(heading(page, 2)).toBeFocused();
    await expect(backButton(page)).toHaveAttribute('aria-disabled', 'false');
    await expect(page.locator('[x-data="setupWizard()"] .mb-8 button').nth(0)).toHaveAttribute('aria-disabled', 'false');
  });
});

const directoryListing = {
  success: true, dirs: ['/movies/', '/shows/'], parent: '/', home: '/', is_root: false, platform: 'posix',
};

/** The four places the wizard opens the folder browser from, each a "Browse" button beside its own input. */
const OPENERS = [
  { label: 'Download Folder', step: 4, scene: '', field: '#wizard-renamer-from' },
  { label: 'Movie Library', step: 4, scene: '', field: '#wizard-renamer-to' },
  { label: 'NZB Watch Folder', step: 3, scene: 'state.formData.blackholeEnabled = true;', field: '#wizard-blackhole-nzb-dir' },
  { label: 'Torrent Watch Folder', step: 3, scene: 'state.formData.blackholeEnabled = true;', field: '#wizard-blackhole-torrent-dir' },
] as const;

const browseButtonFor = (page: Page, field: string) => page.locator(field).locator('xpath=..').getByRole('button', { name: 'Browse', exact: true });
// Located by its x-show, not its role, so the behaviour tests below fail for the behaviour
// they name and only the first test fails for a missing role.
const folderDialog = (page: Page) => page.locator('[x-show="browserOpen"]');

/** True when the focused element is inside the dialog; the failure message names where focus is instead. */
async function expectFocusInDialog(page: Page, context: string) {
  const inside = await folderDialog(page).evaluate((el) => el.contains(document.activeElement));
  expect(inside, `${context}: focus is on ${await whereIsFocus(page)}, outside the dialog`).toBe(true);
}

/**
 * Wait until the dialog has taken focus. Its move-in is released by Alpine's timer-based $nextTick, so
 * a key pressed before it lands races that timer (seen as "focus is on <body>" after a close path).
 * Every test that opens the dialog waits here before its next key press.
 */
async function waitForFocusInDialog(page: Page) {
  await expect.poll(() => folderDialog(page).evaluate((el) => el.contains(document.activeElement)), {
    message: 'opening the folder browser did not move focus into it',
  }).toBe(true);
}

async function openFolderBrowser(page: Page, opener: (typeof OPENERS)[number]) {
  await page.route('**/directory.list/**', (route) => route.fulfill({
    status: 200, contentType: 'application/json', body: JSON.stringify(directoryListing),
  }));
  await acceptSaves(page);
  await openWizard(page);
  await mountStep(page, opener.step, opener.scene);
  const browse = browseButtonFor(page, opener.field);
  await tabTo(page, browse);
  await page.keyboard.press('Enter');
  await waitForFocusInDialog(page);
  return browse;
}

type Listing = { dirs: string[]; fail?: boolean };

/**
 * Serve a different listing per path, with the answers the test can change and hold. `hold(path)` makes
 * the next request for that path wait until the returned function is called.
 */
async function routeListings(page: Page, listings: Record<string, Listing>) {
  const holds = new Map<string, Promise<void>>();
  await page.route('**/directory.list/**', async (route) => {
    const path = decodeURIComponent(new URL(route.request().url()).searchParams.get('path') || '/');
    const held = holds.get(path);
    if (held) { holds.delete(path); await held; }
    const entry = listings[path];
    if (!entry || entry.fail) {
      await route.fulfill({ status: 503, contentType: 'application/json', body: JSON.stringify({ success: false }) });
      return;
    }
    await route.fulfill({
      status: 200, contentType: 'application/json',
      body: JSON.stringify({ success: true, dirs: entry.dirs, parent: '/', home: '/', is_root: path === '/', platform: 'posix' }),
    });
  });
  return {
    hold(path: string) {
      let release!: () => void;
      holds.set(path, new Promise<void>((resolve) => { release = resolve; }));
      return release;
    },
  };
}

/** Open the dialog from "Download Folder" with `listings` served; returns the Browse button. */
async function openWithListings(page: Page, listings: Record<string, Listing>) {
  const served = await routeListings(page, listings);
  await acceptSaves(page);
  await openWizard(page);
  await mountStep(page, 4);
  const browse = browseButtonFor(page, '#wizard-renamer-from');
  await tabTo(page, browse);
  await page.keyboard.press('Enter');
  await waitForFocusInDialog(page);
  return { browse, served };
}

const folderRow = (page: Page, name: string) => folderDialog(page).getByRole('button', { name, exact: true });

test.describe('the folder browser is a modal dialog', () => {
  test.use({ viewport: PHONE });

  test('it is exposed as a modal dialog named "Browse Folders"', async ({ page }) => {
    await openFolderBrowser(page, OPENERS[0]);
    const dialog = page.getByRole('dialog', { name: 'Browse Folders' });
    await expect(dialog, 'the folder browser has no role="dialog"').toBeVisible();
    await expect(dialog).toHaveAttribute('aria-modal', 'true');
    await expect(dialog).toHaveJSProperty('tagName', 'DIV');
    await expectDialogNamedByUniqueHeading(page, dialog, 'Browse Folders', 3);
  });

  for (const opener of OPENERS) {
    test(`opening it from "${opener.label}" moves focus in, Escape closes it and focus returns to that Browse button`, async ({ page }) => {
      const browse = await openFolderBrowser(page, opener);
      await expect(folderDialog(page)).toBeVisible();
      await expect.poll(() => folderDialog(page).evaluate((el) => el.contains(document.activeElement)), {
        message: 'opening the folder browser did not move focus into it',
      }).toBe(true);

      await page.keyboard.press('Escape');
      await expect(folderDialog(page)).toBeHidden();
      // This button, not "a" Browse button: the four are identical to a screen reader.
      await expect(browse, `focus is on ${await whereIsFocus(page)}, not the Browse button that opened the dialog`).toBeFocused();
    });
  }

  for (const opener of OPENERS) {
    // Safari does not focus a button on click, so document.activeElement is <body> when the
    // handler runs. Chromium is made to behave the same by cancelling the mousedown default.
    test(`opening it by a click that does not focus the button ("${opener.label}") still returns focus to that button`, async ({ page }) => {
      await page.route('**/directory.list/**', (route) => route.fulfill({
        status: 200, contentType: 'application/json', body: JSON.stringify(directoryListing),
      }));
      await acceptSaves(page);
      await openWizard(page);
      await mountStep(page, opener.step, opener.scene);
      const browse = browseButtonFor(page, opener.field);
      await browse.evaluate((el) => el.addEventListener('mousedown', (e) => e.preventDefault()));
      await browse.click();
      expect(await browse.evaluate((el) => el === document.activeElement), 'the click focused the button, so this is not the Safari case').toBe(false);

      await expect(folderDialog(page).getByRole('button', { name: 'movies', exact: true })).toBeVisible();
      await waitForFocusInDialog(page);
      await page.keyboard.press('Escape');
      await expect(folderDialog(page)).toBeHidden();
      await expect(browse, `focus is on ${await whereIsFocus(page)}, not the Browse button that opened the dialog`).toBeFocused();
    });
  }

  test('Cancel, the close button and Select This Folder each return focus to the Browse button', async ({ page }) => {
    const opener = OPENERS[1];                                // Movie Library: not the first Browse on the page
    const browse = await openFolderBrowser(page, opener);
    const dialog = folderDialog(page);
    await expect(dialog.getByRole('button', { name: 'movies', exact: true })).toBeVisible();

    await tabTo(page, dialog.getByRole('button', { name: 'Cancel', exact: true }));
    await page.keyboard.press('Enter');
    await expect(dialog).toBeHidden();
    await expect(browse, `after Cancel, focus is on ${await whereIsFocus(page)}`).toBeFocused();

    await page.keyboard.press('Enter');                       // reopen from the focused Browse button
    await expect(dialog.getByRole('button', { name: 'movies', exact: true })).toBeVisible();
    await waitForFocusInDialog(page);
    await tabTo(page, dialog.getByRole('button', { name: 'Close directory browser', exact: true }));
    await page.keyboard.press('Enter');
    await expect(dialog).toBeHidden();
    await expect(browse, `after the close button, focus is on ${await whereIsFocus(page)}`).toBeFocused();

    await page.keyboard.press('Enter');
    await expect(dialog.getByRole('button', { name: 'movies', exact: true })).toBeVisible();
    await waitForFocusInDialog(page);
    await tabTo(page, dialog.getByRole('button', { name: 'Select This Folder', exact: true }));
    await page.keyboard.press('Enter');
    await expect(dialog).toBeHidden();
    await expect(page.locator(opener.field), 'Select This Folder did not fill the field it was opened for').toHaveValue('/');
    await expect(page.locator('#wizard-renamer-from')).toHaveValue('');
    await expect(browse, `after Select, focus is on ${await whereIsFocus(page)}`).toBeFocused();
  });

  test('Tab and Shift+Tab cycle inside the dialog and never reach the page behind it', async ({ page }) => {
    await openFolderBrowser(page, OPENERS[0]);
    const dialog = folderDialog(page);
    await expect(dialog.getByRole('button', { name: 'shows', exact: true })).toBeVisible();
    const stops = await dialog.getByRole('button').count();  // Close, Up, 2 folders, Cancel, Select
    expect(stops).toBeGreaterThanOrEqual(5);

    const seen = new Set<string>();
    for (let i = 0; i < stops * 2 + 1; i += 1) {
      await page.keyboard.press('Tab');
      await expectFocusInDialog(page, `Tab press ${i + 1}`);
      seen.add(await page.evaluate(() => (document.activeElement?.textContent || document.activeElement?.getAttribute('aria-label') || '').trim()));
    }
    expect(seen.size, 'Tab did not visit every control in the dialog').toBeGreaterThanOrEqual(stops);

    for (let i = 0; i < stops * 2 + 1; i += 1) {
      await page.keyboard.press('Shift+Tab');
      await expectFocusInDialog(page, `Shift+Tab press ${i + 1}`);
    }
  });

  test('Tab from the last control wraps to the first, and Shift+Tab from the first wraps to the last', async ({ page }) => {
    await openFolderBrowser(page, OPENERS[0]);
    const dialog = folderDialog(page);
    const first = dialog.getByRole('button', { name: 'Close directory browser', exact: true });
    const last = dialog.getByRole('button', { name: 'Select This Folder', exact: true });
    await expect(dialog.getByRole('button', { name: 'shows', exact: true })).toBeVisible();

    await last.focus();
    await page.keyboard.press('Tab');
    await expect(first, `focus is on ${await whereIsFocus(page)}`).toBeFocused();
    await page.keyboard.press('Shift+Tab');
    await expect(last, `focus is on ${await whereIsFocus(page)}`).toBeFocused();
  });

  test('Tab pressed with nothing focused still lands inside the dialog, not on the page behind', async ({ page }) => {
    await openFolderBrowser(page, OPENERS[0]);
    await expect(folderDialog(page).getByRole('button', { name: 'shows', exact: true })).toBeVisible();
    // Wait for the dialog to have taken focus first: its move-in is released by a timer, and blurring
    // before it lands is a race with that timer (seen 2 in 40 runs under CPU load), not the scene.
    await expect.poll(() => folderDialog(page).evaluate((el) => el.contains(document.activeElement))).toBe(true);
    await page.evaluate(() => (document.activeElement as HTMLElement | null)?.blur());   // e.g. after a click on the backdrop
    expect(await page.evaluate(() => document.activeElement === document.body), `focus is on ${await whereIsFocus(page)} after blur`).toBe(true);

    await page.keyboard.press('Tab');
    await expectFocusInDialog(page, 'Tab from <body>');
  });

  test('opening a folder row by keyboard, two levels deep, keeps focus in the dialog and lands on the first row', async ({ page }) => {
    const { served } = await openWithListings(page, {
      '/': { dirs: ['/a/', '/b/'] },
      '/a/': { dirs: ['/a/x/', '/a/y/'] },
      '/a/x/': { dirs: ['/a/x/deep/'] },
      '/a/x/deep/': { dirs: [] },
    });
    await expect(folderRow(page, 'a')).toBeVisible();
    // A successful listing shows no error box and no Retry (the "hide" direction of the error container).
    const errorBox = folderDialog(page).locator('[role="alert"]');
    const retryButton = folderDialog(page).getByRole('button', { name: 'Retry', exact: true });
    await expect(errorBox, 'an empty error box shows over a successful listing').toBeHidden();
    await expect(retryButton, 'a stray Retry shows over a successful listing').toBeHidden();

    // Level one: the focused row is removed while the next listing loads. Hold it to look at that moment.
    const releaseA = served.hold('/a/');
    await tabTo(page, folderRow(page, 'a'));
    await page.keyboard.press('Enter');
    await expectFocusInDialog(page, 'while /a/ is loading');
    await expect(errorBox, 'an error box shows while a listing loads').toBeHidden();
    await expect(retryButton, 'Retry shows while a listing loads').toBeHidden();
    releaseA();
    await expect(folderRow(page, 'x')).toBeVisible();
    await expect(folderRow(page, 'x'), `after /a/ loaded, focus is on ${await whereIsFocus(page)}`).toBeFocused();

    // Level two.
    const releaseX = served.hold('/a/x/');
    await page.keyboard.press('Enter');
    await expectFocusInDialog(page, 'while /a/x/ is loading');
    releaseX();
    await expect(folderRow(page, 'deep')).toBeVisible();
    await expect(folderRow(page, 'deep'), `after /a/x/ loaded, focus is on ${await whereIsFocus(page)}`).toBeFocused();
  });

  test('opening a folder that turns out to be empty puts focus on Up, inside the dialog', async ({ page }) => {
    const { served } = await openWithListings(page, {
      '/': { dirs: ['/empty/'] },
      '/empty/': { dirs: [] },
    });
    await expect(folderRow(page, 'empty')).toBeVisible();
    const release = served.hold('/empty/');
    await tabTo(page, folderRow(page, 'empty'));
    await page.keyboard.press('Enter');
    await expectFocusInDialog(page, 'while /empty/ is loading');
    release();
    await expect(folderDialog(page).getByText('Empty folder')).toBeVisible();
    await expect(folderDialog(page).getByRole('button', { name: /Up$/ }), `focus is on ${await whereIsFocus(page)}`).toBeFocused();
  });

  test('a failed listing puts focus on Retry, a second failure keeps it there, and a success moves it to the first row', async ({ page }) => {
    const listings: Record<string, Listing> = {
      '/': { dirs: ['/bad/'] },
      '/bad/': { dirs: [], fail: true },
    };
    const { served } = await openWithListings(page, listings);
    await expect(folderRow(page, 'bad')).toBeVisible();
    const retry = folderDialog(page).getByRole('button', { name: 'Retry', exact: true });

    await tabTo(page, folderRow(page, 'bad'));
    await page.keyboard.press('Enter');
    await expect(folderDialog(page).getByRole('alert')).toContainText('Unable to list directory');
    await expect(retry, `after the failed load, focus is on ${await whereIsFocus(page)}`).toBeFocused();

    // Retry fails again. Retry's own container is hidden while it loads: focus must not fall out.
    const release = served.hold('/bad/');
    await page.keyboard.press('Enter');
    await expectFocusInDialog(page, 'while Retry is loading');
    release();
    await expect(folderDialog(page).getByRole('alert')).toContainText('Unable to list directory');
    await expect(retry, `after the second failure, focus is on ${await whereIsFocus(page)}`).toBeFocused();

    // Now it works.
    listings['/bad/'] = { dirs: ['/bad/ok/'] };
    await page.keyboard.press('Enter');
    await expect(folderRow(page, 'ok')).toBeVisible();
    await expect(folderRow(page, 'ok'), `after the successful retry, focus is on ${await whereIsFocus(page)}`).toBeFocused();
  });

  test('focus the user has already moved elsewhere is not pulled back when a listing arrives', async ({ page }) => {
    const { served } = await openWithListings(page, {
      '/': { dirs: ['/a/'] },
      '/a/': { dirs: ['/a/x/'] },
    });
    await expect(folderRow(page, 'a')).toBeVisible();
    const release = served.hold('/a/');
    await tabTo(page, folderRow(page, 'a'));
    await page.keyboard.press('Enter');
    const cancel = folderDialog(page).getByRole('button', { name: 'Cancel', exact: true });
    await tabTo(page, cancel);                                // the user moves on while it loads
    release();
    await expect(folderRow(page, 'x')).toBeVisible();
    await expect(cancel, `a late listing pulled focus to ${await whereIsFocus(page)}`).toBeFocused();
  });

  test('a listing still in flight when the dialog is closed does not move focus when the dialog is opened again', async ({ page }) => {
    const { browse, served } = await openWithListings(page, {
      '/': { dirs: ['/a/'] },
      '/a/': { dirs: ['/a/x/'] },
    });
    await expect(folderRow(page, 'a')).toBeVisible();
    served.hold('/a/');                                       // never released: the old request stays in flight
    await tabTo(page, folderRow(page, 'a'));
    await page.keyboard.press('Enter');                       // focus is parked on Up while it loads
    await page.keyboard.press('Escape');
    await expect(folderDialog(page)).toBeHidden();
    await expect(browse).toBeFocused();

    const releaseRoot = served.hold('/');
    await page.keyboard.press('Enter');                       // open again; its own listing is held
    await waitForFocusInDialog(page);
    await page.evaluate(() => (document.activeElement as HTMLElement | null)?.blur());
    releaseRoot();
    await expect(folderRow(page, 'a')).toBeVisible();
    expect(await page.evaluate(() => document.activeElement === document.body), `a stale park moved focus to ${await whereIsFocus(page)}`).toBe(true);
  });

  test('Enter then Escape with no wait between leaves focus on the Browse button, not <body>', async ({ page }) => {
    await page.route('**/directory.list/**', (route) => route.fulfill({
      status: 200, contentType: 'application/json', body: JSON.stringify(directoryListing),
    }));
    await acceptSaves(page);
    await openWizard(page);
    await mountStep(page, 4);
    const browse = browseButtonFor(page, '#wizard-renamer-from');
    await tabTo(page, browse);
    await page.keyboard.press('Enter');
    await page.keyboard.press('Escape');                      // no wait: the dialog's focus timer is still pending
    await expect(folderDialog(page)).toBeHidden();
    // Let the timers queued before this one run (the dialog's own move-in is among them), then look again.
    await page.evaluate(() => new Promise<void>((resolve) => { setTimeout(resolve, 0); }));
    await page.evaluate(() => new Promise<void>((resolve) => { setTimeout(resolve, 0); }));
    await expect(browse, `after a quick open and close, focus is on ${await whereIsFocus(page)}`).toBeFocused();
  });
});

test.describe('Browse is inert while a save is in flight', () => {
  test.use({ viewport: PHONE });

  for (const opener of OPENERS) {
    test(`pressing Browse ("${opener.label}") during a held save does not open the dialog and says it is busy`, async ({ page }) => {
      const held = await holdSaves(page);
      let listings = 0;
      await page.route('**/directory.list/**', (route) => {
        listings += 1;
        return route.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify(directoryListing) });
      });
      await openWizard(page);
      await mountStep(page, opener.step, opener.scene);
      const browse = browseButtonFor(page, opener.field);
      await expect(browse).toHaveAttribute('aria-disabled', 'false');

      await tabTo(page, nextButton(page));
      await page.keyboard.press('Enter');
      await expect.poll(() => held.saves.length).toBeGreaterThan(0);
      await expect(browse, 'Browse is not exposed as busy during a save').toHaveAttribute('aria-disabled', 'true');
      expect(await browse.evaluate((el) => el.hasAttribute('disabled'))).toBe(false);

      await browse.focus();                                    // scene: the control is reachable
      await page.keyboard.press('Enter');
      // The component's own state first: it is set in the click handler itself, so unlike the rendered
      // dialog (shown by Alpine a moment later) it cannot be read too early.
      const opened = await page.evaluate(() => (window as any).Alpine.$data(document.querySelector('[x-data="setupWizard()"]')).browserOpen);
      expect(opened, 'the folder browser opened during a save').toBe(false);
      await expect(folderDialog(page), 'the folder browser is showing during a save').toBeHidden();
      expect(listings, 'a listing was requested during a save').toBe(0);

      held.release();
      await expect(heading(page, opener.step + 1)).toBeFocused();
      await expect(folderDialog(page)).toBeHidden();
    });
  }
});

test.describe('step headings are focus targets, not tab stops', () => {
  test.use({ viewport: PHONE });

  test('every step heading has tabindex -1', async ({ page }) => {
    await openWizard(page);
    for (let step = 0; step < STEP_HEADINGS.length; step += 1) {
      await expect(page.locator(`#wizard-step-heading-${step}`), `heading of step ${step + 1}`).toHaveAttribute('tabindex', '-1');
    }
  });

  test('Tab through each step never stops on its heading', async ({ page }) => {
    await acceptSaves(page);
    await openWizard(page);
    for (let step = 0; step < STEP_HEADINGS.length; step += 1) {
      await mountStep(page, step);
      await page.evaluate(() => (document.activeElement as HTMLElement | null)?.blur());
      // Step 6 has no Continue: its last control is the Start Searching link.
      const last = step < 5 ? nextButton(page) : page.getByRole('link', { name: 'Start Searching' });
      const stops: string[] = [];
      for (let i = 0; i < 150; i += 1) {
        await page.keyboard.press('Tab');
        stops.push(await page.evaluate(() => document.activeElement?.id || ''));
        if (await last.evaluate((el) => el === document.activeElement)) break;
      }
      expect(await last.evaluate((el) => el === document.activeElement), `Tab never reached the end of step ${step + 1}`).toBe(true);
      expect(stops.filter((id) => id.startsWith('wizard-step-heading')), `Tab stopped on the heading of step ${step + 1}`).toEqual([]);
    }
  });
});

const STEP_NAMES = ['Welcome', 'Security', 'Providers', 'Downloader', 'Library', 'Done'];
const indicators = (page: Page) => page.locator('[x-data="setupWizard()"] .mb-8 button');

test.describe('the step indicator names each step and marks the current one', () => {
  test.use({ viewport: PHONE });

  test('every step button has a name with its position, its step and whether it is complete, and only the current one is aria-current', async ({ page }) => {
    await acceptSaves(page);
    await openWizard(page);
    await expect(indicators(page)).toHaveCount(6);

    for (let current = 0; current < 6; current += 1) {
      for (let idx = 0; idx < 6; idx += 1) {
        const done = idx < current ? ', completed' : '';
        await expect(
          indicators(page).nth(idx),
          `step button ${idx + 1} on step ${current + 1} is named by its glyph alone`,
        ).toHaveAccessibleName(`Step ${idx + 1} of 6: ${STEP_NAMES[idx]}${done}`);
      }
      // Exactly one is current, and it is the right one.
      await expect(page.locator('[x-data="setupWizard()"] .mb-8 button[aria-current]'), `step ${current + 1}: not exactly one aria-current`).toHaveCount(1);
      await expect(indicators(page).nth(current), `aria-current is not on step ${current + 1}`).toHaveAttribute('aria-current', 'step');

      if (current < 5) {
        await tabTo(page, nextButton(page));
        await page.keyboard.press('Enter');
        await expect(heading(page, current + 1)).toBeFocused();
      }
    }
  });

  test('a step button not yet reached is natively disabled and carries no aria-disabled; reached ones read "false"', async ({ page }) => {
    await acceptSaves(page);
    await openWizard(page);
    await mountStep(page, 2);
    for (let idx = 0; idx < 6; idx += 1) {
      const button = indicators(page).nth(idx);
      if (idx > 2) {
        await expect(button, `step ${idx + 1} is not natively disabled`).toBeDisabled();
        await expect(button, `step ${idx + 1} (not reached) has aria-disabled as well as disabled`).not.toHaveAttribute('aria-disabled', /.*/);
      } else {
        await expect(button, `reached step ${idx + 1}`).toHaveAttribute('aria-disabled', 'false');
      }
    }
  });

  test('going back moves aria-current and clears "completed" from the steps ahead', async ({ page }) => {
    await acceptSaves(page);
    await openWizard(page);
    await mountStep(page, 3);
    await tabTo(page, backButton(page));
    await page.keyboard.press('Enter');
    await expect(heading(page, 2)).toBeFocused();

    await expect(indicators(page).nth(2)).toHaveAttribute('aria-current', 'step');
    await expect(indicators(page).nth(3)).not.toHaveAttribute('aria-current', /.*/);
    await expect(indicators(page).nth(3)).toHaveAccessibleName('Step 4 of 6: Downloader');
  });
});

// Owner decision 2026-11-13: Usenet / Torrents / Both is a pick-one group (a radio group), not three
// toggles. Only the actual choice is checked, so choosing Both checks ONLY Both. The highlight is
// deliberately left as it was (Both still tints all three), and that mismatch is recorded as debt.
const SOURCE_TRUTH = {
  usenet: { Usenet: 'true', Torrents: 'false', Both: 'false' },
  torrents: { Usenet: 'false', Torrents: 'true', Both: 'false' },
  both: { Usenet: 'false', Torrents: 'false', Both: 'true' },
} as const;
const sourceGroup = (page: Page) => page.getByRole('radiogroup');
const sourceRadio = (page: Page, name: string) => sourceGroup(page).getByRole('radio', { name: new RegExp(`^${name}`) });
const checkedSource = (page: Page) => sourceGroup(page).locator('[role="radio"][aria-checked="true"]');

/** Reach `target` the way a keyboard user does: Tab to the group's one tab stop, then Arrow to the radio. */
async function focusSourceRadio(page: Page, target: Locator) {
  await tabTo(page, checkedSource(page));
  for (let i = 0; i < 3; i += 1) {
    if (await target.evaluate((el) => el === document.activeElement)) return;
    await page.keyboard.press('ArrowRight');
  }
  await expect(target, 'Arrow keys never reached the radio').toBeFocused();
}

test.describe('the source choice is a radio group', () => {
  test.use({ viewport: PHONE });

  test('the group is named by the question already on the page, and the three radios carry no aria-pressed', async ({ page }) => {
    await acceptSaves(page);
    await openWizard(page);
    await mountStep(page, 2);
    const group = sourceGroup(page);
    await expect(group, 'the three source buttons are not a radiogroup').toHaveCount(1);
    await expect(group).toHaveAccessibleName('Choose how you want to find movies.');
    await expect(group).not.toHaveAttribute('aria-label', /.*/);
    const labelledby = await group.getAttribute('aria-labelledby');
    expect(labelledby, 'the group is named by something other than text already on the page').toBeTruthy();
    await expect(page.locator(`[id="${labelledby}"]`)).toHaveText('Choose how you want to find movies.');
    await expect(group.getByRole('radio')).toHaveCount(3);
    await expect(group.locator('[aria-pressed]'), 'a pick-one choice still carries aria-pressed').toHaveCount(0);
  });

  test('aria-checked is true only for the actual choice, and Both checks only Both while all three stay highlighted', async ({ page }) => {
    await acceptSaves(page);
    await openWizard(page);
    await mountStep(page, 2);
    // Start is "torrents". Arrow to each choice in turn: Usenet, then Torrents, then Both.
    for (const choice of ['usenet', 'torrents', 'both'] as const) {
      const pick = choice === 'usenet' ? 'Usenet' : choice === 'torrents' ? 'Torrents' : 'Both';
      await focusSourceRadio(page, sourceRadio(page, pick));
      await page.keyboard.press('Space');
      for (const [name, checked] of Object.entries(SOURCE_TRUTH[choice])) {
        await expect(sourceRadio(page, name), `${name} after choosing ${choice}`).toHaveAttribute('aria-checked', checked);
      }
      // The look is unchanged on purpose: Both tints all three, otherwise only the chosen one.
      for (const name of ['Usenet', 'Torrents', 'Both']) {
        const lit = choice === 'both' || SOURCE_TRUTH[choice][name as 'Usenet'] === 'true';
        if (lit) await expect(sourceRadio(page, name), `${name} should be tinted for ${choice}`).toHaveClass(/bg-cp-accent\/20/);
        else await expect(sourceRadio(page, name), `${name} should not be tinted for ${choice}`).not.toHaveClass(/bg-cp-accent\/20/);
      }
    }
  });

  test('the group is a single tab stop that follows the choice', async ({ page }) => {
    await acceptSaves(page);
    await openWizard(page);
    await mountStep(page, 2);
    const stops = () => sourceGroup(page).locator('[role="radio"][tabindex="0"]');
    await expect(stops(), 'more or fewer than one radio is in the tab order').toHaveCount(1);
    await expect(checkedSource(page).first()).toHaveAttribute('tabindex', '0');

    // Tab in, Tab out: the next stop is not another radio of the group.
    await tabTo(page, checkedSource(page));
    await page.keyboard.press('Tab');
    expect(await page.evaluate(() => !!document.activeElement?.closest('[role="radiogroup"]')), 'Tab moved to a second radio in the group').toBe(false);
    await page.keyboard.press('Shift+Tab');
    await expect(checkedSource(page)).toBeFocused();
    await page.keyboard.press('Shift+Tab');
    expect(await page.evaluate(() => !!document.activeElement?.closest('[role="radiogroup"]')), 'Shift+Tab moved to a second radio in the group').toBe(false);

    // The stop follows the choice.
    await tabTo(page, checkedSource(page));
    await page.keyboard.press('ArrowRight');
    await expect(sourceRadio(page, 'Both')).toHaveAttribute('tabindex', '0');
    await expect(stops()).toHaveCount(1);
    await expect(sourceRadio(page, 'Torrents')).toHaveAttribute('tabindex', '-1');
  });

  test('arrow keys move focus and the choice together, wrapping at both ends', async ({ page }) => {
    await acceptSaves(page);
    await openWizard(page);
    await mountStep(page, 2);
    await tabTo(page, checkedSource(page));                    // Torrents
    const expectOn = async (name: string, why: string) => {
      await expect(sourceRadio(page, name), `${why}: focus`).toBeFocused();
      await expect(sourceRadio(page, name), `${why}: choice`).toHaveAttribute('aria-checked', 'true');
      await expect(checkedSource(page), `${why}: exactly one checked`).toHaveCount(1);
    };
    await page.keyboard.press('ArrowRight');
    await expectOn('Both', 'Right from Torrents');
    await page.keyboard.press('ArrowRight');
    await expectOn('Usenet', 'Right from the last wraps to the first');
    await page.keyboard.press('ArrowLeft');
    await expectOn('Both', 'Left from the first wraps to the last');
    await page.keyboard.press('ArrowUp');
    await expectOn('Torrents', 'Up is Left');
    await page.keyboard.press('ArrowDown');
    await expectOn('Both', 'Down is Right');
  });

  test('Alt, Control and Meta with an arrow key leave the choice alone and do not cancel the browser shortcut', async ({ page }) => {
    await acceptSaves(page);
    await openWizard(page);
    await mountStep(page, 2);
    await tabTo(page, checkedSource(page));                    // Torrents
    // Record whether the page's own handler cancelled each keydown (document runs after the group's
    // handler in the bubble phase), then cancel it here so a real Alt+Left cannot navigate the test away.
    // The key is recorded with the flag so a handler that STOPS the event (it never reaches here)
    // is caught as well as one that cancels it.
    await page.evaluate(() => {
      const seen: { key: string; prevented: boolean }[] = [];
      (window as any).__keys = seen;
      document.addEventListener('keydown', (event) => { seen.push({ key: event.key, prevented: event.defaultPrevented }); event.preventDefault(); });
    });
    for (const [chord, label] of [['Alt+ArrowLeft', 'Alt+Left'], ['Control+ArrowRight', 'Control+Right'], ['Meta+ArrowLeft', 'Meta+Left']]) {
      await page.keyboard.press(chord);
      await expect(sourceRadio(page, 'Torrents'), `${label} changed the choice`).toHaveAttribute('aria-checked', 'true');
      await expect(sourceRadio(page, 'Torrents'), `${label} moved focus`).toBeFocused();
    }
    const keys = await page.evaluate(() => (window as any).__keys as { key: string; prevented: boolean }[]);
    // The modifier keys' own keydowns are recorded too; only the arrows matter.
    const arrows = keys.filter(({ key }) => key.startsWith('Arrow'));
    expect(
      arrows.map(({ key }) => key),
      'a modified arrow key never reached the document: the page stopped it',
    ).toEqual(['ArrowLeft', 'ArrowRight', 'ArrowLeft']);
    expect(arrows.filter(({ prevented }) => prevented), 'the page cancelled a modified arrow key, swallowing a browser shortcut').toEqual([]);
  });

  test('Space on a focused radio chooses it', async ({ page }) => {
    await acceptSaves(page);
    await openWizard(page);
    await mountStep(page, 2);
    await expect(sourceRadio(page, 'Usenet'), 'there is no Usenet radio').toHaveCount(1);
    await sourceRadio(page, 'Usenet').focus();                 // scene: focus a radio that is not the choice
    await page.keyboard.press('Space');
    await expect(sourceRadio(page, 'Usenet')).toHaveAttribute('aria-checked', 'true');
    await expect(sourceRadio(page, 'Torrents')).toHaveAttribute('aria-checked', 'false');
  });
});

test.describe('the download client buttons are toggles and say so', () => {
  test.use({ viewport: PHONE });

  test('aria-pressed follows the real state of each usenet and torrent client button', async ({ page }) => {
    await acceptSaves(page);
    await openWizard(page);
    await mountStep(page, 3, 'state.formData.searchType = "both";');
    const client = (name: string) => page.getByRole('button', { name, exact: true });

    for (const name of ['SABnzbd', 'NZBGet', 'qBittorrent', 'Transmission']) {
      await expect(client(name), `${name} before any choice`).toHaveAttribute('aria-pressed', 'false');
    }
    await tabTo(page, client('SABnzbd'));
    await page.keyboard.press('Space');
    await expect(client('SABnzbd')).toHaveAttribute('aria-pressed', 'true');
    await expect(client('NZBGet')).toHaveAttribute('aria-pressed', 'false');

    await tabTo(page, client('NZBGet'));
    await page.keyboard.press('Space');                        // choosing the other replaces it
    await expect(client('NZBGet')).toHaveAttribute('aria-pressed', 'true');
    await expect(client('SABnzbd')).toHaveAttribute('aria-pressed', 'false');
    await page.keyboard.press('Space');                        // and pressing the chosen one clears it
    await expect(client('NZBGet')).toHaveAttribute('aria-pressed', 'false');

    await tabTo(page, client('qBittorrent'));
    await page.keyboard.press('Space');
    await expect(client('qBittorrent')).toHaveAttribute('aria-pressed', 'true');
    await expect(client('Transmission')).toHaveAttribute('aria-pressed', 'false');
    await page.keyboard.press('Space');
    await expect(client('qBittorrent')).toHaveAttribute('aria-pressed', 'false');
  });
});

const statusRegion = (page: Page) => page.getByTestId('wizard-status');

/** Record every text the status region is given, in order, from now on. */
async function recordStatusTexts(page: Page) {
  await expect(statusRegion(page), 'there is no wizard status region').toHaveCount(1);
  await statusRegion(page).evaluate((region) => {
    const seen: string[] = [];
    (window as any).__statusTexts = seen;
    new MutationObserver((records) => {
      for (const record of records) {
        if (record.type !== 'childList') continue;
        seen.push(Array.from(record.addedNodes).map((n) => n.textContent).join(''));
      }
    }).observe(region, { childList: true, characterData: true, subtree: true });
  });
}
const statusTexts = (page: Page): Promise<string[]> => page.evaluate(() => (window as any).__statusTexts);

test.describe('busy states and results are announced through one persistent status region', () => {
  test.use({ viewport: PHONE });

  test('the region exists on first render as a visually hidden polite status that is never hidden or templated', async ({ page }) => {
    await acceptSaves(page);
    await openWizard(page);
    const region = statusRegion(page);
    await expect(region, 'there is no wizard status region').toHaveCount(1);
    await expect(region).toHaveJSProperty('tagName', 'OUTPUT');
    await expect(region).toHaveAttribute('aria-live', 'polite');
    await expect(region).toHaveText('');
    await expect(region).toHaveClass(/\bsr-only\b/);

    // It must be in the accessibility tree from the start, not created or revealed with its text.
    const placement = await region.evaluate((el) => ({
      hiddenAncestor: !!el.closest('[x-show], [x-if], template, [hidden], [aria-hidden="true"]'),
      display: getComputedStyle(el).display,
    }));
    expect(placement.hiddenAncestor, 'the status region sits inside something that is shown or hidden, so it is not persistent').toBe(false);
    expect(placement.display).not.toBe('none');
  });

  test('a save announces "Saving…" while it runs and clears afterwards, in the same element throughout', async ({ page }) => {
    const held = await holdSaves(page);
    await openWizard(page);
    await mountStep(page, 1, 'state.formData.username = "admin";');
    await expect(statusRegion(page), 'there is no wizard status region').toHaveCount(1);
    await statusRegion(page).evaluate((el) => { (el as any).__persistent = true; });
    await recordStatusTexts(page);

    await tabTo(page, nextButton(page));
    await page.keyboard.press('Enter');
    await expect.poll(() => held.saves.length).toBe(1);
    await expect(statusRegion(page), 'a running save is not announced').toHaveText('Saving…');

    held.release();
    await expect(heading(page, 2)).toBeFocused();
    await expect(statusRegion(page)).toHaveText('');
    expect(await statusRegion(page).evaluate((el) => (el as any).__persistent === true), 'the region was recreated instead of updated').toBe(true);
    // The success itself is carried by the focus move to the new heading: nothing else is said.
    expect(await statusTexts(page)).toEqual(['Saving…', '']);
  });

  test('a failed save is announced once, by the existing alert, and the status region does not repeat it', async ({ page }) => {
    await refuseSaves(page);
    await openWizard(page);
    await mountStep(page, 1, 'state.formData.username = "admin";');
    await recordStatusTexts(page);
    await tabTo(page, nextButton(page));
    await page.keyboard.press('Enter');

    await expect(page.getByTestId('toast-announcer-assertive')).toContainText(/Failed to save/);
    await expect(nextButton(page)).toHaveAttribute('aria-disabled', 'false');
    await expect(statusRegion(page)).toHaveText('');
    const texts = await statusTexts(page);
    expect(texts.filter((t) => /fail|refus|error/i.test(t)), 'the failure was announced by the status region as well as the alert').toEqual([]);
  });

  test('a Jackett sync announces "Syncing…" then its result, and announces an identical second result again', async ({ page }) => {
    await acceptSaves(page);
    let calls = 0;
    await page.route('**/provider.torrentpotato.jackett_sync/**', (route) => {
      calls += 1;
      return route.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify({ success: false, error: 'Jackett refused the key' }) });
    });
    await openWizard(page);
    await mountStep(page, 2, 'state.formData.torrentpotato.enabled = true;');
    await recordStatusTexts(page);
    const sync = page.getByRole('button', { name: /^(Sync Trackers from Jackett|Syncing…)$/ });

    await tabTo(page, sync);
    await page.keyboard.press('Enter');
    await expect.poll(() => calls).toBe(1);
    await expect(statusRegion(page)).toHaveText('Jackett refused the key');
    await page.keyboard.press('Enter');                       // the same failure again
    await expect.poll(() => calls).toBe(2);
    await expect.poll(() => statusTexts(page)).toEqual([
      'Syncing…', 'Jackett refused the key', 'Syncing…', 'Jackett refused the key',
    ]);

    // The visible result line is not a live region as well, or it would be read twice.
    const resultLine = page.locator('p[x-text="jackettSyncResult"]');
    await expect(resultLine).toHaveText('Jackett refused the key');
    const live = await resultLine.evaluate((el) => !!el.closest('[aria-live], [role="status"], [role="alert"], output'));
    expect(live, 'the sync result is live as well as the status region, so it is announced twice').toBe(false);
  });

  // The legacy downloader test button is dead markup (`x-if="false && ..."`), so no user can reach
  // this; the method is still announced so reviving the button cannot reintroduce a silent busy state.
  test('testDownloader() announces "Testing…" and its result', async ({ page }) => {
    await acceptSaves(page);
    let release!: () => void;
    const gate = new Promise<void>((resolve) => { release = resolve; });
    await page.route('**/download.sabnzbd.test/**', async (route) => {
      await gate;
      await route.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify({ success: true }) });
    });
    await openWizard(page);
    await mountStep(page, 3);
    await recordStatusTexts(page);
    await page.evaluate(() => {
      const state = (window as any).Alpine.$data(document.querySelector('[x-data="setupWizard()"]'));
      state.formData.downloader = 'sabnzbd';
      (window as any).__test = state.testDownloader();
    });
    await expect(statusRegion(page)).toHaveText('Testing…');
    release();
    await page.evaluate(() => (window as any).__test);
    await expect(statusRegion(page)).toHaveText('Connected!');
  });
});

type Ring = { coverage: Record<'top' | 'right' | 'bottom' | 'left', number>; minContrast: number };

/**
 * What a keyboard user SEES when `target` has focus: the pixels in the 1-5px band just OUTSIDE its box,
 * with and without focus, decoded in the page. `getComputedStyle(el).outlineStyle` is not evidence: the
 * global `:focus-visible` ring is drawn outside the border box, so an ancestor with `overflow-hidden`
 * (or a `w-full` row in a scroll container) can clip it to nothing while the style stays valid.
 *
 * The band runs from 4px inside the edge to 5px outside it, so a ring drawn inwards (needed where an
 * ancestor clips the outward one) counts as well as the default outward one.
 *
 * Coverage is the share of each edge (corners excluded) where a pixel in the band CHANGED and is at least
 * 3:1 against what it replaced, the surface the ring sits on (WCAG 1.4.11). The caller must already have
 * focused `target` with the keyboard, so `:focus-visible` really applies.
 */
async function measureFocusRing(page: Page, target: Locator, corner = 8, recenter = true): Promise<Ring> {
  await page.mouse.move(0, 0);
  await expect(target, 'the control is not focused, so there is no ring to measure').toBeFocused();
  // Settle FIRST, then centre: a step fading out is still in the layout while it runs, and when it
  // goes the document shrinks and the browser clamps the scroll, leaving the control under the fixed
  // phone header (measured: a button at y=18 with scrollY 243).
  await expectVisualTransitionsToSettle(page, 'focus ring');
  // Not for a control whose position after a step change is itself under test.
  if (recenter) await target.evaluate((el) => el.scrollIntoView({ block: 'center', behavior: 'instant' }));
  const reading = () => target.evaluate((el) => JSON.stringify({ r: el.getBoundingClientRect().toJSON(), y: window.scrollY }));
  const first = await reading();
  const box = JSON.parse(first).r;
  // The whole viewport, cropped in the page. NOT `clip`: Chromium renders a clipped capture as if the
  // viewport were the clip, so the fixed phone header and bottom bar jump to the clip's edges and
  // cover the control (intermittently), which reads as a missing ring.
  const focused = (await page.screenshot()).toString('base64');
  const second = await reading();
  await target.evaluate((el) => (el as HTMLElement).blur());
  await expectVisualTransitionsToSettle(page, 'focus ring removed');
  const unfocused = (await page.screenshot()).toString('base64');
  const third = await reading();
  expect(
    [second, third],
    'the control moved while its focus ring was being captured, so the two pictures do not frame the same pixels',
  ).toEqual([first, first]);
  const result = await page.evaluate(async ({ a, b, geo, edge }) => {
    const decode = async (data: string) => {
      const bitmap = await createImageBitmap(await (await fetch(`data:image/png;base64,${data}`)).blob());
      const ctx = new OffscreenCanvas(bitmap.width, bitmap.height).getContext('2d')!;
      ctx.drawImage(bitmap, 0, 0);
      return { w: bitmap.width, h: bitmap.height, px: ctx.getImageData(0, 0, bitmap.width, bitmap.height).data };
    };
    const A = await decode(a);   // focused
    const B = await decode(b);   // unfocused
    const at = (img: { w: number; px: Uint8ClampedArray }, px: number, py: number) => {
      const i = (py * img.w + px) * 4;
      return [img.px[i], img.px[i + 1], img.px[i + 2]];
    };
    const lum = (c: number[]) => {
      const [r, g, bl] = c.map((v) => { const s = v / 255; return s <= 0.04045 ? s / 12.92 : ((s + 0.055) / 1.055) ** 2.4; });
      return 0.2126 * r + 0.7152 * g + 0.0722 * bl;
    };
    const contrast = (c1: number[], c2: number[]) => {
      const [hi, lo] = [lum(c1), lum(c2)].sort((p, q) => q - p);
      return (hi + 0.05) / (lo + 0.05);
    };
    const x0 = Math.round(geo.bx);
    const y0 = Math.round(geo.by);
    const x1 = Math.round(geo.bx + geo.bw);
    const y1 = Math.round(geo.by + geo.bh);
    const inside = (px: number, py: number) => px >= 0 && py >= 0 && px < A.w && py < A.h;
    let minContrast = Infinity;
    const hit = (px: number, py: number) => {
      if (!inside(px, py)) return false;
      const f = at(A, px, py);
      const u = at(B, px, py);
      if (f.every((v, k) => v === u[k])) return false;
      const ratio = contrast(f, u);
      if (ratio < 3) return false;
      minContrast = Math.min(minContrast, ratio);
      return true;
    };
    // Per edge: for each position along it, is ANY pixel 1..5px out changed with >= 3:1?
    const along = (from: number, to: number, probe: (i: number, d: number) => boolean) => {
      let n = 0;
      let ok = 0;
      for (let i = from; i < to; i += 1) {
        n += 1;
        if ([-4, -3, -2, -1, 0, 1, 2, 3, 4, 5].some((d) => probe(i, d))) ok += 1;
      }
      return n === 0 ? 0 : ok / n;
    };
    // The corner allowance is capped at a quarter of the edge so a 16px control still has a middle to sample.
    const cw = Math.min(edge, Math.floor((x1 - x0) / 4));
    const ch = Math.min(edge, Math.floor((y1 - y0) / 4));
    const coverage = {
      top: along(x0 + cw, x1 - cw, (i, d) => hit(i, y0 - d)),
      bottom: along(x0 + cw, x1 - cw, (i, d) => hit(i, y1 + d - 1)),
      left: along(y0 + ch, y1 - ch, (i, d) => hit(x0 - d, i)),
      right: along(y0 + ch, y1 - ch, (i, d) => hit(x1 + d - 1, i)),
    };
    return { coverage, minContrast: Number.isFinite(minContrast) ? minContrast : 0 };
  }, {
    a: focused, b: unfocused, edge: corner,
    geo: { bx: box.x, by: box.y, bw: box.width, bh: box.height },
  });
  return result;
}

type Probe = { name: string; target: Locator; corner?: number; reach?: () => Promise<void> };

/** Focus each control with the keyboard, then require a visible ring on all four sides and a target of 24x24 or more. */
async function expectVisibleFocusAndSize(page: Page, probes: Probe[]) {
  const problems: string[] = [];
  for (const { name, target, corner, reach } of probes) {
    await (reach ? reach() : tabTo(page, target));
    // An entering dialog is scaled to 95% until its transition ends: measure the settled size.
    await expectVisualTransitionsToSettle(page, name);
    const size = await target.evaluate((el) => { const r = el.getBoundingClientRect(); return { w: r.width, h: r.height }; });
    if (size.w < 24 || size.h < 24) problems.push(`${name}: target ${size.w.toFixed(1)}x${size.h.toFixed(1)}px is below 24x24 (WCAG 2.5.8)`);
    const ring = await measureFocusRing(page, target, corner);
    const sides = Object.entries(ring.coverage).filter(([, share]) => share < 0.9).map(([side, share]) => `${side} ${(share * 100).toFixed(0)}%`);
    if (sides.length) problems.push(`${name}: focus ring missing or under 3:1 on ${sides.join(', ')} (min contrast ${ring.minContrast.toFixed(2)})`);
  }
  expect(problems, `controls without a visible focus indicator or with a small target:\n${problems.join('\n')}`).toEqual([]);
}

for (const theme of ['light', 'dark'] as const) {
  test.describe(`every touched control shows a focus ring and has a 24px target (${theme} theme, 375px)`, () => {
    test.use({ viewport: PHONE });

    test('the step indicator and the navigation buttons', async ({ page }) => {
      await acceptSaves(page);
      await openWizard(page, theme);
      await mountStep(page, 1);
      await expectVisibleFocusAndSize(page, [
        { name: 'step 1 button (completed)', target: indicators(page).nth(0), corner: 12 },
        { name: 'step 2 button (current)', target: indicators(page).nth(1), corner: 12 },
        { name: 'Back', target: backButton(page) },
        { name: 'Skip', target: skipButton(page) },
        { name: 'Continue', target: nextButton(page) },
      ]);
    });

    test('the source buttons and Sync Trackers from Jackett', async ({ page }) => {
      await acceptSaves(page);
      await openWizard(page, theme);
      await mountStep(page, 2, 'state.formData.torrentpotato.enabled = true;');
      // Radios are one tab stop: each is reached by Tab to the group, then Arrow.
      const radio = (name: string) => {
        const target = sourceRadio(page, name);
        return { name, target, reach: () => focusSourceRadio(page, target) };
      };
      await expectVisibleFocusAndSize(page, [
        radio('Usenet'),
        radio('Torrents'),
        radio('Both'),
        { name: 'Sync Trackers from Jackett', target: page.getByRole('button', { name: 'Sync Trackers from Jackett' }) },
      ]);
    });

    test('the download client toggle buttons', async ({ page }) => {
      await acceptSaves(page);
      await openWizard(page, theme);
      await mountStep(page, 3, 'state.formData.searchType = "both";');
      await expectVisibleFocusAndSize(page, ['SABnzbd', 'NZBGet', 'qBittorrent'].map((name) => ({
        name, target: page.getByRole('button', { name, exact: true }),
      })));
    });

    test('the four Browse buttons and Finish Setup', async ({ page }) => {
      await acceptSaves(page);
      await openWizard(page, theme);
      await mountStep(page, 3, 'state.formData.blackholeEnabled = true;');
      await expectVisibleFocusAndSize(page, OPENERS.filter((o) => o.step === 3).map((o) => ({ name: `Browse (${o.label})`, target: browseButtonFor(page, o.field) })));
      await mountStep(page, 4);
      await expectVisibleFocusAndSize(page, [
        ...OPENERS.filter((o) => o.step === 4).map((o) => ({ name: `Browse (${o.label})`, target: browseButtonFor(page, o.field) })),
        { name: 'Finish Setup', target: nextButton(page) },
      ]);
    });

    test('each step heading that takes focus on a step change', async ({ page }) => {
      await acceptSaves(page);
      await openWizard(page, theme);
      const problems: string[] = [];
      for (let step = 0; step <= 5; step += 1) {
        // Arrive by the keyboard, the way a user does: the code moves focus, the last input was a key.
        if (step === 0) {
          await mountStep(page, 1);
          await tabTo(page, backButton(page));
        } else {
          await mountStep(page, step - 1);
          await tabTo(page, nextButton(page));
        }
        await page.keyboard.press('Enter');
        await expect(heading(page, step)).toBeFocused();
        const size = await heading(page, step).evaluate((el) => el.getBoundingClientRect().height);
        expect(size).toBeGreaterThanOrEqual(24);
        // WCAG 2.4.11: where the step change left the heading is what a user gets, so it is NOT re-centred
        // here, and the fixed phone header (48px) must not be on top of it.
        const covered = await heading(page, step).evaluate((el) => {
          const r = el.getBoundingClientRect();
          const top = document.elementFromPoint(r.x + r.width / 2, r.y + 2);
          return top !== null && !el.contains(top) ? top.tagName.toLowerCase() + ' ' + (top.className || '').toString().slice(0, 40) : '';
        });
        if (covered) problems.push(`heading of step ${step + 1}: covered by <${covered}> after the step change`);
        const ring = await measureFocusRing(page, heading(page, step), 8, false);
        const sides = Object.entries(ring.coverage).filter(([, share]) => share < 0.9).map(([side, share]) => `${side} ${(share * 100).toFixed(0)}%`);
        if (sides.length) problems.push(`heading of step ${step + 1}: ring missing on ${sides.join(', ')} (min contrast ${ring.minContrast.toFixed(2)})`);
      }
      expect(problems, `a heading that takes focus shows no ring:\n${problems.join('\n')}`).toEqual([]);
    });

    test('the Remove indexer buttons and + Add another indexer', async ({ page }) => {
      await acceptSaves(page);
      await openWizard(page, theme);
      await mountStep(page, 2, indexerScene(2));
      await expectVisibleFocusAndSize(page, [
        ...[1, 2].map((n) => ({
          name: `Remove indexer ${n}`, target: page.getByRole('button', { name: `Remove indexer ${n}`, exact: true }),
        })),
        { name: '+ Add another indexer', target: addIndexerButton(page) },
      ]);
    });

    test('the folder browser controls', async ({ page }) => {
      await openFolderBrowser(page, OPENERS[0]);
      const dialog = folderDialog(page);
      await expect(dialog.getByRole('button', { name: 'movies', exact: true })).toBeVisible();
      await expectVisibleFocusAndSize(page, [
        { name: 'Close directory browser', target: dialog.getByRole('button', { name: 'Close directory browser', exact: true }) },
        { name: 'Up', target: dialog.getByRole('button', { name: /Up$/ }) },
        { name: 'folder row "movies"', target: dialog.getByRole('button', { name: 'movies', exact: true }) },
        { name: 'Cancel', target: dialog.getByRole('button', { name: 'Cancel', exact: true }) },
        { name: 'Select This Folder', target: dialog.getByRole('button', { name: 'Select This Folder', exact: true }) },
      ]);
    });
  });
}

/**
 * The folder rows ("input + Browse") must fit the card at 375px, so the Browse button and its focus
 * ring are not cut off by the card's `overflow-hidden`.
 *
 * This was found by Linux CI and invisible on macOS: a text input's intrinsic width comes from the
 * font, and the page's `Inter` is not loaded, so the fallback face decides. On Linux the two step-5
 * inputs were 244px wide, the row overflowed its 293px by 39px, and the Browse button's right edge
 * (373px) sat past the card's right edge (359px): its ring was clipped (right side 0%). On macOS the
 * same input is 205px and fits, so no test run on a Mac could see it. The inputs are therefore
 * made deliberately wide here (`size`), which reproduces the Linux overflow on any platform.
 */
test.describe('the Browse rows fit the card at 375px whatever the input\'s own width', () => {
  test.use({ viewport: PHONE });

  for (const opener of OPENERS) {
    for (const wide of [false, true]) {
      test(`"${opener.label}" Browse button and its ring stay inside the card${wide ? ' with a very wide input' : ''}`, async ({ page }) => {
        await acceptSaves(page);
        await openWizard(page);
        await mountStep(page, opener.step, opener.scene);
        if (wide) await page.locator(opener.field).evaluate((el) => el.setAttribute('size', '40'));
        // The step is still animating in until now; a button read mid-transition sits short of where it settles.
        await expectVisualTransitionsToSettle(page, `the ${opener.label} step`);
        const m = await page.locator(opener.field).evaluate((input) => {
          const row = input.parentElement as HTMLElement;
          const button = row.querySelector('button') as HTMLElement;
          let card: Element | null = row;
          while (card && getComputedStyle(card).overflowX === 'visible') card = card.parentElement;
          return {
            buttonRight: button.getBoundingClientRect().right,
            // The INNER edge: what the clip actually cuts at is inside the card's border.
            cardRight: (card as Element).getBoundingClientRect().right - parseFloat(getComputedStyle(card as Element).borderRightWidth),
            rowScroll: row.scrollWidth,
            rowClient: row.clientWidth,
          };
        });
        expect(m.rowScroll, `the row overflows its box by ${m.rowScroll - m.rowClient}px`).toBeLessThanOrEqual(m.rowClient);
        // 4px: the 2px outline plus its 2px offset.
        expect(m.buttonRight + 4, `the Browse button's ring reaches ${m.buttonRight + 4}px but the card clips at ${m.cardRight}px`).toBeLessThanOrEqual(m.cardRight);
      });
    }
  }
});

/** Step 3 ("Where to Search") with Usenet chosen, Newznab on and `n` empty indexer rows. */
const indexerScene = (n: number) =>
  `state.formData.searchType = "usenet"; state.formData.newznab.enabled = true; state.formData.newznab.entries = [${Array.from({ length: n }, () => '{host: "", api_key: ""}').join(', ')}];`;

const removeButtons = (page: Page) => page.getByRole('button', { name: /^Remove indexer \d+$/ });
const addIndexerButton = (page: Page) => page.getByRole('button', { name: '+ Add another indexer' });

/**
 * The Newznab indexer rows ("URL input + API key input + Remove") at 375px. Neither input had `min-w-0`,
 * so each kept its intrinsic width: the row overflowed (measured 115px on macOS, 171px on Linux, with two
 * entries), the API key was sliced by the card's `overflow-hidden`, and the Remove buttons sat wholly
 * outside the card while Tab still reached them. `size=40` reproduces Linux font metrics on any platform.
 */
test.describe('the Newznab indexer rows fit the card at 375px whatever the inputs\' own width', () => {
  test.use({ viewport: PHONE });

  for (const entries of [1, 2]) {
    for (const wide of [false, true]) {
      test(`${entries} ${entries === 1 ? 'entry' : 'entries'}: the row and every Remove button stay inside the card${wide ? ' with very wide inputs' : ''}`, async ({ page }) => {
        await acceptSaves(page);
        await openWizard(page);
        await mountStep(page, 2, indexerScene(entries));
        await expect(page.getByLabel(/^Newznab indexer URL/)).toHaveCount(entries);
        if (wide) {
          await page.locator('[aria-label^="Newznab indexer URL"], [aria-label^="Newznab API key"]')
            .evaluateAll((els) => els.forEach((el) => el.setAttribute('size', '40')));
        }
        // The step is still animating in until now; a button read mid-transition sits short of where it settles.
        await expectVisualTransitionsToSettle(page, 'the Providers step');
        const rows = await page.locator('[aria-label^="Newznab indexer URL"]').evaluateAll((inputs) => inputs.map((input) => {
          const row = input.parentElement as HTMLElement;
          let clip: Element | null = row;
          while (clip && getComputedStyle(clip).overflowX === 'visible') clip = clip.parentElement;
          const clipRight = (clip as Element).getBoundingClientRect().right - parseFloat(getComputedStyle(clip as Element).borderRightWidth);
          return {
            rowScroll: row.scrollWidth,
            rowClient: row.clientWidth,
            clipRight,
            buttons: Array.from(row.querySelectorAll('button')).map((b) => ({
              visible: getComputedStyle(b).display !== 'none',
              right: b.getBoundingClientRect().right,
            })),
          };
        }));
        expect(rows).toHaveLength(entries);
        rows.forEach((m, i) => {
          expect(m.rowScroll, `row ${i + 1} overflows its box by ${m.rowScroll - m.rowClient}px`).toBeLessThanOrEqual(m.rowClient);
          for (const b of m.buttons.filter((x) => x.visible)) {
            // 4px: the 2px outline plus its 2px offset.
            expect(b.right + 4, `row ${i + 1}: the Remove button's ring reaches ${b.right + 4}px but the card clips at ${m.clipRight}px`).toBeLessThanOrEqual(m.clipRight);
          }
        });
        expect(await removeButtons(page).count(), 'two or more entries must show a Remove button each').toBe(entries > 1 ? entries : 0);
        if (entries > 1) await expect(removeButtons(page).first()).toBeVisible();
      });
    }
  }
});

/**
 * Pressing Enter on Remove removes the focused button itself (the rows are keyed by index, and with one
 * entry left no Remove button is shown), so focus must be handed on or it falls to <body>.
 */
test.describe('removing an indexer by keyboard never drops focus to <body>', () => {
  test.use({ viewport: PHONE });

  const cases = [
    { name: 'the last of three', n: 3, remove: 3, focused: 'Remove indexer 2' },
    { name: 'the first of three', n: 3, remove: 1, focused: 'Remove indexer 1' },
    // The focused node survives here but becomes display:none, so a handler that leaves focus alone strands it on <body>.
    { name: 'the first of two (its button survives but is hidden)', n: 2, remove: 1, focused: '+ Add another indexer' },
    { name: 'one of two (no Remove button is left to focus)', n: 2, remove: 2, focused: '+ Add another indexer' },
  ];

  for (const c of cases) {
    test(`removing ${c.name} leaves focus on "${c.focused}"`, async ({ page }) => {
      await acceptSaves(page);
      await openWizard(page);
      await mountStep(page, 2, indexerScene(c.n));
      // Tell the rows apart by what they hold, so the right one is shown to have gone.
      await page.evaluate(() => {
        const state = (window as any).Alpine.$data(document.querySelector('[x-data="setupWizard()"]'));
        state.formData.newznab.entries.forEach((e: any, i: number) => { e.host = `host-${i + 1}`; });
      });
      await tabTo(page, page.getByRole('button', { name: `Remove indexer ${c.remove}`, exact: true }));
      await page.keyboard.press('Enter');
      await expect(page.getByLabel(/^Newznab indexer URL/)).toHaveCount(c.n - 1);
      const kept = await page.getByLabel(/^Newznab indexer URL/).evaluateAll((els) => els.map((el) => (el as HTMLInputElement).value));
      expect(kept, 'the wrong indexer was removed').toEqual(Array.from({ length: c.n }, (_, i) => `host-${i + 1}`).filter((_, i) => i !== c.remove - 1));
      // Focus is handed on after the rows re-render, so wait for it (bounded) rather than read it at the
      // instant the row disappears, when it is legitimately still on the removed button's way out.
      const target = c.focused.startsWith('+') ? addIndexerButton(page) : page.getByRole('button', { name: c.focused, exact: true });
      await expect.poll(() => whereIsFocus(page), { message: `focus should reach "${c.focused}"` }).not.toMatch(/^<body>|^nothing/);
      const where = await whereIsFocus(page);
      expect(await page.evaluate(() => document.activeElement === document.body), `focus fell to <body> (${where})`).toBe(false);
      await expect(target, `focus should be on "${c.focused}" but is on ${where}`).toBeFocused();
    });
  }
});

const indexerHosts = (page: Page) => page.getByLabel(/^Newznab indexer URL/).evaluateAll((els) => els.map((el) => (el as HTMLInputElement).value));

/** Record the number of indexer rows after every change to the page from now on. */
async function recordRowCounts(page: Page) {
  await page.evaluate(() => {
    const counts: number[] = [document.querySelectorAll('[aria-label^="Newznab indexer URL"]').length];
    (window as any).__rowCounts = counts;
    new MutationObserver(() => {
      counts.push(document.querySelectorAll('[aria-label^="Newznab indexer URL"]').length);
    }).observe(document.body, { childList: true, subtree: true });
  });
}
const rowCounts = (page: Page): Promise<number[]> => page.evaluate(() => (window as any).__rowCounts);

/** Hold Enter: the first `down` is the press, every further `down` without an `up` is an auto-repeat. */
async function holdEnter(page: Page, presses = 6) {
  for (let i = 0; i < presses; i += 1) await page.keyboard.down('Enter');
  await page.keyboard.up('Enter');
}

test.describe('a held key removes one indexer and adds none', () => {
  test.use({ viewport: PHONE });

  test('Playwright\'s repeated down() really produces repeat keydowns (the premise of the tests below)', async ({ page }) => {
    await acceptSaves(page);
    await openWizard(page);
    await page.evaluate(() => {
      const seen: boolean[] = [];
      (window as any).__repeats = seen;
      document.addEventListener('keydown', (e) => { if (e.key === 'Enter') seen.push(e.repeat); }, true);
    });
    await holdEnter(page, 4);
    expect(await page.evaluate(() => (window as any).__repeats)).toEqual([false, true, true, true]);
  });

  // `late`: the repeats start only after focus has been handed on, so they land on the NEXT control (the next
  // Remove button, or Add). Without it they are all sent before the handover and only the Remove button sees them.
  for (const held of [
    { n: 4, left: 3, late: false }, { n: 2, left: 1, late: false },
    { n: 4, left: 3, late: true }, { n: 2, left: 1, late: true },
  ]) {
    test(`holding Enter on Remove indexer 1 of ${held.n}${held.late ? ' (repeats start once focus has moved on)' : ''} removes exactly one row, adds none, and never reaches zero`, async ({ page }) => {
      await acceptSaves(page);
      await openWizard(page);
      await mountStep(page, 2, indexerScene(held.n));
      await page.evaluate(() => {
        const state = (window as any).Alpine.$data(document.querySelector('[x-data="setupWizard()"]'));
        state.formData.newznab.entries.forEach((e: any, i: number) => { e.host = `host-${i + 1}`; });
      });
      await tabTo(page, page.getByRole('button', { name: 'Remove indexer 1', exact: true }));
      await recordRowCounts(page);
      // Focus is handed on to the next Remove button, or to Add once only one row is left.
      const handedTo = held.left > 1 ? page.getByRole('button', { name: 'Remove indexer 1', exact: true }) : addIndexerButton(page);
      if (held.late) {
        await page.keyboard.down('Enter');
        await expect(page.getByLabel(/^Newznab indexer URL/)).toHaveCount(held.left);
        await expect(handedTo).toBeFocused();
        for (let i = 0; i < 5; i += 1) await page.keyboard.down('Enter');
        await page.keyboard.up('Enter');
      } else {
        await holdEnter(page);
      }
      await expect(page.getByLabel(/^Newznab indexer URL/)).toHaveCount(held.left);
      await expect(handedTo).toBeFocused();
      // Let the held key's remaining keydowns be handled, then read the whole history rather than the end state.
      await page.evaluate(() => new Promise((resolve) => requestAnimationFrame(() => requestAnimationFrame(resolve))));
      const counts = await rowCounts(page);
      expect(Math.min(...counts), `the row count reached ${Math.min(...counts)} (history ${counts.join(',')})`).toBeGreaterThanOrEqual(1);
      expect(Math.max(...counts.slice(1)), `a row was added while the key was held (history ${counts.join(',')})`).toBeLessThan(held.n);
      expect(await indexerHosts(page)).toEqual(Array.from({ length: held.n - 1 }, (_, i) => `host-${i + 2}`));
    });
  }

  test('removing is a no-op when only one entry is left, even if a Remove click is delivered', async ({ page }) => {
    await acceptSaves(page);
    await openWizard(page);
    await mountStep(page, 2, indexerScene(1));
    // The button is display:none with one entry; the handler's own guard is what is under test, so the
    // click is dispatched rather than pressed.
    await page.locator('[data-indexer-remove]').dispatchEvent('click');
    await page.evaluate(() => new Promise((resolve) => requestAnimationFrame(() => requestAnimationFrame(resolve))));
    await expect(page.getByLabel(/^Newznab indexer URL/), 'the last indexer was removed, leaving zero rows').toHaveCount(1);
  });

  test('a single Enter and a single Space each still add one row on Add, and remove one on Remove', async ({ page }) => {
    await acceptSaves(page);
    await openWizard(page);
    await mountStep(page, 2, indexerScene(2));
    const rows = page.getByLabel(/^Newznab indexer URL/);
    await tabTo(page, addIndexerButton(page));
    await page.keyboard.press('Enter');
    await expect(rows).toHaveCount(3);
    await page.keyboard.press('Space');
    await expect(rows).toHaveCount(4);
    await tabTo(page, page.getByRole('button', { name: 'Remove indexer 1', exact: true }));
    await page.keyboard.press('Space');
    await expect(rows).toHaveCount(3);
    await expect(addIndexerButton(page), 'a Space on Remove must not carry its keyup into a click on Add').not.toBeFocused();
    await expect(page.getByRole('button', { name: 'Remove indexer 1', exact: true })).toBeFocused();
    await page.keyboard.press('Enter');
    await expect(rows).toHaveCount(2);
    await page.evaluate(() => new Promise((resolve) => requestAnimationFrame(() => requestAnimationFrame(resolve))));
    await expect(rows).toHaveCount(2);
  });
});

test.describe('removing an indexer is announced and only moves focus that was on the pressed button', () => {
  test.use({ viewport: PHONE });

  test('the removal is announced as "Indexer N removed", and again when the same position is removed twice', async ({ page }) => {
    await acceptSaves(page);
    await openWizard(page);
    await mountStep(page, 2, indexerScene(3));
    await recordStatusTexts(page);
    await tabTo(page, page.getByRole('button', { name: 'Remove indexer 1', exact: true }));
    await page.keyboard.press('Enter');
    await expect(statusRegion(page)).toHaveText('Indexer 1 removed');
    // Focus has been handed to the Remove button now at position 1: remove that one too.
    await expect(page.getByRole('button', { name: 'Remove indexer 1', exact: true })).toBeFocused();
    await page.keyboard.press('Enter');
    await expect.poll(async () => (await statusTexts(page)).filter((t) => t === 'Indexer 1 removed').length, {
      message: 'an identical announcement must be made again, so the region has to be emptied between the two',
    }).toBe(2);
  });

  test('the position announced is the 1-based position removed', async ({ page }) => {
    await acceptSaves(page);
    await openWizard(page);
    await mountStep(page, 2, indexerScene(3));
    await tabTo(page, page.getByRole('button', { name: 'Remove indexer 3', exact: true }));
    await page.keyboard.press('Enter');
    await expect(statusRegion(page)).toHaveText('Indexer 3 removed');
  });

  test('a Remove click while focus is on another control removes the row and leaves focus where it was', async ({ page }) => {
    await acceptSaves(page);
    await openWizard(page);
    await mountStep(page, 2, indexerScene(3));
    const url = page.getByLabel('Newznab indexer URL 1');
    await url.focus();
    // Not a key press: Chromium focuses a button on a mouse click, so the "focus is elsewhere" branch of the
    // handler cannot be reached by clicking. What is under test is that branch, not an input device.
    await page.getByRole('button', { name: 'Remove indexer 3', exact: true }).dispatchEvent('click');
    await expect(page.getByLabel(/^Newznab indexer URL/)).toHaveCount(2);
    // The announcement is made in the same tick that would have moved focus, so once it is there the
    // handler has finished and focus can be read without racing it.
    await expect(statusRegion(page)).toHaveText('Indexer 3 removed');
    await expect(url, `focus was taken from the control it was on, and is now on ${await whereIsFocus(page)}`).toBeFocused();
  });
});
