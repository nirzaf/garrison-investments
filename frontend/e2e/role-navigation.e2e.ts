import { execFileSync } from 'node:child_process';
import { env } from 'node:process';
import { fileURLToPath } from 'node:url';

import { expect, test, type Page } from '@playwright/test';

const backendDirectory = fileURLToPath(new URL('../../backend/', import.meta.url));
const commonLinks = {
  Dashboard: '/dashboard',
  Approvals: '/approvals',
  'Roles & Permissions': '/roles',
  'User Manual': '/manual'
};
const guardedLinks = {
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
    role: 'admin',
    label: 'Admin',
    links: [...companyLinks, 'Security', 'Audit', 'Imports'],
    inbox: true,
    feature: 'Users',
    heading: 'Users',
    action: 'Create user',
    canAct: true
  },
  {
    role: 'general_manager',
    label: 'General Manager',
    links: companyLinks,
    inbox: true,
    feature: 'Users',
    heading: 'Users',
    action: 'Create user',
    canAct: false,
    denied: { route: '/admin/audit-logs', api: '/api/v1/audit-logs' }
  },
  {
    role: 'operation_manager',
    label: 'Operation Manager',
    links: companyLinks,
    inbox: true,
    feature: 'Projects',
    heading: 'Projects',
    action: 'New project',
    canAct: true,
    denied: { route: '/admin/imports', api: '/api/v1/imports/batches' }
  },
  {
    role: 'project_manager',
    label: 'Project Manager',
    links: [
      'Projects',
      'Reports',
      'Supervisor updates',
      'Materials',
      'Finance',
      'Documents',
      'Photos'
    ],
    inbox: true,
    feature: 'Projects',
    heading: 'Projects',
    action: 'New project',
    canAct: false,
    denied: { route: '/suppliers', api: '/api/v1/suppliers' }
  },
  {
    role: 'civil_engineer',
    label: 'Civil Engineer',
    links: ['Projects', 'Reports', 'Supervisor updates', 'Materials', 'Documents', 'Photos'],
    inbox: false,
    feature: 'Reports',
    heading: 'Engineer Daily Report',
    action: 'Submit report',
    canAct: true,
    denied: { route: '/finance', api: '/api/v1/finance/invoices' }
  },
  {
    role: 'civil_supervisor',
    label: 'Civil Supervisor',
    links: ['Projects', 'Reports', 'Documents', 'Photos'],
    inbox: false,
    feature: 'Reports',
    heading: 'Supervisor Site Update',
    action: 'Submit update',
    canAct: true,
    denied: {
      route: '/reports/daily',
      api: '/api/v1/reports',
      landing: '/reports/supervisor-update'
    }
  },
  {
    role: 'store_keeper',
    label: 'Store Keeper',
    links: ['Materials', 'Suppliers'],
    inbox: false,
    feature: 'Materials',
    heading: 'Inventory And Stores',
    action: 'Add item',
    canAct: true,
    denied: { route: '/projects', api: '/api/v1/projects' }
  },
  {
    role: 'accounts',
    label: 'Accounts',
    links: ['Projects', 'Reports', 'Supervisor updates', 'Finance', 'Documents', 'Photos'],
    inbox: false,
    feature: 'Finance',
    heading: 'Invoices and payments',
    action: 'New invoice',
    canAct: true,
    denied: { route: '/materials', api: '/api/v1/inventory/items' }
  }
];

test.use({ trace: 'off' });

async function signIn(page: Page, role: string) {
  const account = JSON.parse(
    execFileSync(
      env.BROWSER_TEST_PYTHON ?? 'python',
      ['-m', 'tests.browser_fixtures', 'seed', '--role', role],
      { cwd: backendDirectory, encoding: 'utf8' }
    )
  ) as { email: string; password: string };

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
    if (roleCase.role === 'store_keeper') await page.setViewportSize({ width: 390, height: 844 });
    const token = await signIn(page, roleCase.role);
    await expect(page).toHaveURL('/dashboard');

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
        label === 'Reports' && roleCase.role === 'civil_supervisor'
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
  });
}
