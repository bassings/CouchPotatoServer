import AxeBuilder from '@axe-core/playwright';
import type { Locator, Page } from '@playwright/test';
import { test, expect } from './fixtures';
import { expectVisualTransitionsToSettle } from './helpers';

/**
 * The log viewer's two landmarks, on both surfaces that render it.
 *
 * `logs.html` (standalone) and `partials/settings/logs_tab.html` (Settings ->
 * Logs) carry the same markup twice. Both use native elements for what used to
 * be ARIA roles on a <div>: the "Loading logs..." indicator is an <output>
 * (implicit role=status, polite) and the scroll container is a <section> with
 * an accessible name (a region).
 *
 * A semantics change on a live page must not change what assistive technology
 * does or how the page lays out, so this asserts the BEHAVIOUR that existed
 * before (status, polite, region, named, focusable, scrollable, same boxes) as
 * well as the element names. The loading state is held open with a gated
 * route and released explicitly, so every assertion reads a settled state and
 * nothing depends on arrival order or elapsed time.
 */

type Surface = 'standalone' | 'settings';
const SURFACES: Surface[] = ['standalone', 'settings'];
const PHONE = { width: 375, height: 812 };
const ENTRY = '01-02 03:04:05 ERROR [ accessible-source ] visible severity';
const MANY_ENTRIES = Array.from({ length: 400 }, (_, i) => `01-02 03:04:05 INFO [ scroll ] entry number ${i}`);

type Gate = { release: () => void };

async function gateLogs(page: Page, log: string[]): Promise<Gate> {
  let release!: () => void;
  const gate = new Promise<void>((resolve) => { release = resolve; });
  await page.route('**/logging.partial/**', async (route) => {
    await gate;
    await route.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify({ success: true, log }) });
  });
  return { release };
}

async function openLogs(page: Page, surface: Surface, theme: 'light' | 'dark' = 'light'): Promise<Locator> {
  await page.addInitScript((value) => localStorage.setItem('cp-theme', value), theme);
  await page.goto(surface === 'settings' ? '/settings/' : '/logs/');
  if (surface === 'settings') await page.getByRole('tab', { name: 'Logs' }).click();
  await expect.poll(
    () => page.evaluate(() => document.documentElement.classList.contains('light')),
    { message: `${theme} theme was not applied` },
  ).toBe(theme === 'light');
  return page.locator('[x-data="logsPanel()"]');
}

/** Live-region properties of the status nodes inside the logs panel, from the real accessibility tree. */
async function statusLiveness(page: Page): Promise<{ role: string; live: string }[]> {
  const cdp = await page.context().newCDPSession(page);
  try {
    const { nodes } = await cdp.send('Accessibility.getFullAXTree');
    const found: { role: string; live: string }[] = [];
    for (const node of nodes) {
      if (node.ignored || node.role?.value !== 'status' || !node.backendDOMNodeId) continue;
      const { object } = await cdp.send('DOM.resolveNode', { backendNodeId: node.backendDOMNodeId });
      const inside = await cdp.send('Runtime.callFunctionOn', {
        objectId: object.objectId,
        functionDeclaration: 'function () { return !!this.closest(\'[x-data="logsPanel()"]\'); }',
        returnByValue: true,
      });
      if (!inside.result.value) continue;
      const live = node.properties?.find((p) => p.name === 'live')?.value.value;
      found.push({ role: 'status', live: String(live) });
    }
    return found;
  } finally {
    await cdp.detach();
  }
}

