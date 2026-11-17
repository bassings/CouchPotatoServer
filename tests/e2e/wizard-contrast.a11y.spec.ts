import AxeBuilder from '@axe-core/playwright';
import type { Locator, Page } from '@playwright/test';
import { test, expect } from './fixtures';
import { expectVisualTransitionsToSettle, mockSettingsSave, openProvidersStep, showWizardRefusal, TEXT_CONTRAST, waitForNewznabRead } from './helpers';

/**
 * Text contrast (WCAG 2.2 AA 1.4.3) on every step of the setup wizard, in both
 * themes, at phone width and desktop width, with NO exclusion.
 *
 * The three hint lines on the Providers step's source buttons ("NZB indexers",
 * "Torrent trackers", "Maximum coverage") measured 2.34:1 light and 3.21:1
 * dark when their button was selected, and 2.42:1 light and 3.09:1 dark when it
 * was not (`opacity-60` on 10px text). The two button states have different
 * foreground and background colours, so each is scanned on its own, and the
 * rest of the wizard is scanned in the richest state the user can reach (every
 * provider on, clients chosen, folders filled in, Jackett sync results showing)
 * because axe only measures text that is on screen.
 *
 * NOT covered, deliberately and openly: the wizard's own visual toast
 * (`x-show="message"`). It is a 20% tint of the success/danger token behind
 * text in that same token, so its ratio depends on whatever is beneath it.
 * Measured at 1280px: light success 4.49:1 and dark error 4.29:1 (both need
 * 4.5:1); at 375px axe cannot decide ("incomplete") because the toast overlaps
 * page content. Settings ships the identical markup, and the fix is a design
 * decision about the toast component, not a one-token change here. It is
 * recorded in docs/technical-debt.md rather than excluded from a scan.
 */

const VIEWPORTS = [{ width: 375, height: 812 }, { width: 1280, height: 900 }];
const STEPS = ['Welcome', 'Security', 'Providers', 'Downloader', 'Library', 'Done'];

type Scene = { label: string; step: number; apply: string };

const RICH = `
  state.formData.newznab.enabled = true;
  state.formData.newznab.entries = [{ host: 'https://indexer.invalid', api_key: '' }];
  state.formData.binsearch.enabled = true;
  state.formData.thepiratebay.enabled = true;
  state.formData.yts.enabled = true;
  state.formData.torrentpotato.enabled = true;
  state.formData.usenetClient = 'sabnzbd';
  state.formData.torrentClient = 'qbittorrent';
  state.formData.blackholeEnabled = true;
  state.formData.renamer.from = '/downloads/complete';
  state.formData.renamer.to = '/movies';
`;

const SCENES: Scene[] = [
  { label: 'Welcome', step: 0, apply: '' },
  { label: 'Security', step: 1, apply: '' },
  // The source buttons in each of their two visual states: selected and not.
  { label: 'Providers, Usenet selected', step: 2, apply: `state.formData.searchType = 'usenet';` },
  { label: 'Providers, Torrents selected', step: 2, apply: `state.formData.searchType = 'torrents';` },
  { label: 'Providers, Both selected', step: 2, apply: `state.formData.searchType = 'both'; ${RICH}` },
  {
    label: 'Providers, sync succeeded', step: 2,
    apply: `state.formData.searchType = 'torrents'; ${RICH} state.jackettSyncResult = 'Synced 3 trackers'; state.jackettSyncSuccess = true;`,
  },
  {
    label: 'Providers, sync failed', step: 2,
    apply: `state.formData.searchType = 'torrents'; ${RICH} state.jackettSyncResult = 'Sync failed'; state.jackettSyncSuccess = false;`,
  },
  { label: 'Downloader, clients chosen', step: 3, apply: `state.formData.searchType = 'both'; ${RICH}` },
  { label: 'Downloader, nothing chosen', step: 3, apply: `state.formData.searchType = 'both';` },
  { label: 'Library, renaming on', step: 4, apply: RICH },
  { label: 'Library, renaming off', step: 4, apply: `state.formData.renamer.enabled = false;` },
  { label: 'Done', step: 5, apply: RICH },
];

async function mount(page: Page, scene: Scene) {
  await page.evaluate(({ n, code }) => {
    const root = document.querySelector('[x-data="setupWizard()"]') as HTMLElement;
    const state = (window as any).Alpine.$data(root);
    // eslint-disable-next-line no-new-func
    new Function('state', `${code} state.currentStep = ${n};`)(state);
  }, { n: scene.step, code: scene.apply });
  await expect(page.locator('[x-text="steps[currentStep]"]')).toHaveText(STEPS[scene.step]);
  // The folded sections hide their text from axe until opened.
  await page.evaluate(() => document.querySelectorAll('details').forEach((d) => { d.open = true; }));
  await expectVisualTransitionsToSettle(page, scene.label);
}

