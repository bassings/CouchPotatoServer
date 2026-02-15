import { test, expect } from '@playwright/test';

/**
 * Search functionality tests for CouchPotato new UI.
 */

test.describe('Movie Search', () => {
  test.beforeEach(async ({ page }) => {
    await page.goto('/add/');
    // Wait for page to load
    await expect(page.locator('h1')).toContainText('Add');
  });

  test('should have a search input', async ({ page }) => {
    const searchInput = page.locator('input[type="text"]').first();
    await expect(searchInput).toBeVisible();
    await expect(searchInput).toHaveAttribute('placeholder', /search/i);
  });

  test('should show search results when typing', async ({ page }) => {
    const searchInput = page.locator('input[type="text"]').first();
    await searchInput.fill('The Matrix');
    
    // Wait for htmx to load results (debounced)
    await page.waitForTimeout(500);
    
    // Check for results container
    const resultsContainer = page.locator('#search-results');
    await expect(resultsContainer).toBeVisible({ timeout: 10000 });
    
    // Should have some movie cards
    const movieCards = resultsContainer.locator('.rounded-md');
    await expect(movieCards.first()).toBeVisible({ timeout: 10000 });
  });

  test('should show year and identifying info for search results (DEF-007)', async ({ page }) => {
    const searchInput = page.locator('input[type="text"]').first();
    await searchInput.fill('The Matrix');
    
    // Wait for results
    await page.waitForTimeout(500);
    const resultsContainer = page.locator('#search-results');
    await expect(resultsContainer).toBeVisible({ timeout: 10000 });
    
    // First result should have year visible (not empty parentheses)
    const firstCard = resultsContainer.locator('.rounded-md').first();
    await expect(firstCard).toBeVisible({ timeout: 5000 });
    
    // Year should not show empty parentheses (DEF-005)
    const yearText = await firstCard.locator('p').first().textContent();
    expect(yearText).not.toBe('');
    expect(yearText).not.toBe('()');
  });

  test('should have Add button on search results', async ({ page }) => {
    const searchInput = page.locator('input[type="text"]').first();
    await searchInput.fill('Inception');
    
    // Wait for results
    await page.waitForTimeout(500);
    const resultsContainer = page.locator('#search-results');
    await expect(resultsContainer).toBeVisible({ timeout: 10000 });
    
    // Should have Add button
    const addButton = resultsContainer.locator('button').filter({ hasText: 'Add' }).first();
    await expect(addButton).toBeVisible({ timeout: 5000 });
  });

  test('should show profile selector in search results', async ({ page }) => {
    const searchInput = page.locator('input[type="text"]').first();
    await searchInput.fill('Inception');
    
    // Wait for results
    await page.waitForTimeout(500);
    const resultsContainer = page.locator('#search-results');
    await expect(resultsContainer).toBeVisible({ timeout: 10000 });
    
    // Should have profile selector
    const profileSelector = resultsContainer.locator('select').first();
    await expect(profileSelector).toBeVisible({ timeout: 5000 });
  });
});
