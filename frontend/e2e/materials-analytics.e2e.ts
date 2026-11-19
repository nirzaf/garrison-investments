import { execFileSync } from 'node:child_process';
import { randomUUID } from 'node:crypto';
import { env } from 'node:process';
import { fileURLToPath } from 'node:url';

import { expect, test, type Page } from '@playwright/test';

type Account = { email: string; password: string; projectId: string };
const backendDirectory = fileURLToPath(new URL('../../backend/', import.meta.url));

function seed(role: 'managing_director' | 'site_supervisor'): Account {
  return JSON.parse(
    execFileSync(
      env.BROWSER_TEST_PYTHON ?? 'python',
      ['-m', 'tests.browser_fixtures', 'seed', '--role', role],
      { cwd: backendDirectory, encoding: 'utf8' }
    )
  );
}

async function signIn(page: Page, account: Account) {
  await page.goto('/login');
  await page.getByLabel('Email', { exact: true }).fill(account.email);
  await page.getByLabel('Password', { exact: true }).fill(account.password);
  await page.getByRole('button', { name: 'Continue' }).click();
  const code = (await page.getByText(/^Development code:/).innerText()).match(/\d{6}/)?.[0];
  if (!code) throw new Error('Test code unavailable.');
  await page.getByLabel('Verification code').fill(code);
  const response = page.waitForResponse(
    (reply) => reply.url().endsWith('/auth/verify-otp') && reply.ok()
  );
  await page.getByRole('button', { name: 'Verify and sign in' }).click();
  const { access_token } = await (await response).json();
  return { Authorization: `Bearer ${access_token}` };
}

test('site supervisors can read price-safe stock but cannot run inventory commands', async ({
  page,
  request
}) => {
  const account = seed('site_supervisor');
  const headers = await signIn(page, account);
  const before = await request.get('/api/v1/inventory/items', { headers });
  expect(before.status()).toBe(200);
  const items = await before.json();
  expect(items.every((item: { unit_cost: string | null }) => item.unit_cost === null)).toBe(true);

  const mark = randomUUID().slice(0, 8);
  const requests = [
    request.post('/api/v1/inventory/locations', {
      headers,
      data: { name: `Denied location ${mark}`, code: `DEN-${mark}`, location_type: 'warehouse' }
    }),
    request.post('/api/v1/inventory/items', {
      headers,
      data: {
        name: `Denied item ${mark}`,
        item_code: `DEN-${mark}`,
        category: 'Fixture',
        item_type: 'consumable',
        unit: 'KG',
        supplier_id: randomUUID()
      }
    }),
    request.post('/api/v1/inventory/movements', {
      headers,
      data: { item_id: randomUUID(), movement_type: 'receive', quantity: '1', to_location_id: randomUUID() }
    }),
    request.post('/api/v1/inventory/requests', {
      headers,
      data: {
        project_id: account.projectId,
        from_location_id: randomUUID(),
        lines: [{ item_id: randomUUID(), quantity: '1' }]
      }
    }),
    request.post(`/api/v1/inventory/requests/${randomUUID()}/reserve`, { headers }),
    request.post(`/api/v1/inventory/requests/${randomUUID()}/issue`, { headers })
  ];
  const responses = await Promise.all(requests);
  expect(responses.map((response) => response.status())).toEqual([403, 403, 403, 403, 403, 403]);

  await page.goto('/materials');
  await expect(page.getByRole('button', { name: 'Add item', exact: true })).toHaveCount(0);
  await expect(page.getByRole('button', { name: 'Record movement', exact: true })).toHaveCount(0);
  const after = await request.get('/api/v1/inventory/items', { headers });
  expect(await after.json()).toEqual(items);
});

