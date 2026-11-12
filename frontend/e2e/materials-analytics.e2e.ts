import { execFileSync } from 'node:child_process';
import { randomUUID } from 'node:crypto';
import { env } from 'node:process';
import { fileURLToPath } from 'node:url';

import { expect, test, type Page } from '@playwright/test';

type Account = { email: string; password: string; projectId: string };
const backendDirectory = fileURLToPath(new URL('../../backend/', import.meta.url));

function seed(role: 'admin' | 'store_keeper'): Account {
  return JSON.parse(execFileSync(env.BROWSER_TEST_PYTHON ?? 'python',
    ['-m', 'tests.browser_fixtures', 'seed', '--role', role], { cwd: backendDirectory, encoding: 'utf8' }));
}

async function signIn(page: Page, account: Account) {
  await page.goto('/login');
  await page.getByLabel('Email', { exact: true }).fill(account.email);
  await page.getByLabel('Password', { exact: true }).fill(account.password);
  await page.getByRole('button', { name: 'Continue' }).click();
  const code = (await page.getByText(/^Development code:/).innerText()).match(/\d{6}/)?.[0];
  if (!code) throw new Error('Test code unavailable.');
  await page.getByLabel('Verification code').fill(code);
  const response = page.waitForResponse((reply) => reply.url().endsWith('/auth/verify-otp') && reply.ok());
  await page.getByRole('button', { name: 'Verify and sign in' }).click();
  const { access_token } = await (await response).json();
  return { Authorization: `Bearer ${access_token}` };
}

test('store requester selects company project and fulfills chosen quantities across reload', async ({ browser }) => {
  const storePage = await browser.newPage();
  const adminPage = await browser.newPage();
  const admin = seed('admin');
  const adminHeaders = await signIn(adminPage, admin);
  const storeHeaders = await signIn(storePage, seed('store_keeper'));
  const mark = randomUUID().slice(0, 8);

  const create = async (path: string, data: object) => {
    const response = await adminPage.request.post(`/api/v1${path}`, { headers: adminHeaders, data });
    expect(response.ok()).toBe(true);
    return response.json();
  };
  const supplier = await create('/suppliers', { name: `Stores ${mark}`, category: 'Civil', rating: 'A',
    payment_terms: '30 days', contact_person: 'Test contact', phone: '1234567',
    email: `${mark}@example.com`, address: 'Test warehouse', tax_registration_number: `TAX-${mark}`,
    compliance_status: 'compliant' });
  const location = await create('/inventory/locations', { name: `Receipt ${mark}`, code: `R-${mark}`, location_type: 'warehouse' });
  const items = [];
  for (const label of ['Cement', 'Sand']) {
    const item = await create('/inventory/items', { name: `${label} ${mark}`, item_code: `${label}-${mark}`,
      category: 'Civil', item_type: 'consumable', unit: 'KG', supplier_id: supplier.id, unit_cost: '10.00' });
    items.push(item);
    await create('/inventory/movements', { item_id: item.id, movement_type: 'receive', quantity: '12', to_location_id: location.id });
  }

  await storePage.goto('/materials');
  await expect(storePage.getByRole('combobox', { name: 'Request project' }).locator(`option[value="${admin.projectId}"]`)).toHaveCount(1);
  await storePage.getByRole('combobox', { name: 'Request project' }).selectOption(admin.projectId);
  await storePage.getByRole('combobox', { name: 'Source location' }).selectOption(location.id);
  await storePage.getByRole('combobox', { name: 'Item 1' }).selectOption(items[0].id);
  await storePage.getByRole('spinbutton', { name: 'Quantity 1' }).fill('10');
  await storePage.getByRole('button', { name: 'Add line' }).click();
  await storePage.getByRole('combobox', { name: 'Item 2' }).selectOption(items[1].id);
  await storePage.getByRole('spinbutton', { name: 'Quantity 2' }).fill('2');
  const created = storePage.waitForResponse((reply) => reply.url().endsWith('/inventory/requests') && reply.request().method() === 'POST');
  await storePage.getByRole('button', { name: 'Create request' }).click();
  const response = await created;
  expect(response.status()).toBe(201);
  const request = await response.json();
  const projectDetail = await storePage.request.get(`/api/v1/projects/${admin.projectId}`, { headers: storeHeaders });
  expect(projectDetail.status()).toBe(403);

  await storePage.goto('/approvals');
  await expect(storePage.getByText(request.request_number, { exact: true })).toBeVisible();
  await expect(storePage.getByRole('button', { name: 'Report approvals' })).toHaveCount(0);
  const outbox = await storePage.request.get('/api/v1/approvals?box=outbox', { headers: storeHeaders });
  const approval = (await outbox.json()).items.find((item: { request_id: string }) => item.request_id === request.id);
  const decision = await adminPage.request.post(`/api/v1/approvals/${approval.id}/override`, {
    headers: adminHeaders, data: { decision: 'approved', reason: 'Isolated browser verification' }
  });
  expect(decision.ok()).toBe(true);

  await storePage.goto(`/materials?materialRequestId=${request.id}`);
  const card = storePage.locator('article').filter({ hasText: request.request_number });
  await card.getByText('Request lines', { exact: true }).click();
  const cement = card.getByLabel(`Quantity for ${items[0].name}`);
  await cement.fill('4');
  await card.getByRole('button', { name: 'Reserve selected' }).click();
  await expect(card).toContainText('partially_reserved');
  await cement.fill('3');
  await card.getByRole('button', { name: 'Issue selected' }).click();
  await expect(card).toContainText('partially_issued');
  await storePage.reload();
  await card.getByText('Request lines', { exact: true }).click();
  await expect(card).toContainText('7.000 outstanding');
  await expect(card).toContainText('3.000 issued');
  const balances = await storePage.request.get(`/api/v1/inventory/items/${items[0].id}/stock`, { headers: storeHeaders });
  expect((await balances.json()).find((row: { location_id: string }) => row.location_id === location.id))
    .toMatchObject({ on_hand_qty: '9.000', reserved_qty: '1.000', available_qty: '8.000' });
  await storePage.close();
  await adminPage.close();
});

test('analytics shows errors and retains applied controls through retry', async ({ page }) => {
  await signIn(page, seed('admin'));
  let fail = true;
  await page.route('**/api/v1/analytics/summary**', (route) => fail
    ? route.fulfill({ status: 500, json: { detail: 'Analytics unavailable for this check' } })
    : route.continue());
  await page.goto('/analytics');
  await expect(page.getByRole('alert').filter({ hasText: 'Analytics unavailable' })).toBeVisible();
  await page.getByLabel('Project-panel location').fill('Unknown fixture location');
  fail = false;
  await page.getByRole('button', { name: 'Apply filters' }).click();
  await expect(page.getByText('No project data')).toBeVisible();
  await page.route('**/api/v1/export/material-usage**', (route) => {
    expect(new URL(route.request().url()).searchParams.has('location')).toBe(false);
    return route.fulfill({ status: 200, contentType: 'application/json', body: '{"detail":"invalid file"}' });
  });
  await page.getByRole('button', { name: 'Material XLSX' }).click();
  await expect(page.getByRole('alert').filter({ hasText: /invalid export file|Unable to download/ })).toBeVisible();
  await expect(page.getByLabel('Project-panel location')).toHaveValue('Unknown fixture location');
});
