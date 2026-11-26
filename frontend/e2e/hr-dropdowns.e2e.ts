import { execFileSync } from 'node:child_process';
import { randomBytes } from 'node:crypto';
import { env } from 'node:process';
import { fileURLToPath } from 'node:url';

import { expect, test, type APIRequestContext, type Page } from '@playwright/test';

const BACKEND_DIR = fileURLToPath(new URL('../../backend/', import.meta.url));
const PYTHON_BIN = env.BROWSER_TEST_PYTHON ?? 'python';

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

function uniqueSuffix(): string {
  return randomBytes(4).toString('hex').toUpperCase();
}

function seedAccount(role: string): SeededAccount {
  return JSON.parse(
    execFileSync(PYTHON_BIN, ['-m', 'tests.browser_fixtures', 'seed', '--role', role], {
      cwd: BACKEND_DIR,
      encoding: 'utf8'
    })
  ) as SeededAccount;
}

async function signIn(page: Page, account: Pick<SeededAccount, 'email' | 'password'>): Promise<LoginResult> {
  await page.goto('/login');
  await page.getByLabel('Email', { exact: true }).fill(account.email);
  await page.getByLabel('Password', { exact: true }).fill(account.password);
  await page.getByRole('button', { name: 'Continue' }).click();
  const code = (await page.getByText(/^Development code:/).innerText()).match(/\d{6}/)?.[0];
  if (!code) throw new Error('The isolated test API did not expose its verification code.');

  const verified = page.waitForResponse(
    (response) =>
      new URL(response.url()).pathname === '/api/v1/auth/verify-otp' &&
      response.request().method() === 'POST'
  );
  await page.getByLabel('Verification code').fill(code);
  await page.getByRole('button', { name: 'Verify and sign in' }).click();
  const response = await verified;
  expect(response.status()).toBe(200);
  const body = (await response.json()) as { access_token: string; user: { id: string } };
  await expect(page).not.toHaveURL(/\/login$/);
  return { accessToken: body.access_token, userId: body.user.id };
}

async function createEmployee(
  request: APIRequestContext,
  accessToken: string,
  values: {
    code: string;
    email?: string;
    departmentId?: string;
    positionId?: string;
    employmentStatus?: 'draft' | 'active';
  }
): Promise<{ id: string }> {
  const response = await request.post('/api/v1/hr/employees', {
    headers: { Authorization: `Bearer ${accessToken}` },
    data: {
      employee_code: values.code,
      first_name: 'Synthetic',
      last_name: 'Dropdown',
      work_email: values.email,
      employment_status: values.employmentStatus ?? 'draft',
      department_id: values.departmentId,
      position_id: values.positionId
    }
  });
  expect(response.status()).toBe(201);
  return (await response.json()) as { id: string };
}

function seedLegacyLeaveType(name: string): { id: string; code: string } {
  const seeded = execFileSync(
    PYTHON_BIN,
    [
      '-c',
      `
from tests.browser_fixtures import configure
configure()
import asyncio
import json
from uuid import uuid4
from app.database import AsyncSessionLocal, engine
from app.models.hr import HrLeaveType

async def seed():
    row = HrLeaveType(
        code=f"LEGACY-{uuid4().hex[:12]}",
        name=${JSON.stringify(name)},
        is_paid=True,
        is_active=True,
        policy_required=False,
    )
    async with AsyncSessionLocal() as session:
        session.add(row)
        await session.flush()
        result = {"id": str(row.id), "code": row.code}
        await session.commit()
    await engine.dispose()
    print(json.dumps(result))

asyncio.run(seed())
`
    ],
    { cwd: BACKEND_DIR, encoding: 'utf8' }
  );
  return JSON.parse(seeded) as { id: string; code: string };
}

