import { execFileSync } from 'node:child_process';
import { createHash } from 'node:crypto';
import { mkdtempSync, readFileSync, rmSync, statSync, writeFileSync } from 'node:fs';
import { tmpdir } from 'node:os';
import { join } from 'node:path';
import { env } from 'node:process';
import { fileURLToPath } from 'node:url';

import { expect, test, type APIRequestContext, type Page } from '@playwright/test';

const BACKEND_DIR = fileURLToPath(new URL('../../backend/', import.meta.url));
const PYTHON_BIN = env.BROWSER_TEST_PYTHON ?? 'python';

const CANONICAL_ROLES = [
  ['managing_director', 'Managing Director'],
  ['operations_director', 'Operations Director'],
  ['group_project_manager', 'Group Project Manager'],
  ['mep_project_manager', 'MEP Project Manager'],
  ['quantity_surveyor', 'Quantity Surveyor'],
  ['senior_site_supervisor', 'Senior Site Supervisor'],
  ['site_supervisor', 'Site Supervisor'],
  ['hr_manager', 'HR Manager'],
  ['hr_executive_reader', 'HR Executive'],
  ['administrative_executive', 'Administrative Executive']
] as const;

const RETIRED_ROLE_LABELS = [
  'Admin',
  'General Manager',
  'Operation Manager',
  'Project Manager',
  'Civil Engineer',
  'Civil Supervisor',
  'Store Keeper',
  'Accounts'
];

const CANONICAL_PERMISSIONS = [
  'users:manage',
  'users:read',
  'projects:manage',
  'projects:read',
  'audit:view',
  'dashboard:company',
  'dashboard:scoped',
  'reports:view',
  'reports:submit',
  'reports:approve',
  'inventory:view',
  'inventory:manage',
  'suppliers:manage',
  'documents:view',
  'documents:manage',
  'financial:view'
] as const;

interface SeededAccount {
  email: string;
  password: string;
  projectId: string;
  projectCode: string;
}

interface LoginResult {
  accessToken: string;
  userId: string;
}

function seedAccount(role?: string, projectId?: string): SeededAccount {
  const args = ['-m', 'tests.browser_fixtures', 'seed'];
  if (role) args.push('--role', role);
  if (projectId) args.push('--project-id', projectId);
  return JSON.parse(
    execFileSync(PYTHON_BIN, args, { cwd: BACKEND_DIR, encoding: 'utf8' })
  ) as SeededAccount;
}

function seedProjectAccounts(...roles: string[]): SeededAccount[] {
  const args = ['-m', 'tests.browser_fixtures', 'seed-group'];
  for (const role of roles) args.push('--role', role);
  return JSON.parse(
    execFileSync(PYTHON_BIN, args, { cwd: BACKEND_DIR, encoding: 'utf8' })
  ) as SeededAccount[];
}

async function signIn(
  page: Page,
  account: Pick<SeededAccount, 'email' | 'password'>
): Promise<LoginResult> {
  await page.goto('/login');
  await page.getByLabel('Email', { exact: true }).fill(account.email);
  await page.getByLabel('Password', { exact: true }).fill(account.password);
  await page.getByRole('button', { name: 'Continue' }).click();

  const code = (await page.getByText(/^Development code:/).innerText()).match(/\d{6}/)?.[0];
  if (!code) throw new Error('The test API did not expose the verification code.');

  await page.getByLabel('Verification code').fill(code);
  const verified = page.waitForResponse(
    (response) =>
      new URL(response.url()).pathname === '/api/v1/auth/verify-otp' &&
      response.request().method() === 'POST'
  );
  await page.getByRole('button', { name: 'Verify and sign in' }).click();
  const response = await verified;
  expect(response.status()).toBe(200);
  const body = (await response.json()) as { access_token: string; user: { id: string } };
  await expect(page).not.toHaveURL(/\/login$/);
  return { accessToken: body.access_token, userId: body.user.id };
}

test('changing a password ends the current browser session and requires a fresh sign-in', async ({ page }) => {
  const account = seedAccount();
  await signIn(page, account);
  await page.goto('/change-password');
  const updatedPassword = 'Synthetic-Password-98#';
  await page.getByLabel('Current password', { exact: true }).fill(account.password);
  await page.getByLabel('New password', { exact: true }).fill(updatedPassword);
  await page.getByLabel('Confirm new password', { exact: true }).fill(updatedPassword);
  await page.getByRole('button', { name: 'Update password' }).click();
  await expect(page).toHaveURL(/\/login$/);
  await signIn(page, { email: account.email, password: updatedPassword });
});

test('directors cannot open the Super Admin portal', async ({ page, request }) => {
  const director = await signIn(page, seedAccount());
  await page.goto('/super-admin');
  await expect(page).toHaveURL(/\/dashboard$/);
  await expect(page.getByRole('heading', { name: 'Super Admin', exact: true })).toHaveCount(0);
  const response = await request.get('/api/v1/super-admin/overview', {
    headers: { Authorization: `Bearer ${director.accessToken}` }
  });
  expect(response.status()).toBe(404);
});

async function assignUserToProject(
  request: APIRequestContext,
  accessToken: string,
  projectId: string,
  userEmail: string,
  roleInProject: string
): Promise<void> {
  const headers = { Authorization: `Bearer ${accessToken}` };
  const usersResponse = await request.get('/api/v1/users', {
    params: { email: userEmail },
    headers
  });
  expect(usersResponse.status()).toBe(200);
  const usersPayload = (await usersResponse.json()) as { items: Array<{ id: string }> };
  expect(usersPayload.items).toHaveLength(1);

  const projectResponse = await request.get(`/api/v1/projects/${projectId}`, { headers });
  expect(projectResponse.status()).toBe(200);
  const projectPayload = (await projectResponse.json()) as { revision: number };

  const assignResponse = await request.post(`/api/v1/projects/${projectId}/members`, {
    headers,
    data: {
      user_id: usersPayload.items[0].id,
      role_in_project: roleInProject,
      expected_revision: projectPayload.revision
    }
  });
  expect(assignResponse.status()).toBe(201);
}

test('roles page and users roles endpoint expose the ten canonical roles and the HR permissions', async ({
  page
}) => {
  const director = seedAccount();
  const session = await signIn(page, director);

  await page.getByRole('link', { name: 'Roles & Permissions', exact: true }).click();
  await expect(page).toHaveURL(/\/roles$/);
  await expect(page.getByRole('link', { name: 'HR & Workforce' })).toHaveCount(1);
  await expect(
    page.getByRole('heading', { name: 'Roles & permissions', exact: true })
  ).toBeVisible();
  await expect(page.getByText(/Your account has 16 of \d+ listed permissions/)).toBeVisible();

  await expect(page.locator('main article')).toHaveCount(CANONICAL_ROLES.length);
  await expect(page.getByRole('cell', { name: 'hr:employees:read', exact: true })).toBeVisible();

  for (const [key, label] of CANONICAL_ROLES) {
    const card = page.locator('main article').filter({ has: page.getByText(key, { exact: true }) });
    await expect(card).toContainText(label);
  }

  const headerTexts = (await page.locator('thead th').allInnerTexts()).map((text) => text.trim());
  expect(headerTexts).toHaveLength(CANONICAL_ROLES.length + 1);
  for (const retiredLabel of RETIRED_ROLE_LABELS) {
    expect(headerTexts.some((header) => header === retiredLabel)).toBe(false);
  }

  await expect(
    page.locator('main input[type="checkbox"], main input[type="radio"], main [role="switch"]')
  ).toHaveCount(0);

  const rolesResponse = await page.request.get('/api/v1/users/roles', {
    headers: { Authorization: `Bearer ${session.accessToken}` }
  });
  expect(rolesResponse.status()).toBe(200);
  const rolesBody = (await rolesResponse.json()) as {
    items: Array<{ role: string; label: string; permissions: string[]; assignable: boolean }>;
  };
  expect(rolesBody.items.map((item) => item.role).sort()).toEqual(
    CANONICAL_ROLES.map(([key]) => key).sort()
  );
  const canonicalPermissionSet = new Set<string>(CANONICAL_PERMISSIONS);
  for (const item of rolesBody.items) {
    expect(
      item.permissions.every(
        (permission) =>
          canonicalPermissionSet.has(permission) ||
          (item.role.startsWith('hr_') && permission.startsWith('hr:'))
      )
    ).toBe(true);
  }
  const directorHrDirectory = await page.request.get('/api/v1/hr/employees', {
    headers: { Authorization: `Bearer ${session.accessToken}` }
  });
  expect(directorHrDirectory.status()).toBe(403);
});

test('HR Manager cannot administer accounts while Managing Director sends expected_updated_at on role change', async ({
  browser
}) => {
  const [director, hrManager, siteSupervisor] = seedProjectAccounts(
    'managing_director', 'hr_manager', 'site_supervisor'
  );

  const hrContext = await browser.newContext();
  try {
    const hrPage = await hrContext.newPage();
    const hrSession = await signIn(hrPage, hrManager);
    const hrHeaders = { Authorization: `Bearer ${hrSession.accessToken}` };

    const rolesPromise = hrPage.waitForResponse(
      (response) => new URL(response.url()).pathname === '/api/v1/users/roles'
    );
    await hrPage.getByRole('link', { name: 'Users', exact: true }).click();
    await expect(hrPage).toHaveURL(/\/admin\/users$/);
    const rolesRes = await rolesPromise;
    expect(rolesRes.status()).toBe(200);

    await expect(hrPage.getByRole('button', { name: 'Create user' })).toHaveCount(0);

    const privilegedAccountEmail = `forbidden-director-${Date.now()}@example.com`;
    const forbiddenAssignment = await hrPage.request.post('/api/v1/users', {
      headers: hrHeaders,
      data: {
        email: privilegedAccountEmail,
        temporary_password: 'BrowserFixture!2027',
        full_name: 'Forbidden HR account creation',
        role: 'site_supervisor',
        employee_code: `DENY-${Date.now()}`,
        phone: '5550124'
      }
    });
    expect(forbiddenAssignment.status()).toBe(403);
    const forbiddenUsers = await hrPage.request.get('/api/v1/users', {
      headers: hrHeaders,
      params: { email: privilegedAccountEmail }
    });
    expect((await forbiddenUsers.json()).items).toEqual([]);

    const privilegedImport = await hrPage.request.get('/api/v1/imports/templates/projects', {
      headers: hrHeaders
    });
    expect(privilegedImport.status()).toBe(403);

    const searchInput = hrPage.getByPlaceholder('Search', { exact: true });
    await searchInput.fill(siteSupervisor.email);
    const target = hrPage.getByRole('row').filter({ hasText: siteSupervisor.email });
    await expect(target).toBeVisible();
    await expect(target.getByRole('button', { name: 'Change role' })).toHaveCount(0);
    await expect(target.getByRole('button', { name: 'Deactivate' })).toHaveCount(0);
  } finally {
    await hrContext.close();
  }

  const directorContext = await browser.newContext();
  try {
    const directorPage = await directorContext.newPage();
    const directorSession = await signIn(directorPage, director);
    const directorHeaders = { Authorization: `Bearer ${directorSession.accessToken}` };
    const targetBefore = await directorPage.request.get('/api/v1/users', {
      headers: directorHeaders,
      params: { email: siteSupervisor.email }
    });
    expect(targetBefore.status()).toBe(200);
    const beforeUser = (
      (await targetBefore.json()) as {
        items: Array<{ id: string; updated_at: string }>;
      }
    ).items[0];
    expect(beforeUser).toBeDefined();
    await directorPage.getByRole('link', { name: 'Users', exact: true }).click();
    await directorPage.getByPlaceholder('Search', { exact: true }).fill(siteSupervisor.email);

    const targetRow = directorPage.getByRole('row').filter({ hasText: siteSupervisor.email });
    await expect(targetRow).toBeVisible();
    await targetRow.getByRole('button', { name: 'Change role' }).click();
    await targetRow
      .getByRole('combobox', { name: /New role/ })
      .selectOption('senior_site_supervisor');

    const patchRequestPromise = directorPage.waitForRequest(
      (request) =>
        request.method() === 'PATCH' && new URL(request.url()).pathname.startsWith('/api/v1/users/')
    );
    const patchResponsePromise = directorPage.waitForResponse(
      (response) =>
        response.request().method() === 'PATCH' &&
        new URL(response.url()).pathname.startsWith('/api/v1/users/')
    );

    await targetRow.getByRole('button', { name: 'Save role' }).click();

    const patchRequest = await patchRequestPromise;
    const patchPayload = patchRequest.postDataJSON() as {
      role?: string;
      expected_updated_at?: string;
    };
    expect(patchPayload.role).toBe('senior_site_supervisor');
    expect(typeof patchPayload.expected_updated_at).toBe('string');
    expect(patchPayload.expected_updated_at?.length).toBeGreaterThan(0);

    const patchResponse = await patchResponsePromise;
    expect(patchResponse.status()).toBe(200);
    await expect(targetRow.getByRole('cell', { name: /Senior Site Supervisor/ })).toBeVisible();

    const stale = await directorPage.request.patch(`/api/v1/users/${beforeUser.id}`, {
      headers: directorHeaders,
      data: { role: 'site_supervisor', expected_updated_at: beforeUser.updated_at }
    });
    expect(stale.status()).toBe(409);
    const afterStale = await directorPage.request.get('/api/v1/users', {
      headers: directorHeaders,
      params: { email: siteSupervisor.email }
    });
    expect((await afterStale.json()).items).toEqual([
      expect.objectContaining({ id: beforeUser.id, role: 'senior_site_supervisor' })
    ]);
  } finally {
    await directorContext.close();
  }
});

test('quantity_surveyor submits daily reports via report-options without reports:view or projects list', async ({
  browser
}) => {
  const [director, qs] = seedProjectAccounts('managing_director', 'quantity_surveyor');

  const setupContext = await browser.newContext();
  try {
    const setupPage = await setupContext.newPage();
    const session = await signIn(setupPage, director);
    await assignUserToProject(
      setupPage.request,
      session.accessToken,
      director.projectId,
      qs.email,
      'quantity_surveyor'
    );
  } finally {
    await setupContext.close();
  }

  const qsContext = await browser.newContext();
  try {
    const qsPage = await qsContext.newPage();
    const apiPaths: string[] = [];
    qsPage.on('request', (request) => {
      const { pathname } = new URL(request.url());
      if (pathname.startsWith('/api/v1/')) apiPaths.push(pathname);
    });

    await signIn(qsPage, qs);
    await expect(qsPage.getByRole('link', { name: 'Projects', exact: true })).toHaveCount(0);

    await qsPage.getByRole('link', { name: 'Reports', exact: true }).click();
    await expect(qsPage).toHaveURL(/\/reports\/daily$/);
    await expect.poll(() => apiPaths).toContain('/api/v1/reports/project-options');
    expect(apiPaths).not.toContain('/api/v1/projects');

    const projectSelect = qsPage.getByRole('combobox', { name: 'Project', exact: true });
    await expect(projectSelect.locator(`option[value="${director.projectId}"]`)).toHaveCount(1);
    await projectSelect.selectOption(director.projectId);

    await qsPage.getByLabel('Work area / location').fill('Block B Basement');
    await qsPage.getByLabel('Weather').fill('Sunny');
    await qsPage.getByLabel('Work completed').fill('Measured concrete pours and rebar quantities.');
    await qsPage.getByLabel('Next-day plan').fill('Continue BOQ verification for level 1.');
    await qsPage.getByLabel('Site visitors').fill('None');
    await qsPage.getByLabel('Subcontractors').fill('MEP subcontractor');
    await qsPage.getByLabel('WIR number').fill('GAR-WIR-2026-011');
    await qsPage.getByPlaceholder('Trade', { exact: true }).fill('Masons');

    await qsPage.getByRole('button', { name: 'Save draft' }).click();
    await expect(qsPage.getByText('Daily report draft saved.', { exact: true })).toBeVisible();

    await qsPage.getByRole('button', { name: 'Submit report' }).click();
    await expect(
      qsPage.getByRole('status').filter({ hasText: /^Daily report .+ submitted\.$/ })
    ).toBeVisible();
  } finally {
    await qsContext.close();
  }
});

test('supervisors navigate to supervisor updates via report-options including mobile navigation', async ({
  browser
}) => {
  const [director, seniorSupervisor, siteSupervisor] = seedProjectAccounts(
    'managing_director', 'senior_site_supervisor', 'site_supervisor'
  );

  const setupContext = await browser.newContext();
  try {
    const setupPage = await setupContext.newPage();
    const session = await signIn(setupPage, director);
    await assignUserToProject(
      setupPage.request,
      session.accessToken,
      director.projectId,
      seniorSupervisor.email,
      'senior_site_supervisor'
    );
  } finally {
    await setupContext.close();
  }

  const mobileContext = await browser.newContext({ viewport: { width: 390, height: 844 } });
  try {
    const mobilePage = await mobileContext.newPage();
    const apiPaths: string[] = [];
    mobilePage.on('request', (request) => {
      const { pathname } = new URL(request.url());
      if (pathname.startsWith('/api/v1/')) apiPaths.push(pathname);
    });

    await signIn(mobilePage, seniorSupervisor);
    await mobilePage.getByRole('button', { name: 'Open navigation' }).click();
    const mobileDrawer = mobilePage
      .locator('aside')
      .filter({ has: mobilePage.getByRole('button', { name: 'Close navigation' }) });
    const reportsDrawerLink = mobileDrawer.getByRole('link', { name: 'Reports', exact: true });
    await expect(reportsDrawerLink).toHaveAttribute('href', '/reports/supervisor-update');
    await reportsDrawerLink.click();

    await expect(mobilePage).toHaveURL(/\/reports\/supervisor-update$/);
    await expect.poll(() => apiPaths).toContain('/api/v1/reports/project-options');
    expect(apiPaths).not.toContain('/api/v1/projects');

    const projectSelect = mobilePage.getByRole('combobox', { name: 'Project', exact: true });
    await expect(projectSelect.locator(`option[value="${director.projectId}"]`)).toHaveCount(1);
    await projectSelect.selectOption(director.projectId);

    await mobilePage.getByLabel('Work location').fill('Tower A Level 2');
    await mobilePage.getByLabel('Progress notes').fill('Completed slab formwork check.');
    await mobilePage.getByLabel('Required notes').fill('Rebar spacer inspection before pour.');
    await mobilePage.getByRole('button', { name: 'Submit update' }).click();
    await expect(mobilePage.getByText('Site update submitted.', { exact: true })).toBeVisible();
  } finally {
    await mobileContext.close();
  }

  const supervisorContext = await browser.newContext();
  try {
    const supervisorPage = await supervisorContext.newPage();
    const apiPaths: string[] = [];
    supervisorPage.on('request', (request) => {
      const { pathname } = new URL(request.url());
      if (pathname.startsWith('/api/v1/')) apiPaths.push(pathname);
    });

    await signIn(supervisorPage, siteSupervisor);
    await supervisorPage.getByRole('link', { name: 'Reports', exact: true }).click();
    await expect(supervisorPage).toHaveURL(/\/reports\/supervisor-update$/);
    await expect.poll(() => apiPaths).toContain('/api/v1/reports/project-options');
    expect(apiPaths).not.toContain('/api/v1/projects');
    await expect(
      supervisorPage
        .getByRole('combobox', { name: 'Project', exact: true })
        .locator(`option[value="${director.projectId}"]`)
    ).toHaveCount(1);
  } finally {
    await supervisorContext.close();
  }
});

test('administrative_executive sees aggregate dashboard and read-only documents', async ({
  browser
}) => {
  const adminExec = seedAccount('administrative_executive');
  const context = await browser.newContext();
  try {
    const page = await context.newPage();
    const apiPaths: string[] = [];
    page.on('request', (request) => {
      const { pathname } = new URL(request.url());
      if (pathname.startsWith('/api/v1/')) apiPaths.push(pathname);
    });

    const summaryPromise = page.waitForResponse(
      (response) =>
        new URL(response.url()).pathname === '/api/v1/dashboard/summary' &&
        response.request().method() === 'GET'
    );
    await signIn(page, adminExec);

    const summaryResponse = await summaryPromise;
    expect(summaryResponse.status()).toBe(200);
    const summary = (await summaryResponse.json()) as { recent_activity: unknown[] };
    expect(summary.recent_activity).toEqual([]);

    await expect(page.getByText('Active projects', { exact: true })).toBeVisible();
    await expect(page.getByText('Pending reports', { exact: true })).toBeVisible();
    await expect(page.getByText('Approved reports', { exact: true })).toBeVisible();
    await expect(page.getByText('Pending documents', { exact: true })).toBeVisible();
    await expect(page.getByText('Unread alerts', { exact: true })).toBeVisible();
    await expect(page.getByText('No recent activity', { exact: true })).toBeVisible();

    await page.getByRole('link', { name: 'Documents', exact: true }).click();
    await expect(page).toHaveURL(/\/documents$/);
    await expect.poll(() => apiPaths).toContain('/api/v1/documents/project-options');
    expect(apiPaths).not.toContain('/api/v1/projects');
    await expect(page.getByRole('button', { name: 'Upload' })).toHaveCount(0);
    await expect(page.getByLabel('Document title')).toHaveCount(0);
  } finally {
    await context.close();
  }
});

test('HR Manager creates a draft in the workspace and it persists across reload', async ({
  page
}) => {
  const account = seedAccount('hr_manager');
  await signIn(page, account);
  await page.getByRole('link', { name: 'HR & Workforce', exact: true }).click();
  await page.getByRole('button', { name: 'Directory & Org' }).click();
  const code = `CHROME-HR-${Date.now()}`;
  await page.getByLabel('Employee code', { exact: true }).fill(code);
  await page.getByLabel('First name', { exact: true }).fill('Synthetic');
  await page.getByLabel('Last name', { exact: true }).fill('Workforce');
  await page.getByRole('button', { name: 'Create employee' }).click();
  await expect(page.getByText(`Employee ${code} created.`)).toBeVisible();
  await page.reload();
  await page.getByRole('button', { name: 'Directory & Org' }).click();
  await page.getByLabel('Search employees').fill(code);
  const row = page.getByRole('row').filter({ hasText: code });
  await expect(row).toContainText('Synthetic Workforce');
  await expect(row).toContainText('draft');
  await page.getByRole('link', { name: 'My HR', exact: true }).click();
  await expect(page.getByText(/not linked|no employee/i).first()).toBeVisible();
});

test('independent HR Managers approve and apply an effective-dated employment change', async ({
  page,
  browser,
  request
}) => {
  const creator = await signIn(page, seedAccount('hr_manager'));
  const code = `EMP-CHANGE-${Date.now()}`;
  const headers = { Authorization: `Bearer ${creator.accessToken}` };
  const created = await request.post('/api/v1/hr/employees', {
    headers,
    data: {
      employee_code: code,
      first_name: 'Synthetic',
      last_name: 'Transfer',
      employment_status: 'active',
      join_date: '2025-01-01',
      work_location: 'Original site'
    }
  });
  expect(created.status()).toBe(201);
  const employee = (await created.json()) as { id: string; record_revision: number };
  const employeePath = `/api/v1/hr/employees/${employee.id}`;
  const effective = new Intl.DateTimeFormat('sv-SE', { timeZone: 'Asia/Qatar' }).format(new Date());

  async function openEmployee(target: Page) {
    await target.getByRole('link', { name: 'HR & Workforce', exact: true }).click();
    await target.getByRole('button', { name: 'Directory & Org' }).click();
    await target.getByLabel('Search employees').fill(code);
    await target
      .getByRole('row')
      .filter({ hasText: code })
      .getByRole('button', { name: 'Inspect' })
      .click();
    await target.getByText('Reviewed employment changes', { exact: true }).click();
  }

  await openEmployee(page);
  await page.getByLabel('New work location (optional)').fill('Synthetic new site');
  await page.getByLabel('Effective date', { exact: true }).fill(effective);
  await page.getByLabel('Employment change reason').fill('Synthetic site transfer');
  await page.getByRole('button', { name: 'Propose employment change' }).click();
  await expect(page.getByRole('heading', { name: /Transfer .* proposed/ })).toBeVisible();
  await expect(page.getByRole('button', { name: 'Approve employment change' })).toHaveCount(0);

  const reviewerContext = await browser.newContext();
  try {
    const reviewerPage = await reviewerContext.newPage();
    const reviewer = await signIn(reviewerPage, seedAccount('hr_manager'));
    await openEmployee(reviewerPage);
    await reviewerPage.getByRole('button', { name: 'Approve employment change' }).click();
    await expect(reviewerPage.getByRole('heading', { name: /Transfer .* approved/ })).toBeVisible();
    await reviewerPage.reload();
    await reviewerPage.getByRole('button', { name: 'Directory & Org' }).click();
    await reviewerPage.getByText('Due employment changes', { exact: true }).click();
    const dueRow = reviewerPage.getByRole('list', { name: 'Approved changes due' })
      .getByRole('listitem').filter({ hasText: code });
    await expect(dueRow).toContainText(effective);
    await dueRow.getByRole('button', { name: 'Inspect employee' }).click();
    await reviewerPage.getByText('Reviewed employment changes', { exact: true }).click();
    let current = await request.get(employeePath, { headers });
    expect(await current.json()).toMatchObject({
      work_location: 'Original site',
      record_revision: employee.record_revision
    });
    await reviewerPage.getByRole('button', { name: 'Apply due employment change' }).click();
    await expect(reviewerPage.getByRole('heading', { name: /Transfer .* applied/ })).toBeVisible();
    await expect(dueRow).toHaveCount(0);
    current = await request.get(employeePath, { headers });
    expect(await current.json()).toMatchObject({
      work_location: 'Synthetic new site',
      record_revision: employee.record_revision + 1
    });
    await reviewerPage.reload();
    await openEmployee(reviewerPage);
    await expect(reviewerPage.getByRole('heading', { name: /Transfer .* applied/ })).toBeVisible();

    const cli = (token: string, action: string, args: string[]) =>
      JSON.parse(
        execFileSync(
          PYTHON_BIN,
          [
            '-m',
            'scripts.garrisonctl',
            'hr',
            'employees',
            'changes',
            action,
            ...(action === 'due' ? [] : ['--employee-id', employee.id]),
            ...args,
            '--json'
          ],
          {
            cwd: BACKEND_DIR,
            encoding: 'utf8',
            env: {
              ...env,
              GARRISON_API_BASE_URL: 'http://127.0.0.1:8425',
              GARRISON_ENVIRONMENT: 'test',
              GARRISON_ACCESS_TOKEN: token
            }
          }
        )
      ).data;
    const confirm = (token: string, action: string, args: string[]) => {
      const plan = cli(token, action, [...args, '--dry-run']);
      return cli(token, action, [...args, '--apply', '--expect', plan.plan_sha256]);
    };
    const temp = mkdtempSync(join(tmpdir(), 'garrison-employment-test-'));
    try {
      const file = join(temp, 'proposal.json');
      writeFileSync(
        file,
        JSON.stringify({
          change_type: 'category_amendment',
          effective_date: effective,
          reason: 'Synthetic category amendment',
          updates: { employment_category: 'contract' }
        }),
        { mode: 0o600 }
      );
      const amendment = confirm(creator.accessToken, 'propose', ['--file', file]);
      expect(amendment.status).toBe('proposed');
      const changeId = ['--change-id', amendment.id];
      expect(
        confirm(reviewer.accessToken, 'decide', [...changeId, '--decision', 'approved']).status
      ).toBe('approved');
      expect(cli(reviewer.accessToken, 'due', []).items).toEqual(
        expect.arrayContaining([expect.objectContaining({ id: amendment.id, revision_matches: true })])
      );
      expect(confirm(reviewer.accessToken, 'apply', changeId).status).toBe('applied');
      expect(cli(reviewer.accessToken, 'list', []).items).toEqual(
        expect.arrayContaining([expect.objectContaining({ id: amendment.id, status: 'applied' })])
      );
      const applied = await request.get(employeePath, { headers });
      expect(await applied.json()).toMatchObject({
        employment_category: 'contract',
        record_revision: employee.record_revision + 2
      });
    } finally {
      rmSync(temp, { recursive: true, force: true });
    }
    async function uploadContract(title: string, expiryDate: string) {
      const uploaded = await request.post('/api/v1/hr/documents', {
        headers,
        multipart: {
          title,
          document_type: 'contract',
          category: 'confidential',
          employee_id: employee.id,
          expiry_date: expiryDate,
          file: {
            name: 'synthetic-contract.pdf',
            mimeType: 'application/pdf',
            buffer: Buffer.from('%PDF-1.4\n1 0 obj<<>>endobj\n%%EOF')
          }
        }
      });
      expect(uploaded.status()).toBe(201);
      const documentId = (await uploaded.json()).id as string;
      const evidence = await request.post(
        `/api/v1/hr/documents/${documentId}/versions/1/decision`,
        {
          headers: { Authorization: `Bearer ${reviewer.accessToken}` },
          data: { decision: 'approve' }
        }
      );
      expect(evidence.status()).toBe(200);
      return documentId;
    }
    const shiftDate = (days: number) =>
      new Date(Date.parse(`${effective}T00:00:00Z`) + days * 86400000).toISOString().slice(0, 10);
    const currentContract = await uploadContract('Previous synthetic contract', shiftDate(-1));
    const renewalExpiry = shiftDate(180);
    const renewalContract = await uploadContract('Renewed synthetic contract', renewalExpiry);
    await page.reload();
    await openEmployee(page);
    await page.getByLabel('Change type').selectOption('contract_renewal');
    await page.getByLabel('Current contract version').selectOption(`${currentContract}:1`);
    await page.getByLabel('Renewal contract version').selectOption(`${renewalContract}:1`);
    await page.getByLabel('Effective date', { exact: true }).fill(effective);
    await page.getByLabel('Employment change reason').fill('Synthetic contract renewal');
    await page.getByRole('button', { name: 'Propose employment change' }).click();
    await expect(page.getByRole('heading', { name: /Contract renewal .* proposed/ })).toBeVisible();
    await reviewerPage.reload();
    await openEmployee(reviewerPage);
    const renewal = reviewerPage
      .getByRole('article')
      .filter({ hasText: /Contract renewal .* proposed/ });
    await expect(
      renewal.getByRole('button', { name: 'Open renewal contract evidence · version 1' })
    ).toBeVisible();
    await renewal.getByRole('button', { name: 'Approve employment change' }).click();
    const approvedRenewal = reviewerPage
      .getByRole('article')
      .filter({ hasText: /Contract renewal .* approved/ });
    await approvedRenewal.getByRole('button', { name: 'Apply due employment change' }).click();
    await expect(
      reviewerPage.getByRole('heading', { name: /Contract renewal .* applied/ })
    ).toBeVisible();
    const history = await request.get(`${employeePath}/history`, { headers });
    expect((await history.json()).items).toEqual(
      expect.arrayContaining([
        expect.objectContaining({
          change_type: 'contract_renewal',
          new_snapshot: expect.objectContaining({
            renewal_contract_document_id: renewalContract,
            renewal_contract_version: 1,
            contract_end_date: renewalExpiry
          })
        })
      ])
    );
    const latest = await request.get(employeePath, { headers });
    const nextDate = new Date(Date.parse(effective) + 86_400_000).toISOString().slice(0, 10);
    const scheduled = await request.post(`${employeePath}/employment-changes`, {
      headers,
      data: {
        change_type: 'transfer',
        effective_date: nextDate,
        employee_revision: (await latest.json()).record_revision,
        reason: 'Synthetic future transfer',
        updates: { work_location: 'Future site' }
      }
    });
    expect(scheduled.status()).toBe(201);
    const scheduledId = (await scheduled.json()).id as string;
    const approvedSchedule = await request.post(
      `${employeePath}/employment-changes/${scheduledId}/decision`,
      {
        headers: { Authorization: `Bearer ${reviewer.accessToken}` },
        data: { decision: 'approved' }
      }
    );
    expect(approvedSchedule.status()).toBe(200);
    expect(() =>
      cli(reviewer.accessToken, 'apply', ['--change-id', scheduledId, '--dry-run'])
    ).toThrow();
    await reviewerPage.reload();
    await openEmployee(reviewerPage);
    const scheduledRow = reviewerPage
      .getByRole('article').filter({ hasText: 'Synthetic future transfer' });
    await expect(scheduledRow.getByText(`Scheduled for ${nextDate}.`)).toBeVisible();
    await expect(
      scheduledRow.getByRole('button', { name: 'Apply due employment change' })
    ).toHaveCount(0);
  } finally {
    await reviewerContext.close();
  }
});

