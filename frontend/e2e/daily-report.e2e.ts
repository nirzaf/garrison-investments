import { execFileSync } from 'node:child_process';
import { readFileSync } from 'node:fs';
import { env } from 'node:process';
import { fileURLToPath } from 'node:url';

import { expect, test, type Page } from '@playwright/test';

import type { components } from '../src/api/schema';

type TestAccount = { email: string; password: string; projectId: string };
type Reports = components['schemas']['DailyReportListResponse'];
type Photos = components['schemas']['PhotoListResponse'];

const backendDirectory = fileURLToPath(new URL('../../backend/', import.meta.url));
const photo = readFileSync(
  new URL('../../backend/scripts/assets/blockwork_day5.jpg', import.meta.url)
);

function seed(...args: string[]): TestAccount {
  return JSON.parse(
    execFileSync(env.BROWSER_TEST_PYTHON ?? 'python', ['-m', 'tests.browser_fixtures', ...args], {
      cwd: backendDirectory,
      encoding: 'utf8'
    })
  );
}

async function signIn(page: Page, account: TestAccount) {
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
  return { Authorization: `Bearer ${access_token}` };
}

test('offline report photos and verified supervisor evidence survive rejection and resubmission', async ({
  browser,
  page,
  context,
  request
}) => {
  const account = seed('seed');
  const supervisor = seed('seed-supervisor', '--project-id', account.projectId);
  const supervisorPage = await browser.newPage();
  await signIn(supervisorPage, supervisor);
  await supervisorPage.getByRole('link', { name: 'Reports', exact: true }).click();
  await supervisorPage
    .getByRole('combobox', { name: 'Project', exact: true })
    .selectOption(account.projectId);
  await supervisorPage.getByLabel('Work location').fill('Linked supervisor evidence');
  await supervisorPage.getByLabel('Progress notes').fill('Checked the formwork before handover.');
  await supervisorPage.getByLabel('Required notes').fill('Inspect again before concrete.');
  await supervisorPage.getByRole('button', { name: 'Submit update' }).click();
  await expect(supervisorPage.getByText('Site update submitted.', { exact: true })).toBeVisible();
  await supervisorPage.close();

  const headers = await signIn(page, account);
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
  await page.getByRole('checkbox', { name: /Linked supervisor evidence/ }).check();
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

  await page.reload();
  const reportCard = page.getByRole('article').filter({ hasText: 'East wing' });
  await expect(reportCard.getByRole('button', { name: 'Editing this report' })).toBeDisabled();
  await expect(page.getByLabel('Work completed')).toHaveValue('Set and inspected the formwork.');
  await expect(page.getByText('inspection.jpg', { exact: true })).toBeVisible();
  await page.getByLabel('Next-day plan').fill('Pour concrete after inspection.');
  await context.setOffline(true);
  try {
    await expect(page.getByText(/^Local draft active\./)).toBeVisible();
  } finally {
    await context.setOffline(false);
  }
  await page.reload();
  await expect(page.getByLabel('Next-day plan')).toHaveValue('Pour concrete after inspection.');
  await page.getByRole('button', { name: 'Submit report' }).click();
  await expect(page.getByText(/^Daily report .* submitted\.$/)).toBeVisible();
  const submitted = await getReports();
  expect(submitted.total).toBe(1);
  expect(submitted.items[0]).toMatchObject({
    id: original.id,
    status: 'submitted',
    next_day_plan: 'Pour concrete after inspection.'
  });
  expect(submitted.items[0].supervisor_update_ids).toHaveLength(1);
  const number = submitted.items[0].report_number;
  if (!number) throw new Error('The submitted report has no report number.');
  const evidencePath = `/api/v1/reports/${original.id}/supervisor-updates`;
  const evidence = await request.get(evidencePath, { headers });
  expect(evidence.ok()).toBe(true);
  const before = (await evidence.json())[0];
  expect(before).toMatchObject({ status: 'verified', verified_report_id: original.id });

  const reviewer = await browser.newPage();
  await signIn(reviewer, seed('seed', '--role', 'operation_manager'));
  const inbox = `/approvals?tab=reports&reportId=${original.id}`;
  await reviewer.goto(inbox);
  const submittedCard = reviewer.getByRole('article').filter({ hasText: number ?? '' });
  await submittedCard.getByText('Supervisor evidence', { exact: true }).click();
  await submittedCard.getByText(/Linked supervisor evidence/).click();
  await expect(submittedCard.getByText('Checked the formwork before handover.')).toBeVisible();
  await submittedCard
    .getByLabel('Approval or rejection comments')
    .fill('Clarify the inspection results.');
  await submittedCard.getByRole('button', { name: 'Reject', exact: true }).click();
  await expect(reviewer.getByText('Report rejected and returned to draft.')).toBeVisible();
  await page.reload();
  await reportCard.getByRole('button', { name: 'Resume report' }).click();
  await expect(page.getByText('Review feedback: Clarify the inspection results.')).toBeVisible();
  const retained = page.getByRole('checkbox', { name: /Linked supervisor evidence/ });
  await expect(retained).toBeChecked();
  await expect(retained).toBeDisabled();
  await page.getByLabel('Work completed').fill('Set the formwork and verified all bracing.');
  await page.getByRole('button', { name: 'Submit report' }).click();
  await expect(page.getByText(/^Daily report .* submitted\.$/)).toBeVisible();
  const resubmitted = await getReports();
  expect(resubmitted.total).toBe(1);
  expect(resubmitted.items[0]).toMatchObject({
    id: original.id,
    report_number: number,
    status: 'submitted',
    work_completed: 'Set the formwork and verified all bracing.',
    supervisor_update_ids: submitted.items[0].supervisor_update_ids
  });
  const retainedResponse = await request.get(evidencePath, { headers });
  expect((await retainedResponse.json())[0]).toMatchObject({
    verified_at: before.verified_at,
    verified_report_id: original.id
  });
  await reviewer.goto(inbox);
  await submittedCard.getByRole('checkbox', { name: /Target covered confirmation/ }).check();
  await submittedCard.getByRole('button', { name: 'Approve', exact: true }).click();
  await expect(reviewer.getByText(`Approved ${number}.`, { exact: true })).toBeVisible();
  const approved = await getReports();
  expect(approved.items[0].status).toBe('approved');
  await page.reload();
  const approvedCard = page.getByRole('article').filter({
    has: page.getByText(number, { exact: true })
  });
  await expect(approvedCard).toHaveCount(1);
  const [download] = await Promise.all([
    page.waitForEvent('download'),
    approvedCard.getByRole('button', { name: 'Download PDF', exact: true }).click()
  ]);
  expect(download.suggestedFilename()).toBe(`${number}.pdf`);
  const pdf = readFileSync(await download.path());
  expect(pdf.subarray(0, 5).toString()).toBe('%PDF-');
  expect(pdf.subarray(-128).toString()).toContain('%%EOF');
  await reviewer.close();
});
