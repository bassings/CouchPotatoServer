import { test, expect } from './fixtures';

/**
 * The wizard's Providers step makes its settings saves in a fixed order, and
 * the values it sends depend on `.filter(Boolean)`-style trimming of empty
 * indexer rows. No other spec reaches this step with providers switched on, so
 * this pins the exact call sequence and payloads that step produces.
 *
 * The saves are sent concurrently, so the order in which `page.route` sees the
 * requests is the browser's, not the code's. The CALL order is therefore
 * recorded inside the page by wrapping the component's `saveSetting` (which
 * still delegates, so the requests are really made); the intercepted requests
 * are asserted separately, as an order-independent set.
 *
 * Saves are intercepted with `page.route`, so nothing is written to the
 * per-worker server. The values are placeholders, not credentials.
 */
test('Providers step saves each enabled provider in a fixed order with trimmed lists', async ({ page }) => {
  const saves: string[] = [];
  await page.route('**/settings.save/**', async (route) => {
    const params = new URLSearchParams(route.request().postData() || '');
    saves.push(`${params.get('section')}.${params.get('name')}=${params.get('value')}`);
    await route.fulfill({
      status: 200,
      contentType: 'application/json',
      body: JSON.stringify({ success: true }),
    });
  });

  await page.goto('/wizard/');
  await page.getByRole('button', { name: /Continue/i }).click();           // Welcome -> Security
  await page.getByRole('button', { name: /Continue/i }).click();           // Security -> Providers (saves nothing)
  await expect(page.getByRole('heading', { name: 'Where to Search' })).toBeVisible({ timeout: 10000 });
  expect(saves, 'the Security step saved something although both fields were empty').toEqual([]);

  await page.getByRole('radio', { name: /^Both/ }).click();

  await page.getByRole('switch', { name: 'Enable Newznab Indexers' }).click();
  await page.getByRole('button', { name: '+ Add another indexer' }).click();
  await page.getByRole('button', { name: '+ Add another indexer' }).click();
  await page.getByLabel('Newznab indexer URL 1').fill('https://indexer-one.invalid');
  await page.getByLabel('Newznab API key 1').fill('placeholder-key-one');
  // Row 2 has a key but no host: the host is dropped, the key is kept, and
  // the "use" flag for the row is 0.
  await page.getByLabel('Newznab API key 2').fill('placeholder-key-two');
  // Row 3 has a host but no key.
  await page.getByLabel('Newznab indexer URL 3').fill('https://indexer-three.invalid');

  await page.getByRole('switch', { name: 'Enable ThePirateBay' }).click();
  await page.getByRole('switch', { name: 'Enable Jackett / TorrentPotato' }).click();
  await page.locator('#wizard-jackett-url').fill('http://jackett.invalid:9117');
  await page.locator('#wizard-jackett-api-key').fill('placeholder-jackett-key');

  await page.evaluate(() => {
    const root = document.querySelector('[x-data="setupWizard()"]');
    if (!root) throw new Error('Wizard root is absent');
    const wizard = (window as any).Alpine.$data(root);
    const original = wizard.saveSetting;
    const calls: string[][] = [];
    (window as any).__saveCalls = calls;
    wizard.saveSetting = function (section: string, name: string, value: string) {
      calls.push([section, name, value]);
      return original.call(this, section, name, value);
    };
  });

  await page.getByRole('button', { name: /Continue/i }).click();
  await expect(page.getByRole('heading', { name: 'Where to Search' })).toBeHidden({ timeout: 10000 });

  const calls = await page.evaluate(() => (window as any).__saveCalls);
  expect(calls).toEqual([
    ['newznab', 'enabled', '1'],
    ['newznab', 'host', 'https://indexer-one.invalid,https://indexer-three.invalid'],
    ['newznab', 'api_key', 'placeholder-key-one,placeholder-key-two'],
    ['newznab', 'use', '1,0,1'],
    ['binsearch', 'enabled', '0'],
    ['thepiratebay', 'enabled', '1'],
    ['yts', 'enabled', '0'],
    ['torrentpotato', 'enabled', '1'],
    ['torrentpotato', 'jackett_url', 'http://jackett.invalid:9117'],
    ['torrentpotato', 'jackett_api_key', 'placeholder-jackett-key'],
  ]);

  // Requests as the browser delivered them: same saves, any order.
  const sent = calls.map(([section, name, value]) => `${section}.${name}=${value}`);
  expect(saves).toHaveLength(sent.length);
  expect([...saves].sort()).toEqual([...sent].sort());
});