test('employees can open their own published payslip in My HR', async ({
  page,
  browser,
  request
}) => {
  const contractor = seedAccount('quantity_surveyor');
  const colleague = seedAccount('quantity_surveyor');
  const maker = await signIn(page, seedAccount('hr_manager'));
  const directorContext = await browser.newContext();
  const reviewerContext = await browser.newContext();
  const ownerContext = await browser.newContext();
  const otherContext = await browser.newContext();
  try {
    const director = await signIn(await directorContext.newPage(), seedAccount());
    const reviewer = await signIn(await reviewerContext.newPage(), seedAccount('hr_manager'));
    const ownerPage = await ownerContext.newPage();
    const owner = await signIn(ownerPage, contractor);
    const otherPage = await otherContext.newPage();
    const other = await signIn(otherPage, colleague);
    async function link(account: SeededAccount, session: LoginResult) {
      const employee = await request.post('/api/v1/hr/employees', {
        headers: { Authorization: `Bearer ${maker.accessToken}` },
        data: {
          employee_code: `PAYSLIP-${session.userId.slice(0, 12)}`,
          first_name: 'Synthetic',
          last_name: 'Payslip',
          employment_status: 'active',
          join_date: '2025-01-01',
          work_email: account.email
        }
      });
      expect(employee.status()).toBe(201);
      const employeeId = (await employee.json()).id as string;
      const linked = await request.post(`/api/v1/hr/employees/${employeeId}/link-account`, {
        headers: { Authorization: `Bearer ${director.accessToken}` },
        data: { user_id: session.userId }
      });
      expect(linked.status()).toBe(200);
      return employeeId;
    }
    const employeeId = await link(contractor, owner);
    await link(colleague, other);
    await ownerPage.getByRole('link', { name: 'My HR', exact: true }).click();
    await ownerPage.getByText('My payslips', { exact: true }).click();
    await expect(ownerPage.getByText('No payslips have been published for you.')).toBeVisible();
    const seedOutput = execFileSync(
      PYTHON_BIN,
      [
        '-m',
        'tests.browser_fixtures',
        'seed-employee-payslip',
        '--employee-id',
        employeeId,
        '--maker-id',
        maker.userId,
        '--reviewer-id',
        reviewer.userId
      ],
      { cwd: BACKEND_DIR, encoding: 'utf8' }
    ).trim();
    const { runId } = JSON.parse(seedOutput.slice(seedOutput.lastIndexOf('\n') + 1)) as {
      runId: string;
    };
    expect(runId).toBeTruthy();
    await ownerPage.reload();
    await ownerPage.getByText('My payslips', { exact: true }).click();
    await ownerPage
      .getByRole('button', { name: 'Open payslip for 2025-01-01 to 2025-01-31' })
      .click();
    const slip = ownerPage
      .getByRole('article')
      .filter({ hasText: 'Payslip for 2025-01-01 to 2025-01-31' });
    await expect(slip.getByText('LKR 100.05', { exact: true })).toBeVisible();
    await expect(slip.getByText('LKR 10.01', { exact: true })).toBeVisible();
    await expect(slip.getByText('LKR 90.04', { exact: true })).toBeVisible();
    await slip.getByRole('button', { name: 'Close payslip' }).click();
    await expect(slip).toHaveCount(0);

    await otherPage.getByRole('link', { name: 'My HR', exact: true }).click();
    await otherPage.getByText('My payslips', { exact: true }).click();
    await expect(otherPage.getByText('No payslips have been published for you.')).toBeVisible();
    const forbidden = await request.get(`/api/v1/hr/me/payslips/${runId}`, {
      headers: { Authorization: `Bearer ${other.accessToken}` }
    });
    expect(forbidden.status()).toBe(404);
    const cli = JSON.parse(
      execFileSync(
        PYTHON_BIN,
        ['-m', 'scripts.garrisonctl', 'hr', 'payslip', 'show', '--run-id', runId, '--json'],
        {
          cwd: BACKEND_DIR,
          encoding: 'utf8',
          env: {
            ...env,
            GARRISON_API_BASE_URL: 'http://127.0.0.1:8425',
            GARRISON_ENVIRONMENT: 'test',
            GARRISON_ACCESS_TOKEN: owner.accessToken
          }
        }
      )
    );
    expect(cli.data).toMatchObject({ run_id: runId, currency: 'LKR', net: '90.04' });
  } finally {
    await Promise.all([
      directorContext.close(),
      reviewerContext.close(),
      ownerContext.close(),
      otherContext.close()
    ]);
  }
});

test('HR issues a salary confirmation from approved compensation', async ({ page, browser, request }) => {
  const maker = await signIn(page, seedAccount('hr_manager'));
  const reviewerContext = await browser.newContext();
  const workerContext = await browser.newContext();
  const directorContext = await browser.newContext();
  try {
    const reviewerPage = await reviewerContext.newPage();
    const reviewer = await signIn(reviewerPage, seedAccount('hr_manager'));
    const worker = seedAccount('quantity_surveyor');
    const workerPage = await workerContext.newPage();
    const owner = await signIn(workerPage, worker);
    const director = await signIn(await directorContext.newPage(), seedAccount());
    const code = `SALARY-${Date.now()}`;
    const headers = { Authorization: `Bearer ${maker.accessToken}` };
    const employee = await request.post('/api/v1/hr/employees', {
      headers, data: {
        employee_code: code, first_name: 'Synthetic', last_name: 'Salary Letter Recipient',
        work_email: worker.email, employment_status: 'active'
      }
    });
    expect(employee.status()).toBe(201);
    const employeeId = (await employee.json()).id as string;
    expect((await request.post(`/api/v1/hr/employees/${employeeId}/link-account`, {
      headers: { Authorization: `Bearer ${director.accessToken}` },
      data: { user_id: owner.userId }
    })).status()).toBe(200);
    const term = await request.post('/api/v1/hr/compensation', {
      headers, data: {
        employee_id: employeeId, effective_from: '2022-01-01', currency: 'LKR',
        base_salary: '23456.78', pay_frequency: 'monthly'
      }
    });
    expect(term.status()).toBe(201);
    const termId = (await term.json()).id as string;
    expect((await request.post(`/api/v1/hr/compensation/${termId}/decision`, {
      headers: { Authorization: `Bearer ${reviewer.accessToken}` },
      data: { decision: 'approve' }
    })).status()).toBe(200);
    const template = await request.post('/api/v1/hr/letter-templates', {
      headers, data: {
        code, name: 'Salary confirmation example', letter_type: 'salary_confirmation',
        subject_template: 'Compensation for {full_name}',
        body_template: 'Approved base salary {salary_currency} {base_salary} ({pay_frequency}).'
      }
    });
    expect(template.status()).toBe(201);
    const templateId = (await template.json()).id as string;
    async function selectEmployee(target: Page) {
      await target.getByRole('link', { name: 'HR & Workforce', exact: true }).click();
      await target.getByRole('button', { name: 'Policies & Requests' }).click();
      await target.getByLabel('Find employee by name or code').fill(code);
      await target.getByRole('button', { name: 'Find employee', exact: true }).click();
      await target.getByRole('combobox', { name: 'Letter employee', exact: true }).selectOption(employeeId);
    }
    await selectEmployee(page);
    await page.getByRole('combobox', { name: 'Letter template', exact: true }).selectOption(templateId);
    await expect(page.getByLabel('base_salary', { exact: true })).toHaveCount(0);
    await page.getByRole('button', { name: 'Preview letter' }).click();
    const text = 'Approved base salary LKR 23456.78 (monthly).';
    await expect(page.getByText(text, { exact: true })).toBeVisible();
    await page.getByRole('button', { name: 'Save draft for independent review' }).click();
    await expect(page.getByText('Letter draft saved for review.')).toBeVisible();

    await selectEmployee(reviewerPage);
    await reviewerPage.getByRole('button', { name: /Salary confirmation example · draft/ }).click();
    await expect(reviewerPage.getByText(text, { exact: true })).toBeVisible();
    await reviewerPage.getByRole('button', { name: 'Approve and issue letter' }).click();
    await expect(reviewerPage.getByRole('button', { name: /Salary confirmation example · issued/ }))
      .toBeVisible();

    await workerPage.getByRole('link', { name: 'My HR', exact: true }).click();
    await workerPage.reload();
    await workerPage.getByRole('button', { name: /Salary confirmation example · issued/ }).click();
    await expect(workerPage.getByText(text, { exact: true })).toBeVisible();
  } finally {
    await Promise.all([reviewerContext.close(), workerContext.close(), directorContext.close()]);
  }
});

test('HR previews and retains a letter for independent issuance and employee retrieval', async ({
  page,
  browser,
  request
}) => {
  const session = await signIn(page, seedAccount('hr_manager'));
  const worker = seedAccount('quantity_surveyor');
  const code = `LETTER-${Date.now()}`;
  const employee = await request.post('/api/v1/hr/employees', {
    headers: { Authorization: `Bearer ${session.accessToken}` },
    data: {
      employee_code: code,
      first_name: 'Synthetic',
      last_name: 'Letter Employee',
      work_email: worker.email,
      employment_status: 'active'
    }
  });
  expect(employee.status()).toBe(201);
  const employeeId = (await employee.json()).id as string;
  const directorContext = await browser.newContext();
  const workerContext = await browser.newContext();
  const reviewerContext = await browser.newContext();
  try {
    const director = await signIn(await directorContext.newPage(), seedAccount());
    const workerPage = await workerContext.newPage();
    const linkedUser = await signIn(workerPage, worker);
    const link = await request.post(`/api/v1/hr/employees/${employeeId}/link-account`, {
      headers: { Authorization: `Bearer ${director.accessToken}` },
      data: { user_id: linkedUser.userId }
    });
    expect(link.status()).toBe(200);
    await page.getByRole('link', { name: 'HR & Workforce', exact: true }).click();
    await page.getByRole('button', { name: 'Policies & Requests' }).click();
    await page.getByLabel('Template code', { exact: true }).fill(code);
    await page.getByLabel('Template name', { exact: true }).fill('Employment verification');
    const subject = page.getByLabel('Letter subject template');
    await subject.fill('Confirmation for {full_name');
    await page
      .getByLabel('Letter body template')
      .fill('Employee {employee_code} requests {purpose}.');
    await page.getByRole('button', { name: 'Save letter template' }).click();
    await expect(page.getByText(/use named placeholders/i)).toBeVisible();
    await expect(page.getByLabel('Template code', { exact: true })).toHaveValue(code);
    await subject.fill('Confirmation for {full_name}');
    await page.getByRole('button', { name: 'Save letter template' }).click();
    await expect(page.getByText('Letter template saved.')).toBeVisible();

    await page.reload();
    await page.getByRole('button', { name: 'Policies & Requests' }).click();
    await page.getByRole('combobox', { name: 'Letter template', exact: true }).selectOption({
      label: `${code} · Employment verification`
    });
    await page.getByLabel('Find employee by name or code').fill(code);
    await page.getByRole('button', { name: 'Find employee', exact: true }).click();
    await page
      .getByRole('combobox', { name: 'Letter employee', exact: true })
      .selectOption(employeeId);
    await page.getByLabel('purpose', { exact: true }).fill('a <b>staff</b> record');
    await page.getByRole('button', { name: 'Preview letter' }).click();
    await expect(page.getByText('Confirmation for Synthetic Letter Employee')).toBeVisible();
    await expect(page.getByText(`Employee ${code} requests a <b>staff</b> record.`)).toBeVisible();
    await page.getByRole('button', { name: 'Save draft for independent review' }).click();
    await expect(page.getByText('Letter draft saved for review.')).toBeVisible();
    await page.getByRole('button', { name: /Employment verification · draft/ }).click();
    await expect(page.getByRole('button', { name: 'Approve and issue letter' })).toHaveCount(0);
    await workerPage.getByRole('link', { name: 'My HR', exact: true }).click();
    await expect(workerPage.getByText('No HR letters are available.')).toBeVisible();
    const requestSubject = `Employment letter ${code}`;
    await workerPage.getByPlaceholder('Subject', { exact: true }).fill(requestSubject);
    await workerPage.getByRole('button', { name: 'Submit request', exact: true }).click();
    await expect(
      workerPage.getByText('HR service request submitted.', { exact: true })
    ).toBeVisible();

    const reviewer = await reviewerContext.newPage();
    await signIn(reviewer, seedAccount('hr_manager'));
    await reviewer.getByRole('link', { name: 'HR & Workforce', exact: true }).click();
    await reviewer.getByRole('button', { name: 'Policies & Requests' }).click();
    await reviewer.getByLabel('Find employee by name or code').fill(code);
    await reviewer.getByRole('button', { name: 'Find employee', exact: true }).click();
    await reviewer
      .getByRole('combobox', { name: 'Letter employee', exact: true })
      .selectOption(employeeId);
    await reviewer.getByRole('button', { name: /Employment verification · draft/ }).click();
    await expect(
      reviewer.getByText(`Employee ${code} requests a <b>staff</b> record.`)
    ).toBeVisible();
    await reviewer.getByRole('button', { name: 'Approve and issue letter' }).click();
    await expect(
      reviewer.getByRole('button', { name: /Employment verification · issued/ })
    ).toBeVisible();

    await workerPage.reload();
    await workerPage.getByRole('button', { name: /Employment verification · issued/ }).click();
    await expect(
      workerPage.getByText(`Employee ${code} requests a <b>staff</b> record.`)
    ).toBeVisible();
    await expect(workerPage.getByRole('button', { name: 'Approve and issue letter' })).toHaveCount(
      0
    );
    const runAsEmployee = (...args: string[]) =>
      JSON.parse(
        execFileSync(PYTHON_BIN, ['-m', 'scripts.garrisonctl', 'hr', 'letter', ...args, '--json'], {
          cwd: BACKEND_DIR,
          encoding: 'utf8',
          env: {
            ...env,
            GARRISON_API_BASE_URL: 'http://127.0.0.1:8425',
            GARRISON_ENVIRONMENT: 'test',
            GARRISON_ACCESS_TOKEN: linkedUser.accessToken
          }
        })
      );
    const letterId = runAsEmployee('list').data.items[0].id as string;
    expect(runAsEmployee('show', '--letter-id', letterId).data).toMatchObject({
      id: letterId,
      status: 'issued',
      body: `Employee ${code} requests a <b>staff</b> record.`
    });

    await page.reload();
    await page.getByRole('button', { name: 'Policies & Requests' }).click();
    const requestCard = page.getByText(requestSubject).locator('..');
    await requestCard.getByRole('button', { name: 'Start review' }).click();
    await requestCard.getByText('Attach issued letter', { exact: true }).click();
    await requestCard.getByLabel('Issued response letter').selectOption(letterId);
    await requestCard.getByRole('button', { name: 'Preview selected response letter' }).click();
    await expect(
      requestCard.getByText(`Employee ${code} requests a <b>staff</b> record.`)
    ).toBeVisible();
    await requestCard.getByRole('button', { name: 'Complete request' }).click();
    await expect(requestCard).toContainText('(completed)');
    await workerPage.reload();
    const completedRequest = workerPage.getByText(requestSubject).locator('..');
    await completedRequest.getByRole('button', { name: 'Open response letter' }).click();
    await expect(
      completedRequest.getByText(`Employee ${code} requests a <b>staff</b> record.`)
    ).toBeVisible();
    await completedRequest.getByRole('button', { name: /Reopen request/ }).click();
    await expect(
      workerPage.getByText('HR service request reopened.', { exact: true })
    ).toBeVisible();
    await workerPage.reload();
    await expect(
      completedRequest.getByRole('button', { name: 'Open response letter' })
    ).toBeVisible();
    const requests = await request.get('/api/v1/hr/me/requests', {
      headers: { Authorization: `Bearer ${linkedUser.accessToken}` }
    });
    const reopened = (await requests.json()).items.find(
      (row: { subject: string }) => row.subject === requestSubject
    );
    expect(reopened).toMatchObject({ status: 'open', generated_letter_id: letterId });
    const runRequest = (command: string, ...options: string[]) =>
      JSON.parse(
        execFileSync(
          PYTHON_BIN,
          [
            '-m',
            'scripts.garrisonctl',
            'hr',
            'request',
            command,
            '--request-id',
            reopened.id,
            ...options,
            '--json'
          ],
          {
            cwd: BACKEND_DIR,
            encoding: 'utf8',
            env: {
              ...env,
              GARRISON_API_BASE_URL: 'http://127.0.0.1:8425',
              GARRISON_ENVIRONMENT: 'test',
              GARRISON_ACCESS_TOKEN: session.accessToken
            }
          }
        )
      );
    expect(runRequest('status').data).toMatchObject({ id: reopened.id, status: 'open' });
    const startPlan = runRequest('start', '--dry-run').data;
    expect(runRequest('status').data.status).toBe('open');
    expect(runRequest('start', '--apply', '--expect', startPlan.plan_sha256).data).toMatchObject({
      status: 'in_review',
      assigned_to_id: session.userId
    });
    const completion = ['--letter-id', letterId];
    const completionPlan = runRequest('complete', ...completion, '--dry-run').data;
    expect(completionPlan.proposed.generated_letter_id).toBe(letterId);
    expect(JSON.stringify(completionPlan)).not.toContain('a <b>staff</b> record');
    expect(runRequest(
      'complete', ...completion, '--apply', '--expect', completionPlan.plan_sha256
    ).data).toMatchObject({
      status: 'completed',
      generated_letter_id: letterId
    });
  } finally {
    await Promise.all([directorContext.close(), workerContext.close(), reviewerContext.close()]);
  }
});

test('candidate CVs stay private through upload, independent review and download', async ({
  page,
  browser,
  request
}) => {
  const uploader = seedAccount('hr_manager');
  const session = await signIn(page, uploader);
  const code = `CV-${Date.now()}`;
  const create = await request.post('/api/v1/hr/candidates', {
    headers: { Authorization: `Bearer ${session.accessToken}` },
    data: { candidate_code: code, full_name: 'Synthetic CV Candidate' }
  });
  expect(create.status()).toBe(201);
  const candidateId = (await create.json()).id as string;
  await page.getByRole('link', { name: 'HR & Workforce', exact: true }).click();
  await page.getByRole('button', { name: 'Recruitment', exact: true }).click();
  await page.getByRole('combobox', { name: 'CV candidate' }).selectOption(candidateId);
  await page.getByLabel(/^CV file/).setInputFiles({
    name: 'candidate.pdf',
    mimeType: 'application/pdf',
    buffer: Buffer.from('%PDF-1.4\n1 0 obj<<>>endobj\n%%EOF')
  });
  await page.getByRole('button', { name: 'Upload CV', exact: true }).click();
  await expect(page.getByText('candidate.pdf · version 1 · pending')).toBeVisible();
  await expect(page.getByRole('button', { name: 'Approve CV', exact: true })).toHaveCount(0);
  await expect(page.getByRole('button', { name: 'Download for review' })).toHaveCount(0);

  const reviewContext = await browser.newContext();
  try {
    const reviewer = await reviewContext.newPage();
    await signIn(reviewer, seedAccount('hr_manager', uploader.projectId));
    await reviewer.getByRole('link', { name: 'HR & Workforce', exact: true }).click();
    await reviewer.getByRole('button', { name: 'Recruitment', exact: true }).click();
    await reviewer.getByRole('combobox', { name: 'CV candidate' }).selectOption(candidateId);
    await expect(reviewer.getByRole('button', { name: 'Download for review' })).toBeVisible();
    await reviewer.getByRole('button', { name: 'Approve CV', exact: true }).click();
    await expect(reviewer.getByText('candidate.pdf · version 1 · active')).toBeVisible();
  } finally {
    await reviewContext.close();
  }

  await page.reload();
  await page.getByRole('button', { name: 'Recruitment', exact: true }).click();
  await page.getByRole('combobox', { name: 'CV candidate' }).selectOption(candidateId);
  const [download] = await Promise.all([
    page.waitForEvent('download'),
    page.getByRole('button', { name: 'Download CV', exact: true }).click()
  ]);
  expect(await download.failure()).toBeNull();
});

