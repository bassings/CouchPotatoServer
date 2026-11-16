import type { Locator, Page } from '@playwright/test';
import AxeBuilder from '@axe-core/playwright';

import { test, expect } from './fixtures';
import { expectVisualTransitionsToSettle } from './helpers';

/**
 * SEC-004 P3: the combined field's refusal and misaligned-group notice, to WCAG 2.2 AA.
 *
 * The refusal is stubbed in the server's own shape (a real server refusal is exercised
 * against the real server in settings.spec.ts), so each state is reached the same way in
 * both themes and at every width, and nothing is written. Each test has a hard
 * precondition that the state under test is actually on screen: an axe run over a page
 * with no refusal in it proves nothing.
 */

const THEMES = ['light', 'dark'] as const;

const REFUSAL = {
  success: false,
  error: 'A cell cannot contain a comma.',
  invalid: [{ row: 1, column: 'host', reason: 'comma' }],
};

async function openSearchers(page: Page, theme: (typeof THEMES)[number]): Promise<Locator> {
  await page.addInitScript((selected) => localStorage.setItem('cp-theme', selected), theme);
  await page.goto('/settings/');
  await expect.poll(() => page.evaluate(() => document.documentElement.classList.contains('light')))
    .toBe(theme === 'light');
  await page.getByRole('tab', { name: 'Searchers' }).click();
  const card = page.locator('.bg-cp-card', { has: page.getByRole('heading', { name: 'Newznab', exact: true }) });
  await expect(card).toBeVisible();
  await expectVisualTransitionsToSettle(page, `${theme} theme, Searchers tab`);
  return card;
}

async function showRefusal(page: Page, card: Locator): Promise<Locator> {
  await page.route('**/settings.save_group/**', (route) => route.fulfill({
    status: 200, contentType: 'application/json', body: JSON.stringify(REFUSAL),
  }));
  const host = card.getByLabel('host for row 2', { exact: true });
  await host.fill('https://placeholder-two.invalid/api,https://placeholder-evil.invalid');
  await expect(card.getByTestId('combine-row-error')).toBeVisible();
  // The precondition every measurement below rests on.
  await expect(card.locator('[aria-invalid="true"]')).toHaveCount(1);
  return host;
}

/** In-page: contrast of an element's text against the opaque surface behind it, translucent layers composited. */
const TEXT_CONTRAST = (element: HTMLElement) => {
  type Rgba = { r: number; g: number; b: number; a: number };
  const parse = (value: string): Rgba => {
    const channels = (value.match(/rgba?\(([^)]+)\)/)?.[1] ?? '').split(/[,/ ]+/).filter(Boolean).map(Number.parseFloat);
    return { r: channels[0], g: channels[1], b: channels[2], a: channels.length > 3 ? channels[3] : 1 };
  };
  const over = (top: Rgba, below: Rgba): Rgba => ({
    r: top.r * top.a + below.r * (1 - top.a),
    g: top.g * top.a + below.g * (1 - top.a),
    b: top.b * top.a + below.b * (1 - top.a),
    a: 1,
  });
  const luminance = (c: Rgba) => {
    const ch = (v: number) => { const s = v / 255; return s <= 0.04045 ? s / 12.92 : ((s + 0.055) / 1.055) ** 2.4; };
    return 0.2126 * ch(c.r) + 0.7152 * ch(c.g) + 0.0722 * ch(c.b);
  };
  const layers: Rgba[] = [];
  for (let node: HTMLElement | null = element; node; node = node.parentElement) {
    const layer = parse(getComputedStyle(node).backgroundColor);
    if (layer.a > 0) layers.push(layer);
    if (layer.a === 1) break;
  }
  let backdrop = layers.length ? layers[layers.length - 1] : { r: 255, g: 255, b: 255, a: 1 };
  for (let i = layers.length - 2; i >= 0; i -= 1) backdrop = over(layers[i], backdrop);
  const text = over(parse(getComputedStyle(element).color), backdrop);
  const [hi, lo] = [luminance(text), luminance(backdrop)].sort((a, b) => b - a);
  return (hi + 0.05) / (lo + 0.05);
};