test('a Managing Director transfers a tagged asset and preserves reserved stock', async ({ browser, page }) => {
  const headers = await signIn(page, seed('managing_director'));
  const admin = await browser.newPage();
  const adminHeaders = await signIn(admin, seed('managing_director'));
  const mark = randomUUID().slice(0, 8);
  const supplierResponse = await admin.request.post('/api/v1/suppliers', {
    headers: adminHeaders,
    data: {
      name: `Tools ${mark}`, category: 'Civil', rating: 'A', payment_terms: '30 days',
      contact_person: 'Test contact', phone: '1234567', email: `${mark}@example.com`,
      address: 'Test warehouse', tax_registration_number: `TAX-${mark}`,
      compliance_status: 'compliant'
    }
  });
  expect(supplierResponse.status()).toBe(201);
  const { id: supplierId } = await supplierResponse.json();
  await admin.close();
  const create = async (path: string, data: object) => {
    const response = await page.request.post(`/api/v1/inventory${path}`, { headers, data });
    expect(response.status()).toBe(201);
    return response.json();
  };
  const makeLocation = (name: string) => create('/locations', {
    name: `${name} ${mark}`, code: `${name}-${mark}`, location_type: 'warehouse'
  });
  const source = await makeLocation('Source');
  const destination = await makeLocation('Destination');
  const item = await create('/items', {
    name: `Laser ${mark}`, item_code: `LASER-${mark}`, item_type: 'asset',
    category: 'Tools', unit: 'Nos', supplier_id: supplierId
  });
  const other = await create('/items', {
    name: `Level ${mark}`, item_code: `LEVEL-${mark}`, item_type: 'asset',
    category: 'Tools', unit: 'Nos', supplier_id: supplierId
  });
  const tag = `TAG-${mark}`;
  const asset = await create('/assets', {
    item_id: item.id, asset_tag: tag, current_location_id: source.id
  });
  await create('/assets', {
    item_id: other.id, asset_tag: `OTHER-${mark}`, current_location_id: source.id
  });
  const transfer = {
    item_id: other.id, asset_id: asset.id, movement_type: 'transfer', quantity: '1',
    from_location_id: source.id, to_location_id: destination.id
  };
  const invalid = await page.request.post('/api/v1/inventory/movements', { headers, data: transfer });
  expect(invalid.status()).toBe(422);
  expect((await invalid.json()).error_code).toBe('INVALID_ASSET_TRANSFER');
  const wrongQuantity = await page.request.post('/api/v1/inventory/movements', {
    headers, data: { ...transfer, item_id: item.id, quantity: '0.5' }
  });
  expect(wrongQuantity.status()).toBe(422);
  const missingLocation = await page.request.post('/api/v1/inventory/movements', {
    headers, data: { ...transfer, item_id: item.id, to_location_id: randomUUID() }
  });
  expect(missingLocation.status()).toBe(404);

  await page.goto('/materials');
  await page.getByRole('textbox', { name: 'Search inventory' }).fill(mark);
  const form = page.getByRole('form', { name: 'Record stock movement' });
  const type = form.getByRole('combobox', { name: 'Movement type' });
  const selected = form.getByRole('combobox', { name: 'Movement item' });
  const from = form.getByRole('combobox', { name: 'From', exact: true });
  const to = form.getByRole('combobox', { name: 'To', exact: true });
  const quantity = form.getByPlaceholder('Quantity');
  const record = form.getByRole('button', { name: 'Record movement', exact: true });
  const submit = async (status: number) => {
    const result = page.waitForResponse((response) =>
      response.url().endsWith('/api/v1/inventory/movements') && response.request().method() === 'POST'
    );
    await record.click();
    const response = await result;
    expect(response.status()).toBe(status);
    return response.json();
  };
  await expect(selected.getByRole('option', { name: item.name, exact: true })).toHaveCount(1);
  await selected.selectOption(item.id);
  await form.getByRole('combobox', { name: 'Movement asset tag' }).selectOption(asset.id);
  await from.selectOption(source.id);
  await to.selectOption(destination.id);
  await quantity.fill('1');
  await create('/movements', {
    item_id: item.id, movement_type: 'reserve', quantity: '1', from_location_id: source.id
  });
  expect((await submit(409)).error_code).toBe('INSUFFICIENT_STOCK');
  await expect(form.getByRole('alert')).toContainText('Insufficient stock');

  const spare = await create('/assets', {
    item_id: item.id, asset_tag: `SPARE-${mark}`, current_location_id: source.id
  });
  const moved = await submit(201);
  expect(moved).toMatchObject({ asset_id: asset.id, to_location_id: destination.id });
  const stale = await page.request.post('/api/v1/inventory/movements', {
    headers, data: { ...transfer, item_id: item.id }
  });
  expect(stale.status()).toBe(409);
  expect((await stale.json()).error_code).toBe('ASSET_NOT_AVAILABLE');
  await page.reload();
  const tool = (assetTag: string) => page.locator('span').getByText(assetTag, { exact: true }).locator('..');
  await expect(tool(tag)).toContainText(destination.name);
  await expect(tool(spare.asset_tag)).toContainText(source.name);

  const consumable = await create('/items', {
    name: `Cable ${mark}`, item_code: `CABLE-${mark}`, item_type: 'consumable',
    category: 'Electrical', unit: 'Nos', supplier_id: supplierId
  });
  await page.reload();
  await page.getByRole('textbox', { name: 'Search inventory' }).fill(consumable.name);
  await expect(selected.getByRole('option', { name: consumable.name, exact: true })).toHaveCount(1);
  for (const [movement, amount] of [['return', '2.125'], ['adjustment', '-0.125']]) {
    await type.selectOption(movement);
    await selected.selectOption(consumable.id);
    await to.selectOption(destination.id);
    await quantity.fill(amount);
    await submit(201);
    await expect(quantity).toHaveValue('');
  }
  const stock = async (id: string) => {
    const response = await page.request.get(`/api/v1/inventory/items/${id}/stock`, { headers });
    expect(response.ok()).toBe(true);
    return response.json();
  };
  expect(await stock(item.id)).toEqual(expect.arrayContaining([
    expect.objectContaining({ location_id: source.id, on_hand_qty: '1.000', reserved_qty: '1.000', available_qty: '0.000' }),
    expect.objectContaining({ location_id: destination.id, on_hand_qty: '1.000', reserved_qty: '0.000', available_qty: '1.000' })
  ]));
  expect(await stock(other.id)).toEqual([
    expect.objectContaining({ location_id: source.id, on_hand_qty: '1.000' })
  ]);
  expect(await stock(consumable.id)).toEqual([
    expect.objectContaining({ location_id: destination.id, on_hand_qty: '2.000' })
  ]);
  const history = await page.request.get('/api/v1/inventory/movements', {
    headers, params: { item_id: item.id }
  });
  expect(history.ok()).toBe(true);
  expect((await history.json()).filter((row: { movement_type: string }) => row.movement_type === 'transfer'))
    .toEqual([expect.objectContaining({ id: moved.id })]);
});

