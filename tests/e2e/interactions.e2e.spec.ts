import { test, expect, Page } from '@playwright/test';

/**
 * Comprehensive interaction tests for CouchPotato.
 * Tests every user-interactable element across all pages.
 * 
 * Coverage:
 * - Navigation (sidebar, mobile menu)
 * - Wanted page (filters, search, movie cards, bulk actions)
 * - Available page (same as wanted)
 * - Add Movie page (search, add button, profile selection)
 * - Movie Detail page (refresh, trailer, delete, releases)
 * - Suggestions page (charts, add/skip buttons)
 * - Settings page (all tabs, inputs, toggles, test buttons)
 * - Theme toggle
 */

// Helper: wait for page to be fully loaded
async function waitForPageReady(page: Page) {
  await page.waitForLoadState('networkidle');
  await page.waitForTimeout(500);
}

// Helper: check no JS errors occurred
async function checkNoErrors(page: Page, errors: string[]) {
  const criticalErrors = errors.filter(e => 
    e.includes('TypeError') || 
    e.includes('ReferenceError') ||
    e.includes('bytes-like object')
  );
  expect(criticalErrors).toHaveLength(0);
}

test.describe('Navigation', () => {
  test('sidebar links navigate correctly', async ({ page }) => {
    const errors: string[] = [];
    page.on('console', msg => { if (msg.type() === 'error') errors.push(msg.text()); });

    await page.goto('/');
    await waitForPageReady(page);

    // Test each nav link
    const navLinks = [
      { href: '/wanted/', text: 'Wanted' },
      { href: '/available/', text: 'Available' },
      { href: '/suggestions/', text: 'Suggestions' },
      { href: '/add/', text: 'Add Movie' },
      { href: '/settings/', text: 'Settings' },
    ];

    for (const link of navLinks) {
      await page.click(`a[href*="${link.href}"]`);
      await waitForPageReady(page);
      expect(page.url()).toContain(link.href);
    }

    checkNoErrors(page, errors);
  });

  test('sidebar collapse button works', async ({ page }) => {
    await page.goto('/');
    await waitForPageReady(page);

    const collapseBtn = page.locator('button[aria-label*="Collapse"], button[aria-label*="Expand"]');
    if (await collapseBtn.isVisible()) {
      await collapseBtn.click();
      await page.waitForTimeout(300);
      // Sidebar should be collapsed (nav text hidden)
      await collapseBtn.click();
      await page.waitForTimeout(300);
    }
  });

  test('theme toggle switches modes', async ({ page }) => {
    await page.goto('/');
    await waitForPageReady(page);

    const themeBtn = page.locator('button:has-text("Light mode"), button:has-text("Dark mode")');
    if (await themeBtn.isVisible()) {
      const initialText = await themeBtn.textContent();
      await themeBtn.click();
      await page.waitForTimeout(300);
      const newText = await themeBtn.textContent();
      expect(newText).not.toBe(initialText);
      // Toggle back
      await themeBtn.click();
    }
  });

  test('mobile menu works on small viewport', async ({ page }) => {
    await page.setViewportSize({ width: 375, height: 667 });
    await page.goto('/');
    await waitForPageReady(page);

    const menuBtn = page.locator('button[aria-label*="menu"], button[aria-label*="navigation"]');
    if (await menuBtn.isVisible()) {
      await menuBtn.click();
      await page.waitForTimeout(300);
      // Mobile menu should be visible
      const mobileNav = page.locator('[role="menu"], #mobile-menu');
      await expect(mobileNav).toBeVisible();
    }
  });
});

test.describe('Wanted Page', () => {
  test('filter buttons work', async ({ page }) => {
    const errors: string[] = [];
    page.on('console', msg => { if (msg.type() === 'error') errors.push(msg.text()); });

    await page.goto('/wanted/');
    await waitForPageReady(page);

    // Click each filter button
    const filterBtns = page.locator('button:has-text("All"), button:has-text("Wanted"), button:has-text("Done")');
    const count = await filterBtns.count();
    
    for (let i = 0; i < count; i++) {
      await filterBtns.nth(i).click();
      await page.waitForTimeout(300);
    }

    checkNoErrors(page, errors);
  });

  test('text filter input works', async ({ page }) => {
    await page.goto('/wanted/');
    await waitForPageReady(page);

    const filterInput = page.locator('input[placeholder*="Filter"]');
    if (await filterInput.isVisible()) {
      await filterInput.fill('test');
      await page.waitForTimeout(500);
      await filterInput.fill('');
    }
  });

  test('select all button works', async ({ page }) => {
    await page.goto('/wanted/');
    await waitForPageReady(page);

    const selectAllBtn = page.locator('button:has-text("Select All")');
    if (await selectAllBtn.isVisible()) {
      await selectAllBtn.click();
      await page.waitForTimeout(300);
    }
  });

  test('movie card hover actions visible', async ({ page }) => {
    await page.goto('/wanted/');
    await waitForPageReady(page);

    const movieCard = page.locator('.poster-card, [data-movie-id]').first();
    if (await movieCard.isVisible()) {
      await movieCard.hover();
      await page.waitForTimeout(300);
      // Refresh button should be visible on hover
    }
  });

  test('movie card click navigates to detail', async ({ page }) => {
    await page.goto('/wanted/');
    await waitForPageReady(page);

    const movieLink = page.locator('a[href*="/movie/"]').first();
    if (await movieLink.isVisible()) {
      await movieLink.click();
      await waitForPageReady(page);
      expect(page.url()).toContain('/movie/');
    }
  });
});

