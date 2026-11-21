import { setTimeout as sleep } from 'node:timers/promises';

import type { Locator, Page } from '@playwright/test';

import { test, expect } from './fixtures';
import { configSection } from './helpers';
import { SETTINGS_PERSISTENCE_ANNOTATION } from './settings_persistence';

/**
 * SEC-005 P1: what the Settings Sync button and the wizard do BEFORE any guard exists.
 *
 * Nothing here reads the stored binding to refuse anything (that is a later slice), so every
 * Jackett address used is either a `.invalid` name or the loopback address with no listener
 * (`http://127.0.0.1:9`): a Sync that reaches the network answers "Failed to connect to
 * Jackett" and nothing leaves the machine. The sync route is NOT stubbed in any test of this
 * file, and the debounce is on the fake clock, so a value typed in the page can only reach the
 * server through the flush the button makes, never through the page's own 500 ms timer.
 *
 * The values are placeholders, not credentials.
 */
const SEEDED_URL = 'http://seeded-jackett.invalid:9117';
const LOOPBACK_URL = 'http://127.0.0.1:9';
const KEY_ONE = 'placeholder-key-one';
const KEY_TWO = 'placeholder-key-two';
const CONNECT_FAILURE = /Failed to connect to Jackett/;
const SYNC_ROUTE = 'torrentpotato.jackett_sync';

type Step = { kind: 'request' | 'response'; name: string };

