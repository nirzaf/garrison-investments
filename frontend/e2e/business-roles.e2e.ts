import { execFileSync } from 'node:child_process';
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

test('roles page and users roles endpoint expose the nine canonical roles and the HR permissions', async ({
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
  const director = seedAccount();
  const hrManager = seedAccount('hr_manager', director.projectId);
  const siteSupervisor = seedAccount('site_supervisor', director.projectId);

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
  const director = seedAccount();
  const qs = seedAccount('quantity_surveyor', director.projectId);

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
  const director = seedAccount();
  const seniorSupervisor = seedAccount('senior_site_supervisor', director.projectId);
  const siteSupervisor = seedAccount('site_supervisor', director.projectId);

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

test('HR staff draft, approve and publish a calendar and download the aggregate summary', async ({
  page,
  browser,
  request
}) => {
  const preparer = seedAccount('hr_manager');
  const reviewer = seedAccount('hr_manager', preparer.projectId);
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

  const calendarName = `Synthetic work calendar ${Date.now()}`;
  await page.getByRole('button', { name: 'Attendance', exact: true }).click();
  await page.getByText('Work calendars, holidays and shifts', { exact: true }).click();
  await page.getByLabel('Calendar code').fill(`CAL-${Date.now()}`);
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
  const draft = page.getByRole('listitem').filter({ hasText: calendarName });
  await draft.getByRole('button', { name: 'Submit calendar' }).click();
  await expect(draft.getByText(/^submitted/)).toBeVisible();
  await expect(draft.getByRole('button', { name: 'Approve calendar' })).toHaveCount(0);

  const reviewerContext = await browser.newContext();
  try {
    const approvalPage = await reviewerContext.newPage();
    await signIn(approvalPage, reviewer);
    await approvalPage.getByRole('link', { name: 'HR & Workforce', exact: true }).click();
    await approvalPage.getByRole('button', { name: 'Attendance', exact: true }).click();
    await approvalPage.getByText('Work calendars, holidays and shifts', { exact: true }).click();
    const record = approvalPage.getByRole('listitem').filter({ hasText: calendarName });
    await record.getByRole('button', { name: 'Approve calendar' }).click();
    await record.getByRole('button', { name: 'Publish calendar' }).click();
    await expect(record.getByText(/^published/)).toBeVisible();

    await page.getByText('Import attendance CSV', { exact: true }).click();
    await page.getByLabel('Attendance CSV', { exact: true }).setInputFiles({
      name: 'attendance.csv',
      mimeType: 'text/csv',
      buffer: Buffer.from(
        'employee_code,work_date,attendance_status,worked_hours,check_in_at,check_out_at\n' +
          `${employeeCode},2027-01-04,present,7.50,2027-01-04T08:30:00+05:30,2027-01-04T16:00:00+05:30\n`
      )
    });
    await page.getByRole('button', { name: 'Preview attendance', exact: true }).click();
    await expect(page.getByRole('list', { name: 'Attendance import preview' })).toContainText(
      employeeCode
    );
    await page.getByRole('button', { name: 'Apply attendance import', exact: true }).click();
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
  await expect(page.getByText('Scheduled training', { exact: true })).toHaveCount(0);

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
  const director = seedAccount();
  const hr = seedAccount('hr_manager', director.projectId);
  const lineManager = seedAccount('group_project_manager', director.projectId);
  const worker = seedAccount('quantity_surveyor', director.projectId);
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

test('a linked employee submits and cancels their own leave in Chrome', async ({
  browser,
  request
}) => {
  const director = seedAccount();
  const manager = seedAccount('hr_manager', director.projectId);
  const worker = seedAccount('quantity_surveyor', director.projectId);
  const directorContext = await browser.newContext();
  const managerContext = await browser.newContext();
  const workerContext = await browser.newContext();
  try {
    const directorSession = await signIn(await directorContext.newPage(), director);
    const managerSession = await signIn(await managerContext.newPage(), manager);
    const workerPage = await workerContext.newPage();
    const workerSession = await signIn(workerPage, worker);
    const managerHeaders = { Authorization: `Bearer ${managerSession.accessToken}` };
    const unique = Date.now().toString(36);
    const employee = await request.post('/api/v1/hr/employees', {
      headers: managerHeaders,
      data: {
        employee_code: `LEAVE-${unique}`,
        first_name: 'Synthetic',
        last_name: 'Employee',
        work_email: worker.email,
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
    const leaveType = await request.post('/api/v1/hr/leave/types', {
      headers: managerHeaders,
      data: { code: `LT-${unique}`, name: leaveName, is_paid: false }
    });
    expect(leaveType.status()).toBe(201);
    const leaveTypeId = (await leaveType.json()).id as string;

    await workerPage.getByRole('link', { name: 'My HR', exact: true }).click();
    await expect(
      workerPage.getByRole('heading', { name: 'My HR Profile', exact: true })
    ).toBeVisible();
    await workerPage.getByLabel('Leave type', { exact: true }).selectOption(leaveTypeId);
    await workerPage.getByLabel('Leave starts').fill('2026-12-04');
    await workerPage.getByLabel('Leave ends').fill('2026-12-04');
    await workerPage.getByRole('button', { name: 'Submit leave request' }).click();
    await expect(workerPage.getByText('Leave request submitted.', { exact: true })).toBeVisible();
    await workerPage.getByRole('button', { name: 'Cancel leave' }).click();
    await expect(workerPage.getByText('Leave request cancelled.', { exact: true })).toBeVisible();
    await workerPage.reload();
    await expect(workerPage.getByText('cancelled', { exact: true })).toBeVisible();
    const othersDirectory = await workerPage.request.get('/api/v1/hr/employees', {
      headers: { Authorization: `Bearer ${workerSession.accessToken}` }
    });
    expect(othersDirectory.status()).toBe(403);
  } finally {
    await directorContext.close();
    await managerContext.close();
    await workerContext.close();
  }
});
