import AxeBuilder from '@axe-core/playwright';
import type { Locator, Page } from '@playwright/test';
import { test, expect } from './fixtures';
import { expectVisualTransitionsToSettle, mockSettingsSave } from './helpers';

/**
 * The setup wizard's inline icons (WCAG 2.2 AA 1.1.1 Non-text Content, 4.1.2
 * Name, Role, Value).
 *
 * Every icon in wizard.html sits beside visible text that already says the
 * same thing, or inside a control that already carries its own accessible
 * name, so each one is decorative and must be hidden from assistive
 * technology rather than labelled (a label would be announced twice).
 *
 * axe does not reliably flag an unnamed inline <svg>, and several of the icons
 * are never in the live DOM at all: the Newznab remove button and the folder
 * rows live inside Alpine <template x-for>, and the legacy downloader's
 * "Testing..." spinner sits inside `<template x-if="false && ...">`, which
 * never renders. A test that only looked at the rendered DOM would therefore
 * pass on icons it never saw. The audit below walks the server's markup,
 * including the content of every <template>, so it sees all of them.
 */

const GRAPHIC_ROLES = new Set(['graphics-document', 'graphics-symbol', 'img', 'image']);
const PHONE = { width: 375, height: 812 };
const directoryListing = {
  success: true, dirs: ['/movies/', '/shows/'], parent: '/', home: '/', is_root: false, platform: 'posix',
};

type SvgAudit = { total: number; exposed: string[] };

/**
 * Audits every svg under the wizard root, including <template> content.
 * With `servedHtml` it audits the server's markup parsed inert (no Alpine, so
 * the count is exactly what the template source contains); without it, the
 * live DOM, which also holds the clones Alpine has rendered.
 */
async function auditSvgs(page: Page, servedHtml?: string): Promise<SvgAudit> {
  return page.evaluate((html) => {
    const doc = html === undefined ? document : new DOMParser().parseFromString(html, 'text/html');
    // Scoped to the wizard: base.html carries icons of its own.
    const wizard = doc.querySelector('[x-data="setupWizard()"]') as Element;
    const roots: { root: ParentNode; where: string }[] = [{ root: wizard, where: 'page' }];
    for (let i = 0; i < roots.length; i += 1) {
      roots[i].root.querySelectorAll('template').forEach((t, n) => roots.push({
        root: t.content,
        where: `${roots[i].where} > template#${n} (${t.getAttribute('x-for') || t.getAttribute('x-if') || 'anonymous'})`.slice(0, 110),
      }));
    }
    const svgs = roots.flatMap(({ root, where }) => Array.from(root.querySelectorAll('svg')).map((svg) => ({ svg, where })));

    const hasName = (svg: Element): boolean => {
      if ((svg.getAttribute('aria-label') || '').trim()) return true;
      const labelledby = (svg.getAttribute('aria-labelledby') || '').trim();
      if (labelledby && labelledby.split(/\s+/).some((id) => {
        const target = svg.ownerDocument.getElementById(id);
        return !!target && !!(target.textContent || '').trim();
      })) return true;
      return Array.from(svg.children).some(
        (child) => child.tagName.toLowerCase() === 'title' && !!(child.textContent || '').trim(),
      );
    };
    const hidden = (svg: Element): boolean => {
      for (let el: Element | null = svg; el; el = el.parentElement) {
        if (el.getAttribute('aria-hidden') === 'true') return true;
      }
      return false;
    };
    // Nearest enclosing text, so a failure names the icon, plus its path data
    // and where in the template tree it lives.
    const describe = ({ svg, where }: { svg: Element; where: string }): string => {
      let text = '';
      for (let el: Element | null = svg.parentElement, up = 0; el && !text && up < 6; el = el.parentElement, up += 1) {
        text = (el.textContent || '').replace(/\s+/g, ' ').trim();
      }
      const d = (svg.querySelector('path')?.getAttribute('d') || '').slice(0, 24);
      return `svg[class="${svg.getAttribute('class')}"] path d="${d}…" in ${where}; nearest text "${text.slice(0, 60)}"`;
    };

    return {
      total: svgs.length,
      exposed: svgs.filter((entry) => !hidden(entry.svg) && !hasName(entry.svg)).map(describe),
    };
  }, servedHtml);
}