/** In-page: contrast of an outline or border colour against the PARENT's opaque surface (an offset outline is painted on it). */
const EDGE_CONTRAST = (element: HTMLElement, edge: 'outline' | 'border') => {
  type Rgba = { r: number; g: number; b: number; a: number };
  const parse = (value: string): Rgba => {
    const channels = (value.match(/rgba?\(([^)]+)\)/)?.[1] ?? '').split(/[,/ ]+/).filter(Boolean).map(Number.parseFloat);
    return { r: channels[0], g: channels[1], b: channels[2], a: channels.length > 3 ? channels[3] : 1 };
  };
  const over = (top: Rgba, below: Rgba): Rgba => ({
    r: top.r * top.a + below.r * (1 - top.a),
    g: top.g * top.a + below.g * (1 - top.a),
    b: top.b * top.a + below.b * (1 - top.a),
    a: 1,
  });
  const luminance = (c: Rgba) => {
    const ch = (v: number) => { const s = v / 255; return s <= 0.04045 ? s / 12.92 : ((s + 0.055) / 1.055) ** 2.4; };
    return 0.2126 * ch(c.r) + 0.7152 * ch(c.g) + 0.0722 * ch(c.b);
  };
  const layers: Rgba[] = [];
  for (let node = element.parentElement; node; node = node.parentElement) {
    const layer = parse(getComputedStyle(node).backgroundColor);
    if (layer.a > 0) layers.push(layer);
    if (layer.a === 1) break;
  }
  let backdrop = layers.length ? layers[layers.length - 1] : { r: 255, g: 255, b: 255, a: 1 };
  for (let i = layers.length - 2; i >= 0; i -= 1) backdrop = over(layers[i], backdrop);
  const style = getComputedStyle(element);
  const drawn = over(parse(edge === 'outline' ? style.outlineColor : style.borderTopColor), backdrop);
  const [hi, lo] = [luminance(drawn), luminance(backdrop)].sort((a, b) => b - a);
  return { ratio: (hi + 0.05) / (lo + 0.05), width: Number.parseFloat(edge === 'outline' ? style.outlineWidth : style.borderTopWidth), style: edge === 'outline' ? style.outlineStyle : style.borderTopStyle };
};

