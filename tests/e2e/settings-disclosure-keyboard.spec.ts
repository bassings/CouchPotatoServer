import {test, expect} from './fixtures';

for (const theme of ['light', 'dark'] as const) {
  for (const width of [393, 1280]) {
    test(`provider disclosure supports keyboard use in ${theme} at ${width}px`, async ({page}) => {
      await page.setViewportSize({width, height: 850});
      await page.addInitScript(value => localStorage.setItem('cp-theme', value), theme);
      await page.goto('/settings/');
      await page.getByRole('tab', {name: 'Searchers', exact: true}).click();
      const disclosure = page.getByRole('button', {name: 'Newznab', exact: true});
      await expect(disclosure).toBeVisible();
      await expect(disclosure).toHaveAttribute('aria-expanded', 'true');
      const target = await disclosure.getAttribute('aria-controls');
      expect(target).toBeTruthy();
      const options = page.locator(`[id="${target}"]`);
      await expect(options).toBeVisible();
      await disclosure.focus();
      await page.keyboard.press('Enter');
      await expect(disclosure).toHaveAttribute('aria-expanded', 'false');
      await expect(options).toBeHidden();
      await expect(disclosure).toBeFocused();
      await page.keyboard.press('Space');
      await expect(disclosure).toHaveAttribute('aria-expanded', 'true');
      await expect(options).toBeVisible();
      await expect(disclosure).toBeFocused();
      const bounds = await disclosure.boundingBox();
      expect(bounds).not.toBeNull();
      expect(bounds!.height).toBeGreaterThanOrEqual(44);
      expect(bounds!.x).toBeGreaterThanOrEqual(0);
      expect(bounds!.x + bounds!.width).toBeLessThanOrEqual(width);
      await expect(disclosure.locator('button')).toHaveCount(0);
      await expect(page.getByRole('switch', {name: 'Enable Newznab', exact: true})).toBeVisible();
    });
  }
}

test('the phone navigation closes with Escape and retains pointer dismissal', async ({page}) => {
  await page.setViewportSize({width: 393, height: 850});
  await page.goto('/settings/');
  const toggle = page.getByRole('button', {name: 'Toggle navigation menu'});
  const navigation = page.getByRole('navigation', {name: 'Mobile menu', exact: true});
  await toggle.focus();
  await page.keyboard.press('Enter');
  await expect(navigation).toBeVisible();
  await navigation.getByRole('link').first().focus();
  await page.keyboard.press('Escape');
  await expect(navigation).toBeHidden();
  await expect(toggle).toBeFocused();
  await toggle.click();
  await expect(navigation).toBeVisible();
  await page.locator('[x-show="mobileMenu"][aria-hidden="true"]').click({position: {x: 10, y: 100}});
  await expect(navigation).toBeHidden();
});
