import type { Locator, Page, Response } from '@playwright/test';

import { test, expect } from './fixtures';
import { configColumns, configEnabled, configSha, configView } from './helpers';
import { combineGroupWriter, SETTINGS_PERSISTENCE_ANNOTATION } from './settings_persistence';

/**
 * Settings page tests for CouchPotato new UI.
 */

test.describe('Settings', () => {
  test.beforeEach(async ({ page }) => {
    await page.goto('/settings/');
    await expect(page.locator('h1')).toContainText('Settings');
  });

  test('the Jackett sync button reaches the real server and is not refused by the origin check', async ({ page }) => {
    // SEC-004 P2, AC-SEC-9 rule (b). The sync route is deliberately NOT stubbed:
    // a stub would answer in the browser and could never show that the origin
    // check lets the real button through. The Jackett URL is an `.invalid` host
    // with no saved key, so the handler stops at its own "required" refusal and
    // nothing leaves the machine. The persistence guard restores the URL.
    test.info().annotations.push({ type: SETTINGS_PERSISTENCE_ANNOTATION });
    const saved = await page.evaluate(async () => {
      const body = new URLSearchParams({
        section: 'torrentpotato', name: 'jackett_url', value: 'http://jackett.invalid:9117',
      });
      const response = await fetch((window as any).CP.apiBase + '/settings.save/', { method: 'POST', body });
      return (await response.json()).success;
    });
    expect(saved).toBe(true);

    const answered = page.waitForResponse((response) => response.url().includes('torrentpotato.jackett_sync'));
    const outcome = await page.evaluate(async () => {
      const root = document.querySelector('[x-data="settingsPanel()"]');
      const panel = (window as any).Alpine.$data(root);
      const option = Object.values(panel.options as Record<string, any>)
        .flatMap((section) => section.groups || [])
        .flatMap((group: any) => group.options || [])
        .find((candidate: any) => candidate.name === 'jackett_sync');
      if (!option) throw new Error('the declared jackett_sync button option is absent');
      const field = (window as any).buttonField('torrentpotato', option);
      await field.execute();
      return { success: field.success, result: field.result };
    });
    const response = await answered;

    expect(response.status()).toBe(200);
    expect(await response.request().headerValue('referer')).toContain('/settings/');
    expect(outcome.success).toBe(false);
    expect(outcome.result).toMatch(/Jackett URL and API key are required/);
    expect(outcome.result).not.toMatch(/cross-origin/i);
  });

  test('should show settings tabs', async ({ page }) => {
    // Should have multiple tabs
    const tabs = page.locator('button').filter({ hasText: /general|searcher|downloader|renamer|notification/i });
    await expect(tabs.first()).toBeVisible({ timeout: 5000 });
  });

  test('settings helpers resolve only their owning panel', async ({ page }) => {
    const result = await page.evaluate(() => {
      const root = document.querySelector('[x-data="settingsPanel()"]');
      if (!root) throw new Error('settingsPanel root is absent');

      const child = document.createElement('div');
      root.appendChild(child);
      const owner = (window as any).Alpine.$data(root);
      owner.__testOwnerMarker = 'owning-panel';
      const components = [
        (window as any).buttonField('test', {}),
        (window as any).traktDeviceAuth(),
        (window as any).combinedField('test', {}),
        (window as any).directoriesField('test', {}),
      ];
      const fromOwner = components.map((component) => component.getPanel.call({ $el: child }));

      child.remove();
      const fromDetachedChild = components.map((component) => component.getPanel.call({ $el: child }));

      return {
        foundOwner: fromOwner.every((panel) => panel?.__testOwnerMarker === 'owning-panel'),
        detachedIsIsolated: fromDetachedChild.every((panel) => panel === null),
      };
    });

    expect(result).toEqual({ foundOwner: true, detachedIsIsolated: true });
  });

  test('reloading settings does not multiply panel watchers', async ({ page }) => {
    const updateCount = await page.evaluate(async () => {
      const root = document.querySelector('[x-data="settingsPanel()"]');
      if (!root) throw new Error('settingsPanel root is absent');
      const panel = (window as any).Alpine.$data(root);

      await Promise.all([panel.init(), panel.init()]);

      let calls = 0;
      const original = panel.updateCurrentGroups;
      panel.updateCurrentGroups = (...args: unknown[]) => {
        calls += 1;
        return original.apply(panel, args);
      };
      panel.activeTab = panel.activeTab === 'general' ? 'logs' : 'general';
      await new Promise<void>((resolve) => panel.$nextTick(resolve));
      return calls;
    });

    expect(updateCount).toBe(1);
  });

  test('should be able to switch tabs', async ({ page }) => {
    // Both tabs are among the always-present default set this file's own
    // "should show settings tabs" test pins -- the old
    // `if (await X.isVisible())` guards could never be false, and neither
    // click was ever checked for a real effect either way.
    const searcherTab = page.getByRole('tab', { name: /searcher/i });
    await expect(searcherTab).toBeVisible();
    await searcherTab.click();
    await expect(searcherTab).toHaveAttribute('aria-selected', 'true');

    const downloadersTab = page.getByRole('tab', { name: /downloader/i });
    await expect(downloadersTab).toBeVisible();
    await downloadersTab.click();
    await expect(downloadersTab).toHaveAttribute('aria-selected', 'true');
    // Switching tabs is exclusive: the previous tab must give up selection.
    await expect(searcherTab).toHaveAttribute('aria-selected', 'false');
  });

  test('should show Advanced toggle', async ({ page }) => {
    // Should have Advanced toggle
    const advancedToggle = page.getByText(/advanced/i);
    await expect(advancedToggle.first()).toBeVisible({ timeout: 5000 });
  });

  test('should show Logs tab', async ({ page }) => {
    // Should have Logs tab
    const logsTab = page.locator('button').filter({ hasText: /logs/i }).first();
    await expect(logsTab).toBeVisible({ timeout: 5000 });
    
    // Click Logs tab
    await logsTab.click();
    
    // Should show log-related controls
    const refreshButton = page.getByRole('button', { name: /refresh/i });
    await expect(refreshButton).toBeVisible({ timeout: 5000 });
  });

  test('visual option captions match their control accessible names', async ({ page }) => {
    const captionExpression = "opt.label || opt.name.replace(/_/g, ' ')";

    // Each case is asserted in a SETTLED state. After a tab switch the page
    // reuses cards by index (settings.html `:key="groupIdx"`), so the previous
    // tab's provider panel stays visible for ~100ms while it fades out
    // (provider_card.html `x-transition`). The Searchers tab has no open
    // provider panel once settled, so a provider caption found there is only
    // the fading General panel. The provider case therefore runs on General,
    // where the always-open `core.basics` group (Username, Password, Port)
    // gives it a caption that is still there after the page has settled.
    const assertCaptionMatchesControl = async (source: string, caption: Locator) => {
      await expect(caption, `${source} did not render a visual option caption`).toBeVisible();
      const visibleText = (await caption.textContent())?.trim() || '';
      expect(visibleText, `${source} rendered an empty visual caption`).not.toBe('');

      const control = caption.locator('..').locator('input:visible, select:visible, textarea:visible, button:visible').first();
      await expect(control, `${source} caption had no rendered control`).toBeVisible();
      await expect(control, `${source} control name drifted from its visible caption`).toHaveAccessibleName(visibleText);
    };

    const generalTab = page.getByRole('tab', { name: /general/i });
    await expect(generalTab).toHaveAttribute('aria-selected', 'true');
    await assertCaptionMatchesControl(
      'provider settings',
      page.locator(`span[aria-hidden="true"][x-text="${captionExpression}"][x-show]:visible`).first(),
    );

    const searcherTab = page.getByRole('tab', { name: /searcher/i });
    await expect(searcherTab).toBeVisible();
    await searcherTab.click();
    await expect(searcherTab).toHaveAttribute('aria-selected', 'true');
    await assertCaptionMatchesControl(
      'combined settings',
      page.locator(`span[aria-hidden="true"][x-text="${captionExpression}"]:not([x-show]):visible`).first(),
    );
  });

  test('Jackett sync button should have description (DEF-003)', async ({ page }) => {
    // Searchers is one of the always-present default tabs (see "should show
    // settings tabs" above) -- the old `if (await searcherTab.isVisible())`
    // guard could never be false.
    const searcherTab = page.getByRole('tab', { name: /searcher/i });
    await expect(searcherTab).toBeVisible();
    await searcherTab.click();
    await expect(searcherTab).toHaveAttribute('aria-selected', 'true');

    // Measured: the sync button is an `advanced`-flagged field
    // (provider_card.html: `x-show="... (showAdvanced || !opt.advanced) &&
    // isOptionVisible(opt, group) ..."`), so switching Advanced on is
    // necessary -- but `isOptionVisible` (scripts.html) ALSO gates it on
    // `show_when`, which for Jackett's sync action is tied to the provider's
    // own enabler toggle. Enabling Jackett for real is a side effect this
    // test should not cause (it is disabled in a fresh seed/config), so
    // unlike the "advanced" gate, that part of the precondition is genuinely
    // out of this test's control. Both branches now assert something,
    // instead of "not visible" silently reading as "test passed".
    const advancedToggle = page.getByRole('switch', { name: /show advanced settings/i });
    await expect(advancedToggle).toBeVisible();
    await advancedToggle.click();

    const jackettSync = page.locator('button').filter({ hasText: /sync/i }).first();
    if (await jackettSync.isVisible({ timeout: 5000 })) { // vacuous-guard-ok: the sync action is also gated on Jackett's own enabler toggle (show_when), which this test does not flip -- enabling a provider for real is a side effect out of scope here.
      // The description should be visible nearby (not "undefined")
      const parent = jackettSync.locator('..');
      const descriptionText = await parent.locator('p').textContent();

      // Description should exist and not be "undefined"
      expect(descriptionText).not.toBe('undefined');
      expect(descriptionText).not.toContain('undefined');
    } else {
      // Still in the DOM (x-show, not v-if), just hidden -- toBeHidden, not
      // toHaveCount(0).
      await expect(jackettSync).toBeHidden();
    }
  });

  test('the "Require login" toggle renders and reflects the stored value', async ({ page }) => {
    // Raised by claude-review on #226: `auth_required` was covered only by
    // Python unit tests, so nothing failed if the operator could not actually
    // find or read the control. That is not a hypothetical gap in this repo --
    // `fanarttv.py` shipped a settings block copied faithfully from
    // themoviedb's (`tab: 'providers'` + `hidden: True`) that `hiddenTabs`
    // filters out entirely, so its key could only be set by hand-editing
    // config.ini. A security toggle nobody can reach is worse than no toggle.
    //
    // WHAT THIS TEST ACTUALLY PROVES, stated plainly because the obvious
    // reading over-claims:
    //
    //   STRONG -- the control is reachable, is a checkbox, and carries the
    //   accessible name "Require login". This is the half that guards the real
    //   failure mode above, and it is load-bearing: removing the option from
    //   `_core.py`'s config block, or moving it to a tab `hiddenTabs` filters,
    //   fails it.
    //
    //   WEAK -- the checked-state comparison. `scripts/seed_e2e_data.py` starts
    //   every worker's instance with NO password, so `runner.py`'s startup
    //   resolution writes `auth_required = 0` and the expected state is always
    //   `false`. A binding hardcoded to `false` would therefore pass. This is
    //   recorded rather than dressed up: it is a real limit of the fixture, not
    //   a property of the code.
    //
    // The obvious way to make it strong -- toggle it and assert the round-trip
    // -- is deliberately NOT done. Turning `auth_required` on against an
    // instance with no password is exactly the lock-out state PR #226 exists to
    // prevent: every page request is then denied, and a failure between the two
    // writes would leave that worker's server locked for every subsequent test
    // in this file. A flaky guard is worse than an absent one. Making this
    // strong properly means seeding a password-protected instance, which is its
    // own fixture change.
    const toggle = page.getByRole('checkbox', { name: 'Require login' });
    await expect(toggle).toBeVisible({ timeout: 5000 });

    // Read the persisted value through the page so the test needs no api_key
    // of its own -- CP.apiBase is set in base.html.
    const stored = await page.evaluate(async () => {
      const resp = await fetch((window as any).CP.apiBase + '/settings/');
      const data = await resp.json();
      return data?.values?.core?.auth_required;
    });

    // The API must actually return the key. Without this the comparison below
    // would be `false === false` for an ABSENT setting -- passing while
    // proving nothing, which is the vacuous shape this repo keeps catching.
    expect(stored, 'core.auth_required missing from the settings API').not.toBeUndefined();

    // `Settings.get` coerces via the registered 'bool' type by the time the
    // API is called, so this is a real boolean rather than '0'/'1'.
    await expect(toggle).toBeChecked({ checked: Boolean(stored) });
  });

  test('should auto-save settings', async ({ page }) => {
    let savedValue: string | null = null;
    await page.route('**/settings.save/**', async (route) => {
      savedValue = new URLSearchParams(route.request().postData() || '').get('value');
      await route.fulfill({
        status: 200,
        contentType: 'application/json',
        body: JSON.stringify({ success: true }),
      });
    });

    // `:visible`, not `.first()` on the bare selector: General has
    // `advanced`-flagged text inputs earlier in DOM order that are
    // `x-show`-hidden until Advanced settings are shown (see the Jackett
    // sync test above for the same gating mechanism) -- `.first()` on the
    // unscoped locator picked one of those, so `isVisible()` on it was
    // false by construction and this always fell through to nothing being
    // asserted. General always renders at least one plain (non-advanced)
    // text field, so this is unconditional.
    const firstInput = page.getByRole('textbox', { name: 'Username' });
    await expect(firstInput).toBeVisible({ timeout: 5000 });

    const originalValue = await firstInput.inputValue();
    const nextValue = originalValue === 'test-value-123' ? 'test-value-456' : 'test-value-123';
    await firstInput.fill(nextValue);
    await firstInput.blur();

    await expect.poll(() => savedValue).toBe(nextValue);

    // Should show "Saved" indicator
    const savedIndicator = page.getByText(/saved/i);
    await expect(savedIndicator.first()).toBeVisible({ timeout: 5000 });
  });

  test('a rewritten setting name stays complete in the refusal announcement', async ({ page }) => {
    await page.route('**/settings.save/**', async (route) => {
      await route.fulfill({
        status: 200,
        contentType: 'application/json',
        body: JSON.stringify({ success: true, changed: true, value: false }),
      });
    });

    const state = await page.evaluate(async () => {
      const root = document.querySelector('[x-data="settingsPanel()"]');
      if (!root) throw new Error('settingsPanel root is absent');
      const panel = (window as any).Alpine.$data(root);
      await panel.saveSingle('core', 'auth_required_guard', true);
      return { saving: panel.saving, lastSaved: panel.lastSaved };
    });

    const expected = 'auth required guard could not be set to that value; the server stored "false" instead. Check the log for the reason.';
    expect(state).toEqual({ saving: false, lastSaved: false });
    await expect(page.getByTestId('settings-announcer-assertive')).toHaveText(expected);
    await expect(page.getByTestId('settings-announcer-polite')).toBeEmpty();
    const visibleToast = page.locator('[x-show="message"][x-text="message"]');
    await expect(visibleToast).toHaveText(expected);
    await expect(visibleToast).toBeVisible();
    await expect(page.getByText('Saved', { exact: true })).toBeHidden();
  });
});

