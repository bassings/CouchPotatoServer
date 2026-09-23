import type { Locator, Page } from '@playwright/test';
import { test, expect } from './fixtures';
import { expectVisualTransitionsToSettle, mockSettingsSave } from './helpers';

/**
 * WCAG 2.2 AA 1.4.11 (non-text contrast) for the settings toggle switch.
 *
 * REFRAME (round 2 review): a static, regex-based unit test cannot honestly
 * model CSS scope or the cascade -- two review rounds found a new instance
 * of exactly that class of gap (an unanchored match that "found" a rule
 * regardless of what scoped it away; a "fixed" anchored version that still
 * could not tell a rule that EXISTS from one that WINS, or notice a real
 * tinted surface it never rendered). This file is now the source of truth:
 * it renders the real host templates, in a real browser, in both themes,
 * and reads real computed styles off real elements after real transitions
 * settle. `tests/unit/test_toggle_switch_contrast.py` only proves what
 * static analysis honestly can (the pinned rule exists once, unnested, with
 * its pinned colour, and nothing else in the stylesheet also targets the
 * switch role) plus pure arithmetic on those pinned colours against the
 * theme's CSS custom properties -- it does not, and no longer tries to,
 * restate a ratio this file measures on a live page.
 *
 * All four toggle template instances are covered by finding real pages that
 * render them:
 *   - partials/settings/header.html   -- /settings/, the "Show advanced
 *     settings" switch (page-background surface).
 *   - partials/settings/provider_card.html -- /settings/, Searchers tab,
 *     the Newznab provider card's enabler switch (bg-cp-card surface).
 *   - partials/settings/field_types.html   -- the SAME Newznab card, after
 *     "+ Add" creates a combined host/key row: its "use" toggle is the
 *     `opt.type === 'combined'` markup this file cannot otherwise reach any
 *     other way (the wizard's own indexer rows use the canonical
 *     toggle.html partial instead, not this one).
 *   - partials/settings/toggle.html (canonical) -- /wizard/, the Providers
 *     and Download Clients steps, both rendering it on the wizard's
 *     tinted (`bg-white/[0.0x]`) row panels rather than a flat card colour.
 *
 * Rather than hand-picking one toggle per page, `sweepToggles` measures
 * EVERY visible `[role="switch"]` in a given scope, in whatever state it is
 * already in, then clicks it and measures the flipped state too -- so each
 * sweep gets one OFF and one ON reading per control, and a control that
 * defaults to ON is not silently skipped the way a fixed "assume it starts
 * OFF" precondition would. It restores each toggle immediately after
 * measuring both states, before moving to the next one, so an enabler
 * toggle that shows/hides sibling controls does not shift what a later
 * index in the same sweep resolves to.
 *
 * Settings toggles autosave 500ms after a change (scripts.html's
 * `debounceSave`). `mockSettingsSave` (tests/e2e/helpers.ts) intercepts
 * that request wherever this file clicks one, so no state written by one
 * test's toggle click can leak into a later spec sharing this worker's data
 * dir (Reviewer A, round 2: the initial state of a provider's enabler was
 * observed flipping between runs before this was added).
 */

/**
 * `mockSettingsSave`'s fixed `{success:true}` response has no `value` field.
 * scripts.html's `saveSingle()` deliberately never falls back to the value
 * it submitted when the response omits one (a password field's response
 * omits `value` on purpose, to avoid ever writing the plaintext just typed
 * back into local state) -- so with the plain mock, the moment the 500ms
 * debounce fires and `dirty` is cleared, `isEnabled()` reads back
 * whatever `this.values` held from the ORIGINAL page load, silently
 * reverting a toggle this file just clicked mid-sweep. Measured: the
 * Newznab enabler, forced ON to establish this test's own precondition,
 * read back OFF a few hundred ms later, mid-measurement, with no click of
 * ours in between. Echoing the submitted value back keeps `this.values` in
 * sync with what we actually set, the way a real save response would.
 */
async function mockSettingsSaveEchoingValue(page: Page): Promise<void> {
  await mockSettingsSave(page);
  await page.route('**/settings.save/**', async (route) => {
    const params = new URLSearchParams(route.request().postData() ?? '');
    await route.fulfill({
      status: 200,
      contentType: 'application/json',
      body: JSON.stringify({ success: true, value: params.get('value') }),
    });
  });
}

/**
 * Measure a single `role="switch"` element: its own track colour against
 * the real opaque surface behind it (found by walking real DOM ancestry
 * from the toggle's own PARENT, compositing translucent layers), and its
 * knob (the direct `<span>` child every one of the four templates renders)
 * against that same composited track. Alpha is composited before BOTH
 * ratios -- reading raw channel values and ignoring alpha would treat a
 * translucent OFF track as opaque and report a falsely huge ratio instead
 * of the real, dimmer one a tinted or dark surface produces.
 */
