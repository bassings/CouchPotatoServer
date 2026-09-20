import { Locator, Page } from '@playwright/test';
import { test, expect } from './fixtures';


async function expectHeadingFitsViewport(heading: Locator) {
  await expect(heading).toBeVisible();
  await heading.scrollIntoViewIfNeeded();
  await expect(heading).toBeInViewport({ ratio: 1 });
  const bounds = await heading.evaluate((element) => {
    const box = element.getBoundingClientRect();
    return {
      left: box.left,
      right: box.right,
      viewportWidth: document.documentElement.clientWidth,
    };
  });
  expect(bounds.left).toBeGreaterThanOrEqual(0);
  expect(bounds.right).toBeLessThanOrEqual(bounds.viewportWidth);
}


async function expectNativeListFitsViewport(
  list: Locator,
  expectedItems?: number,
  expectedMarginBlockEnd = '0px',
) {
  await expect(list).toBeVisible();
  await expect(list).toHaveJSProperty('tagName', 'OL');
  await expect(list).toHaveAttribute('role', 'list');

  const reset = await list.evaluate((element) => {
    const style = getComputedStyle(element);
    return {
      listStyleType: style.listStyleType,
      marginInlineStart: style.marginInlineStart,
      marginBlockStart: style.marginBlockStart,
      marginBlockEnd: style.marginBlockEnd,
      paddingInlineStart: style.paddingInlineStart,
    };
  });
  expect(reset).toEqual({
    listStyleType: 'none',
    marginInlineStart: '0px',
    marginBlockStart: '0px',
    marginBlockEnd: expectedMarginBlockEnd,
    paddingInlineStart: '0px',
  });

  const items = list.getByRole('listitem');
  if (expectedItems === undefined) {
    expect(await items.count(), 'native list rendered no items').toBeGreaterThan(0);
  } else {
    await expect(items).toHaveCount(expectedItems);
  }

  const viewportWidth = await list.evaluate(() => window.innerWidth);
  for (const item of await items.all()) {
    await expect(item).toHaveJSProperty('tagName', 'LI');
    await expect(item).not.toHaveAttribute('role');
    const box = await item.boundingBox();
    expect(box, 'native list item has no rendered box').not.toBeNull();
    expect(box!.x).toBeGreaterThanOrEqual(0);
    expect(box!.x + box!.width).toBeLessThanOrEqual(viewportWidth);
  }
}

async function openSettingsTab(page: Page, name: 'Categories' | 'Profiles') {
  await page.goto('/settings/');
  await expect(page.locator('h1')).toContainText('Settings');
  await page.getByRole('tab', { name }).click();
  const panel = page.locator(`#${name.toLowerCase()}-panel`);
  await expect(panel).toBeVisible();
  const singular = name === 'Categories' ? 'category' : 'profile';
  await expect(panel.getByRole('button', { name: new RegExp(`new ${singular}`, 'i') })).toBeVisible();
  return panel;
}

for (const theme of ['light', 'dark'] as const) {
  test(`ordered settings lists retain native semantics and mobile layout in ${theme} theme`, async ({ page }) => {
    expect(page.viewportSize()!.width).toBe(393);
    await page.addInitScript((selectedTheme) => {
      localStorage.setItem('cp-theme', selectedTheme);
    }, theme);

    await page.goto('/settings/');
    await expect(page.getByRole('tablist', { name: 'Settings categories' })).toBeVisible();
    await page.getByRole('tab', { name: 'Searchers' }).click();
    const settingsHeadings = [
      page.getByRole('heading', { name: 'Search Settings', level: 3 }),
      page.getByRole('heading', { name: 'Usenet — Account Required', level: 2 }),
      page.getByRole('heading', { name: 'Newznab', level: 3 }),
    ];
    for (const heading of settingsHeadings) {
      await expectHeadingFitsViewport(heading);
    }

    const categories = await openSettingsTab(page, 'Categories');
    const categoryName = `E2E Native List ${theme}`;
    await categories.getByRole('button', { name: /new category/i }).click();
    const categoryModal = page.getByTestId('category-edit-modal');
    await expect(categoryModal).toBeVisible();
    await expectHeadingFitsViewport(
      categoryModal.getByRole('heading', { name: 'New Category', level: 3 }),
    );
    await categoryModal
      .getByPlaceholder('e.g. Horror, Kids, Documentary')
      .fill(categoryName);
    await categoryModal.getByRole('button', { name: /create category/i }).click();
    await expect(categoryModal).not.toBeVisible();
    await expect(categories.getByRole('button', { name: `Delete category: ${categoryName}` })).toBeVisible();
    await expectNativeListFitsViewport(categories.getByRole('list', { name: 'Categories' }));

    await categories.getByRole('button', { name: `Delete category: ${categoryName}` }).click();
    const deleteDialog = page.getByTestId('category-delete-dialog');
    await expect(deleteDialog).toBeVisible();
    await deleteDialog.getByRole('button', { name: /^delete$/i }).click();
    await expect(deleteDialog).not.toBeVisible();

    const profiles = await openSettingsTab(page, 'Profiles');
    await expectNativeListFitsViewport(profiles.getByRole('list', { name: 'Quality profiles' }));

    await profiles.getByRole('button', { name: /new profile/i }).click();
    const modal = page.getByTestId('edit-modal');
    await expect(modal).toBeVisible();
    await expectHeadingFitsViewport(
      modal.getByRole('heading', { name: 'New Profile', level: 3 }),
    );
    const qualityList = modal.getByRole('list', { name: 'Qualities in this profile' });

    for (let index = 0; index < 2; index++) {
      await modal.locator('select').first().selectOption({ index: 1 });
      await modal.getByRole('button', { name: /^add$/i }).click();
      await expect(qualityList.getByRole('listitem')).toHaveCount(index + 1);
    }
    await expectNativeListFitsViewport(qualityList, 2, '12px');

    const layout = await page.evaluate(() => ({
      clientWidth: document.documentElement.clientWidth,
      scrollWidth: document.documentElement.scrollWidth,
      light: document.documentElement.classList.contains('light'),
    }));
    expect(layout.scrollWidth).toBeLessThanOrEqual(layout.clientWidth);
    expect(layout.light).toBe(theme === 'light');
  });
}
