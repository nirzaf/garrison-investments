import { execFileSync } from 'node:child_process';
import { readFileSync } from 'node:fs';
import { env } from 'node:process';
import { fileURLToPath } from 'node:url';

import { expect, test, type Page } from '@playwright/test';

type TestAccount = { email: string; password: string; projectId: string };
const backendDirectory = fileURLToPath(new URL('../../backend/', import.meta.url));
const jpeg = readFileSync(new URL('../../backend/scripts/assets/blockwork_day5.jpg', import.meta.url));
const pdfFile = (name: string) => ({
  name,
  mimeType: 'application/pdf',
  buffer: Buffer.from(`%PDF-1.4\n1 0 obj<<>>endobj\n% ${name}\n%%EOF`)
});

async function signIn(page: Page) {
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
  await expect(page.getByRole('link', { name: 'Documents', exact: true })).toBeVisible();
  return { account, headers: { Authorization: `Bearer ${access_token}` } };
}

test('document type filtering and replacement preserve the active version', async ({ page, request }) => {
  const { account, headers } = await signIn(page);
  await page.getByRole('link', { name: 'Documents', exact: true }).click();
  const typeFilter = page.getByRole('combobox', { name: 'Filter documents by type' });
  const uploadType = page.getByLabel('Upload document type');
  await typeFilter.fill('drawing');
  await expect(uploadType).toHaveValue('wir');
  await uploadType.selectOption('drawing');
  const title = `Versioned plan ${account.projectId.slice(0, 8)}`;
  await page.getByLabel('Document title').fill(title);
  await page.getByLabel('Upload document project').selectOption(account.projectId);
  await page.getByLabel('Document file', { exact: true }).setInputFiles(pdfFile('v1.pdf'));
  const created = page.waitForResponse(
    (response) => response.url().endsWith('/api/v1/documents') && response.status() === 201
  );
  await page.getByRole('button', { name: 'Upload', exact: true }).click();
  const document = await (await created).json();
  const card = page.getByRole('article').filter({ hasText: title });
  await card.getByRole('button', { name: 'Approve v1', exact: true }).click();
  await expect(card.getByText(/Active v1/)).toBeVisible();

  await card.getByRole('button', { name: 'Upload replacement' }).click();
  await card.getByLabel(/Replacement file/).setInputFiles(pdfFile('v2.pdf'));
  await card.getByRole('button', { name: 'Upload for approval' }).click();
  await expect(card.getByRole('button', { name: 'Approve v2', exact: true })).toBeVisible();
  await expect(card.getByText(/Active v1/)).toBeVisible();

  const active = await request.get(`/api/v1/documents/${document.id}/download`, { headers });
  expect(active.ok()).toBe(true);
  expect((await active.json()).superseded_warning).toBe(false);

  await card.getByRole('button', { name: 'Approve v2', exact: true }).click();
  await expect(card.getByText(/Active v2/)).toBeVisible();
  await page.reload();
  await expect(card.getByText(/Active v2/)).toBeVisible();
  await expect(card.getByText('superseded', { exact: true })).toBeVisible();

  await page.goto(`/documents?documentId=${document.id}`);
  await typeFilter.fill('wir');
  await expect(card.getByText('Linked document outside the current results')).toBeVisible();
  await expect(uploadType).toHaveValue('wir');
});

test('media removal and recovery persist after reload', async ({ page, request }) => {
  const { account, headers } = await signIn(page);
  const report = await request.post('/api/v1/reports', {
    headers,
    data: {
      project_id: account.projectId,
      report_date: new Intl.DateTimeFormat('en-CA', { timeZone: 'Asia/Qatar' }).format(new Date()),
      work_location: 'Test site',
      manpower_total: 1,
      work_completed: 'Test report evidence.',
      next_day_plan: 'Inspect evidence.',
      progress_percentage: '0',
      wir_status: 'pending',
      inspection_status: 'pending'
    }
  });
  expect(report.status()).toBe(201);
  const reportId = (await report.json()).id;
  const originalName = `evidence-${account.projectId.slice(0, 8)}.jpg`;
  const upload = await request.post('/api/v1/photos/upload', {
    headers,
    multipart: {
      entity_type: 'daily_report', entity_id: reportId, kind: 'photo',
      files: { name: originalName, mimeType: 'image/jpeg', buffer: jpeg }
    }
  });
  expect(upload.status()).toBe(201);
  const [photo] = await upload.json();

  await page.goto('/photos');
  const item = page.getByRole('article').filter({ hasText: originalName });
  await item.getByRole('button', { name: 'Remove', exact: true }).click();
  const dialog = page.getByRole('dialog');
  await expect(dialog).toContainText(reportId);
  await dialog.getByRole('button', { name: 'Remove file' }).click();
  await expect(item).toHaveCount(0);
  const deleted = await request.get(`/api/v1/photos/${photo.id}/download`, { headers });
  expect(deleted.status()).toBe(404);

  await page.getByRole('checkbox', { name: 'Show deleted files' }).check();
  await item.getByRole('button', { name: 'Recover', exact: true }).click();
  await dialog.getByRole('button', { name: 'Recover file' }).click();
  await expect(item).toHaveCount(0);
  await page.reload();
  await expect(item).toBeVisible();
  await expect(item.getByRole('button', { name: 'Preview' })).toBeVisible();
});