test('HR Manager creates a multi-headcount requisition, rejects it with a reason, and reissues an offer', async ({
  browser,
  page,
  request
}) => {
  const session = await signIn(page, seedAccount('hr_manager'));
  const headers = { Authorization: `Bearer ${session.accessToken}` };
  const unique = Date.now().toString(36);
  const reqCode = `REQ-UI-${unique}`;

  await page.getByRole('link', { name: 'HR & Workforce', exact: true }).click();
  await page.getByRole('button', { name: 'Recruitment', exact: true }).click();
  await page.getByLabel('Requisition code').fill(reqCode);
  await page.getByLabel('Requisition title').fill('Site Foreman');
  await page.getByLabel('Requested headcount').fill('3');
  await page.getByRole('button', { name: 'Create requisition' }).click();

  const reqItem = page.getByRole('listitem').filter({ hasText: reqCode });
  await expect(reqItem).toContainText('Headcount 3');
  await reqItem.getByRole('button', { name: 'Submit requisition' }).click();
  await expect(reqItem).toContainText('submitted');
  await reqItem.getByLabel('Requisition rejection reason').fill('Budget deferred for Q4.');
  await reqItem.getByRole('button', { name: 'Reject requisition' }).click();
  await expect(reqItem).toContainText('rejected');
  await expect(reqItem).toContainText('Rejected: Budget deferred for Q4.');

  // Prepare an evaluated application so offer creation and versioning can be exercised in the browser.
  const openReq = await request.post('/api/v1/hr/requisitions', {
    headers,
    data: { requisition_code: `REQ-O-${unique}`, title: 'MEP Lead', headcount_requested: 1 }
  });
  expect(openReq.status()).toBe(201);
  const openReqId = (await openReq.json()).id as string;
  for (const step of ['submitted', 'approved', 'open']) {
    expect(
      (
        await request.post(`/api/v1/hr/requisitions/${openReqId}/decision`, {
          headers,
          data: { status: step }
        })
      ).status()
    ).toBe(200);
  }
  const candidate = await request.post('/api/v1/hr/candidates', {
    headers,
    data: { candidate_code: `CAND-UI-${unique}`, full_name: `Candidate ${unique}` }
  });
  expect(candidate.status()).toBe(201);
  const candidateId = (await candidate.json()).id as string;
  const application = await request.post('/api/v1/hr/applications', {
    headers,
    data: { requisition_id: openReqId, candidate_id: candidateId }
  });
  expect(application.status()).toBe(201);
  const appId = (await application.json()).id as string;
  for (const stage of ['screening', 'shortlisted', 'interview']) {
    expect(
      (
        await request.patch(`/api/v1/hr/applications/${appId}/stage`, {
          headers,
          data: { stage }
        })
      ).status()
    ).toBe(200);
  }
  const interview = await request.post('/api/v1/hr/interviews', {
    headers,
    data: { application_id: appId, interview_type: 'technical' }
  });
  expect(interview.status()).toBe(201);
  expect(
    (
      await request.patch(`/api/v1/hr/interviews/${(await interview.json()).id}`, {
        headers,
        data: { status: 'completed' }
      })
    ).status()
  ).toBe(200);
  expect(
    (
      await request.patch(`/api/v1/hr/applications/${appId}/stage`, {
        headers,
        data: { stage: 'evaluation' }
      })
    ).status()
  ).toBe(200);

  await page.reload();
  await page.getByRole('button', { name: 'Recruitment', exact: true }).click();
  await expect(reqItem).toContainText('Headcount 3 · rejected · Rejected: Budget deferred for Q4.');
  const reviewerContext = await browser.newContext();
  const reviewerPage = await reviewerContext.newPage();
  const reviewer = await signIn(reviewerPage, seedAccount('hr_manager'));
  const reviewerHeaders = { Authorization: `Bearer ${reviewer.accessToken}` };
  await reviewerContext.close();

  const fileForm = page.getByRole('combobox', { name: 'Offer file candidate', exact: true });
  await fileForm.selectOption(candidateId);
  const firstPdf = Buffer.from('%PDF-1.4\nOriginal offer terms\n%%EOF');
  await page.getByLabel('Offer file (PDF, up to 60 MiB)').setInputFiles({
    name: 'original-offer.pdf',
    mimeType: 'application/pdf',
    buffer: firstPdf
  });
  await page.getByRole('button', { name: 'Upload offer file', exact: true }).click();
  await expect(page.getByText('original-offer.pdf · version 1 · pending')).toBeVisible();
  const uploaded = await request.get('/api/v1/hr/documents', {
    headers,
    params: { candidate_id: candidateId, document_type: 'candidate_offer' }
  });
  expect(uploaded.ok()).toBeTruthy();
  const docId = (await uploaded.json()).items[0].id as string;
  const approve = async (version: number) => {
    const decision = await request.post(
      `/api/v1/hr/documents/${docId}/versions/${version}/decision`,
      {
        headers: reviewerHeaders,
        data: { decision: 'approve' }
      }
    );
    expect(decision.ok()).toBeTruthy();
  };
  await approve(1);

  const deadline = new Date(Date.now() + 7 * 86_400_000).toISOString().slice(0, 10);
  const createForm = page
    .locator('form')
    .filter({ has: page.getByRole('button', { name: 'Save recruitment record' }) });
  await createForm.getByLabel('New record').selectOption('offer');
  await createForm.getByLabel('Reference code').fill(`OFR-UI-${unique}`);
  await createForm.getByLabel('Proposed title').fill('Junior MEP Lead');
  await createForm.locator('select[name="application"]').selectOption(appId);
  const initialFile = createForm.getByLabel('Approved offer PDF');
  await expect(initialFile.getByRole('option', { name: 'original-offer.pdf · v1' })).toBeAttached();
  await initialFile.selectOption({ label: 'original-offer.pdf · v1' });
  await createForm.getByLabel('Valid until').fill(deadline);
  await createForm.getByRole('button', { name: 'Save recruitment record' }).click();

  const v1Card = page
    .getByRole('article')
    .filter({ hasText: `OFR-UI-${unique} · Junior MEP Lead` });
  await expect(v1Card).toContainText(`v1 · draft · Valid until ${deadline}`);
  const secondPdf = Buffer.from('%PDF-1.4\nReplacement offer terms\n%%EOF');
  const uploadSecond = await request.post(`/api/v1/hr/documents/${docId}/versions`, {
    headers,
    multipart: {
      file: { name: 'updated-offer.pdf', mimeType: 'application/pdf', buffer: secondPdf }
    }
  });
  expect(uploadSecond.status()).toBe(201);
  await approve(2);
  await v1Card.getByLabel('Offer code').fill(`OFR-UI2-${unique}`);
  await v1Card.getByLabel('Proposed title').fill('Senior MEP Lead');
  await v1Card.getByRole('button', { name: 'Find a replacement offer file' }).click();
  const replacementFile = v1Card.getByLabel('Approved offer PDF');
  await expect(
    replacementFile.getByRole('option', { name: 'updated-offer.pdf · v2' })
  ).toBeAttached();
  await replacementFile.selectOption({ label: 'updated-offer.pdf · v2' });
  await v1Card.getByRole('button', { name: 'Reissue offer' }).click();

  const v2Card = page
    .getByRole('article')
    .filter({ hasText: `OFR-UI2-${unique} · Senior MEP Lead` });
  await expect(v2Card).toContainText('v2 · draft');
  await expect(v1Card).toContainText('v1 · superseded');
  for (const [card, bytes] of [
    [v1Card, firstPdf],
    [v2Card, secondPdf]
  ] as const) {
    const downloadPromise = page.waitForEvent('download');
    await card.getByRole('button', { name: 'Download offer file' }).click();
    const artifact = await downloadPromise;
    const path = await artifact.path();
    expect(path).not.toBeNull();
    expect(readFileSync(path!)).toEqual(bytes);
  }

  await page.reload();
  await page.getByRole('button', { name: 'Recruitment', exact: true }).click();
  await expect(v2Card).toContainText('v2 · draft');
  await expect(v1Card).toContainText('v1 · superseded');

  for (const state of ['pending approval', 'approved', 'issued', 'accepted']) {
    await v2Card.getByRole('button', { name: `Mark ${state}`, exact: true }).click();
    await expect(v2Card).toContainText(`v2 · ${state.replace(' ', '_')}`);
  }
  const offers = await request.get('/api/v1/hr/offers', {
    headers,
    params: { offer_status: 'accepted' }
  });
  expect(offers.status()).toBe(200);
  const offerRows = (await offers.json()).items as { id: string; offer_code: string }[];
  const acceptedOffer = offerRows.find((row) => row.offer_code === `OFR-UI2-${unique}`);
  expect(acceptedOffer).toBeDefined();
  const cliStatus = () =>
    JSON.parse(
      execFileSync(
        PYTHON_BIN,
        [
          '-m',
          'scripts.garrisonctl',
          'hr',
          'offers',
          'status',
          '--offer-id',
          acceptedOffer!.id,
          '--json'
        ],
        {
          cwd: BACKEND_DIR,
          encoding: 'utf8',
          env: {
            ...env,
            GARRISON_API_BASE_URL: 'http://127.0.0.1:8425',
            GARRISON_ENVIRONMENT: 'test',
            GARRISON_ACCESS_TOKEN: session.accessToken
          }
        }
      )
    ) as { data: { status: string; converted_employee_id: string | null } };
  expect(cliStatus().data.status).toBe('accepted');
  await v2Card.getByLabel('Employee code').fill(`HIRE-${unique}`);
  await v2Card.getByRole('button', { name: 'Start onboarding from offer' }).click();
  const filled = page.getByRole('listitem').filter({ hasText: `REQ-O-${unique}` });
  await expect(filled).toContainText('Headcount 1 · filled');
  await expect(v2Card).toContainText('v2 · converted');
  expect(cliStatus().data).toMatchObject({
    status: 'converted',
    converted_employee_id: expect.any(String)
  });
  await page.reload();
  await page.getByRole('button', { name: 'Recruitment', exact: true }).click();
  await expect(filled).toContainText('Headcount 1 · filled');
  await expect(v2Card).toContainText('v2 · converted');
});

test('HR extends and confirms probation from a completed onboarding case', async ({
  page,
  request
}) => {
  const session = await signIn(page, seedAccount('hr_manager'));
  const headers = { Authorization: `Bearer ${session.accessToken}` };
  const code = `PROB-${Date.now()}`;
  const employee = await request.post('/api/v1/hr/employees', {
    headers,
    data: {
      employee_code: code,
      first_name: 'Synthetic',
      last_name: code,
      employment_category: 'probation'
    }
  });
  expect(employee.status()).toBe(201);
  const isoDate = (days: number) =>
    new Date(Date.now() + days * 86_400_000).toISOString().slice(0, 10);
  const created = await request.post('/api/v1/hr/onboarding', {
    headers,
    data: {
      employee_id: (await employee.json()).id,
      start_date: isoDate(-30),
      probation_end_date: isoDate(2)
    }
  });
  expect(created.status()).toBe(201);
  const { id: caseId, tasks } = (await created.json()) as {
    id: string;
    tasks: { id: string }[];
  };
  const scratch = mkdtempSync(join(tmpdir(), 'garrison-onboarding-cli-'));
  try {
    const path = join(scratch, 'evidence.json');
    const evidence = 'Verified synthetic checklist.';
    writeFileSync(path, JSON.stringify({ status: 'completed', evidence_notes: evidence }), {
      mode: 0o600
    });
    const taskCommand = [
      '-m',
      'scripts.garrisonctl',
      'hr',
      'onboarding',
      'task',
      '--case-id',
      caseId,
      '--task-id',
      tasks[0].id,
      '--file',
      path,
      '--json'
    ];
    const runTask = (...options: string[]) =>
      execFileSync(PYTHON_BIN, [...taskCommand, ...options], {
        cwd: BACKEND_DIR,
        encoding: 'utf8',
        env: {
          ...env,
          GARRISON_API_BASE_URL: 'http://127.0.0.1:8425',
          GARRISON_ENVIRONMENT: 'test',
          GARRISON_ACCESS_TOKEN: session.accessToken
        }
      });
    const preview = JSON.parse(runTask('--dry-run')) as { data: { plan_sha256: string } };
    const receipt = runTask('--apply', '--expect', preview.data.plan_sha256);
    expect(receipt).not.toContain(evidence);
    expect(JSON.parse(receipt).data.tasks).toContainEqual(
      expect.objectContaining({ id: tasks[0].id, status: 'completed' })
    );
  } finally {
    rmSync(scratch, { recursive: true, force: true });
  }
  for (const task of tasks.slice(1)) {
    const completed = await request.patch(`/api/v1/hr/onboarding/tasks/${task.id}`, {
      headers,
      data: { status: 'completed', evidence_notes: 'Verified synthetic checklist.' }
    });
    expect(completed.status()).toBe(200);
  }
  await page.getByRole('link', { name: 'HR & Workforce', exact: true }).click();
  await page.getByRole('button', { name: 'Recruitment', exact: true }).click();
  const card = page.getByRole('article').filter({ hasText: `Synthetic ${code}` });
  await card.getByRole('button', { name: 'Start probation', exact: true }).click();
  await card.getByRole('combobox', { name: 'Probation outcome' }).selectOption('extend');
  await card.getByLabel('New probation end date', { exact: true }).fill(isoDate(15));
  await card
    .getByLabel('Probation review reason', { exact: true })
    .fill('Extended for further review.');
  await card.getByRole('button', { name: 'Record probation decision' }).click();
  await expect(card.getByText(`Probation end date ${isoDate(15)}`, { exact: true })).toBeVisible();
  await page.reload();
  await page.getByRole('button', { name: 'Recruitment', exact: true }).click();
  await card
    .getByRole('combobox', { name: 'Confirmed employment category' })
    .selectOption('contract');
  await card
    .getByLabel('Probation review reason', { exact: true })
    .fill('Confirmed based on documented results.');
  await card.getByRole('button', { name: 'Record probation decision' }).click();
  await expect(card.getByText('Employment active', { exact: true })).toBeVisible();
});

test('HR requests a project assignment for a director to approve', async ({
  page,
  browser,
  request
}) => {
  const director = seedAccount();
  const worker = seedAccount('group_project_manager');
  const directorContext = await browser.newContext();
  try {
    const directorPage = await directorContext.newPage();
    const directorSession = await signIn(directorPage, director);
    const directorHeaders = { Authorization: `Bearer ${directorSession.accessToken}` };
    const projectEndpoint = `/api/v1/projects/${director.projectId}`;
    const project = (await (
      await request.get(projectEndpoint, { headers: directorHeaders })
    ).json()) as {
      name: string;
      code: string;
    };
    const accounts = await request.get('/api/v1/users', {
      headers: directorHeaders,
      params: { email: worker.email }
    });
    const workerId = (await accounts.json()).items[0].id as string;
    const manager = await signIn(page, seedAccount('hr_manager'));
    const employeeCode = `ASSIGN-${Date.now()}`;
    const created = await request.post('/api/v1/hr/employees', {
      headers: { Authorization: `Bearer ${manager.accessToken}` },
      data: {
        employee_code: employeeCode,
        first_name: 'Synthetic',
        last_name: 'Assignment',
        work_email: worker.email,
        employment_status: 'active'
      }
    });
    expect(created.status()).toBe(201);
    const linked = await request.post(
      `/api/v1/hr/employees/${(await created.json()).id}/link-account`,
      {
        headers: directorHeaders,
        data: { user_id: workerId }
      }
    );
    expect(linked.status()).toBe(200);

    await page.getByRole('link', { name: 'HR & Workforce', exact: true }).click();
    await page.getByRole('button', { name: 'Directory & Org', exact: true }).click();
    await page.getByLabel('Search employees').fill(employeeCode);
    await page
      .getByRole('row')
      .filter({ hasText: employeeCode })
      .getByRole('button', { name: 'Inspect' })
      .click();
    await page.getByLabel('Find project by name or code').fill(project.code);
    await page.getByRole('button', { name: 'Find project', exact: true }).click();
    await page
      .getByRole('combobox', { name: 'Assignment project' })
      .selectOption(director.projectId);
    await page.getByLabel('Assignment reason').fill('Staffing review.');
    await page.getByRole('button', { name: 'Send assignment request' }).click();
    await expect(page.getByText('Request sent for project review.')).toBeVisible();
    const before = await request.get(`${projectEndpoint}/members`, { headers: directorHeaders });
    expect(
      (await before.json()).some((item: { user_id: string }) => item.user_id === workerId)
    ).toBe(false);

    await directorPage.getByRole('link', { name: 'Projects', exact: true }).click();
    await directorPage.getByRole('button', { name: project.name, exact: true }).click();
    const detail = directorPage.getByRole('region', { name: 'Project details' });
    await detail.getByRole('button', { name: 'Team', exact: true }).click();
    await detail.getByRole('button', { name: 'Approve assignment', exact: true }).click();
    await expect(detail.getByText('Assignment decision recorded.')).toBeVisible();
    const after = await request.get(`${projectEndpoint}/members`, { headers: directorHeaders });
    expect(
      (await after.json()).some((item: { user_id: string }) => item.user_id === workerId)
    ).toBe(true);

    await page.reload();
    await page.getByRole('button', { name: 'Directory & Org', exact: true }).click();
    await expect(
      page.getByText(`Synthetic Assignment · ${project.code} · Add · approved`)
    ).toBeVisible();
  } finally {
    await directorContext.close();
  }
});

test('revoking the HR role clears the open HR workspace and prevents access after sign-in', async ({
  page,
  browser,
  request
}) => {
  const [director, manager] = seedProjectAccounts('managing_director', 'hr_manager');
  const session = await signIn(page, manager);
  const hrHeaders = { Authorization: `Bearer ${session.accessToken}` };
  const marker = `Revocation-${Date.now()}`;
  const employee = await request.post('/api/v1/hr/employees', {
    headers: hrHeaders,
    data: { employee_code: marker, first_name: 'Synthetic', last_name: marker }
  });
  expect(employee.status()).toBe(201);
  await page.getByRole('link', { name: 'HR & Workforce', exact: true }).click();
  await page.getByRole('button', { name: 'Directory & Org' }).click();
  const employeeRow = page.getByRole('row').filter({ hasText: marker });
  await expect(employeeRow).toBeVisible();

  const directorContext = await browser.newContext();
  try {
    const directorSession = await signIn(await directorContext.newPage(), director);
    const headers = { Authorization: `Bearer ${directorSession.accessToken}` };
    const users = await request.get('/api/v1/users', { headers, params: { email: manager.email } });
    expect(users.status()).toBe(200);
    const { items } = (await users.json()) as { items: Array<{ id: string; updated_at: string }> };
    expect(items).toHaveLength(1);
    expect(items[0].id).toBe(session.userId);
    const changed = await request.patch(`/api/v1/users/${session.userId}`, {
      headers,
      data: { role: 'site_supervisor', expected_updated_at: items[0].updated_at }
    });
    expect(changed.status()).toBe(200);
  } finally {
    await directorContext.close();
  }

  const stale = await request.get('/api/v1/hr/employees', { headers: hrHeaders });
  expect(stale.status()).toBe(401);
  await page.getByRole('button', { name: 'Refresh', exact: true }).click();
  await expect(page).toHaveURL(/\/login$/);
  await expect(employeeRow).toHaveCount(0);

  const lowerPrivilege = await signIn(page, manager);
  expect(lowerPrivilege.userId).toBe(session.userId);
  await expect(page.getByRole('link', { name: 'HR & Workforce', exact: true })).toHaveCount(0);
  const forbidden = await request.get('/api/v1/hr/employees', {
    headers: { Authorization: `Bearer ${lowerPrivilege.accessToken}` }
  });
  expect(forbidden.status()).toBe(403);
  const deniedPageRequests: string[] = [];
  page.on('request', (outgoing) => {
    const path = new URL(outgoing.url()).pathname;
    if (path.startsWith('/api/v1/hr/')) deniedPageRequests.push(path);
  });
  await page.goto('/hr');
  await expect(page).toHaveURL(/\/dashboard$/);
  await expect(page.getByRole('heading', { name: 'HR & Workforce Hub' })).toHaveCount(0);
  await expect(employeeRow).toHaveCount(0);
  expect(deniedPageRequests).toEqual([]);
});

test('HR staff draft, approve and publish a calendar and download the aggregate summary', async ({
  page,
  browser,
  request
}) => {
  const [preparer, reviewer] = seedProjectAccounts('hr_manager', 'hr_manager');
  const preparerSession = await signIn(page, preparer);
  const employeeCode = `CSV-${Date.now().toString(36)}`;
  const employee = await request.post('/api/v1/hr/employees', {
    headers: { Authorization: `Bearer ${preparerSession.accessToken}` },
    data: {
      employee_code: employeeCode,
      first_name: 'Synthetic',
      last_name: employeeCode,
      employment_status: 'active',
      primary_project_id: preparer.projectId
    }
  });
  expect(employee.status()).toBe(201);
  await page.getByRole('link', { name: 'HR & Workforce', exact: true }).click();
  const summaryButton = page.getByRole('button', { name: 'Download summary (XLSX)', exact: true });
  await expect(summaryButton).toBeEnabled();
  const download = page.waitForEvent('download');
  await summaryButton.click();
  expect((await download).suggestedFilename()).toBe('hr-summary.xlsx');

  const calendarCode = `CAL-${Date.now()}`;
  const calendarName = `Synthetic work calendar ${calendarCode}`;
  type Calendar = { id: string; code: string; status: string; revision: number };
  function calendarCli(token: string, ...args: string[]) {
    return JSON.parse(execFileSync(
      PYTHON_BIN, ['-m', 'scripts.garrisonctl', 'hr', 'calendars', ...args, '--json'], {
        cwd: BACKEND_DIR,
        encoding: 'utf8',
        env: {
          ...env, GARRISON_API_BASE_URL: 'http://127.0.0.1:8425',
          GARRISON_ENVIRONMENT: 'test', GARRISON_ACCESS_TOKEN: token
        }
      }
    )) as { data: Calendar & { items: Calendar[]; plan_sha256: string } };
  }
  await page.getByRole('button', { name: 'Attendance', exact: true }).click();
  await page.getByText('Work calendars, holidays and shifts', { exact: true }).click();
  await page.getByLabel('Calendar code').fill(calendarCode);
  await page.getByLabel('Name', { exact: true }).fill(calendarName);
  await page.getByLabel('Calendar effective from').fill('2027-01-01');
  await page.getByLabel('Calendar effective through').fill('2027-01-31');
  await page.getByLabel('IANA timezone').fill('Asia/Colombo');
  await page.getByLabel('Project ID (optional)', { exact: true }).fill(preparer.projectId);
  await page.getByLabel('MON', { exact: true }).check();
  await page.getByLabel('Scheduled daily hours').fill('7.50');
  await page.getByLabel('Start time', { exact: true }).fill('08:30');
  await page.getByLabel('End time', { exact: true }).fill('16:00');
  await page.getByRole('button', { name: 'Save schedule' }).click();
  await expect(page.getByText(`${calendarName} · MON · 7.50 h`, { exact: true })).toBeVisible();
  const calendar = calendarCli(preparerSession.accessToken, 'list').data.items.find(
    (item) => item.code === calendarCode
  );
  expect(calendar?.status).toBe('draft');
  if (!calendar) throw new Error('Calendar missing from CLI list');
  const calendarIdArgs = ['--calendar-id', calendar.id];
  const inputDirectory = mkdtempSync(join(tmpdir(), 'garrison-calendar-cli-'));
  try {
    const inputPath = join(inputDirectory, 'calendar.json');
    const fields = {
      code: calendarCode, name: calendarName, work_days_json: ['MON', 'TUE'],
      standard_start_time: '08:30', standard_end_time: '16:00', daily_hours: '7.50',
      effective_from: '2027-01-01', effective_to: '2027-01-31',
      timezone: 'Asia/Colombo', project_id: preparer.projectId
    };
    const create = ['create', '--file', inputPath];
    writeFileSync(inputPath, JSON.stringify({
      ...fields, code: `${calendarCode}-draft`, name: 'Separate CLI draft'
    }), {
      mode: 0o600
    });
    const createPlan = calendarCli(preparerSession.accessToken, ...create, '--dry-run');
    const created = calendarCli(
      preparerSession.accessToken, ...create, '--apply', '--expect', createPlan.data.plan_sha256
    );
    expect(created.data).toMatchObject({ code: `${calendarCode}-draft`, status: 'draft', revision: 1 });
    const update = ['update', ...calendarIdArgs, '--file', inputPath];
    writeFileSync(inputPath, JSON.stringify(fields));
    const updatePlan = calendarCli(preparerSession.accessToken, ...update, '--dry-run');
    const updated = calendarCli(
      preparerSession.accessToken, ...update, '--apply', '--expect', updatePlan.data.plan_sha256
    );
    expect(updated.data).toMatchObject({ status: 'draft', revision: calendar.revision + 1 });
    expect(() => calendarCli(
      preparerSession.accessToken, ...update, '--apply', '--expect', updatePlan.data.plan_sha256
    )).toThrow();
  } finally {
    rmSync(inputDirectory, { recursive: true, force: true });
  }
  await page.reload();
  await page.getByRole('button', { name: 'Attendance', exact: true }).click();
  await page.getByText('Work calendars, holidays and shifts', { exact: true }).click();
  const draft = page.getByRole('listitem').filter({ hasText: calendarName });
  await draft.getByRole('button', { name: 'Submit calendar' }).click();
  await expect(draft.getByText(/^submitted/)).toBeVisible();
  await expect(draft.getByRole('button', { name: 'Approve calendar' })).toHaveCount(0);

  const reviewerContext = await browser.newContext();
  try {
    const approvalPage = await reviewerContext.newPage();
    const reviewerSession = await signIn(approvalPage, reviewer);
    const decision = ['decide', ...calendarIdArgs, '--action', 'approve'];
    expect(() => calendarCli(preparerSession.accessToken, ...decision, '--dry-run')).toThrow();
    const decisionPlan = calendarCli(reviewerSession.accessToken, ...decision, '--dry-run');
    const approved = calendarCli(
      reviewerSession.accessToken, ...decision, '--apply', '--expect', decisionPlan.data.plan_sha256
    );
    expect(approved.data.status).toBe('approved');
    await approvalPage.getByRole('link', { name: 'HR & Workforce', exact: true }).click();
    await approvalPage.getByRole('button', { name: 'Attendance', exact: true }).click();
    await approvalPage.getByText('Work calendars, holidays and shifts', { exact: true }).click();
    const record = approvalPage.getByRole('listitem').filter({ hasText: calendarName });
    await record.getByRole('button', { name: 'Publish calendar' }).click();
    await expect(record.getByText(/^published/)).toBeVisible();
    expect(calendarCli(reviewerSession.accessToken, 'show', ...calendarIdArgs).data.status).toBe(
      'published'
    );

    await page.getByText('Import attendance CSV', { exact: true }).click();
    const importHeader = 'employee_code,work_date,attendance_status,worked_hours,check_in_at,check_out_at\n';
    const start = '2027-01-04T22:30:00+05:30';
    const end = '2027-01-05T06:00:00+05:30';
    const importPreview = page.getByRole('list', { name: 'Attendance import preview' });
    const applyImport = page.getByRole('button', { name: 'Apply attendance import', exact: true });
    await page.getByLabel('Attendance CSV', { exact: true }).setInputFiles({
      name: 'incomplete-attendance.csv',
      mimeType: 'text/csv',
      buffer: Buffer.from(importHeader + `${employeeCode},2027-01-04,present,7.50,${start},\n`)
    });
    await page.getByRole('button', { name: 'Preview attendance', exact: true }).click();
    await expect(importPreview).toContainText('Enter both clock times or neither.');
    await expect(applyImport).toBeDisabled();

    await page.getByLabel('Attendance CSV', { exact: true }).setInputFiles({
      name: 'attendance.csv',
      mimeType: 'text/csv',
      buffer: Buffer.from(
        importHeader + `${employeeCode},2027-01-04,present,7.50,${start},${end}\n`
      )
    });
    await page.getByRole('button', { name: 'Preview attendance', exact: true }).click();
    await expect(importPreview).toContainText(employeeCode);
    await expect(importPreview).toContainText(start);
    await expect(importPreview).toContainText(end);
    await applyImport.click();
    await expect(page.getByText('1 attendance entries submitted for review.')).toBeVisible();

    await approvalPage.reload();
    await approvalPage.getByRole('button', { name: 'Attendance', exact: true }).click();
    const attendance = approvalPage.getByText(new RegExp(`Synthetic ${employeeCode}.*2027-01-04`));
    await attendance.locator('..').getByRole('button', { name: 'Approve attendance' }).click();
    await expect(attendance).toContainText('approved');
  } finally {
    await reviewerContext.close();
  }

  await page.reload();
  await page.getByRole('button', { name: 'Attendance', exact: true }).click();
  await page.getByText('Work calendars, holidays and shifts', { exact: true }).click();
  await expect(draft.getByText(/^published/)).toBeVisible();
  await expect(draft.getByRole('button', { name: 'Edit calendar' })).toHaveCount(0);
});

test('HR Manager filters the dashboard and exports the same report', async ({ page, request }) => {
  const account = seedAccount('hr_manager');
  const session = await signIn(page, account);
  const headers = { Authorization: `Bearer ${session.accessToken}` };
  const code = `REP-${Date.now().toString(36)}`;
  const department = await request.post('/api/v1/hr/departments', {
    headers,
    data: { code, name: `Synthetic reporting ${code}` }
  });
  expect(department.status()).toBe(201);
  const departmentId = (await department.json()).id as string;
  const employee = await request.post('/api/v1/hr/employees', {
    headers,
    data: {
      employee_code: code,
      first_name: 'Synthetic',
      last_name: 'Reporting',
      employment_status: 'active',
      primary_project_id: account.projectId,
      department_id: departmentId
    }
  });
  expect(employee.status()).toBe(201);
  const entry = await request.post('/api/v1/hr/attendance', {
    headers,
    data: {
      employee_id: (await employee.json()).id,
      work_date: '2027-01-05',
      worked_hours: '0.00',
      attendance_status: 'absent'
    }
  });
  expect(entry.status()).toBe(201);

  await page.getByRole('link', { name: 'HR & Workforce', exact: true }).click();
  await page
    .getByRole('combobox', { name: 'Primary site', exact: true })
    .selectOption(account.projectId);
  await page.getByRole('combobox', { name: 'Department', exact: true }).selectOption(departmentId);
  await page.getByLabel('Activity start date').fill('2027-01-05');
  await page.getByRole('button', { name: 'Apply report filters' }).click();
  await expect(page.getByText(/Choose an activity start and end date/)).toBeVisible();
  await page.getByLabel('Activity end date').fill('2027-01-05');
  await page.getByRole('button', { name: 'Apply report filters' }).click();
  await expect(page.getByText(/Attendance 2027-01-05 to 2027-01-05/)).toBeVisible();
  await expect(
    page.getByText('Attendance exceptions', { exact: true }).locator('..').locator('dd')
  ).toHaveText('1');
  await expect(
    page.getByText('Active workforce', { exact: true }).locator('..').locator('dd')
  ).toHaveText('1');
  await expect(
    page.getByText('Scheduled training', { exact: true }).locator('..').locator('dd')
  ).toHaveText('0');

  const refreshed = page.waitForResponse(
    (response) =>
      response.url().includes('/hr/reports/summary?') &&
      new URL(response.url()).searchParams.get('department_id') === departmentId
  );
  await page.getByRole('button', { name: 'Refresh', exact: true }).click();
  expect((await refreshed).status()).toBe(200);

  for (const format of ['CSV', 'PDF']) {
    const file = page.waitForEvent('download');
    const exported = page.waitForResponse((response) =>
      response.url().includes(`/hr/reports/summary.${format.toLowerCase()}?`)
    );
    await page.getByRole('button', { name: `Download summary (${format})` }).click();
    const params = new URL((await exported).url()).searchParams;
    expect(params.get('project_id')).toBe(account.projectId);
    expect(params.get('department_id')).toBe(departmentId);
    expect(params.get('date_from')).toBe('2027-01-05');
    expect((await file).suggestedFilename()).toBe(`hr-summary.${format.toLowerCase()}`);
  }
});

