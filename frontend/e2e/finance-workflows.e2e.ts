import { execFileSync } from 'node:child_process';
import { randomUUID } from 'node:crypto';
import { env } from 'node:process';
import { fileURLToPath } from 'node:url';

import { expect, test, type APIRequestContext, type Page } from '@playwright/test';

type Account = { email: string; password: string };
type SeedAccount = Account & { projectId: string };
const backendDirectory = fileURLToPath(new URL('../../backend/', import.meta.url));
const python = env.BROWSER_TEST_PYTHON ?? 'python';

test.use({ trace: 'off' });

function seedAdmin(): SeedAccount {
  return JSON.parse(
    execFileSync(python, ['-m', 'tests.browser_fixtures', 'seed'], {
      cwd: backendDirectory,
      encoding: 'utf8'
    })
  );
}

async function signIn(page: Page, account: Account): Promise<string> {
  await page.goto('/login');
  await page.getByLabel('Email', { exact: true }).fill(account.email);
  await page.getByLabel('Password', { exact: true }).fill(account.password);
  await page.getByRole('button', { name: 'Continue' }).click();
  const codeLabel = page.getByText(/^Development code:/);
  await expect(codeLabel).toBeVisible();
  const code = (await codeLabel.innerText()).match(/\d{6}/)?.[0];
  if (!code) throw new Error('The test API did not expose the verification code.');
  await page.getByLabel('Verification code').fill(code);
  const verification = page.waitForResponse(
    (response) => response.url().endsWith('/api/v1/auth/verify-otp') && response.ok()
  );
  await page.getByRole('button', { name: 'Verify and sign in' }).click();
  return ((await (await verification).json()) as { access_token: string }).access_token;
}

async function createAccount(
  request: APIRequestContext,
  headers: Record<string, string>,
  role: string,
  suffix: string
) {
  const account = { email: `${role}-${suffix}@example.com`, password: 'BrowserFixture!2027' };
  const created = await request.post('/api/v1/users', {
    headers,
    data: {
      email: account.email,
      temporary_password: account.password,
      full_name: `Finance tester ${role} ${suffix}`,
      role,
      employee_code: `${role}-${suffix}`,
      phone: '5550124'
    }
  });
  expect(created.status()).toBe(201);
  return { ...account, id: ((await created.json()) as { id: string }).id };
}

async function createSupplier(
  request: APIRequestContext,
  headers: Record<string, string>,
  suffix: string
) {
  const supplier = {
    name: `Finance fixture ${suffix}`,
    category: 'Electrical',
    rating: 'A',
    payment_terms: '30 days',
    contact_person: 'Site contact',
    phone: '5550125',
    email: `supplier-${suffix}@example.com`,
    address: 'Site address',
    tax_registration_number: `TAX-${suffix}`,
    compliance_status: 'pending'
  };
  const created = await request.post('/api/v1/suppliers', { headers, data: supplier });
  expect(created.status()).toBe(201);
  return { ...supplier, id: ((await created.json()) as { id: string }).id };
}

async function submitInvoice(
  page: Page,
  projectId: string,
  projectName: string,
  invoiceNumber: string,
  supplierName: string
) {
  await page.goto('/finance');
  await page.getByRole('button', { name: 'New invoice', exact: true }).click();
  await page.getByLabel('Invoice number', { exact: true }).fill(invoiceNumber);
  await page.getByLabel('Search invoice project options').fill(projectName);
  await page.getByLabel('Invoice project', { exact: true }).selectOption(projectId);
  await page.getByLabel('Search supplier options').fill(supplierName);
  await page.getByLabel('Supplier', { exact: true }).selectOption({ label: supplierName });
  await page.getByLabel('Invoice date', { exact: true }).fill('2027-01-02');
  await page.getByLabel('Due date', { exact: true }).fill('2027-01-01');
  await page.getByLabel('Amount', { exact: true }).fill('125.50');
  const button = page.getByRole('button', { name: 'Submit invoice', exact: true });
  await button.click();
  await expect(page.getByText('Due date must be on or after the invoice date.')).toBeVisible();
  await expect(page.getByLabel('Invoice number', { exact: true })).toHaveValue(invoiceNumber);
  await page.getByLabel('Due date', { exact: true }).fill('2027-02-01');
  const response = page.waitForResponse(
    (result) => result.url().endsWith('/api/v1/finance/invoices') && result.status() === 201
  );
  await button.click();
  return (await (await response).json()) as { id: string; supplier_name: string };
}

