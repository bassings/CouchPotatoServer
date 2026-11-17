import { test, expect } from './fixtures';
import { openProvidersStep, recordWizardRequests } from './helpers';

/**
 * The wizard's Providers step makes its settings saves in a fixed order, and
 * the Newznab rows it sends depend on what was read and what was typed. No other
 * spec reaches this step with providers switched on, so this pins the exact
 * calls and payloads that step produces (SEC-004 P5).
 *
 * Newznab is saved as ONE group (`settings.save_group`, all five columns for every
 * row, hidden rows included at their stored positions), AWAITED before anything
 * else: `newznab.enabled` and every other save of the step are issued only after
 * it has succeeded. The other saves are per setting and sent together, so their
 * order is the browser's; the order of the group save against them is asserted
 * from the requests as they arrive.
 *
 * Saves are intercepted with `page.route`, so nothing is written to the
 * per-worker server. This runs against a fresh install, whose six keyless default
 * hosts are the hidden rows: they are read from the server, not assumed. The
 * values are placeholders, not credentials.
 */
const DEFAULT_ROW_COUNT = 6;

test('Providers step saves Newznab as one group first, then each enabled provider', async ({ page, testServer }) => {
  const order: string[] = [];
  const groupBodies: any[] = [];
  const singleSaves: string[] = [];
  await page.route('**/settings.save_group/**', async (route) => {
    order.push('group');
    groupBodies.push(JSON.parse(route.request().postData() || '{}'));
    await route.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify({ success: true }) });
  });
  await page.route('**/settings.save/**', async (route) => {
    const params = new URLSearchParams(route.request().postData() || '');
    order.push(`${params.get('section')}.${params.get('name')}`);
    singleSaves.push(`${params.get('section')}.${params.get('name')}=${params.get('value')}`);
    await route.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify({ success: true }) });
  });
  const requests = await recordWizardRequests(page);

  await page.goto('/wizard/');
  await page.getByRole('button', { name: /Continue/i }).click();           // Welcome -> Security
  await page.getByRole('button', { name: /Continue/i }).click();           // Security -> Providers (saves nothing)
  await expect(page.getByRole('heading', { name: 'Where to Search' })).toBeVisible({ timeout: 10000 });
  expect(order, 'the Security step saved something although both fields were empty').toEqual([]);

  await page.getByRole('radio', { name: /^Both/ }).click();
  await page.getByRole('switch', { name: 'Enable Newznab Indexers' }).click();
  await page.getByRole('button', { name: '+ Add another indexer' }).click();
  await page.getByRole('button', { name: '+ Add another indexer' }).click();
  await page.getByLabel('Newznab indexer URL 1').fill('https://indexer-one.invalid');
  await page.getByLabel('Newznab API key 1').fill('placeholder-key-one');
  // Row 2 has a key but no host: a row with no URL is dropped whole, key included.
  await page.getByLabel('Newznab API key 2').fill('placeholder-key-two');
  // Row 3 has a host but no key.
  await page.getByLabel('Newznab indexer URL 3').fill('https://indexer-three.invalid');

  await page.getByRole('switch', { name: 'Enable ThePirateBay' }).click();
  await page.getByRole('switch', { name: 'Enable Jackett / TorrentPotato' }).click();
  await page.locator('#wizard-jackett-url').fill('http://jackett.invalid:9117');
  await page.locator('#wizard-jackett-api-key').fill('placeholder-jackett-key');

  const stored = await (await page.request.get(`${testServer.apiBase}/settings/`)).json();
  const defaultHosts: string[] = stored.values.newznab.host.split(',');
  expect(defaultHosts, 'the fresh install no longer has six default hosts').toHaveLength(DEFAULT_ROW_COUNT);

  await page.getByRole('button', { name: /Continue/i }).click();
  await expect(page.getByRole('heading', { name: 'Where to Search' })).toBeHidden({ timeout: 10000 });

  // One group save, for newznab, carrying every column of every row.
  expect(groupBodies).toHaveLength(1);
  expect(groupBodies[0].section).toBe('newznab');
  const rows: Record<string, string>[] = groupBodies[0].rows;
  expect(rows.map((row) => Object.keys(row).sort())).toEqual(
    rows.map(() => ['api_key', 'custom_tag', 'extra_score', 'host', 'use']),
  );
  // The six keyless defaults are kept, in place and unchanged; then the two new rows.
  expect(rows.slice(0, DEFAULT_ROW_COUNT).map((row) => row.host)).toEqual(defaultHosts);
  expect(rows.slice(0, DEFAULT_ROW_COUNT).every((row) => row.api_key === '' && row.use === '0')).toBe(true);
  expect(rows.slice(DEFAULT_ROW_COUNT)).toEqual([
    { use: '1', host: 'https://indexer-one.invalid', api_key: 'placeholder-key-one', extra_score: '0', custom_tag: '' },
    { use: '1', host: 'https://indexer-three.invalid', api_key: '', extra_score: '0', custom_tag: '' },
  ]);

  // The per-setting saves: seven, and the only newznab one is `enabled`.
  await expect.poll(() => order.length, { message: 'the saves after the group save never all arrived' }).toBe(1 + 7);
  expect([...singleSaves].sort()).toEqual([
    'binsearch.enabled=0',
    'newznab.enabled=1',
    'thepiratebay.enabled=1',
    'torrentpotato.enabled=1',
    'torrentpotato.jackett_api_key=placeholder-jackett-key',
    'torrentpotato.jackett_url=http://jackett.invalid:9117',
    'yts.enabled=0',
  ]);
  expect(order[0], 'the group was not saved first').toBe('group');
  expect(order.indexOf('newznab.enabled')).toBeGreaterThan(order.indexOf('group'));
  const newznabSaves = requests.columnSaves()
    .map((request) => new URLSearchParams(request.body))
    .filter((params) => params.get('section') === 'newznab')
    .map((params) => params.get('name'));
  expect(newznabSaves, 'a newznab column was saved on its own').toEqual(['enabled']);
});