/**
 * T48: a password field must not let the operator destroy a stored credential
 * by editing the mask.
 *
 * `getValues()` renders a password-typed option as a run of asterisks. Without
 * clear-on-focus, clicking into the field puts the cursor AFTER that mask, so
 * pasting a new token stores `********xoxb-NEW` -- the old credential is gone
 * and the new one is corrupt, while the UI reports success. On this project's
 * loss ranking a stored credential is irreplaceable: the user has to re-issue
 * it at the provider, and for a tracker passkey that can mean contacting staff.
 *
 * The server-side guard in `Settings.saveView` cannot cover this. Any predicate
 * loose enough to reject `********xoxb-NEW` also rejects a human password
 * containing an asterisk, and refusing THOSE was measurably worse -- it left
 * first-run instances unauthenticated. So the browser is the only layer that
 * can tell "the user touched this field", and this test is what proves that
 * layer works.
 *
 * Deliberately driven in a real browser rather than asserted against the
 * template: the behaviour under test IS the DOM event sequence.
 */
test.describe('Settings: a password field cannot be half-edited', () => {
  /**
   * Find a rendered password input, or fail with a reason rather than pass.
   *
   * Stubs the save endpoint FIRST. Without that these tests were destructive:
   * clearing the field on focus and then blurring fires `@change`, which saves
   * an EMPTY value over a real credential. CI caught it -- the first test wiped
   * the downloader's password, its group collapsed, and the second test then
   * found no visible password input at all.
   *
   * Worth stating plainly: a test for the credential-destruction defect was
   * itself destroying credentials. It passed locally because the runs happened
   * to leave a usable field behind; the CI seed did not.
   *
   * These tests are about what the BROWSER does, so nothing needs to persist.
   */
  async function firstPasswordInput(page, saves?: string[]) {
    // ONE route handler. An earlier version had the caller register its own
    // capture route as well, and Playwright gives precedence to the most
    // recently added match -- so this helper's handler won, the caller's array
    // stayed empty, and the "saves nothing" test could not fail even when the
    // focus handler was mutated to save deliberately. Two competing handlers
    // for one pattern is a guard that cannot fire.
    await page.route('**/settings.save/**', async (route) => {
      if (saves) saves.push(route.request().postData() || '');
      await route.fulfill({
        status: 200,
        contentType: 'application/json',
        body: JSON.stringify({ success: true }),
      });
    });
    await page.goto('/settings/');
    await expect(page.locator('h1')).toContainText('Settings');

    // Use core.password on the GENERAL tab, not a downloader's.
    //
    // The downloaders tab was wrong and CI proved it twice. On the seeded E2E
    // config only Blackhole is enabled and it has no password field; every
    // other downloader group is collapsed by provider_card.html, so there is
    // no visible password input on that tab at all. It passed locally because
    // this checkout's data has more downloaders enabled -- a green that was
    // about my machine, not about the code.
    //
    // core.password sits in the same General-tab group as the "Require login"
    // toggle, which this file already covers with a passing test, so it is
    // present regardless of which downloaders a config happens to enable.
    const field = page.locator('input[type="password"]').first();
    await expect(
      field,
      'no password input on the General tab -- core.password should be in the ' +
        'login group beside "Require login"; if that moved, re-point this ' +
        'rather than loosening the selector',
    ).toBeVisible({ timeout: 10000 });
    return field;
  }

  /*
   * The three assertions that used to live here -- "renders empty", "does not
   * disclose length", "placeholder reflects stored state" -- moved to
   * tests/unit/test_password_field_template.py.
   *
   * They are properties of the TEMPLATE, and asserting them in a browser
   * needed a stored credential to be meaningful (without one, `getVal`
   * returns '' and the field is empty whether or not the mask is bound -- all
   * three passed against a template mutated back to the old design).
   *
   * Seeding one is not available: writing `core.password` fires
   * `Core.md5Password`, which turns `auth_required` ON, so the next page load
   * is a sign-in screen. That is the feature working correctly, and it is a
   * clear signal these belong at a level that does not need app state.
   *
   * What stays here is what genuinely needs a browser: what happens to the
   * value when a human types, and whether an untouched field posts anything.
   */

  test('typing stores only what was typed', async ({ page }) => {
    const field = await firstPasswordInput(page);

    await field.focus();
    await field.type('brand-new-secret');

    await expect(field).toHaveValue('brand-new-secret');
    expect(
      await field.inputValue(),
      'the stored value would carry mask characters into the credential',
    ).not.toContain('*');
  });

  test('focus then blur WITHOUT typing saves nothing', async ({ page }) => {
    /**
     * The load-bearing claim behind clear-on-focus, and it was documented in
     * field_types.html without ever being tested.
     *
     * If focus-and-blur DID fire `change`, then clearing on focus would post an
     * empty value and destroy the credential on every visit to the settings
     * page -- turning the mitigation into a far worse version of the bug it
     * was written for. The claim is that browsers gate change-on-blur on the
     * dirty value flag, which only real keystrokes or a paste set; a scripted
     * `.value = ''` inside the focus handler does not.
     *
     * That is a claim about browser behaviour, so it is worth nothing until a
     * browser is asked. This asks.
     *
     * Not hypothetical either: the sibling tests in this file were destructive
     * until CI caught them wiping a downloader's password through exactly this
     * save path.
     */
    const saves: string[] = [];
    const field = await firstPasswordInput(page, saves);

    await field.focus();
    await field.blur();
    // Must comfortably exceed `debounceSave`'s 500ms timer in
    // partials/settings/scripts.html. Waiting exactly 500 raced it: the POST
    // landed just after the wait ended, so the assertion saw an empty array and
    // the test passed even when the focus handler was mutated to dispatch a
    // `change` deliberately. It would have shipped as a guard that cannot fail.
    await page.waitForTimeout(1500);

    expect(
      saves,
      'focus + blur without typing posted a save -- clear-on-focus would ' +
        'destroy the stored credential on every visit to this page',
    ).toEqual([]);
  });

  test('the field is type=password, so it is not shoulder-surfable', async ({ page }) => {
    const field = await firstPasswordInput(page);
    await expect(field).toHaveAttribute('type', 'password');
  });
});

// SEC-004 AC-QA-10: a named starting configuration is written to the worker's
// config.ini BEFORE its server starts. This pins the mechanism itself, end to end:
// the file, the provider's real reader over that file, and the settings read the page
// uses must all show the fixture. Read-only, so it needs no persistence annotation.
test.describe('Settings: a named starting configuration', () => {
  test.use({ seedConfig: 'newznab_aligned#starting-configuration-check' });

  test('the test\'s server started from the fixture, and the file and the reader agree', async ({ page, testServer }) => {
    const columns = configColumns(testServer.configPath, 'newznab');
    expect(columns.use).toBe('1,0,1');
    expect(columns.api_key).toBe('placeholder-key-one,placeholder-key-two,placeholder-key-three');

    const view = configView(testServer.configPath, 'newznab') as string[][];
    expect(view.map((row) => row[0])).toEqual(['1', '0', '1']);

    const read = await page.request.get(`${testServer.apiBase}/settings/`);
    const values = (await read.json()).values.newznab;
    expect(values.api_key).toBe(columns.api_key);
    expect(values.host).toBe(columns.host);
  });
});

