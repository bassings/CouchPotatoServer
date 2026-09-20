import { execFileSync } from 'node:child_process';
import { existsSync, readFileSync } from 'node:fs';

import { expect, test, type Page, type Route, type TestInfo } from '@playwright/test';


const PYTHON = process.env.PYTHON || (existsSync('.venv/bin/python') ? '.venv/bin/python' : 'python3');
const SURFACES = ['charts', 'search', 'suggestions', 'library'] as const;
const ONE_PIXEL_PNG = Buffer.from(
  'iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mNk+A8AAQUBAScY42YAAAAASUVORK5CYII=',
  'base64',
);


function renderProductionMarkup(testInfo: TestInfo): string {
  const output = testInfo.outputPath('poster-fallbacks.html');
  execFileSync(PYTHON, ['tests/e2e/render_poster_fallbacks.py', output], {
    stdio: 'pipe',
  });
  return readFileSync(output, 'utf-8');
}


async function loadWithHeldPosterRequests(page: Page, html: string): Promise<Map<string, Route>> {
  const pending = new Map<string, Route>();
  await page.route('http://poster.test/**', (route) => {
    const name = new URL(route.request().url()).pathname.split('/').pop()!.replace('.png', '');
    pending.set(name, route);
  });
  await page.setContent('<main id="poster-fixture"></main>');
  await page.locator('#poster-fixture').evaluate((target, productionHtml) => {
    const parsed = new DOMParser().parseFromString(productionHtml, 'text/html');
    target.append(...parsed.body.childNodes);
  }, html);

  for (const surface of SURFACES) {
    const root = page.locator(`[data-poster-surface="${surface}"]`);
    const image = root.locator('img[onerror]');
    await image.scrollIntoViewIfNeeded();
    await expect.poll(
      () => pending.has(surface),
      { message: `${surface} poster request never started` },
    ).toBe(true);
    await expect(image).not.toHaveCSS('display', 'none');
    await expect(image.locator('xpath=following-sibling::*[1]')).toHaveCSS('display', 'none');
  }
  return pending;
}


test('successful poster requests leave every production fallback hidden', async ({ page }, testInfo) => {
  const errors: Error[] = [];
  page.on('pageerror', (error) => errors.push(error));
  const pending = await loadWithHeldPosterRequests(page, renderProductionMarkup(testInfo));

  await Promise.all([...pending.values()].map((route) => route.fulfill({
    status: 200,
    contentType: 'image/png',
    body: ONE_PIXEL_PNG,
  })));

  for (const surface of SURFACES) {
    const image = page.locator(`[data-poster-surface="${surface}"] img[onerror]`);
    await expect.poll(
      () => image.evaluate((element: HTMLImageElement) => ({
        complete: element.complete,
        naturalWidth: element.naturalWidth,
        naturalHeight: element.naturalHeight,
      })),
      { message: `${surface} poster did not decode successfully` },
    ).toEqual({ complete: true, naturalWidth: 1, naturalHeight: 1 });
    await expect(image).not.toHaveCSS('display', 'none');
    await expect(image.locator('xpath=following-sibling::*[1]')).toHaveCSS('display', 'none');
  }
  expect(errors).toEqual([]);
});


test('failed poster requests reveal each real template fallback without changing its control', async ({ page }, testInfo) => {
  const errors: Error[] = [];
  page.on('pageerror', (error) => errors.push(error));
  const pending = await loadWithHeldPosterRequests(page, renderProductionMarkup(testInfo));

  await Promise.all([...pending.values()].map((route) => route.abort('failed')));

  for (const surface of SURFACES) {
    const root = page.locator(`[data-poster-surface="${surface}"]`);
    const image = root.locator('img[onerror]');
    const fallback = image.locator('xpath=following-sibling::*[1]');
    const control = root.locator('button[aria-label], a[aria-label]').first();
    await expect(image).toHaveCSS('display', 'none');
    await expect(fallback).toHaveCSS('display', 'flex');
    await expect(control).toHaveAttribute('aria-label', /fallback movie/i);
    await control.focus();
    await expect(control).toBeFocused();
  }
  expect(errors).toEqual([]);
});