async function measureToggle(toggle: Locator) {
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

type Measurement = {
  ariaChecked: string | null;
  surfaceOwner: string;
  trackColor: string;
  knobColor: string;
  surfaceColor: string;
  trackVsSurface: number | null;
  knobVsTrack: number | null;
};

function assertMeasurement(label: string, m: Measurement) {
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

/**
 * Measure and assert every element `switches` currently resolves to, one at
 * a time: the CURRENT state, then click + settle + the FLIPPED state, then
 * click again to restore the original state before moving on.
 *
 * `switches` is re-evaluated (via `.nth(i)`) on every access, so a click
 * that changes what else is in the DOM is reflected on the NEXT iteration
 * -- but restoring before advancing keeps that from actually mattering here.
 *
 * Asserts `aria-checked` is exactly the string "true" or "false" on every
 * read, catching a toggle instance whose `:aria-checked` binding renders
 * something else (e.g. a raw stored value like "1"/"0" instead of a
 * boolean's `.toString()`), which would otherwise measure real colours
 * against a control that is not actually wired to the switch pattern axe
 * and screen readers expect.
 */
async function sweepToggles(page: Page, switches: Locator, contextLabel: string): Promise<void> {
  const count = await switches.count();
  expect(count, `${contextLabel}: no toggle(s) found to sweep`).toBeGreaterThan(0);

  for (let i = 0; i < count; i++) {
    const toggle = switches.nth(i);
    if (!(await toggle.isVisible())) continue;
    const label = `${contextLabel} #${i}`;

    const ariaBefore = await toggle.getAttribute('aria-checked');
    expect(
      ariaBefore,
      `${label}: aria-checked must be exactly "true" or "false", got ${JSON.stringify(ariaBefore)}`,
    ).toMatch(/^(true|false)$/);
    assertMeasurement(`${label} (${ariaBefore})`, await measureToggle(toggle));

    await toggle.click();
    await expectVisualTransitionsToSettle(page, `${label} post-click`);

    const ariaAfter = await toggle.getAttribute('aria-checked');
    expect(
      ariaAfter,
      `${label} after click: aria-checked must be exactly "true" or "false", got ${JSON.stringify(ariaAfter)}`,
    ).toMatch(/^(true|false)$/);
    expect(ariaAfter, `${label}: click did not flip aria-checked`).not.toBe(ariaBefore);
    assertMeasurement(`${label} (${ariaAfter})`, await measureToggle(toggle));

    // Restore immediately: keeps sibling visibility/indices stable for the
    // rest of THIS sweep, and (with mockSettingsSave already intercepting
    // the network write) leaves nothing for a later spec to inherit.
    await toggle.click();
    await expectVisualTransitionsToSettle(page, `${label} post-restore`);
  }
}

for (const theme of ['dark', 'light'] as const) {
  test(`settings page toggles meet 1.4.11 in the ${theme} theme (header.html, provider_card.html, field_types.html)`, async ({ page }) => {
    test.setTimeout(90_000);
    await mockSettingsSaveEchoingValue(page);
    await page.addInitScript((t) => localStorage.setItem('cp-theme', t), theme);
    await page.goto('/settings/');
    await expect(page.getByRole('tablist', { name: 'Settings categories' })).toBeVisible();
    await expect
      .poll(() => page.evaluate(() => document.documentElement.classList.contains('light')))
      .toBe(theme === 'light');

    // header.html: present on every non-custom-panel tab, on the page
    // background (no bg-cp-card ancestor).
    const headerToggle = page.getByRole('switch', { name: 'Show advanced settings' });
    await expect(headerToggle).toBeVisible();
    await sweepToggles(page, headerToggle, `${theme} theme, header.html "Show advanced settings"`);

    // provider_card.html + field_types.html: the Newznab card on Searchers.
    //
    // Newznab's SEEDED default is enabled, but that default is not this
    // test's to assume: accessibility.a11y.spec.ts's wizard flow clicks
    // "Enable Newznab Indexers" (an ON -> OFF toggle, since it starts
    // enabled) and that save really persists to this worker's DB via
    // mockSettingsSave-free code elsewhere -- so whichever spec in this
    // project happened to run first decides what state this test's own
    // Newznab card starts in. Measured: with that spec running first,
    // Newznab is OFF here, its card is collapsed, and "+ Add" is hidden --
    // a real, deterministic run-order dependency, not a timing flake.
    // Establish the precondition explicitly instead of assuming it.
    await page.getByRole('tab', { name: 'Searchers' }).click();
    await expectVisualTransitionsToSettle(page, `${theme} theme, Searchers tab opened`);
    const newznabCard = page.locator('.bg-cp-card', { has: page.getByRole('heading', { name: 'Newznab', exact: true }) });
    await expect(newznabCard, 'the Newznab provider card never rendered on the Searchers tab').toBeVisible();

    // provider_card.html's enabler labels itself `'Enable ' + (group.label
    // || group.name)`, which for this provider is the group's own label,
    // "Newznab" -- NOT "Enable Newznab Indexers", the wizard's own toggle.html
    // instance's static label used at accessibility.a11y.spec.ts:820.
    // Different template, different label; scoping to `newznabCard` alone
    // is not enough to make the wizard's string match here too.
    const newznabEnabler = newznabCard.getByRole('switch', { name: 'Enable Newznab' });
    await expect(newznabEnabler).toBeVisible();
    if ((await newznabEnabler.getAttribute('aria-checked')) !== 'true') {
      await newznabEnabler.click();
      await expectVisualTransitionsToSettle(page, `${theme} theme, Newznab enabler forced ON`);
      await expect(newznabEnabler).toHaveAttribute('aria-checked', 'true');
    }

    // Create a combined host/key row so its field_types.html "use" toggle
    // exists to be swept below -- it does not exist until "+ Add" is
    // clicked, and the card must be open (enabler ON, settled) first.
    const addRowBtn = newznabCard.getByRole('button', { name: 'Add row' });
    await expect(addRowBtn, 'the "+ Add" row button never rendered under Newznab').toBeVisible();
    await addRowBtn.click();

    // Sweeps the card's OWN enabler (provider_card.html) and the new row's
    // "use" toggle (field_types.html) together. The enabler is swept FIRST
    // (DOM order): toggling it off/on-and-restore happens before the loop
    // reaches the row toggle's index, so the row is never hidden when its
    // turn comes.
    await sweepToggles(
      page,
      newznabCard.locator('[role="switch"]:visible'),
      `${theme} theme, Newznab card (provider_card.html enabler + field_types.html row)`,
    );
  });
}

for (const theme of ['dark', 'light'] as const) {
  test(`wizard toggles meet 1.4.11 in the ${theme} theme (canonical toggle.html, on tinted row panels)`, async ({ page }) => {
    test.setTimeout(90_000);
    await page.addInitScript((t) => localStorage.setItem('cp-theme', t), theme);
    await page.goto('/wizard/');
    await page.waitForLoadState('networkidle');
    await expect(page.getByRole('heading', { name: 'Welcome to CouchPotato' })).toBeVisible();
    await expect
      .poll(() => page.evaluate(() => document.documentElement.classList.contains('light')))
      .toBe(theme === 'light');

    // Welcome -> Server Security -> (Skip) -> Providers. "Both" renders the
    // usenet and torrent toggle.html instances together, each sitting on
    // this step's `bg-white/[0.0x]` tinted row panel (wizard.html), not a
    // flat --cp-card colour.
    //
    // Steps are `x-show="currentStep === N"` with `x-transition`: the step
    // being LEFT stays present (fading out) for a moment after the next
    // step's heading is already visible, so a bare page-wide
    // `[role="switch"]:visible` locator can still resolve to the PREVIOUS
    // step's toggle -- measured hanging the whole test, retrying a click on
    // a control from a step already left behind. Scoping to each step's own
    // `x-show` container (the attribute Alpine reads, still a plain HTML
    // attribute on the rendered element) makes that impossible regardless
    // of transition timing.
    const providersStep = page.locator('[x-show="currentStep === 2"]');
    const downloaderStep = page.locator('[x-show="currentStep === 3"]');

    await page.getByRole('button', { name: 'Continue' }).click();
    await expect(page.getByRole('heading', { name: 'Server Security' })).toBeVisible();
    await page.getByRole('button', { name: 'Skip' }).click();
    await expect(page.getByRole('heading', { name: 'Where to Search' })).toBeVisible();
    await page.getByRole('button', { name: /^Both/ }).click();
    await expect(providersStep.locator('button[role="switch"]:visible').first()).toBeVisible();

    await sweepToggles(
      page,
      providersStep.locator('button[role="switch"]:visible'),
      `${theme} theme, wizard Providers step (toggle.html)`,
    );

    // Providers -> Downloader. Black Hole's own enabler is another
    // toggle.html instance, on the same kind of tinted panel.
    await page.getByRole('button', { name: 'Continue' }).click();
    await expect(page.getByRole('heading', { name: 'Download Clients' })).toBeVisible();

    await sweepToggles(
      page,
      downloaderStep.locator('button[role="switch"]:visible'),
      `${theme} theme, wizard Download Clients step (toggle.html)`,
    );
  });
}
