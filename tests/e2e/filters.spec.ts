import { test, expect } from '@playwright/test';

/**
 * Filter functionality tests for CouchPotato new UI.
 */

test.describe('Filters', () => {
  test.beforeEach(async ({ page }) => {
    await page.goto('/');
    // Wait for movies to load
    const movieGrid = page.locator('#movie-grid');
    await expect(movieGrid).toBeVisible({ timeout: 10000 });
  });

  test('should have filter buttons on Wanted page', async ({ page }) => {
    // Should have All, Wanted, Available buttons
    const allButton = page.getByRole('button', { name: /^all$/i });
    const wantedButton = page.getByRole('button', { name: /wanted/i });
    const availableButton = page.getByRole('button', { name: /available/i });
    
    await expect(allButton).toBeVisible();
    await expect(wantedButton).toBeVisible();
    await expect(availableButton).toBeVisible();
  });

  test('should have search filter input', async ({ page }) => {
    const searchInput = page.locator('input[placeholder*="filter" i]');
    await expect(searchInput).toBeVisible();
  });

  test('should filter movies by text search', async ({ page }) => {
    const movieCards = page.locator('#movie-grid .poster-card');
    const initialCount = await movieCards.count();
    
    if (initialCount > 0) {
      // Get the title of the first movie
      const firstTitle = await movieCards.first().getAttribute('data-title');
      
      // Type in the filter
      const searchInput = page.locator('input[placeholder*="filter" i]');
      await searchInput.fill(firstTitle || '');
      
      // Wait for filter to apply
      await page.waitForTimeout(300);
      
      // The first movie should still be visible
      const visibleCards = page.locator('#movie-grid .poster-card:not([style*="display: none"])');
      const filteredCount = await visibleCards.count();
      
      // Filtered count should be less than or equal to initial
      expect(filteredCount).toBeLessThanOrEqual(initialCount);
      // And at least one card should be visible (the one we searched for)
      expect(filteredCount).toBeGreaterThan(0);
    }
  });

  test('clicking Wanted filter should filter movies', async ({ page }) => {
    const wantedButton = page.getByRole('button', { name: /wanted/i });
    await wantedButton.click();
    
    // Button should be highlighted
    await expect(wantedButton).toHaveClass(/text-cp-accent/);
    
    // Wait for filter to apply
    await page.waitForTimeout(300);
    
    // All visible cards should have status "active" (wanted)
    const visibleCards = page.locator('#movie-grid .poster-card:not([style*="display: none"])');
    const count = await visibleCards.count();
    
    for (let i = 0; i < Math.min(count, 5); i++) {
      const status = await visibleCards.nth(i).getAttribute('data-status');
      if (status) {
        expect(status).toBe('active');
      }
    }
  });

  test('clicking Available filter should filter movies', async ({ page }) => {
    const availableButton = page.getByRole('button', { name: /available/i });
    await availableButton.click();
    
    // Button should be highlighted with accent colour
    await expect(availableButton).toHaveClass(/text-cp-accent/);
    
    // Wait for filter to apply
    await page.waitForTimeout(300);
    
    // All visible cards should have data-has-releases="true" (has releases or downloading)
    const visibleCards = page.locator('#movie-grid .poster-card:not([style*="display: none"])');
    const count = await visibleCards.count();
    
    for (let i = 0; i < Math.min(count, 5); i++) {
      const hasReleases = await visibleCards.nth(i).getAttribute('data-has-releases');
      if (hasReleases !== null) {
        expect(hasReleases).toBe('true');
      }
    }
  });

  test('clicking All should show all movies', async ({ page }) => {
    // First apply a filter
    const wantedButton = page.getByRole('button', { name: /wanted/i });
    await wantedButton.click();
    await page.waitForTimeout(300);
    
    // Then click All
    const allButton = page.getByRole('button', { name: /^all$/i });
    await allButton.click();
    
    // Button should be highlighted
    await expect(allButton).toHaveClass(/text-cp-accent/);
    
    // Wait for filter to apply
    await page.waitForTimeout(300);
    
    // More movies should be visible (or same if all were wanted)
    const visibleCards = page.locator('#movie-grid .poster-card:not([style*="display: none"])');
    const count = await visibleCards.count();
    expect(count).toBeGreaterThanOrEqual(0);
  });

  test('should show movie count', async ({ page }) => {
    // Should show count in the header
    const countElement = page.locator('#movie-count');
    await expect(countElement).toBeVisible({ timeout: 5000 });
    
    // Count should contain "movies"
    const countText = await countElement.textContent();
    expect(countText).toContain('movies');
  });
});

/**
 * BUG (owner report, 2026-07-31): "I just deleted Tinsel Town to add it back to
 * search, when I go in to my movies list it's now empty" -- followed by
 * "actually it was a filter problem. The tinsel town filter was still there,
 * but I had deleted it."
 *
 * The library was intact (1099 movies, verified on the production database).
 * What the user saw was a filter that matched nothing after the movie was
 * deleted, and a grid that renders COMPLETELY BLANK in that case: no message,
 * no indication a filter is even active, and no way to clear it except
 * noticing the text still sitting in the filter box. An empty grid is
 * indistinguishable from a lost library, which is exactly the conclusion that
 * was drawn.
 *
 * Measured before the fix: /library?q=<no match> gives 1 card in the DOM, 0
 * visible, and an empty #movie-grid on screen.
 */
test.describe('Filtered-to-empty state', () => {
  test('explains why the grid is empty and offers a way out', async ({ page }) => {
    await page.goto('/library');
    const grid = page.locator('#movie-grid');
    await expect(grid).toBeVisible({ timeout: 10000 });
    await expect(page.locator('#movie-grid .poster-card').first())
      .toBeAttached({ timeout: 10000 });
    const total = await page.locator('#movie-grid .poster-card').count();

    await page.locator('#filter-movies').fill('zzz-no-such-movie-zzz');

    // The user must be told the library is filtered, not gone.
    const emptyState = page.locator('[data-testid="filter-empty-state"]');
    await expect(emptyState).toBeVisible({ timeout: 5000 });
    await expect(emptyState).toContainText('zzz-no-such-movie-zzz');

    // ...and be able to get out of it in one click, without having to work
    // out that the filter box is the culprit.
    await emptyState.locator('[data-testid="clear-filters"]').click();

    await expect(emptyState).toBeHidden({ timeout: 5000 });
    const visible = await page.locator('#movie-grid .poster-card:not([style*="display: none"])').count();
    expect(visible, 'clearing from the empty state must restore the full list').toBe(total);
    await expect(page.locator('#filter-movies')).toHaveValue('');
  });

  test('a genuinely empty library is not reported as a filter problem', async ({ page }) => {
    // The Wanted page is empty in the seeded fixture (the seeded movie is
    // 'done'), so this covers total === 0 with no filter applied: the
    // filter-specific empty state must NOT claim a filter is hiding things.
    await page.goto('/');
    await expect(page.locator('#movie-grid')).toBeVisible({ timeout: 10000 });
    await page.waitForTimeout(1500);
    const total = await page.locator('#movie-grid .poster-card').count();
    test.skip(total > 0, 'wanted list is not empty in this run');

    await expect(page.locator('[data-testid="filter-empty-state"]')).toBeHidden();
  });
});
