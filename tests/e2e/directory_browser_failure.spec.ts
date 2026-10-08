import { test, expect } from './fixtures';
import { mockSettingsSave } from './helpers';

const emptyListing = { dirs: [], empty: true, parent: '/', home: '/', is_root: true, platform: 'posix' };
const failedListing = { ...emptyListing, success: false, error: 'Unable to list directory' };

test('settings picker announces a failed listing and only selects after retry on a phone', async ({ page }) => {
  await page.setViewportSize({ width: 393, height: 851 });
  let requests = 0;
  await page.route('**/directory.list/**', async route => {
    requests += 1;
    const payload = requests === 1 ? failedListing
      : requests === 2 ? { ...emptyListing, dirs: ['/chosen/'] } : emptyListing;
    await route.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify(payload) });
  });
  await mockSettingsSave(page);
  await page.goto('/settings/');
  await page.getByRole('tab', { name: 'Library' }).click();
  await page.getByRole('heading', { name: 'Movie Library' }).click();
  await page.locator('button', { hasText: '+ Add folder' }).click();
  const folderInput = page.getByRole('button', { name: 'Browse for folder 1' }).locator('..').locator('input');
  await folderInput.fill('/previous/');
  await page.getByRole('button', { name: 'Browse for folder 1' }).click();

  const dialog = page.getByRole('dialog', { name: 'Browse Folders' });
  await expect(dialog.getByRole('alert')).toContainText('Unable to list directory');
  await expect(dialog.locator('[aria-label="Current path"]')).toHaveText('/previous/');
  await expect(dialog.getByText('Empty folder')).toBeHidden();
  await expect(dialog.getByRole('button', { name: 'Select This Folder' })).toHaveAttribute('aria-disabled', 'true');
  await dialog.getByRole('button', { name: 'Select This Folder' }).focus();
  await page.keyboard.press('Enter');
  await expect(dialog).toBeVisible();
  await expect(folderInput).toHaveValue('/previous/');

  await dialog.getByRole('button', { name: 'Retry' }).click();
  await dialog.getByRole('button', { name: 'chosen' }).click();
  await expect(dialog.getByText('Empty folder')).toBeVisible();
  await expect(dialog.getByRole('button', { name: 'Select This Folder' })).toHaveAttribute('aria-disabled', 'false');
  await dialog.getByRole('button', { name: 'Select This Folder' }).focus();
  await page.keyboard.press('Enter');
  await expect(dialog).toBeHidden();
  await expect(folderInput).toHaveValue('/chosen/');
});

test('setup picker keeps its form value on HTTP failure and selects after retry by keyboard', async ({ page }) => {
  await page.setViewportSize({ width: 393, height: 851 });
  let requests = 0;
  await page.route('**/directory.list/**', async route => {
    requests += 1;
    await route.fulfill({ status: requests === 1 ? 503 : 200, contentType: 'application/json', body: JSON.stringify(emptyListing) });
  });
  await page.goto('/wizard/');
  await page.evaluate(() => {
    const root = document.querySelector('[x-data="setupWizard()"]') as HTMLElement;
    const wizard = (window as any).Alpine.$data(root);
    wizard.formData.renamer.from = '/previous/';
    wizard.browseDirectory('renamer_from');
  });

  const browser = page.locator('[x-show="browserOpen"]').filter({ hasText: 'Browse Folders' });
  await expect(browser.getByRole('alert')).toContainText('Unable to list directory');
  await expect(browser.getByText('Empty folder')).toBeHidden();
  await expect(browser.getByRole('button', { name: 'Up' })).toHaveCSS('opacity', '0.3');
  await browser.getByRole('button', { name: 'Select This Folder' }).focus();
  await page.keyboard.press('Enter');
  await expect(browser).toBeVisible();
  expect(await page.evaluate(() => {
    const root = document.querySelector('[x-data="setupWizard()"]') as HTMLElement;
    return (window as any).Alpine.$data(root).formData.renamer.from;
  })).toBe('/previous/');

  await browser.getByRole('button', { name: 'Retry' }).click();
  await expect(browser.getByText('Empty folder')).toBeVisible();
  await browser.getByRole('button', { name: 'Select This Folder' }).focus();
  await page.keyboard.press('Enter');
  await expect(browser).toBeHidden();
  expect(await page.evaluate(() => {
    const root = document.querySelector('[x-data="setupWizard()"]') as HTMLElement;
    return (window as any).Alpine.$data(root).formData.renamer.from;
  })).toBe('/');
});