// SEC-004 AC-QA-19: the persistence guard covers the group-save route. `test.fail()`
// makes this pass only if the test FAILS, and the only thing that can fail it is the
// guard's teardown (the body below asserts nothing): a group save with no persistence
// annotation must fail the test, never reach the worker's config.ini unseen.
// What this cannot tell is WHICH guard failed it (the block, or the changed-file audit
// that follows); tests/unit/e2e_fixture_cleanup.test.ts pins the block on its own.
test.describe('Settings: the persistence guard covers the group-save route', () => {
  test.use({ seedConfig: 'newznab_aligned#guard-covers-group-save' });

  test('an unannotated group save fails the test at teardown', async ({ page, testServer }) => {
    test.fail(true, 'the guard must fail a test that saves a combine group without declaring it');
    await page.goto('/settings/');
    await expect(page.locator('h1')).toContainText('Settings');

    await page.evaluate(async (apiBase) => {
      await fetch(`${apiBase}/settings.save_group/`, {
        method: 'POST',
        headers: { 'content-type': 'application/json' },
        body: JSON.stringify({ section: 'newznab', rows: [{
          use: '1', host: 'https://placeholder-guard.invalid', api_key: 'placeholder-key-guard',
          extra_score: '0', custom_tag: '',
        }] }),
      });
    }, testServer.apiBase);
  });
});

// ─────────────────────────────────────────────────────────────────────────────
// SEC-004 P3: a combined field saves ONE group per request, as rows.
//
// Every test runs against its own server seeded from a named fixture
// (`seedConfig`), and asserts on the settings FILE through the provider's real
// reader (`configColumns`, `configView`, `configSha`), not only on what the page
// sent. A test that writes a combine group says so with `combineGroupWriter()` and
// owns its fixture value alone (tests/unit/e2e_seed_config_ownership.test.ts).
// ─────────────────────────────────────────────────────────────────────────────

type SeenRequest = { url: string; method: string; body: string };

/**
 * Record every request the page makes, at the network AND inside the page (a
 * wrapper round `fetch`, armed before any script runs). Two vantage points: a
 * request the route layer never saw, or one the page never made, is not read as
 * "no request".
 */
