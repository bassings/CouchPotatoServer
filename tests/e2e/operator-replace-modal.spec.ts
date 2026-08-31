import { test, expect } from './fixtures';
import { type Page } from '@playwright/test';

/**
 * FEAT-011 "Replace with this file": wiring the modal to its data and its
 * submit (client-side data flow only, not accessibility, not progress
 * polling beyond what these six behaviours need).
 *
 * Deliberately Playwright, not a Jinja render test. A render test can pin
 * markup, but cannot exercise a fetch, a click, or a request count -- an
 * earlier increment on this same feature was pointed at that pattern and
 * shipped a dialog with no data in it while a full gate stayed green. Every
 * test below drives the REAL server-rendered movie detail page (the trigger
 * and dialog shell already built and pinned by
 * tests/unit/test_operator_replace_trigger_ui_template.py and
 * tests/unit/test_operator_replace_modal_ui_template.py) and intercepts only
 * the two renamer routes the client talks to
 * (renamer.operator_candidates, renamer.operator_replace) -- never the page
 * itself.
 *
 * Uses scripts/seed_e2e_data.py's two dedicated review-gate movies
 * (REVIEW_MOVIE_ID / REVIEW_DESTRUCTIVE_MOVIE_ID), which that script now
 * seeds with a `files.movie` entry on their one completed release
 * specifically so movie_detail.html's operator-replace trigger has
 * something real to gate on -- see that script's own comment on
 * REVIEW_RELEASE/REVIEW_DESTRUCTIVE_RELEASE. Every test here intercepts
 * renamer.operator_replace itself rather than letting it reach the real
 * backend, so neither seeded movie is actually mutated (same reasoning
 * filters.spec.ts already documents for reusing these two ids despite the
 * action "looking" destructive) -- the split between them below exists only
 * to spread the six behaviours across both fixtures per the task, not
 * because either one is genuinely at risk.
 *
 * This file pins the CONTRACT the next increment must build to, not
 * something already built: as of this commit nothing in
 * movie_detail.html fetches renamer.operator_candidates, renders a
 * candidate as a choice, or submits to renamer.operator_replace, so every
 * test below is expected to fail on that missing wiring (a timeout waiting
 * for [data-testid="operator-replace-confirm"], or a candidate radio that
 * never appears) -- not on a fixture, import, or syntax problem.
 *
 * Test-id / role contract this file pins (none of it exists yet):
 *   - Each candidate is offered as a radio: `getByRole('radio', { name: <candidate name>, exact: true })`.
 *   - `[data-testid="operator-replace-confirm"]` -- the destructive commit control.
 *   - `[data-testid="operator-replace-empty"]` -- shown when the listing succeeds with zero candidates.
 *   - `[data-testid="operator-replace-error"]` -- shown when the listing request itself fails.
 */

const REVIEW_MOVIE_ID = 'e2e-seed-movie-007';
const REVIEW_DESTRUCTIVE_MOVIE_ID = 'e2e-seed-movie-008';

const CANDIDATE_ROUTE = /renamer\.operator_candidates/;
const REPLACE_ROUTE = /renamer\.operator_replace/;

const CANDIDATES = [
  'Minions.and.Monsters.2024.2160p.UHD.HDR10Plus-GRP9.mkv',
  'Some.Other.Placed.File.2024.mkv',
];

function candidatesResponse(candidates: string[]) {
  return {
    status: 200,
    contentType: 'application/json',
    body: JSON.stringify({ success: true, candidates }),
  };
}

/**
 * Navigate to `movieId`'s detail page and wait for the real detail body
 * (not the static shell -- see movie-detail.spec.ts's own gotoMovie, which
 * this mirrors rather than imports: importing a .spec.ts re-registers its
 * tests).
 */
