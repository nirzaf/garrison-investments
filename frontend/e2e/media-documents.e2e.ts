import { execFileSync } from 'node:child_process';
import { readFileSync } from 'node:fs';
import { env } from 'node:process';
import { fileURLToPath } from 'node:url';

import { expect, test, type Page } from '@playwright/test';

type TestAccount = { email: string; password: string; projectId: string };
const backendDirectory = fileURLToPath(new URL('../../backend/', import.meta.url));
const jpeg = readFileSync(
  new URL('../../backend/scripts/assets/blockwork_day5.jpg', import.meta.url)
);
const pdfFile = (name: string) => ({
  name,
  mimeType: 'application/pdf',
  buffer: Buffer.from(`%PDF-1.4\n1 0 obj<<>>endobj\n% ${name}\n%%EOF`)
});

async function signIn(page: Page, seedCommand = 'seed') {
  const account: TestAccount = JSON.parse(
    execFileSync(env.BROWSER_TEST_PYTHON ?? 'python', ['-m', 'tests.browser_fixtures', seedCommand], {
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

test('document type filtering and replacement preserve the active version', async ({
  page,
  request
}) => {
  const { account, headers } = await signIn(page);
  await page.getByRole('link', { name: 'Documents', exact: true }).click();
  const typeFilter = page.getByRole('combobox', { name: 'Filter documents by type' });
  const uploadType = page.getByLabel('Upload document type');
  await typeFilter.fill('DRAWING');
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

test('supervisor selects supported photo formats and retrieves the original HEIC', async ({
  page,
  request
}) => {
  const { account, headers } = await signIn(page, 'seed-supervisor');
  await page.getByRole('link', { name: 'Reports', exact: true }).click();
  await page.getByRole('combobox', { name: 'Project', exact: true }).selectOption(account.projectId);
  await page.getByLabel('Work location').fill('Photo format verification');
  await page.getByLabel('Progress notes').fill('Verify uploaded site evidence.');
  await page.getByLabel('Required notes').fill('Retain the original HEIC file.');
  await page.getByRole('button', { name: 'Save draft' }).click();
  await expect(page.getByText('Draft saved.', { exact: true })).toBeVisible();

  const input = page.locator('input[type="file"][capture="environment"]');
  const limit = 10 * 1024 * 1024;
  const fixture = readFileSync(new URL('./fixtures/site.heic', import.meta.url));
  const original = Buffer.alloc(limit);
  fixture.copy(original);
  // A free-space ISO BMFF box pads the valid image to the exact upload limit.
  original.writeUInt32BE(limit - fixture.length, fixture.length);
  original.write('free', fixture.length + 4, 'ascii');
  const oversized = Buffer.concat([original, Buffer.alloc(1)]);
  await input.setInputFiles({ name: 'oversized.heic', mimeType: 'image/heic', buffer: oversized });
  await expect(page.getByRole('alert')).toContainText('File exceeds the 10 MiB limit.');

  const png = readFileSync(new URL('../public/brand/icon-32.png', import.meta.url));
  const accepted = [
    { name: 'site.jpeg', mimeType: 'image/jpeg', buffer: jpeg },
    { name: 'site.png', mimeType: 'image/png', buffer: png },
    { name: 'site.heic', mimeType: 'image/heic', buffer: original }
  ];
  await input.setInputFiles(accepted);
  await expect(page.getByText('3 files saved.', { exact: true })).toBeVisible();

  await page.reload();
  await page.getByRole('article').filter({ hasText: 'Photo format verification' })
    .getByRole('button', { name: 'Resume draft' }).click();
  const card = (name: string) => page.getByRole('listitem').filter({ hasText: name });
  for (const name of ['site.jpeg', 'site.png']) {
    await expect(card(name).getByRole('button', { name: 'Preview', exact: true })).toBeVisible();
  }
  const heic = card('site.heic');
  await expect(heic.getByText('Original only', { exact: true })).toBeVisible();
  await expect(heic.getByRole('button', { name: 'Preview' })).toHaveCount(0);
  await expect(card('oversized.heic')).toHaveCount(0);

  const linkResponse = page.waitForResponse(
    (response) => /\/api\/v1\/photos\/[^/]+\/download$/.test(new URL(response.url()).pathname)
  );
  await heic.getByRole('button', { name: 'Download original' }).click();
  const link = await linkResponse;
  expect(link.status()).toBe(200);
  const { url }: { url: string } = await link.json();
  expect(['127.0.0.1', 'localhost']).toContain(new URL(url).hostname);
  const bytes = await request.get(url);
  expect(bytes.status()).toBe(200);
  expect(await bytes.body()).toEqual(original);

  const photoUrl = new URL(link.url()).pathname.replace(/\/download$/, '');
  const unauthorized = await request.get(`${photoUrl}/download`);
  expect(unauthorized.status()).toBe(401);
  const record = await request.get(photoUrl, { headers });
  expect(record.status()).toBe(200);
  const { entity_id } = await record.json();
  const rejected = await request.post('/api/v1/photos/upload', {
    headers,
    multipart: {
      entity_type: 'supervisor_update',
      entity_id,
      kind: 'photo',
      files: { name: 'oversized.heic', mimeType: 'image/heic', buffer: oversized }
    }
  });
  expect(rejected.status()).toBe(413);
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
      entity_type: 'daily_report',
      entity_id: reportId,
      kind: 'photo',
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
