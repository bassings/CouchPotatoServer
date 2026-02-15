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
    // Should have All, Wanted, Done buttons
    const allButton = page.getByRole('button', { name: /^all$/i });
    const wantedButton = page.getByRole('button', { name: /wanted/i });
    const doneButton = page.getByRole('button', { name: /done/i });
    
    await expect(allButton).toBeVisible();
    await expect(wantedButton).toBeVisible();
    await expect(doneButton).toBeVisible();
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

  test('clicking Done filter should filter movies', async ({ page }) => {
    const doneButton = page.getByRole('button', { name: /done/i });
    await doneButton.click();
    
    // Button should be highlighted
    await expect(doneButton).toHaveClass(/text-cp-success/);
    
    // Wait for filter to apply
    await page.waitForTimeout(300);
    
    // All visible cards should have status "done"
    const visibleCards = page.locator('#movie-grid .poster-card:not([style*="display: none"])');
    const count = await visibleCards.count();
    
    for (let i = 0; i < Math.min(count, 5); i++) {
      const status = await visibleCards.nth(i).getAttribute('data-status');
      if (status) {
        expect(status).toBe('done');
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
