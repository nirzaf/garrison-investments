import { execFileSync } from 'node:child_process';
import { env } from 'node:process';
import { fileURLToPath } from 'node:url';

import { expect, test, type Page } from '@playwright/test';

const BACKEND_DIR = fileURLToPath(new URL('../../backend/', import.meta.url));
const PYTHON_BIN = env.BROWSER_TEST_PYTHON ?? 'python';

type SeededAccount = { email: string; password: string; projectId: string; projectCode: string };

function seedProjectAccounts(...roles: string[]): SeededAccount[] {
  const args = ['-m', 'tests.browser_fixtures', 'seed-group'];
  for (const role of roles) args.push('--role', role);
  return JSON.parse(
    execFileSync(PYTHON_BIN, args, { cwd: BACKEND_DIR, encoding: 'utf8' })
  ) as SeededAccount[];
}

async function signIn(page: Page, account: Pick<SeededAccount, 'email' | 'password'>) {
  await page.goto('/login');
  await page.getByLabel('Email', { exact: true }).fill(account.email);
  await page.getByLabel('Password', { exact: true }).fill(account.password);
  await page.getByRole('button', { name: 'Continue' }).click();
  const code = (await page.getByText(/^Development code:/).innerText()).match(/\d{6}/)?.[0];
  if (!code) throw new Error('The test API did not expose the verification code.');
  await page.getByLabel('Verification code').fill(code);
  const verified = page.waitForResponse((response) =>
    new URL(response.url()).pathname === '/api/v1/auth/verify-otp' &&
    response.request().method() === 'POST'
  );
  await page.getByRole('button', { name: 'Verify and sign in' }).click();
  const response = await verified;
  expect(response.status()).toBe(200);
  const body = await response.json() as { access_token: string };
  await expect(page).not.toHaveURL(/\/login$/);
  return { Authorization: `Bearer ${body.access_token}` };
}

test('correction asset selector shows eligible assets and revalidates after custody changes', async ({
  browser, page, request
}) => {
  const [director, supervisor, engineer] = seedProjectAccounts(
    'managing_director', 'site_supervisor', 'mep_project_manager'
  );
  const directorPage = await browser.newPage();
  const engineerPage = await browser.newPage();
  try {
    const directorHeaders = await signIn(directorPage, director);
    const locationResponse = await request.post('/api/v1/inventory/locations', {
      headers: directorHeaders,
      data: {
        name: 'Site stockroom', code: `ST-${director.projectCode}`,
        location_type: 'project_site', project_id: director.projectId
      }
    });
    expect(locationResponse.status()).toBe(201);
    const location = await locationResponse.json();

    const supervisorHeaders = await signIn(page, supervisor);
    await page.goto('/materials');
    await page.getByRole('button', { name: 'Register received items' }).click();
    await page.getByLabel('Registration project').selectOption(supervisor.projectId);
    await page.getByLabel('Receipt location').selectOption(location.id);
    await page.getByLabel('Item name', { exact: true }).fill(`Browser receipt ${director.projectCode}`);
    await page.getByLabel('Item description').fill('Counted equipment at the site stockroom');
    await page.getByLabel('Category').selectOption('equipment');
    await page.getByLabel('Received quantity').fill('3');
    await page.getByLabel('Date received').fill('2026-10-01');
    await page.getByRole('button', { name: 'Save registration draft' }).click();
    const record = page.locator('summary').filter({ hasText: `Browser receipt ${director.projectCode}` });
    await record.click();
    const submit = page.getByRole('button', { name: 'Submit registration' });
    await expect(submit).toBeDisabled();
    const jpg = execFileSync(PYTHON_BIN,
      ['-c', 'import sys; from tests.test_photos import jpeg_bytes; sys.stdout.buffer.write(jpeg_bytes())'],
      { cwd: BACKEND_DIR }
    );
    await page.getByLabel('Item photographs').setInputFiles({
      name: 'receipt.jpg', mimeType: 'image/jpeg', buffer: jpg
    });
    await submit.click();
    await expect(record).toContainText('pending engineer');

    const engineerHeaders = await signIn(engineerPage, engineer);
    await engineerPage.goto('/materials');
    await engineerPage.locator('summary')
      .filter({ hasText: `Browser receipt ${director.projectCode}` }).click();
    await engineerPage.getByRole('button', { name: 'Confirm receipt', exact: true }).click();
    await expect(engineerPage.locator('summary')
      .filter({ hasText: `Browser receipt ${director.projectCode}` })).toContainText('approved');

    await page.reload();
    await page.locator('summary').filter({ hasText: `Browser receipt ${director.projectCode}` }).click();
    await page.getByRole('button', { name: 'Correct registration', exact: true }).click();
    await page.getByLabel('Received quantity').fill('2');
    await page.getByLabel('Correction reason').fill('Correct the serialized stock count.');
    const assetResponse = page.waitForResponse((response) =>
      response.url().includes('/correction-assets') && response.url().includes('search=REG-')
    );
    await page.getByLabel('Search asset tags').fill('REG-');
    const options = (await (await assetResponse).json()).items;
    expect(options).toHaveLength(3);
    const selected = options[0] as {
      id: string; item_id: string; asset_tag: string; condition: string; location_name: string
    };
    const checkbox = page.getByRole('checkbox', { name: new RegExp(selected.asset_tag) });
    await checkbox.check();
    await expect(checkbox).toBeChecked();
    await expect(page.getByText(
      `${selected.asset_tag} · ${selected.condition} · ${selected.location_name}`, { exact: true }
    )).toBeVisible();

    const saved = page.waitForResponse((response) =>
      response.url().endsWith('/correction') && response.request().method() === 'POST'
    );
    await page.getByRole('button', { name: 'Save registration draft', exact: true }).click();
    const savedResponse = await saved;
    expect(savedResponse.status(), await savedResponse.text()).toBe(201);
    const correction = await savedResponse.json();
    expect(savedResponse.request().postDataJSON().remove_asset_ids).toEqual([selected.id]);

    const targetResponse = await request.post('/api/v1/inventory/locations', {
      headers: directorHeaders,
      data: {
        name: 'Destination', code: `DEST-${director.projectCode}`,
        location_type: 'project_site', project_id: director.projectId
      }
    });
    expect(targetResponse.status()).toBe(201);
    const target = await targetResponse.json();
    const transfer = await request.post('/api/v1/inventory/movements', {
      headers: directorHeaders,
      data: {
        item_id: selected.item_id, asset_id: selected.id, movement_type: 'transfer', quantity: '1',
        from_location_id: location.id, to_location_id: target.id, project_id: director.projectId
      }
    });
    expect(transfer.status()).toBe(201);
    const uploaded = await request.post('/api/v1/photos/upload', {
      headers: supervisorHeaders,
      multipart: {
        entity_type: 'inventory_registration', entity_id: correction.id,
        files: { name: 'count.jpg', mimeType: 'image/jpeg', buffer: jpg }
      }
    });
    expect(uploaded.status()).toBe(201);
    const submitted = await request.post(`/api/v1/inventory/registrations/${correction.id}/submit`, {
      headers: supervisorHeaders,
      data: { expected_submission_revision: correction.submission_revision }
    });
    expect(submitted.status()).toBe(200);
    const decision = await request.post(`/api/v1/inventory/registrations/${correction.id}/decision`, {
      headers: engineerHeaders,
      data: { decision: 'approved', expected_submission_revision: correction.submission_revision }
    });
    expect(decision.status(), await decision.text()).toBe(409);
  } finally {
    await directorPage.close();
    await engineerPage.close();
  }
});
