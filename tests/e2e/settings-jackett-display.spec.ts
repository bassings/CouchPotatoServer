import { test, expect, FAKE_JACKETT_KEY } from './fake-jackett';
import { configSection, mockSettingsSave, openProvidersStep, watchLiveRegions } from './helpers';
import {
  DID_NOT_SAVE,
  KEY_ONE,
  OTHER_URL,
  REFUSAL,
  SEEDED_URL,
  SYNC_ROUTE,
  position,
  pressSync,
  refuseByAddressChange,
  resultRegion,
  saveThroughApi,
  STILL_SAVING,
  syncButton,
  KEY_REJECTED,
  holdKeySaves,
  pressEnded,
  refuseAddressSaves,
  watchSyncRequests,
  stubWizardSyncRefusal,
  syncField,
  urlField,
  keyField,
  openTorrentCard,
  watchOrder,
  SECTION,
} from './jackett-sync-page';
import { combineGroupWriter, SETTINGS_PERSISTENCE_ANNOTATION } from './settings_persistence';

/**
 * SEC-005 P3: what the user reads and hears when Sync does not run, on the real server.
 *
 * No `page.route` on `torrentpotato.jackett_sync` in the Settings tests (AC-QA-19): the refusal comes
 * from the real guard (a key saved for one address, then the address changed through the API), and
 * the success half from the fake Jackett of ./fake-jackett.ts, which the app really calls over HTTP.
 * The one stubbed test is the wizard's (AC-A11Y-4), which cannot reach the refusal by itself.
 */

/** The save of the key, as the browser sent it and the server answered it. Arm before the press. */
const keySaveAnswer = (page: import('@playwright/test').Page) => page.waitForResponse((response) => {
  const request = response.request();
  return /settings\.save\//.test(response.url())
    && new URLSearchParams(request.postData() ?? '').get('name') === 'jackett_api_key';
});

test.describe('Settings: the refusal is shown on the Sync result (SEC-005 P3, AC-DESIGN-5, AC-A11Y-3)', () => {
  test.use({ seedConfig: 'fresh_defaults#jackett-display-refusal' });

  test('shows the server text verbatim in a status region that was already in the page, once per press, with focus on the button', async ({ page, testServer }) => {
    test.info().annotations.push({ type: SETTINGS_PERSISTENCE_ANNOTATION });
    await refuseByAddressChange(page, testServer.apiBase, KEY_ONE, OTHER_URL);
    const liveTexts = await watchLiveRegions(page);
    const card = await openTorrentCard(page);
    const region = resultRegion(card);

    // Before the response: the region is in the accessibility tree, empty, and is not display:none.
    await expect(syncField(card).getByRole('status')).toHaveCount(1);
    await expect(region).toHaveText('');
    expect(await region.evaluate((element) => getComputedStyle(element).display)).not.toBe('none');
    await region.evaluate((element) => element.setAttribute('data-probe', 'same-node'));

    const first = await pressSync(page, card);

    expect(first).toEqual({ success: false, error: REFUSAL });
    await expect(region).toHaveText(REFUSAL);
    expect(await region.evaluate((element) => element.textContent)).toBe(REFUSAL);
    // The same node: it was not removed and re-created together with its text.
    await expect(region).toHaveAttribute('data-probe', 'same-node');
    await expect(region).toHaveClass(/text-cp-danger/);
    await expect(region).not.toHaveClass(/text-cp-success/);
    expect((await liveTexts()).filter((text) => text === REFUSAL)).toHaveLength(1);
    // Focus stayed on the button, which is operable again.
    await expect(syncButton(card)).toBeFocused();
    await expect(syncButton(card)).not.toHaveAttribute('aria-disabled', 'true');

    // Enter and Space press it again; each press announces the refusal once more, no more.
    const pressWith = async (key: 'Enter' | 'Space', announcements: number) => {
      const answered = page.waitForResponse((response) => response.url().includes(SYNC_ROUTE));
      await page.keyboard.press(key);
      expect((await (await answered).json()).error).toBe(REFUSAL);
      await expect.poll(async () => (await liveTexts()).filter((text) => text === REFUSAL).length).toBe(announcements);
      await expect(syncButton(card)).toBeFocused();
      await expect(syncButton(card)).not.toHaveAttribute('aria-disabled', 'true');
    };
    await pressWith('Enter', 2);
    await pressWith('Space', 3);
    expect((await liveTexts()).filter((text) => text === REFUSAL)).toHaveLength(3);
  });
});