async function recordRequests(page: Page) {
  const seen: SeenRequest[] = [];
  page.on('request', (request) => seen.push({
    url: request.url(), method: request.method(), body: request.postData() ?? '',
  }));
  await page.addInitScript(() => {
    const original = window.fetch.bind(window);
    const log: { url: string; method: string; body: string }[] = [];
    (window as any).__fetches = log;
    window.fetch = (input: RequestInfo | URL, init?: RequestInit) => {
      log.push({
        url: String(input instanceof Request ? input.url : input),
        method: init?.method ?? 'GET',
        body: typeof init?.body === 'string' ? init.body : String(init?.body ?? ''),
      });
      return original(input, init);
    };
  });
  const writes = (all: SeenRequest[]) => all.filter((request) => /settings\.save(_group)?\//.test(request.url));
  return {
    seen,
    networkWrites: () => writes(seen),
    pageWrites: async () => writes(await page.evaluate(() => (window as any).__fetches as SeenRequest[])),
    groupSaves: () => seen.filter((request) => request.url.includes('settings.save_group') && request.method === 'POST'),
  };
}

async function openSettings(page: Page, tab?: string) {
  await page.goto('/settings/');
  await expect(page.locator('h1')).toContainText('Settings');
  if (tab) await page.getByRole('tab', { name: tab }).click();
}

function providerCard(page: Page, heading: string): Locator {
  return page.locator('.bg-cp-card', { has: page.getByRole('heading', { name: heading, exact: true }) });
}

/** A disabled provider is collapsed; opening it saves nothing. An enabled one is already open. */
async function openCard(card: Locator) {
  const closed = card.locator('h3 button[aria-expanded="false"]');
  // The assertion below fails if the card is not open afterwards, so the guard cannot hide a failure.
  if (await closed.count()) await closed.click(); // vacuous-guard-ok: idempotent open, an enabled provider starts open
  await expect(card.locator('h3 button[aria-expanded="true"]')).toHaveCount(1);
}

function groupSaveResponse(page: Page): Promise<Response> {
  return page.waitForResponse((response) => response.url().includes('settings.save_group')
    && response.request().method() === 'POST');
}

/**
 * Let every pending debounce fire, then wait for the network to go quiet. The page
 * debounces edits by 500ms, so a negative assertion read at the same instant as the
 * event would pass while a save is still scheduled. Needs `page.clock.install()`
 * before the page loads.
 */
async function settleDebounce(page: Page) {
  await page.clock.fastForward(5000);
  await page.waitForLoadState('networkidle');
}

const NEWZNAB_HOSTS = ['one', 'two', 'three'].map((word) => `https://placeholder-${word}.invalid/api`);
const NEWZNAB_KEYS = ['one', 'two', 'three'].map((word) => `placeholder-key-${word}`);

test.describe('Settings: a refused combined-field save, against the real server', () => {
  test.use({ seedConfig: 'newznab_aligned#real-refusal' });

  test('a comma in row 2 is refused inline, below row 2, writes nothing and moves no focus', async ({ page, testServer }) => {
    // The refused request must reach the real server, so it is let through; a refusal
    // writes nothing, which the file hash below proves.
    test.info().annotations.push({ type: SETTINGS_PERSISTENCE_ANNOTATION });
    await page.clock.install();
    const net = await recordRequests(page);
    const before = configSha(testServer.configPath);
    await openSettings(page, 'Searchers');
    const card = providerCard(page, 'Newznab');
    const host = card.getByLabel('host for row 2', { exact: true });

    const refused = groupSaveResponse(page);
    await host.fill(`${NEWZNAB_HOSTS[1]},https://placeholder-evil.invalid`);
    await host.focus();
    await page.clock.fastForward(600);
    const body = await (await refused).json();

    expect(body.success).toBe(false);
    const error = card.getByTestId('combine-row-error');
    await expect(error).toHaveCount(1);
    await expect(error).toHaveText('Row 2: the host cannot contain a comma. Remove it to save.');
    // Directly below row 2 and before row 3: the error sits between the two rows' inputs.
    const order = await card.locator('input[aria-label$="for row 2"], [data-testid="combine-row-error"], input[aria-label$="for row 3"]')
      .evaluateAll((nodes) => nodes.map((node) => node.getAttribute('data-testid') ?? node.getAttribute('aria-label')));
    expect(order.indexOf('combine-row-error')).toBeGreaterThan(order.findIndex((name) => name?.endsWith('for row 2')));
    expect(order.indexOf('combine-row-error')).toBeLessThan(order.findIndex((name) => name?.endsWith('for row 3')));
    // Only row 2's host is marked, with the danger token, and its description resolves.
    await expect(card.locator('[aria-invalid="true"]')).toHaveCount(1);
    await expect(host).toHaveAttribute('aria-invalid', 'true');
    const describedBy = await host.getAttribute('aria-describedby');
    await expect(page.locator(`[id="${describedBy}"]`)).toHaveText(/Row 2: the host/);
    const marked = await host.evaluate((input) => {
      const probe = document.createElement('div');
      probe.className = 'border border-cp-danger';
      document.body.append(probe);
      const expected = getComputedStyle(probe).borderTopColor;
      probe.remove();
      return getComputedStyle(input).borderTopColor === expected;
    });
    expect(marked).toBe(true);
    // The text never carries the typed value, and no per-column toast appears.
    await expect(error).not.toContainText('evil');
    await expect(page.getByText(/Could not save/)).toHaveCount(0);
    // Never "Saved", and the focused element did not move.
    await expect(page.getByText('Saved', { exact: true })).toBeHidden();
    await expect(host).toBeFocused();
    // The file, read from disk, is exactly what it was; the page sent one group save.
    expect(configSha(testServer.configPath)).toBe(before);
    expect(net.groupSaves()).toHaveLength(1);
    expect(net.networkWrites().filter((request) => request.url.includes('settings.save/'))).toEqual([]);

    // A11Y-2: nothing removes the message on a timer.
    await page.clock.fastForward(10_000);
    await expect(error).toBeVisible();
    await expect(host).toHaveAttribute('aria-invalid', 'true');
  });

  test('a refusal survives a tab change, and the refused value is not shown as saved', async ({ page, testServer }) => {
    test.info().annotations.push({ type: SETTINGS_PERSISTENCE_ANNOTATION });
    await page.clock.install();
    const before = configSha(testServer.configPath);
    await openSettings(page, 'Searchers');
    const card = providerCard(page, 'Newznab');
    const host = card.getByLabel('host for row 2', { exact: true });
    const refused = groupSaveResponse(page);
    await host.fill(`${NEWZNAB_HOSTS[1]},https://placeholder-evil.invalid`);
    await page.clock.fastForward(600);
    await refused;
    await expect(card.getByTestId('combine-row-error')).toHaveCount(1);

    await page.getByRole('tab', { name: 'General' }).click();
    await page.getByRole('tab', { name: 'Searchers' }).click();

    const rebuilt = providerCard(page, 'Newznab');
    const rebuiltHost = rebuilt.getByLabel('host for row 2', { exact: true });
    await expect(rebuiltHost).toHaveAttribute('aria-invalid', 'true');
    await expect(rebuiltHost).toHaveValue(`${NEWZNAB_HOSTS[1]},https://placeholder-evil.invalid`);
    await expect(rebuilt.getByTestId('combine-row-error')).toHaveText(/Row 2: the host/);
    expect(configSha(testServer.configPath)).toBe(before);
  });

  test('a refusal does not move focus whichever control had it: another cell, or a use switch', async ({ page }) => {
    test.info().annotations.push({ type: SETTINGS_PERSISTENCE_ANNOTATION });
    await page.clock.install();
    await openSettings(page, 'Searchers');
    const card = providerCard(page, 'Newznab');
    const host = card.getByLabel('host for row 2', { exact: true });

    const refused = groupSaveResponse(page);
    await host.fill(`${NEWZNAB_HOSTS[1]},https://placeholder-evil.invalid`);
    await page.keyboard.press('Tab');
    await expect(card.getByLabel('api key for row 2', { exact: true })).toBeFocused();
    await page.clock.fastForward(600);
    await refused;
    await expect(card.getByTestId('combine-row-error')).toHaveCount(1);
    await expect(card.getByLabel('api key for row 2', { exact: true })).toBeFocused();

    await page.keyboard.press('Shift+Tab');
    await page.keyboard.press('Shift+Tab');
    await expect(card.getByRole('switch', { name: 'Enable row 2' })).toBeFocused();
    await page.clock.fastForward(5000);
    await page.waitForLoadState('networkidle');
    await expect(card.getByRole('switch', { name: 'Enable row 2' })).toBeFocused();
  });
});

test.describe('Settings: the refusal text is composed by the page for every combine group', () => {
  test.use({ seedConfig: 'all_groups_aligned#message-shape' });

  const GROUPS: [string, string, string, string][] = [
    // The refused column is the KEY column of the first two: its option key (api_key,
    // pass_key) and its label (api key, pass key) differ, so a message that names the raw
    // key fails the text and the underscore checks below. `host` would not tell them apart.
    ['Searchers', 'Newznab', 'api_key', 'api_key'],
    ['Searchers', 'TorrentPotato', 'pass_key', 'pass_key'],
    ['Suggestions', 'IMDB Watchlist', 'automation_urls', 'automation_urls_use'],
    ['Suggestions', 'iTunes', 'automation_urls', 'automation_urls_use'],
    ['Suggestions', 'Letterboxd', 'automation_urls', 'automation_urls_use'],
  ];

  for (const [tab, heading, column] of GROUPS.map(([a, b, c]) => [a, b, c])) {
    test(`${heading}: the message names the row and the field, and nothing else`, async ({ page }) => {
      await page.route('**/settings.save_group/**', (route) => route.fulfill({
        status: 200,
        contentType: 'application/json',
        body: JSON.stringify({
          success: false, error: 'A cell cannot contain a comma.',
          invalid: [{ row: 0, column, reason: 'comma' }],
        }),
      }));
      await page.clock.install();
      await openSettings(page, tab);
      const card = providerCard(page, heading);
      await openCard(card);
      const field = card.getByLabel(`${column.replace(/_/g, ' ')} for row 1`, { exact: true });

      await field.fill('placeholder-secret-value');
      await page.clock.fastForward(600);

      const text = (await card.getByTestId('combine-row-error').innerText()).trim();
      expect(text).toBe(`Row 1: the ${column.replace(/_/g, ' ')} cannot contain a comma. Remove it to save.`);
      expect(text).not.toMatch(/placeholder|_|\w\.\w|Error:|HTTP|\b[45]\d\d\b/);
      await expect(field).toHaveAttribute('aria-invalid', 'true');
    });
  }
});

test.describe('Settings: a refusal shaped like the server\'s, with two offending cells', () => {
  test.use({ seedConfig: 'newznab_aligned#two-cells' });

  test('marks both inputs, each described by its own visible message', async ({ page }) => {
    await page.route('**/settings.save_group/**', (route) => route.fulfill({
      status: 200,
      contentType: 'application/json',
      body: JSON.stringify({
        success: false, error: 'A cell cannot contain a comma.',
        invalid: [{ row: 1, column: 'host', reason: 'comma' }, { row: 1, column: 'api_key', reason: 'comma' }],
      }),
    }));
    await page.clock.install();
    await openSettings(page, 'Searchers');
    const card = providerCard(page, 'Newznab');

    await card.getByLabel('host for row 2', { exact: true }).fill('x');
    await page.clock.fastForward(600);

    await expect(card.locator('[aria-invalid="true"]')).toHaveCount(2);
    for (const [label, words] of [['host for row 2', /Row 2: the host/], ['api key for row 2', /Row 2: the api key/]] as const) {
      const input = card.getByLabel(label, { exact: true });
      const target = page.locator(`[id="${await input.getAttribute('aria-describedby')}"]`);
      await expect(target).toBeVisible();
      await expect(target).toHaveText(words);
    }
  });
});

test.describe('Settings: a save that fails for any other reason', () => {
  test.use({ seedConfig: 'newznab_aligned#other-failures' });

  const FAILURES: [string, { status: number; body: string }][] = [
    ['a server that no longer has the route', { status: 200, body: JSON.stringify({ success: false, error: "API call doesn't exist" }) }],
    ['an HTTP 500', { status: 500, body: 'Internal Server Error' }],
  ];

  for (const [name, reply] of FAILURES) {
    test(`shows the failure, keeps the rows, and never says Saved: ${name}`, async ({ page }) => {
      await page.route('**/settings.save_group/**', (route) => route.fulfill({ ...reply, contentType: 'application/json' }));
      await page.clock.install();
      await openSettings(page, 'Searchers');
      const card = providerCard(page, 'Newznab');
      const host = card.getByLabel('host for row 1', { exact: true });

      await host.fill('https://placeholder-typed.invalid/api');
      await page.clock.fastForward(600);

      await expect(card.getByTestId('combine-save-error')).toBeVisible();
      await expect(host).toHaveValue('https://placeholder-typed.invalid/api');
      await expect(page.getByText('Saved', { exact: true })).toBeHidden();
      await page.getByRole('tab', { name: 'General' }).click();
      await page.getByRole('tab', { name: 'Searchers' }).click();
      await expect(providerCard(page, 'Newznab').getByLabel('host for row 1', { exact: true }))
        .toHaveValue('https://placeholder-typed.invalid/api');
      await expect(providerCard(page, 'Newznab').getByTestId('combine-save-error')).toBeVisible();
    });
  }
});

test.describe('Settings: a refusal is announced once, through one channel, and recovery says Saved once', () => {
  test.use({ seedConfig: 'newznab_aligned#announce-and-recover' });

  test('typing past a refusal does not re-announce it; clearing and re-adding the comma does, once', async ({ page, testServer }) => {
    // The comma is removed again at the end, so the group is saved with the cells it started
    // with: this test writes the group (one successful save) and owns its fixture value.
    test.info().annotations.push(...combineGroupWriter());
    await page.clock.install();
    const net = await recordRequests(page);
    await openSettings(page, 'Searchers');
    const card = providerCard(page, 'Newznab');
    const host = card.getByLabel('host for row 2', { exact: true });
    // Armed BEFORE the first keystroke. Counts how often a live region (aria-live,
    // role=alert, role=status) comes to hold the text, across ALL of them together, so a
    // refusal sent through two channels counts twice.
    await page.evaluate(() => {
      const state = { refusal: 0, saved: 0, last: new Map<Element, string>() };
      (window as any).__live = state;
      const live = '[aria-live], [role="alert"], [role="status"]';
      new MutationObserver((records) => {
        const touched = new Set<Element>();
        for (const record of records) {
          const node = record.target instanceof Element ? record.target : record.target.parentElement;
          const region = node?.closest(live);
          if (region) touched.add(region);
        }
        for (const region of touched) {
          // innerText, not textContent: the header's status region always holds its hidden
          // "Saved" span, which is not announced until it is shown.
          const text = (region as HTMLElement).innerText ?? '';
          const before = state.last.get(region) ?? '';
          if (text.includes('cannot contain a comma') && !before.includes('cannot contain a comma')) state.refusal += 1;
          if (/\bSaved\b/.test(text) && !/\bSaved\b/.test(before)) state.saved += 1;
          state.last.set(region, text);
        }
      }).observe(document.body, { subtree: true, childList: true, characterData: true, attributes: true });
    });
    const counts = () => page.evaluate(() => {
      const { refusal, saved } = (window as any).__live;
      return { refusal, saved };
    });
    const typeAndSave = async (key: string) => {
      const answered = groupSaveResponse(page);
      await page.keyboard.press(key);
      await page.clock.fastForward(600);
      return (await answered).json();
    };

    await host.click();
    await page.keyboard.press('End');
    expect((await typeAndSave(',')).success).toBe(false);
    await expect(card.getByTestId('combine-row-error')).toHaveCount(1);
    for (const key of ['a', 'b', 'c', 'd', 'e']) expect((await typeAndSave(key)).success).toBe(false);
    expect(await counts()).toEqual({ refusal: 1, saved: 0 });

    // Backspace over the five letters and the comma: the last one saves.
    for (const key of ['Backspace', 'Backspace', 'Backspace', 'Backspace', 'Backspace']) {
      expect((await typeAndSave(key)).success).toBe(false);
    }
    expect(await counts()).toEqual({ refusal: 1, saved: 0 });
    expect((await typeAndSave('Backspace')).success).toBe(true);
    await expect(card.getByTestId('combine-row-error')).toHaveCount(0);
    await expect(host).not.toHaveAttribute('aria-invalid', 'true');
    await expect(page.getByText('Saved', { exact: true })).toBeVisible();
    expect(await counts()).toEqual({ refusal: 1, saved: 1 });

    // The comma again is a NEW refusal: announced again, exactly once more.
    expect((await typeAndSave(',')).success).toBe(false);
    await expect(card.getByTestId('combine-row-error')).toHaveCount(1);
    expect(await counts()).toEqual({ refusal: 2, saved: 1 });
    // One group save per edit (1 comma, 5 letters, 6 backspaces, 1 comma), nothing per
    // column, and the file holds the original host: the refused cell was never written.
    expect(net.groupSaves()).toHaveLength(13);
    expect(net.networkWrites().filter((request) => request.url.includes('settings.save/'))).toEqual([]);
    expect(configColumns(testServer.configPath, 'newznab').host).toBe(NEWZNAB_HOSTS.join(','));
  });
});

test.describe('Settings: the starting configurations write nothing on load', () => {
  for (const shape of ['all_groups_aligned', 'all_groups_misaligned', 'newznab_legacy_bytes']) {
    test.describe(shape, () => {
      test.use({ seedConfig: `${shape}#no-write-on-load` });

      test('opening Settings, visiting every tab and expanding every group sends no save and leaves the file alone', async ({ page, testServer }) => {
        await page.clock.install();
        const net = await recordRequests(page);
        const before = configSha(testServer.configPath);
        await openSettings(page);

        for (const name of await page.getByRole('tab').allInnerTexts()) {
          await page.getByRole('tab', { name }).click();
          // Each click opens one group, so the next closed one is always the first.
          const closed = page.locator('h3 button[aria-expanded="false"]');
          for (let remaining = await closed.count(); remaining > 0; remaining -= 1) await closed.first().click();
        }
        await settleDebounce(page);

        expect(net.networkWrites()).toEqual([]);
        expect(await net.pageWrites()).toEqual([]);
        expect(configSha(testServer.configPath)).toBe(before);
      });
    });
  }
});

/** Fill one cell, let the debounce fire, and return the group save's answer. */
async function editCell(page: Page, card: Locator, label: string, value: string) {
  const answered = groupSaveResponse(page);
  await card.getByLabel(label, { exact: true }).fill(value);
  await page.clock.fastForward(600);
  return (await answered).json();
}

const cellsOf = (value: string | null) => (value ?? '').split(',');

test.describe('Settings: deleting a row saves the rows that are left, each with its own cells', () => {
  test.describe('newznab: delete the middle row', () => {
    test.use({ seedConfig: 'newznab_aligned#delete-middle' });

    test('rows A and C are stored with their own values', async ({ page, testServer }) => {
      test.info().annotations.push(...combineGroupWriter());
      await page.clock.install();
      await openSettings(page, 'Searchers');
      const card = providerCard(page, 'Newznab');

      const answered = groupSaveResponse(page);
      await card.getByRole('button', { name: 'Remove row 2' }).click();
      await page.clock.fastForward(600);
      expect((await (await answered).json()).success).toBe(true);
      await page.waitForLoadState('networkidle');

      const columns = configColumns(testServer.configPath, 'newznab');
      expect(columns).toEqual({
        use: '1,1',
        host: [NEWZNAB_HOSTS[0], NEWZNAB_HOSTS[2]].join(','),
        api_key: [NEWZNAB_KEYS[0], NEWZNAB_KEYS[2]].join(','),
        extra_score: '5,15',
        custom_tag: 'tag-one,tag-three',
      });
      expect(configEnabled(testServer.configPath, 'newznab')).toEqual({ reader_raises: false, rows: [true, true] });
      expect((configView(testServer.configPath, 'newznab') as string[][]).map((row) => row[2])).toEqual([NEWZNAB_KEYS[0], NEWZNAB_KEYS[2]]);
    });
  });

  test.describe('newznab: edit row C, then delete row A before the debounce fires', () => {
    test.use({ seedConfig: 'newznab_aligned#edit-then-delete' });

    test('stores B and the edited C, and no key against a host it was not entered for', async ({ page, testServer }) => {
      test.info().annotations.push(...combineGroupWriter());
      await page.clock.install();
      const net = await recordRequests(page);
      await openSettings(page, 'Searchers');
      const card = providerCard(page, 'Newznab');

      await card.getByLabel('api key for row 3', { exact: true }).fill('placeholder-key-edited');
      const answered = groupSaveResponse(page);
      await card.getByRole('button', { name: 'Remove row 1' }).click();
      expect(net.groupSaves()).toHaveLength(0);
      await page.clock.fastForward(600);
      expect((await (await answered).json()).success).toBe(true);
      await page.waitForLoadState('networkidle');

      expect(net.groupSaves()).toHaveLength(1);
      expect(configColumns(testServer.configPath, 'newznab')).toEqual({
        use: '0,1',
        host: [NEWZNAB_HOSTS[1], NEWZNAB_HOSTS[2]].join(','),
        api_key: [NEWZNAB_KEYS[1], 'placeholder-key-edited'].join(','),
        extra_score: '10,15',
        custom_tag: 'tag-two,tag-three',
      });
    });
  });

  test.describe('torrentpotato: delete the middle row', () => {
    test.use({ seedConfig: 'torrentpotato_aligned#delete-middle' });

    test('rows A and C keep their pass key, name, seed ratio, seed time and extra score', async ({ page, testServer }) => {
      test.info().annotations.push(...combineGroupWriter());
      await page.clock.install();
      await openSettings(page, 'Searchers');
      const card = providerCard(page, 'TorrentPotato');
      await openCard(card);

      const answered = groupSaveResponse(page);
      await card.getByRole('button', { name: 'Remove row 2' }).click();
      await page.clock.fastForward(600);
      expect((await (await answered).json()).success).toBe(true);
      await page.waitForLoadState('networkidle');

      expect(configColumns(testServer.configPath, 'torrentpotato')).toMatchObject({
        use: '1,1',
        pass_key: 'placeholder-pass-one,placeholder-pass-three',
        name: 'name-one,name-three',
        seed_ratio: '1,3',
        seed_time: '40,60',
        extra_score: '0,10',
      });
      expect(configEnabled(testServer.configPath, 'torrentpotato')).toEqual({ reader_raises: false, rows: [true, true] });
    });
  });
});

test.describe('Settings: a misaligned group is saved only as the rows the user saw', () => {
  const SHAPES: [string, string, string, string, string][] = [
    ['newznab_misaligned_key_short', 'newznab', 'Newznab', 'api key for row 3', 'host for row 1'],
    ['newznab_misaligned_use_short', 'newznab', 'Newznab', 'api key for row 3', 'host for row 1'],
    ['torrentpotato_misaligned', 'torrentpotato', 'TorrentPotato', 'pass key for row 3', 'host for row 1'],
    ['torrentpotato_use_short', 'torrentpotato', 'TorrentPotato', 'pass key for row 3', 'host for row 1'],
  ];

  for (const [fixture, section, heading, thirdKey, edited] of SHAPES) {
    test.describe(fixture, () => {
      test.use({ seedConfig: `${fixture}#first-edit` });

      test('shows the notice, writes nothing on load, and the first edit saves the rows on screen', async ({ page, testServer }) => {
        test.info().annotations.push(...combineGroupWriter());
        await page.clock.install();
        const before = configSha(testServer.configPath);
        await openSettings(page, 'Searchers');
        const card = providerCard(page, heading);
        await openCard(card);
        await expect(card.getByTestId('combine-misaligned-notice')).toBeVisible();
        await expect(card.getByTestId('combine-misaligned-notice')).toContainText('do not line up');
        await settleDebounce(page);
        expect(configSha(testServer.configPath)).toBe(before);

        // What is on screen is what is saved: row 3's key as the page shows it.
        const shownKey = await card.getByLabel(thirdKey, { exact: true }).inputValue();
        const shownHosts = await card.locator('input[aria-label^="host for row"]').evaluateAll(
          (inputs) => inputs.map((input) => (input as HTMLInputElement).value));
        const shownKeys = await card.locator(`input[aria-label^="${thirdKey.split(' for ')[0]} for row"]`).evaluateAll(
          (inputs) => inputs.map((input) => (input as HTMLInputElement).value));
        expect((await editCell(page, card, edited, `${shownHosts[0]}x`)).success).toBe(true);
        await page.waitForLoadState('networkidle');

        const columns = configColumns(testServer.configPath, section);
        const lengths = new Set(Object.values(columns).map((value) => cellsOf(value).length));
        expect([...lengths]).toEqual([3]);
        expect(cellsOf(columns.host)).toEqual(shownHosts.map((host, index) => (index === 0 ? `${host}x` : host)));
        expect(cellsOf(columns[thirdKey.startsWith('api') ? 'api_key' : 'pass_key'])).toEqual(shownKeys);
        expect(shownKeys[2]).toBe(shownKey);
        // A missing use cell is saved as 0, so no row makes the real isEnabled raise.
        expect(cellsOf(columns.use).every((cell) => cell !== '')).toBe(true);
        // Exactly 0, read from the file: the cell the user never saw is saved OFF, not on.
        // (Only torrentpotato_misaligned stores three use cells; the others store two.)
        expect(cellsOf(columns.use)[2]).toBe(fixture === 'torrentpotato_misaligned' ? '1' : '0');
        const enabled = configEnabled(testServer.configPath, section);
        expect(enabled.reader_raises).toBe(false);
        expect(enabled.rows).not.toContain('raises');
        await expect(card.getByTestId('combine-misaligned-notice')).toHaveCount(0);
      });
    });
  }
});

test.describe('Settings: shapes that are NOT misaligned show no notice', () => {
  const SHAPES: [string, string, string, number][] = [
    ['fresh_defaults', 'Searchers', 'Newznab', 6],
    ['newznab_key_in_row_four', 'Searchers', 'Newznab', 6],
    ['newznab_wizard_written', 'Searchers', 'Newznab', 3],
    ['fresh_defaults', 'Suggestions', 'iTunes', 2],
    ['fresh_defaults', 'Suggestions', 'IMDB Watchlist', 1],
    ['fresh_defaults', 'Searchers', 'TorrentPotato', 2],
  ];
  for (const [fixture, tab, heading, rows] of SHAPES) {
    test.describe(`${fixture} / ${heading}`, () => {
      test.use({ seedConfig: `${fixture}#no-notice` });

      test(`shows ${rows} rows and no notice`, async ({ page }) => {
        await openSettings(page, tab);
        const card = providerCard(page, heading);
        await openCard(card);

        await expect(card.getByRole('switch', { name: /^Enable row/ })).toHaveCount(tab === 'Suggestions' ? 0 : rows);
        await expect(card.locator('[aria-label$="for row 1"]').first()).toBeVisible();
        await expect(card.locator(`[aria-label$="for row ${rows}"]`).first()).toBeVisible();
        await expect(card.locator(`[aria-label$="for row ${rows + 1}"]`)).toHaveCount(0);
        await expect(card.getByTestId('combine-misaligned-notice')).toHaveCount(0);
      });
    });
  }
});

test.describe('Settings: what the first save of an aligned shape changes, and what it leaves', () => {
  test.describe('a key in default row 4', () => {
    test.use({ seedConfig: 'newznab_key_in_row_four#edit-another-row' });

    test('the key stays at row 4 after an edit to another row, and only the host line changes', async ({ page, testServer }) => {
      test.info().annotations.push(...combineGroupWriter());
      await page.clock.install();
      const before = configColumns(testServer.configPath, 'newznab');
      await openSettings(page, 'Searchers');
      const card = providerCard(page, 'Newznab');
      await expect(card.getByLabel('api key for row 4', { exact: true })).toHaveValue('placeholder-key-four');

      const hosts = cellsOf(before.host);
      hosts[0] = 'https://placeholder-edited.invalid/api';
      expect((await editCell(page, card, 'host for row 1', hosts[0])).success).toBe(true);
      await page.waitForLoadState('networkidle');

      const after = configColumns(testServer.configPath, 'newznab');
      expect(after.api_key).toBe(before.api_key);
      expect(after.use).toBe(before.use);
      expect(after.host).toBe(hosts.join(','));
    });
  });

  test.describe('the wizard-written shape', () => {
    test.use({ seedConfig: 'newznab_wizard_written#first-save' });

    test('shows three rows, and its first save drops the surplus default cells to three', async ({ page, testServer }) => {
      test.info().annotations.push(...combineGroupWriter());
      await page.clock.install();
      expect(cellsOf(configColumns(testServer.configPath, 'newznab').extra_score)).toHaveLength(6);
      await openSettings(page, 'Searchers');
      const card = providerCard(page, 'Newznab');

      expect((await editCell(page, card, 'custom tag for row 2', 'tag-edited')).success).toBe(true);
      await page.waitForLoadState('networkidle');

      const columns = configColumns(testServer.configPath, 'newznab');
      expect(columns.extra_score).toBe('0,0,0');
      expect(columns.custom_tag).toBe(',tag-edited,');
      expect(columns.host.split(',')).toHaveLength(3);
    });
  });

  test.describe('the shipped iTunes default', () => {
    test.use({ seedConfig: 'itunes_shipped#no-change-save' });

    test('a save of exactly the rows it shows leaves the file byte for byte as it was', async ({ page, testServer }) => {
      test.info().annotations.push(...combineGroupWriter());
      await page.clock.install();
      await openSettings(page, 'Suggestions');
      const card = providerCard(page, 'iTunes');
      await openCard(card);
      const before = configSha(testServer.configPath);
      const urlLabel = 'automation urls for row 1';
      const stored = await card.getByLabel(urlLabel, { exact: true }).inputValue();

      expect((await editCell(page, card, urlLabel, `${stored}x`)).success).toBe(true);
      expect(configSha(testServer.configPath)).not.toBe(before);
      expect((await editCell(page, card, urlLabel, stored)).success).toBe(true);
      await page.waitForLoadState('networkidle');

      expect(configSha(testServer.configPath)).toBe(before);
    });
  });

  test.describe('a fresh install\'s shipped torrentpotato defaults', () => {
    test.use({ seedConfig: 'fresh_defaults#torrentpotato-add-row' });

    test('stay editable and savable: one added row is read back through getHosts', async ({ page, testServer }) => {
      test.info().annotations.push(...combineGroupWriter());
      await page.clock.install();
      const net = await recordRequests(page);
      await openSettings(page, 'Searchers');
      const card = providerCard(page, 'TorrentPotato');
      await openCard(card);

      await card.getByRole('button', { name: 'Add row' }).click();
      await page.clock.fastForward(5000);
      await page.waitForLoadState('networkidle');
      expect(net.groupSaves()).toHaveLength(0);

      await card.getByLabel('host for row 3', { exact: true }).fill('https://placeholder-added.invalid/api');
      const answered = groupSaveResponse(page);
      await card.getByLabel('pass key for row 3', { exact: true }).fill('placeholder-pass-added');
      await card.getByRole('switch', { name: 'Enable row 3' }).click();
      await page.clock.fastForward(600);
      expect((await (await answered).json()).success).toBe(true);
      await page.waitForLoadState('networkidle');

      const rows = configView(testServer.configPath, 'torrentpotato') as [string, string, string][];
      expect(rows).toHaveLength(3);
      expect(rows[2].slice(0, 3)).toEqual(['1', 'https://placeholder-added.invalid/api', 'placeholder-pass-added']);
      expect(configEnabled(testServer.configPath, 'torrentpotato').rows).not.toContain('raises');
    });
  });
});

test.describe('Settings: an empty use cell', () => {
  test.describe('on an edited torrentpotato row', () => {
    test.use({ seedConfig: 'fresh_defaults#empty-use-edit' });

    test('is stored as 0 when the row gets a host and a pass key and the switch is untouched', async ({ page, testServer }) => {
      test.info().annotations.push(...combineGroupWriter());
      await page.clock.install();
      await openSettings(page, 'Searchers');
      const card = providerCard(page, 'TorrentPotato');
      await openCard(card);
      expect(configColumns(testServer.configPath, 'torrentpotato').use).toBe('');

      await card.getByLabel('host for row 1', { exact: true }).fill('https://placeholder-added.invalid/api');
      expect((await editCell(page, card, 'pass key for row 1', 'placeholder-pass-added')).success).toBe(true);
      await page.waitForLoadState('networkidle');

      // The file, not the request body: both rows are off, as shown.
      expect(configColumns(testServer.configPath, 'torrentpotato').use).toBe('0,0');
      expect(configEnabled(testServer.configPath, 'torrentpotato')).toEqual({ reader_raises: false, rows: [false, false] });
    });
  });

  test.describe('in a group nobody edited', () => {
    test.use({ seedConfig: 'fresh_defaults#empty-use-unedited' });

    test('is byte for byte as it was after load, tab changes and a reload', async ({ page, testServer }) => {
      await page.clock.install();
      const net = await recordRequests(page);
      const before = configSha(testServer.configPath);
      await openSettings(page, 'Searchers');
      await openCard(providerCard(page, 'TorrentPotato'));
      await page.getByRole('tab', { name: 'General' }).click();
      await page.getByRole('tab', { name: 'Searchers' }).click();
      await page.reload();
      await page.getByRole('tab', { name: 'Searchers' }).click();
      await settleDebounce(page);

      expect(net.networkWrites()).toEqual([]);
      expect(configSha(testServer.configPath)).toBe(before);
      expect(configColumns(testServer.configPath, 'torrentpotato').use).toBe('');
    });
  });

  test.describe('in an automation group', () => {
    test.use({ seedConfig: 'fresh_defaults#automation-empty-use' });

    test('stays empty after an edit: only the use column named use is normalised', async ({ page, testServer }) => {
      test.info().annotations.push(...combineGroupWriter());
      await page.clock.install();
      await openSettings(page, 'Suggestions');
      const card = providerCard(page, 'IMDB Watchlist');
      await openCard(card);

      expect((await editCell(page, card, 'automation urls for row 1', 'https://placeholder-list.invalid/a')).success).toBe(true);
      await page.waitForLoadState('networkidle');

      const columns = configColumns(testServer.configPath, 'imdb');
      expect(columns.automation_urls).toBe('https://placeholder-list.invalid/a');
      expect(columns.automation_urls_use).toBe('');
    });
  });
});

test.describe('Settings: cells are trimmed on an edit, not before', () => {
  test.use({ seedConfig: 'newznab_untrimmed#trim-on-edit' });

  test('a space after a separator is untouched until the group is edited, then stored trimmed', async ({ page, testServer }) => {
    test.info().annotations.push(...combineGroupWriter());
    await page.clock.install();
    const before = configSha(testServer.configPath);
    const raw = configColumns(testServer.configPath, 'newznab');
    expect(raw.host).toContain(', ');
    await openSettings(page, 'Searchers');
    const card = providerCard(page, 'Newznab');
    await settleDebounce(page);
    expect(configSha(testServer.configPath)).toBe(before);
    await expect(card.getByLabel('host for row 2', { exact: true })).toHaveValue('https://placeholder-two.invalid/api');

    expect((await editCell(page, card, 'custom tag for row 1', 'tag-edited')).success).toBe(true);
    await page.waitForLoadState('networkidle');

    const after = configColumns(testServer.configPath, 'newznab');
    expect(after.host).toBe('https://placeholder-one.invalid/api,https://placeholder-two.invalid/api');
    expect(after.api_key).toBe('placeholder-key-one,placeholder-key-two');
    expect(after.use).toBe('1,0');
  });
});

test.describe('Settings: percent-encoded text is stored as typed', () => {
  test.use({ seedConfig: 'newznab_aligned#percent-cells' });

  test('a%2Cb and a%252Cb survive a reload and an edit to a different row', async ({ page, testServer }) => {
    test.info().annotations.push(...combineGroupWriter());
    await page.clock.install();
    await openSettings(page, 'Searchers');
    let card = providerCard(page, 'Newznab');

    expect((await editCell(page, card, 'custom tag for row 1', 'a%2Cb')).success).toBe(true);
    expect((await editCell(page, card, 'custom tag for row 2', 'a%252Cb')).success).toBe(true);
    await page.waitForLoadState('networkidle');
    expect(configColumns(testServer.configPath, 'newznab').custom_tag).toBe('a%2Cb,a%252Cb,tag-three');

    await page.reload();
    await expect(page.locator('h1')).toContainText('Settings');
    await page.getByRole('tab', { name: 'Searchers' }).click();
    card = providerCard(page, 'Newznab');
    await expect(card.getByLabel('custom tag for row 2', { exact: true })).toHaveValue('a%252Cb');
    expect((await editCell(page, card, 'extra score for row 3', '99')).success).toBe(true);
    await page.waitForLoadState('networkidle');

    const columns = configColumns(testServer.configPath, 'newznab');
    expect(columns.custom_tag).toBe('a%2Cb,a%252Cb,tag-three');
    expect(columns.extra_score).toBe('5,10,99');
    for (const value of Object.values(columns)) expect(cellsOf(value)).toHaveLength(3);
  });
});

test.describe('Settings: a config stored with Python bytes literals', () => {
  test.describe('opening it', () => {
    test.use({ seedConfig: 'newznab_legacy_bytes#display' });

    test('shows the rows unwrapped', async ({ page }) => {
      await openSettings(page, 'Searchers');
      const card = providerCard(page, 'Newznab');

      await expect(card.getByLabel('host for row 1', { exact: true })).toHaveValue(NEWZNAB_HOSTS[0]);
      await expect(card.getByLabel('host for row 2', { exact: true })).toHaveValue(NEWZNAB_HOSTS[1]);
      await expect(card.getByLabel('api key for row 2', { exact: true })).toHaveValue(NEWZNAB_KEYS[1]);
      await expect(card.getByTestId('combine-misaligned-notice')).toHaveCount(0);
    });
  });

  test.describe('editing it', () => {
    test.use({ seedConfig: 'newznab_legacy_bytes#edit' });

    test('saves clean values, every row keeping its own cells', async ({ page, testServer }) => {
      test.info().annotations.push(...combineGroupWriter());
      await page.clock.install();
      expect(configColumns(testServer.configPath, 'newznab').host).toMatch(/^b'/);
      await openSettings(page, 'Searchers');
      const card = providerCard(page, 'Newznab');

      expect((await editCell(page, card, 'custom tag for row 2', 'tag-edited')).success).toBe(true);
      await page.waitForLoadState('networkidle');

      const columns = configColumns(testServer.configPath, 'newznab');
      expect(columns).toMatchObject({
        use: '1,0',
        host: NEWZNAB_HOSTS.slice(0, 2).join(','),
        api_key: NEWZNAB_KEYS.slice(0, 2).join(','),
      });
      expect(Object.values(columns).some((value) => /b'/.test(value ?? ''))).toBe(false);
      expect(cellsOf(columns.custom_tag)).toEqual(['', 'tag-edited']);
    });
  });
});

test.describe('Settings: saves are ordered, one in flight per group', () => {
  test.use({ seedConfig: 'newznab_aligned#ordering' });

  test('two edits while the first save is held end with the second edit on disk, never two requests at once', async ({ page, testServer }) => {
    test.info().annotations.push(...combineGroupWriter());
    await page.clock.install();
    const net = await recordRequests(page);
    let release!: () => void;
    const held = new Promise<void>((resolve) => { release = resolve; });
    let inFlight = 0;
    let peak = 0;
    let seenFirst = false;
    await page.route('**/settings.save_group/**', async (route) => {
      inFlight += 1;
      peak = Math.max(peak, inFlight);
      if (!seenFirst) {
        seenFirst = true;
        await held;
      }
      await route.continue();
      inFlight -= 1;
    });
    await openSettings(page, 'Searchers');
    const card = providerCard(page, 'Newznab');

    await card.getByLabel('host for row 1', { exact: true }).fill('https://placeholder-first.invalid/api');
    await page.clock.fastForward(600);
    await expect.poll(() => net.groupSaves().length).toBe(1);
    await card.getByLabel('host for row 1', { exact: true }).fill('https://placeholder-second.invalid/api');
    await page.clock.fastForward(5000);
    expect(net.groupSaves()).toHaveLength(1);

    release();
    await expect.poll(() => net.groupSaves().length).toBe(2);
    await page.waitForLoadState('networkidle');

    expect(peak).toBe(1);
    expect(cellsOf(configColumns(testServer.configPath, 'newznab').host)[0]).toBe('https://placeholder-second.invalid/api');
  });
});

test.describe('Settings: a button acts on saved rows, never on held ones', () => {
  test.use({ seedConfig: 'torrentpotato_aligned#sync-button' });

  // What this proves: the edit is saved BEFORE the sync, and the sync's rows are shown with
  // no later group save. The lock that stops typing during the action has its own tests below.
  test('the held edit is saved before the sync, and the sync\'s rows are then shown, not saved over', async ({ page, testServer }) => {
    test.info().annotations.push(...combineGroupWriter());
    await page.clock.install();
    const net = await recordRequests(page);
    const synced: Record<string, string> = {
      use: '1', host: 'https://placeholder-synced.invalid/api', pass_key: 'placeholder-pass-synced',
      name: 'name-synced', seed_ratio: '1', seed_time: '40', extra_score: '0',
    };
    // Counted from the CLICK, not from the load: the page reads settings twice when it
    // loads (Alpine calls init() and x-init calls it again), so "the second read" is a
    // load read. The first read after the click is the re-read after the sync.
    let afterClick = false;
    await page.route(/\/api\/[^/]+\/settings\/(\?.*)?$/, async (route) => {
      if (!afterClick) {
        await route.continue();
        return;
      }
      const response = await route.fetch();
      const payload = await response.json();
      for (const [column, cell] of Object.entries(synced)) {
        payload.values.torrentpotato[column] = `${payload.values.torrentpotato[column]},${cell}`;
      }
      payload.combine_state.torrentpotato.rows = 4;
      await route.fulfill({ response, json: payload });
    });
    await page.route('**/torrentpotato.jackett_sync/**', (route) => route.fulfill({
      status: 200, contentType: 'application/json', body: JSON.stringify({ success: true, message: 'Synced' }),
    }));
    await openSettings(page, 'Searchers');
    const card = providerCard(page, 'TorrentPotato');
    await openCard(card);

    await card.getByLabel('name for row 1', { exact: true }).fill('name-edited-before-sync');
    afterClick = true;
    await card.getByRole('button', { name: /Sync Indexers/ }).click();
    await page.clock.fastForward(5000);
    // The sync is sent only after the pre-action save has answered, which on a slow
    // runner can be after the network first goes idle: wait for the request itself
    // before comparing the order (seen in CI as "expected < -1").
    const indexOf = (part: string) => net.seen.map((request) => request.url).findIndex((url) => url.includes(part));
    await expect.poll(() => indexOf('torrentpotato.jackett_sync')).toBeGreaterThanOrEqual(0);
    await page.waitForLoadState('networkidle');

    const save = indexOf('settings.save_group');
    const sync = indexOf('torrentpotato.jackett_sync');
    expect(save).toBeGreaterThanOrEqual(0);
    expect(save).toBeLessThan(sync);
    expect(cellsOf(configColumns(testServer.configPath, 'torrentpotato').name)[0]).toBe('name-edited-before-sync');
    await expect(card.getByLabel('host for row 4', { exact: true })).toHaveValue('https://placeholder-synced.invalid/api');
    expect(net.groupSaves()).toHaveLength(1);
  });
});

// ── The rows are LOCKED from the click of a button until the page has the server's rows
// back (SEC-004 AC-DATA-21; owner decision 2026-11-17, "Lock rows during sync"). The sync is
// stood in for by a held route that writes a fourth row to the REAL server, as the real
// writer does, and answers as each test says. Nothing sleeps: the test releases the gate.
type SyncAnswer = 'success' | 'refused' | 'abort' | 'html500';

const SYNCED_HOST = 'https://placeholder-synced.invalid/api';

async function stubSync(page: Page, apiBase: string, configPath: string, answer: SyncAnswer) {
  let release!: () => void;
  const gate = new Promise<void>((resolve) => { release = resolve; });
  const hits: string[] = [];
  await page.route('**/torrentpotato.jackett_sync/**', async (route) => {
    hits.push(route.request().url());
    await gate;
    if (answer === 'refused') {
      await route.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify({ success: false, error: 'Jackett refused' }) });
      return;
    }
    const before = configColumns(configPath, 'torrentpotato');
    const synced: Record<string, string> = {
      use: '1', host: SYNCED_HOST, pass_key: 'placeholder-pass-synced',
      name: 'name-synced', seed_ratio: '1', seed_time: '40', extra_score: '0',
    };
    const columns = Object.keys(synced);
    const rows = [0, 1, 2, 3].map((index) => Object.fromEntries(columns.map((column) => [
      column, index < 3 ? cellsOf(before[column])[index] : synced[column],
    ])));
    await fetch(`${apiBase}/settings.save_group/`, {
      method: 'POST', headers: { 'content-type': 'application/json' },
      body: JSON.stringify({ section: 'torrentpotato', rows }),
    });
    if (answer === 'abort') await route.abort();
    else if (answer === 'html500') await route.fulfill({ status: 500, contentType: 'text/html', body: '<html>Internal Server Error</html>' });
    else await route.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify({ success: true, message: 'Synced' }) });
  });
  return { release, hits };
}

