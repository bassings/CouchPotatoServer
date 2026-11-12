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


type Ring = { coverage: Record<'top' | 'left' | 'bottom', number>; minContrast: number };

/**
 * What a keyboard user actually SEES when the log region takes focus: the
 * pixels of the region's own edge, with and without focus, decoded in the page.
 *
 * `getComputedStyle(el).outlineStyle` is not evidence. The global
 * `:focus-visible` rule draws a 2px outline offset 2px OUTSIDE the element, and
 * the region exactly fills a parent with `overflow-hidden`, so the outline was
 * computed, valid, and clipped away entirely (measured: 0 changed pixels in
 * all eight surface x theme x width combinations).
 *
 * Coverage is the share of the 2px edge band (corner squares excluded, because
 * the parent's rounded corners clip them) whose pixels CHANGED between the
 * unfocused and focused screenshots and are at least 3:1 against both what they
 * replaced and the pixel just outside the box, the two surfaces the ring is
 * adjacent to (WCAG 1.4.11). The right edge is not sampled: the scrollbar paints
 * over it.
 */
async function measureFocusRing(page: Page, panel: Locator, region: Locator): Promise<Ring> {
  await page.mouse.move(0, 0);
  // Reach the region the way a keyboard user does. Focus can scroll the page,
  // so centre the region AFTER focusing it and wait for the box to stop moving:
  // both screenshots must frame exactly the same pixels.
  await panel.getByRole('button', { name: /^Clear/ }).focus();
  await page.keyboard.press('Tab');
  await expect(region).toBeFocused();
  await region.evaluate((el) => el.scrollIntoView({ block: 'center' }));
  let last = '';
  await expect.poll(async () => {
    const now = await region.evaluate((el) => JSON.stringify(el.getBoundingClientRect()));
    const stable = now === last;
    last = now;
    return stable;
  }, { message: 'the log region never stopped moving after scrollIntoView' }).toBe(true);

  const origin = await region.evaluate((el) => el.getBoundingClientRect().toJSON());
  const MARGIN = 6;
  const clip = {
    x: Math.max(0, origin.x - MARGIN), y: Math.max(0, origin.y - MARGIN),
    width: origin.width + 2 * MARGIN, height: origin.height + 2 * MARGIN,
  };
  const after = (await page.screenshot({ clip })).toString('base64');
  await region.evaluate((el) => (el as HTMLElement).blur());
  const before = (await page.screenshot({ clip })).toString('base64');

  return page.evaluate(async ({ a, b, geo }) => {
    const decode = async (data: string) => {
      const bitmap = await createImageBitmap(await (await fetch(`data:image/png;base64,${data}`)).blob());
      const ctx = new OffscreenCanvas(bitmap.width, bitmap.height).getContext('2d')!;
      ctx.drawImage(bitmap, 0, 0);
      return { w: bitmap.width, px: ctx.getImageData(0, 0, bitmap.width, bitmap.height).data };
    };
    const A = await decode(a);
    const B = await decode(b);
    const at = (img: { w: number; px: Uint8ClampedArray }, x: number, y: number) => {
      const i = (Math.round(y) * img.w + Math.round(x)) * 4;
      return [img.px[i], img.px[i + 1], img.px[i + 2]];
    };
    const lum = (c: number[]) => {
      const [r, g, bl] = c.map((v) => { const s = v / 255; return s <= 0.04045 ? s / 12.92 : ((s + 0.055) / 1.055) ** 2.4; });
      return 0.2126 * r + 0.7152 * g + 0.0722 * bl;
    };
    const contrast = (c1: number[], c2: number[]) => {
      const [hi, lo] = [lum(c1), lum(c2)].sort((x, y) => y - x);
      return (hi + 0.05) / (lo + 0.05);
    };
    const differs = (x: number, y: number) => at(A, x, y).some((v, k) => v !== at(B, x, y)[k]);

    const x0 = Math.round(geo.bx);
    const y0 = Math.round(geo.by);
    const x1 = Math.round(geo.bx + geo.bw);
    const y1 = Math.round(geo.by + geo.bh);
    const CORNER = 8;
    // Each edge: the two pixel lines the 2px ring occupies, and the line just outside the box.
    const edges = {
      top: { ring: (i: number) => [[x0 + CORNER + i, y0], [x0 + CORNER + i, y0 + 1]], out: (i: number) => [x0 + CORNER + i, y0 - 1], n: x1 - x0 - 2 * CORNER },
      bottom: { ring: (i: number) => [[x0 + CORNER + i, y1 - 1], [x0 + CORNER + i, y1 - 2]], out: (i: number) => [x0 + CORNER + i, y1], n: x1 - x0 - 2 * CORNER },
      left: { ring: (i: number) => [[x0, y0 + CORNER + i], [x0 + 1, y0 + CORNER + i]], out: (i: number) => [x0 - 1, y0 + CORNER + i], n: y1 - y0 - 2 * CORNER },
    } as const;
    const coverage = { top: 0, left: 0, bottom: 0 };
    let minContrast = Infinity;
    for (const name of ['top', 'left', 'bottom'] as const) {
      const e = edges[name];
      let hit = 0;
      for (let i = 0; i < e.n; i += 1) {
        const [outer, inner] = e.ring(i);
        // A ring pixel is one that CHANGED and is >= 3:1 against what it replaced
        // and against the pixel just outside the box (1.4.11), in both ring lines.
        const [ox, oy] = e.out(i);
        const ringPx = [outer, inner].map(([x, y]) => at(B, x, y));
        const contrasts = [outer, inner].flatMap(([x, y], k) => [contrast(ringPx[k], at(A, x, y)), contrast(ringPx[k], at(A, ox, oy))]);
        if (differs(outer[0], outer[1]) && differs(inner[0], inner[1]) && Math.min(...contrasts) >= 3) {
          hit += 1;
          minContrast = Math.min(minContrast, ...contrasts);
        }
      }
      coverage[name] = hit / e.n;
    }
    return { coverage, minContrast: Number.isFinite(minContrast) ? minContrast : 0 };
  }, { a: before, b: after, geo: { bx: origin.x - clip.x, by: origin.y - clip.y, bw: origin.width, bh: origin.height } });
}