/** What each request is, by the setting it saves or the route it calls. Names no value. */
function nameOf(url: string, body: string): string | null {
  if (url.includes(SYNC_ROUTE)) return 'sync';
  if (!/settings\.save\//.test(url)) return null;
  return `save:${new URLSearchParams(body).get('name')}`;
}

/** Every save and sync, requests and answers, in the order the browser saw them. Arm before the trigger. */
function watchOrder(page: Page): Step[] {
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

const position = (steps: Step[], kind: Step['kind'], name: string, nth = 0) => {
  const matches = steps.map((step, index) => ({ step, index }))
    .filter(({ step }) => step.kind === kind && step.name === name);
  return matches[nth]?.index ?? -1;
};

async function saveThroughApi(page: Page, apiBase: string, name: string, value: string) {
  const response = await page.request.post(`${apiBase}/settings.save/`, {
    form: { section: 'torrentpotato', name, value },
  });
  expect((await response.json()).success).toBe(true);
}

function providerCard(page: Page, heading: string): Locator {
  return page.locator('.bg-cp-card', { has: page.getByRole('heading', { name: heading, exact: true }) });
}

async function openTorrentCard(page: Page): Promise<Locator> {
  await page.clock.install();
  await page.goto('/settings/');
  await expect(page.locator('h1')).toContainText('Settings');
  await page.getByRole('tab', { name: 'Searchers' }).click();
  const card = providerCard(page, 'TorrentPotato');
  const closed = card.locator('h3 button[aria-expanded="false"]');
  // The assertion below fails if the card is not open afterwards, so the guard cannot hide a failure.
  if (await closed.count()) await closed.click(); // vacuous-guard-ok: idempotent open, an enabled provider starts open
  await expect(card.locator('h3 button[aria-expanded="true"]')).toHaveCount(1);
  return card;
}

const syncButton = (card: Locator) => card.getByRole('button', { name: /Sync Indexers/ });
const urlField = (card: Locator) => card.getByLabel('Jackett URL', { exact: true });
const keyField = (card: Locator) => card.getByLabel('Jackett API Key', { exact: true });

/** Press Sync and return what the server answered, read from the response the press caused. */
async function pressSync(page: Page, card: Locator) {
  const answered = page.waitForResponse((response) => response.url().includes(SYNC_ROUTE));
  await syncButton(card).click();
  return (await answered).json();
}

test.describe('Settings: Sync sends its own section\'s typed values first (SEC-005 C1)', () => {
  test.use({ seedConfig: 'fresh_defaults#jackett-flush' });

  test('a Sync pressed with no wait after the address, and again after the key, goes out after those saves', async ({ page, testServer }) => {
    test.info().annotations.push({ type: SETTINGS_PERSISTENCE_ANNOTATION });
    await saveThroughApi(page, testServer.apiBase, 'jackett_url', SEEDED_URL);
    await saveThroughApi(page, testServer.apiBase, 'jackett_api_key', KEY_ONE);
    const card = await openTorrentCard(page);
    const steps = watchOrder(page);

    // The fake clock stops the page's own debounce, so only the button's flush can send these.
    await urlField(card).fill(LOOPBACK_URL);
    const first = await pressSync(page, card);

    expect(position(steps, 'response', 'save:jackett_url'), 'the address was never saved').toBeGreaterThanOrEqual(0);
    expect(position(steps, 'response', 'save:jackett_url')).toBeLessThan(position(steps, 'request', 'sync'));
    // It went to the address just typed, not the seeded one: the loopback has no listener.
    expect(first.success).toBe(false);
    expect(first.error).toMatch(CONNECT_FAILURE);
    await expect(card.getByText(CONNECT_FAILURE)).toBeVisible();
    expect(configSection(testServer.configPath, 'torrentpotato').jackett_url).toBe(LOOPBACK_URL);

    // The key is entered again and Sync is pressed with no wait: the press commits the field.
    await keyField(card).fill(KEY_TWO);
    const second = await pressSync(page, card);

    expect(position(steps, 'response', 'save:jackett_api_key'), 'the key was never saved').toBeGreaterThanOrEqual(0);
    expect(position(steps, 'response', 'save:jackett_api_key')).toBeLessThan(position(steps, 'request', 'sync', 1));
    expect(second.success).toBe(false);
    expect(second.error).not.toMatch(/URL and API key are required/);
    expect(second.error).toMatch(CONNECT_FAILURE);
  });
});

test.describe('Settings: a refused Sync re-reads the section (SEC-005 C1, AC-PROD-11)', () => {
  test.use({ seedConfig: 'fresh_defaults#jackett-reread' });

  test('an address changed behind the page\'s back shows in the Jackett URL field after the press', async ({ page, testServer }) => {
    test.info().annotations.push({ type: SETTINGS_PERSISTENCE_ANNOTATION });
    await saveThroughApi(page, testServer.apiBase, 'jackett_url', SEEDED_URL);
    await saveThroughApi(page, testServer.apiBase, 'jackett_api_key', KEY_ONE);
    const card = await openTorrentCard(page);
    await expect(urlField(card)).toHaveValue(SEEDED_URL);

    // The API, not the page: the page still believes the address is the seeded one.
    await saveThroughApi(page, testServer.apiBase, 'jackett_url', LOOPBACK_URL);
    const answer = await pressSync(page, card);

    expect(answer.success).toBe(false);
    await expect(urlField(card)).toHaveValue(LOOPBACK_URL);
    await expect(syncButton(card)).toBeEnabled();
  });
});

test.describe('Settings: Sync flushes its own section only (SEC-005 C1)', () => {
  test.use({ seedConfig: 'all_groups_aligned#jackett-own-section' });

  test('a Newznab row removed in another section keeps its Undo window and sends nothing', async ({ page, testServer }) => {
    test.info().annotations.push({ type: SETTINGS_PERSISTENCE_ANNOTATION });
    await saveThroughApi(page, testServer.apiBase, 'jackett_url', LOOPBACK_URL);
    await saveThroughApi(page, testServer.apiBase, 'jackett_api_key', KEY_ONE);
    const card = await openTorrentCard(page);
    const newznab = providerCard(page, 'Newznab');
    const groupSaves: string[] = [];
    page.on('request', (request) => {
      if (request.url().includes('settings.save_group')) groupSaves.push(request.url());
    });
    const before = configSection(testServer.configPath, 'newznab');

    await newznab.getByRole('button', { name: 'Remove row 2', exact: true }).click();
    await expect(newznab.getByTestId('combine-removed-line')).toHaveText('Row 2 removed. Undo');
    const answer = await pressSync(page, card);

    expect(answer.error).toMatch(CONNECT_FAILURE);
    // The removal is still held: nothing was sent, the file is as it was, Undo is there.
    expect(groupSaves).toEqual([]);
    expect(configSection(testServer.configPath, 'newznab')).toEqual(before);
    const undo = newznab.getByRole('button', { name: 'Undo', exact: true });
    await expect(undo).toBeVisible();
    await undo.click();
    await expect(newznab.getByRole('button', { name: /^Remove row/ })).toHaveCount(3);
    expect(groupSaves).toEqual([]);
  });
});

test.describe('Wizard: the address is saved before the key (SEC-005 AC-ARCH-9)', () => {
  test.use({ seedConfig: 'fresh_defaults#jackett-wizard-order' });

  test('with the address save held back, the key is still stored with the address typed in the step', async ({ page, testServer }) => {
    test.info().annotations.push({ type: SETTINGS_PERSISTENCE_ANNOTATION });
    const wizardUrl = 'http://wizard-jackett.invalid:9117';
    const steps = watchOrder(page);
    let keyArrived!: () => void;
    const keyRequest = new Promise<void>((resolve) => { keyArrived = resolve; });
    // The address save is held until the key save arrives or 1.5 s pass. Run in order, the key
    // save cannot arrive while the address save is held, so the hold ends by the timer; run in
    // the same batch, it arrives at once, is bound to the address as it stood, and the test fails.
    await page.route('**/settings.save/**', async (route) => {
      const params = new URLSearchParams(route.request().postData() ?? '');
      if (params.get('name') === 'jackett_api_key') keyArrived();
      if (params.get('name') === 'jackett_url') await Promise.race([keyRequest, sleep(1500)]);
      await route.continue();
    });
    await page.goto('/wizard/');
    await page.getByRole('button', { name: /Continue/i }).click();           // Welcome -> Security
    await page.getByRole('button', { name: /Continue/i }).click();           // Security -> Providers
    await expect(page.getByRole('heading', { name: 'Where to Search' })).toBeVisible({ timeout: 10000 });
    await page.getByRole('radio', { name: /^Torrents/ }).click();
    await page.getByRole('switch', { name: 'Enable Jackett / TorrentPotato' }).click();
    await page.locator('#wizard-jackett-url').fill(wizardUrl);
    await page.locator('#wizard-jackett-api-key').fill(KEY_ONE);

    await page.getByRole('button', { name: /Continue/i }).click();
    await expect(page.getByRole('heading', { name: 'Where to Search' })).toBeHidden({ timeout: 10000 });

    await expect.poll(() => configSection(testServer.configPath, 'torrentpotato').jackett_key_binding,
      { message: 'the key was not bound to the address typed in the step' }).toBe(wizardUrl);
    expect(position(steps, 'response', 'save:jackett_url')).toBeLessThan(position(steps, 'request', 'save:jackett_api_key'));
    expect(configSection(testServer.configPath, 'torrentpotato').jackett_api_key).toBe(KEY_ONE);
  });
});
