import { execFileSync } from 'node:child_process';
import { env } from 'node:process';
import { fileURLToPath } from 'node:url';

import { expect, test, type Page } from '@playwright/test';

const backendDirectory = fileURLToPath(new URL('../../backend/', import.meta.url));
const commonLinks = {
  'My HR': '/me/hr',
  Dashboard: '/dashboard',
  Approvals: '/approvals',
  'Roles & Permissions': '/roles',
  'User Manual': '/manual'
};
const guardedLinks = {
  'HR & Workforce': '/hr',
  'Employee relations': '/hr/cases',
  Projects: '/projects',
  Reports: '/reports/daily',
  'Supervisor updates': '/reports/supervisor-update',
  Materials: '/materials',
  Suppliers: '/suppliers',
  Finance: '/finance',
  Analytics: '/analytics',
  Documents: '/documents',
  Photos: '/photos',
  Security: '/security',
  'Launch readiness': '/delivery',
  Audit: '/admin/audit-logs',
  Imports: '/admin/imports',
  Users: '/admin/users'
};
type GuardedLink = keyof typeof guardedLinks;
type RoleCase = {
  role: string;
  label: string;
  links: GuardedLink[];
  inbox: boolean;
  feature: GuardedLink;
  heading: string;
  action: string;
  canAct: boolean;
  denied?: { route: string; api: string; landing?: string };
};

const companyLinks: GuardedLink[] = [
  'Projects',
  'Reports',
  'Supervisor updates',
  'Materials',
  'Suppliers',
  'Finance',
  'Analytics',
  'Documents',
  'Photos',
  'Launch readiness',
  'Users'
];
const cases: RoleCase[] = [
  {
    role: 'managing_director',
    label: 'Managing Director',
    links: [...companyLinks, 'Security', 'Audit', 'Imports', 'HR & Workforce'],
    inbox: true,
    feature: 'Users',
    heading: 'Users',
    action: 'Create user',
    canAct: true
  },
  {
    role: 'operations_director',
    label: 'Operations Director',
    links: [...companyLinks, 'Security', 'Audit', 'Imports', 'HR & Workforce'],
    inbox: true,
    feature: 'Users',
    heading: 'Users',
    action: 'Create user',
    canAct: true
  },
  {
    role: 'group_project_manager',
    label: 'Group Project Manager',
    links: [
      'Projects',
      'Reports',
      'Supervisor updates',
      'Materials',
      'Finance',
      'Documents',
      'Photos',
      'Users'
    ],
    inbox: true,
    feature: 'Projects',
    heading: 'Projects',
    action: 'New project',
    canAct: false
  },
  {
    role: 'mep_project_manager',
    label: 'MEP Project Manager',
    links: [
      'Projects',
      'Reports',
      'Supervisor updates',
      'Materials',
      'Suppliers',
      'Documents',
      'Photos',
      'Users'
    ],
    inbox: true,
    feature: 'Suppliers',
    heading: 'Suppliers And Compliance',
    action: 'New supplier',
    canAct: true,
    denied: { route: '/finance', api: '/api/v1/finance/invoices' }
  },
  {
    role: 'quantity_surveyor',
    label: 'Quantity Surveyor',
    links: ['Reports', 'Materials', 'Suppliers', 'Documents', 'Users'],
    inbox: false,
    feature: 'Documents',
    heading: 'Document Library',
    action: 'Upload',
    canAct: false,
    denied: { route: '/projects', api: '/api/v1/projects' }
  },
  {
    role: 'senior_site_supervisor',
    label: 'Senior Site Supervisor',
    links: ['Projects', 'Reports', 'Materials', 'Documents', 'Users'],
    inbox: false,
    feature: 'Materials',
    heading: 'Inventory And Stores',
    action: 'Add item',
    canAct: false,
    denied: { route: '/finance', api: '/api/v1/finance/invoices' }
  },
  {
    role: 'site_supervisor',
    label: 'Site Supervisor',
    links: ['Projects', 'Reports', 'Materials', 'Documents', 'Users'],
    inbox: false,
    feature: 'Materials',
    heading: 'Inventory And Stores',
    action: 'Add item',
    canAct: false,
    denied: { route: '/finance', api: '/api/v1/finance/invoices' }
  },
  {
    role: 'hr_manager',
    label: 'HR Manager',
    links: [
      'Analytics',
      'Launch readiness',
      'Users',
      // Present only when playwright.config.ts starts browser_fixtures with --enable-fixture-hr-cases.
      'Employee relations',
      'HR & Workforce'
    ],
    inbox: false,
    feature: 'Users',
    heading: 'Users',
    action: 'Create user',
    canAct: false,
    denied: { route: '/reports/daily', api: '/api/v1/reports' }
  },
  {
    role: 'hr_executive_reader',
    label: 'HR Executive',
    links: ['Documents', 'Users'],
    inbox: false,
    feature: 'Users',
    heading: 'Users',
    action: 'Create user',
    canAct: false,
    denied: { route: '/hr', api: '/api/v1/hr/employees' }
  },
  {
    role: 'administrative_executive',
    label: 'Administrative Executive',
    links: ['Materials', 'Suppliers', 'Analytics', 'Documents', 'Launch readiness', 'Users'],
    inbox: false,
    feature: 'Materials',
    heading: 'Inventory And Stores',
    action: 'Add item',
    canAct: false,
    denied: { route: '/finance', api: '/api/v1/finance/invoices' }
  }
];

