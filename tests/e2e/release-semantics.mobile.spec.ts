import { test, expect } from './fixtures';


const RELEASE_MOVIE_ID = 'e2e-seed-movie-001';
const PROFILE_HIDDEN_MOVIE_ID = 'e2e-seed-movie-009';


for (const theme of ['light', 'dark'] as const) {
  test(`the overflowing releases table scrolls from the keyboard in the ${theme} theme`, async ({ page }) => {
    await page.addInitScript((value) => localStorage.setItem('cp-theme', value), theme);
    await page.goto(`/movie/${RELEASE_MOVIE_ID}`);
    await expect.poll(
      () => page.evaluate(() => document.documentElement.classList.contains('light')),
    ).toBe(theme === 'light');

    const region = page.getByRole('region', {
      name: 'Releases table, scrolls horizontally',
    });
    await expect(region).toBeVisible();

    const widths = await region.evaluate((element) => ({
      client: element.clientWidth,
      scroll: element.scrollWidth,
    }));
    expect(
      widths.scroll,
      'the fixture must genuinely overflow or keyboard scrolling is not exercised',
    ).toBeGreaterThan(widths.client);

    const viewportWidth = page.viewportSize()?.width;
    expect(viewportWidth).toBeDefined();
    const regionBounds = await region.boundingBox();
    expect(regionBounds).not.toBeNull();
    expect(regionBounds!.x).toBeGreaterThanOrEqual(0);
    expect(regionBounds!.x + regionBounds!.width).toBeLessThanOrEqual(viewportWidth!);
    const documentBefore = await page.evaluate(() => ({
      scrollWidth: document.documentElement.scrollWidth,
      scrollX: window.scrollX,
    }));

    await page.locator('#rel-status').focus();
    await page.keyboard.press('Tab');
    await expect(region).toBeFocused();
    const focusStyle = await region.evaluate((element) => {
      const style = getComputedStyle(element);
      return {
        outlineStyle: style.outlineStyle,
        outlineWidth: Number.parseFloat(style.outlineWidth),
        outlineColor: style.outlineColor,
      };
    });
    const transparentOutline = focusStyle.outlineColor === 'transparent' ||
      /^rgba\([^)]*,\s*0(?:\.0+)?\)$/.test(focusStyle.outlineColor);
    expect(
      focusStyle.outlineStyle !== 'none' &&
        focusStyle.outlineWidth > 0 &&
        !transparentOutline,
      `focused release region has no visible indicator: ${JSON.stringify(focusStyle)}`,
    ).toBe(true);

    expect(await region.evaluate((element) => element.scrollLeft)).toBe(0);
    await page.keyboard.press('ArrowRight');
    await expect.poll(
      () => region.evaluate((element) => element.scrollLeft),
      { message: 'ArrowRight did not scroll the focused release region' },
    ).toBeGreaterThan(0);
    await expect.poll(() => page.evaluate(() => ({
      scrollWidth: document.documentElement.scrollWidth,
      scrollX: window.scrollX,
    }))).toEqual(documentBefore);

    await page.keyboard.press('Tab');
    await expect(page.locator('#sort-name')).toBeFocused();
  });
}


test('profile-hidden releases expose the output element as a status', async ({ page }) => {
  await page.goto(`/partial/movie/${PROFILE_HIDDEN_MOVIE_ID}/releases`);
  const status = page.getByRole('status');
  await expect(status).toHaveText('No releases match the selected profile qualities.');
  await expect(status).toHaveJSProperty('tagName', 'OUTPUT');
});