async function openTorrentCard(page: Page) {
  await page.clock.install();
  await openSettings(page, 'Searchers');
  const card = providerCard(page, 'TorrentPotato');
  await openCard(card);
  return card;
}

const syncButton = (card: Locator) => card.getByRole('button', { name: /Sync Indexers/ });

test.describe('Settings: the rows are locked while a button acts, and until the server\'s rows are back', () => {
  test.describe('what is locked, for how long, and what follows', () => {
    test.use({ seedConfig: 'torrentpotato_aligned#lock-and-reread' });

    test('nothing can be typed, toggled, added or removed; no save goes out; then the sync\'s rows show and an edit keeps all four', async ({ page, testServer }) => {
      test.info().annotations.push(...combineGroupWriter());
      const net = await recordRequests(page);
      const sync = await stubSync(page, testServer.apiBase, testServer.configPath, 'success');
      const card = await openTorrentCard(page);
      const name = card.getByLabel('name for row 1', { exact: true });

      await syncButton(card).click();
      await expect(card.getByTestId('combine-locked-note')).toBeVisible();
      await expect(name).toHaveJSProperty('readOnly', true);
      await expect(card.locator('[aria-busy="true"]')).toHaveCount(1);
      await expect(card.getByRole('switch', { name: 'Enable row 1' })).toHaveAttribute('aria-disabled', 'true');
      await expect(card.getByRole('button', { name: 'Add row' })).toHaveAttribute('aria-disabled', 'true');
      await expect(card.getByRole('button', { name: 'Remove row 2' })).toHaveAttribute('aria-disabled', 'true');
      await expect(syncButton(card)).toHaveAttribute('aria-disabled', 'true');

      await name.focus();
      await page.keyboard.type('typed-while-locked');
      // `force`: Playwright treats aria-disabled as not enabled and would refuse the click,
      // and the point is that a click that DOES arrive changes nothing.
      await card.getByRole('switch', { name: 'Enable row 1' }).click({ force: true });
      await card.getByRole('button', { name: 'Add row' }).click({ force: true });
      await card.getByRole('button', { name: 'Remove row 2' }).click({ force: true });
      await page.clock.fastForward(6000);
      await expect(name).toHaveValue('name-one');
      await expect(card.getByRole('switch', { name: 'Enable row 1' })).toHaveAttribute('aria-checked', 'true');
      await expect(card.getByRole('switch', { name: /^Enable row/ })).toHaveCount(3);
      expect(net.groupSaves()).toHaveLength(0);

      sync.release();
      await expect(card.getByLabel('host for row 4', { exact: true })).toHaveValue(SYNCED_HOST);
      await expect(card.getByLabel('name for row 1', { exact: true })).toHaveJSProperty('readOnly', false);
      await expect(card.locator('[aria-busy="true"]')).toHaveCount(0);
      expect(net.groupSaves()).toHaveLength(0);

      expect((await editCell(page, card, 'name for row 1', 'name-edited-after')).success).toBe(true);
      await page.waitForLoadState('networkidle');
      const columns = configColumns(testServer.configPath, 'torrentpotato');
      expect(cellsOf(columns.host)).toHaveLength(4);
      expect(cellsOf(columns.name)).toEqual(['name-edited-after', 'name-two', 'name-three', 'name-synced']);
    });
  });

  test.describe('a tab change during the action', () => {
    test.use({ seedConfig: 'torrentpotato_aligned#lock-tab-change' });

    test('keeps the rows locked and the rebuilt button busy; a second press sends nothing; the server\'s rows show afterwards', async ({ page, testServer }) => {
      test.info().annotations.push(...combineGroupWriter());
      const net = await recordRequests(page);
      const sync = await stubSync(page, testServer.apiBase, testServer.configPath, 'success');
      const card = await openTorrentCard(page);

      await syncButton(card).click();
      await expect.poll(() => sync.hits.length).toBe(1);
      await page.getByRole('tab', { name: 'General' }).click();
      await page.getByRole('tab', { name: 'Searchers' }).click();
      const rebuilt = providerCard(page, 'TorrentPotato');
      await openCard(rebuilt);

      await expect(rebuilt.getByLabel('name for row 1', { exact: true })).toHaveJSProperty('readOnly', true);
      await expect(syncButton(rebuilt)).toHaveAttribute('aria-disabled', 'true');
      await syncButton(rebuilt).click({ force: true });
      await page.clock.fastForward(1000);
      expect(sync.hits).toHaveLength(1);

      sync.release();
      await expect(rebuilt.getByLabel('host for row 4', { exact: true })).toHaveValue(SYNCED_HOST);
      await expect(rebuilt.getByLabel('name for row 1', { exact: true })).toHaveJSProperty('readOnly', false);
      expect((await editCell(page, rebuilt, 'name for row 1', 'name-edited-after')).success).toBe(true);
      await page.waitForLoadState('networkidle');
      expect(cellsOf(configColumns(testServer.configPath, 'torrentpotato').host)).toHaveLength(4);
      expect(net.groupSaves()).toHaveLength(1);
    });
  });

  for (const answer of ['abort', 'html500'] as const) {
    test.describe(`an action that ${answer === 'abort' ? 'throws' : 'answers an HTML 500'}`, () => {
      test.use({ seedConfig: `torrentpotato_aligned#lock-${answer}` });

      test('may have written: the page re-reads, shows the file\'s rows and the error, and the next edit saves the file\'s rows plus that edit', async ({ page, testServer }) => {
        test.info().annotations.push(...combineGroupWriter());
        const sync = await stubSync(page, testServer.apiBase, testServer.configPath, answer);
        const card = await openTorrentCard(page);

        await syncButton(card).click();
        await expect.poll(() => sync.hits.length).toBe(1);
        sync.release();

        await expect(card.getByLabel('host for row 4', { exact: true })).toHaveValue(SYNCED_HOST);
        await expect(card.getByText(/^Error:/)).toBeVisible();
        await expect(card.getByLabel('name for row 1', { exact: true })).toHaveJSProperty('readOnly', false);
        expect((await editCell(page, card, 'name for row 1', 'name-edited-after')).success).toBe(true);
        await page.waitForLoadState('networkidle');
        const columns = configColumns(testServer.configPath, 'torrentpotato');
        expect(cellsOf(columns.host)).toHaveLength(4);
        expect(cellsOf(columns.name)).toEqual(['name-edited-after', 'name-two', 'name-three', 'name-synced']);
      });
    });
  }

  test.describe('an action that answers success false', () => {
    test.use({ seedConfig: 'torrentpotato_aligned#lock-refused' });

    test('unlocks at once with the rows as they were, and the next edit saves three', async ({ page, testServer }) => {
      test.info().annotations.push(...combineGroupWriter());
      const sync = await stubSync(page, testServer.apiBase, testServer.configPath, 'refused');
      const card = await openTorrentCard(page);

      await syncButton(card).click();
      await expect(card.getByLabel('name for row 1', { exact: true })).toHaveJSProperty('readOnly', true);
      sync.release();

      await expect(card.getByLabel('name for row 1', { exact: true })).toHaveJSProperty('readOnly', false);
      await expect(card.getByText('Jackett refused')).toBeVisible();
      await expect(card.getByLabel('host for row 4', { exact: true })).toHaveCount(0);
      expect((await editCell(page, card, 'name for row 1', 'name-edited-after')).success).toBe(true);
      await page.waitForLoadState('networkidle');
      expect(cellsOf(configColumns(testServer.configPath, 'torrentpotato').host)).toHaveLength(3);
    });
  });

  test.describe('a re-read that fails', () => {
    test.use({ seedConfig: 'torrentpotato_aligned#lock-reread-fails' });

    test('stays locked, says so, and no save is possible', async ({ page, testServer }) => {
      test.info().annotations.push(...combineGroupWriter());
      const net = await recordRequests(page);
      const sync = await stubSync(page, testServer.apiBase, testServer.configPath, 'success');
      // Only reads after the click fail (the page reads twice at load).
      let failReads = false;
      await page.route(/\/api\/[^/]+\/settings\/(\?.*)?$/, async (route) => {
        if (failReads) await route.fulfill({ status: 500, contentType: 'text/html', body: '<html>no</html>' });
        else await route.continue();
      });
      const card = await openTorrentCard(page);

      failReads = true;
      await syncButton(card).click();
      await expect.poll(() => sync.hits.length).toBe(1);
      sync.release();

      await expect(card.getByTestId('combine-reload-error')).toHaveText('Could not reload these rows. Reload the page before changing them.');
      // Stale, not busy: the error is not inside a busy region, and the button is pressable.
      await expect(card.locator('[aria-busy="true"]')).toHaveCount(0);
      await expect(syncButton(card)).not.toHaveAttribute('aria-disabled', 'true');
      await expect(card.getByLabel('name for row 1', { exact: true })).toHaveJSProperty('readOnly', true);
      await card.getByLabel('name for row 1', { exact: true }).focus();
      await page.keyboard.type('typed-while-stale');
      await page.clock.fastForward(5000);
      await page.waitForLoadState('networkidle');
      expect(net.groupSaves()).toHaveLength(0);

      // Pressing Sync again takes the stale lock, re-reads, and lifts it.
      failReads = false;
      await syncButton(card).click();
      await expect(card.getByTestId('combine-reload-error')).toHaveCount(0);
      await expect(card.getByLabel('host for row 4', { exact: true })).toHaveValue(SYNCED_HOST);
      await expect(card.getByLabel('name for row 1', { exact: true })).toHaveJSProperty('readOnly', false);
    });
  });

  test.describe('rows edited just before the click', () => {
    test.use({ seedConfig: 'torrentpotato_aligned#lock-flush-first' });

    test('are saved before the action request goes out', async ({ page, testServer }) => {
      test.info().annotations.push(...combineGroupWriter());
      const net = await recordRequests(page);
      const sync = await stubSync(page, testServer.apiBase, testServer.configPath, 'refused');
      const card = await openTorrentCard(page);

      await card.getByLabel('name for row 1', { exact: true }).fill('name-edited-before-click');
      await page.clock.fastForward(100);
      await syncButton(card).click();
      await expect.poll(() => sync.hits.length).toBe(1);
      sync.release();
      await page.waitForLoadState('networkidle');

      const urls = net.seen.map((request) => request.url);
      expect(urls.findIndex((url) => url.includes('settings.save_group'))).toBeGreaterThanOrEqual(0);
      expect(urls.findIndex((url) => url.includes('settings.save_group')))
        .toBeLessThan(urls.findIndex((url) => url.includes('jackett_sync')));
      expect(cellsOf(configColumns(testServer.configPath, 'torrentpotato').name)[0]).toBe('name-edited-before-click');
    });
  });

  test.describe('a pre-action flush the server refuses', () => {
    test.use({ seedConfig: 'torrentpotato_aligned#lock-flush-refused' });

    test('runs no action, unlocks, shows the refusal, and the next edit saves', async ({ page, testServer }) => {
      test.info().annotations.push(...combineGroupWriter());
      const sync = await stubSync(page, testServer.apiBase, testServer.configPath, 'refused');
      let refused = false;
      await page.route('**/settings.save_group/**', async (route) => {
        if (refused) {
          await route.continue();
          return;
        }
        refused = true;
        await route.fulfill({
          status: 200, contentType: 'application/json',
          body: JSON.stringify({ success: false, error: 'x', invalid: [{ row: 0, column: 'host', reason: 'comma' }] }),
        });
      });
      const card = await openTorrentCard(page);
      const host = card.getByLabel('host for row 1', { exact: true });

      await host.fill('https://placeholder-bad.invalid/api,https://placeholder-evil.invalid');
      await syncButton(card).click();

      await expect(card.getByTestId('combine-row-error')).toBeVisible();
      await expect(host).toHaveJSProperty('readOnly', false);
      // After a bounded settle: the action request, had there been one, has been sent by now.
      await page.clock.fastForward(2000);
      await page.waitForLoadState('networkidle');
      expect(sync.hits).toHaveLength(0);
      expect((await editCell(page, card, 'host for row 1', 'https://placeholder-fixed.invalid/api')).success).toBe(true);
    });
  });
});

