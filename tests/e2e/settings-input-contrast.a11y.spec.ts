import type { Locator } from '@playwright/test';
import { test, expect } from './fixtures';


async function measureBorderContrast(input: Locator) {
  return input.evaluate((element: HTMLElement) => {
    type Rgba = { r: number; g: number; b: number; a: number };

    const parse = (value: string): Rgba => {
      const match = value.match(/rgba?\(([^)]+)\)/);
      if (!match) throw new Error(`cannot parse colour ${JSON.stringify(value)}`);
      const channels = match[1].split(',').map((part) => Number.parseFloat(part.trim()));
      return {
        r: channels[0],
        g: channels[1],
        b: channels[2],
        a: channels.length === 4 ? channels[3] : 1,
      };
    };
    const over = (foreground: Rgba, background: Rgba): Rgba => ({
      r: foreground.r * foreground.a + background.r * (1 - foreground.a),
      g: foreground.g * foreground.a + background.g * (1 - foreground.a),
      b: foreground.b * foreground.a + background.b * (1 - foreground.a),
      a: 1,
    });
    const luminance = (colour: Rgba) => {
      const channel = (value: number) => {
        const srgb = value / 255;
        return srgb <= 0.04045 ? srgb / 12.92 : ((srgb + 0.055) / 1.055) ** 2.4;
      };
      return 0.2126 * channel(colour.r) + 0.7152 * channel(colour.g) + 0.0722 * channel(colour.b);
    };

    const layers: Rgba[] = [];
    let ancestor = element.parentElement;
    while (ancestor) {
      const layer = parse(window.getComputedStyle(ancestor).backgroundColor);
      if (layer.a > 0) layers.push(layer);
      if (layer.a === 1) break;
      ancestor = ancestor.parentElement;
    }
    if (layers.length === 0 || layers.at(-1)?.a !== 1) {
      throw new Error('input has no opaque ancestor backdrop');
    }

    let backdrop = layers.at(-1)!;
    for (let index = layers.length - 2; index >= 0; index -= 1) {
      backdrop = over(layers[index], backdrop);
    }
    const border = over(parse(window.getComputedStyle(element).borderTopColor), backdrop);
    const borderLuminance = luminance(border);
    const backdropLuminance = luminance(backdrop);
    return {
      ratio: (Math.max(borderLuminance, backdropLuminance) + 0.05)
        / (Math.min(borderLuminance, backdropLuminance) + 0.05),
      border: window.getComputedStyle(element).borderTopColor,
      backdrop,
    };
  });
}


async function expectCompliantBoundary(control: Locator, theme: string, kind: string) {
  await expect(control).toBeVisible();
  const measurement = await measureBorderContrast(control);

  expect(
    measurement.ratio,
    `${theme} ${kind} boundary ${measurement.border} measured ${measurement.ratio.toFixed(2)}:1 ` +
      `against ${JSON.stringify(measurement.backdrop)}; WCAG 1.4.11 requires 3:1`,
  ).toBeGreaterThanOrEqual(3);

  await control.focus();
  await expect(control).toBeFocused();
  const focusedMeasurement = await measureBorderContrast(control);
  expect(
    focusedMeasurement.border,
    'the boundary override must release the canonical accent border while the control is focused',
  ).not.toBe(measurement.border);
  expect(
    focusedMeasurement.ratio,
    `${theme} focused ${kind} boundary ${focusedMeasurement.border} measured ` +
      `${focusedMeasurement.ratio.toFixed(2)}:1; WCAG 1.4.11 requires 3:1`,
  ).toBeGreaterThanOrEqual(3);
}


for (const theme of ['dark', 'light'] as const) {
  test(`settings text inputs have a visible boundary in the ${theme} theme`, async ({ page }) => {
    await page.addInitScript((selectedTheme) => {
      localStorage.setItem('cp-theme', selectedTheme);
    }, theme);
    await page.goto('/settings/');

    await expect.poll(() => page.evaluate(() =>
      document.documentElement.classList.contains('light') ? 'light' : 'dark'
    ), { message: `Settings did not render in the ${theme} theme` }).toBe(theme);

    await expectCompliantBoundary(
      page.getByRole('textbox', { name: 'Username' }),
      theme,
      'input',
    );

    await page.getByRole('tab', { name: 'Renamer', exact: true }).click();
    await expectCompliantBoundary(
      page.locator('select.bg-white\\/\\[0\\.03\\].border-white\\/\\[0\\.06\\]:visible').first(),
      theme,
      'select',
    );
  });
}