async function gotoReviewMovie(page: Page, movieId: string) {
  await page.goto(`/movie/${movieId}`);
  const loaded = await page.locator('#movie-releases')
    .waitFor({ state: 'attached', timeout: 15000 })
    .then(() => true)
    .catch(() => false);
  expect(
    loaded,
    `No seeded movie at /movie/${movieId}. Run ` +
    '`.venv/bin/python scripts/seed_e2e_data.py --data_dir=.e2e-data` before ' +
    'starting the server.',
  ).toBe(true);

  // T8a: the operator-replace trigger/modal render only when
  // `operator_replace_enabled` is on (default OFF in production, per
  // specs/FEAT-011-replace-with-this-file.md's "Shipped disabled" note).
  // This file's own tests intercept the operator_candidates/operator_replace
  // fetches themselves (never letting them reach the real backend), so
  // flipping the template's gate through the real settings.save API and
  // reloading is enough -- no server restart needed, since
  // couchpotato.ui._ctx() reads the setting fresh on every request.
  await page.evaluate(async () => {
    await fetch(window.CP.apiBase + '/settings.save/?section=renamer&name=operator_replace_enabled&value=true');
  });
  await page.reload();
  await page.locator('#movie-releases').waitFor({ state: 'attached', timeout: 15000 });
}

/**
 * Open the "Replace with this file" dialog and return it, scoped, so every
 * assertion below reads from THIS dialog rather than coincidentally
 * matching something else on the page.
 */
async function openReplaceModal(page: Page, movieId: string) {
  await gotoReviewMovie(page, movieId);

  const trigger = page.locator('[data-testid="operator-replace-trigger"]');
  await expect(
    trigger,
    'operator-replace trigger did not render -- did scripts/seed_e2e_data.py ' +
    'seed a files.movie entry for this release?',
  ).toBeVisible({ timeout: 10000 });
  await trigger.click();

  const modal = page.locator('[data-testid="operator-replace-modal"]');
  await expect(modal).toBeVisible({ timeout: 5000 });
  return modal;
}

