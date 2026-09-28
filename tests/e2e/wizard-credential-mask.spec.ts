import { test, expect } from './fixtures';

type Tracker = {
  id: string;
  name: string;
  fields: { name: string }[];
};

test('wizard renders every tracker credential as a password input', async ({ page }) => {
  // Use the server's Jinja-rendered markup, including its real tracker data,
  // but mount it directly so step-navigation cannot make the test vacuous.
  const response = await page.request.get('/wizard/');
  expect(response.ok()).toBeTruthy();
  const wizardHtml = await response.text();
  await page.goto('/'); // Give relative vendor script URLs the app's origin.
  await page.setContent(wizardHtml);

  const wizard = page.locator('[x-data="setupWizard()"]');
  await expect(page.locator('[x-text="steps[currentStep]"]')).toHaveText('Welcome');
  const trackers = await wizard.evaluate((element): Tracker[] => {
    const alpine = (window as any).Alpine;
    const state = alpine.$data(element);
    state.currentStep = 2;
    return state.privateTrackers.map((tracker: Tracker) => ({
      id: tracker.id,
      name: tracker.name,
      fields: tracker.fields.map((field) => ({ name: field.name })),
    }));
  });

  expect(trackers.length).toBeGreaterThanOrEqual(6);
  await page.getByRole('button', { name: /Private Trackers/ }).click();

  let credentialCount = 0;
  let usernameCount = 0;
  for (const tracker of trackers) {
    await page.getByRole('switch', { name: `Enable ${tracker.name}` }).click();
    for (const field of tracker.fields) {
      const input = page.locator(`#wizard-tracker-${tracker.id}-${field.name}`);
      await expect(input).toBeVisible();
      if (/api_?key|user_?key|passkey|pass_key|secret|token|password|cookie|auth/i.test(field.name)) {
        await expect(input).toHaveAttribute('type', 'password');
        credentialCount += 1;
      } else if (field.name === 'username') {
        await expect(input).toHaveAttribute('type', 'text');
        usernameCount += 1;
      }
    }
  }

  expect(credentialCount).toBeGreaterThanOrEqual(7);
  expect(usernameCount).toBe(trackers.length);
  await expect(page.locator('#wizard-tracker-hdbits-passkey')).toHaveAttribute('type', 'password');
  await expect(page.locator('#wizard-tracker-passthepopcorn-passkey')).toHaveAttribute('type', 'password');
});