test('a direct manager recommends self-submitted time and HR makes the final decision', async ({
  page,
  browser,
  request
}) => {
  const [director, hr, lineManager, worker] = seedProjectAccounts(
    'managing_director', 'hr_manager', 'group_project_manager', 'quantity_surveyor'
  );
  const directorSession = await signIn(page, director);
  const directorHeaders = { Authorization: `Bearer ${directorSession.accessToken}` };
  const hrContext = await browser.newContext();
  const managerContext = await browser.newContext();
  const staffContext = await browser.newContext();
  try {
    const hrPage = await hrContext.newPage();
    const managerPage = await managerContext.newPage();
    const staffPage = await staffContext.newPage();
    const hrSession = await signIn(hrPage, hr);
    const managerSession = await signIn(managerPage, lineManager);
    const employeeSession = await signIn(staffPage, worker);
    const hrHeaders = { Authorization: `Bearer ${hrSession.accessToken}` };
    const unique = Date.now().toString(36);
    const reviewer = await request.post('/api/v1/hr/employees', {
      headers: hrHeaders,
      data: {
        employee_code: `MGR-${unique}`,
        first_name: 'Synthetic',
        last_name: 'Reviewer',
        work_email: lineManager.email,
        employment_status: 'active'
      }
    });
    expect(reviewer.status()).toBe(201);
    const reviewerId = (await reviewer.json()).id as string;
    const employee = await request.post('/api/v1/hr/employees', {
      headers: hrHeaders,
      data: {
        employee_code: `WRK-${unique}`,
        first_name: 'Synthetic',
        last_name: `Worker-${unique}`,
        work_email: worker.email,
        employment_status: 'active',
        manager_employee_id: reviewerId
      }
    });
    expect(employee.status()).toBe(201);
    const employeeId = (await employee.json()).id as string;
    for (const [id, userId] of [
      [reviewerId, managerSession.userId],
      [employeeId, employeeSession.userId]
    ]) {
      const linked = await request.post(`/api/v1/hr/employees/${id}/link-account`, {
        headers: directorHeaders,
        data: { user_id: userId }
      });
      expect(linked.status()).toBe(200);
    }

    await hrPage.getByRole('link', { name: 'HR & Workforce', exact: true }).click();
    await hrPage.getByRole('button', { name: 'Directory & Org' }).click();
    await hrPage.getByLabel('Search employees').fill(`WRK-${unique}`);
    const row = hrPage.getByRole('row').filter({ hasText: `WRK-${unique}` });
    await row.getByRole('button', { name: 'Inspect', exact: true }).click();
    await hrPage
      .getByRole('button', { name: 'Authorize line-manager review', exact: true })
      .click();
    await expect(
      hrPage.getByText('Line-manager review for future requests: authorized')
    ).toBeVisible();

    await staffPage.getByRole('link', { name: 'My HR', exact: true }).click();
    await staffPage.getByLabel('Period starts').fill('2027-02-01');
    await staffPage.getByLabel('Period ends').fill('2027-02-05');
    await staffPage.getByLabel('Regular hours', { exact: true }).fill('35.00');
    await staffPage.getByLabel('Time notes').fill('Private fixture notes');
    const submitted = staffPage.waitForResponse(
      (response) =>
        response.url().endsWith('/hr/me/timesheets') && response.request().method() === 'POST'
    );
    await staffPage.getByRole('button', { name: 'Submit timesheet', exact: true }).click();
    expect((await submitted).status()).toBe(201);
    const timesheetId = (await (await submitted).json()).id as string;

    await managerPage.getByRole('link', { name: 'My HR', exact: true }).click();
    const review = managerPage.getByRole('listitem').filter({ hasText: `Worker-${unique}` });
    await expect(review).toContainText('35.00 hours');
    await expect(managerPage.getByText('Private fixture notes')).toHaveCount(0);
    await review.getByRole('button', { name: 'Recommend', exact: true }).click();
    await expect(
      managerPage.getByText('Recommendation recorded. HR will make the final decision.')
    ).toBeVisible();
    await expect(review).toHaveCount(0);

    const decision = await request.post(`/api/v1/hr/timesheets/${timesheetId}/decision`, {
      headers: hrHeaders,
      data: { decision: 'approved', expected_revision: 2 }
    });
    expect(decision.status()).toBe(200);
    const overtime = await request.post('/api/v1/hr/overtime', {
      headers: hrHeaders,
      data: {
        employee_id: employeeId,
        work_date: '2027-02-04',
        requested_hours: '2.00',
        reason: 'Synthetic pending overtime'
      }
    });
    expect(overtime.status()).toBe(201);
    await hrPage.getByRole('button', { name: 'Attendance', exact: true }).click();
    await hrPage
      .getByText(`Worker-${unique} · 2027-02-01 to 2027-02-05 · approved`, { exact: false })
      .locator('..')
      .getByRole('button', { name: 'Lock timesheet', exact: true })
      .click();
    await expect(
      hrPage
        .getByRole('alert')
        .filter({ hasText: 'pending corrections and overtime before locking' })
    ).toBeVisible();
    await staffPage.reload();
    await expect(
      staffPage.getByRole('listitem').filter({ hasText: '2027-02-01 to 2027-02-05' })
    ).toContainText('approved');
  } finally {
    await hrContext.close();
    await managerContext.close();
    await staffContext.close();
  }
});

test('a linked employee manages their own leave and reopens a completed HR request', async ({
  browser,
  request
}) => {
  const [director, manager, reviewer, worker] = seedProjectAccounts(
    'managing_director', 'hr_manager', 'hr_manager', 'quantity_surveyor'
  );
  const directorContext = await browser.newContext();
  const managerContext = await browser.newContext();
  const reviewerContext = await browser.newContext();
  const workerContext = await browser.newContext();
  try {
    const directorSession = await signIn(await directorContext.newPage(), director);
    await directorContext.close();
    const managerPage = await managerContext.newPage();
    const managerSession = await signIn(managerPage, manager);
    const workerPage = await workerContext.newPage();
    const workerSession = await signIn(workerPage, worker);
    const managerHeaders = { Authorization: `Bearer ${managerSession.accessToken}` };
    const reviewerPage = await reviewerContext.newPage();
    const reviewerSession = await signIn(reviewerPage, reviewer);
    const reviewerHeaders = { Authorization: `Bearer ${reviewerSession.accessToken}` };
    const unique = Date.now().toString(36);
    const calendarResponse = await request.post('/api/v1/hr/calendars', {
      headers: managerHeaders,
      data: {
        code: `CAL-${unique}`,
        name: 'Synthetic site calendar',
        project_id: director.projectId,
        work_days_json: ['MON', 'TUE', 'WED', 'THU', 'FRI'],
        standard_start_time: '08:00',
        standard_end_time: '17:00',
        daily_hours: '8.00',
        effective_from: '2026-12-01',
        effective_to: '2026-12-31',
        timezone: 'Asia/Colombo'
      }
    });
    expect(calendarResponse.status()).toBe(201);
    let calendar = (await calendarResponse.json()) as { id: string; revision: number };
    for (const action of ['submit', 'approve', 'publish']) {
      const decision = await request.post(`/api/v1/hr/calendars/${calendar.id}/decision`, {
        headers: action === 'submit' ? managerHeaders : reviewerHeaders,
        data: { action, expected_revision: calendar.revision }
      });
      expect(decision.status()).toBe(200);
      calendar = (await decision.json()) as typeof calendar;
    }
    const employee = await request.post('/api/v1/hr/employees', {
      headers: managerHeaders,
      data: {
        employee_code: `LEAVE-${unique}`,
        first_name: 'Synthetic',
        last_name: 'Employee',
        work_email: worker.email,
        join_date: '2025-01-01',
        primary_project_id: director.projectId,
        employment_status: 'active'
      }
    });
    expect(employee.status()).toBe(201);
    const employeeId = (await employee.json()).id as string;
    const link = await request.post(`/api/v1/hr/employees/${employeeId}/link-account`, {
      headers: { Authorization: `Bearer ${directorSession.accessToken}` },
      data: { user_id: workerSession.userId }
    });
    expect(link.status()).toBe(200);
    const leaveName = `Synthetic leave ${unique}`;
    const partialEmployee = await request.post('/api/v1/hr/employees', {
      headers: managerHeaders,
      data: {
        employee_code: `PART-${unique}`,
        first_name: 'Synthetic',
        last_name: 'Midmonth',
        join_date: '2025-02-15',
        employment_status: 'active'
      }
    });
    expect(partialEmployee.status()).toBe(201);
    const partialEmployeeId = (await partialEmployee.json()).id as string;
    const leaveType = await request.post('/api/v1/hr/leave/types', {
      headers: managerHeaders,
      data: { code: `LT-${unique}`, name: leaveName, is_paid: true }
    });
    expect(leaveType.status()).toBe(201);
    const leaveTypeId = (await leaveType.json()).id as string;

    const policyCode = `POL-${unique}`;
    await managerPage.getByRole('link', { name: 'HR & Workforce', exact: true }).click();
    await managerPage.getByRole('button', { name: 'Leave', exact: true }).click();
    await managerPage.getByText('Leave policy proposals', { exact: true }).click();
    await managerPage.getByLabel('Policy code', { exact: true }).fill(policyCode);
    await managerPage
      .getByLabel('Policy name', { exact: true })
      .fill('Synthetic monthly entitlement');
    await managerPage
      .getByRole('combobox', { name: 'Policy leave type' })
      .selectOption(leaveTypeId);
    await managerPage.getByLabel('Effective from', { exact: true }).fill('2025-01-01');
    await managerPage.getByLabel('Effective through', { exact: true }).fill('2025-12-31');
    await managerPage.getByLabel('Annual entitlement', { exact: true }).fill('12');
    await managerPage.getByRole('combobox', { name: 'Accrual frequency' }).selectOption('monthly');
    await managerPage.getByRole('checkbox', { name: /Prorate eligible calendar days/ }).check();
    await managerPage.getByLabel('Maximum carry-forward', { exact: true }).fill('3');
    await managerPage
      .getByRole('checkbox', { name: 'Expire days above the carry-forward cap at year-end' })
      .check();
    await managerPage.getByRole('button', { name: 'Propose leave policy' }).click();
    const staffDraft = managerPage.getByRole('article').filter({ hasText: policyCode });
    await expect(staffDraft).toContainText('draft');
    await expect(staffDraft.getByRole('button', { name: 'Approve leave policy' })).toHaveCount(0);
    await reviewerPage.getByRole('link', { name: 'HR & Workforce', exact: true }).click();
    await reviewerPage.getByRole('button', { name: 'Leave', exact: true }).click();
    await reviewerPage.getByText('Leave policy proposals', { exact: true }).click();
    const reviewPolicy = reviewerPage.getByRole('article').filter({ hasText: policyCode });
    await expect(reviewPolicy).toContainText('Partial periods prorated by eligible calendar days');
    await reviewPolicy.getByRole('button', { name: 'Approve leave policy' }).click();
    await expect(reviewPolicy).toContainText('approved');
    await reviewerPage.reload();
    await reviewerPage.getByRole('button', { name: 'Leave', exact: true }).click();
    await reviewerPage.getByText('Leave policy proposals', { exact: true }).click();
    await expect(reviewPolicy).toContainText('approved');

    await managerPage.getByText('Post approved leave accrual', { exact: true }).click();
    const accrualEmployee = managerPage.getByRole('combobox', { name: 'Accrual employee' });
    const accrualMonth = managerPage.getByRole('spinbutton', {
      name: 'Accrual month (blank for full year)'
    });
    await accrualEmployee.selectOption(partialEmployeeId);
    await managerPage
      .getByRole('combobox', { name: 'Accrual leave type' })
      .selectOption(leaveTypeId);
    await managerPage.getByRole('spinbutton', { name: 'Accrual year' }).fill('2025');
    await accrualMonth.fill('2');
    await managerPage.getByRole('button', { name: 'Preview accrual' }).click();
    await expect(managerPage.getByText('Days to credit: 0.50')).toBeVisible();
    await expect(managerPage.getByText(/Prorated for 2025-02-15 through 2025-02-28/)).toBeVisible();
    await managerPage.getByRole('button', { name: 'Confirm and post accrual' }).click();
    await expect(managerPage.getByText(/Accrual posted. Ledger reference/)).toHaveCount(1);
    await accrualEmployee.selectOption(employeeId);
    await accrualMonth.fill('1');
    await managerPage.getByRole('spinbutton', { name: 'Catch-up end month (optional)' }).fill('12');
    await managerPage.getByRole('button', { name: 'Preview accrual' }).click();
    await expect(managerPage.getByText('Days to credit: 12.00')).toBeVisible();
    await managerPage.getByRole('button', { name: 'Confirm and post accrual' }).click();
    await expect(managerPage.getByText(/Accrual posted. Ledger reference/)).toHaveCount(12);
    const cliAccrual = JSON.parse(
      execFileSync(
        PYTHON_BIN,
        [
          '-m',
          'scripts.garrisonctl',
          'hr',
          'leave',
          'accrual',
          'post',
          '--employee-id',
          employeeId,
          '--leave-type-id',
          leaveTypeId,
          '--year',
          '2025',
          '--month',
          '1',
          '--through-month',
          '12',
          '--dry-run',
          '--json'
        ],
        {
          cwd: BACKEND_DIR,
          encoding: 'utf8',
          env: {
            ...env,
            GARRISON_API_BASE_URL: 'http://127.0.0.1:8425',
            GARRISON_ENVIRONMENT: 'test',
            GARRISON_ACCESS_TOKEN: managerSession.accessToken
          }
        }
      )
    ) as { data: { accrual: { periods: { days: string; ledger_entry_id: string }[] } } };
    const receipts = cliAccrual.data.accrual.periods;
    expect(new Set(receipts.map((period) => period.ledger_entry_id)).size).toBe(12);
    expect(receipts).toHaveLength(12);
    expect(receipts.every((period) => period.days === '1.00' && period.ledger_entry_id)).toBe(true);

    await managerPage.getByText('Review year-end leave rollover', { exact: true }).click();
    await managerPage.getByRole('combobox', { name: 'Rollover employee' }).selectOption(employeeId);
    await managerPage
      .getByRole('combobox', { name: 'Rollover leave type' })
      .selectOption(leaveTypeId);
    await managerPage.getByRole('spinbutton', { name: 'Source leave year' }).fill('2025');
    await managerPage.getByRole('button', { name: 'Preview rollover' }).click();
    await expect(managerPage.getByText('Carry to 2026: 3.00 days')).toBeVisible();
    await expect(managerPage.getByText('Year-end expiry: 9.00 days')).toBeVisible();
    await managerPage.getByRole('button', { name: 'Confirm and close leave year' }).click();
    await expect(managerPage.getByText(/Rollover posted. Receipt/)).toBeVisible();
    const cliRollover = JSON.parse(
      execFileSync(
        PYTHON_BIN,
        [
          '-m',
          'scripts.garrisonctl',
          'hr',
          'leave',
          'rollover',
          'post',
          '--employee-id',
          employeeId,
          '--leave-type-id',
          leaveTypeId,
          '--year',
          '2025',
          '--dry-run',
          '--json'
        ],
        {
          cwd: BACKEND_DIR,
          encoding: 'utf8',
          env: {
            ...env,
            GARRISON_API_BASE_URL: 'http://127.0.0.1:8425',
            GARRISON_ENVIRONMENT: 'test',
            GARRISON_ACCESS_TOKEN: managerSession.accessToken
          }
        }
      )
    ) as { data: { rollover: { carried_days: string; expired_days: string; receipt_id: string } } };
    expect(cliRollover.data.rollover).toMatchObject({
      carried_days: '3.00',
      expired_days: '9.00',
      receipt_id: expect.any(String)
    });

    await workerPage.getByRole('link', { name: 'My HR', exact: true }).click();
    await expect(
      workerPage.getByRole('heading', { name: 'My HR Profile', exact: true })
    ).toBeVisible();
    await workerPage.getByLabel('Leave type', { exact: true }).selectOption(leaveTypeId);
    await workerPage.getByLabel('Leave starts').fill('2026-12-04');
    await workerPage.getByLabel('Leave ends').fill('2026-12-04');
    await expect(workerPage.getByText('Scheduled leave days: 1', { exact: true })).toBeVisible();
    await workerPage.getByRole('button', { name: 'Submit leave request' }).click();
    await expect(workerPage.getByText('Leave request submitted.', { exact: true })).toBeVisible();
    const workerHeaders = { Authorization: `Bearer ${workerSession.accessToken}` };
    const ownLeave = await request.get('/api/v1/hr/me/leave-requests', { headers: workerHeaders });
    expect(ownLeave.status()).toBe(200);
    const original = (await ownLeave.json()).items[0] as { id: string; record_revision: number };
    const returned = await request.post(`/api/v1/hr/leave/requests/${original.id}/decision`, {
      headers: managerHeaders,
      data: {
        decision: 'rejected',
        expected_revision: original.record_revision,
        notes: 'Correct the leave date.'
      }
    });
    expect(returned.status()).toBe(200);
    await workerPage.reload();
    await expect(workerPage.getByText('Correct the leave date.', { exact: true })).toBeVisible();
    await workerPage.getByRole('button', { name: 'Edit leave request', exact: true }).click();
    await expect(workerPage.getByLabel('Leave starts')).toHaveValue('2026-12-04');
    await workerPage.getByLabel('Leave starts').fill('2026-12-07');
    await workerPage.getByLabel('Leave ends').fill('2026-12-07');
    await workerPage.getByRole('button', { name: 'Resubmit leave request', exact: true }).click();
    await expect(workerPage.getByText('Leave request resubmitted.', { exact: true })).toBeVisible();
    await workerPage.reload();
    await expect(workerPage.getByText('2026-12-07 to 2026-12-07', { exact: false })).toBeVisible();
    const reloadedLeave = await request.get('/api/v1/hr/me/leave-requests', {
      headers: workerHeaders
    });
    expect((await reloadedLeave.json()).items).toMatchObject([
      { id: original.id, status: 'submitted' }
    ]);
    await workerPage.getByRole('button', { name: 'Cancel leave' }).click();
    await expect(workerPage.getByText('Leave request cancelled.', { exact: true })).toBeVisible();
    await workerPage.reload();
    await expect(workerPage.getByText('cancelled', { exact: true })).toBeVisible();
    await workerPage.getByLabel('Leave type', { exact: true }).selectOption(leaveTypeId);
    await workerPage.getByLabel('Leave starts').fill('2026-12-16');
    await workerPage.getByLabel('Leave ends').fill('2026-12-16');
    await expect(workerPage.getByText('Scheduled leave days: 1', { exact: true })).toBeVisible();
    await workerPage.getByRole('button', { name: 'Submit leave request' }).click();
    await expect(workerPage.getByText('Leave request submitted.', { exact: true })).toBeVisible();

    await reviewerPage.reload();
    await reviewerPage.getByRole('button', { name: 'Leave', exact: true }).click();
    const approvedLeave = reviewerPage.getByText(/^2026-12-16 → 2026-12-16/).locator('..');
    await approvedLeave.getByRole('button', { name: 'Approve', exact: true }).click();
    await expect(approvedLeave).toContainText('approved');
    await approvedLeave.getByText('Reverse approved leave', { exact: true }).click();
    await approvedLeave.getByRole('textbox', { name: 'Reversal reason' }).fill('Synthetic roster change');
    await approvedLeave.getByRole('button', { name: 'Confirm reversal', exact: true }).click();
    await expect(approvedLeave).toContainText('cancelled');
    const queueStatus = reviewerPage.getByRole('combobox', { name: 'Request status', exact: true });
    await queueStatus.selectOption('approved');
    await expect(approvedLeave).toHaveCount(0);
    await queueStatus.selectOption('cancelled');
    await expect(approvedLeave).toContainText('cancelled');
    await workerPage.reload();
    await expect(workerPage.getByText('Synthetic roster change', { exact: true })).toBeVisible();
    const othersDirectory = await workerPage.request.get('/api/v1/hr/employees', {
      headers: { Authorization: `Bearer ${workerSession.accessToken}` }
    });
    expect(othersDirectory.status()).toBe(403);

    const subject = `Synthetic service request ${unique}`;
    await workerPage.getByRole('combobox', { name: 'Request type', exact: true })
      .selectOption('leave_inquiry');
    await workerPage.getByPlaceholder('Subject', { exact: true }).fill(subject);
    await workerPage.getByRole('button', { name: 'Submit request', exact: true }).click();
    await expect(
      workerPage.getByText('HR service request submitted.', { exact: true })
    ).toBeVisible();
    await managerPage.reload();
    await managerPage.getByRole('button', { name: 'Policies & Requests' }).click();
    const reviewCard = managerPage.getByText(subject).locator('..');
    await expect(reviewCard.getByText('Leave inquiry', { exact: true })).toBeVisible();
    await reviewCard.getByRole('button', { name: 'Start review' }).click();
    await expect(reviewCard).toContainText('(in_review)');
    await reviewCard.getByText('Reassign request', { exact: true }).click();
    await reviewCard.getByLabel('Assign to').selectOption(reviewerSession.userId);
    await reviewCard.getByLabel('Handoff reason').fill('Synthetic shift handoff');
    await reviewCard.getByRole('button', { name: 'Save assignment' }).click();
    await expect(reviewCard.getByRole('button', { name: 'Complete request' })).toHaveCount(0);
    await reviewerPage.reload();
    await reviewerPage.getByRole('button', { name: 'Policies & Requests' }).click();
    const assignedCard = reviewerPage.getByText(subject).locator('..');
    const response = 'Your synthetic request has been reviewed.';
    await assignedCard.getByLabel('Response shared with the employee').fill(response);
    await assignedCard.getByRole('button', { name: 'Complete request' }).click();
    await expect(assignedCard).toContainText('(completed)');
    const requestStatus = reviewerPage.getByRole('combobox', {
      name: 'Service request status', exact: true
    });
    await requestStatus.selectOption('open');
    await expect(assignedCard).toHaveCount(0);
    await requestStatus.selectOption('completed');
    await expect(assignedCard).toContainText('(completed)');
    await workerPage.reload();
    const myRequest = workerPage.getByText(subject).locator('..');
    await expect(myRequest).toContainText(response);
    await myRequest.getByRole('button', { name: /Reopen request/ }).click();
    await expect(
      workerPage.getByText('HR service request reopened.', { exact: true })
    ).toBeVisible();
    await workerPage.reload();
    await expect(myRequest).toContainText('open');
    await expect(myRequest).toContainText(response);
    await expect(myRequest.getByRole('button', { name: /Reopen request/ })).toHaveCount(0);
    const requestList = await request.get('/api/v1/hr/me/requests', { headers: workerHeaders });
    const reopened = (await requestList.json()).items.find(
      (row: { subject: string }) => row.subject === subject
    );
    expect(reopened).toMatchObject({
      status: 'open', assigned_to_id: null, request_type: 'leave_inquiry'
    });
    const runAssignment = (...mode: string[]) =>
      JSON.parse(
        execFileSync(
          PYTHON_BIN,
          [
            '-m',
            'scripts.garrisonctl',
            'hr',
            'request',
            'assign',
            '--request-id',
            reopened.id,
            '--assignee-id',
            reviewerSession.userId,
            '--reason',
            'Synthetic scheduled handoff',
            ...mode,
            '--json'
          ],
          {
            cwd: BACKEND_DIR,
            encoding: 'utf8',
            env: {
              ...env,
              GARRISON_API_BASE_URL: 'http://127.0.0.1:8425',
              GARRISON_ENVIRONMENT: 'test',
              GARRISON_ACCESS_TOKEN: managerSession.accessToken
            }
          }
        )
      );
    const assignmentPlan = runAssignment('--dry-run').data;
    expect(assignmentPlan).toMatchObject({
      previous_assignee: null,
      proposed: { assigned_to_id: reviewerSession.userId }
    });
    expect(runAssignment('--apply', '--expect', assignmentPlan.plan_sha256).data).toMatchObject({
      status: 'open',
      assigned_to_id: reviewerSession.userId
    });
  } finally {
    await directorContext.close();
    await managerContext.close();
    await reviewerContext.close();
    await workerContext.close();
  }
});

test('HR workbook preview shows missing account fields without displaying supplied values', async ({
  page
}) => {
  await signIn(page, seedAccount('hr_manager'));
  await page.getByRole('link', { name: 'HR & Workforce', exact: true }).click();
  await page.getByRole('button', { name: 'Access & Workbook', exact: true }).click();
  await page.getByLabel('Personnel workbook').setInputFiles({
    name: 'synthetic-workbook.csv',
    mimeType: 'text/csv',
    buffer: Buffer.from(
      'User Name,Email,Portal Access Required,Role To Assign,Employee ID,Mobile Number\n' +
      'Synthetic Missing Mobile,workbook-a@example.invalid,Yes,quantity_surveyor,00017,\n' +
      'Synthetic Missing ID,workbook-b@example.invalid,Yes,quantity_surveyor,,+94770000017\n'
    )
  });
  await page.getByRole('button', { name: 'Preview workbook' }).click();
  const issues = page.getByRole('list', { name: 'Workbook issues' });
  const rowWithMissingMobile = issues.getByRole('listitem').filter({
    has: page.getByText('Synthetic Missing Mobile', { exact: true })
  });
  await expect(rowWithMissingMobile.getByText('Missing Mobile Number for account onboarding.'))
    .toBeVisible();
  const rowWithMissingId = issues.getByRole('listitem').filter({
    has: page.getByText('Synthetic Missing ID', { exact: true })
  });
  await expect(rowWithMissingId.getByText('Missing Employee ID for account onboarding.'))
    .toBeVisible();
  await expect(issues).not.toContainText('00017');
  await expect(page.getByRole('button', { name: 'Apply workbook reconciliation' })).toBeVisible();
  await page.getByLabel('Role mappings').fill('{"Estimator":"quantity_surveyor"}');
  await expect(page.getByRole('button', { name: 'Apply workbook reconciliation' })).toHaveCount(0);
});