for (const oldFails of [false, true]) {
test(`settings picker ignores a ${oldFails ? 'failed' : 'successful'} listing from a previously closed field`, async ({ page }) => {
  let releaseOld!: () => void;
  let signalOld!: () => void;
  const oldStarted = new Promise<void>(resolve => { signalOld = resolve; });
  let requests = 0;
  await page.route('**/directory.list/**', async route => {
    const requestNumber = ++requests;
    if (requestNumber === 1) {
      await new Promise<void>(resolve => { releaseOld = resolve; signalOld(); });
    }
    await route.fulfill({ status: 200, contentType: 'application/json',
      body: requestNumber === 1 && oldFails ? '{invalid JSON' : JSON.stringify(emptyListing),
    });
  });
  await mockSettingsSave(page);
  await page.goto('/settings/');
  await page.evaluate(() => {
    const panel = (window as any).Alpine.$data(document.querySelector('[x-data="settingsPanel()"]'));
    panel.dirty['browser_test.first'] = '/old-folder/';
    panel.dirty['browser_test.second'] = '/new-folder/';
    (window as any).__oldDirectoryBrowse = panel.browseDirectory('browser_test', 'first');
  });
  await oldStarted;
  await page.evaluate(() => {
    const panel = (window as any).Alpine.$data(document.querySelector('[x-data="settingsPanel()"]'));
    panel.browserOpen = false;
    (window as any).__newDirectoryBrowse = panel.browseDirectory('browser_test', 'second');
  });
  await page.evaluate(() => (window as any).__newDirectoryBrowse);
  releaseOld();
  await page.evaluate(() => (window as any).__oldDirectoryBrowse);
  expect(await page.evaluate(() => {
    const panel = (window as any).Alpine.$data(document.querySelector('[x-data="settingsPanel()"]'));
    return panel.browserError;
  })).toBe('');
  await expect.poll(() => page.evaluate(() => {
    const panel = (window as any).Alpine.$data(document.querySelector('[x-data="settingsPanel()"]'));
    return panel.browserValid ? panel.browserPath : 'pending';
  })).toBe('/new-folder/');
  await page.evaluate(() => {
    const panel = (window as any).Alpine.$data(document.querySelector('[x-data="settingsPanel()"]'));
    panel.confirmDirectory();
  });
  expect(await page.evaluate(() => {
    const panel = (window as any).Alpine.$data(document.querySelector('[x-data="settingsPanel()"]'));
    return panel.dirty['browser_test.second'];
  })).toBe('/new-folder/');
  expect(requests).toBe(2);
});
}

test('setup picker ignores an old child listing after reopening for another field', async ({ page }) => {
  let releaseOld!: () => void;
  let signalOld!: () => void;
  const oldStarted = new Promise<void>(resolve => { signalOld = resolve; });
  let requests = 0;
  await page.route('**/directory.list/**', async route => {
    requests += 1;
    if (requests === 2) {
      await new Promise<void>(resolve => { releaseOld = resolve; signalOld(); });
    }
    await route.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify(emptyListing) });
  });
  await page.goto('/wizard/');
  await page.evaluate(async () => {
    const wizard = (window as any).Alpine.$data(document.querySelector('[x-data="setupWizard()"]'));
    await wizard.browseDirectory('renamer_from');
    (window as any).__oldDirectoryBrowse = wizard.loadDirectories('/old-folder/');
  });
  await oldStarted;
  await page.evaluate(() => {
    const wizard = (window as any).Alpine.$data(document.querySelector('[x-data="setupWizard()"]'));
    wizard.browserOpen = false;
    wizard.formData.renamer.to = '/previous/';
    (window as any).__newDirectoryBrowse = wizard.browseDirectory('renamer_to');
  });
  await page.evaluate(() => (window as any).__newDirectoryBrowse);
  releaseOld();
  await page.evaluate(() => (window as any).__oldDirectoryBrowse);
  await expect.poll(() => page.evaluate(() => {
    const wizard = (window as any).Alpine.$data(document.querySelector('[x-data="setupWizard()"]'));
    return wizard.browserValid ? wizard.browserPath : 'pending';
  })).toBe('/');
  await page.evaluate(() => {
    const wizard = (window as any).Alpine.$data(document.querySelector('[x-data="setupWizard()"]'));
    wizard.confirmDirectory();
  });
  expect(await page.evaluate(() => {
    const wizard = (window as any).Alpine.$data(document.querySelector('[x-data="setupWizard()"]'));
    return wizard.formData.renamer.to;
  })).toBe('/');
  expect(requests).toBe(3);
});