function seedDirectReportLeave(
  supervisorEmail: string,
  workerEmail: string
): { id: string; employeeName: string; leaveDate: string; supervisorUserId: string } {
  const seeded = execFileSync(
    PYTHON_BIN,
    [
      '-c',
      `
from tests.browser_fixtures import configure
configure()
import asyncio
import json
from datetime import timedelta
from decimal import Decimal
from sqlalchemy import select
from app.database import AsyncSessionLocal, engine
from app.models.hr import HrEmployee, HrEmployeePrivate, HrLeaveRequest, HrLeaveType
from app.models.user import User
from app.utils.time import business_today
from uuid import uuid4

async def seed():
    async with AsyncSessionLocal() as session:
        supervisor = await session.scalar(select(User).where(User.email == ${JSON.stringify(supervisorEmail)}))
        worker = await session.scalar(select(User).where(User.email == ${JSON.stringify(workerEmail)}))
        if supervisor is None or worker is None:
            raise RuntimeError("Browser leave accounts were not seeded.")
        supervisor_employee = HrEmployee(
            user_id=supervisor.id,
            employee_code=f"LEAVE-MGR-{uuid4().hex[:10]}",
            first_name="Synthetic",
            last_name="Supervisor",
            full_name="Synthetic Leave Supervisor",
            work_email=supervisor.email,
            employment_status="active",
            join_date=business_today() - timedelta(days=400),
        )
        session.add(supervisor_employee)
        await session.flush()
        today = business_today()
        birthday = today + timedelta(days=3)
        anniversary = today + timedelta(days=6)
        try:
            date_of_birth = birthday.replace(year=1988)
        except ValueError:
            date_of_birth = birthday.replace(year=1988, day=28)
        worker_employee = HrEmployee(
            user_id=worker.id,
            employee_code=f"LEAVE-WRK-{uuid4().hex[:10]}",
            first_name="Browser",
            last_name=f"Leave Worker {uuid4().hex[:6]}",
            full_name=f"Browser Leave Worker {uuid4().hex[:6]}",
            work_email=worker.email,
            employment_status="active",
            join_date=anniversary.replace(year=anniversary.year - 3),
            manager_employee_id=supervisor_employee.id,
        )
        session.add(worker_employee)
        await session.flush()
        session.add(
            HrEmployeePrivate(employee_id=worker_employee.id, date_of_birth=date_of_birth)
        )
        leave_type = HrLeaveType(
            code=f"LEGACY-{uuid4().hex[:12]}",
            name="Synthetic configured leave",
            is_paid=True,
            is_active=True,
            policy_required=False,
        )
        session.add(leave_type)
        await session.flush()
        leave_date = business_today() + timedelta(days=3)
        request = HrLeaveRequest(
            employee_id=worker_employee.id,
            leave_type_id=leave_type.id,
            start_date=leave_date,
            end_date=leave_date,
            days_requested=Decimal("1.00"),
            scheduled_work_dates=[leave_date],
            reason="Synthetic browser routing fixture",
            status="submitted",
            requested_by_id=worker.id,
            approval_route="supervisor",
            assigned_supervisor_user_id=supervisor.id,
        )
        session.add(request)
        await session.flush()
        result = {
            "id": str(request.id),
            "employeeName": worker_employee.full_name,
            "leaveDate": leave_date.isoformat(),
            "supervisorUserId": str(supervisor.id),
        }
        await session.commit()
    await engine.dispose()
    print(json.dumps(result))

asyncio.run(seed())
`
    ],
    { cwd: BACKEND_DIR, encoding: 'utf8' }
  );
  return JSON.parse(seeded) as {
    id: string;
    employeeName: string;
    leaveDate: string;
    supervisorUserId: string;
  };
}

async function linkEmployee(
  browser: import('@playwright/test').Browser,
  request: APIRequestContext,
  employeeId: string,
  userId: string
): Promise<void> {
  const director = seedAccount('managing_director');
  const directorPage = await browser.newPage();
  try {
    const login = await signIn(directorPage, director);
    const response = await request.post(`/api/v1/hr/employees/${employeeId}/link-account`, {
      headers: { Authorization: `Bearer ${login.accessToken}` },
      data: { user_id: userId }
    });
    expect(response.status()).toBe(200);
  } finally {
    await directorPage.close();
  }
}

