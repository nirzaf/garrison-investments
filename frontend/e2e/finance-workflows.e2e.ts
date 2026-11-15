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

test('directors can read finance while invoice mutations remain unavailable', async ({
  page,
  request
}) => {
  const director = seedAdmin();
  const token = await signIn(page, director);
  const headers = { Authorization: `Bearer ${token}` };
  const invoiceNumber = `DENIED-${randomUUID().slice(0, 8)}`;
  const before = await request.get('/api/v1/finance/invoices', { headers });
  expect(before.status()).toBe(200);

  await page.goto('/finance');
  await expect(page.getByText(/Finance is read-only under the current role policy/)).toBeVisible();
  await expect(page.getByRole('button', { name: 'New invoice', exact: true })).toHaveCount(0);
  await expect(page.getByRole('button', { name: 'Record payment', exact: true })).toHaveCount(0);

  const attempted = await request.post('/api/v1/finance/invoices', {
    headers,
    data: {
      invoice_number: invoiceNumber,
      project_id: director.projectId,
      supplier_id: null,
      invoice_date: '2026-11-14',
      due_date: '2026-12-14',
      amount: '125.50',
      tax_amount: '0.00'
    }
  });
  expect(attempted.status()).toBe(403);

  const after = await request.get('/api/v1/finance/invoices', { headers });
  expect(after.status()).toBe(200);
  expect(await after.json()).toEqual(await before.json());
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