/** Graphics inside the wizard that Chromium actually exposes, from the real accessibility tree. */
async function exposedGraphics(page: Page): Promise<string[]> {
  const cdp = await page.context().newCDPSession(page);
  try {
    const { nodes } = await cdp.send('Accessibility.getFullAXTree');
    const found: string[] = [];
    for (const node of nodes) {
      if (node.ignored || !GRAPHIC_ROLES.has(String(node.role?.value)) || !node.backendDOMNodeId) continue;
      const { object } = await cdp.send('DOM.resolveNode', { backendNodeId: node.backendDOMNodeId });
      const inWizard = await cdp.send('Runtime.callFunctionOn', {
        objectId: object.objectId,
        functionDeclaration: 'function () { return !!this.closest(\'[x-data="setupWizard()"]\'); }',
        returnByValue: true,
      });
      // base.html's own logo is named and outside the wizard: out of scope here.
      if (inWizard.result.value) found.push(`${node.role?.value} "${node.name?.value ?? ''}"`);
    }
    return found;
  } finally {
    await cdp.detach();
  }
}

async function wizardState(page: Page, apply: string) {
  await page.evaluate((source) => {
    const root = document.querySelector('[x-data="setupWizard()"]') as HTMLElement;
    const state = (window as any).Alpine.$data(root);
    // eslint-disable-next-line no-new-func
    new Function('state', source)(state);
  }, apply);
}

async function openWizard(page: Page, theme: 'light' | 'dark' = 'light') {
  await mockSettingsSave(page);
  await page.addInitScript((value) => localStorage.setItem('cp-theme', value), theme);
  await page.goto('/wizard/');
  await expect(page.getByRole('heading', { name: 'Welcome to CouchPotato' })).toBeVisible();
  await expect.poll(
    () => page.evaluate(() => document.documentElement.classList.contains('light')),
    { message: `${theme} theme was not applied` },
  ).toBe(theme === 'light');
}

function expectNoExposedSvg(exposed: string[]) {
  expect(
    exposed,
    `${exposed.length} wizard svg(s) are exposed to assistive technology with no name. ` +
    'Icons beside text or inside a named control are decorative: add aria-hidden="true".\n' +
    exposed.join('\n'),
  ).toEqual([]);
}

test('every svg in the served wizard markup is hidden from assistive technology or has a text alternative', async ({ page }) => {
  await openWizard(page);
  const served = await (await page.request.get('/wizard/')).text();

  // The expected count comes from the served HTML itself, not from a literal:
  // the audit must have seen every <svg> the template emits (three of them are
  // never in the live DOM, so only the inert parse can see them), and a new
  // icon with no aria-hidden must fail here rather than be missed.
  const start = served.indexOf('x-data="setupWizard()"');
  const end = served.indexOf('function setupWizard()');
  expect(start, 'the wizard root is missing from the served HTML').toBeGreaterThan(-1);
  expect(end, 'the wizard script is missing from the served HTML').toBeGreaterThan(start);
  const inSource = (served.slice(start, end).match(/<svg\b/g) || []).length;
  expect(inSource, 'no <svg> found in the served wizard markup').toBeGreaterThan(0);

  const parsed = await auditSvgs(page, served);
  expect(parsed.total, 'the audit and the source disagree on how many svgs the wizard has').toBe(inSource);
  expectNoExposedSvg(parsed.exposed);

  // And the live DOM, which also holds what Alpine has rendered from x-for.
  expectNoExposedSvg((await auditSvgs(page)).exposed);
});

