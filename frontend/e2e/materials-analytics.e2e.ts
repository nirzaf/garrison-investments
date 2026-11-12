import { execFileSync } from 'node:child_process';
import { randomUUID } from 'node:crypto';
import { env } from 'node:process';
import { fileURLToPath } from 'node:url';

import { expect, test, type Page } from '@playwright/test';

type Account = { email: string; password: string; projectId: string };
const backendDirectory = fileURLToPath(new URL('../../backend/', import.meta.url));

function seed(role: 'admin' | 'store_keeper'): Account {
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

test('store requester selects company project and fulfills chosen quantities across reload', async ({
  browser
}) => {
  const storePage = await browser.newPage();
  const adminPage = await browser.newPage();
  const admin = seed('admin');
  const adminHeaders = await signIn(adminPage, admin);
  const storeHeaders = await signIn(storePage, seed('store_keeper'));
  const mark = randomUUID().slice(0, 8);

  const create = async (path: string, data: object) => {
    const response = await adminPage.request.post(`/api/v1${path}`, {
      headers: adminHeaders,
      data
    });
    expect(response.ok()).toBe(true);
    return response.json();
  };
  const supplier = await create('/suppliers', {
    name: `Stores ${mark}`,
    category: 'Civil',
    rating: 'A',
    payment_terms: '30 days',
    contact_person: 'Test contact',
    phone: '1234567',
    email: `${mark}@example.com`,
    address: 'Test warehouse',
    tax_registration_number: `TAX-${mark}`,
    compliance_status: 'compliant'
  });
  const location = await create('/inventory/locations', {
    name: `Receipt ${mark}`,
    code: `R-${mark}`,
    location_type: 'warehouse'
  });
  const otherLocation = await create('/inventory/locations', {
    name: `Second store ${mark}`,
    code: `S-${mark}`,
    location_type: 'warehouse'
  });
  const items = [];
  for (const label of ['Cement', 'Sand']) {
    const item = await create('/inventory/items', {
      name: `${label} ${mark}`,
      item_code: `${label}-${mark}`,
      category: 'Civil',
      item_type: 'consumable',
      unit: 'KG',
      supplier_id: supplier.id,
      unit_cost: '10.00'
    });
    items.push(item);
    await create('/inventory/movements', {
      item_id: item.id,
      movement_type: 'receive',
      quantity: '12',
      to_location_id: location.id
    });
  }

  const project = await adminPage.request.get(`/api/v1/projects/${admin.projectId}`, {
    headers: adminHeaders
  });
  expect(project.ok()).toBe(true);
  const { code: projectCode } = await project.json();
  await storePage.goto('/materials');
  await storePage.getByRole('textbox', { name: 'Search inventory' }).fill(items[0].name);
  await storePage.getByRole('button', { name: new RegExp(items[0].name) }).click();
  const receive = storePage.getByRole('form', { name: 'Receive stock' });
  const destination = receive.getByRole('combobox', { name: 'Receipt destination' });
  const quantity = receive.getByPlaceholder('Quantity');
  const notes = receive.getByPlaceholder('Notes');
  const receiveButton = receive.getByRole('button', { name: 'Receive stock' });
  await expect(destination).toHaveValue('');
  await quantity.fill('0.0001');
  await notes.fill('Browser receipt');
  await receiveButton.click();
  expect(
    await destination.evaluate((select: HTMLSelectElement) => select.validity.valueMissing)
  ).toBe(true);

  await destination.selectOption(otherLocation.id);
  await receiveButton.click();
  await expect(receive.getByRole('alert')).toContainText(/3 decimal places/);
  await expect(destination).toHaveValue(otherLocation.id);
  await expect(quantity).toHaveValue('0.0001');
  await expect(notes).toHaveValue('Browser receipt');

  await quantity.fill('2.125');
  const receiptAttempts: { key: string; body: unknown }[] = [];
  let firstReceiptId: string | undefined;
  await storePage.route('**/inventory/movements', async (route) => {
    if (route.request().method() !== 'POST') return route.continue();
    receiptAttempts.push({
      key: route.request().headers()['idempotency-key'],
      body: route.request().postDataJSON()
    });
    if (receiptAttempts.length > 1) return route.continue();
    const original = await route.fetch();
    expect(original.status()).toBe(201);
    firstReceiptId = (await original.json()).id;
    return route.abort();
  });
  await receiveButton.click();
  await expect(receive.getByRole('alert')).toContainText('Retry this movement');
  await expect(destination).toHaveValue(otherLocation.id);
  await expect(quantity).toBeDisabled();
  const received = storePage.waitForResponse(
    (reply) => reply.url().endsWith('/inventory/movements') && reply.request().method() === 'POST'
  );
  await receive.getByRole('button', { name: 'Retry receipt' }).click();
  const receipt = await received;
  expect(receipt.status()).toBe(201);
  expect(receiptAttempts[0].key).toBeTruthy();
  expect(receiptAttempts).toHaveLength(2);
  expect(receiptAttempts[0]).toEqual(receiptAttempts[1]);
  expect(await receipt.json()).toMatchObject({
    id: firstReceiptId,
    item_id: items[0].id,
    to_location_id: otherLocation.id,
    quantity: '2.125'
  });
  await expect(destination).toHaveValue('');
  await expect(quantity).toHaveValue('');
  const receivedRow = storePage.getByRole('row').filter({
    has: storePage.getByRole('rowheader', { name: otherLocation.name })
  });
  await expect(receivedRow.getByRole('cell')).toHaveText(['2.125', '0.000', '2.125']);
  await storePage.getByRole('combobox', { name: 'Filter by location' }).selectOption(location.id);
  await expect(receivedRow).toHaveCount(0);
  const sourceRow = storePage.getByRole('row').filter({
    has: storePage.getByRole('rowheader', { name: location.name, exact: true })
  });
  await expect(sourceRow.getByRole('cell')).toHaveText(['12.000', '0.000', '12.000']);

  await storePage.getByLabel('Search eligible projects').fill(projectCode);
  await expect(
    storePage
      .getByRole('combobox', { name: 'Request project' })
      .locator(`option[value="${admin.projectId}"]`)
  ).toHaveCount(1);
  await storePage.getByRole('combobox', { name: 'Request project' }).selectOption(admin.projectId);
  await storePage.getByRole('combobox', { name: 'Source location' }).selectOption(location.id);
  await storePage.getByRole('combobox', { name: 'Item 1' }).selectOption(items[0].id);
  await storePage.getByRole('spinbutton', { name: 'Quantity 1' }).fill('10');
  await storePage.getByRole('button', { name: 'Add line' }).click();
  await storePage.getByRole('combobox', { name: 'Item 2' }).selectOption(items[1].id);
  await storePage.getByRole('spinbutton', { name: 'Quantity 2' }).fill('2');
  const created = storePage.waitForResponse(
    (reply) => reply.url().endsWith('/inventory/requests') && reply.request().method() === 'POST'
  );
  await storePage.getByRole('button', { name: 'Create request' }).click();
  const response = await created;
  expect(response.status()).toBe(201);
  const request = await response.json();
  const projectDetail = await storePage.request.get(`/api/v1/projects/${admin.projectId}`, {
    headers: storeHeaders
  });
  expect(projectDetail.status()).toBe(403);

  await storePage.goto('/approvals');
  await expect(storePage.getByText(request.request_number, { exact: true })).toBeVisible();
  await expect(storePage.getByRole('button', { name: 'Report approvals' })).toHaveCount(0);
  const outbox = await storePage.request.get('/api/v1/approvals?box=outbox', {
    headers: storeHeaders
  });
  const approval = (await outbox.json()).items.find(
    (item: { request_id: string }) => item.request_id === request.id
  );
  const workflowLink = `/approvals?tab=workflow&approvalId=${approval.id}`;
  await adminPage.goto(workflowLink);
  const workflow = adminPage.getByRole('article').filter({ hasText: request.request_number });
  await workflow.getByPlaceholder('Override reason').fill('Isolated browser verification');
  await workflow.getByRole('button', { name: 'Override', exact: true }).click();
  await expect(workflow).toContainText('override_approved');
  await adminPage.reload();
  await expect(workflow).toContainText('override_approved');
  await expect(workflow.getByRole('button', { name: 'Override', exact: true })).toHaveCount(0);

  await storePage.goto(`/materials?materialRequestId=${request.id}`);
  const card = storePage.locator('article').filter({ hasText: request.request_number });
  await card.getByText('Request lines', { exact: true }).click();
  const cement = card.getByLabel(`Quantity for ${items[0].name}`);
  const reserveAttempts: { key?: string; body: unknown }[] = [];
  await storePage.route(`**/inventory/requests/${request.id}/reserve`, async (route) => {
    const sent = route.request();
    reserveAttempts.push({ key: sent.headers()['idempotency-key'], body: sent.postDataJSON() });
    if (reserveAttempts.length === 1) {
      expect((await route.fetch()).ok()).toBe(true);
      return route.abort();
    }
    return route.continue();
  });
  await cement.fill('4');
  await card.getByRole('button', { name: 'Reserve selected' }).click();
  await expect(card.getByRole('alert')).toContainText('Retry the same quantities');
  await expect(cement).toHaveValue('4');
  await card.getByRole('button', { name: 'Reserve selected' }).click();
  await expect.poll(() => reserveAttempts.length).toBe(2);
  expect(reserveAttempts[0].key).toBeTruthy();
  expect(reserveAttempts[0]).toEqual(reserveAttempts[1]);
  await expect(card).toContainText('partially_reserved');
  await cement.fill('3');
  await card.getByRole('button', { name: 'Issue selected' }).click();
  await expect(card).toContainText('partially_issued');
  await storePage.reload();
  await card.getByText('Request lines', { exact: true }).click();
  await expect(card).toContainText('7.000 outstanding');
  await expect(card).toContainText('3.000 issued');
  const balances = await storePage.request.get(`/api/v1/inventory/items/${items[0].id}/stock`, {
    headers: storeHeaders
  });
  expect(
    (await balances.json()).find((row: { location_id: string }) => row.location_id === location.id)
  ).toMatchObject({ on_hand_qty: '9.000', reserved_qty: '1.000', available_qty: '8.000' });
  await card.getByRole('button', { name: 'Cancel request' }).click();
  await expect(card).toContainText('cancelled');
  await expect(card.getByRole('button', { name: 'Issue selected' })).toHaveCount(0);
  const remainingStock = await storePage.request.get(
    `/api/v1/inventory/items/${items[0].id}/stock`,
    { headers: storeHeaders }
  );
  expect(
    (await remainingStock.json()).find(
      (row: { location_id: string }) => row.location_id === location.id
    )
  ).toMatchObject({ on_hand_qty: '9.000', reserved_qty: '0.000', available_qty: '9.000' });
  const movementForm = storePage.getByRole('form', { name: 'Record stock movement' });
  await movementForm.getByRole('combobox', { name: 'Movement type' }).selectOption('issue');
  await movementForm.getByRole('combobox', { name: 'Movement item' }).selectOption(items[0].id);
  await movementForm.getByRole('combobox', { name: 'From' }).selectOption(location.id);
  const movementQuantity = movementForm.getByPlaceholder('Quantity');
  await movementQuantity.fill('999');
  await movementForm.getByRole('button', { name: 'Record movement' }).click();
  await expect(movementForm.getByRole('alert')).toContainText('Insufficient stock');
  await expect(movementQuantity).toHaveValue('999');
  await expect(movementQuantity).toBeEnabled();
  await movementQuantity.fill('1');
  const corrected = storePage.waitForResponse(
    (reply) => reply.url().endsWith('/inventory/movements') && reply.request().method() === 'POST'
  );
  await movementForm.getByRole('button', { name: 'Record movement' }).click();
  expect((await corrected).status()).toBe(201);
  await expect(movementQuantity).toHaveValue('');
  await storePage.close();
  await adminPage.close();
});

test('analytics preserves labelled results and filters through a failed refresh', async ({
  page
}) => {
  const account = seed('admin');
  const headers = await signIn(page, account);
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
  failure = null;
  await page.getByRole('button', { name: 'Retry' }).click();
  const fixtureSummary = page.getByText(`${projectName}: 0 reports, 0 invoiced`, { exact: true });
  await expect(fixtureSummary).toBeVisible();

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
});