test.describe('Settings: an unrelated save leaves a misaligned group byte for byte', () => {
  test.use({ seedConfig: 'newznab_misaligned_key_short#unrelated-save' });

  test('saving a setting in another section does not rewrite the group', async ({ page, testServer }) => {
    test.info().annotations.push({ type: SETTINGS_PERSISTENCE_ANNOTATION });
    const before = configColumns(testServer.configPath, 'newznab');
    await openSettings(page, 'Searchers');

    const saved = await page.evaluate(async () => {
      const body = new URLSearchParams({ section: 'torrentpotato', name: 'jackett_url', value: 'http://jackett.invalid:9117' });
      const response = await fetch((window as any).CP.apiBase + '/settings.save/', { method: 'POST', body });
      return (await response.json()).success;
    });

    expect(saved).toBe(true);
    expect(configColumns(testServer.configPath, 'newznab')).toEqual(before);
    expect(cellsOf(before.host)).toHaveLength(3);
    expect(cellsOf(before.api_key)).toHaveLength(2);
  });
});

test.describe('Settings: no combine column is ever saved on its own, and no cell travels in a URL', () => {
  test.use({ seedConfig: 'all_groups_aligned#every-group-flow' });

  const GROUPS: [string, string][] = [
    ['Searchers', 'Newznab'], ['Searchers', 'TorrentPotato'],
    ['Suggestions', 'IMDB Watchlist'], ['Suggestions', 'iTunes'], ['Suggestions', 'Letterboxd'],
  ];

  test('add, edit and delete a row in each of the five groups', async ({ page }) => {
    test.info().annotations.push(...combineGroupWriter());
    await page.clock.install();
    const net = await recordRequests(page);
    await openSettings(page);

    for (const [tab, heading] of GROUPS) {
      await page.getByRole('tab', { name: tab }).click();
      const card = providerCard(page, heading);
      await openCard(card);
      const row = (await card.getByRole('button', { name: /^Remove row/ }).count()) + 1;
      await card.getByRole('button', { name: 'Add row' }).click();
      const answered = groupSaveResponse(page);
      for (const input of await card.locator(`input[aria-label$="for row ${row}"]`).all()) {
        const label = (await input.getAttribute('aria-label')) ?? '';
        await input.fill(`sentinel-${heading.replace(/\W/g, '')}-${label.split(' for ')[0].replace(/ /g, '-')}`);
      }
      await page.clock.fastForward(600);
      expect((await (await answered).json()).success).toBe(true);
      const removed = groupSaveResponse(page);
      await card.getByRole('button', { name: `Remove row ${row}` }).click();
      await page.clock.fastForward(600);
      expect((await (await removed).json()).success).toBe(true);
    }
    await settleDebounce(page);

    const writes = await net.pageWrites();
    expect(writes.length).toBeGreaterThanOrEqual(GROUPS.length * 2);
    expect(net.networkWrites().filter((request) => request.url.includes('settings.save/'))).toEqual([]);
    expect(writes.filter((request) => request.url.includes('settings.save/'))).toEqual([]);
    expect(net.networkWrites().every((request) => request.method === 'POST')).toBe(true);
    expect(net.seen.filter((request) => request.url.includes('sentinel'))).toEqual([]);
  });
});

