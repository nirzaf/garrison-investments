import { execFileSync } from 'node:child_process';
import { readFileSync } from 'node:fs';
import { env } from 'node:process';
import { fileURLToPath } from 'node:url';

import { expect, test } from '@playwright/test';

import type { components } from '../src/api/schema';

type TestAccount = { email: string; password: string; projectId: string };
type Reports = components['schemas']['DailyReportListResponse'];
type Photos = components['schemas']['PhotoListResponse'];

const backendDirectory = fileURLToPath(new URL('../../backend/', import.meta.url));
const photo = readFileSync(
  new URL('../../backend/scripts/assets/blockwork_day5.jpg', import.meta.url)
);

test('photos selected offline on one draft sync to one report, which can still be edited', async ({
  page,
  context,
  request
}) => {
  const account: TestAccount = JSON.parse(
    execFileSync(env.BROWSER_TEST_PYTHON ?? 'python', ['-m', 'tests.browser_fixtures', 'seed'], {
      cwd: backendDirectory,
      encoding: 'utf8'
    })
  );

  await page.goto('/login');
  await page.getByLabel('Email', { exact: true }).fill(account.email);
  await page.getByLabel('Password', { exact: true }).fill(account.password);
  await page.getByRole('button', { name: 'Continue' }).click();
  const developmentCode = page.getByText(/^Development code:/);
  await expect(developmentCode).toBeVisible();
  const code = (await developmentCode.innerText()).match(/\d{6}/)?.[0];
  if (!code) throw new Error('The test API did not expose the verification code.');
  await page.getByLabel('Verification code').fill(code);
  const verified = page.waitForResponse(
    (response) => response.url().endsWith('/api/v1/auth/verify-otp') && response.ok()
  );
  await page.getByRole('button', { name: 'Verify and sign in' }).click();
  const { access_token }: { access_token: string } = await (await verified).json();
  const headers = { Authorization: `Bearer ${access_token}` };
  const getReports = async () => {
    const response = await request.get('/api/v1/reports', {
      headers,
      params: { project_id: account.projectId }
    });
    expect(response.ok()).toBe(true);
    return (await response.json()) as Reports;
  };

  await page.getByRole('link', { name: 'Reports', exact: true }).click();
  await page
    .getByRole('combobox', { name: 'Project', exact: true })
    .selectOption(account.projectId);
  await page.getByLabel('Work area / location').fill('East wing');
  await page.getByLabel('Work completed').fill('Set the formwork.');
  await page.getByLabel('Next-day plan').fill('Pour concrete.');
  await page.getByLabel('Weather').fill('Sunny');
  await page.getByLabel('Site visitors').fill('None');
  await page.getByLabel('Subcontractors').fill('None');
  await page.getByLabel('WIR number').fill('Not required');
  await page.getByPlaceholder('Trade', { exact: true }).fill('Carpenter');
  await page.getByLabel('Attachment file names').fill('inspection-notes.pdf');
  await page.evaluate(() => navigator.serviceWorker.ready.then(() => undefined));

  const photosInput = page.getByLabel('Upload photos');
  const file = (name: string) => ({ name, mimeType: 'image/jpeg', buffer: photo });
  await context.setOffline(true);
  try {
    await photosInput.setInputFiles([file('formwork.jpg'), file('site.jpg')]);
    await expect(page.getByText('2 files queued for upload.')).toBeVisible();
    await photosInput.setInputFiles(file('inspection.jpg'));
    await expect(page.getByText('1 file queued for upload.')).toBeVisible();
    expect((await getReports()).total).toBe(0);
  } finally {
    await context.setOffline(false);
  }

  await expect
    .poll(
      async () => {
        const reports = await getReports();
        if (reports.total !== 1) return { reports: reports.total, photos: [] };
        const response = await request.get('/api/v1/photos', {
          headers,
          params: { entity_type: 'daily_report', entity_id: reports.items[0].id }
        });
        expect(response.ok()).toBe(true);
        const data: Photos = await response.json();
        return {
          reports: reports.total,
          photos: data.items.map((item) => item.original_name).sort()
        };
      },
      { timeout: 20_000 }
    )
    .toEqual({ reports: 1, photos: ['formwork.jpg', 'inspection.jpg', 'site.jpg'] });

  const original = (await getReports()).items[0];
  await page.reload();
  await expect(page.getByLabel('Work completed')).toHaveValue('Set the formwork.');
  await expect(page.getByLabel('Attachment file names')).toHaveValue('inspection-notes.pdf');
  await page.getByLabel('Work completed').fill('Set and inspected the formwork.');
  await page.getByRole('button', { name: 'Save draft' }).click();
  await expect(page.getByText('Daily report draft saved.')).toBeVisible();
  const saved = await getReports();
  expect(saved.total).toBe(1);
  expect(saved.items[0]).toMatchObject({
    id: original.id,
    status: 'draft',
    work_completed: 'Set and inspected the formwork.',
    attachment_refs: [{ name: 'inspection-notes.pdf', kind: 'file' }]
  });

  await page.getByLabel('Next-day plan').fill('Pour concrete after inspection.');
  await page.getByRole('button', { name: 'Submit report' }).click();
  await expect(page.getByText(/^Daily report .* submitted\.$/)).toBeVisible();
  const submitted = await getReports();
  expect(submitted.total).toBe(1);
  expect(submitted.items[0]).toMatchObject({
    id: original.id,
    status: 'submitted',
    next_day_plan: 'Pour concrete after inspection.'
  });
});
