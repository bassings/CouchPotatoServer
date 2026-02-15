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
});