test.describe('Settings: a key that matches the address syncs (SEC-005 AC-QA-19, paired)', () => {
  test.use({ seedConfig: 'fresh_defaults#jackett-display-success' });

  test('shows the success and no refusal, and the fake Jackett received the saved key', async ({ page, testServer, fakeJackett }) => {
    test.info().annotations.push(...combineGroupWriter());
    await saveThroughApi(page, testServer.apiBase, 'jackett_url', fakeJackett.url);
    await saveThroughApi(page, testServer.apiBase, 'jackett_api_key', FAKE_JACKETT_KEY);
    const card = await openTorrentCard(page);

    const answer = await pressSync(page, card);

    expect(answer.success).toBe(true);
    await expect(resultRegion(card)).toHaveText('Synced 2 indexers from Jackett (2 new)');
    await expect(resultRegion(card)).toHaveClass(/text-cp-success/);
    await expect(card.getByText(REFUSAL)).toHaveCount(0);
    expect(fakeJackett.requests).toEqual([{ path: '/torznab/all/api', query: 'indexers', keyAccepted: true }]);
  });
});

test.describe('Settings: recovery after the refusal is one step (SEC-005 AC-PROD-3, AC-DESIGN-4)', () => {
  test.use({ seedConfig: 'fresh_defaults#jackett-display-recovery' });

  test('check the address, enter the key again, press Sync with no wait: it syncs against the address saved', async ({ page, testServer, fakeJackett }) => {
    test.info().annotations.push(...combineGroupWriter());
    // The key was saved for another address; the address is now the fake Jackett's.
    await refuseByAddressChange(page, testServer.apiBase, KEY_ONE, fakeJackett.url);
    const steps = watchOrder(page);
    // The fake clock stops the page's own debounce: the key reaches the server only through the button.
    const card = await openTorrentCard(page, { fakeClock: true });
    await expect(urlField(card)).toHaveValue(fakeJackett.url);

    const refused = await pressSync(page, card);

    expect(refused).toEqual({ success: false, error: REFUSAL });
    await expect(resultRegion(card)).toHaveText(REFUSAL);
    // Refused before the network: nothing reached the fake Jackett.
    expect(fakeJackett.requests).toEqual([]);

    // The address is the one to use (the user checked it); the key is entered again, no wait before the press.
    await keyField(card).fill(FAKE_JACKETT_KEY);
    const synced = await pressSync(page, card);

    expect(position(steps, 'response', 'save:jackett_api_key'), 'the key was never saved').toBeGreaterThanOrEqual(0);
    expect(position(steps, 'response', 'save:jackett_api_key')).toBeLessThan(position(steps, 'request', 'sync', 1));
    expect(synced.success).toBe(true);
    await expect(resultRegion(card)).toHaveText('Synced 2 indexers from Jackett (2 new)');
    await expect(card.getByText(REFUSAL)).toHaveCount(0);
    await expect(urlField(card)).toHaveValue(fakeJackett.url);
    expect(fakeJackett.requests).toEqual([{ path: '/torznab/all/api', query: 'indexers', keyAccepted: true }]);
    expect(configSection(testServer.configPath, SECTION).jackett_key_binding).toBe(fakeJackett.url);
  });
});

test.describe('Settings: a key Jackett does not accept says so (SEC-005 D9)', () => {
  test.use({ seedConfig: 'fresh_defaults#jackett-display-key-rejected' });

  test('a wrong key entered after the refusal is saved, sent, and Jackett\'s answer reads "did not accept"', async ({ page, testServer, fakeJackett }) => {
    test.info().annotations.push({ type: SETTINGS_PERSISTENCE_ANNOTATION });
    await refuseByAddressChange(page, testServer.apiBase, KEY_ONE, fakeJackett.url);
    const card = await openTorrentCard(page);
    await pressSync(page, card);
    await expect(resultRegion(card)).toHaveText(REFUSAL);

    // The key is entered again, and it is the wrong one: the fake answers it the way the app now recognises.
    await keyField(card).fill('placeholder-wrong-key');
    const answer = await pressSync(page, card);

    expect(answer).toEqual({ success: false, error: KEY_REJECTED });
    await expect(resultRegion(card)).toHaveText(KEY_REJECTED);
    await expect(resultRegion(card)).toHaveClass(/text-cp-danger/);
    expect(fakeJackett.requests).toEqual([{ path: '/torznab/all/api', query: 'indexers', keyAccepted: false }]);
  });
});

