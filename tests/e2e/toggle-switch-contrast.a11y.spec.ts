import { test, expect } from './fixtures';
import { expectVisualTransitionsToSettle } from './helpers';

/**
 * WCAG 2.2 AA 1.4.11 (non-text contrast) for the settings toggle switch.
 *
 * The toggle track and knob are pure-colour UI components (no text), so each
 * needs >= 3:1 against the surface it sits on, in EVERY state. Two Tailwind
 * arbitrary-value classes shared by all four toggle template instances
 * (`partials/settings/toggle.html`, and the hand-rolled copies in
 * `header.html`, `provider_card.html`, `field_types.html`) were never
 * measured:
 *
 *   - OFF track `bg-white/[0.08]` had no light-theme override at all, so it
 *     composited to white-on-white (1.0:1) on the light theme's #ffffff
 *     card -- an OFF toggle was literally invisible.
 *   - ON track `bg-cp-accent` (#35c5f4) is only 2.0:1 on a white light-theme
 *     surface, and the plain-white ON knob sitting on that same accent
 *     track is only 2.0:1 in EITHER theme -- the state indicator itself
 *     failed even where the track alone would have passed.
 *
 * `tests/unit/test_toggle_switch_contrast.py` checks the fix's literal
 * colour values against base.html's stylesheet directly (same approach as
 * `test_focus_ring_contrast.py`). This file drives the REAL rendered toggle
 * in a real browser, through a real click, so it catches what the unit test
 * cannot: whether the CSS selectors' specificity actually beats the
 * Tailwind CDN utilities at runtime, on the two real host templates
 * (header.html's "Show advanced settings" toggle, on the page background;
 * provider_card.html's enabler toggle, on a `bg-cp-card` surface) rather
 * than on a static string.
 */

/**
 * Measure a single `role="switch"` element: its own track colour against the
 * real opaque surface behind it, and its knob (the direct `<span>` child
 * every one of the four templates renders) against the track.
 *
 * The surface is found by walking real DOM ancestry from the toggle's own
 * PARENT (never the toggle itself, whose own background is exactly what is
 * being measured) up to the first ancestor with a non-transparent computed
 * `background-color`, composited if translucent -- the same hazard the
 * wizard focus-ring contrast test documents: header.html's toggle sits
 * directly on the page body, while provider_card.html's sits on a nested
 * `bg-cp-card` div, and hardcoding either selector for both would either
 * miss the card (measuring against the wrong, more forgiving surface) or
 * fail to find one at all for the header instance. Throws rather than
 * guessing if the walk reaches the top with nothing opaque, or if the knob
 * is missing.
 */