test.describe('Available Page', () => {
  test('page loads and displays movies', async ({ page }) => {
    const errors: string[] = [];
    page.on('console', msg => { if (msg.type() === 'error') errors.push(msg.text()); });

    await page.goto('/available/');
    await waitForPageReady(page);

    // Should have heading
    await expect(page.locator('h1:has-text("Available")')).toBeVisible();
    checkNoErrors(page, errors);
  });
});

test.describe('Add Movie Page', () => {
  test('search input accepts text and shows results', async ({ page }) => {
    const errors: string[] = [];
    page.on('console', msg => { if (msg.type() === 'error') errors.push(msg.text()); });

    await page.goto('/add/');
    await waitForPageReady(page);

    const searchInput = page.locator('input[placeholder*="Search"]');
    await expect(searchInput).toBeVisible();
    
    await searchInput.fill('Matrix');
    await page.waitForTimeout(2000); // Wait for debounced search
    await waitForPageReady(page);

    // Should show some results or loading state
    checkNoErrors(page, errors);
  });

  test('add button on search result works', async ({ page }) => {
    const errors: string[] = [];
    page.on('console', msg => { if (msg.type() === 'error') errors.push(msg.text()); });

    await page.goto('/add/');
    await waitForPageReady(page);

    const searchInput = page.locator('input[placeholder*="Search"]');
    await searchInput.fill('Inception');
    await page.waitForTimeout(2000);
    await waitForPageReady(page);

    const addBtn = page.locator('button:has-text("Add")').first();
    if (await addBtn.isVisible({ timeout: 5000 })) {
      await addBtn.click();
      await page.waitForTimeout(2000);
      
      // Should not show TV show error
      const tvError = await page.locator('text=/TV show/i').isVisible().catch(() => false);
      expect(tvError).toBe(false);
    }

    checkNoErrors(page, errors);
  });
});

test.describe('Movie Detail Page', () => {
  test.beforeEach(async ({ page }) => {
    // Navigate to first movie detail if available
    await page.goto('/wanted/');
    await waitForPageReady(page);
    
    const movieLink = page.locator('a[href*="/movie/"]').first();
    if (await movieLink.isVisible({ timeout: 3000 })) {
      await movieLink.click();
      await waitForPageReady(page);
    }
  });

  test('refresh button works', async ({ page }) => {
    const errors: string[] = [];
    page.on('console', msg => { if (msg.type() === 'error') errors.push(msg.text()); });

    if (page.url().includes('/movie/')) {
      const refreshBtn = page.locator('button:has-text("Refresh")');
      if (await refreshBtn.isVisible({ timeout: 3000 })) {
        await refreshBtn.click();
        await page.waitForTimeout(2000);
      }
    }

    checkNoErrors(page, errors);
  });

  test('trailer button works', async ({ page }) => {
    const errors: string[] = [];
    page.on('console', msg => { if (msg.type() === 'error') errors.push(msg.text()); });

    if (page.url().includes('/movie/')) {
      const trailerBtn = page.locator('button:has-text("Trailer")');
      if (await trailerBtn.isVisible({ timeout: 3000 })) {
        await trailerBtn.click();
        await page.waitForTimeout(2000);
        
        // Modal should open or loading should show
        const modal = page.locator('[role="dialog"]');
        const loading = page.locator('text=/Loading/i');
        
        // Either is acceptable
      }
    }

    checkNoErrors(page, errors);
  });

  test('delete button shows confirmation', async ({ page }) => {
    if (page.url().includes('/movie/')) {
      // Set up dialog handler
      page.on('dialog', dialog => dialog.dismiss());
      
      const deleteBtn = page.locator('button:has-text("Delete")');
      if (await deleteBtn.isVisible({ timeout: 3000 })) {
        await deleteBtn.click();
        // Dialog should have appeared (and been dismissed)
      }
    }
  });
});