test('HR closes offboarding and independently reviews rehire', async ({
  page,
  browser,
  request
}) => {
  const [director, manager] = seedProjectAccounts('managing_director', 'hr_manager');
  const session = await signIn(page, manager);
  const headers = { Authorization: `Bearer ${session.accessToken}` };
  const marker = `Custody-${Date.now()}`;
  const employee = await request.post('/api/v1/hr/employees', {
    headers,
    data: {
      employee_code: marker,
      first_name: 'Synthetic',
      last_name: marker,
      join_date: '2025-01-01',
      employment_status: 'active'
    }
  });
  expect(employee.status()).toBe(201);
  const employeeId = (await employee.json()).id as string;
  const started = await request.post('/api/v1/hr/offboarding', {
    headers,
    data: {
      employee_id: employeeId,
      separation_type: 'resignation',
      last_working_date: '2026-07-31'
    }
  });
  expect(started.status()).toBe(201);
  const record = (await started.json()) as {
    id: string;
    steps: Array<{ id: string; department_area: string }>;
  };
  for (const step of record.steps.filter(
    (entry) => !['store_inventory', 'it_admin', 'finance_accounts'].includes(entry.department_area)
  )) {
    const result = await request.patch(`/api/v1/hr/offboarding/steps/${step.id}`, {
      headers,
      data: { status: 'cleared', notes: 'Synthetic clearance' }
    });
    expect(result.status()).toBe(200);
  }
  await page.getByRole('link', { name: 'HR & Workforce', exact: true }).click();
  await page.getByRole('button', { name: 'Policies & Requests' }).click();
  const card = page.getByRole('article').filter({ hasText: marker });
  await card.getByText('Inventory custody evidence', { exact: true }).click();
  await expect(card.getByText('No custody evidence recorded.')).toBeVisible();
  await expect(card.getByText(record.id, { exact: true })).toBeVisible();
  await expect(card.getByRole('button', { name: 'Record clearance' })).toHaveCount(0);
  await expect(card.getByRole('button', { name: 'Complete offboarding' })).toHaveCount(0);

  const directorContext = await browser.newContext();
  try {
    const directorPage = await directorContext.newPage();
    const owner = await signIn(directorPage, director);
    const posted = await request.post(`/api/v1/hr/offboarding/${record.id}/custody`, {
      headers: { Authorization: `Bearer ${owner.accessToken}` },
      data: {
        event_id: crypto.randomUUID(),
        kind: 'cleared',
        evidence_reference: 'STORE-BROWSER-1'
      }
    });
    expect(posted.status()).toBe(200);

    await directorPage.getByRole('link', { name: 'HR & Workforce', exact: true }).click();
    await directorPage.getByRole('button', { name: 'Access & Workbook', exact: true }).click();
    await directorPage.getByLabel('Offboarding case ID').fill(record.id);
    await directorPage.getByRole('button', { name: 'Open offboarding case' }).click();
    const handover = directorPage.getByRole('region', { name: 'Offboarding IT handover' });
    await handover.getByLabel('Device reference').fill('fixture-laptop');
    await handover.getByLabel('IT evidence reference').fill('IT-PENDING-CHROME');
    await handover.getByRole('button', { name: 'Record IT custody' }).click();
    await expect(handover.getByText('Outstanding devices 1')).toBeVisible();
    await expect(handover.getByRole('option', { name: 'Sign off IT handover' })).toBeDisabled();

    await handover.getByLabel('IT custody action').selectOption('returned');
    await handover.getByLabel('Device reference').fill('FIXTURE-LAPTOP');
    await handover.getByLabel('IT evidence reference').fill('IT-RETURNED-CHROME');
    await handover.getByRole('button', { name: 'Record IT custody' }).click();
    await expect(handover.getByText('Outstanding devices 0')).toBeVisible();
    await handover.getByLabel('IT custody action').selectOption('cleared');
    await handover.getByLabel('IT evidence reference').fill('IT-SIGNOFF-CHROME');
    await handover.getByRole('button', { name: 'Record IT custody' }).click();
    await expect(handover.getByText('Current custody status cleared')).toBeVisible();

    const finances = directorPage.getByRole('region', { name: 'Offboarding Finance settlement' });
    await finances.getByText('Finance settlement evidence', { exact: true }).click();
    await finances.getByLabel('Settlement outcome').selectOption('nothing_due');
    await finances.getByLabel('Settlement evidence reference').fill('FIN-CHROME-01');
    await finances.getByRole('button', { name: 'Propose settlement' }).click();
    await expect(finances.getByText(/Nothing due · proposed · FIN-CHROME-01/)).toBeVisible();
    await expect(
      finances.getByText('A different director must review this proposal.')
    ).toBeVisible();
    await expect(finances.getByRole('button', { name: 'Record settlement review' })).toHaveCount(0);
  } finally {
    await directorContext.close();
  }
  await card.getByRole('button', { name: 'Refresh custody evidence' }).click();
  await expect(card.getByText(/cleared · STORE-BROWSER-1/)).toBeVisible();
  await card.getByText('IT handover evidence', { exact: true }).click();
  await expect(card.getByText(/cleared · IT-SIGNOFF-CHROME/)).toBeVisible();
  await expect(
    card.getByText(/returned · IT-RETURNED-CHROME · Device FIXTURE-LAPTOP/)
  ).toBeVisible();
  await expect(card.getByRole('button', { name: 'Record IT custody' })).toHaveCount(0);
  await card.getByText('Finance settlement evidence', { exact: true }).click();
  await expect(card.getByText(/Nothing due · proposed · FIN-CHROME-01/)).toBeVisible();
  await expect(card.getByRole('button', { name: 'Complete offboarding' })).toHaveCount(0);
  const settlementContext = await browser.newContext();
  try {
    const reviewerPage = await settlementContext.newPage();
    const financeReviewer = seedAccount('operations_director', director.projectId);
    await signIn(reviewerPage, financeReviewer);
    await reviewerPage.getByRole('link', { name: 'HR & Workforce', exact: true }).click();
    await reviewerPage.getByRole('button', { name: 'Access & Workbook', exact: true }).click();
    await reviewerPage.getByLabel('Offboarding case ID').fill(record.id);
    await reviewerPage.getByRole('button', { name: 'Open offboarding case' }).click();
    const finances = reviewerPage.getByRole('region', { name: 'Offboarding Finance settlement' });
    await finances.getByText('Finance settlement evidence', { exact: true }).click();
    await finances.getByLabel('Settlement decision').selectOption('approved');
    await finances.getByLabel('Settlement review reference').fill('FIN-CHROME-REVIEW');
    await finances.getByRole('button', { name: 'Record settlement review' }).click();
    await expect(finances.getByText('Finance clearance cleared')).toBeVisible();
  } finally {
    await settlementContext.close();
  }
  await card.getByRole('button', { name: 'Refresh settlement evidence' }).click();
  await expect(
    card.getByText(/Nothing due · approved · FIN-CHROME-01 · Review FIN-CHROME-REVIEW/)
  ).toBeVisible();
  await expect(card.getByRole('button', { name: 'Record settlement review' })).toHaveCount(0);
  await card.getByLabel('Rehire eligibility').selectOption('yes');
  await card.getByRole('button', { name: 'Complete offboarding' }).click();
  await expect(card.getByText('2026-07-31 · completed')).toBeVisible();
  await page.reload();
  await page.getByRole('button', { name: 'Policies & Requests' }).click();
  await expect(card.getByText('2026-07-31 · completed')).toBeVisible();
  const result = await request.get(`/api/v1/hr/offboarding/${record.id}/custody`, { headers });
  expect(result.status()).toBe(200);
  expect((await result.json()).case_closed).toBe(true);

  async function openEmployment(target: Page, navigate: boolean) {
    if (navigate) await target.getByRole('link', { name: 'HR & Workforce', exact: true }).click();
    await target.getByRole('button', { name: 'Directory & Org' }).click();
    await target.getByLabel('Search employees').fill(marker);
    await target
      .getByRole('row')
      .filter({ hasText: marker })
      .getByRole('button', { name: 'Inspect' })
      .click();
    await target.getByText('Reviewed employment changes', { exact: true }).click();
  }

  await openEmployment(page, false);
  const effective = new Intl.DateTimeFormat('sv-SE', { timeZone: 'Asia/Qatar' }).format(new Date());
  await expect(page.getByText('2025-01-01 to 2026-07-31')).toBeVisible();
  await page.getByLabel('Rehire employment category').selectOption('permanent');
  await page.getByLabel('Effective date', { exact: true }).fill(effective);
  await page.getByLabel('Employment change reason').fill('Synthetic independently reviewed return');
  await page.getByRole('button', { name: 'Propose rehire' }).click();
  await expect(page.getByRole('heading', { name: /Rehire .* proposed/ })).toBeVisible();
  await expect(page.getByRole('button', { name: 'Approve employment change' })).toHaveCount(0);

  const reviewerContext = await browser.newContext();
  try {
    const reviewerPage = await reviewerContext.newPage();
    const reviewer = await signIn(reviewerPage, seedAccount('hr_manager', director.projectId));
    await openEmployment(reviewerPage, true);
    await reviewerPage.getByRole('button', { name: 'Approve employment change' }).click();
    await reviewerPage.getByRole('button', { name: 'Apply due employment change' }).click();
    await expect(reviewerPage.getByRole('heading', { name: /Rehire .* applied/ })).toBeVisible();
    await expect(reviewerPage.getByText(`${effective} to present`)).toBeVisible();
    await reviewerPage.reload();
    await openEmployment(reviewerPage, false);
    await expect(reviewerPage.getByText(`${effective} to present`)).toBeVisible();
    await expect(reviewerPage.getByText('2025-01-01 to 2026-07-31')).toBeVisible();
    await expect(reviewerPage.getByText(/Status: onboarding/)).toBeVisible();
    const cli = JSON.parse(
      execFileSync(
        PYTHON_BIN,
        [
          '-m',
          'scripts.garrisonctl',
          'hr',
          'employees',
          'periods',
          '--employee-id',
          employeeId,
          '--json'
        ],
        {
          cwd: BACKEND_DIR,
          encoding: 'utf8',
          env: {
            ...env,
            GARRISON_API_BASE_URL: 'http://127.0.0.1:8425',
            GARRISON_ENVIRONMENT: 'test',
            GARRISON_ACCESS_TOKEN: reviewer.accessToken
          }
        }
      )
    ).data;
    expect(cli.total).toBe(2);
    expect(cli.items).toMatchObject([
      { started_on: effective, ended_on: null, onboarding_case_id: expect.any(String) },
      { started_on: '2025-01-01', ended_on: '2026-07-31', separation_case_id: record.id }
    ]);
  } finally {
    await reviewerContext.close();
  }
});

test('HR verifies training against an independently approved certificate', async ({
  page,
  browser,
  request
}) => {
  const [account, worker] = seedProjectAccounts('hr_manager', 'quantity_surveyor');
  const session = await signIn(page, account);
  const marker = `Training-${Date.now()}`;
  const trainingDate = '2026-06-01';
  const position = await request.post('/api/v1/hr/positions', {
    headers: { Authorization: `Bearer ${session.accessToken}` },
    data: { code: marker, title: `Position ${marker}` }
  });
  expect(position.status()).toBe(201);
  const { id: positionId } = (await position.json()) as { id: string };
  const employee = await request.post('/api/v1/hr/employees', {
    headers: { Authorization: `Bearer ${session.accessToken}` },
    data: {
      employee_code: marker,
      first_name: 'Synthetic',
      last_name: marker,
      work_email: worker.email,
      position_id: positionId,
      employment_status: 'active'
    }
  });
  expect(employee.status()).toBe(201);
  const { id: employeeId } = (await employee.json()) as { id: string };

  async function selectTrainingEmployee() {
    await page.getByRole('button', { name: 'Training', exact: true }).click();
    await page.getByLabel('Search training employee').fill(marker);
    await page
      .getByRole('combobox', { name: 'Training employee', exact: true })
      .selectOption(employeeId);
  }

  await page.getByRole('link', { name: 'HR & Workforce', exact: true }).click();
  await selectTrainingEmployee();
  await page.getByLabel('Course code').fill(marker);
  await page.getByLabel('Course title').fill(`Safety ${marker}`);
  await page.getByRole('button', { name: 'Create course' }).click();
  await expect(page.getByText(`${marker} · Safety ${marker}`)).toBeVisible();
  await page.getByText('Mandatory training rules', { exact: true }).click();
  await page
    .getByRole('combobox', { name: 'Required course', exact: true })
    .selectOption({ label: `Safety ${marker}` });
  await page.getByRole('combobox', { name: 'Required job position' }).selectOption(positionId);
  await page.getByRole('button', { name: 'Save training rule' }).click();
  const mandatory = page.getByRole('region', { name: 'Mandatory training', exact: true });
  await expect(mandatory.getByText(`Safety ${marker} · Required`)).toBeVisible();
  await page
    .getByRole('combobox', { name: 'Enrollment course' })
    .selectOption({ label: `Safety ${marker}` });
  await page.getByLabel('Scheduled training date').fill(trainingDate);
  await page.getByRole('button', { name: 'Enroll employee' }).click();
  const enrollment = page.getByRole('article').filter({ hasText: `Safety ${marker}` });
  await expect(enrollment.getByText('Enrollment enrolled')).toBeVisible();
  await expect(enrollment.getByRole('button', { name: 'Verify completion' })).toBeDisabled();
  await enrollment
    .getByRole('combobox', { name: 'Enrollment status', exact: true })
    .selectOption('in_progress');
  await enrollment.getByRole('button', { name: 'Update enrollment' }).click();
  await expect(enrollment.getByText('Enrollment in progress')).toBeVisible();
  await page.reload();
  await selectTrainingEmployee();
  await expect(enrollment.getByText('Enrollment in progress')).toBeVisible();

  await page.getByLabel('Certificate title').fill(`Credential ${marker}`);
  await page.getByLabel('Certificate issue date').fill(trainingDate);
  await page.getByLabel('Certificate expiry').fill('2026-07-01');
  await page.getByLabel('Certificate PDF').setInputFiles({
    name: 'training.pdf',
    mimeType: 'application/pdf',
    buffer: Buffer.from('%PDF-1.4\n% synthetic certificate\n%%EOF\n')
  });
  const saved = page.waitForResponse(
    (response) =>
      new URL(response.url()).pathname === '/api/v1/hr/documents' &&
      response.request().method() === 'POST'
  );
  await page.getByRole('button', { name: 'Upload training certificate' }).click();
  const uploaded = await saved;
  expect(uploaded.status()).toBe(201);
  const document = (await uploaded.json()) as { id: string };
  const reviewerContext = await browser.newContext();
  try {
    const reviewer = await signIn(
      await reviewerContext.newPage(),
      seedAccount('hr_manager', account.projectId)
    );
    const approved = await request.post(`/api/v1/hr/documents/${document.id}/versions/1/decision`, {
      headers: { Authorization: `Bearer ${reviewer.accessToken}` },
      data: { decision: 'approve' }
    });
    expect(approved.status()).toBe(200);
  } finally {
    await reviewerContext.close();
  }

  await page.reload();
  await selectTrainingEmployee();
  await enrollment
    .getByRole('combobox', { name: 'Approved training certificate' })
    .selectOption(document.id);
  await enrollment.getByLabel('Training completion date').fill(trainingDate);
  await enrollment.getByLabel('Training score').fill('95');
  const savedCompletion = page.waitForResponse(
    (response) =>
      response.request().method() === 'POST' &&
      new URL(response.url()).pathname.endsWith('/completion')
  );
  await enrollment.getByRole('button', { name: 'Verify completion' }).click();
  const completionResponse = await savedCompletion;
  expect(completionResponse.status()).toBe(200);
  const completion = (await completionResponse.json()) as { enrollment_id: string };

  await expect(enrollment.getByText('Verified certificate version 1 · 2026-06-01')).toBeVisible();
  await expect(page.getByText(`Credential ${marker} · expired · 2026-07-01`)).toBeVisible();

  await page.reload();
  await selectTrainingEmployee();
  await enrollment.getByRole('button', { name: 'Show verified receipt' }).click();
  await expect(enrollment.getByText('Verified certificate version 1 · 2026-06-01')).toBeVisible();
  await expect(enrollment.getByRole('button', { name: 'Update enrollment' })).toHaveCount(0);
  const receipt = JSON.parse(
    execFileSync(
      PYTHON_BIN,
      [
        '-m',
        'scripts.garrisonctl',
        'hr',
        'training',
        'completion',
        'show',
        '--enrollment-id',
        completion.enrollment_id,
        '--json'
      ],
      {
        cwd: BACKEND_DIR,
        encoding: 'utf8',
        env: {
          ...env,
          GARRISON_API_BASE_URL: 'http://127.0.0.1:8425',
          GARRISON_ENVIRONMENT: 'test',
          GARRISON_ACCESS_TOKEN: session.accessToken
        }
      }
    )
  ).data;
  expect(receipt).toMatchObject({
    enrollment_id: completion.enrollment_id,
    document_id: document.id,
    version_number: 1
  });

  const employeeContext = await browser.newContext();
  const directorContext = await browser.newContext();
  try {
    const workerPage = await employeeContext.newPage();
    const linked = await signIn(workerPage, worker);
    const director = await signIn(await directorContext.newPage(), seedAccount());
    const link = await request.post(`/api/v1/hr/employees/${employeeId}/link-account`, {
      headers: { Authorization: `Bearer ${director.accessToken}` },
      data: { user_id: linked.userId }
    });
    expect(link.status()).toBe(200);
    await workerPage.goto('/me/hr');
    await workerPage.getByText('My training', { exact: true }).click();
    await expect(workerPage.getByText(`Safety ${marker} · completed`)).toBeVisible();
    await expect(workerPage.getByText('Certificate expired 2026-07-01')).toBeVisible();
    await expect(workerPage.getByText(`Safety ${marker} · Expired`)).toBeVisible();
    await expect(workerPage.getByRole('button', { name: 'Verify completion' })).toHaveCount(0);
  } finally {
    await employeeContext.close();
    await directorContext.close();
  }
});

test('employee and manager complete a scoped performance review with HR calibration', async ({
  page,
  browser,
  request
}) => {
  const hr = await signIn(page, seedAccount('hr_manager'));
  const headers = { Authorization: `Bearer ${hr.accessToken}` };
  const marker = `Review-${Date.now()}`;
  const employeeAccount = seedAccount('quantity_surveyor');
  const managerAccount = seedAccount('group_project_manager');
  const successorAccount = seedAccount('mep_project_manager');
  const directorContext = await browser.newContext();
  const employeeContext = await browser.newContext();
  const managerContext = await browser.newContext();
  const successorContext = await browser.newContext();
  try {
    const director = await signIn(await directorContext.newPage(), seedAccount());
    const employeePage = await employeeContext.newPage();
    const managerPage = await managerContext.newPage();
    const successorPage = await successorContext.newPage();
    const employee = await signIn(employeePage, employeeAccount);
    const manager = await signIn(managerPage, managerAccount);
    const successor = await signIn(successorPage, successorAccount);

    async function link(email: string, userId: string, suffix: string, managerId?: string) {
      const created = await request.post('/api/v1/hr/employees', {
        headers,
        data: {
          employee_code: `${marker}-${suffix}`,
          first_name: 'Synthetic',
          last_name: `${marker} ${suffix}`,
          work_email: email,
          employment_status: 'active',
          manager_employee_id: managerId
        }
      });
      expect(created.status()).toBe(201);
      const { id } = (await created.json()) as { id: string };
      const linked = await request.post(`/api/v1/hr/employees/${id}/link-account`, {
        headers: { Authorization: `Bearer ${director.accessToken}` },
        data: { user_id: userId }
      });
      expect(linked.status()).toBe(200);
      return id;
    }

    const managerId = await link(managerAccount.email, manager.userId, 'manager');
    const successorId = await link(successorAccount.email, successor.userId, 'successor');
    const employeeId = await link(employeeAccount.email, employee.userId, 'employee', managerId);
    const record = await request.get(`/api/v1/hr/employees/${employeeId}`, { headers });
    const permission = await request.put(`/api/v1/hr/employees/${employeeId}/manager-review`, {
      headers,
      data: { enabled: true, expected_revision: (await record.json()).record_revision }
    });
    expect(permission.status()).toBe(200);

    await page.getByRole('link', { name: 'HR & Workforce', exact: true }).click();
    await page.getByRole('button', { name: 'Performance', exact: true }).click();
    await page.getByLabel('Cycle code').fill(marker);
    await page.getByLabel('Cycle name').fill(marker);
    await page.getByLabel('Cycle starts').fill('2026-01-01');
    await page.getByLabel('Cycle ends').fill('2026-12-31');
    await page
      .getByLabel('Rating labels (one per line, optional)')
      .fill('Developing\nEstablished\nAdvanced');
    await page.getByRole('button', { name: 'Create review cycle' }).click();
    await page.getByLabel('Search review employee').fill(`${marker}-employee`);
    await page.getByRole('combobox', { name: 'Review employee' }).selectOption(employeeId);
    await page.getByRole('combobox', { name: 'Review cycle' }).selectOption({ label: marker });
    await page.getByLabel('Goal title').fill('Confirm completion evidence');
    await page.getByRole('button', { name: 'Add goal' }).click();
    await page.getByRole('button', { name: 'Open draft review' }).click();

    async function openReview(target: Page, self: boolean) {
      if (self) await target.goto('/me/hr');
      await target.getByText('Performance reviews', { exact: true }).click();
      await target
        .getByRole('button', { name: new RegExp(`Synthetic ${marker} employee`) })
        .click();
      await expect(target.getByText('Confirm completion evidence', { exact: true })).toBeVisible();
    }

    async function act(target: Page, action: string, notes?: string, rating?: string) {
      const review = target.getByRole('region', { name: 'Selected performance review' });
      await review.getByRole('combobox', { name: 'Review action' }).selectOption(action);
      if (notes) await review.getByLabel('Review notes').fill(notes);
      if (rating)
        await review.getByRole('combobox', { name: 'Review rating' }).selectOption(rating);
      const write = target.waitForResponse(
        (response) =>
          response.request().method() === 'POST' &&
          new URL(response.url()).pathname.endsWith('/actions')
      );
      await review.getByRole('button', { name: 'Record review action' }).click();
      expect((await write).status()).toBe(200);
    }

    await openReview(employeePage, true);
    await act(employeePage, 'acknowledge_goals');
    await openReview(managerPage, true);
    await act(managerPage, 'acknowledge_goals');
    await employeePage.getByRole('button', { name: 'Refresh reviews' }).click();
    await act(employeePage, 'submit_self_review', 'Synthetic employee feedback', 'Developing');
    await managerPage.getByRole('button', { name: 'Refresh reviews' }).click();
    await act(managerPage, 'submit_manager_review', 'Synthetic manager assessment', 'Established');
    await employeePage.getByRole('button', { name: 'Refresh reviews' }).click();
    await expect(employeePage.getByText('Synthetic manager assessment')).toHaveCount(0);
    const current = await request.get(`/api/v1/hr/employees/${employeeId}`, { headers });
    const changed = await request.patch(`/api/v1/hr/employees/${employeeId}`, {
      headers,
      data: {
        manager_employee_id: successorId,
        expected_revision: (await current.json()).record_revision
      }
    });
    expect(changed.status()).toBe(200);
    const enabled = await request.put(`/api/v1/hr/employees/${employeeId}/manager-review`, {
      headers,
      data: { enabled: true, expected_revision: (await changed.json()).record_revision }
    });
    expect(enabled.status()).toBe(200);
    await openReview(page, false);
    await act(page, 'reassign_manager', 'Synthetic authorized manager change');
    await openReview(successorPage, true);
    await act(successorPage, 'acknowledge_goals');
    await act(successorPage, 'submit_manager_review', 'Synthetic successor assessment', 'Advanced');
    await page.getByRole('button', { name: 'Refresh reviews' }).click();
    await act(page, 'calibrate', 'Synthetic calibrated outcome', 'Advanced');
    await employeePage.getByRole('button', { name: 'Refresh reviews' }).click();
    await expect(employeePage.getByText('Synthetic successor assessment')).toBeVisible();
    await expect(employeePage.getByText('Synthetic manager assessment')).toHaveCount(0);
    await act(employeePage, 'acknowledge_final');
    await expect(employeePage.getByRole('heading', { name: `${marker} · closed` })).toBeVisible();
    await page.getByRole('button', { name: 'Refresh reviews' }).click();
    await act(page, 'add_addendum', 'Synthetic correction kept as an addendum');
    await openReview(employeePage, true);
    await expect(employeePage.getByText('Synthetic calibrated outcome')).toBeVisible();
    await expect(employeePage.getByText('Synthetic correction kept as an addendum')).toBeVisible();
  } finally {
    await directorContext.close();
    await employeeContext.close();
    await managerContext.close();
    await successorContext.close();
  }
});

test('HR plans and cancels a roster allocation using a published schedule', async ({
  page,
  browser,
  request
}) => {
  const site = seedAccount();
  const hr = await signIn(page, seedAccount('hr_manager', site.projectId));
  const headers = { Authorization: `Bearer ${hr.accessToken}` };
  const reviewerContext = await browser.newContext();
  const privateDir = mkdtempSync(join(tmpdir(), 'garrison-roster-cli-'));
  try {
    const reviewer = await signIn(
      await reviewerContext.newPage(),
      seedAccount('hr_manager', site.projectId)
    );
    const reviewerHeaders = { Authorization: `Bearer ${reviewer.accessToken}` };
    const marker = `Roster-${Date.now().toString(36)}`;
    const date = '2027-01-04';
    const calendarResponse = await request.post('/api/v1/hr/calendars', {
      headers,
      data: {
        code: marker,
        name: 'Synthetic roster calendar',
        project_id: site.projectId,
        work_days_json: ['MON'],
        standard_start_time: '07:30',
        standard_end_time: '16:30',
        daily_hours: '7.50',
        effective_from: date,
        effective_to: date,
        timezone: 'Asia/Colombo'
      }
    });
    expect(calendarResponse.status()).toBe(201);
    let calendar = (await calendarResponse.json()) as { id: string; revision: number };
    for (const action of ['submit', 'approve', 'publish']) {
      const decision = await request.post(`/api/v1/hr/calendars/${calendar.id}/decision`, {
        headers: action === 'submit' ? headers : reviewerHeaders,
        data: { action, expected_revision: calendar.revision }
      });
      expect(decision.status()).toBe(200);
      calendar = (await decision.json()) as typeof calendar;
    }
    const employeeResponse = await request.post('/api/v1/hr/employees', {
      headers,
      data: {
        employee_code: marker,
        first_name: 'Synthetic',
        last_name: marker,
        join_date: '2026-01-01',
        primary_project_id: site.projectId,
        employment_status: 'active'
      }
    });
    expect(employeeResponse.status()).toBe(201);
    const employee = (await employeeResponse.json()) as { id: string };

    await page.getByRole('link', { name: 'HR & Workforce' }).click();
    await page.getByRole('button', { name: 'Attendance', exact: true }).click();
    await page.getByRole('searchbox', { name: 'Find roster employee' }).fill(marker);
    await page.getByRole('combobox', { name: 'Roster employee' }).selectOption(employee.id);
    await page.getByRole('searchbox', { name: 'Find roster project' }).fill(site.projectCode);
    await page.getByRole('combobox', { name: 'Roster project' }).selectOption(site.projectId);
    await page.getByLabel('Allocation date').fill(date);
    await page.getByRole('button', { name: 'Allocate shift' }).click();
    const allocation = page.getByRole('listitem').filter({ hasText: `Synthetic ${marker}` });
    await expect(allocation).toContainText('7.50 planned hours');
    await page.getByRole('button', { name: 'Allocate shift' }).click();
    await expect(
      page.getByRole('alert').filter({ hasText: 'overlapping allocation' })
    ).toBeVisible();
    await allocation.getByRole('button', { name: 'Cancel allocation' }).click();
    await page.getByLabel('Roster cancellation reason').fill('Synthetic reschedule');
    await page.getByRole('button', { name: 'Confirm roster cancellation' }).click();
    await expect(allocation).toContainText('Cancelled · Synthetic reschedule');

    type Roster = {
      id: string; calendar_id: string; planned_hours: string; cancelled_at: string | null;
      cancellation_reason?: string; employee_name?: string;
    };
    function rosterCli(...args: string[]) {
      return JSON.parse(execFileSync(
        PYTHON_BIN, ['-m', 'scripts.garrisonctl', 'hr', 'roster', ...args, '--json'], {
          cwd: BACKEND_DIR,
          encoding: 'utf8',
          env: {
            ...env, GARRISON_API_BASE_URL: 'http://127.0.0.1:8425',
            GARRISON_ENVIRONMENT: 'test', GARRISON_ACCESS_TOKEN: hr.accessToken
          }
        }
      )) as { data: Roster & { plan_sha256: string; items: Roster[]; total: number } };
    }
    const replacementId = globalThis.crypto.randomUUID();
    const replacementArgs = ['--allocation-id', replacementId];
    const allocate = [
      'allocate', ...replacementArgs, '--employee-id', employee.id,
      '--project-id', site.projectId, '--work-date', date
    ];
    const allocationPlan = rosterCli(...allocate, '--dry-run');
    const allocated = rosterCli(...allocate, '--apply', '--expect', allocationPlan.data.plan_sha256);
    expect(allocated.data).toMatchObject({
      id: replacementId, calendar_id: calendar.id, planned_hours: '7.50', cancelled_at: null
    });
    expect(allocated.data.employee_name).toBeUndefined();
    expect(rosterCli(...allocate, '--apply', '--expect', allocationPlan.data.plan_sha256).data)
      .toEqual(allocated.data);
    const cancellationPath = join(privateDir, 'cancel.json');
    writeFileSync(cancellationPath, JSON.stringify({ reason: 'Synthetic CLI cancellation' }), {
      mode: 0o600
    });
    const cancel = ['cancel', ...replacementArgs, '--file', cancellationPath];
    const cancellationPlan = rosterCli(...cancel, '--dry-run');
    const cancelled = rosterCli(...cancel, '--apply', '--expect', cancellationPlan.data.plan_sha256);
    expect(cancelled.data.cancelled_at).toBeTruthy();
    expect(cancelled.data.cancellation_reason).toBeUndefined();
    expect(rosterCli('show', ...replacementArgs).data.cancellation_reason).toBe(
      'Synthetic CLI cancellation'
    );
    const listed = rosterCli(
      'list', '--date-from', date, '--date-to', date, '--employee-id', employee.id
    );
    expect(listed.data.total).toBe(2);
    expect(listed.data.items.find((item) => item.id === replacementId)?.cancelled_at).toBeTruthy();

    await page.reload();
    await page.getByRole('button', { name: 'Attendance', exact: true }).click();
    await page.getByLabel('Roster from').fill(date);
    await page.getByLabel('Roster to').fill(date);
    await page.getByRole('button', { name: 'View roster' }).click();
    await expect(allocation.filter({ hasText: 'Cancelled · Synthetic reschedule' })).toBeVisible();
    await expect(allocation.filter({ hasText: 'Cancelled · Synthetic CLI cancellation' })).toBeVisible();
  } finally {
    rmSync(privateDir, { recursive: true, force: true });
    await reviewerContext.close();
  }
});

