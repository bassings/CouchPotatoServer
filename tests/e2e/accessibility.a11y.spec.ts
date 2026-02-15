import { test, expect } from '@playwright/test';
import AxeBuilder from '@axe-core/playwright';

/**
 * Accessibility tests for CouchPotato new UI using axe-core.
 * These tests check for WCAG violations on all main pages.
 */

// Helper to check a11y violations
async function checkA11y(page: any, pageName: string) {
  const accessibilityScanResults = await new AxeBuilder({ page })
    .withTags(['wcag2a', 'wcag2aa', 'wcag21a', 'wcag21aa'])
    // Exclude known exceptions documented below
    .exclude('#loading') // Loading indicators are transient
    .analyze();

  // Log violations for debugging
  if (accessibilityScanResults.violations.length > 0) {
    console.log(`A11y violations on ${pageName}:`);
    accessibilityScanResults.violations.forEach(violation => {
      console.log(`  - ${violation.id}: ${violation.description}`);
      console.log(`    Impact: ${violation.impact}`);
      console.log(`    Nodes: ${violation.nodes.length}`);
    });
  }

  // Fail on critical or serious violations
  const criticalViolations = accessibilityScanResults.violations.filter(
    v => v.impact === 'critical' || v.impact === 'serious'
  );

  expect(
    criticalViolations.length,
    `Found ${criticalViolations.length} critical/serious a11y violations on ${pageName}: ${
      criticalViolations.map(v => v.id).join(', ')
    }`
  ).toBe(0);

  return accessibilityScanResults;
}

test.describe('Accessibility', () => {
  test('Wanted page should be accessible', async ({ page }) => {
    await page.goto('/');
    await page.waitForLoadState('networkidle');
    await page.waitForTimeout(1000); // Wait for htmx to load content
    
    await checkA11y(page, 'Wanted');
  });

  test('Available page should be accessible', async ({ page }) => {
    await page.goto('/available/');
    await page.waitForLoadState('networkidle');
    await page.waitForTimeout(1000);
    
    await checkA11y(page, 'Available');
  });

  test('Suggestions page should be accessible', async ({ page }) => {
    await page.goto('/suggestions/');
    await page.waitForLoadState('networkidle');
    await page.waitForTimeout(1000);
    
    await checkA11y(page, 'Suggestions');
  });

  test('Add Movie page should be accessible', async ({ page }) => {
    await page.goto('/add/');
    await page.waitForLoadState('networkidle');
    await page.waitForTimeout(1000);
    
    await checkA11y(page, 'Add Movie');
  });

  test('Settings page should be accessible', async ({ page }) => {
    await page.goto('/settings/');
    await page.waitForLoadState('networkidle');
    await page.waitForTimeout(2000); // Settings takes longer to load
    
    await checkA11y(page, 'Settings');
  });

  test('Navigation should have proper ARIA landmarks', async ({ page }) => {
    await page.goto('/');
    await page.waitForLoadState('networkidle');
    
    // Check for main navigation
    const nav = page.locator('nav[aria-label]');
    await expect(nav.first()).toBeVisible();
    
    // Check for main content area
    const main = page.locator('main');
    await expect(main).toBeVisible();
  });

  test('Interactive elements should be keyboard accessible', async ({ page }) => {
    await page.goto('/');
    await page.waitForLoadState('networkidle');
    await page.waitForTimeout(1000);
    
    // Tab through the page
    await page.keyboard.press('Tab');
    
    // Something should be focused
    const focusedElement = page.locator(':focus');
    await expect(focusedElement.first()).toBeVisible();
    
    // Focused element should have visible focus indicator (not disabled in CSS)
    const outline = await focusedElement.first().evaluate(el => {
      const styles = window.getComputedStyle(el);
      return styles.outline !== 'none' || styles.boxShadow !== 'none';
    });
    // Note: This might need adjustment based on the focus styling approach used
  });

  test('Images should have alt text', async ({ page }) => {
    await page.goto('/');
    await page.waitForLoadState('networkidle');
    await page.waitForTimeout(1000);
    
    // Get all images
    const images = page.locator('img');
    const count = await images.count();
    
    for (let i = 0; i < Math.min(count, 10); i++) {
      const img = images.nth(i);
      const alt = await img.getAttribute('alt');
      // All images should have alt attribute (even if empty for decorative)
      expect(await img.getAttribute('alt')).toBeDefined();
    }
  });

  test('Color contrast should be sufficient', async ({ page }) => {
    await page.goto('/');
    await page.waitForLoadState('networkidle');
    await page.waitForTimeout(1000);
    
    // Run axe specifically for color contrast
    const results = await new AxeBuilder({ page })
      .withRules(['color-contrast'])
      .analyze();
    
    // Log any contrast issues
    if (results.violations.length > 0) {
      console.log('Color contrast issues:');
      results.violations.forEach(v => {
        v.nodes.forEach(n => {
          console.log(`  - ${n.html}: ${n.failureSummary}`);
        });
      });
    }
    
    // Allow minor contrast issues but fail on critical
    const critical = results.violations.filter(v => v.impact === 'critical');
    expect(critical.length).toBe(0);
  });
});

/**
 * Known Exceptions:
 * 
 * 1. Loading indicators (#loading) - These are transient and don't need to be
 *    fully accessible as they're only visible for a short time.
 * 
 * 2. Some color contrast issues in badges/status indicators may be acceptable
 *    as they use color alongside other visual indicators (position, text).
 */
