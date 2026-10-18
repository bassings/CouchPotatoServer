import { execFileSync } from 'node:child_process';
import { existsSync } from 'node:fs';
import AxeBuilder from '@axe-core/playwright';
import { test, expect } from './fixtures';

const PYTHON = process.env.PYTHON || (existsSync('.venv/bin/python') ? '.venv/bin/python' : 'python3');
const POSTER = Buffer.from(
  'iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mNk+A8AAQUBAScY42YAAAAASUVORK5CYII=',
  'base64',
);

// Reuse the real-template renderer, extending its library fixture with the
// status and quality text that an explicit aria-label previously concealed.
const cards = execFileSync(PYTHON, ['-c', `
import copy
import runpy
renderer = runpy.run_path('tests/e2e/render_poster_fallbacks.py')
context = renderer['SURFACES']['library'][1]
wanted = context['movies'][0]
wanted['_id'] = 'card-name-wanted'
wanted['info']['titles'] = ['Wanted fixture movie']
wanted['profile'] = {'label': 'Target HD'}
done = copy.deepcopy(wanted)
done.update(_id='card-name-done', status='done', profile={})
done['info'].update(titles=['Done fixture movie'], year=2025, images={})
review = copy.deepcopy(done)
review.update(_id='card-name-review', status='downloaded', profile={'label': 'Target HD'},
              releases=[{'status': 'done', 'quality': '1080p'}])
review['info'].update(titles=['Review fixture movie'], year=0)
context['movies'] = [wanted, done, review]
print(renderer['render']())
`], { encoding: 'utf-8' });

for (const theme of ['light', 'dark'] as const) {
  for (const width of [1280, 393]) {
    test(`movie card names include visible content at ${width}px in ${theme}`, async ({ page }) => {
      await page.setViewportSize({ width, height: 851 });
      await page.addInitScript(value => localStorage.setItem('cp-theme', value), theme);
      await page.route('http://poster.test/**', route => route.fulfill({
        status: 200, contentType: 'image/png', body: POSTER,
      }));
      await page.goto('/');
      await expect(page.locator('#movie-grid .poster-card').first()).toBeVisible();
      await expect.poll(() => page.evaluate(() =>
        document.documentElement.classList.contains('light') ? 'light' : 'dark',
      )).toBe(theme);
      await page.locator('#main-content').evaluate((main, html) => {
        const fixture = document.createElement('div');
        fixture.id = 'card-name-fixture';
        const rendered = new DOMParser().parseFromString(html, 'text/html');
        fixture.append(...rendered.body.childNodes);
        main.append(fixture);
      }, cards);

      const fixture = page.locator('#card-name-fixture');
      const library = fixture.locator('[data-poster-surface="library"]');
      const wanted = library.locator('[data-movie-id="card-name-wanted"] > a');
      await expect(wanted.locator('img')).toHaveJSProperty('naturalWidth', 1);
      await expect(wanted).toHaveAccessibleName('wanted Target HD Wanted fixture movie 2026');
      await expect(library.locator('[data-movie-id="card-name-done"] > a'))
        .toHaveAccessibleName('No poster done Done fixture movie 2025');
      await expect(library.locator('[data-movie-id="card-name-review"] > a'))
        .toHaveAccessibleName('No poster downloaded / review Target HD Downloaded: 1080p Review fixture movie TBA');
      await expect(fixture.locator('[data-poster-surface="charts"] button.poster-card'))
        .toHaveAccessibleName('chart View Details Charts fallback movie 2026');
      await expect(fixture.locator('[data-poster-surface="suggestions"] button.poster-card'))
        .toHaveAccessibleName('View Details Suggestions fallback movie 2026');
      await expect(fixture.locator('[data-poster-surface="search"] button[onclick]'))
        .toHaveAccessibleName('View Details Search fallback movie (2026)');

      const scan = await new AxeBuilder({ page })
        .include('#card-name-fixture')
        .withRules(['label-content-name-mismatch'])
        .analyze();
      expect(scan.violations).toEqual([]);
    });
  }
}
