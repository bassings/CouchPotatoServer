import type { Locator, Page } from '@playwright/test';
import { test, expect } from './fixtures';
import { mockSettingsSave } from './helpers';

type TargetMeasurement = {
  width: number;
  height: number;
  intersectingTargets: string[];
};

async function measureTarget(toggle: Locator): Promise<TargetMeasurement> {
  return toggle.evaluate((element: HTMLElement) => {
    const rect = element.getBoundingClientRect();
    const centreX = rect.left + rect.width / 2;
    const centreY = rect.top + rect.height / 2;
    const candidates = document.querySelectorAll('*');
    const intersectingTargets: string[] = [];
    for (const candidate of candidates) {
      const pointerTarget = candidate.matches(
        'a[href], button, input, select, textarea, [role="button"], [role="switch"], [role="link"], [tabindex]:not([tabindex="-1"])',
      ) || candidate.hasAttribute('@click');
      if (!pointerTarget || candidate === element || element.contains(candidate)) continue;
      if (candidate.matches(':disabled')) continue;
      const style = getComputedStyle(candidate);
      if (style.display === 'none' || style.visibility === 'hidden' || style.pointerEvents === 'none') continue;
      const other = candidate.getBoundingClientRect();
      if (other.width <= 0 || other.height <= 0) continue;

      // WCAG 2.5.8: a centred 24px circle may touch, but not intersect,
      // another target or another undersized target's own 24px circle.
      const otherCentreX = other.left + other.width / 2;
      const otherCentreY = other.top + other.height / 2;
      const distance = other.width < 23.99 || other.height < 23.99
        ? Math.hypot(centreX - otherCentreX, centreY - otherCentreY) - 12
        : Math.hypot(
          centreX - Math.max(other.left, Math.min(centreX, other.right)),
          centreY - Math.max(other.top, Math.min(centreY, other.bottom)),
        );
      if (distance < 11.99) {
        intersectingTargets.push(`${candidate.tagName.toLowerCase()}[role=${candidate.getAttribute('role') ?? ''}] ` +
          `at ${other.left.toFixed(1)},${other.top.toFixed(1)} ${other.width.toFixed(1)}×${other.height.toFixed(1)} ` +
          `versus switch ${rect.left.toFixed(1)},${rect.top.toFixed(1)}`);
      }
    }
    return { width: rect.width, height: rect.height, intersectingTargets };
  });
}

async function assertSwitchTargets(scope: Locator, expectedNames: string[], context: string): Promise<void> {
  for (const name of expectedNames) {
    await expect(scope.getByRole('switch', { name, exact: true }), `${context}: missing ${name}`).toBeVisible();
  }
  const switches = scope.locator('[role="switch"]:visible');
  const names = await switches.evaluateAll((nodes) => nodes.map((node) => node.getAttribute('aria-label') ?? ''));
  expect(names.slice().sort(), `${context}: unexpected switch set`).toEqual(expectedNames.slice().sort());
  for (const name of expectedNames) {
    const toggle = scope.getByRole('switch', { name, exact: true });
    await toggle.evaluate((element) => element.scrollIntoView({ block: 'center', inline: 'nearest' }));
    await expect(toggle).toBeInViewport();
    const measurement = await measureTarget(toggle);
    const largeEnough = measurement.width >= 23.99 && measurement.height >= 23.99;
    expect(
      largeEnough || measurement.intersectingTargets.length === 0,
      `${context}: ${name} target ${measurement.width.toFixed(2)}×${measurement.height.toFixed(2)} ` +
      `intersects ${measurement.intersectingTargets.join(', ')}`,
    ).toBe(true);
  }
}

async function mockBooleanSettingsSave(page: Page): Promise<void> {
  await mockSettingsSave(page);
  await page.route('**/settings.save/**', async (route) => {
    const params = new URLSearchParams(route.request().postData() ?? '');
    await route.fulfill({
      status: 200,
      contentType: 'application/json',
      body: JSON.stringify({ success: true, value: params.get('value') }),
    });
  });
}

test('spacing guard detects a crowded switch and clears after restoration', async ({ page }) => {
  await page.setViewportSize({ width: 393, height: 850 });
  await page.goto('/wizard/');
  await page.getByRole('button', { name: 'Continue' }).click();
  await page.getByRole('button', { name: 'Skip' }).click();
  await page.getByRole('button', { name: /^Both/ }).click();
  const toggle = page.getByRole('switch', { name: 'Enable BinSearch' });
  await toggle.evaluate((element) => element.scrollIntoView({ block: 'center' }));
  await toggle.evaluate((element) => {
    const rect = element.getBoundingClientRect();
    const row = element.parentElement;
    if (!row) throw new Error('BinSearch switch has no row');
    const rowRect = row.getBoundingClientRect();
    row.style.position = 'relative';
    const neighbour = document.createElement('button');
    neighbour.type = 'button';
    neighbour.setAttribute('aria-label', 'Crowded neighbour');
    neighbour.dataset.testid = 'crowded-neighbour';
    Object.assign(neighbour.style, {
      position: 'absolute', left: `${rect.right - rowRect.left - 8}px`,
      top: `${rect.top - rowRect.top}px`,
      width: '16px', height: '16px', zIndex: '1000',
    });
    row.append(neighbour);
  });
  await expect(assertSwitchTargets(toggle.locator('..'), ['Enable BinSearch'], 'crowded guard'))
    .rejects.toThrow(/intersects button/);
  await page.getByTestId('crowded-neighbour').evaluate((element) => {
    const row = element.parentElement;
    element.remove();
    if (row) row.style.position = '';
  });
  await assertSwitchTargets(toggle.locator('..'), ['Enable BinSearch'], 'restored guard');
});

