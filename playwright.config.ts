import { existsSync } from 'node:fs';

import { defineConfig, devices } from '@playwright/test';

/**
 * Playwright configuration for CouchPotato E2E tests.
 * See https://playwright.dev/docs/test-configuration
 */

/*
 * Interpreter used to start the app for local runs (see `webServer` below).
 *
 * Resolution order, most specific first:
 *   1. $PYTHON — what scripts/verify.sh exports, so the gate starts the app with
 *      the same interpreter it ran the unit tests with.
 *   2. ./.venv/bin/python — so a bare `npm run test:e2e` works without the caller
 *      having to know about the venv. The app needs bcrypt/httpx, which a system
 *      python3 typically lacks, and the failure mode is an opaque
 *      "ModuleNotFoundError: No module named 'bcrypt'" from a background process.
 *   3. python3 — PEP 394's guaranteed name. A bare `python` is deliberately NOT
 *      used: it does not exist on a stock macOS + Homebrew setup, which made the
 *      local E2E stage die with "python: command not found" before any test ran.
 */
const VENV_PYTHON = '.venv/bin/python';
const PYTHON =
  process.env.PYTHON || (existsSync(VENV_PYTHON) ? VENV_PYTHON : 'python3');
export default defineConfig({
  testDir: './tests/e2e',
  /* Run tests in files in parallel */
  fullyParallel: true,
  /* Fail the build on CI if you accidentally left test.only in the source code. */
  forbidOnly: !!process.env.CI,
  /* Retry on CI only */
  retries: process.env.CI ? 2 : 0,
  /*
   * ONE worker — and the SAME setting locally and on CI.
   *
   * History worth keeping, because the shape of the bug recurs: this was
   * `process.env.CI ? 1 : undefined`, which serialised CI while a local run used
   * one worker per core. CI was green and local failed ~20 of 142 — so the local
   * gate could never pass, which defeats CLAUDE.md hard rule 2 ("`make verify`
   * must pass locally before every push"). A gate that cannot pass gets bypassed.
   *
   * Two genuine improvements were made toward parallelism, and they stand:
   *   - categories/profiles declare `test.describe.configure({ mode: 'serial' })`,
   *     because they mutate GLOBAL singleton config (the category/profile list)
   *     under fixed fixture names and assert on list order.
   *   - the suggestions and search specs stub their third-party lookups
   *     (`/partial/charts`, `/partial/search`) instead of waiting on Blu-ray.com
   *     and TMDB, which also makes the suite hermetic.
   *
   * They were not sufficient: parallel is NOT yet reliable, so this stays at one
   * worker.
   *
   * Measured after the serial-mode change, n=5 at that commit: 4 green, 1 red
   * (`release_controls` "sorting by size"). Earlier runs of n=3 and n=4 came back
   * all-green, which is why an earlier version of this comment claimed parallel
   * was verified — that was under-powered evidence, not a verification. At one
   * worker the suite has been green on every run.
   *
   * The residual failures are CROSS-FILE: `mode: 'serial'` fixed races within
   * categories/profiles, but those files still run concurrently with each other
   * and with release_controls, and all three mutate global singleton state on one
   * shared server. Playwright has no "these files must not run concurrently"
   * primitive, so the real fixes are (a) merge the state-mutating specs into one
   * serial file, or (b) a server per worker. Both are real work; see
   * docs/technical-debt.md.
   *
   * Cost of this decision: ~4.1 min instead of ~1.0 min. Worth it. A gate that
   * spuriously reds one run in five teaches everyone to re-run and ignore it,
   * which is how a gate stops being a gate.
   */
  workers: 1,
  /* Reporter to use. See https://playwright.dev/docs/test-reporters */
  reporter: [
    ['html', { open: 'never' }],
    ['list']
  ],
  /* Shared settings for all the projects below. */
  use: {
    /* Base URL for tests */
    baseURL: process.env.CP_TEST_URL || 'http://localhost:5050',
    
    /* Collect trace when retrying the failed test. */
    trace: 'on-first-retry',
    
    /* Screenshot on failure */
    screenshot: 'only-on-failure',
  },

  /* Configure projects for major browsers */
  projects: [
    {
      name: 'chromium',
      use: { ...devices['Desktop Chrome'] },
    },
    {
      name: 'firefox',
      use: { ...devices['Desktop Firefox'] },
    },
    {
      name: 'webkit',
      use: { ...devices['Desktop Safari'] },
    },
    /* Accessibility tests project */
    {
      name: 'accessibility',
      testMatch: /.*\.a11y\.spec\.ts/,
      use: { ...devices['Desktop Chrome'] },
    },
    /* Mobile viewport testing */
    {
      name: 'mobile-chrome',
      use: { ...devices['Pixel 5'] },
    },
  ],

  /* Timeout settings */
  timeout: 30000,
  expect: {
    timeout: 5000,
  },

  /*
   * Local runs auto-start the app so `npm run test:e2e` works with no manual
   * server step. CI starts the server itself (see .github/workflows/ci.yml),
   * so we skip webServer there to avoid a port clash.
   * Uses a throwaway .e2e-data dir — never the real ./.config the dev/docker uses.
   *
   * Seeds a deterministic movie + releases (scripts/seed_e2e_data.py, FEAT-007
   * Part B) before the server starts, so tests/e2e/release_controls.spec.ts and
   * the movie-detail case in accessibility.a11y.spec.ts run instead of
   * test.skip()-ing on an empty library -- same before-server-start ordering
   * as the CI job. The seed step is deliberately tolerant (`|| true`): if it
   * fails, the server still starts and the rest of the suite still runs --
   * those two specs just fall back to skipping, matching the pre-seed
   * behaviour, rather than a seed bug taking down the entire local E2E run.
   */
  webServer: process.env.CI
    ? undefined
    : {
        // Interpreter resolution is explained at the top of this file (PYTHON).
        // CI is unaffected — it skips webServer entirely and starts its own server.
        command:
          `(${PYTHON} scripts/seed_e2e_data.py --data_dir=.e2e-data || true) && ` +
          `${PYTHON} CouchPotato.py --data_dir=.e2e-data`,
        url: process.env.CP_TEST_URL || 'http://localhost:5050',
        timeout: 120_000,
        reuseExistingServer: true,
      },
});
