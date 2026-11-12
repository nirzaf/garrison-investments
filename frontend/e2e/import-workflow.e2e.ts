import { execFileSync } from 'node:child_process';
import { randomUUID } from 'node:crypto';
import { env } from 'node:process';
import { fileURLToPath } from 'node:url';

import { expect, test } from '@playwright/test';

const backendDirectory = fileURLToPath(new URL('../../backend/', import.meta.url));

test.use({ trace: 'off' });

test('opening stock import retries the committed batch after losing its response', async ({
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
  const supplier = await request.post('/api/v1/suppliers', {
    headers,
    data: {
      name: `Import supplier ${marker}`,
      category: 'Civil',
      rating: 'A',
      payment_terms: '30 days',
      contact_person: 'Test contact',
      phone: '1234567',
      email: `import-${marker}@example.com`,
      address: 'Test warehouse',
      tax_registration_number: `TAX-${marker}`,
      compliance_status: 'compliant'
    }
  });
  expect(supplier.status()).toBe(201);
  const { id: supplierId } = await supplier.json();
  const item = await request.post('/api/v1/inventory/items', {
    headers,
    data: {
      name: `Opening stock ${marker}`,
      item_code: itemCode,
      category: 'Civil',
      item_type: 'consumable',
      unit: 'KG',
      unit_cost: '3.25',
      supplier_id: supplierId
    }
  });
  expect(item.status()).toBe(201);
  const { id: itemId } = await item.json();
  const location = await request.post('/api/v1/inventory/locations', {
    headers,
    data: { name: `Opening warehouse ${marker}`, code: locationCode, location_type: 'warehouse' }
  });
  expect(location.status()).toBe(201);
  const { id: locationId } = await location.json();

  await page.goto('/admin/imports');
  await page.getByLabel('Import template').selectOption('opening_stock');
  const fileName = `opening-${marker}.csv`;
  const file = page.getByLabel('Import file');
  const selectFile = (quantity: string) =>
    file.setInputFiles({
      name: fileName,
      mimeType: 'text/csv',
      buffer: Buffer.from(
        `item_code,location_code,quantity,notes\n${itemCode},${locationCode},${quantity},Opening balance\n`
      )
    });
  const preview = page.getByRole('button', { name: 'Preview', exact: true });
  const run = page.getByRole('button', { name: 'Run import', exact: true });
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