test('HR roster options load before search and keep selections usable on mobile', async ({ page, request }) => {
  const account = seedAccount('hr_manager');
  const login = await signIn(page, account);
  const suffix = uniqueSuffix();
  const code = `DROPDOWN-${suffix}`;
  const employee = await createEmployee(request, login.accessToken, { code });

  await page.getByRole('link', { name: 'HR & Workforce', exact: true }).click();
  await page.getByRole('button', { name: 'Attendance', exact: true }).click();

  const employeeSelect = page.getByLabel('Roster employee', { exact: true });
  const projectSelect = page.getByLabel('Roster project', { exact: true });
  await expect(employeeSelect.locator('option', { hasText: code })).toHaveCount(1);
  await expect.poll(() => projectSelect.locator('option').count()).toBeGreaterThan(1);

  await page.getByRole('searchbox', { name: 'Find roster employee' }).fill(code);
  await expect(employeeSelect.locator('option', { hasText: code })).toHaveCount(1);
  await employeeSelect.selectOption(employee.id);
  const projectSearch = page.getByLabel('Find roster project');
  await projectSearch.fill(account.projectCode);
  await expect(projectSelect.locator('option', { hasText: account.projectCode })).toHaveCount(1);
  await expect(projectSelect).toBeEnabled();
  await projectSelect.click();
  await projectSelect.press('b');
  await projectSelect.press('Enter');
  await expect(projectSelect).toHaveValue(account.projectId);

  await page.getByRole('searchbox', { name: 'Find roster employee' }).fill(`missing-${suffix}`);
  await expect(page.getByText('No matching employees.')).toBeVisible();
  await expect(employeeSelect).toHaveValue(employee.id);
  await expect(employeeSelect.locator('option', { hasText: code })).toHaveCount(1);

  await page.setViewportSize({ width: 390, height: 844 });
  await expect(employeeSelect).toBeVisible();
  await expect(projectSelect).toBeVisible();
  const bounds = await projectSelect.boundingBox();
  expect(bounds).not.toBeNull();
  expect(bounds!.x).toBeGreaterThanOrEqual(0);
  expect(bounds!.x + bounds!.width).toBeLessThanOrEqual(391);
});

