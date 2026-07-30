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
   * ONE worker everywhere — not just on CI.
   *
   * The suite drives a SINGLE app instance whose categories and quality
   * profiles are global, mutable server state, so parallel workers create,
   * reorder and delete each other's fixtures mid-assertion. This was previously
   * `process.env.CI ? 1 : undefined`, which serialised CI but let a local run
   * use one worker per core: 21 of 142 specs failed locally
   * (categories/profiles/search/interactions) while CI was green — verified as
   * pre-existing on a clean tree, and identical before and after the change
   * that found it.
   *
   * That divergence broke the premise of the local gate (CLAUDE.md hard rule 2:
   * `make verify` must pass locally before every push). A gate that cannot pass
   * locally gets bypassed, so local must mirror CI here rather than be faster
   * than it. Fixing the specs to be independent (per-worker fixtures, or a
   * server per worker) is the better long-term answer and is tracked in
   * docs/technical-debt.md; until then, correctness beats wall-clock.
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