test('Accounts and assigned Project Manager use the finance lookup and complete invoice correction and payment', async ({
  page,
  browser,
  request,
  baseURL
}) => {
  test.setTimeout(65_000);
  const admin = seedAdmin();
  const adminToken = await signIn(page, admin);
  const headers = { Authorization: `Bearer ${adminToken}` };
  const suffix = randomUUID().slice(0, 8);
  const project = await request.get(`/api/v1/projects/${admin.projectId}`, { headers });
  expect(project.ok()).toBe(true);
  const projectName = ((await project.json()) as { name: string }).name;
  const accounts = await createAccount(request, headers, 'accounts', suffix);
  const manager = await createAccount(request, headers, 'project_manager', suffix);
  const operations = await createAccount(request, headers, 'operation_manager', suffix);
  const supplier = await createSupplier(request, headers, suffix);
  const membership = await request.post(`/api/v1/projects/${admin.projectId}/members`, {
    headers,
    data: { user_id: manager.id }
  });
  expect(membership.status()).toBe(201);

  const accountsPage = await browser.newPage({ baseURL });
  const managerPage = await browser.newPage({ baseURL });
  const operationsPage = await browser.newPage({ baseURL });
  try {
    const accountsToken = await signIn(accountsPage, accounts);
    const managerToken = await signIn(managerPage, manager);
    for (const token of [accountsToken, managerToken]) {
      const directory = await request.get('/api/v1/suppliers', {
        headers: { Authorization: `Bearer ${token}` }
      });
      expect(directory.status()).toBe(403);
    }
    const invoice = await submitInvoice(
      accountsPage,
      admin.projectId,
      projectName,
      `ACC-${suffix}`,
      supplier.name
    );
    const scoped = await submitInvoice(
      managerPage,
      admin.projectId,
      projectName,
      `PM-${suffix}`,
      supplier.name
    );
    expect(invoice.supplier_name).toBe(supplier.name);
    expect(scoped.supplier_name).toBe(supplier.name);
    await signIn(operationsPage, operations);
    const path = `/finance?invoiceId=${invoice.id}`;
    await operationsPage.goto(path);
    const operationsDetails = operationsPage.getByRole('region', {
      name: 'Invoice details',
      exact: true
    });
    await operationsDetails.getByRole('button', { name: 'Reject invoice', exact: true }).click();
    await operationsDetails.getByLabel('Rejection notes').fill('Correct the invoice amount.');
    await operationsDetails.getByRole('button', { name: 'Confirm rejection' }).click();
    await expect(operationsDetails.getByText('rejected', { exact: true })).toBeVisible();

    await accountsPage.goto(path);
    const details = accountsPage.getByRole('region', { name: 'Invoice details', exact: true });
    await details.getByRole('button', { name: 'Correct invoice', exact: true }).click();
    await details.getByLabel('Amount', { exact: true }).fill('140.75');
    await details.getByLabel('Tax amount', { exact: true }).fill('4.25');
    await details.getByLabel('Supplier', { exact: true }).selectOption('');
    await details.getByRole('button', { name: 'Save corrections', exact: true }).click();
    await expect(details.getByText('145.00', { exact: true })).toHaveCount(2);
    await details.getByRole('button', { name: 'Resubmit invoice', exact: true }).click();
    await expect(details.getByText('submitted', { exact: true })).toBeVisible();
    await expect(details.getByRole('button', { name: 'Approve invoice', exact: true })).toHaveCount(
      0
    );
    await operationsPage.reload();
    await operationsDetails.getByRole('button', { name: 'Approve invoice', exact: true }).click();
    await expect(operationsDetails.getByText('approved', { exact: true })).toBeVisible();

    await accountsPage.reload();
    const paymentUrl = `**/api/v1/finance/invoices/${invoice.id}/payments`;
    let firstKey: string | undefined;
    let firstBody: string | null = null;
    await accountsPage.route(paymentUrl, async (route) => {
      const outgoing = route.request();
      const key = outgoing.headers()['idempotency-key'];
      if (firstKey === undefined) {
        expect(key).toBeTruthy();
        firstKey = key;
        firstBody = outgoing.postData();
        const committed = await route.fetch();
        expect(committed.ok()).toBe(true);
        await route.abort('failed');
      } else {
        expect(key).toBe(firstKey);
        expect(outgoing.postData()).toBe(firstBody);
        await route.continue();
      }
    });
    await details.getByLabel('Payment amount', { exact: true }).fill('40.10');
    await details.getByRole('button', { name: 'Record payment', exact: true }).click();
    await expect(
      details.getByText('The payment result could not be confirmed.', { exact: false })
    ).toBeVisible();
    await expect(details.getByLabel('Payment amount', { exact: true })).toHaveValue('40.10');
    await details.getByRole('button', { name: 'Retry payment', exact: true }).click();
    await expect(details.getByText('partial', { exact: true })).toBeVisible();
    await expect(details.getByLabel('Payment amount', { exact: true })).toHaveValue('104.90');
    await expect(
      details.getByRole('table', { name: 'Payment history' }).getByRole('row')
    ).toHaveCount(2);
    await accountsPage.unroute(paymentUrl);
    await details.getByRole('button', { name: 'Record payment', exact: true }).click();
    await expect(details.getByText('paid', { exact: true })).toBeVisible();
    await accountsPage.reload();
    await expect(
      details.getByRole('table', { name: 'Payment history' }).getByRole('row')
    ).toHaveCount(3);
    await expect(details.getByRole('button', { name: 'Record payment', exact: true })).toHaveCount(
      0
    );
  } finally {
    await Promise.all([accountsPage.close(), managerPage.close(), operationsPage.close()]);
  }
});

