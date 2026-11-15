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

test('HR saves a letter template and previews it with employee records', async ({
  page,
  request
}) => {
  const session = await signIn(page, seedAccount('hr_manager'));
  const code = `LETTER-${Date.now()}`;
  const employee = await request.post('/api/v1/hr/employees', {
    headers: { Authorization: `Bearer ${session.accessToken}` },
    data: { employee_code: code, first_name: 'Synthetic', last_name: 'Letter Employee' }
  });
  expect(employee.status()).toBe(201);
  const employeeId = (await employee.json()).id as string;

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
  await page.getByRole('combobox', { name: 'Letter employee', exact: true }).selectOption(employeeId);
  await page.getByLabel('purpose', { exact: true }).fill('a staff record');
  await page.getByRole('button', { name: 'Preview letter' }).click();
  await expect(page.getByText('Confirmation for Synthetic Letter Employee')).toBeVisible();
  await expect(page.getByText(`Employee ${code} requests a staff record.`)).toBeVisible();
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
    data: { requisition_code: `REQ-O-${unique}`, title: 'MEP Lead', headcount_requested: 2 }
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
  const application = await request.post('/api/v1/hr/applications', {
    headers,
    data: { requisition_id: openReqId, candidate_id: (await candidate.json()).id }
  });
  expect(application.status()).toBe(201);
  const appId = (await application.json()).id as string;
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
  for (const stage of ['screening', 'interview', 'evaluation']) {
    expect(
      (
        await request.patch(`/api/v1/hr/applications/${appId}/stage`, {
          headers,
          data: { stage }
        })
      ).status()
    ).toBe(200);
  }

  await page.reload();
  await page.getByRole('button', { name: 'Recruitment', exact: true }).click();
  await expect(reqItem).toContainText('Headcount 3 · rejected · Rejected: Budget deferred for Q4.');

  const deadline = new Date(Date.now() + 7 * 86_400_000).toISOString().slice(0, 10);
  const createForm = page
    .locator('form')
    .filter({ has: page.getByRole('button', { name: 'Save recruitment record' }) });
  await createForm.getByLabel('New record').selectOption('offer');
  await createForm.getByLabel('Reference code').fill(`OFR-UI-${unique}`);
  await createForm.getByLabel('Proposed title').fill('Junior MEP Lead');
  await createForm.locator('select[name="application"]').selectOption(appId);
  await createForm.getByLabel('Valid until').fill(deadline);
  await createForm.getByRole('button', { name: 'Save recruitment record' }).click();

  const v1Card = page
    .getByRole('article')
    .filter({ hasText: `OFR-UI-${unique} · Junior MEP Lead` });
  await expect(v1Card).toContainText(`v1 · draft · Valid until ${deadline}`);
  await v1Card.getByLabel('Offer code').fill(`OFR-UI2-${unique}`);
  await v1Card.getByLabel('Proposed title').fill('Senior MEP Lead');
  await v1Card.getByRole('button', { name: 'Reissue offer' }).click();

  const v2Card = page
    .getByRole('article')
    .filter({ hasText: `OFR-UI2-${unique} · Senior MEP Lead` });
  await expect(v2Card).toContainText('v2 · draft');
  await expect(v1Card).toContainText('v1 · superseded');

  await page.reload();
  await page.getByRole('button', { name: 'Recruitment', exact: true }).click();
  await expect(v2Card).toContainText('v2 · draft');
  await expect(v1Card).toContainText('v1 · superseded');
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
  const isoDate = (days: number) => new Date(Date.now() + days * 86_400_000).toISOString().slice(0, 10);
  const created = await request.post('/api/v1/hr/onboarding', {
    headers,
    data: {
      employee_id: (await employee.json()).id,
      start_date: isoDate(-30),
      probation_end_date: isoDate(2)
    }
  });
  expect(created.status()).toBe(201);
  const { tasks } = (await created.json()) as { tasks: { id: string }[] };
  for (const task of tasks) {
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
  await card.getByLabel('Probation review reason', { exact: true }).fill('Extended for further review.');
  await card.getByRole('button', { name: 'Record probation decision' }).click();
  await expect(card.getByText(`Probation end date ${isoDate(15)}`, { exact: true })).toBeVisible();
  await page.reload();
  await page.getByRole('button', { name: 'Recruitment', exact: true }).click();
  await card.getByRole('combobox', { name: 'Confirmed employment category' }).selectOption('contract');
  await card.getByLabel('Probation review reason', { exact: true }).fill('Confirmed based on documented results.');
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
    const project = (await (await request.get(projectEndpoint, { headers: directorHeaders })).json()) as {
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
    const linked = await request.post(`/api/v1/hr/employees/${(await created.json()).id}/link-account`, {
      headers: directorHeaders,
      data: { user_id: workerId }
    });
    expect(linked.status()).toBe(200);

    await page.getByRole('link', { name: 'HR & Workforce', exact: true }).click();
    await page.getByRole('button', { name: 'Directory & Org', exact: true }).click();
    await page.getByLabel('Search employees').fill(employeeCode);
    await page.getByRole('row').filter({ hasText: employeeCode }).getByRole('button', { name: 'Inspect' }).click();
    await page.getByLabel('Find project by name or code').fill(project.code);
    await page.getByRole('button', { name: 'Find project', exact: true }).click();
    await page.getByRole('combobox', { name: 'Assignment project' }).selectOption(director.projectId);
    await page.getByLabel('Assignment reason').fill('Staffing review.');
    await page.getByRole('button', { name: 'Send assignment request' }).click();
    await expect(page.getByText('Request sent for project review.')).toBeVisible();
    const before = await request.get(`${projectEndpoint}/members`, { headers: directorHeaders });
    expect((await before.json()).some((item: { user_id: string }) => item.user_id === workerId)).toBe(false);

    await directorPage.getByRole('link', { name: 'Projects', exact: true }).click();
    await directorPage.getByRole('button', { name: project.name, exact: true }).click();
    const detail = directorPage.getByRole('region', { name: 'Project details' });
    await detail.getByRole('button', { name: 'Team', exact: true }).click();
    await detail.getByRole('button', { name: 'Approve assignment', exact: true }).click();
    await expect(detail.getByText('Assignment decision recorded.')).toBeVisible();
    const after = await request.get(`${projectEndpoint}/members`, { headers: directorHeaders });
    expect((await after.json()).some((item: { user_id: string }) => item.user_id === workerId)).toBe(true);

    await page.reload();
    await page.getByRole('button', { name: 'Directory & Org', exact: true }).click();
    await expect(page.getByText(`Synthetic Assignment · ${project.code} · Add · approved`)).toBeVisible();
  } finally {
    await directorContext.close();
  }
});

test('revoking the HR role clears the open HR workspace and prevents access after sign-in', async ({
  page,
  browser,
  request
}) => {
  const director = seedAccount();
  const manager = seedAccount('hr_manager', director.projectId);
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

test('a linked employee manages their own leave and reopens a completed HR request', async ({
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
    const managerPage = await managerContext.newPage();
    const managerSession = await signIn(managerPage, manager);
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

    const subject = `Synthetic service request ${unique}`;
    await workerPage.getByPlaceholder('Subject', { exact: true }).fill(subject);
    await workerPage.getByRole('button', { name: 'Submit request', exact: true }).click();
    await expect(workerPage.getByText('HR service request submitted.', { exact: true })).toBeVisible();
    await managerPage.getByRole('link', { name: 'HR & Workforce', exact: true }).click();
    await managerPage.getByRole('button', { name: 'Policies & Requests' }).click();
    const reviewCard = managerPage.getByText(subject).locator('..');
    await reviewCard.getByRole('button', { name: 'Start review' }).click();
    const response = 'Your synthetic request has been reviewed.';
    await reviewCard.getByLabel('Response shared with the employee').fill(response);
    await reviewCard.getByRole('button', { name: 'Complete request' }).click();
    await expect(reviewCard).toContainText('(completed)');
    await workerPage.reload();
    const myRequest = workerPage.getByText(subject).locator('..');
    await expect(myRequest).toContainText(response);
    await myRequest.getByRole('button', { name: /Reopen request/ }).click();
    await expect(workerPage.getByText('HR service request reopened.', { exact: true })).toBeVisible();
    await workerPage.reload();
    await expect(myRequest).toContainText('open');
    await expect(myRequest).toContainText(response);
    await expect(myRequest.getByRole('button', { name: /Reopen request/ })).toHaveCount(0);
  } finally {
    await directorContext.close();
    await managerContext.close();
    await workerContext.close();
  }
});
