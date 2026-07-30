import { defineConfig, devices } from '@playwright/test';

/**
 * Playwright configuration for CouchPotato E2E tests.
 * See https://playwright.dev/docs/test-configuration
 */
export default defineConfig({
  testDir: './tests/e2e',
  /* Run tests in files in parallel */
  fullyParallel: true,
  /* Fail the build on CI if you accidentally left test.only in the source code. */
  forbidOnly: !!process.env.CI,
  /* Retry on CI only */
  retries: process.env.CI ? 2 : 0,
  /* Opt out of parallel tests on CI. */
  workers: process.env.CI ? 1 : undefined,
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
        command: '(python scripts/seed_e2e_data.py --data_dir=.e2e-data || true) && python CouchPotato.py --data_dir=.e2e-data',
        url: process.env.CP_TEST_URL || 'http://localhost:5050',
        timeout: 120_000,
        reuseExistingServer: true,
      },
});