async function measureToggle(toggle: import('@playwright/test').Locator) {
  return toggle.evaluate((el: HTMLElement) => {
    const parseColor = (s: string) => {
      const m = s.match(/rgba?\(([^)]+)\)/);
      if (!m) return null;
      const parts = m[1].split(',').map((p) => parseFloat(p.trim()));
      return { r: parts[0], g: parts[1], b: parts[2], a: parts.length > 3 ? parts[3] : 1 };
    };
    const luminance = (c: { r: number; g: number; b: number }) => {
      const chan = (v: number) => {
        const s = v / 255;
        return s <= 0.04045 ? s / 12.92 : Math.pow((s + 0.055) / 1.055, 2.4);
      };
      return 0.2126 * chan(c.r) + 0.7152 * chan(c.g) + 0.0722 * chan(c.b);
    };
    const contrastOf = (fg: { r: number; g: number; b: number }, bg: { r: number; g: number; b: number }) => {
      const l1 = luminance(fg);
      const l2 = luminance(bg);
      return (Math.max(l1, l2) + 0.05) / (Math.min(l1, l2) + 0.05);
    };
    /**
     * Alpha-composite a possibly-translucent computed colour over an opaque
     * background, returning the colour actually visible on screen.
     *
     * Reading the raw channel values and ignoring alpha (an earlier version
     * of this helper did exactly that) treats `rgba(255, 255, 255, 0.08)` --
     * the OFF track's colour if its light-theme override is ever missing or
     * mis-scoped -- as solid opaque white. Against a dark surface that
     * reports a falsely huge ratio instead of the ~1.3:1 the pixel actually
     * shows, so a real regression there would pass silently.
     */
    const compositeOver = (
      colorStr: string,
      bg: { r: number; g: number; b: number },
    ): { r: number; g: number; b: number } | null => {
      const c = parseColor(colorStr);
      if (!c) return null;
      if (c.a >= 1) return { r: c.r, g: c.g, b: c.b };
      return {
        r: c.a * c.r + (1 - c.a) * bg.r,
        g: c.a * c.g + (1 - c.a) * bg.g,
        b: c.a * c.b + (1 - c.a) * bg.b,
      };
    };

    const knob = el.querySelector(':scope > span') as HTMLElement | null;
    if (!knob) {
      throw new Error('toggle has no direct <span> knob child -- markup changed under this test');
    }

    let node: HTMLElement | null = el.parentElement;
    const layers: { r: number; g: number; b: number; a: number }[] = [];
    let surfaceOwner = '';
    let foundOpaque = false;
    while (node) {
      const c = parseColor(getComputedStyle(node).backgroundColor);
      if (c && c.a > 0) {
        if (!surfaceOwner) {
          surfaceOwner = node.id ? `#${node.id}` : (node.className.toString().split(/\s+/)[0] || node.tagName);
        }
        layers.push(c);
        if (c.a >= 1) {
          foundOpaque = true;
          break;
        }
      }
      node = node.parentElement;
    }
    if (!foundOpaque) {
      throw new Error('no opaque backdrop found above this toggle; cannot compute its surface contrast');
    }
    let surfaceRgb: { r: number; g: number; b: number } | null = null;
    for (let i = layers.length - 1; i >= 0; i--) {
      const c = layers[i];
      surfaceRgb = surfaceRgb === null
        ? { r: c.r, g: c.g, b: c.b }
        : {
            r: c.a * c.r + (1 - c.a) * surfaceRgb.r,
            g: c.a * c.g + (1 - c.a) * surfaceRgb.g,
            b: c.a * c.b + (1 - c.a) * surfaceRgb.b,
          };
    }
    const surface = surfaceRgb!;
    const surfaceColor = `rgb(${surface.r}, ${surface.g}, ${surface.b})`;

    const trackColor = getComputedStyle(el).backgroundColor;
    const knobColor = getComputedStyle(knob).backgroundColor;

    // Composited BEFORE both ratios: the track over the real surface, then
    // the knob over that composited (not raw) track -- so a translucent
    // track never gets read as if it were opaque at either step.
    const effectiveTrack = compositeOver(trackColor, surface);
    const effectiveKnob = effectiveTrack ? compositeOver(knobColor, effectiveTrack) : null;

    return {
      ariaChecked: el.getAttribute('aria-checked'),
      surfaceOwner,
      trackColor,
      knobColor,
      surfaceColor,
      trackVsSurface: effectiveTrack ? contrastOf(effectiveTrack, surface) : null,
      knobVsTrack: effectiveTrack && effectiveKnob ? contrastOf(effectiveKnob, effectiveTrack) : null,
    };
  });
}

const MIN_RATIO = 3.0;

function assertMeasurement(
  label: string,
  m: { ariaChecked: string | null; surfaceOwner: string; trackColor: string; knobColor: string; surfaceColor: string; trackVsSurface: number | null; knobVsTrack: number | null },
) {
  expect(m.trackVsSurface, `${label}: track ${m.trackColor} vs surface ${m.surfaceColor} was not computable`).not.toBeNull();
  expect(m.knobVsTrack, `${label}: knob ${m.knobColor} vs track ${m.trackColor} was not computable`).not.toBeNull();

  expect(
    m.trackVsSurface as number,
    `${label} (aria-checked=${m.ariaChecked}): track ${m.trackColor} on surface ` +
    `${m.surfaceColor} measures ${(m.trackVsSurface as number).toFixed(2)}:1, ` +
    `below the WCAG 1.4.11 floor of ${MIN_RATIO}:1`,
  ).toBeGreaterThanOrEqual(MIN_RATIO);

  expect(
    m.knobVsTrack as number,
    `${label} (aria-checked=${m.ariaChecked}): knob ${m.knobColor} on track ` +
    `${m.trackColor} measures ${(m.knobVsTrack as number).toFixed(2)}:1, below ` +
    `the WCAG 1.4.11 floor of ${MIN_RATIO}:1`,
  ).toBeGreaterThanOrEqual(MIN_RATIO);
}

