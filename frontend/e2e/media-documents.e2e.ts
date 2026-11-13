import { execFileSync } from 'node:child_process';
import { randomUUID } from 'node:crypto';
import { readFileSync } from 'node:fs';
import { env } from 'node:process';
import { fileURLToPath } from 'node:url';

import { expect, test, type Page, type Route } from '@playwright/test';

type TestAccount = { email: string; password: string; projectId: string };
type SignedDocument = { url: string; expires_in_seconds: number; superseded_warning: boolean };
const backendDirectory = fileURLToPath(new URL('../../backend/', import.meta.url));
const jpeg = readFileSync(
  new URL('../../backend/scripts/assets/blockwork_day5.jpg', import.meta.url)
);
const pdfFile = (name: string) => ({
  name,
  mimeType: 'application/pdf',
  buffer: Buffer.from(`%PDF-1.4\n1 0 obj<<>>endobj\n% ${name}\n%%EOF`)
});

async function signIn(page: Page, ...seedArgs: string[]) {
  const args = seedArgs.length ? seedArgs : ['seed'];
  const account: TestAccount = JSON.parse(
    execFileSync(env.BROWSER_TEST_PYTHON ?? 'python', ['-m', 'tests.browser_fixtures', ...args], {
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
  browser,
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
  const approve = async (version: number) => {
    const completed = page.waitForResponse((response) => {
      const path = new URL(response.url()).pathname;
      return response.request().method() === 'POST' &&
        path.startsWith(`/api/v1/documents/${document.id}/versions/`) && path.endsWith('/approve');
    });
    await card.getByRole('button', { name: `Approve v${version}`, exact: true }).click();
    const response = await completed;
    expect(response.status()).toBe(200);
    expect(await response.json()).toMatchObject({ active_version: version });
  };
  await approve(1);
  await expect(card.getByText(/Active v1/)).toBeVisible();

  await card.getByRole('button', { name: 'Upload replacement' }).click();
  await card.getByLabel(/Replacement file/).setInputFiles(pdfFile('v2.pdf'));
  await card.getByRole('button', { name: 'Upload for approval' }).click();
  await expect(card.getByRole('button', { name: 'Approve v2', exact: true })).toBeVisible();
  await expect(card.getByText(/Active v1/)).toBeVisible();

  const active = await request.get(`/api/v1/documents/${document.id}/download`, { headers });
  expect(active.ok()).toBe(true);
  const pendingLink: SignedDocument = await active.json();
  expect(pendingLink.superseded_warning).toBe(false);
  // The separate expiry rehearsal backdates the first link per fixture object.
  if (env.BROWSER_TEST_VERIFY_SIGNED_EXPIRY !== '1') {
    const activeFile = await request.get(pendingLink.url);
    expect(activeFile.ok()).toBe(true);
    expect(await activeFile.body()).toEqual(pdfFile('v1.pdf').buffer);
  }

  // Approval returns the committed version. Keep the list refresh in flight so
  // the active card and toast have to use that response.
  let releaseRefresh!: () => void;
  const refreshBlocked = new Promise<void>((resolve) => { releaseRefresh = resolve; });
  const delayRefresh = async (route: Route) => {
    await refreshBlocked;
    await route.fallback();
  };
  await page.route('**/api/v1/documents?*', delayRefresh);
  try {
    await approve(2);
    await expect(page.getByText('Document version approved.')).toBeVisible();
    await expect(card.getByText(/Active v2/)).toBeVisible();
  } finally {
    releaseRefresh();
  }
  await page.unroute('**/api/v1/documents?*', delayRefresh);
  await page.reload();
  await expect(card.getByText(/Active v2/)).toBeVisible();
  await expect(card.getByText('superseded', { exact: true })).toBeVisible();

  await page.goto(`/documents?documentId=${document.id}`);
  await typeFilter.fill('wir');
  await expect(card.getByText('Linked document outside the current results')).toBeVisible();
  await expect(uploadType).toHaveValue('wir');

  const downloadPath = `/api/v1/documents/${document.id}/download`;
  const versions = await (await request.get(`/api/v1/documents/${document.id}/versions`, { headers })).json();
  const version = versions.find((item: { version: number }) => item.version === 2);
  expect(version).toBeDefined();
  const waitForLink = () => page.waitForResponse(
    (response) => new URL(response.url()).pathname === downloadPath && response.ok()
  );
  const initial = waitForLink();
  await card.getByRole('button', { name: 'View', exact: true }).click();
  const initialResponse = await initial;
  expect(initialResponse.headers()['cache-control']).toBe('no-store');
  expect(new URL(initialResponse.url()).searchParams.get('version_id')).toBe(version.id);
  const first: SignedDocument = await initialResponse.json();
  const dialog = page.getByRole('dialog', { name: title });
  const preview = dialog.locator('iframe');
  await expect(preview).toHaveAttribute('src', first.url);
  const storage = env.BROWSER_TEST_MINIO_ENDPOINT ?? '127.0.0.1:9000';
  expect(new URL(first.url).host).toBe(storage);
  expect(first.expires_in_seconds).toBe(300);
  if (env.BROWSER_TEST_VERIFY_SIGNED_EXPIRY === '1') {
    const stale = await request.get(first.url);
    expect(stale.status()).toBe(403);
    expect(await stale.text()).toMatch(/expired/i);
  }

  const refresh = dialog.getByRole('button', { name: 'Refresh preview', exact: true });
  await expect(refresh).toBeVisible();
  await page.route(`**${downloadPath}?*`, (route) => route.fulfill({
    status: 404,
    json: { detail: 'Document version not found' }
  }), { times: 1 });
  await refresh.click();
  await expect(dialog.getByRole('alert')).toHaveText('Document version not found');
  await expect(preview).toHaveCount(0);

  const refreshed = waitForLink();
  await refresh.click();
  const response = await refreshed;
  const second: SignedDocument = await response.json();
  expect(new URL(response.url()).searchParams.get('version_id')).toBe(version.id);
  expect(new URL(second.url).host).toBe(storage);
  if (env.BROWSER_TEST_VERIFY_SIGNED_EXPIRY === '1') expect(second.url === first.url).toBe(false);
  await expect(preview).toHaveAttribute('src', second.url);
  const file = await request.get(second.url);
  expect(file.status()).toBe(200);
  expect(await file.body()).toEqual(pdfFile('v2.pdf').buffer);
  await dialog.getByRole('button', { name: 'Close preview' }).click();

  const oldVersion = versions.find((item: { version: number }) => item.version === 1);
  const oldResponse = await request.get(downloadPath, { headers, params: { version_id: oldVersion.id } });
  expect(oldResponse.ok()).toBe(true);
  const oldLink: SignedDocument = await oldResponse.json();
  expect(oldLink.superseded_warning).toBe(true);
  const oldFile = await request.get(oldLink.url);
  expect(oldFile.ok()).toBe(true);
  expect(await oldFile.body()).toEqual(pdfFile('v1.pdf').buffer);

  const other = await browser.newPage();
  const { headers: unrelated } = await signIn(other, 'seed', '--role', 'project_manager');
  await other.goto(`/documents?documentId=${document.id}`);
  await expect(other.getByRole('alert')).toContainText('Document not found');
  await expect(other.getByRole('heading', { name: title, exact: true })).toHaveCount(0);
  expect((await request.get(downloadPath, { headers: unrelated })).status()).toBe(404);
  await other.close();
});

test('a document reader combines filters, navigates pages and clears the result count', async ({
  browser,
  page
}) => {
  const admin = await browser.newPage();
  const { account, headers } = await signIn(admin);
  const second = await signIn(page, 'seed', '--role', 'accounts');
  const marker = `Library${randomUUID().replace(/-/g, '')}`;
  const titles = Array.from({ length: 26 }, (_, index) => `${marker} structural plan ${index}`);
  const fixtures = [
    ...titles.map((title) => ({ title, project_id: account.projectId, document_type: 'drawing' })),
    { title: `${marker} inspection plan`, project_id: account.projectId, document_type: 'wir' },
    { title: `${marker} electrical plan`, project_id: account.projectId, document_type: 'drawing' },
    { title: `${marker} structural remote`, project_id: second.account.projectId, document_type: 'drawing' }
  ];
  for (let offset = 0; offset < fixtures.length; offset += 5) {
    await Promise.all(fixtures.slice(offset, offset + 5).map(async (row) => {
      const response = await admin.request.post('/api/v1/documents', {
        headers,
        multipart: { ...row, file: pdfFile('library-fixture.pdf') }
      });
      expect(response.status()).toBe(201);
    }));
  }
  await admin.close();
  await page.goto('/documents');

  const project = page.getByRole('combobox', { name: 'Filter documents by project' });
  const projectSearch = page.getByRole('textbox', { name: 'Find projects by name or code' });
  const type = page.getByRole('combobox', { name: 'Filter documents by type' });
  const search = page.getByRole('textbox', { name: 'Search documents' });
  const pagination = page.getByRole('navigation', { name: 'Document pages' });
  const resultCount = page.getByRole('status').filter({ hasText: /matching document/ });
  const cards = page.getByRole('article');
  const titlesOnPage = () => cards.getByRole('heading', { level: 3 }).allTextContents();

  const projectResponse = await page.request.get(`/api/v1/projects/${account.projectId}`, {
    headers: second.headers
  });
  expect(projectResponse.ok()).toBe(true);
  const { code } = await projectResponse.json();
  await projectSearch.fill(code);
  await project.selectOption(account.projectId);
  await type.fill('DRAWING');
  await search.fill(`  ${marker.toUpperCase()} STRUCTURAL  `);
  await expect(resultCount).toHaveText('26 matching documents');
  await expect(pagination.getByText('Page 1 of 2')).toBeVisible();
  await expect(cards).toHaveCount(25);
  const first = await titlesOnPage();

  await pagination.getByRole('button', { name: 'Next' }).click();
  await expect(pagination.getByText('Page 2 of 2')).toBeVisible();
  await expect(cards).toHaveCount(1);
  await expect(pagination.getByRole('button', { name: 'Next' })).toBeDisabled();
  const secondPage = await titlesOnPage();
  expect([...first, ...secondPage].sort()).toEqual([...titles].sort());
  await pagination.getByRole('button', { name: 'Previous' }).click();
  await expect(cards).toHaveCount(25);
  expect(await titlesOnPage()).toEqual(first);

  await type.fill('WIR');
  await expect(resultCount).toHaveText('0 matching documents');
  await expect(page.getByText('No documents found')).toBeVisible();
  await search.fill(`${marker} INSPECTION`);
  await expect(resultCount).toHaveText('1 matching document');
  await expect(cards.getByRole('heading', { name: `${marker} inspection plan` })).toBeVisible();

  const unfiltered = page.waitForResponse((response) => {
    const url = new URL(response.url());
    return url.pathname === '/api/v1/documents' &&
      !['document_type', 'project_id', 'search'].some((key) => url.searchParams.has(key)) &&
      url.searchParams.get('offset') === '0' && response.ok();
  });
  await page.getByRole('button', { name: 'Clear filters' }).click();
  const { total } = await (await unfiltered).json();
  await expect(resultCount).toHaveText(`${total} matching documents`);
  await expect(project).toHaveValue('');
  await expect(projectSearch).toHaveValue('');
  await expect(type).toHaveValue('');
  await expect(search).toHaveValue('');
  await expect(pagination.getByText(`Page 1 of ${Math.ceil(total / 25)}`)).toBeVisible();
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
