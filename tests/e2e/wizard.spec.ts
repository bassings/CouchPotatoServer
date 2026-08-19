import { test, expect } from './fixtures';

/**
 * T51: the first-run wizard must not report success for a save the server
 * refused.
 *
 * `saveSetting()` returns `fetch(...)` and never inspects the result, and
 * `api.py` answers HTTP 200 even for `{"success": false}` — so the promise
 * resolves, `saveCurrentStep()`'s `await Promise.all(saves)` resolves, nothing
 * throws, and `nextStep()` advances the step as though the value was stored.
 *
 * The error path already EXISTS: `nextStep()` wraps the save in try/catch and
 * toasts on failure, and only increments `currentStep` when nothing throws. It
 * is simply unreachable, because the only thing that could throw does not.
 *
 * Why this is ranked as security rather than polish: step 1 saves
 * `core.password`, and `Core.md5Password` (hooked to `setting.save.core.password`)
 * is what flips `auth_required` on. A refused save there means no password is
 * stored, authentication is never enabled, and the wizard's own summary reads
 * "Enabled" from local form state. The operator finishes setup believing the
 * instance is protected while it is publicly reachable.
 *
 * The refusal is forced with `page.route` rather than by finding a value the
 * server happens to reject: the behaviour under test is what the CLIENT does
 * with a refusal, so the refusal must be guaranteed, not hoped for.
 */
const SECURITY_USERNAME = (page) =>
  page.locator('input[type="text"][placeholder="Leave empty to skip"]').first();
const SECURITY_PASSWORD = (page) =>
  page.locator('input[type="password"][placeholder="Leave empty to skip"]').first();

test.describe('Wizard: a refused save must not read as success', () => {
  /** Force every settings save to be refused the way the API really refuses. */
  async function refuseEverySave(page) {
    await page.route('**/settings.save/**', async (route) => {
      await route.fulfill({
        status: 200,                       // the API returns 200 even on refusal
        contentType: 'application/json',
        body: JSON.stringify({ success: false }),
      });
    });
  }

  /** Welcome -> Security, without any save happening on the way. */
  async function gotoSecurityStep(page) {
    await page.goto('/wizard/');
    await expect(page.getByRole('button', { name: /Continue/i })).toBeVisible({
      timeout: 10000,
    });
    await page.getByRole('button', { name: /Continue/i }).click();
    // The security step's inputs carry no name or id -- they are Alpine
    // `x-model` bindings -- so they are addressed by type + placeholder.
    // An earlier draft used input[name="username"], matched nothing, and every
    // test failed for a reason unrelated to what they assert. The control test
    // below is what exposed that: it should PASS before any fix.
    await expect(SECURITY_USERNAME(page)).toBeVisible({ timeout: 5000 });
  }

  test('a refused password save is reported to the operator', async ({ page }) => {
    await refuseEverySave(page);
    await gotoSecurityStep(page);

    await SECURITY_USERNAME(page).fill('admin');
    await SECURITY_PASSWORD(page).fill('hunter2');
    await page.getByRole('button', { name: /Continue/i }).click();

    // The toast is the only channel the wizard has. If the save was refused and
    // nothing appears here, the operator has been told setup succeeded.
    await expect(
      page.locator('[x-text="message"]'),
      'the save was refused and the wizard said nothing',
    ).toBeVisible({ timeout: 5000 });
    await expect(page.locator('[x-text="message"]')).toContainText(/fail|error|could not/i);
  });

  /*
   * REMOVED: "a refused save does not advance the wizard past the step".
   *
   * The behaviour is real -- a probe confirmed it directly: the route
   * intercepted twice, returned {"success": false}, and the page still read
   * "Providers | Where to Search". But I could not write an assertion for it
   * whose failures I could explain, and shipping a test I do not understand is
   * worse than shipping none.
   *
   * Two versions failed for the WRONG reason before that became clear:
   *   - asserting the username field was "still visible" passed trivially,
   *     because it is visible during the transition either way;
   *   - asserting on body text without `useInnerText` compared textContent,
   *     which includes every hidden step's markup, so the step strings are
   *     always present and the assertion could never discriminate. That one
   *     went RED against the unfixed code and looked like proof.
   *
   * With `useInnerText` and the exact pre-fix code restored, it passes -- which
   * contradicts the probe and means something about the timing or the locator
   * is still not understood. Recorded in T51 as the remaining gap rather than
   * papered over.
   *
   * What IS proven below: the refusal is reported (fails against pre-fix code,
   * passes after), and a successful save still advances.
   */

  test('a save that succeeds still advances, so the guard is not a wall', async ({ page }) => {
    // The other direction: if the fix refused everything, these tests would
    // pass for the wrong reason and the wizard would be unusable.
    await page.route('**/settings.save/**', async (route) => {
      await route.fulfill({
        status: 200,
        contentType: 'application/json',
        body: JSON.stringify({ success: true }),
      });
    });
    await gotoSecurityStep(page);

    await SECURITY_USERNAME(page).fill('admin');
    await SECURITY_PASSWORD(page).fill('hunter2');
    await page.getByRole('button', { name: /Continue/i }).click();

    await expect(
      page.locator('body'),
      'a successful save failed to advance the wizard',
    ).toContainText('Where to Search', { timeout: 5000, useInnerText: true });
  });
});
