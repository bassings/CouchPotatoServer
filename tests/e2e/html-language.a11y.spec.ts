import { test, expect } from './fixtures';

test('the rendered shared page declares its language on the root element', async ({ page }) => {
  await page.goto('/wizard/');
  await expect(page.getByRole('heading', { name: 'Welcome to CouchPotato' })).toBeVisible();
  expect(await page.evaluate(() => document.documentElement.lang)).toBe('en');
});
