import { test as base, expect, type Page } from '@playwright/test';
import AxeBuilder from '@axe-core/playwright';
import { type ChildProcess, execFileSync, spawn } from 'node:child_process';
import { existsSync } from 'node:fs';
import { setTimeout as sleep } from 'node:timers/promises';

/**
 * The whole session, in a real browser, with authentication genuinely ON.
 * AC-QA-27, and the browser half of AC-A11Y-7.
 *
 * Everything else in this suite runs against an instance seeded with NO
 * password, where `auth_is_required()` is False. On such an instance:
 *
 *   * `GET /login/` answers 307 to `/`, because `login_get` redirects anyone
 *     `get_current_user` accepts and that is everybody -- so `page.goto('/login/')`
 *     lands on the app;
 *   * the sign-out control does not exist in the DOM at all, because both
 *     copies sit behind `{% if auth_required %}`.
 *
 * So the sign-out control D8 added had never been in a browser, and
 * `navigation.spec.ts:13-27` "handled" login inside two `if`s that passed
 * silently while asserting nothing. `login-page.a11y.spec.ts` worked around it
 * honestly -- rendering the real routes and fulfilling `/login/` with the bytes
 * -- but that cannot show the route is reachable, and has no equivalent for a
 * control that is not rendered.
 *
 * This file therefore starts its OWN server, on its own port, against its own
 * data dir, seeded WITH a password. It deliberately does not import
 * `./fixtures`: that module's `workerServer` is `auto: true`, so importing it
 * would start a second, passwordless server this file has no use for.
 *
 * UNCONDITIONAL, and it must stay that way. No `test.skip`, and the login form
 * is asserted rather than checked: if the form is absent this fails, which is
 * the entire difference between this file and the block it replaces.
 */

const VENV_PYTHON = '.venv/bin/python';
const PYTHON = process.env.PYTHON || (existsSync(VENV_PYTHON) ? VENV_PYTHON : 'python3');

/** Well clear of fixtures.ts's 5150 block and of the app default (5050). */
const BASE_PORT = 5250;
/** Well clear of fixtures.ts's `parallelIndex` block, same safety helper. */
const DATA_DIR_INDEX_BASE = 90;
const PASSWORD = 'e2e-authenticated-session-pw';
const READY_TIMEOUT_MS = 25_000;
const POLL_INTERVAL_MS = 250;

/** WCAG 2.2 AA 2.5.8. The house 44px figure does not bind here -- see the spec. */
const MIN_TARGET_PX = 24;

type AuthServer = { baseURL: string };

function decode(chunk: unknown): string {
  return chunk instanceof Buffer ? chunk.toString('utf-8') : String(chunk);
}

/**
 * Ready means "serving the LOGIN page", not "serving the library".
 *
 * fixtures.ts's probe cannot be reused: it waits for `/partial/movies` to
 * contain a poster card, and on an authenticated instance that request
 * redirects to the login page forever. Reusing it would hang for the full
 * budget and then report a timeout that says nothing about why.
 */
async function waitForLoginPage(
  getExit: () => { code: number | null; signal: NodeJS.Signals | null } | null,
  baseURL: string,
  getOutput: () => string,
): Promise<void> {
  const deadline = Date.now() + READY_TIMEOUT_MS;
  while (Date.now() < deadline) {
    const exited = getExit();
    if (exited) {
      throw new Error(
        `the authenticated instance exited before it became ready (code ${exited.code}, ` +
        `signal ${exited.signal}). Last output:\n${getOutput().slice(-4000)}`,
      );
    }
    try {
      const res = await fetch(new URL('/login/', baseURL).href, { redirect: 'manual' });
      if (res.status === 200 && (await res.text()).includes('name="password"')) return;
    } catch {
      // Not listening yet.
    }
    await sleep(POLL_INTERVAL_MS);
  }
  throw new Error(
    `${baseURL}/login/ never served a login form within ${READY_TIMEOUT_MS}ms. ` +
    `If it answered 307, the seeded password did not take effect and this suite ` +
    `would otherwise have tested an OPEN instance.\nLast output:\n${getOutput().slice(-4000)}`,
  );
}