test.describe('Settings: Sync does not run on top of a value that did not save (SEC-005 D7, AC-PROD-12, AC-QA-23)', () => {
  test.describe('refused by the server', () => {
    test.use({ seedConfig: 'fresh_defaults#jackett-display-save-refused' });

    test('the key save is refused, Sync says so, again on Enter, and no sync request is made by the page or reaches the fake Jackett', async ({ page, testServer, fakeJackett }) => {
      test.info().annotations.push({ type: SETTINGS_PERSISTENCE_ANNOTATION });
      await saveThroughApi(page, testServer.apiBase, 'jackett_url', fakeJackett.url);
      await saveThroughApi(page, testServer.apiBase, 'jackett_api_key', FAKE_JACKETT_KEY);
      // The clock is held: only the press sends the typed value.
      const card = await openTorrentCard(page, { fakeClock: true });
      const syncUrls = watchSyncRequests(page);
      const keySaves: string[] = [];
      page.on('request', (request) => {
        if (/settings\.save\//.test(request.url()) && new URLSearchParams(request.postData() ?? '').get('name') === 'jackett_api_key') keySaves.push('sent');
      });
      const saveAnswer = keySaveAnswer(page);

      // The displayed mask of the stored key: the server refuses it (P1), so the save does not land.
      await keyField(card).fill('*'.repeat(FAKE_JACKETT_KEY.length));
      await syncButton(card).click();

      expect((await (await saveAnswer).json()).success).toBe(false);
      await expect(resultRegion(card)).toHaveText(DID_NOT_SAVE);
      await expect(resultRegion(card)).toHaveClass(/text-cp-danger/);
      await expect(syncButton(card)).toBeFocused();
      await pressEnded(card);
      // The press is over: whatever it was going to send, it has sent.
      expect(syncUrls).toEqual([]);
      expect(fakeJackett.requests).toEqual([]);
      expect(configSection(testServer.configPath, SECTION).jackett_api_key).toBe(FAKE_JACKETT_KEY);

      // A second press, from the keyboard, with nothing changed: the refused value is sent AGAIN, refused again.
      await page.keyboard.press('Enter');
      await expect.poll(() => keySaves.length).toBe(2);
      await expect(resultRegion(card)).toHaveText(DID_NOT_SAVE);
      await pressEnded(card);
      expect(syncUrls).toEqual([]);
      expect(fakeJackett.requests).toEqual([]);
    });
  });

  test.describe('unanswered at the end of the wait', () => {
    test.use({ seedConfig: 'fresh_defaults#jackett-display-save-unanswered' });

    test('the key save is never answered: the button says it is busy during the wait, "not finished saving" after it, and again on Enter', async ({ page, testServer, fakeJackett }) => {
      test.info().annotations.push({ type: SETTINGS_PERSISTENCE_ANNOTATION });
      await saveThroughApi(page, testServer.apiBase, 'jackett_url', fakeJackett.url);
      await saveThroughApi(page, testServer.apiBase, 'jackett_api_key', FAKE_JACKETT_KEY);
      const card = await openTorrentCard(page, { fakeClock: true });
      const held = await holdKeySaves(page);
      const syncUrls = watchSyncRequests(page);

      await keyField(card).fill('placeholder-typed-key');
      await syncButton(card).click();
      await held.firstSent;
      // During the wait: busy (aria-disabled, not disabled), saying so, with the region still empty.
      await expect(syncButton(card)).toHaveAttribute('aria-disabled', 'true');
      await expect(syncButton(card)).toHaveAccessibleName(/^Saving… Sync Indexers$/);
      await expect(resultRegion(card)).toHaveText('');
      await page.clock.fastForward(10_000);

      await expect(resultRegion(card)).toHaveText(STILL_SAVING);
      await expect(resultRegion(card)).toHaveClass(/text-cp-danger/);
      await expect(syncButton(card)).toBeFocused();
      await pressEnded(card);
      expect(syncUrls).toEqual([]);

      // The value is still unsaved (no answer is not an acceptance): Enter sends it again, and waits again.
      await page.keyboard.press('Enter');
      await expect.poll(held.sent).toBe(2);
      await expect(syncButton(card)).toHaveAttribute('aria-disabled', 'true');
      await page.clock.fastForward(10_000);
      await expect(resultRegion(card)).toHaveText(STILL_SAVING);
      await pressEnded(card);
      expect(syncUrls).toEqual([]);
      expect(fakeJackett.requests).toEqual([]);
    });
  });

  test.describe('an address refused and answered earlier, then the key typed (the sequence review round 1 found)', () => {
    test.use({ seedConfig: 'fresh_defaults#jackett-display-address-then-key' });

    test('Sync sends the address again, never the key behind it, and nothing reaches the fake Jackett; the config is unchanged', async ({ page, testServer, fakeJackett }) => {
      test.info().annotations.push({ type: SETTINGS_PERSISTENCE_ANNOTATION });
      await saveThroughApi(page, testServer.apiBase, 'jackett_url', fakeJackett.url);
      await saveThroughApi(page, testServer.apiBase, 'jackett_api_key', FAKE_JACKETT_KEY);
      const before = configSection(testServer.configPath, SECTION);
      const card = await openTorrentCard(page, { fakeClock: true });
      const addressRefusals = await refuseAddressSaves(page);
      const steps = watchOrder(page);
      const syncUrls = watchSyncRequests(page);

      // The address is typed, its timer runs, its save is sent, refused and ANSWERED (a toast says so).
      await urlField(card).fill(OTHER_URL);
      await page.clock.runFor(500);
      await expect.poll(addressRefusals.refused).toBe(1);
      // The toast names the field by its label, not its key (a screen reader would spell out jackett_url).
      // (Read from the toast's text, not its visibility: its transition waits on animation frames, which the held clock withholds.)
      await expect(page.locator('div[x-text="message"]')).toHaveText('Could not save Jackett URL: The address was not accepted.');
      // Then the key is typed, and Sync pressed with no wait.
      await keyField(card).fill('placeholder-new-key');
      await syncButton(card).click();

      await expect(resultRegion(card)).toHaveText(DID_NOT_SAVE);
      await pressEnded(card);
      // The address was sent again by the press; the key was not sent at all.
      expect(addressRefusals.refused()).toBe(2);
      expect(steps.filter((step) => step.kind === 'request' && step.name === 'save:jackett_api_key')).toEqual([]);
      expect(syncUrls).toEqual([]);
      expect(fakeJackett.requests).toEqual([]);
      expect(configSection(testServer.configPath, SECTION)).toEqual(before);

      // Press again: the address is sent again, refused again, still no key and no sync.
      await syncButton(card).click();
      await expect.poll(addressRefusals.refused).toBe(3);
      await expect(resultRegion(card)).toHaveText(DID_NOT_SAVE);
      await pressEnded(card);
      expect(steps.filter((step) => step.kind === 'request' && step.name === 'save:jackett_api_key')).toEqual([]);
      expect(syncUrls).toEqual([]);
      expect(fakeJackett.requests).toEqual([]);
      expect(configSection(testServer.configPath, SECTION)).toEqual(before);
    });
  });

  test.describe('a stop after an earlier success', () => {
    test.use({ seedConfig: 'fresh_defaults#jackett-display-stop-after-success' });

    test('shows the stop in the danger style, not the success green left by the earlier press', async ({ page, testServer, fakeJackett }) => {
      test.info().annotations.push(...combineGroupWriter());
      await saveThroughApi(page, testServer.apiBase, 'jackett_url', fakeJackett.url);
      await saveThroughApi(page, testServer.apiBase, 'jackett_api_key', FAKE_JACKETT_KEY);
      const card = await openTorrentCard(page, { fakeClock: true });
      await pressSync(page, card);
      await expect(resultRegion(card)).toHaveClass(/text-cp-success/);

      await keyField(card).fill('*'.repeat(FAKE_JACKETT_KEY.length));
      await syncButton(card).click();

      await expect(resultRegion(card)).toHaveText(DID_NOT_SAVE);
      await expect(resultRegion(card)).toHaveClass(/text-cp-danger/);
      await expect(resultRegion(card)).not.toHaveClass(/text-cp-success/);
    });
  });
});

test.describe('Wizard: the refusal on the Jackett result line (SEC-005 AC-A11Y-4)', () => {
  test('shows the refusal verbatim in the danger style and announces it after "Syncing…", again on a repeat', async ({ page }) => {
    // The one stubbed sync route of SEC-005's tests: the wizard saves the address and key before every
    // sync, so it reaches the refusal only if the saved pair changes in between. Saves reach nothing.
    await mockSettingsSave(page);
    const stub = await stubWizardSyncRefusal(page);
    const liveTexts = await watchLiveRegions(page);
    await openProvidersStep(page, /^Torrents/);
    await page.getByRole('switch', { name: 'Enable Jackett / TorrentPotato' }).click();
    await page.locator('#wizard-jackett-url').fill(SEEDED_URL);
    await page.locator('#wizard-jackett-api-key').fill(KEY_ONE);
    const sync = page.getByRole('button', { name: /^(Sync Trackers from Jackett|Syncing…)$/ });
    const line = page.locator('p[x-text="jackettSyncResult"]');
    const announced = async () => (await liveTexts()).filter((text) => text === 'Syncing…' || text === REFUSAL);

    await sync.click();

    await expect.poll(stub.syncs).toBe(1);
    await expect(line).toHaveText(REFUSAL);
    expect(await line.evaluate((element) => element.textContent)).toBe(REFUSAL);
    await expect(line).toHaveClass(/text-cp-danger/);
    await expect(page.getByTestId('wizard-status')).toHaveText(REFUSAL);
    await expect.poll(announced).toEqual(['Syncing…', REFUSAL]);
    await expect(sync).toBeFocused();

    await page.keyboard.press('Enter');
    await expect.poll(stub.syncs).toBe(2);
    await expect.poll(announced).toEqual(['Syncing…', REFUSAL, 'Syncing…', REFUSAL]);
    // The visible line is not a live region as well, or it would be read twice.
    expect(await line.evaluate((element) => !!element.closest('[aria-live], [role="status"], [role="alert"], output'))).toBe(false);
  });
});
