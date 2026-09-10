import { test, expect } from './fixtures';
import { layoutPx, TARGET_SIZE_MIN, TARGET_SIZE_MIN_LARGE } from './helpers';
import { type Page } from '@playwright/test';
import AxeBuilder from '@axe-core/playwright';

/**
 * FEAT-011 (specs/FEAT-011-replace-with-this-file.md) -- accessibility
 * criteria for the "Replace with this file" operator modal
 * (movie_detail.html, operatorReplaceModal()), primarily AC-A11Y-1/2/3
 * (keyboard operability and the focus trap), AC-A11Y-5 (announcer, focus
 * return), AC-A11Y-7/8 (accessible names, dialog semantics, radiogroup),
 * AC-A11Y-9 (no colour-only signalling), AC-A11Y-10 (a full axe scan with
 * the modal OPEN, both themes) and AC-A11Y-11/14 (contrast and target size
 * measured from the rendered page).
 *
 * The trigger and dialog shell were built by 2a405d67/4051c2c1, and eight
 * data-flow tests already cover fetch/submit wiring
 * (tests/e2e/operator-replace-modal.spec.ts) -- none of that is repeated
 * here. This file is the accessibility pass that CLAUDE.md/AGENTS.md say is
 * still outstanding: nothing about the modal has been checked with the
 * modal actually open, in both themes, or against a screen reader's model
 * of the page.
 *
 * Runs in the `accessibility` project (playwright.config.ts), which pins
 * `colorScheme: 'light'` and Desktop Chrome's default 1280x720 viewport --
 * dark-theme cases seed `cp-theme` into localStorage BEFORE navigation and
 * assert the theme actually took effect, same pattern as
 * review-queue.a11y.spec.ts and accessibility.a11y.spec.ts.
 *
 * TDD RED phase: no production template or script has been touched by this
 * task. Some assertions below may already hold against the current markup
 * (the dialog shell already carries role="dialog"/aria-modal/a labelled
 * heading, and the radiogroup already carries an aria-label) -- those are
 * kept anyway because they are exactly the properties a later change could
 * regress silently, and this file is what would catch it. The genuinely new
 * failures this task's own briefing predicts, and this file is built to
 * surface, are: the confirm control's danger-token contrast against the
 * dialog's cp-card surface (the same shape already fixed once for the
 * review-queue card control, at base.html's own
 * `[data-testid="review-mark-failed"]` comment); the confirm control's
 * target size (px-4/py-2/text-xs does not obviously clear 44x44); the
 * candidate radios having no arrow-key handling at all (grep across
 * movie_detail.html finds no "Arrow" keydown anywhere near the radiogroup);
 * and the page behind the modal having no aria-hidden/inert applied, so a
 * screen reader's browse-mode cursor can still reach it while the dialog is
 * open.
 *
 * Two things measured while building this file, kept here so the next
 * person does not have to re-derive them:
 *
 * - `openReplaceModal` waits for the dialog's `x-transition` (200ms) to
 *   settle before returning. Scanning or reading colours mid-fade is a
 *   false reading, not a real one -- axe genuinely reports a Cancel-button
 *   contrast violation and a "Mark failed" (pre-existing, unrelated)
 *   violation at ~0.18 opacity that both vanish once the transition
 *   finishes; the ONE violation that survives settling in the dark theme
 *   is the confirm control's own contrast, which is the real defect.
 * - The confirm control's contrast test also selects a candidate before
 *   scanning: `disabled:opacity-50` means axe (correctly) skips contrast
 *   checks on the disabled control, so scanning only the never-used
 *   initial state would let the enabled control's real contrast bug pass
 *   green.
 * - The full-page axe scan in the dark theme also reports a genuinely
 *   real, but PRE-EXISTING and unrelated, violation: the release table's
 *   own "Mark failed" button (`partials/movie_releases.html`), independent
 *   of whether this modal exists at all. It is included in movie_detail's
 *   render, so a whole-page scan (as AC-A11Y-10 asks for) sees it; fixing
 *   it is outside this modal's own scope but is the same class of bug
 *   base.html already documents fixing once for
 *   `[data-testid="review-mark-failed"]`.
 * - AC-A11Y-12's focus-ring test opens the dialog via `openReplaceModalByKeyboard`
 *   (focus + Enter), never a mouse click, and reaches the confirm/cancel
 *   controls with real Tab presses rather than `.click()` on a candidate
 *   first. Chromium's `:focus-visible` heuristic tracks the last REAL
 *   input modality: a mouse click earlier in the test (even on an
 *   unrelated candidate) makes a LATER script-driven `.focus()` on
 *   confirm/cancel read as `:focus-visible: false` -- reproduced with the
 *   app's OWN `open()` auto-focus on Close, not just this file's probe --
 *   while the identical sequence started from a keyboard interaction reads
 *   `true`. That is real browser behaviour (base.html's own
 *   `:focus:not(:focus-visible) { outline: none }` rule depends on it,
 *   deliberately, for mouse users elsewhere in the app), not a defect, so
 *   the test drives the keyboard-only path WCAG 2.4.7/1.4.11 actually
 *   protect.
 */

const REVIEW_MOVIE_ID = 'e2e-seed-movie-007';
const REVIEW_DESTRUCTIVE_MOVIE_ID = 'e2e-seed-movie-008';

const CANDIDATE_ROUTE = /renamer\.operator_candidates/;
const REPLACE_ROUTE = /renamer\.operator_replace/;

const CANDIDATES = [
  'Minions.and.Monsters.2024.2160p.UHD.HDR10Plus-GRP9.mkv',
  'Some.Other.Placed.File.2024.mkv',
];

