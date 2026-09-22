import AxeBuilder from '@axe-core/playwright';
import { test, expect } from './fixtures';
import { expectVisualTransitionsToSettle } from './helpers';

test.describe('Visual transition settling', () => {
  test('waits for a visible finite animation to reach its rendered endpoint', async ({ page }) => {
    await page.setContent('<button id="subject">Animated control</button>');
    await page.locator('#subject').evaluate((element) => {
      const animation = element.animate(
        [{ color: 'rgb(0, 0, 0)' }, { color: 'rgb(255, 0, 0)' }],
        { duration: 400, fill: 'forwards' },
      );
    });

    await expectVisualTransitionsToSettle(page, 'synthetic animated control');

    const renderedColor = await page.locator('#subject').evaluate(
      (element) => getComputedStyle(element).color,
    );
    expect(renderedColor).toBe('rgb(255, 0, 0)');
  });

  test('does not mask a genuine settled contrast violation', async ({ page }) => {
    await page.setContent(`
      <main style="background: rgb(255, 255, 255)">
        <button id="subject" style="color: rgb(119, 119, 119); background: rgb(255, 255, 255)">
          Persistently low contrast
        </button>
      </main>
    `);

    await expectVisualTransitionsToSettle(page, 'settled low-contrast control');
    const results = await new AxeBuilder({ page })
      .include('#subject')
      .withRules(['color-contrast'])
      .analyze();

    expect(results.violations.map((violation) => violation.id)).toContain('color-contrast');
  });
});
