import AxeBuilder from '@axe-core/playwright';
import type { Locator, Page } from '@playwright/test';

import { test, expect } from './fixtures';
import {
  expectVisualTransitionsToSettle,
  mockSettingsSave,
  openProvidersStep,
  TEXT_CONTRAST,
  watchLiveRegions,
} from './helpers';
import {
  DID_NOT_SAVE,
  KEY_ONE,
  OTHER_URL,
  REFUSAL,
  SEEDED_URL,
  STILL_SAVING,
  SYNC_ROUTE,
  THEMES,
  holdKeySaves,
  syncField,
  openTorrentCard,
  pressEnded,
  pressSync,
  typeKeyAndPress,
  watchSyncRequests,
  stubWizardSyncRefusal,
  refuseByAddressChange,
  resultRegion,
  saveThroughApi,
  syncButton,
  urlField,
  type Theme,
} from './jackett-sync-page';
import { SETTINGS_PERSISTENCE_ANNOTATION } from './settings_persistence';

/**
 * SEC-005 P3: the Sync result and the wizard's Jackett result line, to WCAG 2.2 AA, in both themes.
 *
 * AC-A11Y-5 (4.5:1, measured against the surface the text is painted on), AC-A11Y-6 (axe, scoped to the
 * TorrentPotato card in two states, and the wizard's Jackett step after a refused sync), AC-DESIGN-1
 * (no control is added), AC-A11Y-11 (the two "did not run" texts of AC-PROD-12). The refusal is reached
 * on the real server, with no stub on the sync route (AC-QA-19); the wizard's is the one stubbed route.
 * Each test asserts its state is on screen first: a scan of a page without the message proves nothing.
 */

const LOCKED = 'These rows are locked while the action runs.';
const MASK_TOAST = 'Could not save Jackett API Key: That is the masked placeholder, not the real value. '
  + 'Clear the field and paste the credential to change it.';
const WCAG_TAGS = ['wcag2a', 'wcag2aa', 'wcag21a', 'wcag21aa', 'wcag22aa'];

/** axe scoped to the TorrentPotato card: the card is marked, and only that subtree is scanned. */
async function cardViolations(page: Page, card: Locator): Promise<string[]> {
  await card.evaluate((element) => element.setAttribute('data-axe-scope', 'torrentpotato-card'));
  const results = await new AxeBuilder({ page })
    .include('[data-axe-scope="torrentpotato-card"]')
    .withTags(WCAG_TAGS)
    .analyze();
  return results.violations.map((violation) => `${violation.id}: ${violation.nodes.map((node) => node.html.slice(0, 90)).join(' | ')}`);
}

async function expectReadable(region: Locator, label: string, theme: Theme) {
  const ratio = await region.evaluate(TEXT_CONTRAST);
  expect(ratio, `${theme}: ${label} contrast ${ratio.toFixed(2)}:1`).toBeGreaterThanOrEqual(4.5);
}