for (const theme of THEMES) {
  test.describe(`the refused Newznab field (${theme} theme)`, () => {
    test.use({ seedConfig: `newznab_aligned#a11y-refusal-${theme}` });

    test('error text is at least 4.5:1, the marked input is not colour alone, and its focus ring is at least 3:1', async ({ page }) => {
      const card = await openSearchers(page, theme);
      const host = await showRefusal(page, card);
      await expectVisualTransitionsToSettle(page, `${theme} theme, refusal shown`);

      for (const message of await card.locator('[data-testid="combine-row-error"] p').all()) {
        const ratio = await message.evaluate(TEXT_CONTRAST);
        expect(ratio, `${theme}: refusal text contrast ${ratio.toFixed(2)}:1`).toBeGreaterThanOrEqual(4.5);
      }
      // Not colour alone: the text is present whenever the invalid border is, and described.
      await expect(page.locator(`[id="${await host.getAttribute('aria-describedby')}"]`)).toBeVisible();
      const border = await host.evaluate(EDGE_CONTRAST, 'border');
      expect(border.ratio, `${theme}: invalid input border ${border.ratio.toFixed(2)}:1`).toBeGreaterThanOrEqual(3);

      // Reached by the keyboard, so :focus-visible paints the ring.
      await card.getByRole('switch', { name: 'Enable row 2' }).focus();
      await page.keyboard.press('Tab');
      await expect(host).toBeFocused();
      const ring = await host.evaluate(EDGE_CONTRAST, 'outline');
      expect(ring.style, `${theme}: no focus outline on the invalid input`).not.toBe('none');
      expect(ring.width).toBeGreaterThanOrEqual(2);
      expect(ring.ratio, `${theme}: focus ring ${ring.ratio.toFixed(2)}:1`).toBeGreaterThanOrEqual(3);
    });

    test('axe reports nothing on the Searchers tab with the field refused', async ({ page }) => {
      const card = await openSearchers(page, theme);
      await showRefusal(page, card);
      await expectVisualTransitionsToSettle(page, `${theme} theme, refusal shown`);

      const results = await new AxeBuilder({ page })
        .withTags(['wcag2a', 'wcag2aa', 'wcag21a', 'wcag21aa', 'wcag22aa'])
        .analyze();

      expect(results.violations.map((violation) => `${violation.id}: ${violation.nodes.map((node) => node.target.join(' ')).join(' | ')}`)).toEqual([]);
    });

    test('every control keeps its accessible name', async ({ page }) => {
      const card = await openSearchers(page, theme);
      await showRefusal(page, card);

      const names = await card.locator('input, button, [role="switch"]').evaluateAll((controls) => controls
        .filter((control) => (control as HTMLElement).offsetParent !== null)
        .map((control) => control.getAttribute('aria-label') ?? ''));
      const rowControls = names.filter((name) => /for row|row \d/.test(name) || name === 'Add row');

      for (const row of [1, 2, 3]) {
        for (const expected of [`Enable row ${row}`, `host for row ${row}`, `api key for row ${row}`,
          `extra score for row ${row}`, `custom tag for row ${row}`, `Remove row ${row}`]) {
          expect(rowControls, `missing control "${expected}"`).toContain(expected);
        }
      }
      expect(rowControls).toContain('Add row');
      // The names the role locators resolve, not only the attributes: the exact
      // locators the existing accessibility specs use still find each control.
      await expect(card.getByRole('switch', { name: 'Enable row 2', exact: true })).toHaveCount(1);
      await expect(card.getByRole('textbox', { name: 'host for row 2', exact: true })).toHaveCount(1);
      await expect(card.getByRole('button', { name: 'Remove row 2', exact: true })).toHaveCount(1);
      await expect(card.getByRole('button', { name: 'Add row', exact: true })).toHaveCount(1);
    });
  });

  test.describe(`the misaligned-group notice (${theme} theme)`, () => {
    test.use({ seedConfig: `newznab_misaligned_key_short#a11y-notice-${theme}` });

    test('is at least 4.5:1 and axe reports nothing with it shown', async ({ page }) => {
      const card = await openSearchers(page, theme);
      const notice = card.getByTestId('combine-misaligned-notice');
      await expect(notice).toBeVisible();
      await expectVisualTransitionsToSettle(page, `${theme} theme, notice shown`);

      const ratio = await notice.locator('p').evaluate(TEXT_CONTRAST);
      expect(ratio, `${theme}: notice contrast ${ratio.toFixed(2)}:1`).toBeGreaterThanOrEqual(4.5);
      const results = await new AxeBuilder({ page })
        .withTags(['wcag2a', 'wcag2aa', 'wcag21a', 'wcag21aa', 'wcag22aa'])
        .analyze();
      expect(results.violations.map((violation) => violation.id)).toEqual([]);
    });
  });

  for (const [name, width] of [['a 320px viewport', 320], ['200% zoom on a 1280px viewport (640 CSS px)', 640]] as const) {
    test.describe(`reflow at ${name} (${theme} theme)`, () => {
      test.use({ seedConfig: `newznab_misaligned_key_short#a11y-reflow-${theme}-${width}` });

      test('the refusal and the notice show in full with no horizontal scroll', async ({ page }) => {
        await page.setViewportSize({ width, height: 900 });
        const card = await openSearchers(page, theme);
        await expect(card.getByTestId('combine-misaligned-notice')).toBeVisible();
        await showRefusal(page, card);
        await expectVisualTransitionsToSettle(page, `${theme} theme, ${width}px, refusal shown`);

        const layout = await page.evaluate(() => {
          const viewport = document.documentElement.clientWidth;
          const inside = (selector: string) => [...document.querySelectorAll<HTMLElement>(selector)].map((element) => {
            const box = element.getBoundingClientRect();
            return { left: box.left, right: box.right, clipped: element.scrollWidth > element.clientWidth };
          });
          return {
            viewport,
            scroll: document.scrollingElement!.scrollWidth,
            errors: inside('[data-testid="combine-row-error"], [data-testid="combine-row-error"] p'),
            notices: inside('[data-testid="combine-misaligned-notice"], [data-testid="combine-misaligned-notice"] p'),
          };
        });

        expect(layout.scroll).toBeLessThanOrEqual(layout.viewport);
        for (const box of [...layout.errors, ...layout.notices]) {
          expect(box.left).toBeGreaterThanOrEqual(0);
          expect(box.right).toBeLessThanOrEqual(layout.viewport);
          expect(box.clipped).toBe(false);
        }
        expect(layout.errors.length).toBeGreaterThan(0);
        expect(layout.notices.length).toBeGreaterThan(0);
      });
    });
  }
}