function candidatesResponse(candidates: string[]) {
  return {
    status: 200,
    contentType: 'application/json',
    body: JSON.stringify({ success: true, candidates }),
  };
}

/** Same navigation idiom as operator-replace-modal.spec.ts's gotoReviewMovie
 *  (duplicated rather than imported -- spec files do not import each
 *  other in this suite; fixtures.ts's own comment explains why). */
async function gotoReviewMovie(page: Page, movieId: string) {
  await page.goto(`/movie/${movieId}`);
  const loaded = await page.locator('#movie-releases')
    .waitFor({ state: 'attached', timeout: 15000 })
    .then(() => true)
    .catch(() => false);
  expect(
    loaded,
    `No seeded movie at /movie/${movieId}. Run ` +
    '`.venv/bin/python scripts/seed_e2e_data.py --data_dir=.e2e-data` before ' +
    'starting the server.',
  ).toBe(true);

  // T8a: the operator-replace trigger/modal render only when
  // `operator_replace_enabled` is on (default OFF in production, per
  // specs/FEAT-011-replace-with-this-file.md's "Shipped disabled" note).
  // This file's own tests intercept the candidate/replace fetches
  // themselves, so flipping the template's gate through the real
  // settings.save API and reloading is enough -- no server restart needed,
  // since couchpotato.ui._ctx() reads the setting fresh on every request.
  await page.evaluate(async () => {
    await fetch(window.CP.apiBase + '/settings.save/?section=renamer&name=operator_replace_enabled&value=true');
  });
  await page.reload();
  await page.locator('#movie-releases').waitFor({ state: 'attached', timeout: 15000 });
}

/**
 * Stub the candidate listing and open the modal, returning it scoped so
 * every assertion below reads from THIS dialog. Every route this file uses
 * is intercepted, never the real backend -- renamer.operator_replace would
 * otherwise attempt a real destructive file swap against the seeded
 * fixture, exactly the reasoning operator-replace-modal.spec.ts's own
 * header comment already gives for both seeded movies.
 */
async function openReplaceModal(page: Page, movieId: string, candidates: string[] = CANDIDATES) {
  await page.route(CANDIDATE_ROUTE, (route) => route.fulfill(candidatesResponse(candidates)));

  await gotoReviewMovie(page, movieId);

  const trigger = page.locator('[data-testid="operator-replace-trigger"]');
  await expect(
    trigger,
    'operator-replace trigger did not render -- did scripts/seed_e2e_data.py ' +
    'seed a files.movie entry for this release?',
  ).toBeVisible({ timeout: 10000 });
  await trigger.click();

  const modal = page.locator('[data-testid="operator-replace-modal"]');
  await expect(modal).toBeVisible({ timeout: 5000 });
  // Wait for the candidate list itself, not just the shell, so every test
  // below sees the populated state rather than racing the fetch.
  await expect(modal.getByRole('radio', { name: candidates[0], exact: true })).toBeVisible({ timeout: 5000 });
  // Wait for the enter transition (x-transition, 200ms) to actually settle.
  // Measured directly: reading colour/contrast or running axe mid-fade
  // catches the dialog at opacity ~0.18, which axe's real pixel-sampling
  // reports as extra "violations" that vanish once the transition finishes
  // -- an artifact of when the scan runs, not a property of the settled
  // page. Every test in this file must see the same, real, settled state.
  await expect.poll(() => modal.evaluate((el) => getComputedStyle(el).opacity)).toBe('1');
  return modal;
}

/**
 * Same as openReplaceModal, but opens the dialog by focusing the trigger and
 * pressing Enter -- never a mouse click -- so the whole flow stays in
 * "keyboard" input modality throughout.
 *
 * This matters specifically for :focus-visible: Chromium's heuristic tracks
 * the last REAL input modality (mouse vs keyboard) and applies it even to a
 * focus() call the app makes programmatically afterwards. Measured directly
 * (scratch diagnostic, not committed): clicking the trigger with the mouse
 * and then letting the app's own open() auto-focus the Close button gives
 * `el.matches(':focus-visible') === false` on Close -- even though nothing
 * about Close's own markup or CSS changed -- while the identical auto-focus
 * after a keyboard-driven open (focus() + Enter) gives `true`. A test that
 * opens by mouse and then checks a focus ring measures a different, less
 * common user path than the one WCAG 2.4.7/1.4.11 exist for (a keyboard-only
 * user), and would report a false failure on a control that is, for the user
 * these criteria protect, actually fine.
 */
async function openReplaceModalByKeyboard(page: Page, movieId: string, candidates: string[] = CANDIDATES) {
  await page.route(CANDIDATE_ROUTE, (route) => route.fulfill(candidatesResponse(candidates)));

  await gotoReviewMovie(page, movieId);

  const trigger = page.locator('[data-testid="operator-replace-trigger"]');
  await expect(
    trigger,
    'operator-replace trigger did not render -- did scripts/seed_e2e_data.py ' +
    'seed a files.movie entry for this release?',
  ).toBeVisible({ timeout: 10000 });
  await trigger.focus();
  await page.keyboard.press('Enter');

  const modal = page.locator('[data-testid="operator-replace-modal"]');
  await expect(modal).toBeVisible({ timeout: 5000 });
  await expect(modal.getByRole('radio', { name: candidates[0], exact: true })).toBeVisible({ timeout: 5000 });
  await expect.poll(() => modal.evaluate((el) => getComputedStyle(el).opacity)).toBe('1');
  return modal;
}

async function setDarkTheme(page: Page) {
  await page.addInitScript(() => localStorage.setItem('cp-theme', 'dark'));
}

async function assertThemeIs(page: Page, light: boolean) {
  await expect
    .poll(() => page.evaluate(() => document.documentElement.classList.contains('light')))
    .toBe(light);
}