test('HR independently corrects an employee name and stale My HR edits are rejected', async ({
  page,
  browser,
  request
}) => {
  const director = seedAccount();
  const maker = await signIn(page, seedAccount('hr_manager', director.projectId));
  const owner = seedAccount('quantity_surveyor', director.projectId);
  const makerHeaders = { Authorization: `Bearer ${maker.accessToken}` };
  const directorContext = await browser.newContext();
  const checkerContext = await browser.newContext();
  const ownerContext = await browser.newContext();
  try {
    const directorSession = await signIn(await directorContext.newPage(), director);
    const checkerPage = await checkerContext.newPage();
    await signIn(checkerPage, seedAccount('hr_manager', director.projectId));
    const ownerPage = await ownerContext.newPage();
    const employeeSession = await signIn(ownerPage, owner);
    const code = `EMP-PROFILE-${Date.now().toString(36)}`;
    const created = await request.post('/api/v1/hr/employees', {
      headers: makerHeaders,
      data: {
        employee_code: code,
        first_name: 'Synthetic',
        last_name: 'Prior',
        employment_status: 'active',
        work_email: owner.email,
        join_date: '2025-01-01'
      }
    });
    expect(created.status()).toBe(201);
    const employee = (await created.json()) as { id: string };
    const employeePath = `/api/v1/hr/employees/${employee.id}`;
    const linked = await request.post(`${employeePath}/link-account`, {
      headers: { Authorization: `Bearer ${directorSession.accessToken}` },
      data: { user_id: employeeSession.userId }
    });
    expect(linked.status()).toBe(200);

    async function openEmployee(target: Page) {
      await target.getByRole('link', { name: 'HR & Workforce', exact: true }).click();
      await target.getByRole('button', { name: 'Directory & Org' }).click();
      await target.getByLabel('Search employees').fill(code);
      await target
        .getByRole('row')
        .filter({ hasText: code })
        .getByRole('button', { name: 'Inspect' })
        .click();
      await target.getByText('Reviewed employment changes', { exact: true }).click();
    }

    await ownerPage.getByRole('link', { name: 'My HR', exact: true }).click();
    const contact = ownerPage.getByLabel('Personal Phone', { exact: true });
    await contact.fill('000777');

    await openEmployee(page);
    await page
      .getByRole('combobox', { name: 'Change type', exact: true })
      .selectOption('profile_correction');
    await page.getByLabel('Corrected last name').fill('Corrected');
    const today = new Intl.DateTimeFormat('sv-SE', { timeZone: 'Asia/Qatar' }).format(new Date());
    await page.getByLabel('Effective date', { exact: true }).fill(today);
    await page.getByLabel('Employment change reason').fill('Synthetic verified name correction');
    await page.getByRole('button', { name: 'Propose employment change' }).click();
    await expect(
      page.getByRole('heading', { name: /Profile name correction .* proposed/ })
    ).toBeVisible();
    await expect(page.getByRole('button', { name: 'Approve employment change' })).toHaveCount(0);
    await openEmployee(checkerPage);
    await checkerPage.getByRole('button', { name: 'Approve employment change' }).click();
    await checkerPage.getByRole('button', { name: 'Apply due employment change' }).click();
    await expect(
      checkerPage.getByRole('heading', { name: /Profile name correction .* applied/ })
    ).toBeVisible();

    await ownerPage.getByRole('button', { name: 'Save contact details' }).click();
    await expect(
      ownerPage.getByRole('alert').filter({ hasText: 'The profile changed after you opened it' })
    ).toBeVisible();
    await expect(contact).toHaveValue('000777');
    await ownerPage
      .getByRole('button', { name: 'Discard edits and reload contact details' })
      .click();
    await expect(contact).toHaveValue('');
    await contact.fill('000888');
    await ownerPage.getByRole('button', { name: 'Save contact details' }).click();
    await expect(ownerPage.getByText('Personal HR contact details updated.')).toBeVisible();
    await ownerPage.reload();
    await expect(contact).toHaveValue('000888');
    const result = await request.get(employeePath, { headers: makerHeaders });
    expect(await result.json()).toMatchObject({ full_name: 'Synthetic Corrected' });

    const nationalId = checkerPage.getByRole('textbox', { name: 'Update National ID' });
    await nationalId.fill('SYNTHETIC-TEST-5331');
    await checkerPage.getByRole('button', { name: 'Encrypt & Save' }).click();
    await expect(
      checkerPage.getByText('The profile changed after you opened it.', { exact: false })
    ).toBeVisible();
    await expect(nationalId).toHaveValue('SYNTHETIC-TEST-5331');
    await checkerPage.getByRole('button', { name: 'Reload private vault' }).click();
    await checkerPage.getByRole('button', { name: 'Encrypt & Save' }).click();
    await expect(checkerPage.getByText(/National ID:.*5331/)).toBeVisible();
    await expect(nationalId).toHaveValue('');
  } finally {
    await Promise.all([directorContext.close(), checkerContext.close(), ownerContext.close()]);
  }
});

test('HR withdraws an application with a retention decision and cancels its interview', async ({
  page,
  request
}) => {
  const session = await signIn(page, seedAccount('hr_manager'));
  const headers = { Authorization: `Bearer ${session.accessToken}` };
  const marker = `Withdrawal-${Date.now().toString(36)}`;
  const req = await request.post('/api/v1/hr/requisitions', {
    headers,
    data: { requisition_code: marker, title: 'Synthetic position' }
  });
  expect(req.status()).toBe(201);
  const reqId = (await req.json()).id as string;
  for (const step of ['submitted', 'approved', 'open']) {
    const decision = await request.post(`/api/v1/hr/requisitions/${reqId}/decision`, {
      headers,
      data: { status: step }
    });
    expect(decision.status()).toBe(200);
  }
  const candidate = await request.post('/api/v1/hr/candidates', {
    headers,
    data: { candidate_code: marker, full_name: `Synthetic ${marker}` }
  });
  expect(candidate.status()).toBe(201);
  const application = await request.post('/api/v1/hr/applications', {
    headers,
    data: { requisition_id: reqId, candidate_id: (await candidate.json()).id }
  });
  expect(application.status()).toBe(201);
  const appId = (await application.json()).id as string;
  await page.getByRole('link', { name: 'HR & Workforce', exact: true }).click();
  await page.getByRole('button', { name: 'Recruitment', exact: true }).click();
  const card = page.getByRole('article').filter({ hasText: `Synthetic ${marker}` });
  await page.getByRole('searchbox', { name: 'Find candidate applications' }).fill(marker);
  await page.getByRole('button', { name: 'Find applications' }).click();
  await card.getByRole('button', { name: 'Mark screening' }).click();
  await card.getByRole('button', { name: 'Shortlist application' }).click();
  await expect(card).toContainText('shortlisted');
  await card.getByText('Application stage history', { exact: true }).click();
  await expect(card.getByRole('listitem').filter({ hasText: 'shortlisted' })).toBeVisible();
  const newRecord = page.locator('form').filter({
    has: page.getByRole('button', { name: 'Save recruitment record' })
  });
  await newRecord.getByLabel('New record').selectOption('interview');
  await newRecord.locator('select[name="application"]').selectOption(appId);
  await newRecord.getByLabel('Interview time').fill('2028-01-05T10:00');
  await newRecord.getByLabel('Round number').fill('1');
  const profile = await request.get('/api/v1/auth/me', { headers });
  expect(profile.ok()).toBeTruthy();
  const { full_name, employee_code } = (await profile.json()) as {
    full_name: string; employee_code: string;
  };
  await newRecord.getByRole('searchbox', { name: 'Find portal interviewer' }).fill(employee_code.toLowerCase());
  const interviewer = newRecord.getByRole('combobox', { name: 'Portal interviewer', exact: true });
  await interviewer.selectOption(session.userId);
  await expect(interviewer.locator('option:checked')).toHaveText(`${full_name} · ${employee_code}`);
  await newRecord.getByRole('button', { name: 'Save recruitment record' }).click();
  await expect(card.getByRole('button', { name: 'Record interview completed' })).toBeVisible();
  await card.getByRole('button', { name: 'Withdraw application' }).click();
  await expect(card.getByRole('button', { name: 'Confirm withdrawal' })).toBeDisabled();
  await card.getByLabel('Withdrawal reason').fill('Candidate requested withdrawal.');
  await card
    .getByRole('combobox', { name: 'Retention decision' })
    .selectOption('retain_until_review');
  const reviewDate = new Date(Date.now() + 3 * 86_400_000).toISOString().slice(0, 10);
  await card.getByLabel('Retention review date').fill(reviewDate);
  await card.getByLabel('Approved retention policy reference').fill('SYNTHETIC-RETENTION-1');
  await card.getByRole('button', { name: 'Confirm withdrawal' }).click();
  await expect(card).toContainText('withdrawn');
  await expect(card).toContainText('· cancelled');
  await expect(card.getByRole('button', { name: 'Withdraw application' })).toHaveCount(0);

  await page.reload();
  await page.getByRole('button', { name: 'Recruitment', exact: true }).click();
  await expect(card).toContainText(`Retain until review on ${reviewDate}`);
  await expect(card).toContainText('SYNTHETIC-RETENTION-1');
  await expect(card).toContainText('Candidate requested withdrawal.');
  await page.getByRole('link', { name: 'Notifications', exact: true }).click();
  await expect(page.getByText('Recruitment interview invitation', { exact: true })).toBeVisible();
  await expect(page.getByText('Recruitment interview cancelled', { exact: true })).toBeVisible();
  await expect(page.getByText(`Synthetic ${marker}`, { exact: false })).toHaveCount(0);
  expect(
    await (await request.get(`/api/v1/hr/applications/${appId}`, { headers })).json()
  ).toMatchObject({ retention_decision: 'retain_until_review', retention_review_on: reviewDate });
});

test('a second HR Manager approves the exact candidate rejection letter', async ({
  page,
  browser,
  request
}) => {
  const maker = await signIn(page, seedAccount('hr_manager'));
  const headers = { Authorization: `Bearer ${maker.accessToken}` };
  const marker = `Candidate-Letter-${Date.now().toString(36)}`;
  const req = await request.post('/api/v1/hr/requisitions', {
    headers,
    data: { requisition_code: marker, title: 'Synthetic Planner' }
  });
  expect(req.status()).toBe(201);
  const reqId = (await req.json()).id as string;
  for (const step of ['submitted', 'approved', 'open']) {
    expect(
      (
        await request.post(`/api/v1/hr/requisitions/${reqId}/decision`, {
          headers,
          data: { status: step }
        })
      ).status()
    ).toBe(200);
  }
  const candidate = await request.post('/api/v1/hr/candidates', {
    headers,
    data: { candidate_code: marker, full_name: `Synthetic ${marker}` }
  });
  expect(candidate.status()).toBe(201);
  expect(
    (
      await request.post('/api/v1/hr/applications', {
        headers,
        data: { requisition_id: reqId, candidate_id: (await candidate.json()).id }
      })
    ).status()
  ).toBe(201);

  await page.getByRole('link', { name: 'HR & Workforce', exact: true }).click();
  await page.getByRole('button', { name: 'Policies & Requests', exact: true }).click();
  await page.getByLabel('Template code').fill(marker);
  await page.getByLabel('Template name').fill(marker);
  await page
    .getByRole('combobox', { name: 'Letter type', exact: true })
    .selectOption('candidate_rejection');
  await page.getByLabel('Letter subject template').fill('Application for {position_title}');
  await page
    .getByLabel('Letter body template')
    .fill('Dear {candidate_name}, thank you for applying.');
  await page.getByRole('button', { name: 'Save letter template' }).click();
  await expect(page.getByText('Letter template saved.')).toBeVisible();

  await page.getByRole('button', { name: 'Recruitment', exact: true }).click();
  const application = page.getByRole('article').filter({ hasText: `Synthetic ${marker}` });
  await application.getByRole('button', { name: 'Reject application', exact: true }).click();
  await application
    .getByLabel('Internal application rejection reason')
    .fill('Synthetic internal reason');
  await application.getByRole('button', { name: 'Confirm application rejection' }).click();
  await application.getByText('Candidate correspondence', { exact: true }).click();
  await application
    .getByRole('combobox', { name: 'Candidate rejection template' })
    .selectOption({ label: marker });
  await application.getByRole('button', { name: 'Draft candidate correspondence' }).click();
  const draft = application.getByRole('region', { name: 'Selected correspondence' });
  await expect(draft).toContainText('Application for Synthetic Planner');
  await expect(draft).toContainText(`Dear Synthetic ${marker}, thank you for applying.`);
  await expect(draft).not.toContainText('Synthetic internal reason');
  await expect(draft.getByRole('button', { name: 'Approve candidate correspondence' })).toHaveCount(
    0
  );

  const reviewerContext = await browser.newContext();
  try {
    const reviewer = await reviewerContext.newPage();
    await signIn(reviewer, seedAccount('hr_manager'));
    async function openCorrespondence(status: string) {
      await reviewer.getByRole('button', { name: 'Recruitment', exact: true }).click();
      const card = reviewer.getByRole('article').filter({ hasText: `Synthetic ${marker}` });
      await card.getByText('Candidate correspondence', { exact: true }).click();
      await card.getByRole('button', { name: `Open ${marker} · ${status}` }).click();
      return card.getByRole('region', { name: 'Selected correspondence' });
    }
    await reviewer.getByRole('link', { name: 'HR & Workforce', exact: true }).click();
    const reviewed = await openCorrespondence('draft');
    await reviewed.getByRole('button', { name: 'Approve candidate correspondence' }).click();
    await expect(reviewed).toContainText('Status approved');
    await reviewer.reload();
    const retained = await openCorrespondence('approved');
    await expect(retained).toContainText(`Dear Synthetic ${marker}, thank you for applying.`);
    await expect(
      retained.getByRole('button', { name: 'Approve candidate correspondence' })
    ).toHaveCount(0);
  } finally {
    await reviewerContext.close();
  }
});

test('policy replacement preserves the acknowledged file and requires a new receipt', async ({
  page,
  browser,
  request
}) => {
  const director = seedAccount();
  const hr = await signIn(page, seedAccount('hr_manager', director.projectId));
  const headers = { Authorization: `Bearer ${hr.accessToken}` };
  const directorContext = await browser.newContext();
  const reviewerContext = await browser.newContext();
  const employeeContext = await browser.newContext();
  const policyDir = mkdtempSync(join(tmpdir(), 'garrison-company-policy-'));
  try {
    const directorSession = await signIn(await directorContext.newPage(), director);
    const reviewer = await signIn(
      await reviewerContext.newPage(),
      seedAccount('hr_manager', director.projectId)
    );
    const reviewerHeaders = { Authorization: `Bearer ${reviewer.accessToken}` };
    const worker = seedAccount('quantity_surveyor', director.projectId);
    const employeePage = await employeeContext.newPage();
    const employeeSession = await signIn(employeePage, worker);
    const marker = `Policy-${Date.now().toString(36)}`;
    const employee = await request.post('/api/v1/hr/employees', {
      headers,
      data: {
        employee_code: marker,
        first_name: 'Synthetic',
        last_name: 'Policy Reader',
        work_email: worker.email,
        employment_status: 'active',
        join_date: '2025-01-01'
      }
    });
    expect(employee.status()).toBe(201);
    const linked = await request.post(
      `/api/v1/hr/employees/${(await employee.json()).id}/link-account`,
      {
        headers: { Authorization: `Bearer ${directorSession.accessToken}` },
        data: { user_id: employeeSession.userId }
      }
    );
    expect(linked.status()).toBe(200);

    const original = Buffer.from('%PDF-1.4\n1 0 obj<<>>endobj\n% first policy\n%%EOF');
    const updated = Buffer.from('%PDF-1.4\n1 0 obj<<>>endobj\n% second policy\n%%EOF');
    await page.getByRole('link', { name: 'HR & Workforce', exact: true }).click();
    await page.getByRole('button', { name: 'Docs & Compliance', exact: true }).click();
    await page.getByLabel('Document title', { exact: true }).fill(marker);
    await page.getByLabel('Upload company policy file').check();
    await page.getByLabel('HR document file').setInputFiles({
      name: 'policy-original.pdf',
      mimeType: 'application/pdf',
      buffer: original
    });
    const uploaded = page.waitForResponse(
      (response) =>
        response.url().endsWith('/api/v1/hr/documents') && response.request().method() === 'POST'
    );
    await page.getByRole('button', { name: 'Upload HR document' }).click();
    const file = await uploaded;
    expect(file.status()).toBe(201);
    const documentId = (await file.json()).id as string;
    const documentCard = page.getByRole('article').filter({ hasText: marker });

    async function approveVersion(number: number) {
      const decision = await request.post(
        `/api/v1/hr/documents/${documentId}/versions/${number}/decision`,
        {
          headers: reviewerHeaders,
          data: { decision: 'approve' }
        }
      );
      expect(decision.status()).toBe(200);
    }
    const dateFormat = new Intl.DateTimeFormat('sv-SE', { timeZone: 'Asia/Qatar' });
    const today = dateFormat.format(new Date());
    const yesterday = dateFormat.format(new Date(Date.now() - 86_400_000));

    async function publish(version: number, effectiveDate: string, predecessor?: string) {
      await page.getByRole('button', { name: 'Policies & Requests', exact: true }).click();
      await page.getByLabel('Policy code').fill(`${marker}-${version}`);
      await page.getByLabel('Policy title').fill(marker);
      await page.getByLabel('Policy edition', { exact: true }).fill(`${version}.0`);
      await page.getByLabel('Policy effective date').fill(effectiveDate);
      if (predecessor) {
        await page
          .getByRole('combobox', { name: 'Replaces policy edition' })
          .selectOption(predecessor);
      }
      await page.getByLabel('Policy summary').fill(`Synthetic edition ${version} body`);
      await page.getByLabel('Attach approved company policy file').check();
      await page
        .getByRole('combobox', { name: 'Policy file version' })
        .selectOption(`${documentId}:${version}`);
      const publication = page.waitForResponse(
        (response) =>
          response.url().endsWith('/api/v1/hr/policies') && response.request().method() === 'POST'
      );
      await page.getByRole('button', { name: 'Publish policy' }).click();
      const response = await publication;
      expect(response.status()).toBe(201);
      await expect(page.getByText('Policy edition published.')).toBeVisible();
      return ((await response.json()) as { id: string }).id;
    }

    await approveVersion(1);
    const firstId = await publish(1, yesterday);
    await employeePage.getByRole('link', { name: 'My HR', exact: true }).click();
    const current = employeePage.getByRole('article').filter({ hasText: `${marker} v1.0` });
    await current.getByRole('button', { name: 'Acknowledge policy edition' }).click();
    await expect(current).toContainText('Acknowledged');

    await page.getByRole('button', { name: 'Docs & Compliance', exact: true }).click();
    await documentCard.getByLabel('Replacement file').setInputFiles({
      name: 'policy-replacement.pdf',
      mimeType: 'application/pdf',
      buffer: updated
    });
    await documentCard.getByRole('button', { name: 'Submit replacement' }).click();
    await expect(documentCard).toContainText('Version 2 · pending');
    await approveVersion(2);
    function cliPolicy(token: string, ...args: string[]) {
      return JSON.parse(execFileSync(
        PYTHON_BIN, ['-m', 'scripts.garrisonctl', 'hr', ...args, '--json'], {
          cwd: BACKEND_DIR,
          encoding: 'utf8',
          env: {
            ...env,
            GARRISON_API_BASE_URL: 'http://127.0.0.1:8425',
            GARRISON_ENVIRONMENT: 'test',
            GARRISON_ACCESS_TOKEN: token
          }
        }
      )) as { data: { id: string; plan_sha256: string; acknowledged_at: string; sha256: string } };
    }
    const editionInput = join(policyDir, 'edition.json');
    writeFileSync(editionInput, JSON.stringify({
      code: `${marker}-2`, title: marker, version: '2.0', effective_date: today,
      content_summary: 'Synthetic edition 2 body', document_id: documentId,
      document_version_number: 2, supersedes_policy_id: firstId
    }), { mode: 0o600 });
    const publishArgs = ['company-policy', 'publish', '--file', editionInput];
    const preview = cliPolicy(hr.accessToken, ...publishArgs, '--dry-run');
    const secondId = cliPolicy(
      hr.accessToken, ...publishArgs, '--apply', '--expect', preview.data.plan_sha256
    ).data.id;
    expect(secondId).not.toBe(firstId);

    await employeePage.getByRole('button', { name: 'Reload policies' }).click();
    const replacement = employeePage.getByRole('article').filter({ hasText: `${marker} v2.0` });
    await expect(current).toContainText('Previous edition');
    await expect(current).toContainText('Acknowledged');
    await expect(
      replacement.getByRole('button', { name: 'Acknowledge policy edition' })
    ).toBeVisible();
    const [historicalFile] = await Promise.all([
      employeePage.waitForEvent('download'),
      current.getByRole('button', { name: 'Download policy file v1' }).click()
    ]);
    expect(readFileSync(await historicalFile.path())).toEqual(original);
    const originalDownload = join(policyDir, 'original.pdf');
    const objectOrigin = `http://${env.BROWSER_TEST_MINIO_ENDPOINT ?? '127.0.0.1:9000'}`;
    const downloaded = cliPolicy(employeeSession.accessToken,
      'my-policy', 'download', '--policy-id', firstId, '--output', originalDownload,
      '--object-origin', objectOrigin
    );
    expect(downloaded.data.sha256).toBe(createHash('sha256').update(original).digest('hex'));
    expect(readFileSync(originalDownload)).toEqual(original);

    const [newFile] = await Promise.all([
      employeePage.waitForEvent('download'),
      replacement.getByRole('button', { name: 'Download policy file v2' }).click()
    ]);
    expect(readFileSync(await newFile.path())).toEqual(updated);
    const ackArgs = [
      'my-policy', 'acknowledge', '--policy-id', secondId, '--edition', '2.0', '--file-version', '2'
    ];
    const acknowledgement = cliPolicy(employeeSession.accessToken, ...ackArgs, '--dry-run');
    const receipt = cliPolicy(
      employeeSession.accessToken, ...ackArgs, '--apply', '--expect', acknowledgement.data.plan_sha256
    );
    expect(receipt.data.acknowledged_at).toBeTruthy();
    await employeePage.getByRole('button', { name: 'Reload policies' }).click();
    await expect(replacement).toContainText('Acknowledged');
    await employeePage.reload();
    await expect(replacement).toContainText('Acknowledged');
  } finally {
    rmSync(policyDir, { recursive: true, force: true });
    await Promise.all([directorContext.close(), reviewerContext.close(), employeeContext.close()]);
  }
});

test('authorized HR operators propose and independently review a private compensation term', async ({
  page,
  browser,
  request
}) => {
  const [, maker, reviewer] = seedProjectAccounts('managing_director', 'hr_manager', 'hr_manager');
  const makerSession = await signIn(page, maker);
  const makerHeaders = { Authorization: `Bearer ${makerSession.accessToken}` };
  const employeeCode = `COMP-${Date.now().toString(36)}`;
  const created = await request.post('/api/v1/hr/employees', {
    headers: makerHeaders,
    data: {
      employee_code: employeeCode,
      first_name: 'Synthetic',
      last_name: 'Compensation Employee',
      employment_status: 'active',
      join_date: '2025-01-01'
    }
  });
  expect(created.status()).toBe(201);
  const employee = (await created.json()) as { id: string };

  async function openCompensation(target: Page) {
    await target.getByRole('link', { name: 'HR & Workforce', exact: true }).click();
    await target.getByRole('button', { name: 'Directory & Org', exact: true }).click();
    await target.getByLabel('Search employees').fill(employeeCode);
    await target
      .getByRole('row')
      .filter({ hasText: employeeCode })
      .getByRole('button', { name: 'Inspect', exact: true })
      .click();
    await target.getByText('Compensation history', { exact: true }).click();
    return target.getByRole('region', { name: 'Compensation terms' });
  }

  const makerPanel = await openCompensation(page);
  await expect(makerPanel.getByText('No compensation terms recorded.')).toBeVisible();
  await makerPanel.getByLabel('Effective date').fill('2025-01-01');
  await makerPanel.getByLabel('Currency code').fill('LKR');
  await makerPanel.getByLabel('Base salary').fill('175.25');
  await makerPanel.getByLabel('Allowances (optional JSON object)').fill('[]');
  await makerPanel.getByRole('button', { name: 'Submit compensation proposal' }).click();
  await expect(makerPanel.getByRole('alert')).toContainText('Enter allowances as a JSON object');
  await expect(makerPanel.getByLabel('Base salary')).toHaveValue('175.25');
  await makerPanel.getByLabel('Allowances (optional JSON object)').fill('{"transport":"5.25"}');
  await makerPanel.getByRole('button', { name: 'Submit compensation proposal' }).click();
  await expect(makerPanel.getByRole('status')).toHaveText('Compensation term sent for independent review.');
  await expect(makerPanel.getByText('Pending independent review', { exact: true })).toBeVisible();
  await expect(makerPanel.getByText('Base salary LKR 175.25')).toHaveCount(0);
  await makerPanel.getByRole('button', { name: 'Reveal term for 2025-01-01' }).click();
  await expect(makerPanel.getByText('Base salary LKR 175.25')).toBeVisible();
  await expect(makerPanel.getByRole('button', { name: 'Approve reviewed term' })).toHaveCount(0);
  await page.getByText('Compensation history', { exact: true }).click();
  await expect(makerPanel).toHaveCount(0);
  await page.getByText('Compensation history', { exact: true }).click();
  await expect(makerPanel.getByText('Pending independent review', { exact: true })).toBeVisible();
  await expect(makerPanel.getByText('Base salary LKR 175.25')).toHaveCount(0);

  const context = await browser.newContext();
  try {
    const reviewerPage = await context.newPage();
    await signIn(reviewerPage, reviewer);
    const panel = await openCompensation(reviewerPage);
    await expect(panel.getByRole('button', { name: 'Approve reviewed term' })).toHaveCount(0);
    const privateRead = reviewerPage.waitForResponse((response) => {
      const url = new URL(response.url());
      return url.pathname === `/api/v1/hr/compensation/${employee.id}` &&
        url.searchParams.get('reveal_sensitive') === 'true';
    });
    await panel.getByRole('button', { name: 'Reveal term for 2025-01-01' }).click();
    const response = await privateRead;
    expect(response.status()).toBe(200);
    expect(response.headers()['cache-control']).toBe('no-store');
    expect(new URL(response.url()).searchParams.get('term_id')).toBeTruthy();
    await expect(panel.getByText('Base salary LKR 175.25')).toBeVisible();
    await panel.getByText('Allowances', { exact: true }).click();
    await expect(panel.getByText(/"transport": "5.25"/)).toBeVisible();
    await panel.getByRole('button', { name: 'Approve reviewed term' }).click();
    await expect(panel.getByText('Current approved term', { exact: true })).toBeVisible();
    await expect(panel.getByText('Base salary LKR 175.25')).toHaveCount(0);
    await reviewerPage.reload();
    await reviewerPage.getByRole('button', { name: 'Directory & Org', exact: true }).click();
    await reviewerPage.getByLabel('Search employees').fill(employeeCode);
    await reviewerPage.getByRole('row').filter({ hasText: employeeCode })
      .getByRole('button', { name: 'Inspect', exact: true }).click();
    await reviewerPage.getByText('Compensation history', { exact: true }).click();
    await expect(panel.getByText('Current approved term', { exact: true })).toBeVisible();
    await expect(panel.getByText('Base salary LKR 175.25')).toHaveCount(0);
  } finally {
    await context.close();
  }
});

