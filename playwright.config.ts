import { defineConfig, devices } from '@playwright/test';

/**
 * Playwright configuration for CouchPotato E2E tests.
 * See https://playwright.dev/docs/test-configuration
 *
 * T1.7: there is no shared `webServer` any more. Every worker starts its
 * OWN CouchPotato server, on its own port, against its own data dir --
 * see tests/e2e/fixtures.ts, which every spec now imports `test`/`expect`
 * from instead of '@playwright/test' directly. That removes the need for
 * `workers: 1` (kept a long history here explaining why parallel used to
 * be unsafe; the reason -- one shared server -- no longer applies, so the
 * explanation went with it rather than being amended in place) and for
 * `test.describe.configure({ mode: 'serial' })` on categories/profiles,
 * which existed to protect that same shared server.
 */
export default defineConfig({
  testDir: './tests/e2e',
  /* Run tests in files in parallel */
  fullyParallel: true,
  /* Fail the build on CI if you accidentally left test.only in the source code. */
  forbidOnly: !!process.env.CI,
  /* Retry on CI only */
  // AC-SIMP-12: parallelism was always conditional on the isolated suite
  // actually being faster AND green. Measured 2026-08-05 on the T1.7
  // tree: 0 of 5 parallel runs passed, dominated by 'no movie card in
  // the Wanted grid'. Per-worker isolation cannot remove cross-file
  // coupling when Playwright runs fewer workers than spec files, so
  // two coupled specs still share a worker. The isolation lands; the
  // parallelism does not, until that coupling is fixed.
  workers: 1,
  retries: process.env.CI ? 2 : 0,
  /* Reporter to use. See https://playwright.dev/docs/test-reporters */
  reporter: [
    ['html', { open: 'never' }],
    ['list']
  ],
  /* Shared settings for all the projects below. `baseURL` is overridden
   * per worker by tests/e2e/fixtures.ts; this default is only ever seen
   * before that fixture initialises. */
  use: {
    /* Collect trace when retrying the failed test. */
    trace: 'on-first-retry',

    /* Screenshot on failure */
    screenshot: 'only-on-failure',
  },

  /* Configure projects for major browsers */
  projects: [
    {
      name: 'chromium',
      /*
       * Desktop projects must NOT run the small-screen specs. They pass at
       * 1280px, where their assertions cannot fail -- a green that means
       * nothing. Worse, the mobile spec's Mark-as-Done fallback mutates the
       * shared seeded movie, so running it here also pollutes the desktop run.
       * The a11y specs have their own project for the same reason.
       */
      // `isolation-*` is excluded here and runs as its own project below: the
      // pair only demonstrates anything at >= 2 workers, and this project runs
      // at workers: 1 (AC-SIMP-12). Left in, isolation-b-assert fails every
      // run by construction, because with one worker it shares that worker
      // with isolation-a-mutate and the mutation legitimately reaches it.
      testIgnore: /.*(\.(mobile|a11y)\.spec|isolation-.*\.spec)\.ts/,
      use: { ...devices['Desktop Chrome'] },
    },
    /* Accessibility tests project */
    {
      name: 'accessibility',
      testMatch: /.*\.a11y\.spec\.ts/,
      use: { ...devices['Desktop Chrome'] },
    },
    {
      /*
       * AC-QA-50's direct isolation proof, deliberately its own project.
       *
       * isolation-a-mutate creates a category and never deletes it;
       * isolation-b-assert asserts it is not visible. That demonstrates
       * something only when the two land on DIFFERENT workers, so it needs
       * at least 2. The main chromium project runs at workers: 1
       * (AC-SIMP-12), which is why this cannot simply live there.
       *
       * A separate project rather than a conditional skip, because AC-QA-52
       * measures the suite by test count with 0 skipped. A skip here would
       * silently retire the only proof that isolation works, which is exactly
       * the vacuous-guard shape this repo keeps finding in its own suite.
       *
       * Run it with `npm run test:isolation` (pins --workers=2).
       */
      name: 'isolation',
      testMatch: /.*isolation-.*\.spec\.ts/,
      use: { ...devices['Desktop Chrome'] },
    },
    /* Mobile viewport testing */
    {
      /*
       * Mobile viewport. Scoped with testMatch to `*.mobile.spec.ts` so this
       * project runs ONLY the specs written for a small screen, which keeps it
       * cheap enough to include in the gate (scripts/verify.sh).
       *
       * It previously matched every spec and was run by nothing — so the
       * mobile dimension, which AGENTS.md flags high-priority, had never been
       * exercised. The first review to check it found the restore picker
       * overflowing at 441px on a 393px device.
       */
      name: 'mobile-chrome',
      testMatch: /.*\.mobile\.spec\.ts/,
      use: { ...devices['Pixel 5'] },
    },
  ],

  /* Timeout settings */
  timeout: 30000,
  expect: {
    timeout: 5000,
  },

  // No webServer block: tests/e2e/fixtures.ts starts one server per worker,
  // identically in CI and locally (playwright.config.ts used to special-case
  // `process.env.CI` here to avoid a port clash with CI's own hand-started
  // server -- see .github/workflows/ci.yml, which no longer hand-starts one).
});