// ─────────────────────────────────────────────────────────────────────────────
// SEC-004 P4: removing a row. No Remove control on a single row (AC-DESIGN-8), and focus
// lands on a live control with the removal announced once (AC-A11Y-7). Every removal here
// is driven by the keyboard, the way the criterion is worded.
// ─────────────────────────────────────────────────────────────────────────────

const SEEDED_ROWS = {
  use: ['1', '0', '1'],
  host: NEWZNAB_HOSTS,
  api_key: NEWZNAB_KEYS,
  extra_score: ['5', '10', '15'],
  custom_tag: ['tag-one', 'tag-two', 'tag-three'],
};

/** What config.ini must hold once the rows at `removed` (0-based) are gone: every column, same rows. */
function rowsWithout(...removed: number[]) {
  const keep = (cells: string[]) => cells.filter((_, index) => !removed.includes(index)).join(',');
  return Object.fromEntries(Object.entries(SEEDED_ROWS).map(([column, cells]) => [column, keep(cells)]));
}

/** Where focus is, as a name a failure message can show: the body is the failure this guards. */
const focusedControl = (page: Page) => page.evaluate(() => {
  const active = document.activeElement;
  if (!active || active === document.body) return 'body';
  return `${active.tagName.toLowerCase()}:${active.getAttribute('aria-label') ?? ''}`;
});

