import { execFileSync } from 'node:child_process';
import { readFileSync } from 'node:fs';
import { env } from 'node:process';
import { fileURLToPath } from 'node:url';

import { expect, test } from '@playwright/test';

test('a supervisor resumes a saved draft and submits the latest changes', async ({ page }) => {
  const account: { email: string; password: string; projectId: string } = JSON.parse(
    execFileSync(
      env.BROWSER_TEST_PYTHON ?? 'python',
      ['-m', 'tests.browser_fixtures', 'seed-supervisor'],
      { cwd: fileURLToPath(new URL('../../backend/', import.meta.url)), encoding: 'utf8' }
    )
  );

  await page.clock.setFixedTime(new Date('2026-11-11T20:59:00Z'));
  await page.goto('/login');
  await page.getByLabel('Email', { exact: true }).fill(account.email);
  await page.getByLabel('Password', { exact: true }).fill(account.password);
  await page.getByRole('button', { name: 'Continue' }).click();
  const code = (await page.getByText(/^Development code:/).innerText()).match(/\d{6}/)?.[0];
  if (!code) throw new Error('The test API did not expose the verification code.');
  await page.getByLabel('Verification code').fill(code);
  await page.getByRole('button', { name: 'Verify and sign in' }).click();

  await page.clock.setFixedTime(new Date('2026-11-11T21:01:00Z'));
  await page.getByRole('link', { name: 'Reports', exact: true }).click();
  await expect(page.getByLabel('Update date')).toHaveValue('2026-11-12');
  await page.clock.setFixedTime(new Date());
  await page.reload();
  await page
    .getByRole('combobox', { name: 'Project', exact: true })
    .selectOption(account.projectId);
  await page.getByLabel('Work location').fill('North wing');
  await page.getByLabel('Progress notes').fill('Completed initial inspection.');
  await page.getByLabel('Required notes').fill('Check handrails.');
  await page.getByRole('button', { name: 'Save draft' }).click();
  await expect(page.getByText('Draft saved.', { exact: true })).toBeVisible();
  const record = page.getByRole('article').filter({ hasText: 'North wing' });
  await expect(record.getByText('draft', { exact: true })).toBeVisible();
  await page.locator('input[type="file"][capture="environment"]').setInputFiles({
    name: 'handrails.jpg',
    mimeType: 'image/jpeg',
    buffer: readFileSync(
      new URL('../../backend/scripts/assets/blockwork_day5.jpg', import.meta.url)
    )
  });
  await expect(page.getByText('1 file saved.', { exact: true })).toBeVisible();

  await page.reload();
  await record.getByRole('button', { name: 'Resume draft' }).click({ timeout: 5_000 });
  await expect(page.getByLabel('Progress notes')).toHaveValue('Completed initial inspection.');
  await expect(page.getByText('handrails.jpg', { exact: true })).toBeVisible();
  await page.getByLabel('Progress notes').fill('Started the handrail checks.');
  await page.getByRole('button', { name: 'Save draft' }).click();
  await expect(record.getByText('Started the handrail checks.', { exact: true })).toBeVisible();

  await page
    .getByLabel('Progress notes')
    .fill('Verified the handrails after the final inspection.');
  await page.clock.setFixedTime(new Date('2026-11-12T21:01:00Z'));
  await page.getByRole('button', { name: 'Submit update' }).click();
  await expect(page.getByText('Site update submitted.', { exact: true })).toBeVisible();
  await expect(page.getByLabel('Update date')).toHaveValue('2026-11-13');
  await page.reload();
  await expect(page.getByLabel('Update date')).toHaveValue('2026-11-13');
  await expect(record).toHaveCount(1);
  await expect(record.getByText('submitted', { exact: true })).toBeVisible();
  await expect(
    record.getByText('Verified the handrails after the final inspection.')
  ).toBeVisible();
});
