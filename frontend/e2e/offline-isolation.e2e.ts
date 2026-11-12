import { execFileSync } from 'node:child_process';
import { readFileSync } from 'node:fs';
import { env } from 'node:process';
import { fileURLToPath } from 'node:url';

import {
  expect,
  test,
  type APIRequestContext,
  type BrowserContext,
  type Page
} from '@playwright/test';

type TestAccount = { email: string; password: string; projectId: string };

const backend = fileURLToPath(new URL('../../backend/', import.meta.url));
const photo = readFileSync(
  new URL('../../backend/scripts/assets/blockwork_day5.jpg', import.meta.url)
);

function seed(role: 'seed' | 'seed-supervisor' = 'seed'): TestAccount {
  return JSON.parse(
    execFileSync(env.BROWSER_TEST_PYTHON ?? 'python', ['-m', 'tests.browser_fixtures', role], {
      cwd: backend,
      encoding: 'utf8'
    })
  );
}

async function signIn(page: Page, account: TestAccount): Promise<string> {
  await page.goto('/login');
  await page.getByLabel('Email', { exact: true }).fill(account.email);
  await page.getByLabel('Password', { exact: true }).fill(account.password);
  await page.getByRole('button', { name: 'Continue' }).click();
  const code = (await page.getByText(/^Development code:/).innerText()).match(/\d{6}/)?.[0];
  if (!code) throw new Error('The test API did not expose the verification code.');
  await page.getByLabel('Verification code').fill(code);
  const response = page.waitForResponse(
    (result) => result.url().endsWith('/auth/verify-otp') && result.ok()
  );
  await page.getByRole('button', { name: 'Verify and sign in' }).click();
  const { access_token }: { access_token: string } = await (await response).json();
  await expect(page).toHaveURL(/\/dashboard$/);
  return access_token;
}

async function signOut(page: Page, roleLabel = 'Admin') {
  await page.getByRole('button', { name: `Browser Test ${roleLabel}` }).click();
  page.once('dialog', async (dialog) => {
    expect(dialog.message()).toContain('Unsynced work will be lost.');
    await dialog.accept();
  });
  await page.getByRole('button', { name: 'Sign out', exact: true }).click();
  await expect(page).toHaveURL(/\/login$/);
}

async function fillReport(page: Page, projectId: string, text: string) {
  await page.getByRole('link', { name: 'Reports', exact: true }).click();
  await page.getByRole('combobox', { name: 'Project', exact: true }).selectOption(projectId);
  await page.getByLabel('Work area / location').fill('East wing');
  await page.getByLabel('Work completed').fill(text);
  await page.getByLabel('Next-day plan').fill('Pour concrete.');
  await page.getByLabel('Weather').fill('Sunny');
  await page.getByLabel('Site visitors').fill('None');
  await page.getByLabel('Subcontractors').fill('None');
  await page.getByLabel('WIR number').fill('Not required');
  await page.getByPlaceholder('Trade', { exact: true }).fill('Carpenter');
}

async function queueReport(
  page: Page,
  context: BrowserContext,
  projectId: string,
  text: string,
  filename: string
) {
  await fillReport(page, projectId, text);
  await page.evaluate(() => navigator.serviceWorker.ready.then(() => undefined));
  await context.setOffline(true);
  await page.getByLabel('Upload photos').setInputFiles({
    name: filename,
    mimeType: 'image/jpeg',
    buffer: photo
  });
  await expect(page.getByText('1 file queued for upload.')).toBeVisible();
}

async function getReports(request: APIRequestContext, token: string, projectId: string) {
  const response = await request.get('/api/v1/reports', {
    headers: { Authorization: `Bearer ${token}` },
    params: { project_id: projectId }
  });
  expect(response.ok()).toBe(true);
  return (await response.json()).items as {
    id: string;
    work_completed: string;
    revision: number;
  }[];
}

async function ownedRecordCount(page: Page, store: string): Promise<number> {
  return page.evaluate(
    async (name) =>
      new Promise<number>((resolve, reject) => {
        const open = indexedDB.open('garrisons-offline');
        open.onerror = () => reject(open.error);
        open.onsuccess = () => {
          const db = open.result;
          const tx = db.transaction(name, 'readonly');
          const count = tx.objectStore(name).count();
          tx.oncomplete = () => {
            db.close();
            resolve(count.result);
          };
          tx.onabort = () => {
            db.close();
            reject(tx.error);
          };
        };
      }),
    store
  );
}