test('analytics downloads match the filtered project and material control totals', async ({ page }) => {
  const account = seed('managing_director');
  const headers = await signIn(page, account);
  const suffix = account.projectId.slice(0, 8);
  const location = `Analytics yard ${suffix}`;
  const currentProject = await page.request.get(`/api/v1/projects/${account.projectId}`, {
    headers
  });
  expect(currentProject.ok()).toBe(true);
  const { revision } = (await currentProject.json()) as { revision: number };
  const updateProject = await page.request.patch(`/api/v1/projects/${account.projectId}`, {
    headers,
    data: { location, expected_revision: revision }
  });
  expect(updateProject.ok()).toBe(true);
  const project = await updateProject.json();
  const post = async (path: string, data: object) => {
    const response = await page.request.post(`/api/v1${path}`, { headers, data });
    expect(response.ok(), `${path} returned HTTP ${response.status()}`).toBe(true);
    return response.json();
  };
  const itemName = `Analytics material ${suffix}`;
  const supplier = await post('/suppliers', {
    name: `Analytics supplier ${suffix}`, category: 'Civil', rating: 'A',
    payment_terms: '30 days', contact_person: 'Fixture contact', phone: '1234567',
    email: `analytics-${suffix}@example.com`, address: 'Fixture yard',
    tax_registration_number: `AN-${suffix}`, compliance_status: 'compliant'
  });
  const item = await post('/inventory/items', {
    name: itemName, item_code: `AN-${suffix}`, category: 'Browser regression tests',
    item_type: 'consumable', unit: 'KG', supplier_id: supplier.id
  });
  const yard = await post('/inventory/locations', {
    name: location, code: `AN-${suffix}`, location_type: 'warehouse'
  });
  await post('/inventory/movements', {
    item_id: item.id, movement_type: 'receive', quantity: '10.000', to_location_id: yard.id
  });
  for (const [movement_type, quantity] of [['issue', '2.750'], ['consume', '1.125']]) {
    await post('/inventory/movements', {
      item_id: item.id, movement_type, quantity, from_location_id: yard.id,
      project_id: account.projectId
    });
  }
  execFileSync(
    env.BROWSER_TEST_PYTHON ?? 'python',
    [
      '-m',
      'tests.browser_fixtures',
      'seed-analytics-finance',
      '--project-id',
      account.projectId
    ],
    { cwd: backendDirectory, encoding: 'utf8' }
  );

  await page.goto('/analytics');
  await page.getByRole('combobox', { name: 'Project', exact: true }).selectOption(account.projectId);
  await page.getByLabel('Activity from').fill('2025-01-01');
  await page.getByLabel('Project-panel location').fill(location);
  await page.getByLabel('Project scope or material category').fill('Browser regression tests');
  const summary = page.waitForResponse((response) =>
    response.url().includes('/api/v1/analytics/summary?') &&
    new URL(response.url()).searchParams.get('project_id') === account.projectId
  );
  await page.getByRole('button', { name: 'Apply filters' }).click();
  const applied = await summary;
  expect(applied.ok()).toBe(true);
  expect(await applied.json()).toMatchObject({
    projects: [{ project_id: account.projectId, invoice_total: '214.50', paid_total: '42.15', report_count: 0 }],
    material_usage: [{ item_name: itemName, issued_quantity: '2.750', consumed_quantity: '1.125' }]
  });
  await expect(page.getByText(`${project.name}: 0 reports, USD 214.50 invoiced`, { exact: true })).toBeVisible();

  for (const [label, filename] of [
    ['Project XLSX', 'project-progress.xlsx'],
    ['Material XLSX', 'material-usage.xlsx'],
    ['Summary PDF', 'management-summary.pdf']
  ]) {
    const response = page.waitForResponse((reply) =>
      new URL(reply.url()).pathname === `/api/v1/export/${filename.split('.')[0]}`
    );
    const downloaded = page.waitForEvent('download');
    await page.getByRole('button', { name: label, exact: true }).click();
    const exportResponse = await response;
    expect(exportResponse.ok()).toBe(true);
    const params = new URL(exportResponse.url()).searchParams;
    expect(params.get('project_id')).toBe(account.projectId);
    expect(params.get('date_from')).toBe('2025-01-01');
    expect(params.get('department')).toBe('Browser regression tests');
    expect(params.get('location')).toBe(label === 'Material XLSX' ? null : location);
    const download = await downloaded;
    expect(download.suggestedFilename()).toBe(filename);
    const path = await download.path();
    if (!path) throw new Error(`Missing download for ${filename}`);
    const content = execFileSync(env.BROWSER_TEST_PYTHON ?? 'python', [
      '-c', [
        'import json, sys',
        'from pathlib import Path',
        'from tests.test_analytics import xlsx_rows',
        'from tests.test_blocking_io_offload import pdf_text',
        'data = Path(sys.argv[1]).read_bytes()',
        'print(json.dumps(pdf_text(data) if sys.argv[2].endswith(".pdf") else xlsx_rows(data)))'
      ].join('\n'), path, filename
    ], { cwd: backendDirectory, encoding: 'utf8' });
    const lines = content.trim().split('\n');
    const report = JSON.parse(lines[lines.length - 1]);
    if (label === 'Project XLSX') {
      expect(report.slice(1)).toEqual([[project.name, '0', '0', '214.50', '42.15']]);
    } else if (label === 'Material XLSX') {
      expect(report.slice(1)).toEqual([[itemName, '2.750', '1.125']]);
    } else {
      for (const text of [project.name, '214.50', '42.15', itemName, '2.750', '1.125', location]) {
        expect(report).toContain(text);
      }
    }
  }
});