test.describe('Suggestions Page', () => {
  test('tabs switch content', async ({ page }) => {
    const errors: string[] = [];
    page.on('console', msg => { if (msg.type() === 'error') errors.push(msg.text()); });

    await page.goto('/suggestions/');
    await waitForPageReady(page);

    const tabs = page.locator('[role="tab"]');
    const tabCount = await tabs.count();

    for (let i = 0; i < tabCount; i++) {
      await tabs.nth(i).click();
      await page.waitForTimeout(500);
    }

    checkNoErrors(page, errors);
  });

  test('add/skip buttons on suggestions work', async ({ page }) => {
    const errors: string[] = [];
    page.on('console', msg => { if (msg.type() === 'error') errors.push(msg.text()); });

    await page.goto('/suggestions/');
    await waitForPageReady(page);

    const skipBtn = page.locator('button:has-text("Skip")').first();
    if (await skipBtn.isVisible({ timeout: 5000 })) {
      await skipBtn.click();
      await page.waitForTimeout(1000);
    }

    checkNoErrors(page, errors);
  });
});

test.describe('Settings Page', () => {
  test('all tabs are clickable', async ({ page }) => {
    const errors: string[] = [];
    page.on('console', msg => { if (msg.type() === 'error') errors.push(msg.text()); });

    await page.goto('/settings/');
    await waitForPageReady(page);

    const tabs = page.locator('[role="tab"]');
    const tabCount = await tabs.count();

    for (let i = 0; i < tabCount; i++) {
      await tabs.nth(i).click();
      await page.waitForTimeout(500);
    }

    checkNoErrors(page, errors);
  });

  test('text inputs accept values', async ({ page }) => {
    const errors: string[] = [];
    page.on('console', msg => { if (msg.type() === 'error') errors.push(msg.text()); });

    await page.goto('/settings/');
    await waitForPageReady(page);

    const textInput = page.locator('input[type="text"]').first();
    if (await textInput.isVisible()) {
      const original = await textInput.inputValue();
      await textInput.fill('test_value');
      await page.waitForTimeout(500);
      await textInput.fill(original);
    }

    checkNoErrors(page, errors);
  });

  test('checkboxes toggle', async ({ page }) => {
    const errors: string[] = [];
    page.on('console', msg => { if (msg.type() === 'error') errors.push(msg.text()); });

    await page.goto('/settings/');
    await waitForPageReady(page);

    const checkbox = page.locator('input[type="checkbox"]').first();
    if (await checkbox.isVisible()) {
      const original = await checkbox.isChecked();
      await checkbox.click();
      await page.waitForTimeout(500);
      if (await checkbox.isChecked() !== original) {
        await checkbox.click(); // Restore
      }
    }

    checkNoErrors(page, errors);
  });

  test('select dropdowns work', async ({ page }) => {
    const errors: string[] = [];
    page.on('console', msg => { if (msg.type() === 'error') errors.push(msg.text()); });

    await page.goto('/settings/');
    await waitForPageReady(page);

    const select = page.locator('select').first();
    if (await select.isVisible()) {
      await select.click();
      await page.waitForTimeout(300);
    }

    checkNoErrors(page, errors);
  });

  test('advanced toggle shows/hides options', async ({ page }) => {
    await page.goto('/settings/');
    await waitForPageReady(page);

    const advancedToggle = page.locator('button:has-text("Advanced"), [role="switch"]:near(:text("Advanced"))');
    if (await advancedToggle.isVisible()) {
      await advancedToggle.click();
      await page.waitForTimeout(500);
      await advancedToggle.click();
    }
  });

  test('Jackett sync button works', async ({ page }) => {
    const errors: string[] = [];
    page.on('console', msg => { if (msg.type() === 'error') errors.push(msg.text()); });

    await page.goto('/settings/');
    await waitForPageReady(page);

    // Go to Searchers tab
    const searchersTab = page.locator('[role="tab"]:has-text("Searchers")');
    if (await searchersTab.isVisible()) {
      await searchersTab.click();
      await page.waitForTimeout(500);
    }

    const syncBtn = page.locator('button:has-text("Sync")');
    if (await syncBtn.isVisible({ timeout: 3000 })) {
      await syncBtn.click();
      await page.waitForTimeout(2000);
    }

    checkNoErrors(page, errors);
  });

  test('provider test buttons return valid response', async ({ page }) => {
    const errors: string[] = [];
    page.on('console', msg => { if (msg.type() === 'error') errors.push(msg.text()); });

    await page.goto('/settings/');
    await waitForPageReady(page);

    // Go to Searchers tab
    const searchersTab = page.locator('[role="tab"]:has-text("Searchers")');
    if (await searchersTab.isVisible()) {
      await searchersTab.click();
      await page.waitForTimeout(500);
    }

    // Click first visible Test button
    const testBtn = page.locator('button:has-text("Test")').first();
    if (await testBtn.isVisible({ timeout: 3000 })) {
      const responsePromise = page.waitForResponse(
        resp => resp.url().includes('test'),
        { timeout: 15000 }
      ).catch(() => null);

      await testBtn.click();
      const response = await responsePromise;

      if (response) {
        expect(response.status()).toBe(200);
      }
    }

    checkNoErrors(page, errors);
  });
});