test('sign-out clears only the departing account and invalidates another open tab', async ({
  page,
  context,
  request
}) => {
  const first = seed();
  const second = seed();
  await signIn(page, first);
  const otherTab = await context.newPage();
  await otherTab.goto('/reports/daily');
  await expect(otherTab.getByLabel('Work completed')).toBeVisible();

  await queueReport(page, context, first.projectId, 'First account offline draft', 'first.jpg');
  expect(await ownedRecordCount(page, 'ownedPhotoQueue')).toBe(1);
  expect(await ownedRecordCount(page, 'ownedReportDrafts')).toBe(1);
  await signOut(page);
  await expect(otherTab).toHaveURL(/\/login$/);
  expect(await ownedRecordCount(page, 'ownedPhotoQueue')).toBe(0);
  expect(await ownedRecordCount(page, 'ownedReportDrafts')).toBe(0);

  await context.setOffline(false);
  const token = await signIn(page, second);
  await page.getByRole('link', { name: 'Reports', exact: true }).click();
  await expect(page.getByLabel('Work completed')).toHaveValue('');
  await expect(page.getByText(/1 upload queued/)).toHaveCount(0);
  expect(await getReports(request, token, first.projectId)).toEqual([]);
});

test('a supervisor draft survives session expiry for its owner and legacy data stays quarantined', async ({
  page,
  context
}) => {
  const first = seed('seed-supervisor');
  const second = seed('seed-supervisor');
  await context.route('**/__offline_fixture', (route) =>
    route.fulfill({
      contentType: 'text/html',
      body: '<title>Offline migration fixture</title>'
    })
  );
  await page.goto('/__offline_fixture');
  await page.evaluate(
    () =>
      new Promise<void>((resolve, reject) => {
        localStorage.setItem(
          'garrisons.supervisor-update-draft',
          JSON.stringify({
            progress_notes: 'Unowned legacy update'
          })
        );
        const open = indexedDB.open('garrisons-offline', 1);
        open.onupgradeneeded = () => {
          open.result
            .createObjectStore('reportDrafts')
            .put({ payload: 'Unowned legacy report' }, 'daily-report');
          open.result.createObjectStore('photoQueue', { keyPath: 'id' }).put({ id: 'legacy-file' });
        };
        open.onsuccess = () => {
          open.result.close();
          resolve();
        };
        open.onerror = () => reject(open.error);
      })
  );

  await signIn(page, first);
  await page.getByRole('link', { name: 'Reports', exact: true }).click();
  await expect(page.getByLabel('Progress notes')).toHaveValue('');
  await page.getByLabel('Progress notes').fill('First supervisor local notes');
  await expect.poll(() => ownedRecordCount(page, 'ownedSupervisorDrafts')).toBe(1);
  await context.clearCookies({ name: 'refresh_token' });

  const nextTab = await context.newPage();
  await signIn(nextTab, second);
  await expect(page).toHaveURL(/\/login$/);
  await nextTab.getByRole('link', { name: 'Reports', exact: true }).click();
  await expect(nextTab.getByLabel('Progress notes')).toHaveValue('');
  await expect.poll(() => ownedRecordCount(nextTab, 'ownedSupervisorDrafts')).toBe(1);
  await signOut(nextTab, 'Civil Supervisor');
  await signIn(nextTab, first);
  await nextTab.getByRole('link', { name: 'Reports', exact: true }).click();
  await expect(nextTab.getByLabel('Progress notes')).toHaveValue('First supervisor local notes');
  expect(await ownedRecordCount(nextTab, 'reportDrafts')).toBe(1);
  expect(await ownedRecordCount(nextTab, 'photoQueue')).toBe(1);
});

test('standalone worker uploads only files owned by its verified account', async ({
  page,
  context,
  request,
  browserName
}) => {
  test.skip(browserName !== 'chromium', 'This check uses Chromium Background Sync dispatch.');
  const first = seed();
  const second = seed();
  await signIn(page, first);
  await queueReport(page, context, first.projectId, 'Retained offline report', 'retained.jpg');
  await context.clearCookies({ name: 'refresh_token' });
  await page.close();
  await context.setOffline(false);

  const nextTab = await context.newPage();
  const token = await signIn(nextTab, second);
  await queueReport(nextTab, context, first.projectId, 'Verified owner report', 'verified.jpg');

  // The about:blank page holds the CDP session without becoming an app window client.
  const observer = await context.newPage();
  const cdp = await context.newCDPSession(observer);
  const origin = new URL(nextTab.url()).origin;
  const registrationId = new Promise<string>((resolve) => {
    cdp.on('ServiceWorker.workerRegistrationUpdated', ({ registrations }) => {
      const registration = registrations.find(
        (entry) => entry.scopeURL === `${origin}/` && !entry.isDeleted
      );
      if (registration) resolve(registration.registrationId);
    });
  });
  await cdp.send('ServiceWorker.enable');
  const registration = await registrationId;
  await nextTab.close();
  await context.setOffline(false);
  await cdp.send('ServiceWorker.dispatchSyncEvent', {
    origin,
    registrationId: registration,
    tag: 'flush-photo-queue',
    lastChance: false
  });

  await expect
    .poll(async () => {
      const reports = await getReports(request, token, first.projectId);
      const photos: string[] = [];
      for (const report of reports) {
        const result = await request.get('/api/v1/photos', {
          headers: { Authorization: `Bearer ${token}` },
          params: { entity_type: 'daily_report', entity_id: report.id }
        });
        expect(result.ok()).toBe(true);
        for (const file of (await result.json()).items) photos.push(file.original_name);
      }
      return { reports: reports.map((report) => report.work_completed), photos };
    })
    .toEqual({ reports: ['Verified owner report'], photos: ['verified.jpg'] });
});