test('one workspace option failure does not block other options and retry restores selection', async ({
  page,
  request
}) => {
  const account = seedAccount('hr_manager');
  const login = await signIn(page, account);
  const suffix = uniqueSuffix();
  const firstDepartment = await request.post('/api/v1/hr/departments', {
    headers: { Authorization: `Bearer ${login.accessToken}` },
    data: { code: `D-${suffix}-1`, name: `Dropdown Department ${suffix}` }
  });
  expect(firstDepartment.status()).toBe(201);
  const departmentOne = (await firstDepartment.json()) as { id: string };
  const secondDepartment = await request.post('/api/v1/hr/departments', {
    headers: { Authorization: `Bearer ${login.accessToken}` },
    data: { code: `D-${suffix}-2`, name: `Dropdown Other ${suffix}` }
  });
  expect(secondDepartment.status()).toBe(201);
  const departmentTwo = (await secondDepartment.json()) as { id: string };
  const positionResponse = await request.post('/api/v1/hr/positions', {
    headers: { Authorization: `Bearer ${login.accessToken}` },
    data: {
      code: `P-${suffix}`,
      title: `Z${suffix} Dropdown Position`,
      department_id: departmentOne.id,
      employment_category: 'permanent',
      headcount_limit: 10,
      approved_count: 10
    }
  });
  expect(positionResponse.status()).toBe(201);
  const position = (await positionResponse.json()) as { id: string };
  const employee = await createEmployee(request, login.accessToken, { code: `EMP-${suffix}` });

  const initialPositions = page.waitForResponse(
    (response) =>
      new URL(response.url()).pathname.endsWith('/api/v1/hr/positions') &&
      response.request().method() === 'GET' &&
      response.status() === 200
  );
  await page.getByRole('link', { name: 'HR & Workforce', exact: true }).click();
  await initialPositions;
  await page.getByRole('button', { name: 'Directory & Org' }).click();
  await expect(page.getByText(/Employee Directory/)).toBeVisible();
  await page.getByLabel('Search employees').fill(`EMP-${suffix}`);
  const employeeRow = page.getByRole('row').filter({ hasText: `EMP-${suffix}` });
  await expect(employeeRow).toBeVisible();
  await employeeRow.getByRole('button', { name: 'Inspect' }).click();

  const employeeEditor = page.locator('form').filter({
    has: page.getByRole('button', { name: 'Save employee' })
  });
  const departmentSelect = employeeEditor.locator('select[name="department"]');
  const positionSelect = employeeEditor.locator('select[name="position"]');

  let failedOnce = false;
  await page.route('**/api/v1/hr/positions**', async (route) => {
    if (!failedOnce && route.request().method() === 'GET') {
      failedOnce = true;
      await route.fulfill({
        status: 422,
        contentType: 'application/json',
        body: JSON.stringify({ detail: 'Synthetic position lookup failure' })
      });
      return;
    }
    await route.continue();
  });
  await page.getByRole('button', { name: 'Refresh', exact: true }).click();
  await expect.poll(() => failedOnce).toBe(true);
  await expect(departmentSelect.locator('option', { hasText: `Dropdown Department ${suffix}` })).toHaveCount(1);
  await expect(page.getByText('Position options failed to load.')).toBeVisible();
  await departmentSelect.selectOption(departmentTwo.id);

  const positionError = page.locator('[role="alert"]').filter({ hasText: 'Position options failed to load.' });
  await positionError.getByRole('button', { name: 'Retry', exact: true }).click();
  await expect(positionSelect.locator(`option[value="${position.id}"]`)).toHaveCount(1);
  await expect(positionSelect).toBeEnabled();
  await positionSelect.focus();
  await positionSelect.pressSequentially(`Z${suffix}`);
  await positionSelect.press('Enter');
  await expect(positionSelect).toHaveValue(position.id);

  await page.setViewportSize({ width: 390, height: 844 });
  await expect(departmentSelect).toBeVisible();
  await expect(positionSelect).toBeVisible();
  const saveResponse = page.waitForResponse((response) => {
    const url = new URL(response.url());
    return (
      url.pathname === `/api/v1/hr/employees/${employee.id}` &&
      response.request().method() === 'PATCH'
    );
  });
  await page.getByRole('button', { name: 'Save employee' }).click();
  expect((await saveResponse).status()).toBe(200);
  await expect(departmentSelect).toHaveValue(departmentTwo.id);
  await expect(positionSelect).toHaveValue(position.id);

  const detail = await request.get(`/api/v1/hr/employees/${employee.id}`, {
    headers: { Authorization: `Bearer ${login.accessToken}` }
  });
  expect(detail.status()).toBe(200);
  await expect(detail.json()).resolves.toMatchObject({
    department_id: departmentTwo.id,
    position_id: position.id
  });
});