for (const theme of ['dark', 'light'] as const) {
  test(`the "Show advanced settings" toggle (header.html) meets 1.4.11 in the ${theme} theme, ON and OFF`, async ({ page }) => {
    await page.addInitScript((t) => localStorage.setItem('cp-theme', t), theme);
    await page.goto('/settings/');
    await expect(page.getByRole('tablist', { name: 'Settings categories' })).toBeVisible();

    // Pin the theme really took effect -- same guard the toast/focus-ring
    // contrast tests use, so a broken theme pipeline reds loudly here
    // instead of silently scanning the wrong theme under the right name.
    await expect
      .poll(() => page.evaluate(() => document.documentElement.classList.contains('light')))
      .toBe(theme === 'light');

    const toggle = page.getByRole('switch', { name: 'Show advanced settings' });
    await expect(toggle).toBeVisible();

    const before = await measureToggle(toggle);
    expect(before.ariaChecked, 'test assumes "Show advanced" starts OFF').toBe('false');
    assertMeasurement(`${theme} theme, header toggle, OFF`, before);

    await toggle.click();
    await expect(toggle).toHaveAttribute('aria-checked', 'true');
    // The track carries `transition-colors` (150ms). Measuring immediately
    // reads a mid-transition frame -- reviewers caught this producing
    // rgb(68..111, 114..128, 126..143), neither the OFF nor the ON colour --
    // which let a broken ON-state rule pass by accident against whatever
    // that transient shade happened to contrast with.
    await expectVisualTransitionsToSettle(page, `${theme} theme, header toggle, post-click`);
    const after = await measureToggle(toggle);
    assertMeasurement(`${theme} theme, header toggle, ON`, after);
  });

  test(`a provider enabler toggle (provider_card.html) meets 1.4.11 in the ${theme} theme, ON and OFF`, async ({ page }) => {
    await page.addInitScript((t) => localStorage.setItem('cp-theme', t), theme);
    await page.goto('/settings/');
    await expect(page.getByRole('tablist', { name: 'Settings categories' })).toBeVisible();
    await expect
      .poll(() => page.evaluate(() => document.documentElement.classList.contains('light')))
      .toBe(theme === 'light');

    const searcherTab = page.getByRole('tab', { name: /searcher/i });
    await expect(searcherTab).toBeVisible();
    await searcherTab.click();
    await expect(searcherTab).toHaveAttribute('aria-selected', 'true');

    // Not every settings group has an enabler toggle (some are plain option
    // lists, or the "combined" basics card) -- pick a card that actually
    // contains a role="switch" rather than assuming the first card does.
    const card = page.locator('[data-settings-group] .bg-cp-card').filter({
      has: page.getByRole('switch'),
    }).first();
    await expect(card).toBeVisible();
    const toggle = card.getByRole('switch').first();
    await expect(toggle).toBeVisible();

    const firstState = await toggle.getAttribute('aria-checked');

    const before = await measureToggle(toggle);
    expect(before.surfaceOwner, 'expected the provider card toggle to sit on a bg-cp-card surface')
      .toContain('bg-cp-card');
    assertMeasurement(`${theme} theme, provider card toggle, ${firstState === 'true' ? 'ON' : 'OFF'} (initial)`, before);

    await toggle.click();
    await expect(toggle).toHaveAttribute('aria-checked', firstState === 'true' ? 'false' : 'true');
    // See the header toggle test above: without this, the track is read
    // mid `transition-colors` rather than at its settled colour.
    await expectVisualTransitionsToSettle(page, `${theme} theme, provider card toggle, post-click`);
    const after = await measureToggle(toggle);
    assertMeasurement(`${theme} theme, provider card toggle, ${firstState === 'true' ? 'OFF' : 'ON'} (after click)`, after);
  });
}