test('text-only drafts recover a lost create response and preserve concurrent local and server edits', async ({
  page,
  context,
  request
}) => {
  const account = seed();
  const token = await signIn(page, account);
  await fillReport(page, account.projectId, 'Original offline text');
  await context.setOffline(true);
  await page.getByRole('button', { name: 'Save draft', exact: true }).click();
  await expect(page.getByText('Daily report draft saved on this device.')).toBeVisible();
  expect(await getReports(request, token, account.projectId)).toEqual([]);

  let afterCreate!: () => void;
  let releaseResponse!: () => void;
  const committed = new Promise<void>((resolve) => {
    afterCreate = resolve;
  });
  const delayed = new Promise<void>((resolve) => {
    releaseResponse = resolve;
  });
  let firstCreate = true;
  await page.route('**/api/v1/reports', async (route) => {
    if (route.request().method() !== 'POST' || !firstCreate) {
      await route.continue();
      return;
    }
    firstCreate = false;
    const result = await route.fetch();
    expect(result.status()).toBe(201);
    afterCreate();
    await delayed;
    await route.abort();
  });

  await context.setOffline(false);
  await committed;
  await page.getByLabel('Work completed').fill('Edited while the first sync was in flight');
  await expect
    .poll(() =>
      page.evaluate(
        async () =>
          new Promise<string>((resolve, reject) => {
            const open = indexedDB.open('garrisons-offline');
            open.onerror = () => reject(open.error);
            open.onsuccess = () => {
              const db = open.result;
              const tx = db.transaction('ownedReportDrafts', 'readonly');
              const drafts = tx.objectStore('ownedReportDrafts').getAll();
              tx.oncomplete = () => {
                db.close();
                resolve(drafts.result[0]?.payload.work_completed);
              };
              tx.onabort = () => {
                db.close();
                reject(tx.error);
              };
            };
          })
      )
    )
    .toBe('Edited while the first sync was in flight');
  releaseResponse();
  await page.getByRole('button', { name: 'Retry sync' }).click();

  await expect
    .poll(async () => {
      const reports = await getReports(request, token, account.projectId);
      return reports.map(({ work_completed, revision }) => ({ work_completed, revision }));
    })
    .toEqual([{ work_completed: 'Edited while the first sync was in flight', revision: 2 }]);
  await page.reload();
  await expect(page.getByLabel('Work completed')).toHaveValue(
    'Edited while the first sync was in flight'
  );

  const [saved] = await getReports(request, token, account.projectId);
  await context.setOffline(true);
  await page.getByLabel('Work completed').fill('Stale device edit');
  await page.getByRole('button', { name: 'Save draft', exact: true }).click();
  await expect(page.getByText('Daily report draft saved on this device.')).toBeVisible();
  const endpoint = `/api/v1/reports/${saved.id}`;
  const headers = { Authorization: `Bearer ${token}` };
  const prior = await (await request.get(endpoint, { headers })).json();
  const changed = await request.put(endpoint, {
    headers,
    data: { ...prior, expected_revision: 2, work_completed: 'Current server edit' }
  });
  expect(changed.ok()).toBe(true);
  await context.setOffline(false);
  await expect(
    page.getByText(
      'The server report changed. Your local draft and queued uploads are still saved on this device.'
    )
  ).toBeVisible();
  await expect(page.getByLabel('Work completed')).toHaveValue('Stale device edit');
  expect(await getReports(request, token, account.projectId)).toEqual([
    expect.objectContaining({ id: saved.id, revision: 3, work_completed: 'Current server edit' })
  ]);
});