for (const surface of SURFACES) {
  test.describe(`${surface} logs`, () => {
    test.use({ viewport: PHONE });

    // Whether a screen reader actually ANNOUNCES the text cannot be automated;
    // what is checked is the exposed role and live-region properties.
    test('the loading indicator is exposed as a polite status and its layout is unchanged', async ({ page }) => {
      const { release } = await gateLogs(page, [ENTRY]);
      try {
        const panel = await openLogs(page, surface);
        const status = panel.getByRole('status');
        await expect(status).toBeVisible();
        await expect(status).toHaveText('Loading logs…');

        const live = await statusLiveness(page);
        expect(live, 'the loading indicator is not exposed as a live status region').toHaveLength(1);
        expect(live[0].live, 'the loading indicator is not exposed as a polite live region').toBe('polite');

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
        // <output> takes phrasing content only: a <div> child is invalid HTML.
        await expect(panel.locator('output div, output p')).toHaveCount(0);
      } finally {
        release();
      }
    });

    test('x-show hides the loading indicator once entries arrive, and the entries are in the page', async ({ page }) => {
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
          overflowY: style.overflowY,
          scrollable: el.scrollHeight > el.clientHeight,
        };
      });
      expect(indicator.focusVisible, 'keyboard focus is not matched by :focus-visible').toBe(true);
      expect(indicator.overflowY).toBe('auto');
      expect(indicator.scrollable, 'the log container no longer scrolls its own overflow').toBe(true);

      await page.keyboard.press('PageDown');
      await expect.poll(() => region.evaluate((el) => el.scrollTop),
        { message: 'PageDown did not scroll the focused log region' }).toBeGreaterThan(0);
    });

    for (const theme of ['light', 'dark'] as const) {
      for (const width of [375, 1280]) {
        test(`keyboard focus on the log region paints a visible ring in the ${theme} theme at ${width}px`, async ({ page }) => {
          await page.setViewportSize({ width, height: 800 });
          // A few short entries, not a full scroller: with text sliced by the
          // region's edge under the ring, the pixels being compared would
          // depend on where the glyphs fall. The CSS is the same either way.
          const { release } = await gateLogs(page, MANY_ENTRIES.slice(0, 3));
          release();
          const panel = await openLogs(page, surface, theme);
          const region = panel.getByRole('region', { name: 'Application logs' });
          await expect(region.getByText('entry number 2')).toBeAttached();

          const ring = await measureFocusRing(page, panel, region);
          for (const edge of ['top', 'left', 'bottom'] as const) {
            expect(
              ring.coverage[edge],
              `the ${edge} edge of the focused log region does not show a 3:1 ring: an outline offset outside the box is clipped by the overflow-hidden parent`,
            ).toBeGreaterThanOrEqual(0.9);
          }
          expect(ring.minContrast, 'no ring pixel reached 3:1 against both adjacent colours (1.4.11)').toBeGreaterThanOrEqual(3);
        });
      }
    }

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
