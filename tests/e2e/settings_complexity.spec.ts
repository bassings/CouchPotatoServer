import { test, expect } from './fixtures';

test.beforeEach(async ({ page }) => {
  await page.goto('/settings/');
  await expect(page.locator('h1')).toContainText('Settings');
});

test('settings load builds preferred and custom tab order and records version', async ({ page }) => {
  const state = await page.evaluate(async () => {
    const panel = (window as any).settingsPanel();
    const watched: string[] = [];
    panel.$watch = (name: string) => watched.push(name);
    const originalFetch = window.fetch;
    window.fetch = (async input => {
      const url = String(input);
      if (url.endsWith('/settings/')) {
        return new Response(JSON.stringify({
          options: {
            renamer: { groups: [{ name: 'rename', tab: 'renamer' }] },
            custom: { groups: [{ name: 'extra', tab: 'extra' }] },
            general: { groups: [{ name: 'base', tab: 'general' }] },
            searcher: { groups: [{ name: 'find', tab: 'searcher' }] },
            automation: { groups: [{ name: 'hidden', tab: 'automation' }] },
          },
          values: { general: { enabled: true } },
        }));
      }
      if (url.endsWith('/updater.info/')) {
        return new Response(JSON.stringify({ version: { repr: 'v1' }, update_version: 'v2' }));
      }
      throw new Error(`Unexpected fetch: ${url}`);
    }) as typeof window.fetch;
    try {
      await panel.init();
      return {
        watched,
        loading: panel.loading,
        tabs: panel.tabOrder,
        version: panel.version,
        updateAvailable: panel.updateAvailable,
        value: panel.values.general.enabled,
      };
    } finally {
      window.fetch = originalFetch;
    }
  });

  expect(state).toEqual({
    watched: ['activeTab', 'showAdvanced'],
    loading: false,
    tabs: ['general', 'searcher', 'renamer', 'extra', 'profiles', 'categories', 'logs'],
    version: 'v1',
    updateAvailable: 'v2',
    value: true,
  });
});

test('settings load failure clears loading and reports an error', async ({ page }) => {
  const state = await page.evaluate(async () => {
    const root = document.querySelector('[x-data="settingsPanel()"]');
    if (!root) throw new Error('Settings panel is absent');
    const panel = (window as any).Alpine.$data(root);
    panel.loading = true;
    const originalFetch = window.fetch;
    window.fetch = (async () => { throw new Error('offline'); }) as typeof window.fetch;
    try {
      await panel.init();
      return { loading: panel.loading, message: panel.message, messageType: panel.messageType };
    } finally {
      window.fetch = originalFetch;
    }
  });

  expect(state).toEqual({ loading: false, message: 'Failed to load settings', messageType: 'error' });
});

test('settings groups preserve combined order, category order and visibility rules', async ({ page }) => {
  const groups = await page.evaluate(() => {
    const panel = (window as any).settingsPanel();
    panel.advancedSections = new Set(['advanced_section']);
    panel.options = {
      searcher: { groups: [
        { name: 'general', tab: 'searcher', label: 'Search' },
        { name: 'filter', tab: 'searcher', label: 'Filter' },
      ] },
      torrent: { groups: [{ name: 'general', tab: 'searcher', label: 'Torrent' }] },
      newznab: { order: 2, groups: [{ name: 'provider', tab: 'searcher' }] },
      binsearch: { order: 12, groups: [{ name: 'provider', tab: 'searcher' }] },
      awesomehd: { groups: [{ name: 'hidden', tab: 'searcher' }] },
      advanced_section: { groups: [{ name: 'advanced', tab: 'searcher' }] },
      remapped: { groups: [{ name: 'display', tab: 'automation' }] },
    };
    const searcher = panel.getTabGroups('searcher');
    const display = panel.getTabGroups('display');
    return {
      searcher: searcher.map((group: any) => ({
        section: group.section,
        category: group._category ?? null,
        combined: group._combinedGroups?.map((part: any) => `${part.section}.${part.name}`) ?? null,
      })),
      display: display.map((group: any) => `${group.section}.${group.name}`),
    };
  });

  expect(groups.searcher).toEqual([
    {
      section: '_combined',
      category: null,
      combined: ['searcher.general', 'searcher.filter', 'torrent.general'],
    },
    { section: 'binsearch', category: 'usenet-free', combined: null },
    { section: 'newznab', category: 'usenet-account', combined: null },
  ]);
  expect(groups.display).toEqual(['remapped.display']);
});

test('a refused settings save keeps the submitted value dirty and the old value visible', async ({ page }) => {
  await page.route('**/settings.save/**', route => route.fulfill({
    status: 503,
    contentType: 'application/json',
    body: JSON.stringify({ success: false, error: 'temporarily unavailable' }),
  }));

  const state = await page.evaluate(async () => {
    const root = document.querySelector('[x-data="settingsPanel()"]');
    if (!root) throw new Error('Settings panel is absent');
    const panel = (window as any).Alpine.$data(root);
    panel.values.core.sonar_contract = 'before';
    panel.dirty['core.sonar_contract'] = 'submitted';
    await panel.saveSingle('core', 'sonar_contract', 'submitted');
    return {
      value: panel.values.core.sonar_contract,
      dirty: panel.dirty['core.sonar_contract'],
      saving: panel.saving,
      lastSaved: panel.lastSaved,
      message: panel.message,
      messageType: panel.messageType,
    };
  });

  expect(state).toEqual({
    value: 'before',
    dirty: 'submitted',
    saving: false,
    lastSaved: false,
    message: 'Could not save sonar_contract: temporarily unavailable',
    messageType: 'error',
  });
  await expect(page.getByTestId('settings-announcer-assertive')).toHaveText(state.message);
  await expect(page.getByTestId('settings-announcer-polite')).toBeEmpty();
});

test('a successful secret save never copies the submitted secret into display state', async ({ page }) => {
  const secret = 'synthetic-secret-for-sonar-contract';
  let postedValue: string | null = null;
  await page.route('**/settings.save/**', route => {
    postedValue = new URLSearchParams(route.request().postData() || '').get('value');
    return route.fulfill({
      status: 200,
      contentType: 'application/json',
      body: JSON.stringify({ success: true }),
    });
  });

  const state = await page.evaluate(async submitted => {
    const root = document.querySelector('[x-data="settingsPanel()"]');
    if (!root) throw new Error('Settings panel is absent');
    const panel = (window as any).Alpine.$data(root);
    panel.values.core.password = '********';
    panel.dirty['core.password'] = submitted;
    await panel.saveSingle('core', 'password', submitted);
    return {
      value: panel.values.core.password,
      dirty: panel.dirty['core.password'] ?? null,
      needsRestart: panel.needsRestart,
      lastSaved: panel.lastSaved,
      message: panel.message,
    };
  }, secret);

  expect(postedValue).toBe(secret);
  expect(state.value).toBe('********');
  expect(state.dirty).toBeNull();
  expect(state.needsRestart).toBe(true);
  expect(state.lastSaved).toBe(true);
  expect(state.message).not.toContain(secret);
  await expect(page.getByText(secret)).toHaveCount(0);
});
