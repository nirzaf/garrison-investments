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
  ['hr_executive', 'HR Executive'],
  ['administrative_executive', 'Administrative Executive']
] as const;

const PROTECTED_ROLES = new Set([
  'managing_director',
  'operations_director',
  'hr_manager'
]);

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
  return JSON.parse(execFileSync(PYTHON_BIN, args, { cwd: BACKEND_DIR, encoding: 'utf8' })) as SeededAccount;
}

async function signIn(page: Page, account: Pick<SeededAccount, 'email' | 'password'>): Promise<LoginResult> {
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

test('roles page and users roles endpoint expose only the 10 canonical roles and 16 permissions', async ({
  page
}) => {
  const director = seedAccount();
  const session = await signIn(page, director);

  await page.getByRole('link', { name: 'Roles & Permissions', exact: true }).click();
  await expect(page).toHaveURL(/\/roles$/);
  await expect(page.getByRole('link', { name: 'HR & Workforce' })).toHaveCount(0);
  await expect(
    page.getByRole('heading', { name: 'Roles & permissions', exact: true })
  ).toBeVisible();
  await expect(page.getByText('Your account has 16 of 16 listed permissions.')).toBeVisible();

  await expect(page.locator('main article')).toHaveCount(CANONICAL_ROLES.length);
  await expect(page.locator('tbody tr')).toHaveCount(CANONICAL_PERMISSIONS.length);

  for (const [key, label] of CANONICAL_ROLES) {
    const card = page
      .locator('main article')
      .filter({ has: page.getByText(key, { exact: true }) });
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
    expect(item.permissions.every((permission) => canonicalPermissionSet.has(permission))).toBe(true);
  }
  const unapprovedHrRoute = await page.request.get('/api/v1/hr/employees', {
    headers: { Authorization: `Bearer ${session.accessToken}` }
  });
  expect(unapprovedHrRoute.status()).toBe(404);
});

test('hr_manager enforces protected role ceiling while managing_director sends expected_updated_at on role change', async ({
  browser
}) => {
  const director = seedAccount();
  const opsDirector = seedAccount('operations_director', director.projectId);
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

    const createRoleSelect = hrPage
      .locator('form')
      .filter({ has: hrPage.getByRole('button', { name: 'Create user' }) })
      .locator('select');
    const createOptionValues = (
      await createRoleSelect.locator('option').evaluateAll((options) =>
        options.map((option) => (option as HTMLOptionElement).value)
      )
    ).filter(Boolean);

    const expectedHrAssignable = CANONICAL_ROLES.map(([key]) => key)
      .filter((key) => !PROTECTED_ROLES.has(key))
      .sort();
    expect(createOptionValues.sort()).toEqual(expectedHrAssignable);
    for (const protectedRole of PROTECTED_ROLES) {
      expect(createOptionValues).not.toContain(protectedRole);
    }

    const privilegedAccountEmail = `forbidden-director-${Date.now()}@example.com`;
    const forbiddenAssignment = await hrPage.request.post('/api/v1/users', {
      headers: hrHeaders,
      data: {
        email: privilegedAccountEmail,
        temporary_password: 'BrowserFixture!2027',
        full_name: 'Forbidden director assignment',
        role: 'managing_director',
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
    for (const protectedEmail of [director.email, opsDirector.email]) {
      await searchInput.fill(protectedEmail);
      const protectedRow = hrPage.getByRole('row').filter({ hasText: protectedEmail });
      await expect(protectedRow).toBeVisible();
      await expect(protectedRow.getByRole('button', { name: 'Change role' })).toHaveCount(0);
      await expect(protectedRow.getByRole('button', { name: 'Deactivate' })).toHaveCount(0);
    }
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
    const beforeUser = ((await targetBefore.json()) as {
      items: Array<{ id: string; updated_at: string }>;
    }).items[0];
    expect(beforeUser).toBeDefined();
    await directorPage.getByRole('link', { name: 'Users', exact: true }).click();
    await directorPage.getByPlaceholder('Search', { exact: true }).fill(siteSupervisor.email);

    const targetRow = directorPage.getByRole('row').filter({ hasText: siteSupervisor.email });
    await expect(targetRow).toBeVisible();
    await targetRow.getByRole('button', { name: 'Change role' }).click();
    await targetRow.getByRole('combobox', { name: /New role/ }).selectOption('senior_site_supervisor');

    const patchRequestPromise = directorPage.waitForRequest(
      (request) =>
        request.method() === 'PATCH' &&
        new URL(request.url()).pathname.startsWith('/api/v1/users/')
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
    await expect(qsPage.getByRole('status').filter({ hasText: /^Daily report .+ submitted\.$/ })).toBeVisible();
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