test('project assignment picker loads its first page for an authorized linked employee', async ({
  page,
  browser,
  request
}) => {
  const hrAccount = seedAccount('hr_manager');
  const hrLogin = await signIn(page, hrAccount);
  const supervisorAccount = seedAccount('site_supervisor');
  const supervisorPage = await browser.newPage();
  let supervisorLogin: LoginResult;
  try {
    supervisorLogin = await signIn(supervisorPage, supervisorAccount);
  } finally {
    await supervisorPage.close();
  }

  const suffix = uniqueSuffix();
  const employee = await createEmployee(request, hrLogin.accessToken, {
    code: `LINK-${suffix}`,
    email: supervisorAccount.email
  });
  await linkEmployee(browser, request, employee.id, supervisorLogin.userId);

  await page.getByRole('link', { name: 'HR & Workforce', exact: true }).click();
  await page.getByRole('button', { name: 'Directory & Org' }).click();
  await page.getByLabel('Search employees').fill(`LINK-${suffix}`);
  const employeeRow = page.getByRole('row').filter({ hasText: `LINK-${suffix}` });
  await expect(employeeRow).toBeVisible();
  await employeeRow.getByRole('button', { name: 'Inspect' }).click();

  const projectSelect = page.getByLabel('Assignment project');
  await expect.poll(() => projectSelect.locator('option').count()).toBeGreaterThan(1);
  await page.getByLabel('Find project by name or code').fill(supervisorAccount.projectCode);
  await page.getByRole('button', { name: 'Find project', exact: true }).click();
  const targetOption = projectSelect.locator('option', { hasText: supervisorAccount.projectCode });
  await expect(targetOption).toHaveCount(1);
  const targetProjectId = await targetOption.getAttribute('value');
  expect(targetProjectId).not.toBeNull();
  await projectSelect.selectOption(targetProjectId!);
  const selected = await projectSelect.inputValue();
  expect(selected).not.toBe('');

  await page.getByLabel('Find project by name or code').fill(`missing-${suffix}`);
  await page.getByRole('button', { name: 'Find project', exact: true }).click();
  await expect(page.getByText('No editable projects are available for this search.')).toBeVisible();
  await expect(projectSelect).toHaveValue(selected);

  await page.setViewportSize({ width: 390, height: 844 });
  await expect(projectSelect).toBeVisible();
});

test('My HR leave options load when the separate attendance request fails', async ({
  page,
  browser,
  request
}) => {
  const hrAccount = seedAccount('hr_manager');
  const hrLogin = await signIn(page, hrAccount);
  const supervisorAccount = seedAccount('site_supervisor');
  const supervisorPage = await browser.newPage();
  let supervisorLogin: LoginResult;
  try {
    supervisorLogin = await signIn(supervisorPage, supervisorAccount);
  } finally {
    await supervisorPage.close();
  }

  const suffix = uniqueSuffix();
  const employee = await createEmployee(request, hrLogin.accessToken, {
    code: `SELF-${suffix}`,
    email: supervisorAccount.email,
    employmentStatus: 'active'
  });
  await linkEmployee(browser, request, employee.id, supervisorLogin.userId);

  const leaveTypeResponse = await request.post('/api/v1/hr/leave/types', {
    headers: { Authorization: `Bearer ${hrLogin.accessToken}` },
    data: {
      code: `LT-${suffix}`,
      name: `Unconfigured Leave ${suffix}`,
      is_paid: true,
      requires_attachment: false,
      allow_half_day: true
    }
  });
  expect(leaveTypeResponse.status()).toBe(201);
  expect((await leaveTypeResponse.json()).is_active).toBe(false);
  const leaveType = seedLegacyLeaveType(`Dropdown Leave ${suffix}`);

  const employeePage = await browser.newPage();
  try {
    await signIn(employeePage, supervisorAccount);
    let attendanceFailed = true;
    await employeePage.route('**/api/v1/hr/me/attendance', async (route) => {
      if (attendanceFailed) {
        await route.fulfill({
          status: 422,
          contentType: 'application/json',
          body: JSON.stringify({ detail: 'Synthetic attendance service failure' })
        });
      } else {
        await route.continue();
      }
    });
    await employeePage.route('**/api/v1/hr/me/leave-types', async (route) => {
      await new Promise((resolve) => setTimeout(resolve, 700));
      await route.continue();
    });

    await employeePage.getByRole('link', { name: 'My HR', exact: true }).click();
    const leaveSelect = employeePage.getByLabel('Leave type');
    await expect(leaveSelect.locator('option').first()).toHaveText('Loading leave types…');
    await expect(leaveSelect.locator('option', { hasText: `Dropdown Leave ${suffix}` })).toHaveCount(1);
    await expect(
      employeePage.locator('[role="alert"]').filter({ hasText: 'Attendance' })
    ).toBeVisible();
    await leaveSelect.selectOption(leaveType.id);
    await expect(leaveSelect).toHaveValue(leaveType.id);

    attendanceFailed = false;
    await employeePage.getByRole('button', { name: 'Retry Attendance', exact: true }).click();
    await expect(
      employeePage.locator('[role="alert"]').filter({ hasText: 'Attendance' })
    ).toHaveCount(0);
    await expect(employeePage.getByRole('heading', { name: 'My HR Profile' })).toBeVisible();
    await expect(leaveSelect).toHaveValue(leaveType.id);

    await employeePage.setViewportSize({ width: 390, height: 844 });
    await expect(leaveSelect).toBeVisible();
    const bounds = await leaveSelect.boundingBox();
    expect(bounds).not.toBeNull();
    expect(bounds!.x + bounds!.width).toBeLessThanOrEqual(391);
  } finally {
    await employeePage.close();
  }
});

