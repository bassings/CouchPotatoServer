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
  return browse;
}

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
    await tabTo(page, dialog.getByRole('button', { name: 'Close directory browser', exact: true }));
    await page.keyboard.press('Enter');
    await expect(dialog).toBeHidden();
    await expect(browse, `after the close button, focus is on ${await whereIsFocus(page)}`).toBeFocused();

    await page.keyboard.press('Enter');
    await expect(dialog.getByRole('button', { name: 'movies', exact: true })).toBeVisible();
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