/** Reach Remove for `row` (1-based) with the keyboard alone, press it, and wait for the one group save. */
async function removeRowByKeyboard(page: Page, card: Locator, row: number, key = 'Enter') {
  await card.getByLabel(`custom tag for row ${row}`, { exact: true }).focus();
  await page.keyboard.press('Tab');
  expect(await focusedControl(page)).toBe(`button:Remove row ${row}`);
  const answered = groupSaveResponse(page);
  await page.keyboard.press(key);
  await page.clock.fastForward(600);
  expect((await (await answered).json()).success).toBe(true);
  await page.waitForLoadState('networkidle');
}

const REMOVE_CASES = [
  { name: 'first', row: 1, key: 'Enter', focus: 'button:Remove row 1' },
  { name: 'middle', row: 2, key: 'Space', focus: 'button:Remove row 2' },
  { name: 'last', row: 3, key: 'Enter', focus: 'button:Remove row 2' },
] as const;

for (const { name, row, key, focus } of REMOVE_CASES) {
  test.describe(`Settings: removing the ${name} of three newznab rows by keyboard`, () => {
    test.use({ seedConfig: `newznab_aligned#remove-${name}-by-keyboard` });

    test('focus stays on a Remove control, the removal is announced once, one group save, rows still aligned', async ({ page, testServer }) => {
      test.info().annotations.push(...combineGroupWriter());
      await page.clock.install();
      const net = await recordRequests(page);
      await openSettings(page, 'Searchers');
      const card = providerCard(page, 'Newznab');
      await expect(card.getByRole('button', { name: /^Remove row/ })).toHaveCount(3);
      // Armed before the keypress: every time the polite region comes to hold the text.
      await page.evaluate(() => {
        const heard: string[] = [];
        (window as any).__heard = heard;
        const region = document.querySelector('[data-testid="settings-announcer-polite"]') as HTMLElement;
        new MutationObserver(() => { if (region.textContent) heard.push(region.textContent); })
          .observe(region, { subtree: true, childList: true, characterData: true });
      });

      await removeRowByKeyboard(page, card, row, key);

      expect(await focusedControl(page)).toBe(focus);
      await expect(card.getByRole('button', { name: /^Remove row/ })).toHaveCount(2);
      // Bounded settle before the negative reads.
      await page.waitForTimeout(300);
      expect(await page.evaluate(() => (window as any).__heard)).toEqual([`Row ${row} removed`]);
      await expect(page.getByTestId('settings-announcer-polite')).toHaveText(`Row ${row} removed`);
      expect(net.groupSaves()).toHaveLength(1);
      expect(configColumns(testServer.configPath, 'newznab')).toEqual(rowsWithout(row - 1));
      const columns = configColumns(testServer.configPath, 'newznab');
      const keptHosts = (columns.host ?? '').split(',');
      const keptKeys = (columns.api_key ?? '').split(',');
      expect(keptKeys).toEqual(keptHosts.map((host) => NEWZNAB_KEYS[NEWZNAB_HOSTS.indexOf(host)]));
    });
  });
}

test.describe('Settings: removing down to one newznab row', () => {
  test.use({ seedConfig: 'newznab_aligned#remove-down-to-one' });

  test('the last Remove control is gone, focus goes to Add, and a new row brings Remove back on both', async ({ page, testServer }) => {
    test.info().annotations.push(...combineGroupWriter());
    await page.clock.install();
    const net = await recordRequests(page);
    await openSettings(page, 'Searchers');
    const card = providerCard(page, 'Newznab');
    const removes = card.getByRole('button', { name: /^Remove row/ });

    await removeRowByKeyboard(page, card, 1);
    await expect(removes).toHaveCount(2);
    await removeRowByKeyboard(page, card, 1);

    expect(await focusedControl(page)).toBe('button:Add row');
    await expect(removes).toHaveCount(0);
    expect(await card.locator('button[aria-label^="Remove row"]').count()).toBe(0);
    expect(net.groupSaves()).toHaveLength(2);
    expect(configColumns(testServer.configPath, 'newznab')).toEqual(rowsWithout(0, 1));

    await page.keyboard.press('Enter');
    await expect(removes).toHaveCount(2);
    await expect(card.getByRole('button', { name: 'Remove row 1', exact: true })).toBeVisible();
    await expect(card.getByRole('button', { name: 'Remove row 2', exact: true })).toBeVisible();
    // Adding saves nothing by itself.
    await page.clock.fastForward(5000);
    await page.waitForLoadState('networkidle');
    expect(net.groupSaves()).toHaveLength(2);
  });
});