test.use({ trace: 'off' });

function browserFixture(...args: string[]) {
  return execFileSync(
    env.BROWSER_TEST_PYTHON ?? 'python',
    ['-m', 'tests.browser_fixtures', ...args],
    { cwd: backendDirectory, encoding: 'utf8' }
  );
}

function seedAccount(role: string) {
  return JSON.parse(browserFixture('seed', '--role', role)) as { email: string; password: string };
}

async function signIn(page: Page, role: string) {
  const account = seedAccount(role);

  await page.goto('/login');
  await page.getByLabel('Email', { exact: true }).fill(account.email);
  await page.getByLabel('Password', { exact: true }).fill(account.password);
  await page.getByRole('button', { name: 'Continue' }).click();
  const code = (await page.getByText(/^Development code:/).innerText()).match(/\d{6}/)?.[0];
  if (!code) throw new Error('The test API did not expose the verification code.');
  await page.getByLabel('Verification code').fill(code);
  const verification = page.waitForResponse(
    (response) => response.url().endsWith('/api/v1/auth/verify-otp') && response.ok()
  );
  await page.getByRole('button', { name: 'Verify and sign in' }).click();
  return ((await (await verification).json()) as { access_token: string }).access_token;
}

test('an expired login code requires a new challenge before a session is restored', async ({
  page,
  context,
  request
}) => {
  const account = seedAccount('group_project_manager');
  const submitPassword = async () => {
    await page.getByLabel('Password', { exact: true }).fill(account.password);
    const login = page.waitForResponse(
      (response) => response.url().endsWith('/api/v1/auth/login') && response.ok()
    );
    await page.getByRole('button', { name: 'Continue' }).click();
    const result = (await (await login).json()) as { challenge_id: string; dev_otp: string };
    await expect(page.getByText(/^Development code:/)).toBeVisible();
    return result;
  };
  const submitCode = async (code: string, status: number) => {
    await page.getByLabel('Verification code').fill(code);
    const verification = page.waitForResponse((response) =>
      response.url().endsWith('/api/v1/auth/verify-otp')
    );
    await page.getByRole('button', { name: 'Verify and sign in' }).click();
    const response = await verification;
    expect(response.status()).toBe(status);
    return response;
  };

  await page.goto('/login');
  await page.getByLabel('Email', { exact: true }).fill(account.email);
  const initial = await submitPassword();
  const wrong = initial.dev_otp === '000000' ? '000001' : '000000';
  expect((await (await submitCode(wrong, 401)).json()).error_code).toBe('OTP_FAILED');
  await expect(page).toHaveURL('/login');

  browserFixture('expire-login', '--challenge-id', initial.challenge_id);
  expect((await (await submitCode(initial.dev_otp, 401)).json()).error_code).toBe('OTP_FAILED');
  await expect(page.getByRole('alert')).toContainText('Check the code or request a new one.');
  expect((await context.cookies()).some((cookie) => cookie.name === 'refresh_token')).toBe(false);
  expect((await request.get('/api/v1/auth/me')).status()).toBe(401);

  const requestNew = page.getByRole('button', { name: 'Request a new code' });
  await expect(requestNew).toBeVisible();
  await requestNew.click();
  await expect(page.getByLabel('Email', { exact: true })).toHaveValue(account.email);
  await expect(page.getByLabel('Password', { exact: true })).toHaveValue('');
  await expect(page.getByLabel('Password', { exact: true })).toBeFocused();
  await expect(page.getByText(/^Development code:/)).toHaveCount(0);
  const fresh = await submitPassword();
  expect(fresh.challenge_id).not.toBe(initial.challenge_id);
  await expect(page.getByLabel('Verification code')).toHaveValue('');
  await expect(page.getByLabel('Verification code')).toBeFocused();
  const verified = await (await submitCode(fresh.dev_otp, 200)).json();
  expect(verified.user).toMatchObject({ email: account.email, role: 'group_project_manager' });
  await expect(page).toHaveURL('/dashboard');

  const refresh = page.waitForResponse(
    (response) => response.url().endsWith('/api/v1/auth/refresh') && response.ok()
  );
  await page.reload();
  const restored = await (await refresh).json();
  expect(restored.user).toMatchObject({ id: verified.user.id, role: 'group_project_manager' });
  await expect(page).toHaveURL('/dashboard');
  await expect(
    (await sidebar(page)).getByRole('link', { name: 'Projects', exact: true })
  ).toBeVisible();
});