/** Same single definition review-queue.a11y.spec.ts and
 *  accessibility.a11y.spec.ts already use (duplicated per this suite's
 *  no-cross-import convention). */
const FOCUS_RING_PROBE = (el: Element) => {
  const read = () => {
    const s = window.getComputedStyle(el);
    return {
      outlineStyle: s.outlineStyle,
      outlineWidth: s.outlineWidth,
      outlineColor: s.outlineColor,
      boxShadow: s.boxShadow,
    };
  };
  const invisible = (colour: string) =>
    !colour || colour === 'transparent' ||
    /rgba\(\s*[\d.]+\s*,\s*[\d.]+\s*,\s*[\d.]+\s*,\s*0\s*\)/.test(colour);
  const shadowHasSubstance = (shadow: string) =>
    shadow !== 'none' && shadow !== '' &&
    shadow.split(/,(?![^(]*\))/).some((layer) => {
      const colour = (layer.trim().match(/^(rgba?\([^)]*\)|#[0-9a-f]+|[a-z]+)/i) || [''])[0];
      const lengths = (layer.match(/-?[\d.]+px/g) || []).map(parseFloat);
      return !invisible(colour) && lengths.some((n) => n !== 0);
    });
  const hadFocus = document.activeElement === el;
  (el as HTMLElement).blur();
  const blurred = read();
  (el as HTMLElement).focus();
  const focused = read();
  if (!hadFocus) (el as HTMLElement).blur();
  const outlineVisible =
    focused.outlineStyle !== 'none' && parseFloat(focused.outlineWidth || '0') > 0 && !invisible(focused.outlineColor);
  const shadowVisible = shadowHasSubstance(focused.boxShadow) && focused.boxShadow !== blurred.boxShadow;
  const changedOnFocus =
    focused.outlineStyle !== blurred.outlineStyle ||
    focused.outlineWidth !== blurred.outlineWidth ||
    focused.outlineColor !== blurred.outlineColor ||
    focused.boxShadow !== blurred.boxShadow;
  return { ...focused, changedOnFocus, visible: (outlineVisible || shadowVisible) && changedOnFocus };
};

/** Same alpha-compositing contrast measurement as review-queue.a11y.spec.ts
 *  (duplicated for the same reason as FOCUS_RING_PROBE above). Composites
 *  the parsed rgba() foreground over a given opaque backdrop colour first,
 *  since the danger-token classes this modal reuses (bg-cp-danger/10 etc.)
 *  are translucent, not opaque. */
function contrastAgainstBackdrop(fgRgba: string, textRgba: string, backdrop: [number, number, number]): number {
  const parse = (s: string) => {
    const m = s.match(/rgba?\(([\d.]+),\s*([\d.]+),\s*([\d.]+)(?:,\s*([\d.]+))?\)/);
    if (!m) throw new Error(`unparseable colour: ${s}`);
    return { r: +m[1], g: +m[2], b: +m[3], a: m[4] !== undefined ? +m[4] : 1 };
  };
  const composite = (fg: { r: number; g: number; b: number; a: number }, bg: [number, number, number]) => ({
    r: fg.r * fg.a + bg[0] * (1 - fg.a),
    g: fg.g * fg.a + bg[1] * (1 - fg.a),
    b: fg.b * fg.a + bg[2] * (1 - fg.a),
  });
  const luminance = (c: { r: number; g: number; b: number }) => {
    const [R, G, B] = [c.r, c.g, c.b].map((v) => {
      const s = v / 255;
      return s <= 0.04045 ? s / 12.92 : Math.pow((s + 0.055) / 1.055, 2.4);
    });
    return 0.2126 * R + 0.7152 * G + 0.0722 * B;
  };
  const bgEffective = composite(parse(fgRgba), backdrop);
  const textEffective = composite(parse(textRgba), [bgEffective.r, bgEffective.g, bgEffective.b]);
  const l1 = luminance(bgEffective);
  const l2 = luminance(textEffective);
  return (Math.max(l1, l2) + 0.05) / (Math.min(l1, l2) + 0.05);
}

test.describe('FEAT-011 Operator replace modal accessibility', () => {
  // -------------------------------------------------------------------
  // Point 1 / AC-A11Y-10: a full axe scan with the modal OPEN, both
  // themes. A closed-modal scan (already run elsewhere in this suite)
  // proves nothing about this dialog's content.
  // -------------------------------------------------------------------
  // AC-A11Y-10, HOVER. `QA/branch-review-2026-08-31-review-queue.md` (M1)
  // recorded this control at 4.21:1 on hover in the dark theme and
  // prescribed measuring after `.hover()` here. That was never done, so the
  // number went unmeasured while the resting state was checked every run.
  //
  // hover:bg-cp-danger/15 darkens the composited background, and the earlier
  // fix set a `background-color` that lost a specificity tie to that utility
  // (the vendored Tailwind CDN appends after the inline <style>), so what it
  // corrected at rest was undone on hover. The current fix moves the
  // FOREGROUND, which no `hover:bg-*` utility can reach.
  //
  // Measured: 5.12:1 hovered, against 4.08:1 with the previous colour.
  test('the confirm control clears the contrast floor ON HOVER, not just at rest (dark theme, AC-A11Y-10)', async ({ page }) => {
    await setDarkTheme(page);
    const modal = await openReplaceModal(page, REVIEW_MOVIE_ID);
    await expect(modal).toBeVisible();

    const confirmBtn = modal.locator('[data-testid="operator-replace-confirm"]');
    await expect(confirmBtn).toBeVisible();
    await confirmBtn.hover();
    // Settle the transition first: reading at the instant of the hover
    // samples the resting colours and proves nothing.
    await page.waitForTimeout(400);

    const results = await new AxeBuilder({ page }).withRules(['color-contrast']).analyze();
    const detail = results.violations
      .flatMap((v) => v.nodes.map((n) => `${v.id}: ${n.html} -- ${n.failureSummary}`))
      .join('\n');
    expect(
      results.violations.length,
      `WCAG contrast violations while the confirm control is HOVERED (dark theme):\n${detail}`,
    ).toBe(0);
  });

  for (const theme of ['light', 'dark'] as const) {
    test(`modal has zero WCAG 2.2 AA violations while open (${theme} theme, point 1 / AC-A11Y-10)`, async ({ page }) => {
      if (theme === 'dark') await setDarkTheme(page);
      const modal = await openReplaceModal(page, REVIEW_MOVIE_ID);
      await assertThemeIs(page, theme === 'light');
      await expect(modal).toBeVisible();

      // A candidate must be SELECTED before scanning: the confirm control
      // carries disabled:opacity-50 until then, and axe does not evaluate
      // colour-contrast on a disabled control -- scanning only the
      // never-used initial state would let a real contrast bug in the
      // control's actual, in-use appearance pass silently green.
      await modal.getByRole('radio', { name: CANDIDATES[0], exact: true }).click();

      const results = await new AxeBuilder({ page })
        .withTags(['wcag2a', 'wcag2aa', 'wcag21a', 'wcag21aa', 'wcag22aa'])
        .analyze();
      const detail = results.violations
        .flatMap((v) => v.nodes.map((n) => `${v.id}: ${n.html} -- ${n.failureSummary}`))
        .join('\n');
      expect(
        results.violations.length,
        `WCAG violations with the replace modal open (${theme} theme):\n${detail}`,
      ).toBe(0);
    });
  }

  // -------------------------------------------------------------------
  // Point 2: focus trap. Tab from the last focusable element goes to the
  // first; Shift+Tab from the first goes to the last; walking Tab all the
  // way round never lands outside the dialog.
  // -------------------------------------------------------------------
  test('Tab from the last focusable control cycles to the first, inside the dialog (point 2)', async ({ page }) => {
    const modal = await openReplaceModal(page, REVIEW_MOVIE_ID);

    const focusable = modal.locator(
      'button:not([disabled]), a[href], input, select, textarea, [tabindex]:not([tabindex="-1"])',
    );
    const count = await focusable.count();
    expect(count, 'the dialog must expose at least one focusable control to trap on').toBeGreaterThan(0);

    const last = focusable.nth(count - 1);
    await last.focus();
    await expect(last).toBeFocused();

    await page.keyboard.press('Tab');

    const first = focusable.nth(0);
    await expect(
      first,
      'Tab from the last focusable control in the dialog must land on the first, not escape the dialog',
    ).toBeFocused();
  });

  test('Shift+Tab from the first focusable control cycles to the last, inside the dialog (point 2)', async ({ page }) => {
    const modal = await openReplaceModal(page, REVIEW_MOVIE_ID);

    const focusable = modal.locator(
      'button:not([disabled]), a[href], input, select, textarea, [tabindex]:not([tabindex="-1"])',
    );
    const count = await focusable.count();

    const first = focusable.nth(0);
    await first.focus();
    await expect(first).toBeFocused();

    await page.keyboard.press('Shift+Tab');

    const last = focusable.nth(count - 1);
    await expect(
      last,
      'Shift+Tab from the first focusable control in the dialog must land on the last, not escape the dialog',
    ).toBeFocused();
  });

  test('walking Tab all the way around the dialog never lands focus on the page behind it (point 2)', async ({ page }) => {
    const modal = await openReplaceModal(page, REVIEW_MOVIE_ID);

    const focusable = modal.locator(
      'button:not([disabled]), a[href], input, select, textarea, [tabindex]:not([tabindex="-1"])',
    );
    const count = await focusable.count();
    await focusable.nth(0).focus();

    // One full loop plus a few extra presses -- if the trap has an
    // off-by-one it still shows up within a couple of laps.
    for (let i = 0; i < count + 3; i++) {
      await page.keyboard.press('Tab');
      const insideDialog = await page.evaluate(() => {
        const dialog = document.querySelector('[data-testid="operator-replace-modal"]');
        return !!dialog && !!document.activeElement && dialog.contains(document.activeElement);
      });
      expect(
        insideDialog,
        `after ${i + 1} Tab presses, focus escaped the dialog to the page behind it`,
      ).toBe(true);
    }
  });

  // -------------------------------------------------------------------
  // L3 (branch review 2026-08-31) / AC-A11Y-6: the confirm control must
  // use aria-disabled, never the real `disabled` attribute, so it stays
  // reachable by Tab both before a candidate is chosen AND while a
  // replacement is in flight -- and the in-flight half must be provably
  // in flight, not merely toggled instantly.
  // -------------------------------------------------------------------
  test('the confirm control is reachable by Tab before any candidate is chosen (AC-A11Y-6)', async ({ page }) => {
    const modal = await openReplaceModal(page, REVIEW_MOVIE_ID);

    // Deliberately nothing selected yet -- this is the state AC-A11Y-6
    // exists for: `disabled` would remove the control from the tab order
    // entirely here, so a keyboard user tabbing the dialog would meet
    // Cancel and then wrap straight past it with no indication a
    // selection was required.
    const confirmBtn = modal.locator('[data-testid="operator-replace-confirm"]');
    await expect(
      confirmBtn,
      'the confirm control must never carry the real disabled attribute -- aria-disabled only',
    ).not.toHaveAttribute('disabled', /.*/);

    // T7d item 8 (round two on L3): this test used to approximate "in the
    // tab order" with the SAME CSS selector `trapFocus()` itself uses
    // (`button:not([disabled]), a[href], input, select, textarea,
    // [tabindex]:not([tabindex="-1"])`) and never pressed Tab at all. That
    // selector cannot see the one thing that actually determines the
    // browser's real tab order versus a plain `querySelectorAll`: giving
    // the confirm button `tabindex="-1"` still matches
    // `button:not([disabled])` (tabindex plays no part in that clause), so
    // the old assertion kept passing while a real Tab key press would
    // skip straight over the control. This walks the ACTUAL tab order
    // with real key presses and checks the real `document.activeElement`,
    // which is the only thing that can see a `tabindex="-1"` regression.
    const focusable = modal.locator(
      'button:not([disabled]), a[href], input, select, textarea, [tabindex]:not([tabindex="-1"])',
    );
    const count = await focusable.count();
    await focusable.nth(0).focus();

    let reachedByTab = false;
    for (let i = 0; i < count + 2; i++) {
      await page.keyboard.press('Tab');
      const testid = await page.evaluate(
        () => document.activeElement?.getAttribute('data-testid') || null,
      );
      if (testid === 'operator-replace-confirm') {
        reachedByTab = true;
        break;
      }
    }
    expect(
      reachedByTab,
      'pressing Tab repeatedly from the dialog\'s first focusable control never actually moved focus onto the confirm control -- it is not reachable by keyboard even though nothing marks it disabled',
    ).toBe(true);
    await expect(confirmBtn, 'the confirm control must actually be focused after being reached by Tab').toBeFocused();

    await expect(confirmBtn, 'aria-disabled must be true while nothing is selected').toHaveAttribute('aria-disabled', 'true');
  });

  test('the confirm control keeps focus and reports aria-busy while a replacement is genuinely in flight (AC-A11Y-6)', async ({ page }) => {
    // A route that does not resolve until this test explicitly lets it --
    // otherwise the in-flight window is too narrow to reliably observe
    // (a same-tick fulfil could settle before the assertions below run).
    let releaseResponse: () => void = () => {};
    const held = new Promise<void>((resolve) => { releaseResponse = resolve; });
    await page.route(REPLACE_ROUTE, async (route) => {
      await held;
      return route.fulfill({ status: 200, contentType: 'application/json', body: '{"success":true}' });
    });

    const modal = await openReplaceModal(page, REVIEW_MOVIE_ID);
    await modal.getByRole('radio', { name: CANDIDATES[0], exact: true }).click();

    const confirmBtn = modal.locator('[data-testid="operator-replace-confirm"]');
    await confirmBtn.focus();
    await expect(confirmBtn).toBeFocused();
    await page.keyboard.press('Enter');

    // Still in flight: the fetch above is blocked on `held`, which this
    // test has not resolved yet.
    await expect(
      confirmBtn,
      'aria-busy must be true while the replacement request is in flight',
    ).toHaveAttribute('aria-busy', 'true');
    await expect(
      confirmBtn,
      'focus must stay on the confirm control while the replacement is in flight -- a native `disabled` attribute here would blur it to <body>',
    ).toBeFocused();

    releaseResponse();
    await expect
      .poll(async () => (await page.locator('[data-testid="toast-announcer-polite"]').textContent()) || '', { timeout: 5000 })
      .toMatch(/replac/i);
  });

  // -------------------------------------------------------------------
  // Point 3: Escape closes the dialog and returns focus to the trigger,
  // never to <body>.
  // -------------------------------------------------------------------
  test('Escape closes the dialog and returns focus to the trigger, not body (point 3)', async ({ page }) => {
    const modal = await openReplaceModal(page, REVIEW_MOVIE_ID);

    await page.keyboard.press('Escape');
    await expect(modal).toBeHidden({ timeout: 5000 });

    const trigger = page.locator('[data-testid="operator-replace-trigger"]');
    await expect(
      trigger,
      'Escape must return focus to the trigger that opened the dialog',
    ).toBeFocused();

    const isBody = await page.evaluate(() => document.activeElement === document.body);
    expect(isBody, 'focus fell to <body> after Escape -- it must land on the trigger').toBe(false);
  });

  // -------------------------------------------------------------------
  // Point 4: dialog semantics, and the page behind it is not reachable.
  // -------------------------------------------------------------------
  test('the dialog has an accessible name and correct role/aria-modal (point 4)', async ({ page }) => {
    const modal = await openReplaceModal(page, REVIEW_MOVIE_ID);

    await expect(modal).toHaveAttribute('role', 'dialog');
    await expect(modal).toHaveAttribute('aria-modal', 'true');

    const accessibleName = await modal.evaluate((el) => {
      const labelledBy = el.getAttribute('aria-labelledby');
      if (labelledBy) {
        const labelEl = document.getElementById(labelledBy);
        return labelEl?.textContent?.trim() || '';
      }
      return el.getAttribute('aria-label') || '';
    });
    expect(accessibleName.length, 'the dialog must have a non-empty accessible name').toBeGreaterThan(0);
  });

  test('the page behind the dialog is not reachable while it is open (point 4)', async ({ page }) => {
    await openReplaceModal(page, REVIEW_MOVIE_ID);

    // #main-content (base.html:477) and the desktop sidebar (base.html's
    // <aside>) are real, persistent landmarks carrying interactive content
    // (the movie's own controls, the Wanted/Settings nav) -- a screen
    // reader's browse-mode virtual cursor can still reach them unless they
    // are actually hidden from the accessibility tree, which Tab-order
    // trapping (point 2) does not achieve on its own.
    const behindState = await page.evaluate(() => {
      const read = (el: Element | null) => {
        if (!el) return null;
        return {
          inert: (el as HTMLElement).inert === true,
          ariaHidden: el.getAttribute('aria-hidden') === 'true',
        };
      };
      return {
        mainContent: read(document.getElementById('main-content')),
        sidebar: read(document.querySelector('aside')),
      };
    });

    expect(behindState.mainContent, '#main-content must exist behind the dialog').not.toBeNull();
    expect(
      behindState.mainContent!.inert || behindState.mainContent!.ariaHidden,
      'the page content behind the dialog (#main-content) must be inert or aria-hidden while the dialog is open, ' +
      'so a screen reader cannot browse into it',
    ).toBe(true);

    expect(behindState.sidebar, 'the sidebar <aside> must exist behind the dialog').not.toBeNull();
    expect(
      behindState.sidebar!.inert || behindState.sidebar!.ariaHidden,
      'the sidebar navigation behind the dialog must be inert or aria-hidden while the dialog is open',
    ).toBe(true);
  });

  test('the page behind the dialog is reachable again once it is closed (point 4)', async ({ page }) => {
    const modal = await openReplaceModal(page, REVIEW_MOVIE_ID);
    await page.keyboard.press('Escape');
    await expect(modal).toBeHidden({ timeout: 5000 });

    const behindState = await page.evaluate(() => {
      const el = document.getElementById('main-content');
      return {
        inert: !!el && (el as HTMLElement).inert === true,
        ariaHidden: el?.getAttribute('aria-hidden') === 'true',
      };
    });
    expect(
      behindState.inert || behindState.ariaHidden,
      '#main-content must not stay inert/aria-hidden after the dialog has closed -- the page would be permanently unreachable',
    ).toBe(false);
  });

  // -------------------------------------------------------------------
  // Point 5: the candidates form a real radio group with an accessible
  // group name, arrow-key operability, and each accessible name is the
  // file name.
  // -------------------------------------------------------------------
  test('the candidates are a radiogroup with an accessible group name (point 5)', async ({ page }) => {
    const modal = await openReplaceModal(page, REVIEW_MOVIE_ID);

    const group = modal.getByRole('radiogroup');
    await expect(group).toHaveCount(1);
    await expect(group).toHaveAccessibleName(/./);
  });

  test('each candidate radio has an accessible name that is the file name, in full (point 5)', async ({ page }) => {
    const longName = 'Minions.and.Monsters.2024.2160p.UHD.HDR10Plus.DoVi.Profile8.Atmos.TrueHD-VERY-LONG-RELEASE-GROUP-NAME.mkv';
    const modal = await openReplaceModal(page, REVIEW_MOVIE_ID, [longName, CANDIDATES[1]]);

    for (const name of [longName, CANDIDATES[1]]) {
      await expect(
        modal.getByRole('radio', { name, exact: true }),
        `candidate radio must have the FULL file name as its accessible name, even when the visible label is truncated by CSS: "${name}"`,
      ).toHaveCount(1);
    }
  });

  test('ArrowDown moves selection to the next candidate, and ArrowUp to the previous (point 5)', async ({ page }) => {
    const modal = await openReplaceModal(page, REVIEW_MOVIE_ID);

    const first = modal.getByRole('radio', { name: CANDIDATES[0], exact: true });
    const second = modal.getByRole('radio', { name: CANDIDATES[1], exact: true });

    await first.focus();
    await expect(first).toBeFocused();

    await page.keyboard.press('ArrowDown');
    await expect(
      second,
      'ArrowDown from the first candidate must move focus AND selection to the next candidate (WAI-ARIA radiogroup pattern)',
    ).toBeFocused();
    await expect(second).toHaveAttribute('aria-checked', 'true');
    await expect(first).toHaveAttribute('aria-checked', 'false');

    await page.keyboard.press('ArrowUp');
    await expect(
      first,
      'ArrowUp from the second candidate must move focus AND selection back to the first',
    ).toBeFocused();
    await expect(first).toHaveAttribute('aria-checked', 'true');
  });

  // -------------------------------------------------------------------
  // Point 6: the outcome is announced through base.html's persistent
  // announcers, and says what happened.
  // -------------------------------------------------------------------
  test('a successful replacement is announced through the persistent polite announcer (point 6)', async ({ page }) => {
    // Only renamer.operator_replace is faked -- the re-fetch this triggers
    // (cpSwap against /partial/movie/<id>) is left to hit the REAL backend,
    // same reasoning operator-replace-modal.spec.ts's own "re-fetches"
    // test already documents: nothing on disk changed (the destructive
    // route itself never reached the server), so re-rendering the same
    // seeded movie is safe and does not need its own stub. An earlier
    // version of this test stubbed /\/partial\/movie\// up front, which
    // also intercepted THIS TEST'S OWN initial navigation (detail.html
    // loads the whole detail partial via hx-get from that exact URL
    // pattern) -- it never reached the seeded movie at all.
    await page.route(REPLACE_ROUTE, (route) =>
      route.fulfill({ status: 200, contentType: 'application/json', body: '{"success":true}' }));

    const modal = await openReplaceModal(page, REVIEW_MOVIE_ID);
    await modal.getByRole('radio', { name: CANDIDATES[0], exact: true }).click();

    const confirmBtn = modal.locator('[data-testid="operator-replace-confirm"]');
    await expect(confirmBtn).toBeEnabled({ timeout: 5000 });
    await confirmBtn.click();

    const politeAnnouncer = page.locator('[data-testid="toast-announcer-polite"]');
    await expect
      .poll(async () => (await politeAnnouncer.textContent()) || '', { timeout: 5000 })
      .toMatch(/replac/i);
  });

  test('a genuine refusal from the real server is announced in a sentence a human can read, not a raw token (point 6, H12)', async ({ page }) => {
    // H12 (branch review 2026-08-31): the test this replaces stubbed
    // renamer.operator_replace with {success: false, error: 'declined_not_better'}
    // -- a response shape operatorReplaceView has NO code path to produce,
    // it answers {'success': True} on every outcome -- and then asserted
    // the raw internal token, which AC-DESIGN-10 explicitly forbids
    // surfacing to an operator. Deleting the server's entire outcome path
    // would not have made that test fail.
    //
    // This drives the REAL server instead. REPLACE_ROUTE is deliberately
    // NOT routed here. scripts/seed_e2e_data.py never writes a
    // renamer.from setting, so conf('from') is genuinely unset for every
    // worker's data dir, and `_resolveOperatorSource` refuses EVERY
    // operator replacement with OPERATOR_REFUSED_SOURCE_OUTSIDE_WATCH_FOLDER
    // before any release, file or database row is touched -- a real,
    // deterministic refusal produced by the application, not a fabricated
    // one. (The candidate LIST is still stubbed via openReplaceModal, same
    // as every other test in this file: this test is not about whether
    // that listing is real, only about what the operator is told once a
    // genuine refusal happens.)
    const modal = await openReplaceModal(page, REVIEW_DESTRUCTIVE_MOVIE_ID);
    await modal.getByRole('radio', { name: CANDIDATES[0], exact: true }).click();

    const confirmBtn = modal.locator('[data-testid="operator-replace-confirm"]');
    await expect(confirmBtn).toBeEnabled({ timeout: 5000 });
    await confirmBtn.click();

    const assertiveAnnouncer = page.locator('[data-testid="toast-announcer-assertive"]');
    const politeAnnouncer = page.locator('[data-testid="toast-announcer-polite"]');

    // The operator must be told, in words, that the request was refused --
    // never left to read nothing at all.
    await expect
      .poll(async () => (await assertiveAnnouncer.textContent()) || '', { timeout: 5000 })
      .not.toBe('');

    const assertiveText = (await assertiveAnnouncer.textContent()) || '';

    // "In a sentence a human can read" -- not a bare machine token. A
    // constant like the outcome name has no space in it; a sentence does.
    expect(
      assertiveText,
      'the announced refusal must read as a sentence, not a bare constant',
    ).toMatch(/\s/);

    // AC-DESIGN-10: none of the internal outcome constants this path can
    // return may ever reach the rendered text.
    for (const rawToken of [
      'operator_refused_source_outside_watch_folder',
      'operator_refused_error',
      'operator_declined_ambiguous_file',
      'declined_',
      'refused_',
      'failed_',
      'replace_atomically',
      'identity_source',
    ]) {
      expect(
        assertiveText,
        `the announced sentence must not surface the raw internal token "${rawToken}" (AC-DESIGN-10)`,
      ).not.toContain(rawToken);
    }

    // And the operator must never be told the replacement started when the
    // server refused it before any work began -- that is the false
    // positive that let H1 and H10 ship unnoticed.
    const politeText = (await politeAnnouncer.textContent()) || '';
    expect(
      politeText,
      'a refused replacement must not be announced as having started',
    ).not.toContain('Replacement started');
  });

  // -------------------------------------------------------------------
  // Point 7: target size and contrast, measured from the rendered page in
  // both themes -- never inferred from Tailwind class names. This branch
  // has already shipped a 23px chip and a 1.92:1 badge with entirely
  // correct-looking classes, so nothing here is asserted from the markup.
  // -------------------------------------------------------------------
  for (const theme of ['light', 'dark'] as const) {
    test(`confirm, cancel and every candidate radio meet the 24x24 target size floor at 1280px (${theme} theme, point 7)`, async ({ page }) => {
      if (theme === 'dark') await setDarkTheme(page);
      const modal = await openReplaceModal(page, REVIEW_MOVIE_ID);
      await assertThemeIs(page, theme === 'light');

      await modal.getByRole('radio', { name: CANDIDATES[0], exact: true }).click();
      const confirmBtn = modal.locator('[data-testid="operator-replace-confirm"]');
      const cancelBtn = modal.getByRole('button', { name: 'Cancel', exact: true });

      const boxes: Array<[string, { width: number; height: number } | null]> = [
        ['confirm', await confirmBtn.boundingBox()],
        ['cancel', await cancelBtn.boundingBox()],
      ];
      const radios = modal.getByRole('radio');
      const radioCount = await radios.count();
      for (let i = 0; i < radioCount; i++) {
        boxes.push([`radio ${i}`, await radios.nth(i).boundingBox()]);
      }

      for (const [name, box] of boxes) {
        expect(box, `${name} has no bounding box`).not.toBeNull();
        expect(layoutPx(box!.width), `${name} width at 1280px (${theme} theme)`).toBeGreaterThanOrEqual(TARGET_SIZE_MIN);
        expect(layoutPx(box!.height), `${name} height at 1280px (${theme} theme)`).toBeGreaterThanOrEqual(TARGET_SIZE_MIN);
      }
    });

    test(`the confirm control (the one that commits the deletion) meets the 44x44 target size floor (${theme} theme, point 7 / AC-A11Y-14)`, async ({ page }) => {
      if (theme === 'dark') await setDarkTheme(page);
      const modal = await openReplaceModal(page, REVIEW_MOVIE_ID);
      await assertThemeIs(page, theme === 'light');
      await modal.getByRole('radio', { name: CANDIDATES[0], exact: true }).click();

      const confirmBtn = modal.locator('[data-testid="operator-replace-confirm"]');
      const box = await confirmBtn.boundingBox();
      expect(box, 'confirm control has no bounding box').not.toBeNull();
      expect(
        layoutPx(box!.width),
        `confirm control width in ${theme} theme -- a mis-tap here destroys an irreplaceable file, so WCAG 2.2 AA 2.5.8's 24px floor is not enough on its own`,
      ).toBeGreaterThanOrEqual(TARGET_SIZE_MIN_LARGE);
      expect(layoutPx(box!.height), `confirm control height in ${theme} theme`).toBeGreaterThanOrEqual(TARGET_SIZE_MIN_LARGE);
    });

    test(`confirm and cancel controls meet 4.5:1 text contrast against the dialog surface they actually sit on (${theme} theme, point 7)`, async ({ page }) => {
      if (theme === 'dark') await setDarkTheme(page);
      const modal = await openReplaceModal(page, REVIEW_MOVIE_ID);
      await assertThemeIs(page, theme === 'light');
      await modal.getByRole('radio', { name: CANDIDATES[0], exact: true }).click();

      // The dialog's own surface, not the page background: the footer
      // controls sit inside the bg-cp-card box, not directly on bg-cp-bg.
      const dialogBg = await modal.locator('.bg-cp-card').first().evaluate(
        (el) => window.getComputedStyle(el).backgroundColor,
      );
      const parseTriplet = (s: string): [number, number, number] => {
        const m = s.match(/(\d+),\s*(\d+),\s*(\d+)/)!;
        return [+m[1], +m[2], +m[3]];
      };
      const backdrop = parseTriplet(dialogBg);

      const confirmBtn = modal.locator('[data-testid="operator-replace-confirm"]');
      const cancelBtn = modal.getByRole('button', { name: 'Cancel', exact: true });

      for (const [name, control] of [['confirm', confirmBtn], ['cancel', cancelBtn]] as const) {
        const colours = await control.evaluate((el) => {
          const s = window.getComputedStyle(el);
          return { bg: s.backgroundColor, fg: s.color };
        });
        const ratio = contrastAgainstBackdrop(colours.bg, colours.fg, backdrop);
        expect(
          ratio,
          `${name} control contrast in ${theme} theme: ${ratio.toFixed(2)}:1 (bg=${colours.bg}, fg=${colours.fg}, ` +
          `dialog surface=${dialogBg}) -- WCAG 1.4.3 requires >= 4.5:1`,
        ).toBeGreaterThanOrEqual(4.5);
      }
    });

    test(`every control reached by keyboard shows a visible focus indicator against the dialog surface (${theme} theme, AC-A11Y-12)`, async ({ page }) => {
      if (theme === 'dark') await setDarkTheme(page);
      const modal = await openReplaceModalByKeyboard(page, REVIEW_MOVIE_ID);
      await assertThemeIs(page, theme === 'light');

      // Real keyboard traversal, matching a keyboard-only user end to end:
      // Close is auto-focused on open; Tab order is then
      // close -> radio 1 -> radio 2 -> Cancel -> Confirm (Confirm only
      // joins the tab order once a candidate is selected, per
      // :disabled="!selected" -- same order already proven by the point 2
      // focus-trap tests above).
      const radio1 = modal.getByRole('radio', { name: CANDIDATES[0], exact: true });
      const radio2 = modal.getByRole('radio', { name: CANDIDATES[1], exact: true });
      const cancelBtn = modal.getByRole('button', { name: 'Cancel', exact: true });
      const confirmBtn = modal.locator('[data-testid="operator-replace-confirm"]');

      const assertRing = async (name: string, control: import('@playwright/test').Locator) => {
        const indicator = await control.evaluate(FOCUS_RING_PROBE);
        expect(
          indicator.visible,
          `${name} has no visible focus indicator in the ${theme} theme when reached by keyboard (WCAG 2.2 AA 1.4.11). ` +
          `Computed: outline ${indicator.outlineStyle} ${indicator.outlineWidth} ${indicator.outlineColor}, ` +
          `box-shadow ${indicator.boxShadow}, changedOnFocus=${indicator.changedOnFocus}.`,
        ).toBe(true);
      };

      await page.keyboard.press('Tab'); // close -> radio 1
      await expect(radio1).toBeFocused();
      await assertRing('first radio', radio1);

      await page.keyboard.press(' '); // native button activation selects it
      await expect(radio1).toHaveAttribute('aria-checked', 'true');

      await page.keyboard.press('Tab'); // radio 1 -> radio 2
      await expect(radio2).toBeFocused();

      await page.keyboard.press('Tab'); // radio 2 -> Cancel
      await expect(cancelBtn).toBeFocused();
      await assertRing('cancel', cancelBtn);

      await page.keyboard.press('Tab'); // Cancel -> Confirm (now enabled)
      await expect(confirmBtn).toBeFocused();
      await assertRing('confirm', confirmBtn);
    });
  }

  // -------------------------------------------------------------------
  // AC-A11Y-9: outcome states are distinguishable by text/name alone, not
  // colour. The confirm control's own name says what it does; it must not
  // rely on being "the red one" to read as destructive.
  // -------------------------------------------------------------------
  test('the confirm control is distinguishable from cancel by accessible name alone, ignoring all styling (AC-A11Y-9)', async ({ page }) => {
    const modal = await openReplaceModal(page, REVIEW_MOVIE_ID);
    await modal.getByRole('radio', { name: CANDIDATES[0], exact: true }).click();

    const confirmName = await modal.locator('[data-testid="operator-replace-confirm"]').evaluate(
      (el) => (el.textContent || '').trim(),
    );
    const cancelName = await modal.getByRole('button', { name: 'Cancel', exact: true }).evaluate(
      (el) => (el.textContent || '').trim(),
    );
    expect(confirmName.toLowerCase()).not.toBe(cancelName.toLowerCase());
    expect(confirmName.length, 'the confirm control must have real text content, not rely on colour to read as destructive').toBeGreaterThan(0);
  });
});
