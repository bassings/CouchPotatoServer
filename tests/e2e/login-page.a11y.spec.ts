import { test, expect, type Page } from './fixtures';
import AxeBuilder from '@axe-core/playwright';
import { execFileSync } from 'node:child_process';
import { existsSync, mkdtempSync, readFileSync, rmSync } from 'node:fs';
import { tmpdir } from 'node:os';
import path from 'node:path';

/**
 * The login page, in a real browser, in both themes. AC-A11Y-1/3/13/14.
 *
 * `login_get` redirects anyone `get_current_user` accepts, and with
 * `auth_required` off that is everybody -- so on these instances (seeded with
 * no password by scripts/seed_e2e_data.py) `/login/` is unreachable by
 * navigation, and the authenticated E2E that would fix that is AC-QA-27, a
 * later tranche.
 *
 * Rather than leave the browser-only checks unwritten until then, each state
 * is rendered by driving the REAL FastAPI routes (tests/e2e/render_login_states.py)
 * and served back at this instance's own `/login/` URL, so the relative
 * `/static/` assets -- including the Tailwind CDN script that produces every
 * class on the page -- resolve against the live server. The bytes are the
 * route's; only the transport differs.
 *
 * What this does NOT prove, stated rather than implied: that `/login/` is
 * reachable at all with authentication on, or that the sign-out control in
 * base.html renders correctly. Both need a server with a password, which is
 * AC-QA-27's tranche.
 */

const VENV_PYTHON = '.venv/bin/python';
const PYTHON = process.env.PYTHON || (existsSync(VENV_PYTHON) ? VENV_PYTHON : 'python3');

/** WCAG 2.2 AA 1.4.11 for a focus indicator; 2.5.8 for a target. */
const MIN_NON_TEXT_RATIO = 3.0;
const MIN_TARGET_PX = 24;

let renderDir: string;
let states: Record<string, string>;

test.beforeAll(() => {
  renderDir = mkdtempSync(path.join(tmpdir(), 'cp-login-states-'));
  const stdout = execFileSync(PYTHON, ['tests/e2e/render_login_states.py', renderDir], {
    encoding: 'utf-8',
  });
  states = JSON.parse(stdout.trim().split('\n').pop()!);
});

test.afterAll(() => {
  if (renderDir) rmSync(renderDir, { recursive: true, force: true });
});

async function showLogin(page: Page, state: string, theme: 'light' | 'dark') {
  const html = readFileSync(states[state], 'utf-8');
  // Seed the theme BEFORE navigation: login.html's own init reads `cp-theme`
  // from localStorage and re-applies it, so toggling the class afterwards is
  // silently undone (the same trap the toast contrast tests document).
  await page.addInitScript((t) => localStorage.setItem('cp-theme', t as string), theme);
  await page.route(/\/login\/?(\?|$)/, (route) =>
    route.fulfill({ status: 200, contentType: 'text/html; charset=utf-8', body: html }),
  );
  await page.goto('/login/');
  await page.waitForLoadState('networkidle');

  // The theme really took effect. Load-bearing: without it a broken theme
  // pipeline would quietly run every "dark" case in the light theme, which is
  // exactly how the dark-only toast failure shipped.
  await expect
    .poll(() => page.evaluate(() => document.documentElement.classList.contains('light')))
    .toBe(theme === 'light');

  // The page's classes are generated at runtime by the Tailwind CDN script,
  // so wait for one of them to have actually produced a colour rather than
  // measuring an unstyled document.
  await expect
    .poll(() =>
      page.evaluate(() => getComputedStyle(document.body).backgroundColor),
    )
    .not.toBe('rgba(0, 0, 0, 0)');
}

const THEMES = ['light', 'dark'] as const;
//: The three states AC-A11Y-1 names: no message, a notice, and a failure.
const SCANNED_STATES = ['first_visit', 'signed_out', 'rejected'] as const;