for (const theme of ['light', 'dark'] as const) {
  for (const viewport of VIEWPORTS) {
    test(`every wizard step meets text contrast with no exclusion at ${viewport.width}px in the ${theme} theme`, async ({ page }) => {
      await mockSettingsSave(page);
      await page.setViewportSize(viewport);
      await page.addInitScript((value) => localStorage.setItem('cp-theme', value), theme);
      await page.goto('/wizard/');
      await waitForNewznabRead(page);
      await expect.poll(
        () => page.evaluate(() => document.documentElement.classList.contains('light')),
        { message: `${theme} theme was not applied` },
      ).toBe(theme === 'light');

      const failures: string[] = [];
      for (const scene of SCENES) {
        await mount(page, scene);
        const results = await new AxeBuilder({ page }).withRules(['color-contrast']).analyze();
        for (const violation of results.violations) {
          for (const node of violation.nodes) {
            const data: any = node.any[0]?.data ?? {};
            failures.push(`${scene.label}: ${node.html.slice(0, 90)} ratio ${data.contrastRatio} (needs ${data.expectedContrastRatio})`);
          }
        }
      }
      expect(failures, `text below its required contrast (${theme}, ${viewport.width}px):\n${failures.join('\n')}`).toEqual([]);
    });
  }
}

// ─────────────────────────────────────────────────────────────────────────────
// SEC-004 P5: the Newznab messages the Providers step can show (AC-A11Y-10, -11).
// A refused save, a misaligned stored group and a failed read each put a message
// in the card. Each is measured at 4.5:1 against its own rendered background and
// scanned with axe, in both themes. The refused state's scan FAILS, not skips,
// when no input is marked invalid (showWizardRefusal asserts it first).
// ─────────────────────────────────────────────────────────────────────────────

const WCAG_TAGS = ['wcag2a', 'wcag2aa', 'wcag21a', 'wcag21aa', 'wcag22aa'];

async function expectReadableAndClean(page: Page, message: Locator, label: string, theme: string) {
  await expectVisualTransitionsToSettle(page, `${theme} theme, ${label}`);
  const ratio = await message.evaluate(TEXT_CONTRAST);
  expect(ratio, `${theme}: ${label} text contrast ${ratio.toFixed(2)}:1`).toBeGreaterThanOrEqual(4.5);
  const results = await new AxeBuilder({ page }).withTags(WCAG_TAGS).analyze();
  expect(results.violations.map((violation) => `${violation.id}: ${violation.nodes.map((node) => node.html.slice(0, 80)).join(' | ')}`)).toEqual([]);
}

for (const theme of ['light', 'dark'] as const) {
  test.describe(`the Newznab card's messages (${theme} theme)`, () => {
    test('a refused save: the text is at least 4.5:1, the input is marked and described by it, and axe is clean', async ({ page }) => {
      await showWizardRefusal(page, theme);
      const input = page.getByLabel('Newznab indexer URL 1');

      await expect(input).toHaveAttribute('aria-invalid', 'true');
      await expect(page.locator(`[id="${await input.getAttribute('aria-describedby')}"]`)).toBeVisible();
      await expectReadableAndClean(page, page.locator('#wizard-newznab-error'), 'refusal', theme);
    });

    test.describe('a failed read', () => {
      test.use({ seedConfig: `newznab_two_stored#wizard-a11y-read-failed-${theme}` });

      test('the message is at least 4.5:1, the retry button is named, and axe is clean', async ({ page }) => {
        await page.addInitScript((value) => localStorage.setItem('cp-theme', value), theme);
        await page.route(/\/settings\/(\?.*)?$/, (route) => route.fulfill({ status: 500, contentType: 'application/json', body: '{}' }));
        await openProvidersStep(page);

        await expect(page.getByRole('button', { name: 'Try loading saved indexers again' })).toBeVisible();
        await expectReadableAndClean(page, page.locator('#wizard-newznab-error'), 'load error', theme);
      });
    });

    test.describe('a read still pending when Continue is pressed', () => {
      test.use({ seedConfig: `newznab_two_stored#wizard-a11y-pending-${theme}` });

      test('the pending message is at least 4.5:1, has no Retry beside it, and axe is clean', async ({ page }) => {
        await page.addInitScript((value) => localStorage.setItem('cp-theme', value), theme);
        await page.route(/\/settings\/(\?.*)?$/, () => new Promise(() => undefined));
        await openProvidersStep(page);
        await page.getByRole('button', { name: /^Continue$/ }).click();

        await expect(page.locator('#wizard-newznab-error')).toContainText('still loading');
        await expect(page.getByRole('button', { name: /Try loading saved indexers again/ })).toBeHidden();
        await expectReadableAndClean(page, page.locator('#wizard-newznab-error'), 'pending message', theme);
      });
    });

    test.describe('a misaligned stored group', () => {
      test.use({ seedConfig: `newznab_misaligned_key_short#wizard-a11y-notice-${theme}` });

      test('the notice is at least 4.5:1 and axe is clean with it shown', async ({ page }) => {
        await page.addInitScript((value) => localStorage.setItem('cp-theme', value), theme);
        await openProvidersStep(page);

        const notice = page.getByTestId('combine-misaligned-notice');
        await expect(notice).toBeVisible();
        await expectReadableAndClean(page, notice.locator('p'), 'misaligned notice', theme);
      });
    });
  });
}