const test = base.extend<Record<string, never>, { authServer: AuthServer }>({
  authServer: [async ({}, use, workerInfo) => {
    const idx = DATA_DIR_INDEX_BASE + workerInfo.parallelIndex;
    const port = BASE_PORT + workerInfo.parallelIndex;
    const baseURL = `http://localhost:${port}`;

    // The same guarded helper every other worker data dir goes through
    // (AC-DATA-24/25/26): validated before a server starts, refused if a
    // previous run left one behind, and deleted only through `safe_rmtree`.
    const dataDir = execFileSync(
      PYTHON, ['scripts/e2e_worker_data.py', 'prepare', String(idx)], { encoding: 'utf-8' },
    ).trim();

    let proc: ChildProcess | undefined;
    let output = '';
    let exited: { code: number | null; signal: NodeJS.Signals | null } | null = null;
    try {
      execFileSync(
        PYTHON, ['scripts/seed_e2e_data.py', `--data_dir=${dataDir}`, `--password=${PASSWORD}`],
        { stdio: 'pipe' },
      );
      proc = spawn(
        PYTHON, ['CouchPotato.py', `--data_dir=${dataDir}`, `--port=${port}`, '--console_log'],
        { stdio: ['ignore', 'pipe', 'pipe'] },
      );
      proc.stdout?.on('data', (d) => { output += decode(d); });
      proc.stderr?.on('data', (d) => { output += decode(d); });
      proc.on('exit', (code, signal) => { exited = { code, signal }; });

      await waitForLoginPage(() => exited, baseURL, () => output);
    } catch (err) {
      if (proc && proc.exitCode === null && proc.signalCode === null) proc.kill('SIGKILL');
      try {
        execFileSync(PYTHON, ['scripts/e2e_worker_data.py', 'cleanup', String(idx)], { stdio: 'pipe' });
      } catch {
        // Cleanup failing must not mask the real error.
      }
      throw err;
    }

    await use({ baseURL });

    if (proc.exitCode === null && proc.signalCode === null) {
      const gone = new Promise<void>((resolve) => proc!.once('exit', () => resolve()));
      proc.kill('SIGTERM');
      const outcome = await Promise.race([
        gone.then(() => 'exited' as const),
        sleep(5000).then(() => 'timeout' as const),
      ]);
      if (outcome === 'timeout') {
        proc.kill('SIGKILL');
        await gone;
      }
    }
    execFileSync(PYTHON, ['scripts/e2e_worker_data.py', 'cleanup', String(idx)], { stdio: 'pipe' });
  }, { scope: 'worker' }],

  baseURL: async ({ authServer }, use) => {
    await use(authServer.baseURL);
  },
});

/**
 * The sign-out control the DESKTOP viewport actually shows.
 *
 * Two render (sidebar and mobile menu), so `getByRole(...)` matches both and
 * `.first()` would be a coin toss. Spec gap 14 records what that costs: the
 * unit-level version of this test filtered by `action="/logout/"` and took
 * `[0]`, so pointing the sidebar form at `/sign-out/` left the mobile one
 * matching and the whole chain stayed green against a control answering 404.
 *
 * So: scoped to the `<aside>` (which is what the unit tests use to tell the
 * two apart), found by its ACCESSIBLE NAME, and asserted to be exactly one.
 */
function signOutInSidebar(page: Page) {
  return page.locator('aside').getByRole('button', { name: /sign out/i });
}