test.describe('Login page accessibility', () => {
  for (const theme of THEMES) {
    for (const state of SCANNED_STATES) {
      test(`axe reports no violations on the ${state} state in the ${theme} theme`, async ({ page }) => {
        await showLogin(page, state, theme);

        const results = await new AxeBuilder({ page })
          .withTags(['wcag2a', 'wcag2aa', 'wcag21a', 'wcag21aa', 'wcag22aa'])
          .analyze();

        const detail = results.violations
          .flatMap((v) => v.nodes.map((n) => `${v.id}: ${n.html} — ${n.failureSummary}`))
          .join('\n');
        expect(results.violations.length, `${state}/${theme}:\n${detail}`).toBe(0);
      });
    }
  }

  for (const theme of THEMES) {
    test(`every control shows a focus indicator when reached by Tab in the ${theme} theme`, async ({ page }) => {
      await showLogin(page, 'first_visit', theme);

      // Tab, never focus(). base.html and login.html both carry
      // `:focus:not(:focus-visible) { outline: none }`, so a programmatic
      // focus can report an indicator a keyboard user would never see -- and,
      // for buttons, the reverse.
      const seen = new Map<string, { ratio: number; outline: string; visible: boolean }>();
      for (let i = 0; i < 8; i++) {
        const probe = await page.evaluate(() => {
          const el = document.activeElement as HTMLElement | null;
          if (!el || el === document.body) return null;
          const s = getComputedStyle(el);
          const card = document.querySelector('.bg-cp-card') as HTMLElement;
          const surface = getComputedStyle(card).backgroundColor;

          const luminance = (colour: string) => {
            const parts = (colour.match(/\d+(\.\d+)?/g) || ['0', '0', '0'])
              .slice(0, 3)
              .map(Number)
              .map((v) => {
                const c = v / 255;
                return c <= 0.04045 ? c / 12.92 : Math.pow((c + 0.055) / 1.055, 2.4);
              });
            return 0.2126 * parts[0] + 0.7152 * parts[1] + 0.0722 * parts[2];
          };
          const a = luminance(s.outlineColor);
          const b = luminance(surface);

          return {
            id: el.id || el.tagName.toLowerCase() + ':' + (el.getAttribute('type') || ''),
            outline: `${s.outlineStyle} ${s.outlineWidth} ${s.outlineColor}`,
            visible:
              s.outlineStyle !== 'none' &&
              parseFloat(s.outlineWidth || '0') > 0 &&
              s.outlineColor !== 'transparent' &&
              !/rgba\([^)]*,\s*0\s*\)/.test(s.outlineColor),
            ratio: (Math.max(a, b) + 0.05) / (Math.min(a, b) + 0.05),
          };
        });

        if (probe) seen.set(probe.id, probe);
        await page.keyboard.press('Tab');
      }

      for (const id of ['username', 'password', 'remember_me']) {
        const probe = seen.get(id);
        expect(probe, `#${id} was never reached by Tab (seen: ${[...seen.keys()].join(', ')})`).toBeTruthy();
        expect(probe!.visible, `#${id} focus indicator: ${probe!.outline}`).toBe(true);
        expect(
          probe!.ratio,
          `#${id} focus indicator ${probe!.outline} measures ${probe!.ratio.toFixed(2)}:1 ` +
            `against the card in the ${theme} theme, under WCAG 1.4.11's ${MIN_NON_TEXT_RATIO}:1`,
        ).toBeGreaterThanOrEqual(MIN_NON_TEXT_RATIO);
      }
    });
  }

  test('the Remember me target clears the WCAG 2.2 minimum', async ({ page }) => {
    await showLogin(page, 'first_visit', 'light');

    // The LABEL, not the checkbox: its `for=` makes the whole thing activate
    // the control, so it is the target 2.5.8 measures.
    const box = await page.locator('label[for="remember_me"]').boundingBox();
    expect(box, 'the remember-me label did not render').toBeTruthy();
    expect(
      Math.min(box!.width, box!.height),
      `the remember-me target measures ${box!.width}x${box!.height} CSS px`,
    ).toBeGreaterThanOrEqual(MIN_TARGET_PX);
  });

  /*
   * AC-A11Y-14. 640x512 is 1280x1024 at 200% zoom -- WCAG 1.4.10 is defined in
   * CSS pixels, so halving the viewport is the equivalence, and 320 is the
   * criterion's own floor.
   */
  for (const theme of THEMES) {
    for (const [label, width, height] of [
      ['320 CSS px', 320, 640],
      ['200% zoom on 1280x1024', 640, 512],
    ] as const) {
      test(`the message reflows at ${label} in the ${theme} theme`, async ({ page }) => {
        await page.setViewportSize({ width, height });
        await showLogin(page, 'session_ended', theme);

        const overflow = await page.evaluate(() => ({
          scrollWidth: document.documentElement.scrollWidth,
          clientWidth: document.documentElement.clientWidth,
        }));
        expect(
          overflow.scrollWidth,
          `the page scrolls horizontally (${overflow.scrollWidth} > ${overflow.clientWidth})`,
        ).toBeLessThanOrEqual(overflow.clientWidth + 1);

        // Present, non-empty and not clipped: a message reduced to zero height
        // by an overflow rule would satisfy "no horizontal scroll" while being
        // unreadable.
        const message = page.locator('[data-testid="login-message"]');
        await expect(message).toBeVisible();
        const clipped = await message.evaluate(
          (el) => el.scrollHeight > el.clientHeight + 1 || el.scrollWidth > el.clientWidth + 1,
        );
        expect(clipped, 'the status message is clipped by its own box').toBe(false);
      });
    }
  }
});
