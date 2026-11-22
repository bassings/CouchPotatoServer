/**
 * What the SEC-005 display specs share: the texts the user reads, and the Settings TorrentPotato card.
 *
 * Every Jackett address is a `.invalid` name or the loopback address (the fake Jackett of
 * ./fake-jackett.ts, or `127.0.0.1:9` with no listener), so nothing leaves the machine. Keys are
 * placeholders. The sync route is never stubbed on the Settings page: the refusal is reached on the
 * real server by saving a key for one address and then another address (`refuseByAddressChange`).
 */
import type { Locator, Page } from '@playwright/test';

import { expect } from './fixtures';

export const SEEDED_URL = 'http://seeded-jackett.invalid:9117';
export const OTHER_URL = 'http://other-jackett.invalid:9117';
export const KEY_ONE = 'placeholder-key-one';

/** AC-DESIGN-5 as reworded by owner decision D8, verbatim (a literal here, never the production constant). */
export const REFUSAL = 'Check the Jackett URL is right, then copy the API key from your Jackett dashboard, '
  + 'paste it above and press Sync. This is needed once after this update, or after the URL changes.';
/** AC-PROD-12, verbatim, for the Settings button labelled "Sync Indexers". */
export const DID_NOT_SAVE = 'Sync Indexers did not run because a change above did not save. Fix it if needed, '
  + 'then press Sync Indexers to save and run again.';
export const STILL_SAVING = 'Sync Indexers did not run: your changes have not finished saving. If this happens '
  + 'again, check CouchPotato is still running.';
/** Owner decision D9, verbatim: what Jackett not accepting the key says. */
export const KEY_REJECTED = 'Jackett did not accept the API key. Copy it again from your Jackett dashboard.';

export const SYNC_ROUTE = 'torrentpotato.jackett_sync';
export const SECTION = 'torrentpotato';
export const THEMES = ['light', 'dark'] as const;
export type Theme = (typeof THEMES)[number];

export async function saveThroughApi(page: Page, apiBase: string, name: string, value: string) {
  const response = await page.request.post(`${apiBase}/settings.save/`, {
    form: { section: SECTION, name, value },
  });
  expect((await response.json()).success).toBe(true);
}

/**
 * A key saved for one address and the address then changed to another, through the API: the
 * state a real user is in after the guard ships (or after the address is changed behind their
 * back). The next Sync is refused by the server.
 */
export async function refuseByAddressChange(page: Page, apiBase: string, key: string, newAddress: string) {
  await saveThroughApi(page, apiBase, 'jackett_url', SEEDED_URL);
  await saveThroughApi(page, apiBase, 'jackett_api_key', key);
  await saveThroughApi(page, apiBase, 'jackett_url', newAddress);
}

export function providerCard(page: Page, heading: string): Locator {
  return page.locator('.bg-cp-card', { has: page.getByRole('heading', { name: heading, exact: true }) });
}

/**
 * The Searchers tab with the TorrentPotato card open, in `theme`.
 *
 * `fakeClock: true` installs Playwright's clock and, once the card is open, PAUSES it. The page's own 500 ms
 * debounce and its 10 second wait deadline then fire only when the test moves the clock
 * (`page.clock.runFor(500)` lets a typed value save, `page.clock.fastForward(10_000)` ends a wait), so a typed
 * value reaches the server only through the button's press, or when the test lets its timer run. A paused
 * clock also withholds the page's announcements (they wait on a tick).
 *
 * `fakeClock: 'running'` installs the clock and leaves it running, for a test that reads announcements:
 * `fastForward` still ends a wait, and the test types and presses in one browser task (`typeKeyAndPress`).
 *
 * `clock.install()` alone holds nothing back, whatever its name suggests (measured: a 300 ms timer fires after
 * about 300 ms of real time).
 */
export async function openTorrentCard(page: Page, options: { theme?: Theme; fakeClock?: boolean | 'running' } = {}): Promise<Locator> {
  const { theme, fakeClock = false } = options;
  if (theme) await page.addInitScript((selected) => localStorage.setItem('cp-theme', selected), theme);
  if (fakeClock) await page.clock.install();
  await page.goto('/settings/');
  await expect(page.locator('h1')).toContainText('Settings');
  if (theme) {
    await expect.poll(() => page.evaluate(() => document.documentElement.classList.contains('light')))
      .toBe(theme === 'light');
  }
  await page.getByRole('tab', { name: 'Searchers' }).click();
  const card = providerCard(page, 'TorrentPotato');
  const closed = card.locator('h3 button[aria-expanded="false"]');
  // The assertion below fails if the card is not open afterwards, so the guard cannot hide a failure.
  if (await closed.count()) await closed.click(); // vacuous-guard-ok: idempotent open, an enabled provider starts open
  await expect(card.locator('h3 button[aria-expanded="true"]')).toHaveCount(1);
  // Paused only now, after the page has loaded: loading itself needs timers. `pauseAt` jumps one
  // second forward, firing whatever was due, and holds the clock there. A paused clock also withholds
  // the page's announcements (they wait on a tick), so a test that reads those passes 'running': the
  // clock is installed, so `fastForward` still ends a wait, and it keeps real time otherwise.
  if (fakeClock === true) await page.clock.pauseAt(Date.now() + 1000);
  return card;
}