for (const theme of ['light', 'dark'] as const) {
  for (const width of [1280, 393] as const) {
    test(`settings switches satisfy target size or spacing at ${width}px in ${theme}`, async ({ page }) => {
      await mockBooleanSettingsSave(page);
      await page.setViewportSize({ width, height: 850 });
      await page.addInitScript((value) => localStorage.setItem('cp-theme', value), theme);
      await page.goto('/settings/');
      const header = page.getByRole('switch', { name: 'Show advanced settings' });
      await assertSwitchTargets(header.locator('..'), ['Show advanced settings'], `${width}px ${theme} settings header`);
      await expect(header).toBeVisible();

      await page.getByRole('tab', { name: 'Searchers' }).click();
      const card = page.locator('.bg-cp-card', { has: page.getByRole('heading', { name: 'Newznab', exact: true }) });
      await expect(card).toBeVisible();
      const enabler = card.getByRole('switch', { name: 'Enable Newznab' });
      await expect(enabler).toBeVisible();
      if ((await enabler.getAttribute('aria-checked')) !== 'true') {
        await enabler.click();
        await expect(enabler).toHaveAttribute('aria-checked', 'true');
      }
      const rowCount = await card.locator('[role="switch"]:visible').count();
      expect(rowCount, 'Newznab card should expose its enabler and seeded combined rows').toBeGreaterThan(1);
      const names = ['Enable Newznab', ...Array.from({ length: rowCount - 1 }, (_, i) => `Enable row ${i + 1}`)];
      await assertSwitchTargets(card, names, `${width}px ${theme} Newznab card`);
      const visual = await enabler.evaluate((element) => {
        const style = getComputedStyle(element);
        const knob = element.querySelector('span');
        return {
          pointerHeight: element.getBoundingClientRect().height,
          paintedHeight: element.clientHeight - parseFloat(style.paddingTop) - parseFloat(style.paddingBottom),
          backgroundClip: style.backgroundClip,
          knobTop: knob ? getComputedStyle(knob).top : null,
        };
      });
      expect(visual, `${width}px ${theme} provider switch keeps its 16px painted track`).toEqual({
        pointerHeight: 24, paintedHeight: 16, backgroundClip: 'content-box', knobTop: '6px',
      });
      await enabler.focus();
      await expect(enabler).toBeFocused();
      await page.keyboard.press('Space');
      await expect(enabler).toHaveAttribute('aria-checked', 'false');
      await page.keyboard.press('Space');
      await expect(enabler).toHaveAttribute('aria-checked', 'true');
      await enabler.click({ position: { x: 16, y: 2 } });
      await expect(enabler).toHaveAttribute('aria-checked', 'false');
      await enabler.click({ position: { x: 16, y: 2 } });
      await expect(enabler).toHaveAttribute('aria-checked', 'true');
      await expect(card.getByRole('switch', { name: 'Enable row 1' })).toBeVisible();
    });

    test(`wizard switches satisfy target size or spacing at ${width}px in ${theme}`, async ({ page }) => {
      await mockSettingsSave(page);
      await page.setViewportSize({ width, height: 850 });
      await page.addInitScript((value) => localStorage.setItem('cp-theme', value), theme);
      await page.goto('/wizard/');
      await expect(page.getByRole('heading', { name: 'Welcome to CouchPotato' })).toBeVisible();
      await page.getByRole('button', { name: 'Continue' }).click();
      await expect(page.getByRole('heading', { name: 'Server Security' })).toBeVisible();
      await page.getByRole('button', { name: 'Skip' }).click();
      await expect(page.getByRole('heading', { name: 'Where to Search' })).toBeVisible();
      await page.getByRole('button', { name: /^Both/ }).click();
      await page.getByRole('button', { name: /Private Trackers/ }).click();
      const providers = page.locator('[x-show="currentStep === 2"]');
      await assertSwitchTargets(providers, [
        'Enable Newznab Indexers', 'Enable BinSearch', 'Enable ThePirateBay',
        'Enable YTS', 'Enable Jackett / TorrentPotato',
        'Enable PassThePopcorn', 'Enable HDBits', 'Enable IPTorrents',
        'Enable TorrentLeech', 'Enable TorrentDay', 'Enable AlphaRatio',
      ], `${width}px ${theme} wizard providers`);
      await page.getByRole('button', { name: 'Continue' }).click();
      await expect(page.getByRole('heading', { name: 'Download Clients' })).toBeVisible();
      const downloaders = page.locator('[x-show="currentStep === 3"]');
      await assertSwitchTargets(downloaders, ['Enable Black Hole'], `${width}px ${theme} wizard downloaders`);
      await page.getByRole('button', { name: 'Continue' }).click();
      await expect(page.getByRole('heading', { name: 'Movie Library' })).toBeVisible();
      const library = page.locator('[x-show="currentStep === 4"]');
      await assertSwitchTargets(library, ['Enable Automatic Renaming'], `${width}px ${theme} wizard library`);
    });
  }
}