test('analytics preserves labelled results and filters through a failed refresh', async ({
  browser
}) => {
  // Let Playwright observe the cold chart request before the app-shell worker can cache it.
  const page = await browser.newPage({ serviceWorkers: 'block' });
  let finishChartRequest!: () => void;
  const chartGate = new Promise<void>((resolve) => { finishChartRequest = resolve; });
  let chartRequests = 0;
  await page.route('**/assets/AnalyticsCharts-*.js', async (route) => {
    chartRequests += 1;
    await chartGate;
    await route.continue();
  });
  const account = seed('managing_director');
  const headers = await signIn(page, account);
  await expect(page.getByRole('heading', { name: 'Launch Operations' })).toBeVisible();
  expect(chartRequests).toBe(0);
  const project = await page.request.get(`/api/v1/projects/${account.projectId}`, { headers });
  expect(project.ok()).toBe(true);
  const { name: projectName } = await project.json();

  let failure: 'initial' | 'filter' | 'denied' | null = 'initial';
  await page.route('**/api/v1/analytics/summary**', (route) => {
    if (failure === 'denied') {
      return route.fulfill({ status: 403, json: { detail: 'Access to analytics was removed' } });
    }
    if (failure) {
      return route.fulfill({
        status: 400,
        json: { detail: 'Analytics unavailable for this check' }
      });
    }
    return route.continue();
  });
  await page.goto('/analytics');
  await expect(page.getByRole('alert').filter({ hasText: 'Analytics unavailable' })).toBeVisible();
  expect(chartRequests).toBe(0);
  failure = null;
  const fixtureSummary = page.getByText(`${projectName}: 0 reports, USD 0 invoiced`, { exact: true });
  try {
    await page.getByRole('button', { name: 'Retry' }).click();
    await expect(fixtureSummary).toBeVisible();
    await expect(page.getByRole('status').filter({ hasText: 'Loading chart…' }).first()).toBeVisible();
    await expect.poll(() => chartRequests).toBe(1);
  } finally {
    finishChartRequest();
  }
  await expect(page.locator('.recharts-surface').first()).toBeVisible();

  failure = 'filter';
  await page.getByLabel('Project-panel location').fill('Unknown fixture location');
  await page.getByRole('button', { name: 'Apply filters' }).click();
  await expect(page.getByRole('alert').filter({ hasText: 'Analytics unavailable' })).toBeVisible();
  await expect(
    page
      .getByRole('status')
      .filter({ hasText: 'last successful results for all accessible projects' })
  ).toBeVisible();
  await expect(fixtureSummary).toBeVisible();
  await expect(page.getByRole('button', { name: 'Material XLSX' })).toBeDisabled();

  failure = null;
  await page.getByRole('button', { name: 'Retry' }).click();
  await expect(page.getByText('No project data')).toBeVisible();
  await expect(fixtureSummary).toHaveCount(0);
  await page.route('**/api/v1/export/material-usage**', (route) => {
    expect(new URL(route.request().url()).searchParams.has('location')).toBe(false);
    return route.fulfill({
      status: 200,
      contentType: 'application/json',
      body: '{"detail":"invalid file"}'
    });
  });
  await page.getByRole('button', { name: 'Material XLSX' }).click();
  await expect(
    page.getByRole('alert').filter({ hasText: /invalid export file|Unable to download/ })
  ).toBeVisible();
  await expect(page.getByLabel('Project-panel location')).toHaveValue('Unknown fixture location');

  failure = 'denied';
  await page.getByLabel('Project-panel location').fill('Denied fixture location');
  await page.getByRole('button', { name: 'Apply filters' }).click();
  await expect(
    page.getByRole('alert').filter({ hasText: 'Access to analytics was removed' })
  ).toBeVisible();
  await expect(page.getByRole('heading', { name: 'Project progress' })).toHaveCount(0);
  await expect(page.getByRole('button', { name: 'Summary PDF' })).toBeDisabled();
  await page.close();
});