export const syncButton = (card: Locator) => card.getByRole('button', { name: /Sync Indexers/ });
export const urlField = (card: Locator) => card.getByLabel('Jackett URL', { exact: true });
export const keyField = (card: Locator) => card.getByLabel('Jackett API Key', { exact: true });
/** The Sync button's own field (the button, its result and its description). */
export const syncField = (card: Locator) => syncButton(card).locator('xpath=..');
/**
 * The Sync result: the button's persistent status region, an `<output>` (implicit role=status).
 * The card has other status regions, for its provider test, so it is found through the button's field.
 */
export const resultRegion = (card: Locator) => syncField(card).getByRole('status');

/** Press Sync and return what the server answered, read from the response the press caused. */
export async function pressSync(page: Page, card: Locator) {
  const answered = page.waitForResponse((response) => response.url().includes(SYNC_ROUTE));
  await syncButton(card).click();
  return (await answered).json();
}

export type Step = { kind: 'request' | 'response'; name: string };

/** What each request is, by the setting it saves or the route it calls. Names no value. */
function nameOf(url: string, body: string): string | null {
  if (url.includes(SYNC_ROUTE)) return 'sync';
  if (!/settings\.save\//.test(url)) return null;
  return `save:${new URLSearchParams(body).get('name')}`;
}

/** Every save and sync, requests and answers, in the order the browser saw them. Arm before the trigger. */
export function watchOrder(page: Page): Step[] {
  const steps: Step[] = [];
  page.on('request', (request) => {
    const name = nameOf(request.url(), request.postData() ?? '');
    if (name) steps.push({ kind: 'request', name });
  });
  page.on('response', (response) => {
    const name = nameOf(response.url(), response.request().postData() ?? '');
    if (name) steps.push({ kind: 'response', name });
  });
  return steps;
}

/** The index of the nth step of that kind and name, or -1. */
export const position = (steps: Step[], kind: Step['kind'], name: string, nth = 0) => {
  const matches = steps.map((step, index) => ({ step, index }))
    .filter(({ step }) => step.kind === kind && step.name === name);
  return matches[nth]?.index ?? -1;
};

/**
 * Every request to the sync route the page starts, from now on. Arm BEFORE the press. A request is
 * recorded when the page starts it, so a list that is still empty once the press has ended (the
 * button operable again, which only happens after everything the press did is over) is the evidence
 * that nothing was sent.
 */
export function watchSyncRequests(page: Page): string[] {
  const urls: string[] = [];
  page.on('request', (request) => { if (request.url().includes(SYNC_ROUTE)) urls.push(request.url()); });
  return urls;
}

/** The press has ended: the button is operable again (aria-disabled is gone, not `disabled`). */
export const pressEnded = (card: Locator) => expect(syncButton(card)).not.toHaveAttribute('aria-disabled', 'true');

/** The key's save leaves the page and is never answered; every other save goes through. Resolves when it has left. */
export async function holdKeySaves(page: Page): Promise<{ sent: () => number; firstSent: Promise<void> }> {
  let count = 0;
  let release!: () => void;
  const firstSent = new Promise<void>((resolve) => { release = resolve; });
  await page.route('**/settings.save/**', (route) => {
    if (new URLSearchParams(route.request().postData() ?? '').get('name') === 'jackett_api_key') {
      count += 1;
      release();
      return undefined;
    }
    return route.fallback();
  });
  return { sent: () => count, firstSent };
}

/** The address's save is refused (a stub of the SAVE route, never the sync route); every other save goes through. Returns a counter of the refused requests. */
export async function refuseAddressSaves(page: Page): Promise<{ refused: () => number }> {
  let count = 0;
  await page.route('**/settings.save/**', (route) => {
    if (new URLSearchParams(route.request().postData() ?? '').get('name') !== 'jackett_url') return route.fallback();
    count += 1;
    return route.fulfill({
      status: 200, contentType: 'application/json',
      body: JSON.stringify({ success: false, error: 'The address was not accepted.' }),
    });
  });
  return { refused: () => count };
}

/**
 * Type a value into the Jackett API Key field and press Sync in ONE browser task, with the real clock
 * running: the field's debounce timer cannot fire in between, so the press (not the timer) sends the
 * value, however slow the machine is. Used where a test needs the page's own announcements, which a
 * held clock would withhold. Focus is on the button first, as after a click.
 */
export async function typeKeyAndPress(card: Locator, value: string) {
  await syncButton(card).focus();
  await card.evaluate((root, typed) => {
    const input = root.querySelector<HTMLInputElement>('input[aria-label="Jackett API Key"]');
    const button = root.querySelector<HTMLButtonElement>('button[aria-label="Sync Indexers"]');
    if (!input || !button) throw new Error('the Jackett key field or the Sync button is not in the card');
    input.value = typed;
    input.dispatchEvent(new Event('change', { bubbles: true }));
    button.click();
  }, value);
}

/**
 * THE one stub of the sync route in SEC-005's tests, used only by the wizard tests (AC-A11Y-4): the wizard
 * saves the address and the key before every sync, so it reaches the refusal only if the saved pair changes
 * in between, which a test cannot arrange. Returns the number of syncs the page made.
 */
export async function stubWizardSyncRefusal(page: Page): Promise<{ syncs: () => number }> {
  let count = 0;
  await page.route(`**/${SYNC_ROUTE}/**`, (route) => {
    count += 1;
    return route.fulfill({
      status: 200, contentType: 'application/json', body: JSON.stringify({ success: false, error: REFUSAL }),
    });
  });
  return { syncs: () => count };
}