test('a direct supervisor makes the final leave decision in My HR while HR retains visibility', async ({
  page,
  browser,
  request
}) => {
  const hrAccount = seedAccount('hr_manager');
  const supervisorAccount = seedAccount('group_project_manager');
  const workerAccount = seedAccount('quantity_surveyor');
  const seeded = seedDirectReportLeave(supervisorAccount.email, workerAccount.email);
  const hrLogin = await signIn(page, hrAccount);
  const supervisorPage = await browser.newPage();
  try {
    await signIn(supervisorPage, supervisorAccount);
    await supervisorPage.goto('/dashboard');
    const birthdays = supervisorPage.getByRole('region', { name: 'Upcoming birthdays — 7 days' });
    const anniversaries = supervisorPage.getByRole('region', {
      name: 'Work anniversaries — 30 days'
    });
    await expect(birthdays.getByText(seeded.employeeName, { exact: true })).toBeVisible();
    expect(await birthdays.innerText()).not.toContain('1988');
    await expect(anniversaries.getByText(seeded.employeeName, { exact: true })).toBeVisible();
    await expect(anniversaries).toContainText('3 years');

    const hrHeaders = { Authorization: `Bearer ${hrLogin.accessToken}` };
    const visibleToHr = await request.get('/api/v1/hr/leave/requests', {
      headers: hrHeaders,
      params: { req_status: 'submitted' }
    });
    expect(visibleToHr.status()).toBe(200);
    const visibleItems = (await visibleToHr.json()).items as Array<{
      id: string;
      approval_route: string | null;
      assigned_supervisor_user_id: string | null;
    }>;
    expect(visibleItems).toContainEqual(expect.objectContaining({
      id: seeded.id,
      approval_route: 'supervisor',
      assigned_supervisor_user_id: seeded.supervisorUserId
    }));

    await supervisorPage.goto('/me/hr');
    await expect(
      supervisorPage.getByRole('heading', { name: 'Direct-report leave approvals', exact: true })
    ).toBeVisible();
    const review = supervisorPage.getByRole('listitem').filter({ hasText: seeded.employeeName });
    await expect(review).toContainText(seeded.leaveDate);
    await review
      .getByRole('textbox', { name: 'Decision note (required for rejection)' })
      .fill('Synthetic browser rejection reason');
    await review.getByRole('button', { name: 'Reject', exact: true }).click();
    await expect(supervisorPage.getByRole('status')).toContainText('Leave request rejected.');
    await expect(review).toHaveCount(0);

    const rejectedForHr = await request.get('/api/v1/hr/leave/requests', {
      headers: hrHeaders,
      params: { req_status: 'rejected' }
    });
    expect(rejectedForHr.status()).toBe(200);
    expect((await rejectedForHr.json()).items).toContainEqual(
      expect.objectContaining({ id: seeded.id, status: 'rejected' })
    );
  } finally {
    await supervisorPage.close();
  }
});