test('the real accessibility tree exposes no graphic from any wizard step', async ({ page }) => {
  await openWizard(page);
  const found: string[] = [];
  for (let step = 0; step <= 5; step += 1) {
    await wizardState(page, `
      state.formData.searchType = 'both';
      state.formData.torrentpotato.enabled = true;
      state.jackettSyncing = true;
      state.testingDownloader = true;
      state.saving = true;
      state.currentStep = ${step};
    `);
    await expect(page.locator('[x-text="steps[currentStep]"]')).toHaveText(
      ['Welcome', 'Security', 'Providers', 'Downloader', 'Library', 'Done'][step],
    );
    await expectVisualTransitionsToSettle(page, `wizard step ${step}`);
    (await exposedGraphics(page)).forEach((graphic) => found.push(`step ${step}: ${graphic}`));
  }
  expect(found, 'a wizard icon is exposed as a graphic with no name').toEqual([]);
});

test('icon-only controls keep their own accessible name', async ({ page }) => {
  await openWizard(page);
  await wizardState(page, `
    state.currentStep = 2;
    state.formData.searchType = 'usenet';
    state.formData.newznab.enabled = true;
    state.formData.newznab.entries = [{ host: '', api_key: '' }, { host: '', api_key: '' }];
  `);
  await expect(page.getByRole('button', { name: 'Remove indexer 1', exact: true })).toBeVisible();
  await expect(page.getByRole('button', { name: 'Remove indexer 2', exact: true })).toBeVisible();

  await page.route('**/directory.list/**', (route) => route.fulfill({
    status: 200, contentType: 'application/json', body: JSON.stringify(directoryListing),
  }));
  await wizardState(page, 'state.currentStep = 4; state.browseDirectory("renamer_from");');
  const browser = page.locator('[x-show="browserOpen"]').filter({ hasText: 'Browse Folders' });
  await expect(browser.getByRole('button', { name: 'Close directory browser', exact: true })).toBeVisible();
  // Folder rows are named by the folder alone: the icon must add nothing.
  await expect(browser.getByRole('button', { name: 'movies', exact: true })).toBeVisible();
  await expect(browser.getByRole('button', { name: 'shows', exact: true })).toBeVisible();
});

test('spinner buttons are named by their visible text alone', async ({ page }) => {
  await openWizard(page);
  await wizardState(page, `
    state.currentStep = 2;
    state.formData.searchType = 'torrents';
    state.formData.torrentpotato.enabled = true;
    state.jackettSyncing = true;
  `);
  await expect(page.getByRole('button', { name: 'Syncing…', exact: true })).toBeVisible();
  await wizardState(page, 'state.jackettSyncing = false; state.currentStep = 1; state.saving = true;');
  await expect(page.getByRole('button', { name: 'Saving…', exact: true })).toBeVisible();
});

test('the Private Trackers disclosure exposes its expanded state and reveals reachable content', async ({ page }) => {
  await openWizard(page);
  await wizardState(page, 'state.currentStep = 2; state.formData.searchType = "torrents";');
  const name = /^Private Trackers/;
  const disclosure = page.locator('[x-data="{ expanded: false }"]');
  const hiddenSwitch = page.getByRole('switch', { name: 'Enable PassThePopcorn' });

  // Collapsed: the state is exposed, and the content is not in the way.
  const collapsed = page.getByRole('button', { name, expanded: false });
  await expect(collapsed).toBeVisible();
  await expect(page.getByRole('button', { name, expanded: true })).toHaveCount(0);
  await expect(hiddenSwitch).toBeHidden();

  await collapsed.click();
  const expanded = page.getByRole('button', { name, expanded: true });
  await expect(expanded).toBeVisible();
  await expect(page.getByRole('button', { name, expanded: false })).toHaveCount(0);
  await expect(hiddenSwitch).toBeVisible();

  // Reachable from the control that revealed it: the next Tab stop is inside.
  await expanded.focus();
  await page.keyboard.press('Tab');
  await expect(disclosure.getByRole('switch').first(), 'Tab from the expanded disclosure does not enter the revealed content').toBeFocused();

  // And it collapses again.
  await expanded.press('Enter');
  await expect(page.getByRole('button', { name, expanded: false })).toBeVisible();
  await expect(hiddenSwitch).toBeHidden();
});