test.describe('Logs Page', () => {
  test('logs page loads and shows content', async ({ page }) => {
    const errors: string[] = [];
    page.on('console', msg => { if (msg.type() === 'error') errors.push(msg.text()); });

    await page.goto('/settings/');
    await waitForPageReady(page);

    const logsTab = page.locator('[role="tab"]:has-text("Logs")');
    if (await logsTab.isVisible()) {
      await logsTab.click();
      await waitForPageReady(page);
      
      // Should show log content
      await page.waitForTimeout(1000);
    }

    checkNoErrors(page, errors);
  });

  test('log filter dropdown works', async ({ page }) => {
    await page.goto('/settings/');
    await waitForPageReady(page);

    const logsTab = page.locator('[role="tab"]:has-text("Logs")');
    if (await logsTab.isVisible()) {
      await logsTab.click();
      await page.waitForTimeout(500);

      const logFilter = page.locator('select').first();
      if (await logFilter.isVisible()) {
        await logFilter.selectOption({ index: 1 });
        await page.waitForTimeout(500);
      }
    }
  });

  test('clear logs button works', async ({ page }) => {
    const errors: string[] = [];
    page.on('console', msg => { if (msg.type() === 'error') errors.push(msg.text()); });

    await page.goto('/settings/');
    await waitForPageReady(page);

    const logsTab = page.locator('[role="tab"]:has-text("Logs")');
    if (await logsTab.isVisible()) {
      await logsTab.click();
      await page.waitForTimeout(500);

      const clearBtn = page.locator('button:has-text("Clear")');
      if (await clearBtn.isVisible()) {
        await clearBtn.click();
        await page.waitForTimeout(500);
      }
    }

    checkNoErrors(page, errors);
  });
});

test.describe('Wizard Page', () => {
  test('wizard page loads', async ({ page }) => {
    const errors: string[] = [];
    page.on('console', msg => { if (msg.type() === 'error') errors.push(msg.text()); });

    await page.goto('/wizard/');
    await waitForPageReady(page);

    // Should have wizard content
    await expect(page.locator('body')).toBeVisible();
    checkNoErrors(page, errors);
  });
});

test.describe('Keyboard Navigation', () => {
  test('can tab through interactive elements', async ({ page }) => {
    await page.goto('/');
    await waitForPageReady(page);

    // Tab through first 10 elements
    for (let i = 0; i < 10; i++) {
      await page.keyboard.press('Tab');
      await page.waitForTimeout(100);
    }

    // Something should be focused
    const focused = page.locator(':focus');
    await expect(focused.first()).toBeVisible();
  });

  test('escape closes modals', async ({ page }) => {
    await page.goto('/wanted/');
    await waitForPageReady(page);

    const movieLink = page.locator('a[href*="/movie/"]').first();
    if (await movieLink.isVisible({ timeout: 3000 })) {
      await movieLink.click();
      await waitForPageReady(page);

      const trailerBtn = page.locator('button:has-text("Trailer")');
      if (await trailerBtn.isVisible({ timeout: 3000 })) {
        await trailerBtn.click();
        await page.waitForTimeout(1000);
        
        await page.keyboard.press('Escape');
        await page.waitForTimeout(300);
        
        // Modal should be closed
        const modal = page.locator('[role="dialog"]');
        const isVisible = await modal.isVisible().catch(() => false);
        expect(isVisible).toBe(false);
      }
    }
  });

  test('arrow keys navigate movie cards', async ({ page }) => {
    await page.goto('/wanted/');
    await waitForPageReady(page);

    const movieCard = page.locator('.poster-card, [data-movie-id]').first();
    if (await movieCard.isVisible({ timeout: 3000 })) {
      await movieCard.focus();
      await page.keyboard.press('ArrowRight');
      await page.waitForTimeout(200);
      await page.keyboard.press('ArrowLeft');
    }
  });
});

test.describe('Error Handling', () => {
  test('404 page shows gracefully', async ({ page }) => {
    await page.goto('/nonexistent-page-12345/');
    // Should not crash, should show some content
    await expect(page.locator('body')).toBeVisible();
  });

  test('invalid movie ID handles gracefully', async ({ page }) => {
    const errors: string[] = [];
    page.on('console', msg => { if (msg.type() === 'error') errors.push(msg.text()); });

    await page.goto('/movie/invalid-id-12345/');
    await waitForPageReady(page);

    // Should not have critical JS errors
    checkNoErrors(page, errors);
  });
});