async function sidebar(page: Page) {
  const nav = page.getByRole('complementary').getByRole('navigation');
  const menu = page.getByRole('button', { name: 'Open navigation' });
  if ((await menu.isVisible()) && !(await nav.isVisible())) await menu.click();
  await expect(nav).toBeVisible();
  return nav;
}

for (const roleCase of cases) {
  test(`${roleCase.label} navigation, manual and action gates match its role`, async ({
    page,
    request
  }) => {
    if (roleCase.role === 'site_supervisor')
      await page.setViewportSize({ width: 390, height: 844 });
    const token = await signIn(page, roleCase.role);
    await expect(page).toHaveURL('/dashboard');

    const roleOptions = await request.get('/api/v1/users/roles', {
      headers: { Authorization: `Bearer ${token}` }
    });
    expect(roleOptions.ok()).toBe(true);
    expect((await roleOptions.json()).items.map((item: { role: string }) => item.role)).toEqual([
      'administrative_executive',
      'group_project_manager',
      'hr_executive_reader',
      'hr_manager',
      'managing_director',
      'mep_project_manager',
      'operations_director',
      'quantity_surveyor',
      'senior_site_supervisor',
      'site_supervisor'
    ]);

    const nav = await sidebar(page);
    await expect(nav.getByRole('link')).toHaveCount(
      Object.keys(commonLinks).length + roleCase.links.length
    );
    for (const [label, path] of Object.entries(commonLinks)) {
      await expect(nav.getByRole('link', { name: label, exact: true })).toHaveAttribute(
        'href',
        path
      );
    }
    for (const label of roleCase.links) {
      const path =
        label === 'Reports' && ['senior_site_supervisor', 'site_supervisor'].includes(roleCase.role)
          ? guardedLinks['Supervisor updates']
          : guardedLinks[label];
      await expect(nav.getByRole('link', { name: label, exact: true })).toHaveAttribute(
        'href',
        path
      );
    }

    await nav.getByRole('link', { name: 'User Manual', exact: true }).click();
    await expect(
      page.getByRole('heading', { name: `${roleCase.label} Manual`, exact: true })
    ).toBeVisible();

    await page.getByRole('button', { name: 'Common Features', exact: true }).click();
    await expect(page.getByRole('heading', { name: 'Approval Views', exact: true })).toBeVisible();
    await page.getByRole('button', { name: 'Permissions & Limits', exact: true }).click();
    await expect(page.getByRole('heading', { name: 'What you can do', exact: true })).toBeVisible();
    await page.getByRole('link', { name: /View the full permissions matrix/ }).click();
    await expect(page).toHaveURL('/roles');

    await (await sidebar(page)).getByRole('link', { name: 'Approvals', exact: true }).click();
    await expect(page.getByRole('button', { name: 'My submitted requests' })).toBeVisible();
    await expect(page.getByRole('button', { name: 'Inbox', exact: true })).toHaveCount(
      roleCase.inbox ? 1 : 0
    );
    await expect(page.getByRole('button', { name: 'Report approvals', exact: true })).toHaveCount(
      roleCase.inbox ? 1 : 0
    );

    await (await sidebar(page)).getByRole('link', { name: roleCase.feature, exact: true }).click();
    const content = page.getByRole('main');
    await expect(
      content.getByRole('heading', { name: roleCase.heading, exact: true })
    ).toBeVisible();
    const action = content.getByRole('button', { name: roleCase.action, exact: true });
    if (roleCase.canAct) await expect(action).toBeVisible();
    else await expect(action).toHaveCount(0);

    if (roleCase.denied) {
      const denied = await request.get(roleCase.denied.api, {
        headers: { Authorization: `Bearer ${token}` }
      });
      expect(denied.status()).toBe(403);
      await page.goto(roleCase.denied.route);
      await expect(page).toHaveURL(roleCase.denied.landing ?? '/dashboard');
    }

    await page.goto('/delivery');
    if (roleCase.links.some((label) => label === 'Launch readiness')) {
      await expect(
        page.getByRole('heading', { name: 'Launch readiness', exact: true, level: 2 })
      ).toBeVisible();
    } else {
      await expect(page).toHaveURL('/dashboard');
    }
  });
}