// What is checked is the exposed role and its text; whether a screen reader
// actually announces it cannot be automated.
test('the folder browser exposes its loading state as a status with text, not only a spinner', async ({ page }) => {
  await openWizard(page);
  let release!: () => void;
  const gate = new Promise<void>((resolve) => { release = resolve; });
  await page.route('**/directory.list/**', async (route) => {
    await gate;
    await route.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify(directoryListing) });
  });

  await wizardState(page, 'state.currentStep = 4; state.browseDirectory("renamer_from");');
  const browser = page.locator('[x-show="browserOpen"]').filter({ hasText: 'Browse Folders' });
  // Not `{ name: ... }`: a status role takes its name from the author, not its
  // content, so matching on the text is the honest query.
  const loading: Locator = browser.getByRole('status').filter({ hasText: 'Loading folders…' });
  await expect(loading, 'the loading spinner has no text alternative').toBeVisible();
  await expect(loading, 'Sonar S6819: use the native <output>, not role=status on a div').toHaveJSProperty('tagName', 'OUTPUT');
  await expect(browser.locator('div[role="status"]')).toHaveCount(0);

  release();
  await expect(loading).toBeHidden();
  await expect(browser.getByRole('button', { name: 'movies', exact: true })).toBeVisible();
});

for (const theme of ['light', 'dark'] as const) {
  test(`axe finds no violations on the icon-bearing wizard states at phone width in the ${theme} theme`, async ({ page }) => {
    await page.setViewportSize(PHONE);
    await page.route('**/directory.list/**', (route) => route.fulfill({
      status: 200, contentType: 'application/json', body: JSON.stringify(directoryListing),
    }));
    await openWizard(page, theme);

    for (let step = 0; step <= 5; step += 1) {
      await wizardState(page, `
        state.formData.searchType = 'both';
        state.formData.torrentpotato.enabled = true;
        state.formData.newznab.enabled = true;
        state.formData.newznab.entries = [{ host: '', api_key: '' }, { host: '', api_key: '' }];
        state.jackettSyncing = ${step === 2};
        state.currentStep = ${step};
      `);
      await expect(page.locator('[x-text="steps[currentStep]"]')).toHaveText(
        ['Welcome', 'Security', 'Providers', 'Downloader', 'Library', 'Done'][step],
      );
      await expectVisualTransitionsToSettle(page, `wizard step ${step} (${theme})`);
      const results = await new AxeBuilder({ page })
        .withTags(['wcag2a', 'wcag2aa', 'wcag21a', 'wcag21aa', 'wcag22aa'])
        .analyze();
      const detail = results.violations
        .flatMap((v) => v.nodes.map((n) => `${v.id}: ${n.html} — ${n.failureSummary}`))
        .join('\n');
      expect(results.violations.length, `wizard step ${step}/${theme}:\n${detail}`).toBe(0);
    }

    await wizardState(page, 'state.currentStep = 4; state.browseDirectory("renamer_from");');
    const browser = page.locator('[x-show="browserOpen"]').filter({ hasText: 'Browse Folders' });
    await expect(browser.getByRole('button', { name: 'movies', exact: true })).toBeVisible();
    // The modal fades in: scanning mid-fade measures a translucent frame.
    await expectVisualTransitionsToSettle(page, `directory browser (${theme})`);
    const results = await new AxeBuilder({ page })
      .include('[x-show="browserOpen"]')
      .withTags(['wcag2a', 'wcag2aa', 'wcag21a', 'wcag21aa', 'wcag22aa'])
      .analyze();
    const detail = results.violations
      .flatMap((v) => v.nodes.map((n) => `${v.id}: ${n.html} — ${n.failureSummary}`))
      .join('\n');
    expect(results.violations.length, `directory browser/${theme}:\n${detail}`).toBe(0);
  });
}