test('supplier manager edits expiry, replaces evidence, and deactivates a supplier with history retained', async ({
  page,
  request
}) => {
  const token = await signIn(page, seedAdmin());
  const headers = { Authorization: `Bearer ${token}` };
  const suffix = randomUUID().slice(0, 8);
  const supplier = await createSupplier(request, headers, suffix);
  await page.goto('/suppliers');
  await page.getByLabel('Search suppliers', { exact: true }).fill(supplier.name);
  const card = page.getByRole('article', { name: supplier.name });
  await card.getByRole('button', { name: 'Edit supplier', exact: true }).click();
  await page.getByLabel('TDS expiry date', { exact: true }).fill('2027-04-20');
  await page.getByLabel('Contact person', { exact: true }).fill('Updated contact');
  await page.getByRole('button', { name: 'Save supplier', exact: true }).click();
  await expect(card).toContainText('2027-04-20');
  await expect(card).toContainText('Updated contact');

  const pdf = execFileSync(python, [
    '-c',
    'import sys; from reportlab.pdfgen.canvas import Canvas; c=Canvas(sys.stdout.buffer); c.drawString(50, 700, "Synthetic TDS fixture"); c.save()'
  ]);
  const input = card.getByLabel('TDS document (30 MiB)', { exact: true });
  for (const name of ['evidence.pdf', 'replacement.pdf']) {
    await input.setInputFiles({ name, mimeType: 'application/pdf', buffer: pdf });
    const uploaded = page.waitForResponse(
      (response) => response.url().endsWith('/tds-document') && response.status() === 200
    );
    await card.getByRole('button', { name: 'Upload TDS document', exact: true }).click();
    await uploaded;
  }
  await card.getByRole('button', { name: 'Deactivate supplier', exact: true }).click();
  await card.getByRole('button', { name: 'Confirm deactivation', exact: true }).click();
  await expect(card).toHaveCount(0);
  await page.getByLabel('Supplier state', { exact: true }).selectOption('inactive');
  await expect(card).toContainText('Inactive');
  await card.getByRole('button', { name: 'Get TDS link', exact: true }).click();
  const documentLink = card.getByRole('link', { name: 'Open TDS document', exact: true });
  await expect(documentLink).toBeVisible();
  const href = await documentLink.getAttribute('href');
  if (!href) throw new Error('The test object link was not generated.');
  const download = await request.get(href);
  expect(download.status()).toBe(200);
  expect((await download.body()).equals(pdf)).toBe(true);
  const lookup = await request.get('/api/v1/finance/supplier-options', {
    headers,
    params: { search: supplier.name }
  });
  expect(await lookup.json()).toEqual({ items: [], total: 0 });
});