for (const theme of THEMES) {
  test.describe(`Settings: the Sync result (${theme} theme)`, () => {
    test.use({ seedConfig: `fresh_defaults#jackett-a11y-refusal-${theme}` });

    test('AC-DESIGN-1: the card has the Jackett URL, the Jackett API Key and Sync Indexers, and no control about a binding', async ({ page, testServer }) => {
      test.info().annotations.push({ type: SETTINGS_PERSISTENCE_ANNOTATION });
      await refuseByAddressChange(page, testServer.apiBase, KEY_ONE, OTHER_URL);
      const card = await openTorrentCard(page, { theme });

      const controls = await card.evaluate((element) => {
        const nameOf = (control: Element) => control.getAttribute('aria-label')
          || (control as HTMLInputElement).labels?.[0]?.textContent?.trim()
          || control.textContent?.trim() || '';
        const all = [...element.querySelectorAll('input, button, select, textarea, [role="switch"]')];
        const firstRow = element.querySelector('[data-testid="combine-row-cells"]');
        const rowStart = firstRow ? all.findIndex((control) => firstRow.contains(control)) : all.length;
        // After the enable switch and the header, before the first indexer row.
        const between = all.slice(0, rowStart)
          .filter((control) => control.getAttribute('role') !== 'switch' && control.closest('h3') === null);
        return {
          between: between.map((control) => ({ tag: control.tagName.toLowerCase(), type: control.getAttribute('type'), name: nameOf(control) })),
          identifiers: all.flatMap((control) => [nameOf(control), control.id, control.getAttribute('name') ?? '']),
        };
      });

      // The controls between the enable switch and the indexer rows: exactly these three.
      expect(controls.between).toEqual([
        { tag: 'input', type: 'text', name: 'Jackett URL' },
        { tag: 'input', type: 'password', name: 'Jackett API Key' },
        { tag: 'button', type: 'button', name: 'Sync Indexers' },
      ]);
      expect(controls.identifiers.filter((text) => /binding|bound|fingerprint|normalis/i.test(text))).toEqual([]);
      expect(await card.getByRole('button', { name: /trust|rebind|keep key/i }).count()).toBe(0);
    });

    test('with the key bound to the address: axe reports nothing on the TorrentPotato card', async ({ page, testServer }) => {
      test.info().annotations.push({ type: SETTINGS_PERSISTENCE_ANNOTATION });
      await saveThroughApi(page, testServer.apiBase, 'jackett_url', SEEDED_URL);
      await saveThroughApi(page, testServer.apiBase, 'jackett_api_key', KEY_ONE);
      const card = await openTorrentCard(page, { theme });
      // The state under test: the key is saved, nothing is refused, and the (empty) result region is in the page.
      await expect(urlField(card)).toHaveValue(SEEDED_URL);
      await expect(resultRegion(card)).toHaveText('');
      await expectVisualTransitionsToSettle(page, `${theme} theme, matched`);

      expect(await cardViolations(page, card)).toEqual([]);
    });

    test('after a refused sync: the text is at least 4.5:1 and says what happened in words, axe reports nothing on the card, focus stays on Sync', async ({ page, testServer }) => {
      test.info().annotations.push({ type: SETTINGS_PERSISTENCE_ANNOTATION });
      await refuseByAddressChange(page, testServer.apiBase, KEY_ONE, OTHER_URL);
      const card = await openTorrentCard(page, { theme });

      const answer = await pressSync(page, card);

      expect(answer.error).toBe(REFUSAL);
      await expect(resultRegion(card)).toHaveText(REFUSAL);
      await expect(syncButton(card)).toBeFocused();
      await expectVisualTransitionsToSettle(page, `${theme} theme, refused`);
      await expectReadable(resultRegion(card), 'refusal', theme);
      expect(await cardViolations(page, card)).toEqual([]);
    });
  });

  test.describe(`Settings: Sync that did not run because a save did not land (${theme} theme)`, () => {
    test.use({ seedConfig: `fresh_defaults#jackett-a11y-notrun-${theme}` });

    test('AC-A11Y-11: "did not save" is in the persistent status region, danger style, announced once, 4.5:1, axe clean, focus on the button', async ({ page, testServer }) => {
      test.info().annotations.push({ type: SETTINGS_PERSISTENCE_ANNOTATION });
      await saveThroughApi(page, testServer.apiBase, 'jackett_url', SEEDED_URL);
      await saveThroughApi(page, testServer.apiBase, 'jackett_api_key', KEY_ONE);
      const liveTexts = await watchLiveRegions(page);
      const card = await openTorrentCard(page, { theme });
      await expect(resultRegion(card)).toHaveText('');
      const syncUrls = watchSyncRequests(page);

      // The displayed mask of the stored key: refused by the server, so the save does not land.
      // Typed and pressed in one browser task so the press, not the field's timer, sends it.
      await typeKeyAndPress(card, '*'.repeat(KEY_ONE.length));

      await expect(resultRegion(card)).toHaveText(DID_NOT_SAVE);
      await expect(resultRegion(card)).toHaveClass(/text-cp-danger/);
      await expect(syncButton(card)).toBeFocused();
      await expect(syncButton(card)).not.toHaveAttribute('aria-disabled', 'true');
      await pressEnded(card);
      // Everything a refused press says to a screen reader, in full: the rows lock (pre-existing), the
      // result, and the toast's alert. A fourth announcement cannot creep in. (The result and the alert
      // are read in either order: both wait on a tick.)
      const said = (await liveTexts()).filter((text) => text.length < 300 && !text.includes('\n'));
      expect(said[0]).toBe(LOCKED);
      expect(said.slice(1).sort()).toEqual([DID_NOT_SAVE, MASK_TOAST].sort());
      expect(syncUrls).toEqual([]);
      await expectVisualTransitionsToSettle(page, `${theme} theme, did not save`);
      await expectReadable(resultRegion(card), 'did-not-save text', theme);
      expect(await cardViolations(page, card)).toEqual([]);
    });

    test('AC-A11Y-11: "not finished saving" is in the same region and style, announced once, 4.5:1, axe clean, focus on the button', async ({ page, testServer }) => {
      test.info().annotations.push({ type: SETTINGS_PERSISTENCE_ANNOTATION });
      await saveThroughApi(page, testServer.apiBase, 'jackett_url', SEEDED_URL);
      await saveThroughApi(page, testServer.apiBase, 'jackett_api_key', KEY_ONE);
      const liveTexts = await watchLiveRegions(page);
      const card = await openTorrentCard(page, { theme, fakeClock: 'running' });
      const held = await holdKeySaves(page);
      const syncUrls = watchSyncRequests(page);

      await typeKeyAndPress(card, 'placeholder-typed-key');
      await held.firstSent;
      await page.clock.fastForward(10_000);

      await expect(resultRegion(card)).toHaveText(STILL_SAVING);
      await expect(resultRegion(card)).toHaveClass(/text-cp-danger/);
      await expect(syncButton(card)).toBeFocused();
      await pressEnded(card);
      // In full: the rows lock, then the one result. No toast: the save was never answered.
      expect((await liveTexts()).filter((text) => text.length < 300 && !text.includes('\n'))).toEqual([LOCKED, STILL_SAVING]);
      expect(syncUrls).toEqual([]);
      await expectVisualTransitionsToSettle(page, `${theme} theme, still saving`);
      await expectReadable(resultRegion(card), 'still-saving text', theme);
      expect(await cardViolations(page, card)).toEqual([]);
    });

    test('a stop after an earlier success is in the danger style, at least 4.5:1', async ({ page, testServer }) => {
      test.info().annotations.push({ type: SETTINGS_PERSISTENCE_ANNOTATION });
      await saveThroughApi(page, testServer.apiBase, 'jackett_url', SEEDED_URL);
      await saveThroughApi(page, testServer.apiBase, 'jackett_api_key', KEY_ONE);
      const card = await openTorrentCard(page, { theme });
      // A success first, so the region carries the success class when the stop arrives. The seeded
      // address is unreachable (.invalid), so this "success" is stood in for by the class the button
      // sets on a successful answer, set through the component the page itself runs.
      await syncField(card).evaluate((field) => {
        const data = (window as any).Alpine.$data(field);
        data.success = true;
        data.result = 'Synced';
      });
      await expect(resultRegion(card)).toHaveClass(/text-cp-success/);

      await typeKeyAndPress(card, '*'.repeat(KEY_ONE.length));

      await expect(resultRegion(card)).toHaveText(DID_NOT_SAVE);
      await expect(resultRegion(card)).toHaveClass(/text-cp-danger/);
      await expectVisualTransitionsToSettle(page, `${theme} theme, stop after success`);
      await expectReadable(resultRegion(card), 'stop after a success', theme);
    });
  });

  test.describe(`Wizard: the Jackett result line after a refused sync (${theme} theme)`, () => {
    test('the text is at least 4.5:1, the wizard has one URL field, one key field and one Sync button, and axe reports nothing', async ({ page }) => {
      await mockSettingsSave(page);
      await stubWizardSyncRefusal(page);
      await page.addInitScript((value) => localStorage.setItem('cp-theme', value), theme);
      await openProvidersStep(page, /^Torrents/);
      await expect.poll(() => page.evaluate(() => document.documentElement.classList.contains('light'))).toBe(theme === 'light');
      await page.getByRole('switch', { name: 'Enable Jackett / TorrentPotato' }).click();
      await page.locator('#wizard-jackett-url').fill(SEEDED_URL);
      await page.locator('#wizard-jackett-api-key').fill(KEY_ONE);

      // AC-DESIGN-1: exactly the controls it had.
      const section = page.locator('div', { has: page.locator('#wizard-jackett-url') }).filter({ has: page.getByRole('button', { name: 'Sync Trackers from Jackett' }) }).last();
      await expect(section.locator('input')).toHaveCount(2);
      await expect(section.getByRole('button', { name: 'Sync Trackers from Jackett' })).toHaveCount(1);

      await page.getByRole('button', { name: 'Sync Trackers from Jackett' }).click();

      const line = page.locator('p[x-text="jackettSyncResult"]');
      await expect(line).toHaveText(REFUSAL);
      await expectVisualTransitionsToSettle(page, `${theme} theme, wizard refused`);
      await expectReadable(line, 'wizard refusal', theme);
      const results = await new AxeBuilder({ page }).withTags(WCAG_TAGS).analyze();
      expect(results.violations.map((violation) => `${violation.id}: ${violation.nodes.map((node) => node.html.slice(0, 90)).join(' | ')}`)).toEqual([]);
    });
  });
}
