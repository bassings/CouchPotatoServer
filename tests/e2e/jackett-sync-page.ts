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

/** AC-DESIGN-5, verbatim. */
export const REFUSAL = 'The saved Jackett API key cannot be used with this Jackett address. Check the '
  + 'address is your Jackett server, then enter the API key again and press Sync again.';
/** AC-PROD-12, verbatim. */
export const DID_NOT_SAVE = 'Your changes did not save, so this was not run. Check the fields above and try again.';
export const STILL_SAVING = 'Your changes are still saving, so this was not run. Try again in a moment.';

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
 * The Searchers tab with the TorrentPotato card open, in `theme`. `fakeClock` stops the page's own
 * 500 ms debounce (a value typed in the page then reaches the server only through the button's
 * flush) and lets a test move the 10 second wait deadline by hand.
 */
export async function openTorrentCard(page: Page, options: { theme?: Theme; fakeClock?: boolean } = {}): Promise<Locator> {
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
  return card;
}

export const syncButton = (card: Locator) => card.getByRole('button', { name: /Sync Indexers/ });
export const urlField = (card: Locator) => card.getByLabel('Jackett URL', { exact: true });
export const keyField = (card: Locator) => card.getByLabel('Jackett API Key', { exact: true });
/** The Sync button's own field (the button, its result and its description). */
export const syncField = (card: Locator) => syncButton(card).locator('xpath=..');
/** The Sync result: the button's persistent status region. (The card has other status regions, for its provider test.) */
export const resultRegion = (card: Locator) => syncField(card).locator('[role="status"]');

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
