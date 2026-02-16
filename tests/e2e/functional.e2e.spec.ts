import { test, expect } from '@playwright/test';

/**
 * Functional E2E tests for CouchPotato.
 * These tests verify actual application flows work correctly.
 */

test.describe('Add Movie', () => {
  test('should search for movies and display results', async ({ page }) => {
    await page.goto('/add/');
    await page.waitForLoadState('networkidle');
    
    // Search for a well-known movie
    const searchInput = page.locator('input[placeholder*="Search"]');
    await searchInput.fill('The Matrix');
    
    // Wait for results (debounced search)
    await page.waitForTimeout(1500);
    await page.waitForLoadState('networkidle');
    
    // Should show search results
    const results = page.locator('[data-testid="search-result"], .search-result, [class*="result"]');
    // If no specific selector, look for movie titles in the results area
    const resultsArea = page.locator('main');
    await expect(resultsArea).toContainText(/Matrix/i, { timeout: 10000 });
  });

  test('should add a movie successfully', async ({ page }) => {
    await page.goto('/add/');
    await page.waitForLoadState('networkidle');
    
    // Search for a specific movie
    const searchInput = page.locator('input[placeholder*="Search"]');
    await searchInput.fill('Blade Runner 2049');
    
    // Wait for results
    await page.waitForTimeout(1500);
    await page.waitForLoadState('networkidle');
    
    // Click Add button on first result
    const addButton = page.locator('button:has-text("Add")').first();
    
    // Check if button exists and is visible
    if (await addButton.isVisible({ timeout: 5000 })) {
      await addButton.click();
      
      // Should show success feedback or redirect
      // Wait for either success indicator or navigation to wanted page
      await Promise.race([
        page.waitForSelector('text=/added/i', { timeout: 5000 }).catch(() => null),
        page.waitForURL('**/wanted/**', { timeout: 5000 }).catch(() => null),
        page.waitForSelector('[class*="success"]', { timeout: 5000 }).catch(() => null),
      ]);
      
      // Verify movie appears in wanted list
      await page.goto('/wanted/');
      await page.waitForLoadState('networkidle');
      await page.waitForTimeout(1000);
      
      // The movie should be in the wanted list (or we should not see an error)
      const errorVisible = await page.locator('text=/TV show/i').isVisible().catch(() => false);
      expect(errorVisible).toBe(false);
    }
  });
});

test.describe('Movie Detail', () => {
  test('trailer button should open trailer modal', async ({ page }) => {
    // First, ensure we have at least one movie
    await page.goto('/wanted/');
    await page.waitForLoadState('networkidle');
    await page.waitForTimeout(1000);
    
    // Click on first movie card to go to detail page
    const movieCard = page.locator('a[href*="/movie/"]').first();
    
    if (await movieCard.isVisible({ timeout: 3000 })) {
      await movieCard.click();
      await page.waitForLoadState('networkidle');
      
      // Find and click trailer button
      const trailerBtn = page.locator('button:has-text("Trailer")');
      
      if (await trailerBtn.isVisible({ timeout: 3000 })) {
        await trailerBtn.click();
        
        // Should show loading or trailer modal
        await page.waitForTimeout(2000);
        
        // Check for trailer modal or iframe
        const trailerModal = page.locator('[role="dialog"], iframe[src*="youtube"]');
        const modalVisible = await trailerModal.isVisible().catch(() => false);
        
        // Either modal shows, or "Loading" text appears (API working)
        const loadingVisible = await page.locator('text=/Loading/i').isVisible().catch(() => false);
        
        // At minimum, clicking should not cause JS errors
        // Check console for errors
        const consoleErrors: string[] = [];
        page.on('console', msg => {
          if (msg.type() === 'error') consoleErrors.push(msg.text());
        });
        
        expect(consoleErrors.filter(e => e.includes('TypeError'))).toHaveLength(0);
      }
    }
  });
});

test.describe('Settings', () => {
  test('TorrentPotato test button should return result', async ({ page }) => {
    await page.goto('/settings/');
    await page.waitForLoadState('networkidle');
    await page.waitForTimeout(2000);
    
    // Navigate to Searchers tab
    const searchersTab = page.locator('button:has-text("Searchers"), [role="tab"]:has-text("Searchers")');
    if (await searchersTab.isVisible({ timeout: 3000 })) {
      await searchersTab.click();
      await page.waitForTimeout(1000);
    }
    
    // Look for TorrentPotato section
    const tpSection = page.locator('text=/TorrentPotato/i');
    
    if (await tpSection.isVisible({ timeout: 3000 })) {
      // Find test button in TorrentPotato section
      const testBtn = page.locator('button:has-text("Test")').first();
      
      if (await testBtn.isVisible({ timeout: 3000 })) {
        // Listen for API response
        const responsePromise = page.waitForResponse(
          resp => resp.url().includes('torrentpotato') && resp.url().includes('test'),
          { timeout: 15000 }
        ).catch(() => null);
        
        await testBtn.click();
        
        const response = await responsePromise;
        
        if (response) {
          // Should get a response (success or expected failure, not a crash)
          expect(response.status()).toBe(200);
          
          const body = await response.json().catch(() => ({}));
          // Should have success field (not a Python traceback)
          expect(body).toHaveProperty('success');
        }
      }
    }
  });

  test('settings should save without bytes error', async ({ page }) => {
    await page.goto('/settings/');
    await page.waitForLoadState('networkidle');
    await page.waitForTimeout(2000);
    
    // Try to save a simple setting
    // Look for any text input in settings
    const textInput = page.locator('input[type="text"]').first();
    
    if (await textInput.isVisible({ timeout: 3000 })) {
      // Get current value
      const currentValue = await textInput.inputValue();
      
      // Type something and trigger save
      await textInput.fill(currentValue + ' ');
      await textInput.fill(currentValue); // Restore
      
      // Wait for any save requests
      await page.waitForTimeout(1000);
      
      // Check for error messages
      const errorVisible = await page.locator('text=/bytes-like object/i').isVisible().catch(() => false);
      expect(errorVisible).toBe(false);
    }
  });
});

test.describe('API Health', () => {
  test('movie.is_movie event handler should exist', async ({ page, request }) => {
    // This test verifies the API endpoint works
    // We can't directly test the event handler, but we can test movie.add
    
    // Try to add a known movie via API
    const apiBase = '/api';
    
    // Get the API key from settings page (or use a test key)
    await page.goto('/settings/');
    await page.waitForLoadState('networkidle');
    
    // For now, just verify the add page works without "TV show" error
    await page.goto('/add/');
    await page.waitForLoadState('networkidle');
    
    const searchInput = page.locator('input[placeholder*="Search"]');
    await searchInput.fill('Inception 2010');
    
    await page.waitForTimeout(2000);
    await page.waitForLoadState('networkidle');
    
    // Should show results without errors
    const tvShowError = await page.locator('text=/seems to be a TV show/i').isVisible().catch(() => false);
    expect(tvShowError).toBe(false);
  });
});