test('an invalid legacy queued file stays local with a removable reason', async ({
  page,
  context,
  request
}) => {
  const account = seed();
  const token = await signIn(page, account);
  await queueReport(page, context, account.projectId, 'Valid offline site report', 'valid.jpg');

  // Simulate a queue entry written before byte validation was introduced.
  await page.evaluate(
    () =>
      new Promise<void>((resolve, reject) => {
        const open = indexedDB.open('garrisons-offline');
        open.onerror = () => reject(open.error);
        open.onsuccess = () => {
          const db = open.result;
          const tx = db.transaction('ownedPhotoQueue', 'readwrite');
          const queue = tx.objectStore('ownedPhotoQueue');
          const files = queue.getAll();
          files.onsuccess = () =>
            queue.add({
              ...files.result[0],
              id: crypto.randomUUID(),
              file: new File(['not an image'], 'invalid.jpg', { type: 'image/jpeg' })
            });
          tx.oncomplete = () => {
            db.close();
            resolve();
          };
          tx.onabort = () => {
            db.close();
            reject(tx.error);
          };
        };
      })
  );

  await context.setOffline(false);
  const issues = page.getByRole('region', { name: 'Queued uploads needing attention' });
  await expect(issues).toContainText('invalid.jpg. Unsupported file type.');
  await expect.poll(() => ownedRecordCount(page, 'ownedPhotoQueue')).toBe(1);
  const [report] = await getReports(request, token, account.projectId);
  const photos = await request.get('/api/v1/photos', {
    headers: { Authorization: `Bearer ${token}` },
    params: { entity_type: 'daily_report', entity_id: report.id }
  });
  expect(photos.ok()).toBe(true);
  expect(
    (await photos.json()).items.map((item: { original_name: string }) => item.original_name)
  ).toEqual(['valid.jpg']);

  page.once('dialog', (dialog) => dialog.accept());
  await issues.getByRole('button', { name: 'Remove queued file invalid.jpg' }).click();
  await expect(issues).toHaveCount(0);
  expect(await ownedRecordCount(page, 'ownedPhotoQueue')).toBe(0);
});

test('a lost upload receipt is replayed before a newer local text edit', async ({
  page,
  context,
  request
}) => {
  const account = seed();
  const token = await signIn(page, account);
  await queueReport(page, context, account.projectId, 'Original report text', 'receipt.jpg');

  let afterUpload!: () => void;
  let releaseResponse!: () => void;
  const committed = new Promise<void>((resolve) => {
    afterUpload = resolve;
  });
  const delayed = new Promise<void>((resolve) => {
    releaseResponse = resolve;
  });
  let originalKey: string | undefined;
  let attempts = 0;
  await page.route('**/api/v1/photos/upload', async (route) => {
    attempts += 1;
    const key = route.request().headers()['idempotency-key'];
    const response = await route.fetch();
    expect(response.ok()).toBe(true);
    expect(response.headers()['x-report-revision']).toBe('2');
    if (attempts === 1) {
      originalKey = key;
      afterUpload();
      await delayed;
      await route.abort();
    } else {
      expect(key).toBe(originalKey);
      await route.fulfill({ response });
    }
  });

  await context.setOffline(false);
  await committed;
  await page.getByLabel('Work completed').fill('Edited while waiting for the upload receipt');
  await expect
    .poll(() =>
      page.evaluate(
        async () =>
          new Promise<string>((resolve, reject) => {
            const open = indexedDB.open('garrisons-offline');
            open.onerror = () => reject(open.error);
            open.onsuccess = () => {
              const db = open.result;
              const tx = db.transaction('ownedReportDrafts', 'readonly');
              const drafts = tx.objectStore('ownedReportDrafts').getAll();
              tx.oncomplete = () => {
                db.close();
                resolve(drafts.result[0]?.payload.work_completed);
              };
              tx.onabort = () => {
                db.close();
                reject(tx.error);
              };
            };
          })
      )
    )
    .toBe('Edited while waiting for the upload receipt');
  releaseResponse();

  await expect
    .poll(async () => {
      const reports = await getReports(request, token, account.projectId);
      return reports.map(({ work_completed, revision }) => ({ work_completed, revision }));
    })
    .toEqual([{ work_completed: 'Edited while waiting for the upload receipt', revision: 3 }]);
  expect(attempts).toBe(2);
  const [report] = await getReports(request, token, account.projectId);
  const photos = await request.get('/api/v1/photos', {
    headers: { Authorization: `Bearer ${token}` },
    params: { entity_type: 'daily_report', entity_id: report.id }
  });
  expect(photos.ok()).toBe(true);
  expect(
    (await photos.json()).items.map((item: { original_name: string }) => item.original_name)
  ).toEqual(['receipt.jpg']);
  expect(await ownedRecordCount(page, 'ownedPhotoQueue')).toBe(0);
});
