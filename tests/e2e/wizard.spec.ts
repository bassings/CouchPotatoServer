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

  test('a refused save does not advance the wizard past the step', async ({ page }) => {
    /**
     * Restored after review explained the disagreement that got it deleted.
     *
     * Two earlier versions passed against the UNFIXED code, which is why it
     * was pulled: asserting on `body` text was a retrying web-first assertion
     * on a NON-event, so it succeeded at its first poll, at t~0, before the
     * async advance had happened. The locator was groping at the right idea --
     * `useInnerText` to dodge hidden steps' markup -- but the missing piece
     * was a bounded settle, which asserting that something must NOT happen
     * always needs.
     *
     * `[x-text="steps[currentStep]"]` is unique in the template and unaffected
     * by hidden markup, so it discriminates where `body` could not.
     *
     * This is the security-relevant half of the task: does a refused PASSWORD
     * save leave the operator on the Security step, or strand them further in
     * with no credential stored.
     */
    await refuseEverySave(page);
    await gotoSecurityStep(page);

    await SECURITY_USERNAME(page).fill('admin');
    await SECURITY_PASSWORD(page).fill('hunter2');
    await page.getByRole('button', { name: /Continue/i }).click();

    // Bounded settle: this asserts a non-event, so it must outlive the advance
    // it is claiming did not happen.
    await page.waitForTimeout(1500);

    await expect(
      page.locator('[x-text="steps[currentStep]"]'),
      'the wizard advanced past Security despite the refusal',
    ).toHaveText('Security');
  });

  test('the refusal is ANNOUNCED, not just drawn', async ({ page }) => {
    /**
     * The visual toast carries no role, no aria-live and no live ancestor --
     * deliberately, per base.html, which ships two persistent sr-only regions
     * for the purpose. The wizard's own toast() never wrote to them, so a
     * screen-reader user was told nothing and the message self-cleared after
     * 3 seconds.
     *
     * That silence was harmless while this path was unreachable. This branch
     * makes it the ONLY channel reporting a refused save -- no password
     * stored, authentication not enabled -- so it is on the security-critical
     * path and CLAUDE.md's WCAG 2.2 AA floor applies.
     */
    await refuseEverySave(page);
    await gotoSecurityStep(page);

    await SECURITY_USERNAME(page).fill('admin');
    await SECURITY_PASSWORD(page).fill('hunter2');
    await page.getByRole('button', { name: /Continue/i }).click();

    await expect(
      page.locator('[data-testid="toast-announcer-assertive"]'),
      'the refusal was drawn on screen but never announced',
    ).toContainText(/fail|refus|error/i, { timeout: 5000 });
  });

  test('a refused PASSWORD names the password, not whichever save lost the race', async ({
    page,
  }) => {
    /**
     * `Promise.all` rejects with whichever save fails first, and username is
     * pushed before password -- so a refused password was reported as
     * "core.username was refused". The operator is pointed at the wrong field
     * and the fact that matters is never stated.
     *
     * Refuses BOTH saves, which is what makes this discriminate. With only the
     * password refused, `Promise.all` rejects with the password's error anyway
     * and the test passes against the unfixed code -- I wrote that version
     * first and the mutation proved it worthless. With both refused, first-
     * rejection reports ONLY the username, which is precisely the bug.
     */
    await refuseEverySave(page);
    await gotoSecurityStep(page);

    await SECURITY_USERNAME(page).fill('admin');
    await SECURITY_PASSWORD(page).fill('hunter2');
    await page.getByRole('button', { name: /Continue/i }).click();

    await expect(
      page.locator('[x-text="message"]'),
      'the message does not name the password, which is the setting that failed',
    ).toContainText(/password/i, { timeout: 5000 });
  });

  test('Skip after typing a password does not claim authentication is enabled', async ({
    page,
  }) => {
    /**
     * The P1 review found on this branch, and the second time this summary has
     * asserted a SERVER property from LOCAL state.
     *
     * Skip is visible on the Security step and calls `skipStep()`, not
     * `saveCurrentStep()`. So typing a password and pressing it stores
     * nothing, leaves `auth_required` off -- and, with the summary keyed on
     * `formData.password`, reported "Enabled" anyway. That is the same lie the
     * branch exists to fix, reached by a different button.
     */
    await page.route('**/settings.save/**', async (route) => {
      await route.fulfill({
        status: 200,
        contentType: 'application/json',
        body: JSON.stringify({ success: true }),
      });
    });
    await gotoSecurityStep(page);

    await SECURITY_PASSWORD(page).fill('hunter2');
    await page.getByRole('button', { name: /^Skip$/i }).click();

    // Walk to the summary step.
    for (let i = 0; i < 4; i++) {
      const next = page.getByRole('button', { name: /Continue|Finish Setup/i });
      if (!(await next.isVisible().catch(() => false))) break;
      await next.click();
      await page.waitForTimeout(300);
    }

    // Scoped to the Authentication row itself. Asserting on `body` was too
    // broad -- other summary rows legitimately read "Enabled" (the renamer,
    // for one), so the test failed for a reason unrelated to its claim.
    await expect(
      page.locator('[x-text*="passwordStored"]'),
      'the summary claims authentication is enabled after Skip stored nothing',
    ).toHaveText('Disabled', { timeout: 5000 });
  });

  test('Back then Skip keeps reporting Enabled, because the save still stands', async ({
    page,
  }) => {
    /**
     * The inverse of the test that used to sit here, which asserted "Disabled"
     * and was locking in a bug.
     *
     * `skipStep()` makes no server call. So after type -> Continue (saved,
     * `auth_required = 1`) -> Back -> Skip, the server still holds the password
     * and still enforces login. Reporting "Disabled" there is the same lie this
     * branch exists to fix, pointing the other way -- and arguably worse, since
     * an operator who believes authentication is off may expose the instance
     * deliberately.
     *
     * How I got it wrong is worth recording: a mutation showed that removing
     * `skipStep`'s clear left the earlier Skip test green. I read that as "the
     * test is too weak" and wrote a stronger test for the clear, rather than
     * asking whether the clear was correct. The mutation was telling me the
     * code was wrong, not the test.
     */
    await page.route('**/settings.save/**', async (route) => {
      await route.fulfill({
        status: 200,
        contentType: 'application/json',
        body: JSON.stringify({ success: true }),
      });
    });
    await gotoSecurityStep(page);

    await SECURITY_PASSWORD(page).fill('hunter2');
    await page.getByRole('button', { name: /Continue/i }).click();   // really saves
    await page.waitForTimeout(500);
    await page.getByRole('button', { name: /Back/i }).click();
    await expect(SECURITY_PASSWORD(page)).toBeVisible({ timeout: 5000 });
    await page.getByRole('button', { name: /^Skip$/i }).click();

    for (let i = 0; i < 4; i++) {
      const next = page.getByRole('button', { name: /Continue|Finish Setup/i });
      if (!(await next.isVisible().catch(() => false))) break;
      await next.click();
      await page.waitForTimeout(300);
    }

    await expect(
      page.locator('[x-text*="passwordStored"]'),
      'the summary says Disabled while the server still has the password and ' +
        'still enforces login',
    ).toHaveText('Enabled', { timeout: 5000 });
  });

  test('a refusal on a LATER step is reported too, not just on Security', async ({ page }) => {
    /**
     * The throw is applied at `saveSetting`, so it covers every call site --
     * Providers, Downloader and Library all push saves, and some of them can
     * genuinely be refused (`chroot2abs` rejects a directory outside the soft
     * chroot, which returns `{"success": false}`).
     *
     * Before this branch those refusals were swallowed by the raw-fetch-promise
     * bug exactly like the password one. Every other test here exercises step
     * 1, so nothing proved the behaviour generalises -- raised in review as a
     * coverage gap, and it is a real one: a step-1-only fix would look
     * identical in all the other tests.
     *
     * Refuses only the renamer saves, so the wizard has to reach a later step
     * under normal conditions first.
     */
    await page.route('**/settings.save/**', async (route) => {
      const body = route.request().postData() || '';
      const refused = body.includes('section=renamer');
      await route.fulfill({
        status: 200,
        contentType: 'application/json',
        body: JSON.stringify(refused ? { success: false } : { success: true }),
      });
    });
    await gotoSecurityStep(page);

    // Walk forward until the renamer save is attempted and refused.
    for (let i = 0; i < 5; i++) {
      const next = page.getByRole('button', { name: /Continue|Finish Setup/i });
      if (!(await next.isVisible().catch(() => false))) break;
      await next.click();
      await page.waitForTimeout(400);
      const msg = await page.locator('[x-text="message"]').textContent().catch(() => '');
      if (msg && /fail|refus|error/i.test(msg)) break;
    }

    await expect(
      page.locator('[x-text="message"]'),
      'a refused save on a later step was swallowed -- the fix is step-1 only',
    ).toContainText(/fail|refus|error/i, { timeout: 5000 });
  });

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
