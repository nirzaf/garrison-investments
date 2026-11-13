import { execFileSync } from 'node:child_process';
import { randomUUID } from 'node:crypto';
import { readFileSync } from 'node:fs';
import { env } from 'node:process';
import { fileURLToPath } from 'node:url';

import { expect, test } from '@playwright/test';

const backendDirectory = fileURLToPath(new URL('../../backend/', import.meta.url));

test.use({ trace: 'off' });

test('launch imports reconcile linked records and retry opening stock without duplication', async ({
  page,
  request
}) => {
  const { email, password } = JSON.parse(
    execFileSync(env.BROWSER_TEST_PYTHON ?? 'python', ['-m', 'tests.browser_fixtures', 'seed'], {
      cwd: backendDirectory,
      encoding: 'utf8'
    })
  ) as { email: string; password: string };
  await page.goto('/login');
  await page.getByLabel('Email', { exact: true }).fill(email);
  await page.getByLabel('Password', { exact: true }).fill(password);
  await page.getByRole('button', { name: 'Continue' }).click();
  const code = (await page.getByText(/^Development code:/).innerText()).match(/\d{6}/)?.[0];
  if (!code) throw new Error('Test code unavailable.');
  await page.getByLabel('Verification code').fill(code);
  const verified = page.waitForResponse(
    (response) => response.url().endsWith('/auth/verify-otp') && response.ok()
  );
  await page.getByRole('button', { name: 'Verify and sign in' }).click();
  const { access_token } = await (await verified).json();
  const headers = { Authorization: `Bearer ${access_token}` };
  const marker = randomUUID().slice(0, 8);
  const itemCode = `ITEM-${marker}`;
  const locationCode = `LOC-${marker}`;
  const projectCode = `PRJ-${marker}`;
  const supplierName = `Import supplier ${marker}`;
  const userEmail = `import-${marker}@example.com`;
  const documentTitle = `Import drawing ${marker}`;

  await page.goto('/admin/imports');
  const template = page.getByLabel('Import template');
  const file = page.getByLabel('Import file');
  const preview = page.getByRole('button', { name: 'Preview', exact: true });
  const run = page.getByRole('button', { name: 'Run import', exact: true });
  const get = async (path: string, params?: Record<string, string>) => {
    const response = await request.get(`/api/v1${path}`, { headers, params });
    expect(response.ok(), `${path} returned HTTP ${response.status()}`).toBe(true);
    return response.json();
  };
  const selectCsv = async (type: string, rows: string[]) => {
    const source = readFileSync(
      new URL(`../../docs/import_templates/${type}.csv`, import.meta.url), 'utf8'
    );
    const [columns] = source.split(/\r?\n/);
    await template.selectOption(type);
    await file.setInputFiles({
      name: `${type}-${marker}.csv`,
      mimeType: 'text/csv',
      buffer: Buffer.from([columns, ...rows, ''].join('\n'))
    });
    await preview.click();
  };
  const importRows = async (type: string, rows: string[]) => {
    await selectCsv(type, rows);
    await expect(page.getByText('valid', { exact: true })).toBeVisible();
    const completed = page.waitForResponse((response) =>
      response.url().endsWith(`/imports/${type}/run`)
    );
    await run.click();
    const response = await completed;
    expect(response.ok()).toBe(true);
    expect(await response.json()).toMatchObject({
      template_type: type, status: 'completed', row_count: rows.length, error_count: 0,
      summary: { created: rows.length }
    });
    await expect(page.getByText(`Import completed: ${rows.length} rows, 0 errors.`)).toBeVisible();
  };

  await selectCsv('users', [
    `${userEmail},Imported Operator,invalid_role,EMP-${marker},1234567,Operator,FixturePass123!`
  ]);
  await expect(page.getByText(/Row 2, role:/)).toBeVisible();
  await expect(run).toHaveCount(0);
  expect((await get('/users', { search: userEmail })).items).toEqual([]);
  await importRows('users', [
    `${userEmail},Imported Operator,store_keeper,EMP-${marker},1234567,Operator,FixturePass123!`
  ]);
  expect((await get('/users', { search: userEmail })).items).toEqual([
    expect.objectContaining({ email: userEmail, role: 'store_keeper', employee_code: `EMP-${marker}` })
  ]);
  await importRows('projects', [
    `${projectCode},Import Project ${marker},Fixture yard,Fit out,active,12500.25,2026-01-01,2027-01-01,Client,CON-${marker}`
  ]);
  const projects = await get('/projects', { search: projectCode });
  expect(projects.items).toEqual([expect.objectContaining({ code: projectCode, budget_amount: '12500.25' })]);
  const projectId = projects.items[0].id;
  await importRows('suppliers', [
    `${supplierName},Civil,A,30 days,Test contact,1234567,supplier-${marker}@example.com,Fixture yard,TAX-${marker},,,compliant`
  ]);
  const suppliers = await get('/suppliers', { search: supplierName });
  expect(suppliers.items).toEqual([expect.objectContaining({ name: supplierName, compliance_status: 'compliant' })]);
  await importRows('materials', [
    `Opening stock ${marker},${itemCode},Civil,consumable,KG,0,0,3.25,${supplierName}`
  ]);
  const items = await get('/inventory/items', { search: itemCode });
  expect(items).toEqual([expect.objectContaining({
    item_code: itemCode, unit_cost: '3.25', supplier_id: suppliers.items[0].id
  })]);
  const itemId = items[0].id;
  await importRows('boq', [
    `${projectCode},BOQ-${marker}-A,Panel works,Civil,Phase 1,m2,12.500,3.20`,
    `${projectCode},BOQ-${marker}-B,Finish works,Civil,Phase 1,m2,2.125,10.00`
  ]);
  const { boq_items } = await get(`/projects/${projectId}`);
  expect(boq_items).toHaveLength(2);
  expect(boq_items).toEqual(expect.arrayContaining([
    expect.objectContaining({ item_code: `BOQ-${marker}-A`, planned_quantity: '12.500', planned_amount: '40.00' }),
    expect.objectContaining({ item_code: `BOQ-${marker}-B`, planned_quantity: '2.125', planned_amount: '21.25' })
  ]));
  await importRows('documents', [
    `${documentTitle},drawing,${projectCode},A,Fixture metadata,drawing.pdf`
  ]);
  const documents = await get('/documents', { project_id: projectId });
  expect(documents.items).toEqual([expect.objectContaining({
    title: documentTitle, active_version: null, versions: [],
    metadata_json: expect.objectContaining({ file_name: 'drawing.pdf' })
  })]);
  const metadataOnly = await request.get(`/api/v1/documents/${documents.items[0].id}/download`, { headers });
  expect(metadataOnly.status()).toBe(404);

  const location = await request.post('/api/v1/inventory/locations', {
    headers,
    data: { name: `Opening warehouse ${marker}`, code: locationCode, location_type: 'warehouse' }
  });
  expect(location.status()).toBe(201);
  const { id: locationId } = await location.json();

  await template.selectOption('opening_stock');
  const fileName = `opening-${marker}.csv`;
  const selectFile = (quantity: string) =>
    file.setInputFiles({
      name: fileName,
      mimeType: 'text/csv',
      buffer: Buffer.from(
        `item_code,location_code,quantity,notes\n${itemCode},${locationCode},${quantity},Opening balance\n`
      )
    });
  await selectFile('0');
  await preview.click();
  await expect(page.getByText('1 errors', { exact: true })).toBeVisible();
  await expect(run).toHaveCount(0);
  await selectFile('7.125');
  await preview.click();
  await expect(page.getByText('valid', { exact: true })).toBeVisible();

  let committedBatch: string | undefined;
  let submissionKey: string | undefined;
  await page.route('**/imports/opening_stock/run', async (route) => {
    if (committedBatch) {
      expect(route.request().headers()['idempotency-key']).toBe(submissionKey);
      await route.continue();
      return;
    }
    submissionKey = route.request().headers()['idempotency-key'];
    const response = await route.fetch();
    expect(response.ok()).toBe(true);
    committedBatch = (await response.json()).batch_id;
    await route.abort('failed');
  });
  await run.click();
  await expect(page.getByText('Unable to run import.', { exact: true })).toBeVisible();
  const retried = page.waitForResponse(
    (response) => response.url().endsWith('/imports/opening_stock/run') && response.ok()
  );
  await run.click();
  expect(committedBatch).toBeTruthy();
  expect((await (await retried).json()).batch_id).toBe(committedBatch);
  await expect(page.getByText('Import completed: 1 rows, 0 errors.')).toBeVisible();
  const replayedAsync = page.waitForResponse(
    (response) => response.url().endsWith('/imports/opening_stock/run-async') && response.ok()
  );
  await page.getByRole('button', { name: 'Queue async import', exact: true }).click();
  expect(await (await replayedAsync).json()).toMatchObject({
    batch_id: committedBatch,
    status: 'completed',
    row_count: 1
  });
  if (!submissionKey) throw new Error('The original import did not send a submission key.');
  const changed = await request.post('/api/v1/imports/opening_stock/run', {
    headers: { ...headers, 'Idempotency-Key': submissionKey },
    multipart: {
      file: {
        name: fileName,
        mimeType: 'text/csv',
        buffer: Buffer.from(
          `item_code,location_code,quantity,notes\n${itemCode},${locationCode},1.000,Changed\n`
        )
      }
    }
  });
  expect(changed.status()).toBe(409);

  const stock = await request.get(`/api/v1/inventory/items/${itemId}/stock`, { headers });
  expect(stock.ok()).toBe(true);
  expect(await stock.json()).toEqual([
    expect.objectContaining({
      location_id: locationId,
      on_hand_qty: '7.125',
      reserved_qty: '0.000',
      available_qty: '7.125'
    })
  ]);
  const movements = await request.get('/api/v1/inventory/movements', {
    headers,
    params: { item_id: itemId }
  });
  expect(movements.ok()).toBe(true);
  expect(await movements.json()).toEqual([expect.objectContaining({ quantity: '7.125' })]);
  await page.reload();
  await expect(page.getByText(fileName, { exact: true })).toHaveCount(1);
});