test.describe('Operator replace modal: candidate data and submit (FEAT-011)', () => {
  test('opening the picker fetches renamer.operator_candidates exactly once and offers each name as a choice, never as a free-text field (point 1)', async ({
    page,
  }) => {
    let candidateRequests = 0;
    await page.route(CANDIDATE_ROUTE, (route) => {
      candidateRequests++;
      return route.fulfill(candidatesResponse(CANDIDATES));
    });
    let replaceRequests = 0;
    await page.route(REPLACE_ROUTE, (route) => {
      replaceRequests++;
      return route.fulfill({ status: 200, contentType: 'application/json', body: '{"success":true}' });
    });

    const modal = await openReplaceModal(page, REVIEW_MOVIE_ID);

    await expect.poll(() => candidateRequests, { timeout: 5000 }).toBe(1);

    for (const name of CANDIDATES) {
      await expect(
        modal.getByRole('radio', { name, exact: true }),
        `candidate "${name}" was not offered as a selectable choice`,
      ).toBeVisible({ timeout: 5000 });
    }

    // AC-SEC-1 / the task's own point 1: no way to type a path.
    const freeTextInputs = modal.locator(
      'input[type="text"], input[type="search"], input[type="url"], input:not([type])',
    );
    await expect(
      freeTextInputs,
      'the picker must offer no free-text path entry -- selection can only come from the server-produced list',
    ).toHaveCount(0);

    expect(replaceRequests, 'merely opening the picker must not call renamer.operator_replace').toBe(0);
  });

  test('confirming a chosen candidate sends exactly media_id and source to renamer.operator_replace, the source verbatim from the server listing (point 2)', async ({
    page,
  }) => {
    // Deliberately awkward: proves the client echoes the name back rather
    // than re-deriving or re-encoding it.
    const trickyName = "Minions & Monsters (2024) [UHD HDR10+] 'GRP9'.mkv";
    await page.route(CANDIDATE_ROUTE, (route) =>
      route.fulfill(candidatesResponse([trickyName, 'Other.Placed.File.mkv'])));

    const replaceRequests: URL[] = [];
    await page.route(REPLACE_ROUTE, (route) => {
      replaceRequests.push(new URL(route.request().url()));
      return route.fulfill({ status: 200, contentType: 'application/json', body: '{"success":true}' });
    });

    const modal = await openReplaceModal(page, REVIEW_MOVIE_ID);
    await modal.getByRole('radio', { name: trickyName, exact: true }).click();

    const confirmBtn = modal.locator('[data-testid="operator-replace-confirm"]');
    await expect(confirmBtn).toBeEnabled({ timeout: 5000 });
    await confirmBtn.click();

    await expect.poll(() => replaceRequests.length, { timeout: 5000 }).toBe(1);

    const params = replaceRequests[0].searchParams;
    expect(
      Array.from(params.keys()).sort(),
      'the request must carry exactly media_id and source -- no destination, dst, to, path, media_folder or base_folder',
    ).toEqual(['media_id', 'source']);
    expect(params.get('media_id')).toBe(REVIEW_MOVIE_ID);
    expect(
      params.get('source'),
      'the source must be the candidate name the server offered, verbatim -- never a client-constructed path',
    ).toBe(trickyName);
  });

  test('the confirm control cannot fire a replacement until a candidate is chosen (point 3)', async ({ page }) => {
    await page.route(CANDIDATE_ROUTE, (route) => route.fulfill(candidatesResponse(CANDIDATES)));
    let replaceRequests = 0;
    await page.route(REPLACE_ROUTE, (route) => {
      replaceRequests++;
      return route.fulfill({ status: 200, contentType: 'application/json', body: '{"success":true}' });
    });

    const modal = await openReplaceModal(page, REVIEW_MOVIE_ID);
    const confirmBtn = modal.locator('[data-testid="operator-replace-confirm"]');
    await expect(confirmBtn).toBeVisible({ timeout: 5000 });
    await expect(confirmBtn, 'the confirm control must not be enabled before a candidate is chosen').not.toBeEnabled();

    // force:true bypasses Playwright's own actionability retries, so a
    // green result here proves the APPLICATION refused the activation, not
    // that Playwright declined to click a disabled element for us.
    await confirmBtn.click({ force: true });
    await page.waitForTimeout(500);
    expect(
      replaceRequests,
      'clicking confirm with nothing selected must not call renamer.operator_replace',
    ).toBe(0);

    await modal.getByRole('radio', { name: CANDIDATES[0], exact: true }).click();
    await expect(confirmBtn, 'choosing a candidate must enable the confirm control').toBeEnabled({ timeout: 5000 });
  });

  test('an empty candidate listing is reported in the modal and offers no confirm control (point 4, empty)', async ({
    page,
  }) => {
    await page.route(CANDIDATE_ROUTE, (route) => route.fulfill(candidatesResponse([])));

    const modal = await openReplaceModal(page, REVIEW_MOVIE_ID);

    const emptyState = modal.locator('[data-testid="operator-replace-empty"]');
    await expect(emptyState, 'an empty candidate list must be reported in the modal').toBeVisible({ timeout: 5000 });
    await expect(
      modal.locator('[data-testid="operator-replace-error"]'),
      'an empty listing must not also render as a failure',
    ).toHaveCount(0);
    await expect(
      modal.locator('[data-testid="operator-replace-confirm"]'),
      'there is nothing to confirm with an empty listing',
    ).toHaveCount(0);
  });

  test('a failed candidate listing request is reported in the modal, distinctly from an empty one (point 4, failure)', async ({
    page,
  }) => {
    await page.route(CANDIDATE_ROUTE, (route) =>
      route.fulfill({ status: 500, contentType: 'application/json', body: '{"success":false}' }));

    const modal = await openReplaceModal(page, REVIEW_MOVIE_ID);

    const errorState = modal.locator('[data-testid="operator-replace-error"]');
    await expect(errorState, 'a failed listing request must be reported in the modal').toBeVisible({ timeout: 5000 });
    await expect(
      modal.locator('[data-testid="operator-replace-empty"]'),
      'a failed request must not read as merely "nothing available"',
    ).toHaveCount(0);
    await expect(modal.locator('[data-testid="operator-replace-confirm"]')).toHaveCount(0);
  });

  test('the empty state and the failure state read as different situations, not both as "nothing here" (point 4)', async ({
    page,
  }) => {
    await page.route(CANDIDATE_ROUTE, (route) => route.fulfill(candidatesResponse([])));
    const emptyModal = await openReplaceModal(page, REVIEW_MOVIE_ID);
    const emptyText = ((await emptyModal.locator('[data-testid="operator-replace-empty"]').textContent()) || '').trim();
    expect(emptyText.length, 'the empty state must say something, not render blank').toBeGreaterThan(0);

    await page.route(CANDIDATE_ROUTE, (route) =>
      route.fulfill({ status: 500, contentType: 'application/json', body: '{"success":false}' }));
    const errorModal = await openReplaceModal(page, REVIEW_DESTRUCTIVE_MOVIE_ID);
    const errorText = ((await errorModal.locator('[data-testid="operator-replace-error"]').textContent()) || '').trim();
    expect(errorText.length, 'the failure state must say something, not render blank').toBeGreaterThan(0);

    expect(
      errorText.toLowerCase(),
      'empty and broken must read differently -- identical copy for both defeats the point of having two states',
    ).not.toBe(emptyText.toLowerCase());
  });

  test('a successful start closes the dialog and announces the background swap, without reloading the page (point 5)', async ({
    page,
  }) => {
    await page.route(CANDIDATE_ROUTE, (route) => route.fulfill(candidatesResponse(CANDIDATES)));
    await page.route(REPLACE_ROUTE, (route) =>
      route.fulfill({ status: 200, contentType: 'application/json', body: '{"success":true}' }));

    const modal = await openReplaceModal(page, REVIEW_MOVIE_ID);
    await modal.getByRole('radio', { name: CANDIDATES[0], exact: true }).click();

    // Rewritten 2026-08-31 (branch review): this test used to wait for a
    // /partial/movie/ re-fetch. The MEDIUM round's M22 fix deliberately
    // removed that swap, because `success` here only means the server has
    // ACCEPTED the request and started a background thread, so re-rendering
    // showed the operator the OLD file's details on the very page whose job
    // is telling them what is about to be destroyed. The re-fetch is gone on
    // purpose and this test now pins the behaviour that replaced it.
    //
    // What must NOT change is the reason the original test existed at all:
    // the success path must never call location.reload(), because that
    // destroys base.html's live-region announcers before the outcome can be
    // spoken. That requirement is carried by the polite-announcer assertion
    // below, not by a separate no-reload marker: a reload wipes the live
    // region, so the announcer assertion fails on exactly the defect the
    // marker was meant to catch. Proven 2026-08-31 by mutation -- adding a
    // synchronous location.reload() to the success branch fails this test on
    // the announcer, with the received text empty. A marker read immediately
    // after the assertions was also tried and could not be made to fail by
    // any realistic mutation, so it was removed rather than kept as a line
    // that always passes.

    const confirmBtn = modal.locator('[data-testid="operator-replace-confirm"]');
    await expect(confirmBtn).toBeEnabled({ timeout: 5000 });
    await confirmBtn.click();

    // Positive effect 1: the dialog closes, so the operator is returned to
    // the page rather than left staring at a modal that did nothing.
    await expect(page.locator('[data-testid="operator-replace-modal"]')).toBeHidden({
      timeout: 5000,
    });

    // Positive effect 2: the operator is told, in the polite live region,
    // that the work is still running. 'info' toasts route to the polite
    // announcer (base.html), which is what a screen reader will speak.
    await expect(page.locator('[data-testid="toast-announcer-polite"]')).toContainText(
      /running in the background/i,
      { timeout: 5000 },
    );

  });

  test('two rapid activations of confirm produce exactly one request to renamer.operator_replace (point 6)', async ({
    page,
  }) => {
    await page.route(CANDIDATE_ROUTE, (route) => route.fulfill(candidatesResponse(CANDIDATES)));

    let replaceRequests = 0;
    await page.route(REPLACE_ROUTE, async (route) => {
      replaceRequests++;
      // Held open so the second activation is a genuine race against the
      // re-entry guard, not a race the guard wins only because the first
      // request already finished -- same technique as filters.spec.ts's
      // AC-QA-16 "two rapid clicks on Mark Done" test.
      await new Promise((resolve) => setTimeout(resolve, 400));
      return route.fulfill({ status: 200, contentType: 'application/json', body: '{"success":true}' });
    });

    const modal = await openReplaceModal(page, REVIEW_DESTRUCTIVE_MOVIE_ID);
    await modal.getByRole('radio', { name: CANDIDATES[0], exact: true }).click();

    const confirmBtn = modal.locator('[data-testid="operator-replace-confirm"]');
    await expect(confirmBtn).toBeEnabled({ timeout: 5000 });

    await Promise.all([
      confirmBtn.click({ force: true }),
      confirmBtn.click({ force: true }),
    ]);
    await page.waitForTimeout(700);

    expect(
      replaceRequests,
      'a second activation while one is in flight must be visibly refused, not queued',
    ).toBe(1);
  });
});