test('HR operators submit, review and reconcile an employee advance', async ({ page, browser, request }) => {
  const [, maker, reviewer, recorder] = seedProjectAccounts(
    'managing_director', 'hr_manager', 'hr_manager', 'hr_manager'
  );
  const makerSession = await signIn(page, maker);
  const makerHeaders = { Authorization: `Bearer ${makerSession.accessToken}` };
  const today = new Intl.DateTimeFormat('sv-SE', { timeZone: 'Asia/Qatar' }).format(new Date());
  const unique = Date.now().toString(36);
  const employeeCode = `ADV-${unique}`;
  const created = await request.post('/api/v1/hr/employees', {
    headers: makerHeaders,
    data: {
      employee_code: employeeCode,
      first_name: 'Synthetic',
      last_name: 'Advance Employee',
      employment_status: 'active',
      join_date: '2025-01-01'
    }
  });
  expect(created.status()).toBe(201);
  const employee = (await created.json()) as { id: string };
  const policyCode = `ADV-POLICY-${unique.toUpperCase()}`;

  async function inspectEmployee(target: Page) {
    await target.getByRole('link', { name: 'HR & Workforce', exact: true }).click();
    await target.getByRole('button', { name: 'Directory & Org', exact: true }).click();
    await target.getByLabel('Search employees').fill(employeeCode);
    await target.getByRole('row').filter({ hasText: employeeCode })
      .getByRole('button', { name: 'Inspect', exact: true }).click();
  }

  async function openAdvance(target: Page) {
    await inspectEmployee(target);
    await target.getByText('Employee advances', { exact: true }).click();
    return target.getByRole('region', { name: 'Advance records' });
  }

  const reviewContext = await browser.newContext();
  const recorderContext = await browser.newContext();
  try {
    const reviewPage = await reviewContext.newPage();
    await signIn(reviewPage, reviewer);
    await inspectEmployee(page);
    await page.getByText('Benefit policies and coverage', { exact: true }).click();
    const makerBenefits = page.getByRole('region', { name: 'Benefit administration' });
    await makerBenefits.getByLabel('Policy code').fill(policyCode);
    await makerBenefits.getByLabel('Policy name').fill('Synthetic advance coverage');
    await makerBenefits.getByLabel('Benefit category').fill('Travel');
    await makerBenefits.getByLabel('Coverage ceiling').fill('75.00');
    await makerBenefits.getByLabel('Benefit currency').fill('LKR');
    await makerBenefits.getByLabel('Allow advances').check();
    await makerBenefits.getByRole('button', { name: 'Submit benefit policy' }).click();
    await expect(makerBenefits.getByText('Benefit policy proposed.', { exact: true })).toBeVisible();
    await expect(makerBenefits.getByText('Pending independent approval', { exact: true })).toBeVisible();
    await expect(makerBenefits.getByRole('button', { name: 'Approve benefit policy' })).toHaveCount(0);
    const policyId = await makerBenefits.getByRole('combobox', { name: 'Benefit policy', exact: true }).inputValue();
    const policyLabel = `${policyCode} · Synthetic advance coverage`;

    await inspectEmployee(reviewPage);
    await reviewPage.getByText('Benefit policies and coverage', { exact: true }).click();
    const reviewerBenefits = reviewPage.getByRole('region', { name: 'Benefit administration' });
    await reviewerBenefits.getByRole('combobox', { name: 'Benefit policy', exact: true }).selectOption(policyId);
    await expect(reviewerBenefits.getByText(/Ceiling LKR 75.00/)).toBeVisible();
    await reviewerBenefits.getByRole('button', { name: 'Approve benefit policy' }).click();
    await expect(reviewerBenefits.getByText('Approved policy', { exact: true })).toBeVisible();

    await makerBenefits.getByRole('button', { name: 'Refresh benefit records' }).click();
    await makerBenefits.getByLabel('Approved policy for coverage').selectOption({ label: policyLabel });
    await makerBenefits.getByLabel('Coverage start').fill(today);
    await makerBenefits.getByLabel('Coverage end').fill(today);
    await makerBenefits.getByRole('button', { name: 'Assign benefit coverage' }).click();
    await expect(makerBenefits.getByText('Benefit coverage assigned.', { exact: true })).toBeVisible();
    await expect(makerBenefits.getByRole('list', { name: 'Assigned benefit coverage' })).toContainText(today);
    await makerBenefits.getByLabel('Approved policy for coverage').selectOption({ label: policyLabel });
    await makerBenefits.getByLabel('Coverage start').fill(today);
    await makerBenefits.getByLabel('Coverage end').fill(today);
    await makerBenefits.getByRole('button', { name: 'Assign benefit coverage' }).click();
    await expect(makerBenefits.getByRole('alert')).toContainText('overlaps existing coverage');
    await expect(makerBenefits.getByLabel('Coverage start')).toHaveValue(today);

    await page.getByText('Employee advances', { exact: true }).click();
    const panel = page.getByRole('region', { name: 'Advance records' });
    await expect(panel.getByText('No advances recorded.')).toBeVisible();
    await panel.getByLabel('Benefit coverage').selectOption({
      label: `Synthetic advance coverage · ${today} to ${today} · LKR`
    });
    await panel.getByLabel('Advance request date').fill(today);
    const amount = panel.getByLabel('Requested amount (LKR)', { exact: true });
    await amount.fill('75.01');
    await panel.getByRole('button', { name: 'Submit advance', exact: true }).click();
    await expect(panel.getByRole('alert')).toContainText('remaining coverage ceiling');
    await expect(amount).toHaveValue('75.01');
    await amount.fill('40.00');
    await panel.getByRole('button', { name: 'Submit advance', exact: true }).click();
    await expect(panel.getByText('Advance submitted.', { exact: true })).toBeVisible();
    const makerDetail = panel.getByRole('article', { name: 'Advance detail' });
    await expect(makerDetail.getByText('Pending independent review')).toBeVisible();
    await expect(makerDetail.getByRole('button', { name: 'Approve advance' })).toHaveCount(0);

    const reviewing = await openAdvance(reviewPage);
    await reviewing.getByRole('button', { name: 'Open advance' }).click();
    await reviewing.getByRole('button', { name: 'Approve advance' }).click();
    const reviewerDetail = reviewing.getByRole('article', { name: 'Advance detail' });
    await expect(reviewerDetail.getByText('Approved for disbursement')).toBeVisible();
    await expect(reviewerDetail.getByRole('button', { name: 'Record external disbursement' })).toHaveCount(0);
    const downloadPromise = reviewPage.waitForEvent('download');
    await reviewerDetail.getByRole('button', { name: 'Download approved payable' }).click();
    const download = await downloadPromise;
    const payable = JSON.parse(readFileSync(await download.path(), 'utf8')) as {
      employee_id: string; amount: string; payable_sha256: string
    };
    expect(payable.employee_id).toBe(employee.id);
    expect(payable.amount).toBe('40.00');
    expect(payable.payable_sha256).toMatch(/^[a-f0-9]{64}$/);

    const recorderPage = await recorderContext.newPage();
    await signIn(recorderPage, recorder);
    const recording = await openAdvance(recorderPage);
    await recording.getByRole('button', { name: 'Open advance' }).click();
    const detail = recording.getByRole('article', { name: 'Advance detail' });

    async function record(button: string, reference: string, actualAmount: string) {
      await detail.getByLabel('External reference').fill(reference);
      await detail.getByLabel('Payment date').fill(today);
      await detail.getByLabel('Actual amount (LKR)').fill(actualAmount);
      await detail.getByRole('button', { name: button }).click();
    }

    await record('Record external disbursement', 'SYNTH-OUT-01', '40.00');
    await expect(detail.getByText('Disbursement recorded', { exact: true })).toBeVisible();
    await record('Record external repayment', 'SYNTH-IN-01', '40.00');
    await expect(detail.getByText('Fully repaid', { exact: true })).toBeVisible();
    await recorderPage.reload();
    const reloaded = await openAdvance(recorderPage);
    await reloaded.getByRole('button', { name: 'Open advance' }).click();
    await expect(reloaded.getByRole('article').getByText('Fully repaid', { exact: true })).toBeVisible();
    await expect(reloaded.getByRole('list', { name: 'Recorded repayments' })).toContainText('SYNTH-IN-01');
  } finally {
    await recorderContext.close();
    await reviewContext.close();
  }
});

test('HR operators review a private reimbursement receipt and reconcile the payable', async ({ page, browser, request }) => {
  const [, maker, reviewer, recorder] = seedProjectAccounts(
    'managing_director', 'hr_manager', 'hr_manager', 'hr_manager'
  );
  const { accessToken } = await signIn(page, maker);
  const makerHeaders = { Authorization: `Bearer ${accessToken}` };
  const today = new Intl.DateTimeFormat('sv-SE', { timeZone: 'Asia/Qatar' }).format(new Date());
  const code = `REIM-${Date.now().toString(36)}`;
  const created = await request.post('/api/v1/hr/employees', {
    headers: makerHeaders,
    data: { employee_code: code, first_name: 'Synthetic', last_name: 'Receipt Employee', employment_status: 'active' }
  });
  expect(created.status()).toBe(201);
  const employeeId = (await created.json() as { id: string }).id;
  const benefit = await request.post('/api/v1/hr/benefits/types', {
    headers: makerHeaders,
    data: { code, name: 'Synthetic receipt coverage', category: 'Travel', reimbursement_ceiling: '75.00', reimbursement_currency: 'LKR' }
  });
  expect(benefit.status()).toBe(201);
  const policyId = (await benefit.json() as { id: string }).id;
  const original = Buffer.from('%PDF-1.4\n% Synthetic original receipt\n%%EOF');

  async function panel(target: Page) {
    await target.getByRole('link', { name: 'HR & Workforce', exact: true }).click();
    await target.getByRole('button', { name: 'Directory & Org', exact: true }).click();
    await target.getByLabel('Search employees').fill(code);
    await target.getByRole('row').filter({ hasText: code }).getByRole('button', { name: 'Inspect' }).click();
    await target.getByText('Reimbursements', { exact: true }).click();
    return target.getByRole('region', { name: 'Reimbursement records' });
  }

  const reviewContext = await browser.newContext();
  const recordContext = await browser.newContext();
  try {
    const reviewPage = await reviewContext.newPage();
    const reviewerSession = await signIn(reviewPage, reviewer);
    const reviewerHeaders = { Authorization: `Bearer ${reviewerSession.accessToken}` };
    const approvedPolicy = await request.post(`/api/v1/hr/benefits/types/${policyId}/approve`, { headers: reviewerHeaders });
    expect(approvedPolicy.status()).toBe(200);
    const assigned = await request.post('/api/v1/hr/benefits/assignments', {
      headers: makerHeaders,
      data: { employee_id: employeeId, benefit_type_id: policyId, effective_from: today, effective_to: today }
    });
    expect(assigned.status()).toBe(201);
    const assignmentId = (await assigned.json() as { id: string }).id;

    const makerPanel = await panel(page);
    await makerPanel.getByLabel('Receipt title').fill('Synthetic reviewed receipt');
    await makerPanel.getByLabel('Receipt file').setInputFiles({ name: 'receipt.pdf', mimeType: 'application/pdf', buffer: original });
    const uploadResponse = page.waitForResponse((response) =>
      new URL(response.url()).pathname === '/api/v1/hr/documents' && response.request().method() === 'POST'
    );
    await makerPanel.getByRole('button', { name: 'Upload private receipt' }).click();
    const uploaded = await uploadResponse;
    expect(uploaded.status()).toBe(201);
    const receiptId = (await uploaded.json() as { id: string }).id;
    await expect(makerPanel.getByText(/Pending receipt review/)).toBeVisible();
    await expect(makerPanel.getByRole('button', { name: 'Approve receipt', exact: true })).toHaveCount(0);

    const reviewing = await panel(reviewPage);
    await reviewing.getByRole('button', { name: 'Prepare receipt review link' }).click();
    const signed = await reviewing.getByRole('link', { name: 'Open receipt for review' }).getAttribute('href');
    expect(signed).toBeTruthy();
    const received = await request.get(signed!);
    expect(await received.body()).toEqual(original);
    await reviewing.getByRole('button', { name: 'Approve receipt', exact: true }).click();
    await expect(reviewing.getByText('Receipt approved.', { exact: true })).toBeVisible();

    await makerPanel.getByRole('button', { name: 'Refresh reimbursements' }).click();
    await makerPanel.getByRole('combobox', { name: 'Reimbursement coverage' }).selectOption(assignmentId);
    await makerPanel.getByRole('combobox', { name: 'Approved receipt' }).selectOption(receiptId);
    await makerPanel.getByLabel('Expense date').fill(today);
    await makerPanel.getByLabel('Claim amount (LKR)').fill('42.50');
    await makerPanel.getByLabel('Claim description').fill('Synthetic reimbursable travel');
    await makerPanel.getByRole('button', { name: 'Submit reimbursement' }).click();
    await expect(makerPanel.getByText('Reimbursement submitted.', { exact: true })).toBeVisible();
    await expect(makerPanel.getByRole('button', { name: 'Approve reimbursement' })).toHaveCount(0);

    await reviewing.getByRole('button', { name: 'Refresh reimbursements' }).click();
    await reviewing.getByRole('button', { name: 'Open claim' }).click();
    await expect(reviewing.getByRole('button', { name: 'Approve reimbursement' })).toBeDisabled();
    await reviewing.getByRole('button', { name: 'Prepare pinned receipt link' }).click();
    const pinned = await reviewing.getByRole('link', { name: 'Open pinned receipt' }).getAttribute('href');
    expect(await (await request.get(pinned!)).body()).toEqual(original);
    await reviewing.getByRole('button', { name: 'Approve reimbursement' }).click();
    await expect(reviewing.getByText('Reimbursement approved.', { exact: true })).toBeVisible();
    await reviewing.getByRole('button', { name: 'Review payable' }).click();
    await expect(reviewing.getByText('Approved payable LKR 42.50')).toBeVisible();
    await expect(reviewing.getByRole('button', { name: 'Confirm external settlement' })).toHaveCount(0);

    const recordPage = await recordContext.newPage();
    await signIn(recordPage, recorder);
    const recording = await panel(recordPage);
    await recording.getByRole('button', { name: 'Open claim' }).click();
    await recording.getByRole('button', { name: 'Review payable' }).click();
    const download = recordPage.waitForEvent('download');
    await recording.getByRole('button', { name: 'Download reimbursement payable' }).click();
    const payable = JSON.parse(readFileSync(await (await download).path(), 'utf8')) as {
      reference: { amount: string; employee_id: string }; reference_sha256: string
    };
    expect(payable.reference).toMatchObject({ amount: '42.50', employee_id: employeeId });
    expect(payable.reference_sha256).toMatch(/^[a-f0-9]{64}$/);
    await recording.getByLabel('External settlement reference').fill('SYNTH-REIM-01');
    await recording.getByLabel('Actual settled currency').fill('LKR');
    const amount = recording.getByLabel('Actual settled amount');
    await amount.fill('42.51');
    const confirm = recording.getByRole('button', { name: 'Confirm external settlement' });
    await confirm.click();
    await expect(recording.getByRole('alert')).toContainText('must match the payable');
    await expect(amount).toHaveValue('42.51');
    await amount.fill('42.50');
    await confirm.click();
    await expect(recording.getByText('External settlement confirmed.', { exact: true })).toBeVisible();
    await recordPage.reload();
    const reloaded = await panel(recordPage);
    await reloaded.getByRole('button', { name: 'Open claim' }).click();
    await expect(reloaded.getByText('Settlement reference SYNTH-REIM-01')).toBeVisible();
    await expect(reloaded.getByRole('button', { name: 'Review payable' })).toHaveCount(0);
  } finally {
    await recordContext.close();
    await reviewContext.close();
  }
});