async function signIn(page: Page) {
  await page.goto('/wanted/');

  await expect(page, 'a protected page did not redirect to the login page, so ' +
    'this instance is not enforcing authentication and every assertion below ' +
    'would be meaningless').toHaveURL(/\/login\//);

  // Asserted, never `if (await form.count())`. This is the line that makes the
  // file fail instead of skipping when the form is not there.
  await expect(page.locator('input[name="password"]')).toBeVisible();

  await page.fill('input[name="password"]', PASSWORD);
  await page.click('button[type="submit"]');
  await page.waitForURL((url) => !url.pathname.includes('/login'));
  await expect(page.locator('#main-content')).toBeVisible();
}

test.describe('An authenticated session, end to end', () => {
  test('sign in, stay signed in across a reload, sign out from the page, and be locked out again', async ({ page }) => {
    await signIn(page);

    // The session survives a reload -- i.e. the cookie was actually set with
    // attributes a real browser keeps and sends back, not merely returned in
    // a header.
    //
    // It does NOT prove the `Secure` half of AC-SEC-39/AC-OPS-52, and saying
    // so matters: this instance is plain HTTP, but it is served over
    // `localhost`, which Chrome treats as a SECURE CONTEXT and therefore
    // accepts `Secure` cookies from. Measured -- hardcoding `secure=True`
    // leaves all five tests in this file green. That mutation is killed by
    // tests/unit/test_session_cookie_attributes.py, which asserts on the raw
    // `Set-Cookie` header; a comment here claiming otherwise would send the
    // next reader looking in the wrong file.
    await page.reload();
    await expect(page).not.toHaveURL(/\/login\//);
    await expect(page.locator('#main-content')).toBeVisible();

    const control = signOutInSidebar(page);
    await expect(control).toHaveCount(1);

    // Drive the control's OWN declared action rather than assuming it. If the
    // form pointed somewhere else, this click would go there and the
    // assertions below would fail -- which is the point.
    // `has:` is resolved against the filtered element, so it must be
    // page-rooted rather than the already-scoped `control` above.
    const form = page.locator('aside form')
      .filter({ has: page.getByRole('button', { name: /sign out/i }) });
    await expect(form).toHaveCount(1);
    const action = await form.getAttribute('action');
    expect(action, 'the sign-out control does not post to the logout route').toMatch(/\/logout\/$/);

    await control.click();

    await expect(page).toHaveURL(/\/login\//);
    const message = page.locator('[data-testid="login-message"]');
    await expect(message).toBeVisible();
    await expect(message).toContainText(/signed out/i);
    await expect(message).toContainText(/every device/i);

    // And the session is really over: a protected page is refused again.
    await page.goto('/wanted/');
    await expect(page, 'a protected page still served after signing out').toHaveURL(/\/login\//);
  });

  test('the sign-out control is reachable by Tab from the top of the page', async ({ page }) => {
    await signIn(page);

    const control = signOutInSidebar(page);
    await expect(control).toHaveCount(1);

    // From the top, with no pointer and no focus() call: AC-A11Y-7 is about a
    // keyboard user, and a programmatic focus proves nothing about tab order.
    await page.evaluate(() => (document.activeElement as HTMLElement | null)?.blur());
    await page.keyboard.press('Tab');

    let reached = false;
    for (let i = 0; i < 60 && !reached; i++) {
      reached = await control.evaluate((el) => el === document.activeElement);
      if (!reached) await page.keyboard.press('Tab');
    }

    expect(reached, 'the sign-out control cannot be reached by Tab, so a ' +
      'keyboard-only operator has no way to end their session').toBe(true);
  });

  test('the sign-out control meets the 24x24 activation target', async ({ page }) => {
    await signIn(page);

    const box = await signOutInSidebar(page).boundingBox();
    expect(box, 'the sign-out control has no layout box at all').not.toBeNull();
    expect(box!.width).toBeGreaterThanOrEqual(MIN_TARGET_PX);
    expect(box!.height).toBeGreaterThanOrEqual(MIN_TARGET_PX);
  });

  for (const theme of ['light', 'dark'] as const) {
    test(`axe reports no violations on the sign-out control in the ${theme} theme`, async ({ page }) => {
      // Seeded before navigation: base.html's own init reads `cp-theme` from
      // localStorage and re-applies it, so setting the class afterwards is
      // silently undone.
      await page.addInitScript((t) => localStorage.setItem('cp-theme', t as string), theme);
      await signIn(page);

      // The theme really took, so a broken theme pipeline cannot quietly run
      // both cases in one theme.
      await expect
        .poll(() => page.evaluate(() => document.documentElement.classList.contains('light')))
        .toBe(theme === 'light');

      await expect(signOutInSidebar(page)).toHaveCount(1);

      const results = await new AxeBuilder({ page })
        .include('aside')
        .withTags(['wcag2a', 'wcag2aa', 'wcag21a', 'wcag21aa', 'wcag22aa'])
        .analyze();

      const detail = results.violations
        .flatMap((v) => v.nodes.map((n) => `${v.id}: ${n.html} — ${n.failureSummary}`))
        .join('\n');
      expect(results.violations.length, `sign-out/${theme}:\n${detail}`).toBe(0);
    });
  }
});