for (const surface of SURFACES) {
  test.describe(`${surface} logs`, () => {
    test.use({ viewport: PHONE });

    test('the loading indicator is a polite status whose layout is unchanged', async ({ page }) => {
      const { release } = await gateLogs(page, [ENTRY]);
      try {
        const panel = await openLogs(page, surface);
        const status = panel.getByRole('status');
        await expect(status).toBeVisible();
        await expect(status).toHaveText('Loading logs…');

        const live = await statusLiveness(page);
        expect(live, 'the loading indicator is not exposed as a live status region').toHaveLength(1);
        expect(live[0].live, 'the loading indicator is not announced politely').toBe('polite');

        // Layout: a full-width flex row, padded py-20, its content centred.
        const measured = await status.evaluate((el) => {
          const style = getComputedStyle(el);
          const box = el.getBoundingClientRect();
          const content = el.firstElementChild!.getBoundingClientRect();
          const parent = el.parentElement!.getBoundingClientRect();
          const parentStyle = getComputedStyle(el.parentElement!);
          return {
            display: style.display,
            width: box.width,
            height: box.height,
            padY: parseFloat(style.paddingTop) + parseFloat(style.paddingBottom),
            contentHeight: content.height,
            offCentre: (content.left + content.width / 2) - (box.left + box.width / 2),
            parentInnerWidth: parent.width - parseFloat(parentStyle.paddingLeft) - parseFloat(parentStyle.paddingRight),
          };
        });
        expect(measured.display, 'an inline <output> lost its flex layout').toBe('flex');
        expect(measured.width).toBeCloseTo(measured.parentInnerWidth, 0);
        expect(measured.height).toBeCloseTo(measured.padY + measured.contentHeight, 0);
        expect(measured.padY).toBe(160);
        expect(Math.abs(measured.offCentre), 'the loading content is no longer centred').toBeLessThanOrEqual(1);
      } finally {
        release();
      }
    });

    test('the indicator and the container use native elements, not roles on divs (S6819)', async ({ page }) => {
      const { release } = await gateLogs(page, [ENTRY]);
      try {
        const panel = await openLogs(page, surface);
        await expect(panel.getByRole('status')).toHaveJSProperty('tagName', 'OUTPUT');
        await expect(panel.getByRole('region', { name: 'Application logs' })).toHaveJSProperty('tagName', 'SECTION');
        // The native elements carry the roles implicitly; a redundant explicit
        // role is exactly what SonarQube S6819 asks to remove.
        await expect(panel.locator('output[role], section[role]')).toHaveCount(0);
      } finally {
        release();
      }
    });

    test('x-show hides the loading indicator once entries arrive and entries are exposed', async ({ page }) => {
      const { release } = await gateLogs(page, [ENTRY]);
      try {
        const panel = await openLogs(page, surface);
        await expect(panel.getByRole('status')).toBeVisible();
        release();
        await expect(panel.getByText('visible severity', { exact: true })).toBeVisible();
        await expect(panel.getByRole('status')).toBeHidden();
      } finally {
        release();
      }
    });

    test('the log container is a named, keyboard-focusable region that scrolls', async ({ page }) => {
      const { release } = await gateLogs(page, MANY_ENTRIES);
      release();
      const panel = await openLogs(page, surface);
      const region = panel.getByRole('region', { name: 'Application logs' });
      await expect(region).toHaveCount(1);
      await expect(region).toHaveAttribute('id', 'log-container');
      await expect(region).toHaveAttribute('tabindex', '0');
      await expect(region.getByText('entry number 399')).toBeAttached();

      // Reached by Tab from the control before it, with no pointer and no focus() call.
      await panel.getByRole('button', { name: /^Clear/ }).focus();
      await page.keyboard.press('Tab');
      await expect(region).toBeFocused();

      const indicator = await region.evaluate((el) => {
        const style = getComputedStyle(el);
        return {
          focusVisible: el.matches(':focus-visible'),
          outlineStyle: style.outlineStyle,
          outlineWidth: parseFloat(style.outlineWidth),
          overflowY: style.overflowY,
          scrollable: el.scrollHeight > el.clientHeight,
        };
      });
      expect(indicator.focusVisible, 'keyboard focus is not matched by :focus-visible').toBe(true);
      expect(indicator.outlineStyle, 'the focused log region has no visible outline').not.toBe('none');
      expect(indicator.outlineWidth).toBeGreaterThanOrEqual(1);
      expect(indicator.overflowY).toBe('auto');
      expect(indicator.scrollable, 'the log container no longer scrolls its own overflow').toBe(true);

      await page.keyboard.press('PageDown');
      await expect.poll(() => region.evaluate((el) => el.scrollTop),
        { message: 'PageDown did not scroll the focused log region' }).toBeGreaterThan(0);
    });

    for (const theme of ['light', 'dark'] as const) {
      test(`axe finds no violations in the loading and loaded states in the ${theme} theme`, async ({ page }) => {
        const { release } = await gateLogs(page, [ENTRY]);
        try {
          const panel = await openLogs(page, surface, theme);
          await expect(panel.getByRole('status')).toBeVisible();
          await expectVisualTransitionsToSettle(page, `loading state (${surface}/${theme})`);
          await expectNoViolations(page, panel, `${surface}/${theme} loading`);

          release();
          await expect(panel.getByText('visible severity', { exact: true })).toBeVisible();
          await expectVisualTransitionsToSettle(page, `loaded state (${surface}/${theme})`);
          await expectNoViolations(page, panel, `${surface}/${theme} loaded`);
        } finally {
          release();
        }
      });
    }
  });
}

async function expectNoViolations(page: Page, panel: Locator, label: string) {
  const selector = (await panel.getAttribute('id')) === 'panel-logs' ? '#panel-logs' : '#main-content';
  const results = await new AxeBuilder({ page })
    .include(selector)
    .withTags(['wcag2a', 'wcag2aa', 'wcag21a', 'wcag21aa', 'wcag22aa'])
    .analyze();
  const detail = results.violations
    .flatMap((v) => v.nodes.map((n) => `${v.id}: ${n.html.slice(0, 160)} — ${n.failureSummary}`))
    .join('\n');
  expect(results.violations.length, `${label}:\n${detail}`).toBe(0);
}