test('payroll operators lock a reviewed snapshot and publish its employee payslip', async ({ page, browser, request }) => {
  // The full policy-to-payslip workflow uses four signed-in browser contexts.
  test.setTimeout(90_000);
  const [director, maker, checker, employeeAccount] = seedProjectAccounts(
    'managing_director', 'hr_manager', 'hr_manager', 'quantity_surveyor'
  );
  const makerSession = await signIn(page, maker);
  const makerHeaders = { Authorization: `Bearer ${makerSession.accessToken}` };
  const unique = Date.now().toString(36);
  const periodCode = `PAY-PORTAL-${unique}`;
  const contexts = await Promise.all([browser.newContext(), browser.newContext(), browser.newContext()]);
  try {
    const checkerPage = await contexts[0].newPage();
    const employeePage = await contexts[1].newPage();
    const directorPage = await contexts[2].newPage();
    const checkerSession = await signIn(checkerPage, checker);
    const employeeSession = await signIn(employeePage, employeeAccount);
    const directorSession = await signIn(directorPage, director);
    const checkerHeaders = { Authorization: `Bearer ${checkerSession.accessToken}` };
    const employee = await request.post('/api/v1/hr/employees', {
      headers: makerHeaders,
      data: {
        employee_code: `PAY-EMP-${unique}`, first_name: 'Synthetic', last_name: 'Portal Payroll',
        work_email: employeeAccount.email, employment_status: 'active', join_date: '2025-01-01'
      }
    });
    expect(employee.status()).toBe(201);
    const employeeId = (await employee.json() as { id: string }).id;
    const accountLink = await request.post(`/api/v1/hr/employees/${employeeId}/link-account`, {
      headers: { Authorization: `Bearer ${directorSession.accessToken}` },
      data: { user_id: employeeSession.userId }
    });
    expect(accountLink.status()).toBe(200);
    const term = await request.post('/api/v1/hr/compensation', {
      headers: makerHeaders,
      data: { employee_id: employeeId, effective_from: '2025-01-01', base_salary: '100.05', currency: 'LKR' }
    });
    expect(term.status()).toBe(201);
    const termId = (await term.json() as { id: string }).id;
    expect((await request.post(`/api/v1/hr/compensation/${termId}/decision`, {
      headers: checkerHeaders, data: { decision: 'approve' }
    })).status()).toBe(200);

    async function openPayroll(target: Page) {
      await target.getByRole('link', { name: 'HR & Workforce', exact: true }).click();
      await target.getByRole('button', { name: 'Payroll', exact: true }).click();
      return target.getByRole('region', { name: 'Payroll operations' });
    }
    const preparing = await openPayroll(page);
    const makerPolicy = preparing.getByRole('region', { name: 'Payroll policy administration' });
    await makerPolicy.getByLabel('Payroll policy code').fill(periodCode);
    await makerPolicy.getByLabel('Payroll policy name').fill('Synthetic reviewed policy');
    await makerPolicy.getByLabel('Controlled document reference').fill('HR-POL-BROWSER');
    await makerPolicy.getByLabel('Document version').fill('1.2');
    await makerPolicy.getByLabel('Policy effective from').fill('2025-06-01');
    await makerPolicy.getByLabel('Business approval reference').fill('HR-APPROVAL-BROWSER');
    await makerPolicy.getByLabel('Example base salary').fill('100.05');
    await makerPolicy.getByLabel('Example additional earnings').fill('10.00');
    await makerPolicy.getByLabel('Example additional deductions').fill('10.00');
    await makerPolicy.getByLabel('Expected gross').fill('110.05');
    await makerPolicy.getByLabel('Expected deductions').fill('20.01');
    await makerPolicy.getByLabel('Expected net').fill('90.05');
    await makerPolicy.getByRole('combobox', { name: 'Calculation basis' }).selectOption('base_salary_with_reviewed_adjustments');
    await makerPolicy.getByLabel('Currency code').fill('LKR');
    await makerPolicy.getByRole('combobox', { name: 'Rounding method' }).selectOption('half_up');
    await makerPolicy.getByLabel('Employee deduction fraction (0–1)').fill('0.10');
    await makerPolicy.getByRole('button', { name: 'Propose payroll policy' }).click();
    const idOutput = makerPolicy.getByLabel('Proposed payroll policy ID');
    await expect(idOutput).toBeVisible();
    const policyId = (await idOutput.textContent())!;
    await makerPolicy.getByLabel('Payroll policy ID', { exact: true }).fill(policyId);
    await makerPolicy.getByRole('button', { name: 'Open policy by ID' }).click();
    await expect(makerPolicy.getByText('A different reviewer must approve this policy.')).toBeVisible();
    await expect(makerPolicy.getByRole('button', { name: 'Approve reviewed payroll policy' })).toHaveCount(0);
    expect((await request.post(`/api/v1/hr/payroll/policies/${policyId}/approve`, { headers: makerHeaders })).status()).toBe(409);
    expect((await request.get(`/api/v1/hr/payroll/policies/${policyId}`, {
      headers: { Authorization: `Bearer ${employeeSession.accessToken}` }
    })).status()).toBe(403);

    const checking = await openPayroll(checkerPage);
    const checkerPolicy = checking.getByRole('region', { name: 'Payroll policy administration' });
    await checkerPolicy.getByLabel('Payroll policy ID', { exact: true }).fill(policyId);
    await checkerPolicy.getByRole('button', { name: 'Open policy by ID' }).click();
    const policyReview = checkerPolicy.getByRole('article', { name: 'Reviewed payroll policy' });
    await expect(policyReview.getByText('HR-APPROVAL-BROWSER', { exact: true })).toBeVisible();
    await expect(policyReview.getByLabel('Worked payroll examples')).toContainText('"90.05"');
    await expect(policyReview.getByLabel('Proposed calculation rules')).toContainText('"employee_deduction_rate": "0.10"');
    await policyReview.getByRole('button', { name: 'Approve reviewed payroll policy' }).click();
    await expect(checkerPolicy.getByRole('alert')).toContainText('Worked example 1 differs');
    await makerPolicy.getByRole('button', { name: 'Edit policy draft' }).click();
    await expect(makerPolicy.getByLabel('Expected net')).toHaveValue('90.05');
    await makerPolicy.getByLabel('Expected net').fill('90.04');
    await makerPolicy.getByRole('button', { name: 'Save policy draft corrections' }).click();
    await expect(makerPolicy.getByText('Payroll policy draft updated.', { exact: true })).toBeVisible();
    await policyReview.getByRole('button', { name: 'Approve reviewed payroll policy' }).click();
    await expect(checkerPolicy.getByRole('alert')).toContainText('Open it again');
    await checkerPolicy.getByRole('button', { name: 'Open policy by ID' }).click();
    await expect(policyReview.getByLabel('Worked payroll examples')).toContainText('"90.04"');
    await policyReview.getByRole('button', { name: 'Approve reviewed payroll policy' }).click();
    await expect(policyReview.getByText('Approved payroll policy', { exact: true })).toBeVisible();

    const policyDir = mkdtempSync(join(tmpdir(), 'garrison-payroll-policy-'));
    try {
      function policyCli(token: string, ...args: string[]) {
        return JSON.parse(execFileSync(
          PYTHON_BIN, ['-m', 'scripts.garrisonctl', 'hr', 'payroll', 'policies', ...args, '--json'], {
            cwd: BACKEND_DIR,
            encoding: 'utf8',
            env: {
              ...env, GARRISON_API_BASE_URL: 'http://127.0.0.1:8425',
              GARRISON_ENVIRONMENT: 'test', GARRISON_ACCESS_TOKEN: token
            }
          }
        )) as { data: {
          id: string; review_sha256: string; plan_sha256: string; is_approved: boolean;
          items: { id: string; is_approved: boolean }[];
        } };
      }
      function applyPolicy(token: string, ...args: string[]) {
        const preview = policyCli(token, ...args, '--dry-run');
        return policyCli(token, ...args, '--apply', '--expect', preview.data.plan_sha256).data;
      }
      const sourceResponse = await request.get(`/api/v1/hr/payroll/policies/${policyId}`, {
        headers: checkerHeaders
      });
      expect(sourceResponse.status()).toBe(200);
      const source = await sourceResponse.json();
      const policyFields = {
        name: 'Synthetic CLI policy',
        rules_json: source.rules_json,
        controlled_record: source.controlled_record
      };
      const input = join(policyDir, 'input.json');
      writeFileSync(input, JSON.stringify({
        ...policyFields, code: `${periodCode}-CLI`
      }), { mode: 0o600 });
      const draftReceipt = applyPolicy(makerSession.accessToken, 'propose', '--file', input);
      expect(draftReceipt.is_approved).toBe(false);
      expect(draftReceipt).not.toHaveProperty('controlled_record');
      const idArgs = ['--policy-id', draftReceipt.id];
      const priorCopy = join(policyDir, 'prior.json');
      const prior = policyCli(checkerSession.accessToken, 'show', ...idArgs, '--output', priorCopy);
      expect(statSync(priorCopy).mode & 0o777).toBe(0o600);
      expect(JSON.parse(readFileSync(priorCopy, 'utf8')).controlled_record).toEqual(
        source.controlled_record
      );
      const oldApproval = ['approve', ...idArgs, '--review-sha256', prior.data.review_sha256];
      const oldPlan = policyCli(checkerSession.accessToken, ...oldApproval, '--dry-run');
      writeFileSync(input, JSON.stringify({ ...policyFields, name: 'Synthetic corrected CLI policy' }));
      applyPolicy(makerSession.accessToken, 'update', ...idArgs, '--file', input);
      expect(() => policyCli(
        checkerSession.accessToken, ...oldApproval, '--apply', '--expect', oldPlan.data.plan_sha256
      )).toThrow();
      const reviewedCopy = join(policyDir, 'reviewed.json');
      const current = policyCli(checkerSession.accessToken, 'show', ...idArgs, '--output', reviewedCopy);
      expect(JSON.parse(readFileSync(reviewedCopy, 'utf8')).name).toBe('Synthetic corrected CLI policy');
      const approved = applyPolicy(
        checkerSession.accessToken, 'approve', ...idArgs, '--review-sha256', current.data.review_sha256
      );
      expect(approved.is_approved).toBe(true);
      expect(policyCli(makerSession.accessToken, 'list').data.items).toEqual(
        expect.arrayContaining([expect.objectContaining({ id: draftReceipt.id, is_approved: true })])
      );
    } finally {
      rmSync(policyDir, { recursive: true, force: true });
    }

    await page.reload();
    await openPayroll(page);
    await preparing.getByLabel('Period code').fill(periodCode);
    await preparing.getByLabel('Period start').fill('2025-06-01');
    await preparing.getByLabel('Period end').fill('2025-06-30');
    await preparing.getByLabel('Pay date').fill('2025-07-02');
    await preparing.getByRole('button', { name: 'Open payroll period' }).click();
    await expect(preparing.getByText('Payroll period opened.', { exact: true })).toBeVisible();
    await preparing.getByRole('combobox', { name: 'Approved payroll policy' }).selectOption(policyId);
    await preparing.getByRole('button', { name: 'Create payroll run' }).click();
    await expect(preparing.getByText('Draft payroll run created.', { exact: true })).toBeVisible();
    const selectedRun = preparing.getByRole('combobox', { name: 'Payroll run', exact: true });
    await expect(selectedRun).toHaveValue(/^[a-f0-9-]{36}$/);
    const runId = await selectedRun.inputValue();
    const makerAdjustments = preparing.getByRole('region', { name: 'Payroll adjustments' });
    await makerAdjustments.getByLabel('Adjustment payroll run ID').fill(runId);
    await makerAdjustments.getByRole('button', { name: 'Open run adjustments' }).click();
    for (const [kind, reference] of [['earning', 'EARN-PORTAL-1'], ['deduction', 'DEDUCT-PORTAL-1']]) {
      await makerAdjustments.getByLabel('Adjustment employee ID').fill(employeeId);
      await makerAdjustments.getByRole('combobox', { name: 'Adjustment type' }).selectOption(kind);
      await makerAdjustments.getByLabel('Adjustment amount in policy currency').fill('10.00');
      await makerAdjustments.getByLabel('Approved evidence reference').fill(reference);
      await makerAdjustments.getByRole('button', { name: 'Propose payroll adjustment' }).click();
      await expect(makerAdjustments.getByText(new RegExp(reference + '.*submitted'))).toBeVisible();
    }
    await expect(makerAdjustments.getByRole('button', { name: 'Approve reviewed adjustment' })).toHaveCount(0);
    const checkerAdjustments = checking.getByRole('region', { name: 'Payroll adjustments' });
    await checkerAdjustments.getByLabel('Adjustment payroll run ID').fill(runId);
    await checkerAdjustments.getByRole('button', { name: 'Open run adjustments' }).click();
    for (const reference of ['EARN-PORTAL-1', 'DEDUCT-PORTAL-1']) {
      const proposal = checkerAdjustments.getByRole('listitem').filter({ hasText: reference });
      await proposal.getByRole('button', { name: 'Approve reviewed adjustment' }).click();
      await expect(proposal.getByText(new RegExp(reference + '.*approved'))).toBeVisible();
    }

    const roster = preparing.getByLabel('Roster employee IDs');
    await roster.fill(`${employeeId},${employeeId}`);
    await preparing.getByRole('button', { name: 'Calculate snapshot' }).click();
    await expect(preparing.getByRole('alert')).toContainText('unique employee IDs');
    await roster.fill(employeeId);
    const sources = preparing.getByRole('region', { name: 'Time and leave source review' });
    await sources.getByRole('button', { name: 'Review time and leave inputs' }).click();
    const time = sources.getByRole('article', { name: 'Time inputs' });
    const leave = sources.getByRole('article', { name: 'Leave inputs' });
    await expect(time.getByText(/missing locked timesheet/)).toContainText(employeeId);
    await expect(time.getByRole('button', { name: 'Download verified time CSV' })).toHaveCount(0);
    await expect(leave.getByText('Paid leave days 0.00 · Unpaid leave days 0.00')).toBeVisible();
    await roster.fill('');
    await expect(sources).toHaveCount(0);
    await roster.fill(employeeId);
    await sources.getByRole('button', { name: 'Review time and leave inputs' }).click();
    await expect(time.getByText(/missing locked timesheet/)).toBeVisible();

    const timeDir = mkdtempSync(join(tmpdir(), 'garrison-payroll-time-'));
    try {
      const privateFile = join(timeDir, 'time.json');
      function runTimeCommand(token: string, args: string[], input: Record<string, unknown>) {
        writeFileSync(privateFile, JSON.stringify(input), { mode: 0o600 });
        function call(...mode: string[]) {
          return JSON.parse(execFileSync(
            PYTHON_BIN,
            ['-m', 'scripts.garrisonctl', 'hr', ...args, '--file', privateFile, ...mode, '--json'],
            {
              cwd: BACKEND_DIR,
              encoding: 'utf8',
              env: {
                ...env,
                GARRISON_API_BASE_URL: 'http://127.0.0.1:8425',
                GARRISON_ENVIRONMENT: 'test',
                GARRISON_ACCESS_TOKEN: token
              }
            }
          )) as { data: { id: string; status: string; plan_sha256: string } };
        }
        const preview = call('--dry-run');
        expect(preview.data.plan_sha256).toMatch(/^[a-f0-9]{64}$/);
        return call('--apply', '--expect', preview.data.plan_sha256).data;
      }

      const sourceOvertime = runTimeCommand(makerSession.accessToken, ['overtime', 'create'], {
        employee_id: employeeId, work_date: '2025-06-03', requested_hours: '2.50',
        reason: 'Synthetic payroll source'
      });
      expect(sourceOvertime.status).toBe('submitted');
      const approvedOvertime = runTimeCommand(
        checkerSession.accessToken, ['overtime', 'decide', '--record-id', sourceOvertime.id],
        { decision: 'approved', approved_hours: '2.50' }
      );
      expect(approvedOvertime.status).toBe('approved');
      const sourceSheet = runTimeCommand(makerSession.accessToken, ['timesheets', 'create'], {
        employee_id: employeeId, period_start: '2025-06-02', period_end: '2025-06-06',
        regular_hours: '40.00', overtime_hours: '2.50', submit: true
      });
      expect(sourceSheet.status).toBe('submitted');
      for (const decision of ['approved', 'locked']) {
        const updated = runTimeCommand(
          checkerSession.accessToken, ['timesheets', 'decide', '--record-id', sourceSheet.id],
          { decision }
        );
        expect(updated.status).toBe(decision);
      }
    } finally {
      rmSync(timeDir, { recursive: true, force: true });
    }
    await sources.getByRole('button', { name: 'Refresh source review' }).click();
    await expect(time.getByText('Regular hours 40.00 · Overtime hours 2.50')).toBeVisible();
    const sourceFiles = new Map<string, Buffer>();
    for (const [source, panel] of [['time', time], ['leave', leave]] as const) {
      const ready = page.waitForEvent('download');
      await panel.getByRole('button', { name: `Download verified ${source} CSV` }).click();
      const downloaded = readFileSync((await (await ready).path())!);
      expect(createHash('sha256').update(downloaded).digest('hex')).toBe(
        await panel.getByLabel(`${source} input checksum`).textContent()
      );
      sourceFiles.set(source, downloaded);
      expect(downloaded.toString('utf8')).toContain(employeeId);
      expect(downloaded.toString('utf8')).not.toContain('Synthetic payroll source');
    }
    const sourceEvidence = {
      time_sha256: (await time.getByLabel('time input checksum').textContent())!,
      leave_sha256: (await leave.getByLabel('leave input checksum').textContent())!
    };
    const calculatePath = `/api/v1/hr/payroll/runs/${runId}/calculate`;
    const stale = await request.post(calculatePath, {
      headers: makerHeaders,
      data: { employee_ids: [employeeId], source_evidence: { ...sourceEvidence, time_sha256: '0'.repeat(64) } }
    });
    expect(stale.status()).toBe(409);
    await sources.getByRole('checkbox', { name: 'Attach reviewed time and leave evidence to the snapshot' }).check();
    await preparing.getByRole('button', { name: 'Calculate snapshot' }).click();
    await expect(preparing.getByText('Payroll snapshot calculated.', { exact: true })).toBeVisible();
    const replay = await request.post(calculatePath, {
      headers: makerHeaders, data: { employee_ids: [employeeId], source_evidence: sourceEvidence }
    });
    expect(replay.status()).toBe(200);
    expect((await request.post(calculatePath, {
      headers: makerHeaders, data: { employee_ids: [employeeId] }
    })).status()).toBe(409);
    const laterOvertime = await request.post('/api/v1/hr/overtime', {
      headers: makerHeaders,
      data: { employee_id: employeeId, work_date: '2025-06-12', requested_hours: '1.00', reason: 'Synthetic later change' }
    });
    expect(laterOvertime.status()).toBe(201);
    const laterOvertimeId = (await laterOvertime.json()).id as string;
    await expect(preparing.getByText('LKR 90.04', { exact: true })).toHaveCount(0);
    await preparing.getByRole('button', { name: 'Review selected snapshot' }).click();
    await expect(preparing.getByText('LKR 90.04', { exact: true })).toBeVisible();
    await expect(preparing.getByRole('button', { name: 'Approve and lock reviewed payroll' })).toHaveCount(0);

    await checking.getByLabel('Payroll run ID', { exact: true }).fill(runId);
    await checking.getByRole('button', { name: 'Open snapshot by ID' }).click();
    const review = checking.getByRole('article', { name: 'Reviewed payroll snapshot' });
    await expect(review.getByLabel('Controlled payroll policy')).toContainText('HR-POL-BROWSER');
    await expect(review.getByText('LKR 110.05', { exact: true })).toBeVisible();
    await expect(review.getByText('LKR 20.01', { exact: true })).toBeVisible();
    await review.getByText('Frozen payroll adjustments', { exact: true }).click();
    await expect(review.getByText(/LKR 10.00.*EARN-PORTAL-1/)).toBeVisible();
    await expect(review.getByText(/LKR 10.00.*DEDUCT-PORTAL-1/)).toBeVisible();
    const frozenSources = review.getByRole('region', { name: 'Frozen time and leave evidence' });
    await expect(frozenSources.getByText('Regular hours 40.00 · Overtime hours 2.50')).toBeVisible();
    for (const source of ['time', 'leave']) {
      const ready = checkerPage.waitForEvent('download');
      await frozenSources.getByRole('button', { name: `Download frozen ${source} CSV` }).click();
      expect(readFileSync((await (await ready).path())!)).toEqual(sourceFiles.get(source));
    }
    expect((await request.get(`/api/v1/hr/payroll/runs/${runId}/snapshot/sources/time`, {
      headers: { Authorization: `Bearer ${employeeSession.accessToken}` }
    })).status()).toBe(403);
    const blocked = checkerPage.waitForResponse((entry) =>
      new URL(entry.url()).pathname === `/api/v1/hr/payroll/runs/${runId}/approve`
    );
    await review.getByRole('button', { name: 'Approve and lock reviewed payroll' }).click();
    const denied = await blocked;
    expect(denied.status()).toBe(409);
    expect((await denied.json()).error_code).toBe('PAYROLL_SOURCES_CHANGED');
    await expect(checking.getByRole('alert')).toContainText('Time or leave changed after calculation');
    await expect(review.getByText(/Awaiting independent approval/)).toBeVisible();
    await expect(review.getByRole('button', { name: 'Publish payslips' })).toHaveCount(0);
    const resolved = await request.post(`/api/v1/hr/overtime/${laterOvertimeId}/decision`, {
      headers: { Authorization: `Bearer ${checkerSession.accessToken}` },
      data: { decision: 'rejected', notes: 'Synthetic unrelated overtime request' }
    });
    expect(resolved.status()).toBe(200);

    const approval = checkerPage.waitForRequest((entry) =>
      new URL(entry.url()).pathname === `/api/v1/hr/payroll/runs/${runId}/approve`
    );
    await review.getByRole('button', { name: 'Approve and lock reviewed payroll' }).click();
    expect((await approval).postDataJSON().expected_snapshot_digest).toMatch(/^[a-f0-9]{64}$/);
    await expect(review.getByText(/Approved and locked/)).toBeVisible();
    await review.getByRole('button', { name: 'Publish payslips' }).click();
    await expect(review.getByText('Payslips are published.', { exact: true })).toBeVisible();

    await review.getByRole('button', { name: 'Open Finance handoff' }).click();
    const finance = review.getByRole('region', { name: 'Payroll Finance handoff' });
    await expect(finance.getByText(/Payments: 1.*LKR 90.04/)).toBeVisible();
    await finance.getByRole('button', { name: 'Register reviewed export' }).click();
    await expect(finance.getByText('Payroll export registered.')).toBeVisible();
    const downloadReady = checkerPage.waitForEvent('download');
    await finance.getByRole('button', { name: 'Download verified payroll CSV' }).click();
    const download = await downloadReady;
    const contents = readFileSync((await download.path())!);
    expect(createHash('sha256').update(contents).digest('hex')).toBe(
      await finance.getByLabel('Export checksum').textContent()
    );
    const match = contents.toString('utf8').match(
      /^payment_reference,currency,net_amount\n([a-f0-9-]{36}),LKR,90\.04\n$/
    );
    expect(match).not.toBeNull();
    const paymentId = match![1];
    await finance.getByRole('combobox', { name: 'Exported payment' }).selectOption(paymentId);
    await finance.getByLabel('Settlement amount').fill('30.00');
    await finance.getByLabel('Settlement date').fill('2025-07-01');
    await finance.getByLabel('External evidence reference').fill('PAYROLL-TEST-001');
    await finance.getByRole('checkbox', { name: /I verified this outcome/ }).check();
    await finance.getByRole('button', { name: 'Record external settlement' }).click();
    await expect(finance.getByLabel('Selected payment balance')).toHaveText('partial · Outstanding LKR 60.04');
    const paymentEvent = finance.getByRole('listitem').filter({ hasText: 'PAYROLL-TEST-001' });
    await expect(paymentEvent).toBeVisible();
    const originalEventId = (await paymentEvent.locator('code').textContent())!;
    await finance.getByLabel('Settlement amount').fill('90.04');
    await finance.getByLabel('Settlement date').fill('2025-07-02');
    await finance.getByLabel('External evidence reference').fill('PAYROLL-TEST-EXCESS');
    await finance.getByRole('checkbox', { name: /I verified this outcome/ }).check();
    await finance.getByRole('button', { name: 'Record external settlement' }).click();
    await expect(finance.getByRole('alert')).toContainText('exceeds the outstanding amount');
    await expect(finance.getByLabel('Settlement amount')).toHaveValue('90.04');
    await finance.getByRole('combobox', { name: 'Payment outcome' }).selectOption('reversed');
    await finance.getByLabel('Settlement amount').fill('30.00');
    await finance.getByLabel('Original payment event ID').fill(originalEventId);
    await finance.getByLabel('External evidence reference').fill('PAYROLL-TEST-REVERSAL');
    await finance.getByRole('button', { name: 'Record external settlement' }).click();
    await expect(finance.getByLabel('Selected payment balance')).toHaveText('reversed · Outstanding LKR 90.04');
    await expect(finance.getByText(/PAYROLL-TEST-REVERSAL/)).toBeVisible();
    await checkerPage.reload();
    const reopened = await openPayroll(checkerPage);
    await reopened.getByLabel('Payroll run ID', { exact: true }).fill(runId);
    await reopened.getByRole('button', { name: 'Open snapshot by ID' }).click();
    await reopened.getByRole('button', { name: 'Open Finance handoff' }).click();
    await expect(reopened.getByLabel('Reconciliation totals')).toContainText('Outstanding LKR 90.04');
    await reopened.getByRole('combobox', { name: 'Exported payment' }).selectOption(paymentId);
    await expect(reopened.getByText(/PAYROLL-TEST-REVERSAL/)).toBeVisible();
    await expect(reopened.getByRole('button', { name: 'Close payroll period' })).toHaveCount(0);
    await reopened.getByLabel('Settlement amount').fill('90.04');
    await reopened.getByLabel('Settlement date').fill('2025-07-03');
    await reopened.getByLabel('External evidence reference').fill('PAYROLL-TEST-FINAL');
    await reopened.getByRole('checkbox', { name: /I verified this outcome/ }).check();
    await reopened.getByRole('button', { name: 'Record external settlement' }).click();
    await expect(reopened.getByLabel('Reconciliation totals')).toContainText('Outstanding LKR 0.00');
    await reopened.getByRole('checkbox', { name: 'I reviewed the final reconciliation.' }).check();
    await reopened.getByRole('button', { name: 'Close payroll period' }).click();
    await expect(reopened.getByText('Payroll period closed.', { exact: true })).toBeVisible();
    await expect(reopened.getByRole('button', { name: 'Record external settlement' })).toHaveCount(0);
    await checkerPage.reload();
    const closed = await openPayroll(checkerPage);
    await closed.getByLabel('Payroll run ID', { exact: true }).fill(runId);
    await closed.getByRole('button', { name: 'Open snapshot by ID' }).click();
    await closed.getByRole('button', { name: 'Open Finance handoff' }).click();
    await expect(closed.getByText('Payroll period closed.', { exact: true })).toBeVisible();
    await page.reload();
    const preparingCorrection = await openPayroll(page);
    await preparingCorrection.getByLabel('Payroll run ID', { exact: true }).fill(runId);
    await preparingCorrection.getByRole('button', { name: 'Open snapshot by ID' }).click();
    const makerCorrections = preparingCorrection.getByRole('region', { name: 'Closed payroll corrections' });
    await makerCorrections.getByRole('combobox', { name: 'Employee for correction' }).selectOption(paymentId);
    await makerCorrections.getByLabel('Corrected gross').fill('115.05');
    await makerCorrections.getByLabel('Corrected deductions').fill('20.01');
    await makerCorrections.getByLabel('Correction evidence reference').fill('PAYROLL-CORRECTION-001');
    await makerCorrections.getByRole('button', { name: 'Propose payroll correction' }).click();
    await expect(makerCorrections.getByText('PAYROLL-CORRECTION-001 · submitted')).toBeVisible();
    await expect(makerCorrections.getByRole('button', { name: 'Approve correction' })).toHaveCount(0);
    const reviewerCorrections = closed.getByRole('region', { name: 'Closed payroll corrections' });
    await reviewerCorrections.getByRole('combobox', { name: 'Employee for correction' }).selectOption(paymentId);
    await expect(reviewerCorrections.getByText(/Net change LKR 5.00/)).toBeVisible();
    await reviewerCorrections.getByRole('button', { name: 'Approve correction' }).click();
    await expect(reviewerCorrections.getByText('PAYROLL-CORRECTION-001 · approved')).toBeVisible();
    await expect(reviewerCorrections.getByText('Current reviewed net LKR 95.04')).toBeVisible();
    await checkerPage.reload();
    const history = await openPayroll(checkerPage);
    await history.getByLabel('Payroll run ID', { exact: true }).fill(runId);
    await history.getByRole('button', { name: 'Open snapshot by ID' }).click();
    const persisted = history.getByRole('region', { name: 'Closed payroll corrections' });
    await persisted.getByRole('combobox', { name: 'Employee for correction' }).selectOption(paymentId);
    await expect(persisted.getByText('PAYROLL-CORRECTION-001 · approved')).toBeVisible();



    await employeePage.getByRole('link', { name: 'My HR', exact: true }).click();
    await employeePage.getByText('My payslips', { exact: true }).click();
    await employeePage.getByRole('button', { name: 'Open payslip for 2025-06-01 to 2025-06-30' }).click();
    await expect(employeePage.getByText('LKR 90.04', { exact: true })).toBeVisible();
  } finally {
    await Promise.all(contexts.map((context) => context.close()));
  }
});

test('HR independently reviews legacy leave work dates', async ({ page, browser, request }) => {
  const [maker, reviewer] = seedProjectAccounts('hr_manager', 'hr_manager');
  const makerSession = await signIn(page, maker);
  const reviewerContext = await browser.newContext();
  const evidenceDir = mkdtempSync(join(tmpdir(), 'garrison-leave-evidence-'));
  try {
    const reviewerPage = await reviewerContext.newPage();
    const reviewerSession = await signIn(reviewerPage, reviewer);
    const employee = await request.post('/api/v1/hr/employees', {
      headers: { Authorization: `Bearer ${makerSession.accessToken}` },
      data: {
        employee_code: `LEGACY-LEAVE-${Date.now().toString(36)}`,
        first_name: 'Synthetic',
        last_name: 'Legacy Leave',
        employment_status: 'active',
        join_date: '2035-01-01'
      }
    });
    expect(employee.status()).toBe(201);
    const employeeId = (await employee.json() as { id: string }).id;
    const seeded = JSON.parse(execFileSync(PYTHON_BIN, [
      '-m', 'tests.browser_fixtures', 'seed-legacy-leave', '--employee-id', employeeId,
      '--reviewer-id', reviewerSession.userId
    ], { cwd: BACKEND_DIR, encoding: 'utf8', env })) as { request_id: string };

    async function openEvidence(target: Page, discover = false) {
      await target.getByRole('link', { name: 'HR & Workforce', exact: true }).click();
      await target.getByRole('button', { name: 'Leave', exact: true }).click();
      const panel = target.getByRole('region', { name: 'Legacy leave work dates' });
      if (discover) {
        await panel.getByRole('button', { name: 'Find leave with missing work dates' }).click();
        const candidate = panel.getByRole('listitem').filter({ hasText: employeeId });
        await candidate.getByRole('button', { name: 'View historical request' }).click();
      } else {
        await panel.getByLabel('Legacy leave request ID').fill(seeded.request_id);
        await panel.getByRole('button', { name: 'Open historical work dates' }).click();
      }
      await expect(
        panel.getByText('Approved range 2036-03-30 to 2036-04-03 · Approved days 2.00', {
          exact: true
        })
      ).toBeVisible();
      return panel;
    }

    const proposing = await openEvidence(page, true);
    await proposing.getByLabel('Historical work dates').fill('2036-03-31');
    await proposing.getByLabel('Historical evidence reference').fill('BROWSER-LEGACY-LEAVE-1');
    await proposing.getByRole('button', { name: 'Propose historical dates' }).click();
    await expect(proposing.getByRole('alert')).toContainText('match its units');
    function cliEvidence(token: string, ...args: string[]) {
      return JSON.parse(execFileSync(
        PYTHON_BIN, ['-m', 'scripts.garrisonctl', 'hr', 'leave', 'date-evidence', ...args, '--json'], {
          cwd: BACKEND_DIR,
          encoding: 'utf8',
          env: {
            ...env, GARRISON_API_BASE_URL: 'http://127.0.0.1:8425',
            GARRISON_ENVIRONMENT: 'test', GARRISON_ACCESS_TOKEN: token
          }
        }
      )) as { data: { id: string; digest: string; plan_sha256: string; status: string } };
    }
    const privateFile = join(evidenceDir, 'dates.json');
    writeFileSync(privateFile, JSON.stringify({
      proposal_id: globalThis.crypto.randomUUID(),
      work_dates: ['2036-03-31', '2036-04-01'],
      evidence_reference: 'BROWSER-LEGACY-LEAVE-1'
    }), { mode: 0o600 });
    const proposalArgs = ['propose', '--request-id', seeded.request_id, '--file', privateFile];
    const plan = cliEvidence(makerSession.accessToken, ...proposalArgs, '--dry-run');
    const receipt = cliEvidence(makerSession.accessToken, ...proposalArgs, '--apply', '--expect', plan.data.plan_sha256);
    expect(receipt.data.status).toBe('submitted');
    await proposing.getByRole('button', { name: 'Open historical work dates' }).click();
    await expect(proposing.getByText('BROWSER-LEGACY-LEAVE-1 · submitted')).toBeVisible();
    await expect(proposing.getByRole('button', { name: 'Approve historical dates' })).toHaveCount(0);

    const approving = await openEvidence(reviewerPage);
    await expect(approving.getByRole('button', { name: 'Approve historical dates' })).toBeVisible();
    const decisionArgs = [
      'decide', '--request-id', seeded.request_id, '--proposal-id', receipt.data.id,
      '--decision', 'approved', '--digest', receipt.data.digest
    ];
    const decisionPlan = cliEvidence(reviewerSession.accessToken, ...decisionArgs, '--dry-run');
    const approved = cliEvidence(
      reviewerSession.accessToken, ...decisionArgs, '--apply', '--expect', decisionPlan.data.plan_sha256
    );
    expect(approved.data.status).toBe('approved');
    await approving.getByRole('button', { name: 'Open historical work dates' }).click();
    await expect(approving.getByText('Retained work dates: 2036-03-31, 2036-04-01')).toBeVisible();
    await reviewerPage.reload();
    const persisted = await openEvidence(reviewerPage);
    await expect(persisted.getByText('BROWSER-LEGACY-LEAVE-1 · approved')).toBeVisible();
    await expect(persisted.getByText('Retained work dates: 2036-03-31, 2036-04-01')).toBeVisible();
  } finally {
    rmSync(evidenceDir, { recursive: true, force: true });
    await reviewerContext.close();
  }
});

test('HR opens and closes a restricted case without overwriting a newer review', async ({ page, browser }) => {
  const account = seedAccount('hr_manager');
  const owner = await signIn(page, account);
  await page.getByRole('link', { name: 'Employee relations' }).click();
  await expect(page.getByRole('heading', { name: 'Employee relations' })).toBeVisible();
  await expect(page.getByText('You have no cases.')).toBeVisible();

  await page.getByLabel('Case code').fill(account.projectCode);
  await page.getByLabel('Case title').fill('Synthetic employee-relations case');
  await page.getByLabel('Case details').fill('Restricted synthetic case narrative.');
  const created = page.waitForResponse((response) =>
    new URL(response.url()).pathname === '/api/v1/hr/cases' && response.request().method() === 'POST'
  );
  await page.getByRole('button', { name: 'Open case' }).click();
  const response = await created;
  expect(response.status()).toBe(201);
  const { id } = await response.json() as { id: string };
  await expect(page.getByText('Restricted synthetic case narrative.')).toBeVisible();

  const headers = { Authorization: `Bearer ${owner.accessToken}` };
  const concurrent = await page.request.post(`/api/v1/hr/cases/${id}/close`, {
    headers,
    data: { status: 'investigating', resolution_notes: 'Concurrent synthetic note.' }
  });
  expect(concurrent.ok()).toBeTruthy();
  await page.getByLabel('New status').selectOption('closed');
  await page.getByLabel('New resolution notes').fill('Reviewed synthetic resolution.');
  const conflict = page.waitForResponse((result) =>
    new URL(result.url()).pathname.endsWith(`/cases/${id}/close`) && result.status() === 409
  );
  await page.getByRole('button', { name: 'Save case update' }).click();
  await conflict;
  await expect(page.getByRole('alert')).toContainText(/review/i);
  await page.getByRole('button', { name: 'Reload case' }).click();
  await expect(page.getByText('Concurrent synthetic note.')).toBeVisible();
  await expect(page.getByLabel('New resolution notes')).toHaveValue('Reviewed synthetic resolution.');
  await page.getByRole('button', { name: 'Save case update' }).click();
  await expect(page.getByText('Case status closed')).toBeVisible();

  await page.reload();
  await page.getByRole('button', { name: `Review ${account.projectCode}` }).click();
  await expect(page.getByText('Reviewed synthetic resolution.')).toBeVisible();
  await expect(page.getByRole('button', { name: 'Save case update' })).toHaveCount(0);

  const otherContext = await browser.newContext();
  try {
    const other = await otherContext.newPage();
    const outsider = await signIn(other, seedAccount('hr_manager'));
    await other.goto('/hr/cases');
    await expect(other.getByText('You have no cases.')).toBeVisible();
    const forbidden = await other.request.get(`/api/v1/hr/cases/${id}`, {
      headers: { Authorization: `Bearer ${outsider.accessToken}` }
    });
    expect(forbidden.status()).toBe(404);
  } finally {
    await otherContext.close();
  }

  const directorContext = await browser.newContext();
  try {
    const director = await directorContext.newPage();
    await signIn(director, seedAccount('managing_director'));
    await expect(director.getByRole('link', { name: 'Employee relations' })).toHaveCount(0);
    await director.goto('/hr/cases');
    await expect(director.getByRole('heading', { name: 'Employee relations' })).toHaveCount(0);
  } finally {
    await directorContext.close();
  }
});

test('reviewed recovery opens the reset confirmation without requesting another code', async ({ page }) => {
  const reference = '67de2676-1cca-4d56-90a1-ae771509e633';
  await page.goto('/password-reset#recovery=' + reference);
  await expect(page.getByLabel('Email', { exact: true })).toHaveCount(0);
  await expect(page.getByLabel('Verification code', { exact: true })).toBeVisible();
  await expect(page.getByRole('button', { name: 'Reset password' })).toBeVisible();
  await page.goto('/login');
  await page.goto('/password-reset#recovery=unrecognized');
  await expect(page.getByLabel('Email', { exact: true })).toBeVisible();
  await expect(page.getByRole('button', { name: 'Send reset code' })).toBeVisible();
});
