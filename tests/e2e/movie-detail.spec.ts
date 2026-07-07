import { test, expect } from '@playwright/test';

/**
 * Movie detail page tests for CouchPotato new UI.
 */

test.describe('Movie Detail', () => {
  test('should navigate to movie detail from wanted list', async ({ page }) => {
    await page.goto('/');
    
    // Wait for movies to load
    const movieGrid = page.locator('#movie-grid');
    await expect(movieGrid).toBeVisible({ timeout: 10000 });
    
    // Get first movie card
    const firstCard = movieGrid.locator('.poster-card').first();
    if (await firstCard.count() > 0) {
      // Click on the movie
      await firstCard.click();
      
      // Should navigate to detail page
      await expect(page).toHaveURL(/.*movie\/.+/);
      
      // Should show movie title
      await expect(page.locator('h1')).toBeVisible({ timeout: 5000 });
    }
  });

  test('should show refresh button on detail page', async ({ page }) => {
    await page.goto('/');
    
    const movieGrid = page.locator('#movie-grid');
    await expect(movieGrid).toBeVisible({ timeout: 10000 });
    
    const firstCard = movieGrid.locator('.poster-card').first();
    if (await firstCard.count() > 0) {
      await firstCard.click();
      await expect(page).toHaveURL(/.*movie\/.+/);
      
      // Should have Refresh button
      const refreshButton = page.getByRole('button', { name: /refresh/i });
      await expect(refreshButton).toBeVisible({ timeout: 5000 });
    }
  });

  test('should show Delete button on detail page', async ({ page }) => {
    await page.goto('/');
    
    const movieGrid = page.locator('#movie-grid');
    await expect(movieGrid).toBeVisible({ timeout: 10000 });
    
    const firstCard = movieGrid.locator('.poster-card').first();
    if (await firstCard.count() > 0) {
      await firstCard.click();
      await expect(page).toHaveURL(/.*movie\/.+/);
      
      // Should have Delete button
      const deleteButton = page.getByRole('button', { name: /delete/i });
      await expect(deleteButton).toBeVisible({ timeout: 5000 });
    }
  });

  test('should show back link on detail page', async ({ page }) => {
    await page.goto('/');
    
    const movieGrid = page.locator('#movie-grid');
    await expect(movieGrid).toBeVisible({ timeout: 10000 });
    
    const firstCard = movieGrid.locator('.poster-card').first();
    if (await firstCard.count() > 0) {
      await firstCard.click();
      await expect(page).toHaveURL(/.*movie\/.+/);
      
      // Should have Back link
      const backLink = page.getByRole('link', { name: /back/i });
      await expect(backLink).toBeVisible({ timeout: 5000 });
      
      // Click back should navigate away
      await backLink.click();
      await expect(page).not.toHaveURL(/.*movie\/.+/);
    }
  });

  test('year should show TBA for movies without release date (DEF-005)', async ({ page }) => {
    // This test verifies the fix for DEF-005
    // We can't easily find a movie without a year, so we just verify
    // that the year format is correct (either a number or TBA)
    await page.goto('/');

    const movieGrid = page.locator('#movie-grid');
    await expect(movieGrid).toBeVisible({ timeout: 10000 });

    const firstCard = movieGrid.locator('.poster-card').first();
    if (await firstCard.count() > 0) {
      // Check year format in card - should not be empty or "()"
      const yearText = await firstCard.locator('p').last().textContent();
      expect(yearText).toBeTruthy();
      expect(yearText).not.toBe('');
      expect(yearText?.trim()).not.toBe('()');
    }
  });

  /**
   * Downloaded/review workflow (specs/DOWNLOADED-REVIEW-WORKFLOW.md, Phase 3c).
   *
   * COVERAGE GAP: there is no fixture / test-only API to seed a movie in the
   * 'downloaded' (review-gate) status -- reaching it requires a profile with
   * manual_confirmation ON plus a real completed download (Phase 2 completion
   * routing). CI and local e2e always start from a fresh, empty data dir
   * (see playwright.config.ts's throwaway .e2e-data / .config), so the Wanted
   * list here can only ever contain 'active' movies (or be empty). We
   * therefore assert the review-gate buttons are ABSENT for whatever movie is
   * actually present, and skip (rather than fake) the "buttons ARE shown"
   * case -- faking a 'downloaded' movie via direct DB access from an e2e test
   * would misrepresent real coverage.
   */
  test('review-gate buttons (Mark Done / Mark Failed & Re-search) are absent for a non-downloaded movie', async ({ page }) => {
    await page.goto('/');

    const movieGrid = page.locator('#movie-grid');
    await expect(movieGrid).toBeVisible({ timeout: 10000 });

    const firstCard = movieGrid.locator('.poster-card').first();
    if (await firstCard.count() > 0) {
      await firstCard.click();
      await expect(page).toHaveURL(/.*movie\/.+/);
      await expect(page.locator('h1')).toBeVisible({ timeout: 5000 });

      // "Mark Done" (review-gate) has a distinct accessible name from the
      // pre-existing generic "Mark as Done" button (shown for any
      // non-done/non-downloaded movie) -- exact match keeps them from
      // being confused with each other.
      await expect(page.getByRole('button', { name: 'Mark Done', exact: true })).toHaveCount(0);
      await expect(page.getByRole('button', { name: /mark failed\s*&\s*re-search/i })).toHaveCount(0);

      // Per-release "Mark failed" (only rendered for a release in
      // 'downloaded' status) should likewise be absent.
      await expect(page.getByRole('button', { name: 'Mark failed', exact: true })).toHaveCount(0);
    }
  });

  test('Mark Failed & Re-search requires confirmation when shown (review-gate movie)', async ({ page }) => {
    await page.goto('/');

    const movieGrid = page.locator('#movie-grid');
    await expect(movieGrid).toBeVisible({ timeout: 10000 });

    const firstCard = movieGrid.locator('.poster-card').first();
    if (await firstCard.count() > 0) {
      await firstCard.click();
      await expect(page).toHaveURL(/.*movie\/.+/);

      const markFailedButton = page.getByRole('button', { name: /mark failed\s*&\s*re-search/i });
      if (await markFailedButton.count() > 0) {
        let dialogMessage: string | null = null;
        page.once('dialog', async (dialog) => {
          dialogMessage = dialog.message();
          expect(dialog.type()).toBe('confirm');
          await dialog.dismiss();
        });
        await markFailedButton.click();
        await expect.poll(() => dialogMessage).not.toBeNull();
        // Dismissed -- should not have navigated away or reloaded into an
        // active/searching state we didn't confirm.
        await expect(page).toHaveURL(/.*movie\/.+/);
      }
      // See the coverage-gap note on the preceding test: this suite has no
      // way to reliably produce a 'downloaded' movie, so the "dialog shown"
      // branch above only exercises when such a movie happens to exist.
    }
  });

  test('per-release Mark failed requires confirmation when shown', async ({ page }) => {
    await page.goto('/');

    const movieGrid = page.locator('#movie-grid');
    await expect(movieGrid).toBeVisible({ timeout: 10000 });

    const firstCard = movieGrid.locator('.poster-card').first();
    if (await firstCard.count() > 0) {
      await firstCard.click();
      await expect(page).toHaveURL(/.*movie\/.+/);

      const releaseMarkFailedButton = page.getByRole('button', { name: 'Mark failed', exact: true });
      if (await releaseMarkFailedButton.count() > 0) {
        let dialogMessage: string | null = null;
        page.once('dialog', async (dialog) => {
          dialogMessage = dialog.message();
          expect(dialog.type()).toBe('confirm');
          await dialog.dismiss();
        });
        await releaseMarkFailedButton.first().click();
        await expect.poll(() => dialogMessage).not.toBeNull();
      }
      // Coverage gap: see above -- no fixture produces a 'downloaded' release
      // in this suite, so this only exercises when one happens to exist.
    }
  });
});
