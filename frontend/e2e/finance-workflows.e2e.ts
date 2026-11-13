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

test('Accounts and assigned Project Manager correct, retry, and race invoice payments without overpaying', async ({
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

    await managerPage.goto(path);
    const paymentSessions = [accountsPage, managerPage].map((payerPage) => ({
      page: payerPage,
      invoice: payerPage.getByRole('region', { name: 'Invoice details', exact: true })
    }));
    let releasePayments!: () => void;
    const bothPaymentsReady = new Promise<void>((resolve) => {
      releasePayments = resolve;
    });
    const paymentKeys: (string | undefined)[] = [];
    for (const session of paymentSessions) {
      const amount = session.invoice.getByLabel('Payment amount', { exact: true });
      await expect(amount).toHaveValue('104.90');
      await amount.fill('75.00');
      await session.page.route(
        paymentUrl,
        async (route) => {
          paymentKeys.push(route.request().headers()['idempotency-key']);
          if (paymentKeys.length === paymentSessions.length) releasePayments();
          await bothPaymentsReady;
          await route.continue();
        },
        { times: 1 }
      );
    }
    const competingPayments = await Promise.all(
      paymentSessions.map(async (session) => {
        const [response] = await Promise.all([
          session.page.waitForResponse(
            (result) =>
              result.request().method() === 'POST' &&
              new URL(result.url()).pathname === `/api/v1/finance/invoices/${invoice.id}/payments`
          ),
          session.invoice.getByRole('button', { name: 'Record payment', exact: true }).click()
        ]);
        return { response, invoice: session.invoice };
      })
    );
    expect(paymentKeys).toEqual([expect.any(String), expect.any(String)]);
    expect(new Set([firstKey, ...paymentKeys]).size).toBe(3);
    expect(competingPayments.map(({ response }) => response.status()).sort()).toEqual([200, 409]);
    const conflict = competingPayments.find(({ response }) => response.status() === 409)!;
    expect(await conflict.response.json()).toMatchObject({ error_code: 'PAYMENT_EXCEEDS_BALANCE' });
    await expect(conflict.invoice.getByRole('alert')).toContainText(
      'Payment exceeds the outstanding balance of 29.90.'
    );
    const conflictedAmount = conflict.invoice.getByLabel('Payment amount', { exact: true });
    await expect(conflictedAmount).toHaveValue('75.00');
    await conflict.invoice.getByRole('button', { name: 'Refresh invoice' }).click();
    await expect(conflict.invoice.getByText('29.90', { exact: true })).toBeVisible();
    await conflictedAmount.fill('29.90');
    await conflict.invoice.getByRole('button', { name: 'Record payment', exact: true }).click();
    await expect(conflict.invoice.getByText('paid', { exact: true })).toBeVisible();

    await accountsPage.reload();
    const history = details.getByRole('table', { name: 'Payment history' });
    await expect(history.getByRole('row')).toHaveCount(4);
    for (const amount of ['40.10', '75.00', '29.90']) {
      await expect(history.getByRole('cell', { name: amount, exact: true })).toHaveCount(1);
    }
    await expect(details.getByRole('button', { name: 'Record payment', exact: true })).toHaveCount(
      0
    );
    await expect(details.getByText('0.00', { exact: true })).toBeVisible();
    await accountsPage.getByLabel('Search project filter options').fill(projectName);
    await accountsPage.getByLabel('Project filter', { exact: true }).selectOption(admin.projectId);
    await expect(accountsPage.getByText('270.50', { exact: true })).toBeVisible();
    await expect(
      accountsPage.getByText('Recorded payments', { exact: true }).locator('..')
    ).toHaveText('Recorded payments145.00');
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
  const searched = page.waitForResponse((response) => {
    const url = new URL(response.url());
    return url.pathname === '/api/v1/suppliers' && url.searchParams.get('search') === supplier.name;
  });
  await page.getByLabel('Search suppliers', { exact: true }).fill(supplier.name);
  expect((await searched).status()).toBe(200);
  const card = page.getByRole('article', { name: supplier.name });

  const pdf = execFileSync(python, [
    '-c',
    'import sys; from reportlab.pdfgen.canvas import Canvas; c=Canvas(sys.stdout.buffer); c.drawString(50, 700, "Synthetic TDS fixture"); c.save()'
  ]);
  const input = card.getByLabel('TDS document (30 MiB)', { exact: true });
  // The register must show committed edits and use committed revisions while refresh is pending.
  let releaseRegisterRefresh: (() => void) | undefined;
  const registerRefresh = new Promise<void>((resolve) => {
    releaseRegisterRefresh = resolve;
  });
  await page.route(
    (url) => url.pathname === '/api/v1/suppliers',
    async (route) => {
      await registerRefresh;
      await route.continue();
    }
  );
  try {
    await card.getByRole('button', { name: 'Edit supplier', exact: true }).click();
    await page.getByLabel('TDS expiry date', { exact: true }).fill('2027-04-20');
    await page.getByLabel('Contact person', { exact: true }).fill('Updated contact');
    const saved = page.waitForResponse(
      (response) =>
        response.request().method() === 'PATCH' &&
        new URL(response.url()).pathname === `/api/v1/suppliers/${supplier.id}`
    );
    await page.getByRole('button', { name: 'Save supplier', exact: true }).click();
    const savedResponse = await saved;
    expect(savedResponse.status()).toBe(200);
    expect(await savedResponse.json()).toMatchObject({
      tds_expiry_date: '2027-04-20',
      contact_person: 'Updated contact'
    });
    await expect(card).toContainText('2027-04-20');
    await expect(card).toContainText('Updated contact');
    await card.getByRole('button', { name: 'Edit supplier', exact: true }).click();
    await expect(page.getByLabel('TDS expiry date', { exact: true })).toHaveValue('2027-04-20');
    await page.getByRole('button', { name: 'Discard supplier edits', exact: true }).click();

    let uploadedRevision = 0;
    for (const name of ['evidence.pdf', 'replacement.pdf']) {
      await input.setInputFiles({ name, mimeType: 'application/pdf', buffer: pdf });
      const uploaded = page.waitForResponse(
        (response) => response.url().endsWith('/tds-document') && response.status() === 200
      );
      await card.getByRole('button', { name: 'Upload TDS document', exact: true }).click();
      uploadedRevision = ((await (await uploaded).json()) as { revision: number }).revision;
    }
    await card.getByRole('button', { name: 'Deactivate supplier', exact: true }).click();
    const deactivated = page.waitForResponse(
      (response) =>
        response.request().method() === 'DELETE' &&
        new URL(response.url()).pathname === `/api/v1/suppliers/${supplier.id}`
    );
    await card.getByRole('button', { name: 'Confirm deactivation', exact: true }).click();
    const response = await deactivated;
    expect(new URL(response.url()).searchParams.get('expected_revision')).toBe(
      String(uploadedRevision)
    );
    expect(response.status()).toBe(200);
  } finally {
    releaseRegisterRefresh?.();
  }
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
  await page.reload();
  await page.getByLabel('Supplier state', { exact: true }).selectOption('inactive');
  await page.getByLabel('Search suppliers', { exact: true }).fill(supplier.name);
  await expect(card).toContainText('Updated contact');
  await expect(card).toContainText('2027-04-20');
});
