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
  const inactiveLeaveType = (await leaveTypeResponse.json()) as { id: string; is_active: boolean };
  expect(inactiveLeaveType.is_active).toBe(false);
  const leaveType = seedLegacyLeaveType(`Dropdown Leave ${suffix}`);

  const employeePage = await browser.newPage();
  try {
    const employeeLogin = await signIn(employeePage, supervisorAccount);
    const staffHeaders = { Authorization: `Bearer ${employeeLogin.accessToken}` };
    const adminTypes = await request.get('/api/v1/hr/leave/types', {
      headers: { Authorization: `Bearer ${hrLogin.accessToken}` }
    });
    expect(adminTypes.status()).toBe(200);
    expect((await adminTypes.json()).items).toContainEqual(
      expect.objectContaining({ id: inactiveLeaveType.id, is_active: false })
    );
    const selfTypes = await request.get('/api/v1/hr/me/leave-types', { headers: staffHeaders });
    expect(selfTypes.status()).toBe(200);
    const selfTypeItems = (await selfTypes.json()).items;
    expect(selfTypeItems).not.toContainEqual(
      expect.objectContaining({ id: inactiveLeaveType.id })
    );
    expect(selfTypeItems).toContainEqual(
      expect.objectContaining({
        id: leaveType.id,
        availability_state: 'requestable_for_current_business_date'
      })
    );
    const selectedDateTypes = await request.get('/api/v1/hr/me/leave-types', {
      headers: staffHeaders,
      params: { start_date: '2027-01-05', end_date: '2027-01-06' }
    });
    expect(selectedDateTypes.status()).toBe(200);
    expect((await selectedDateTypes.json()).items).toContainEqual(
      expect.objectContaining({
        id: leaveType.id,
        availability_state: 'requestable_for_selected_dates'
      })
    );
    const inactiveQuote = await request.get('/api/v1/hr/me/leave-units', {
      headers: staffHeaders,
      params: {
        leave_type_id: inactiveLeaveType.id,
        start_date: '2027-01-05',
        end_date: '2027-01-05'
      }
    });
    expect(inactiveQuote.status()).toBe(404);
    const inactiveSubmission = await request.post('/api/v1/hr/me/leave-requests', {
      headers: staffHeaders,
      data: {
        leave_type_id: inactiveLeaveType.id,
        start_date: '2027-01-05',
        end_date: '2027-01-05',
        submit_immediately: true
      }
    });
    expect(inactiveSubmission.status()).toBe(404);

    const historicalLeaveRequest = {
      id: `00000000-0000-4000-8000-${suffix.padStart(12, '0')}`,
      employee_id: employee.id,
      leave_type_id: inactiveLeaveType.id,
      leave_type_name: `Unconfigured Leave ${suffix}`,
      start_date: '2027-01-04',
      end_date: '2027-01-04',
      days_requested: '1.00',
      is_half_day: false,
      half_day_period: null,
      reason: 'Synthetic historical correction reason',
      attachment_document_id: null,
      status: 'rejected',
      requested_by_id: employeeLogin.userId,
      decided_by_id: null,
      decided_at: null,
      decision_notes: 'Please correct this request.',
      created_at: '2026-11-27T00:00:00Z',
      updated_at: '2026-11-27T00:00:00Z',
      record_revision: 1,
      requires_manager_recommendation: false,
      manager_recommendation: null,
      manager_recommended_at: null,
      approval_route: null,
      assigned_supervisor_user_id: null,
      fallback_reason_code: null,
      fallback_until: null,
      setup_error_code: null,
      allowed_actions: [],
      route_status: 'final'
    };
    const dateScopedLeaveType = {
      id: `11111111-1111-4111-8111-${suffix.padStart(12, '0')}`,
      code: `WINDOW-${suffix}`,
      name: `Date-window leave ${suffix}`,
      is_paid: true,
      requires_attachment: false,
      allow_half_day: true,
      availability_state: 'requestable_for_selected_dates'
    };
    const dateScopedLeaveRequest = {
      ...historicalLeaveRequest,
      id: `33333333-3333-4333-8333-${suffix.padStart(12, '0')}`,
      leave_type_id: dateScopedLeaveType.id,
      leave_type_name: dateScopedLeaveType.name,
      start_date: '2027-01-05',
      end_date: '2027-01-05',
      status: 'rejected',
      reason: 'Synthetic date-scoped leave correction'
    };
    let attendanceFailed = true;
    let noTypesForSelectedDates = false;
    let resubmitAttempts = 0;
    let createAttempts = 0;
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
    await employeePage.route('**/api/v1/hr/me/leave-requests', async (route) => {
      if (route.request().method() === 'GET') {
        await route.fulfill({
          contentType: 'application/json',
          json: { items: [dateScopedLeaveRequest, historicalLeaveRequest], total: 2 }
        });
      } else if (route.request().method() === 'POST') {
        createAttempts += 1;
        await route.fulfill({ status: 500, body: 'Unexpected new leave request' });
      } else {
        await route.continue();
      }
    });
    await employeePage.route('**/api/v1/hr/me/leave-units**', async (route) => {
      await route.fulfill({
        contentType: 'application/json',
        json: { days_requested: '1.00' }
      });
    });
    await employeePage.route('**/api/v1/hr/me/leave-requests/*/submission', async (route) => {
      resubmitAttempts += 1;
      if (resubmitAttempts === 1) {
        await route.fulfill({
          status: 409,
          contentType: 'application/json',
          json: { error_code: 'LEAVE_OVERLAP', detail: 'Synthetic overlap conflict' }
        });
        return;
      }
      await route.fulfill({
        status: 200,
        contentType: 'application/json',
        json: { ...dateScopedLeaveRequest, status: 'submitted', record_revision: 2 }
      });
    });
    await employeePage.route('**/api/v1/hr/me/leave-types**', async (route) => {
      const params = new URL(route.request().url()).searchParams;
      if (noTypesForSelectedDates && (params.has('start_date') || params.has('end_date'))) {
        await route.fulfill({
          contentType: 'application/json',
          json: { items: [], total: 0 }
        });
        return;
      }
      if (params.get('start_date') === dateScopedLeaveRequest.start_date) {
        await new Promise((resolve) => setTimeout(resolve, 700));
        await route.fulfill({ contentType: 'application/json', json: { items: [dateScopedLeaveType], total: 1 } });
        return;
      }
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

    await expect(
      employeePage.getByText(new RegExp(`Unconfigured Leave ${suffix}: 2027-01-04`))
    ).toBeVisible();
    await employeePage.getByRole('button', { name: 'Edit leave request' }).nth(0).click();
    await expect(leaveSelect).toHaveValue(dateScopedLeaveType.id);
    await expect(leaveSelect).toBeEnabled();
    await expect(
      employeePage.getByText(/This leave type is unavailable for the selected dates/)
    ).toHaveCount(0);
    await expect(employeePage.getByLabel('Leave starts')).toHaveValue('2027-01-05');
    await expect(employeePage.getByRole('button', { name: 'Resubmit leave request' })).toBeEnabled();
    await employeePage.getByRole('button', { name: 'Resubmit leave request' }).click();
    await expect(employeePage.getByRole('button', { name: 'Resubmit leave request' })).toBeVisible();
    await expect.poll(() => resubmitAttempts).toBe(1);
    expect(createAttempts).toBe(0);
    await employeePage.getByRole('button', { name: 'Resubmit leave request' }).click();
    await expect(employeePage.getByText('Leave request resubmitted.')).toBeVisible();
    expect(resubmitAttempts).toBe(2);
    expect(createAttempts).toBe(0);

    await expect(leaveSelect.locator('option', { hasText: `Dropdown Leave ${suffix}` })).toHaveCount(1);
    await employeePage.getByRole('button', { name: 'Edit leave request' }).click();
    await expect(leaveSelect).toHaveValue('');
    await expect(
      leaveSelect.getByRole('option', {
        name: new RegExp(`Unconfigured Leave ${suffix}.*unavailable for`)
      })
    ).toBeDisabled();
    await expect(employeePage.getByLabel('Leave starts')).toHaveValue('2027-01-04');
    await expect(employeePage.getByPlaceholder('Reason (optional)')).toHaveValue(
      'Synthetic historical correction reason'
    );
    await expect(employeePage.getByRole('button', { name: 'Resubmit leave request' })).toBeDisabled();
    await employeePage.getByRole('button', { name: 'Cancel editing' }).click();
    await expect(leaveSelect).toBeEnabled();
    await leaveSelect.selectOption(leaveType.id);
    await employeePage.getByLabel('Leave ends').fill('2027-01-06');
    await employeePage.getByLabel('Leave starts').fill('2027-01-05');
    await expect(employeePage.getByText('Scheduled leave days: 1.00')).toBeVisible();

    noTypesForSelectedDates = true;
    await employeePage.getByLabel('Leave starts').fill('2027-01-07');
    await expect(leaveSelect).toHaveValue('');
    await expect(
      employeePage.getByText(
        'No leave types are available for these dates. Check HR setup or select another period.'
      )
    ).toBeVisible();
    await expect(employeePage.getByText('Scheduled leave days: 1.00')).toHaveCount(0);
    await expect(employeePage.getByRole('button', { name: 'Submit leave request' })).toBeDisabled();
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
    await expect(
      supervisorPage.getByText('Leave request rejected.', { exact: true })
    ).toBeVisible();
    await expect(review).toHaveCount(0);

    const rejectedForHr = await request.get('/api/v1/hr/leave/requests', {
      headers: hrHeaders,
      params: { req_status: 'rejected' }
    });
    expect(rejectedForHr.status()).toBe(200);
    const rejectedItems = (await rejectedForHr.json()).items as Array<{
      id: string;
      status: string;
      decided_by_id: string | null;
      decided_by_name: string | null;
      decided_at: string | null;
    }>;
    const rejectedForDisplay = rejectedItems.find((item) => item.id === seeded.id);
    expect(rejectedForDisplay).toMatchObject({
      status: 'rejected',
      decided_by_id: seeded.supervisorUserId
    });
    expect(rejectedForDisplay?.decided_by_name).toBeTruthy();
    expect(rejectedForDisplay?.decided_at).toBeTruthy();

    await page.goto('/hr');
    await page.getByRole('button', { name: 'Leave', exact: true }).click();
    const requestsSection = page.getByRole('heading', { name: /^Leave Requests/ }).locator('..');
    const requestRow = requestsSection
      .locator('div.flex.items-center.justify-between')
      .filter({ hasText: seeded.leaveDate })
      .first();
    await expect(requestRow).toContainText(`Final decision by ${rejectedForDisplay?.decided_by_name}`);
  } finally {
    await supervisorPage.close();
  }
});

test('HR restores a temporary leave fallback through the advertised reasoned action', async ({
  page,
  request
}) => {
  const hrAccount = seedAccount('hr_manager');
  const supervisorAccount = seedAccount('group_project_manager');
  const workerAccount = seedAccount('quantity_surveyor');
  const seeded = seedDirectReportLeave(supervisorAccount.email, workerAccount.email);
  const hrLogin = await signIn(page, hrAccount);
  const headers = { Authorization: `Bearer ${hrLogin.accessToken}` };

  const pending = await request.get('/api/v1/hr/leave/requests', {
    headers,
    params: { req_status: 'submitted' }
  });
  expect(pending.status()).toBe(200);
  const pendingItems = (await pending.json()).items as Array<{
    id: string;
    record_revision: number;
  }>;
  const current = pendingItems.find((item) => item.id === seeded.id);
  expect(current).toBeDefined();

  const fallback = await request.post(`/api/v1/hr/leave/requests/${seeded.id}/fallback`, {
    headers,
    data: {
      reason_code: 'manager_temporarily_unavailable',
      reason: 'Synthetic browser fixture temporary absence',
      expected_revision: current!.record_revision,
      until: seeded.leaveDate
    }
  });
  expect(fallback.status()).toBe(200);
  const fallbackBody = (await fallback.json()) as {
    allowed_actions: string[];
    record_revision: number;
  };
  expect(fallbackBody.allowed_actions).toContain('restore_supervisor');

  await page.goto('/hr');
  await page.getByRole('button', { name: 'Leave', exact: true }).click();
  const requestsSection = page.getByRole('heading', { name: /^Leave Requests/ }).locator('..');
  const requestRow = requestsSection
    .locator('div.flex.items-center.justify-between')
    .filter({ hasText: seeded.leaveDate })
    .first();
  await expect(requestRow).toContainText('Pending decision: HR fallback');
  await requestRow.getByRole('button', { name: 'Restore current supervisor' }).click();

  const dialog = page.getByRole('dialog', { name: 'Restore the current supervisor' });
  const reason = dialog.getByRole('textbox', { name: 'Restoration reason' });
  const restoreButton = dialog.getByRole('button', { name: 'Restore supervisor', exact: true });
  await expect(restoreButton).toBeDisabled();
  await reason.fill('Synthetic reviewed restoration reason');
  const routeRefresh = page.waitForResponse((response) =>
    new URL(response.url()).pathname === `/api/v1/hr/leave/requests/${seeded.id}/route-refresh` &&
    response.request().method() === 'POST'
  );
  await restoreButton.click();
  expect((await routeRefresh).status()).toBe(200);
  await expect(dialog).toHaveCount(0);

  const refreshed = await request.get('/api/v1/hr/leave/requests', {
    headers,
    params: { req_status: 'submitted' }
  });
  expect(refreshed.status()).toBe(200);
  expect((await refreshed.json()).items).toContainEqual(expect.objectContaining({
    id: seeded.id,
    approval_route: 'supervisor',
    assigned_supervisor_user_id: seeded.supervisorUserId,
    record_revision: fallbackBody.record_revision + 1
  }));
});

test('HR reviews private employee data-quality findings and opens the existing record', async ({
  page,
  request
}) => {
  const account = seedAccount('hr_manager');
  const login = await signIn(page, account);
  const code = `DQ-${uniqueSuffix()}`;
  await createEmployee(request, login.accessToken, { code });

  await page.goto('/hr');
  await page.getByRole('button', { name: 'Directory & Org', exact: true }).click();
  const heading = page.getByRole('heading', { name: 'Employee data quality review' });
  const panel = heading.locator('xpath=../../..');
  const issue = panel.locator('article').filter({ hasText: code });
  await expect(issue).toContainText('missing birth date');
  await expect(issue).toContainText('employment start unverified');
  expect(await issue.innerText()).not.toMatch(/\b\d{4}-\d{2}-\d{2}\b/);
  await issue.getByRole('button', { name: 'Inspect employee' }).click();
  const selected = page.getByRole('heading', { name: 'Selected Employee' }).locator('..');
  await expect(selected).toContainText(code);
});



function updateLm12Fixture(id: string, operation: 'advisory' | 'expire_fallback') {
  execFileSync(PYTHON_BIN, ['-c', `
from tests.browser_fixtures import configure
configure()
import asyncio
from datetime import timedelta
from uuid import UUID
from app.database import AsyncSessionLocal, engine
from app.models.hr import HrLeaveRequest
from app.utils.time import business_today

async def update():
    async with AsyncSessionLocal() as session:
        row = await session.get(HrLeaveRequest, UUID(${JSON.stringify(id)}))
        if row is None or row.reason != "Synthetic browser routing fixture":
            raise RuntimeError("LM-12 updates only its synthetic browser leave fixture.")
        if ${JSON.stringify(operation)} == "advisory":
            row.requires_manager_recommendation = True
            row.manager_recommendation = "support"
        else:
            row.fallback_until = business_today() - timedelta(days=1)
            row.record_revision += 1
        await session.commit()
    await engine.dispose()

asyncio.run(update())
`], { cwd: BACKEND_DIR, encoding: 'utf8' });
}

function watchLm12BrowserErrors(page: Page) {
  const failures: string[] = [];
  page.on('pageerror', (error) => failures.push(error.message));
  page.on('console', (message) => {
    if (message.type() === 'error' && !message.text().startsWith('Failed to load resource:')) {
      failures.push(message.text());
    }
  });
  page.on('response', (response) => {
    const url = new URL(response.url());
    if (url.pathname.startsWith('/api/') && response.status() >= 500) {
      failures.push(`${response.status()} ${url.pathname}`);
    }
  });
  page.on('requestfailed', (request) => {
    const failure = request.failure()?.errorText;
    if (new URL(request.url()).pathname.startsWith('/api/') && failure !== 'net::ERR_ABORTED') {
      failures.push(failure ?? 'Request failed');
    }
  });
  return () => expect(failures).toEqual([]);
}

test('LM-12 HR is read-only on supervisor leave and employee sees own final result after account switch', async ({
  page, browser
}) => {
  const checkErrors = watchLm12BrowserErrors(page);
  const hrAccount = seedAccount('hr_manager');
  const supervisorAccount = seedAccount('group_project_manager');
  const workerAccount = seedAccount('quantity_surveyor');
  const seeded = seedDirectReportLeave(supervisorAccount.email, workerAccount.email);
  updateLm12Fixture(seeded.id, 'advisory');
  await signIn(page, hrAccount);
  await page.goto('/hr');
  await page.getByRole('button', { name: 'Leave', exact: true }).click();
  const row = page.getByTestId(`leave-request-${seeded.id}`);
  await expect(row).toContainText('Pending decision: direct supervisor');
  await expect(row).toContainText('Current reviewer: Browser Test Group Project Manager');
  await expect(row.getByRole('button', { name: 'Approve', exact: true })).toHaveCount(0);
  await expect(row.getByRole('button', { name: 'Reject', exact: true })).toHaveCount(0);
  await expect(row).not.toContainText('Pending manager recommendation');
  const supervisorPage = await browser.newPage();
  const checkSupervisorErrors = watchLm12BrowserErrors(supervisorPage);
  try {
    await signIn(supervisorPage, supervisorAccount);
    await supervisorPage.goto('/me/hr');
    const review = supervisorPage.getByRole('listitem').filter({ hasText: seeded.employeeName });
    await expect(review).toContainText('Revision 1');
    await expect(review).not.toContainText('Synthetic configured leave');
    await expect(review).not.toContainText('Synthetic browser routing fixture');
    await expect(review.getByRole('button', { name: 'Reject', exact: true })).toBeDisabled();
    await review.getByLabel('Decision note (required for rejection)').fill('Synthetic LM-12 final rejection');
    await review.getByRole('button', { name: 'Reject', exact: true }).click();
    await expect(supervisorPage.getByRole('status')).toContainText('Leave request rejected.');
    await expect(review).toHaveCount(0);
    await page.reload();
    await page.getByRole('button', { name: 'Leave', exact: true }).click();
    await expect(row).toContainText('Final decision by Browser Test Group Project Manager');
    await expect(row).not.toContainText('Pending manager recommendation');
    await row.getByText('Historical manager advisory', { exact: true }).click();
    await expect(row).toContainText('support');
    await page.getByRole('button', { name: /^Browser Test Hr Manager/ }).click();
    page.once('dialog', (dialog) => dialog.accept());
    await page.getByRole('button', { name: 'Sign out', exact: true }).click();
    await expect(page).toHaveURL(/\/login$/);
    await signIn(page, workerAccount);
    await page.goto('/me/hr');
    await expect(page.getByText('Final result: rejected', { exact: false })).toBeVisible();
    await expect(page.getByText('Synthetic LM-12 final rejection', { exact: true })).toBeVisible();
    await expect(page.getByText('Final decision by Browser Test Group Project Manager', { exact: false })).toHaveCount(0);
    await expect(page.getByRole('button', { name: 'Cancel leave', exact: true })).toHaveCount(0);
    await page.setViewportSize({ width: 390, height: 844 });
    await expect(page.getByText('Final result: rejected', { exact: false })).toBeVisible();
    expect(await page.evaluate(() => document.documentElement.scrollWidth <= window.innerWidth)).toBe(true);
    checkErrors();
    checkSupervisorErrors();
  } finally {
    await supervisorPage.close();
  }
});

test('LM-12 stale HR action reloads once without replay and needs-attention filter uses current route', async ({
  page, request
}) => {
  const checkErrors = watchLm12BrowserErrors(page);
  const hrAccount = seedAccount('hr_manager');
  const supervisorAccount = seedAccount('group_project_manager');
  const workerAccount = seedAccount('quantity_surveyor');
  const seeded = seedDirectReportLeave(supervisorAccount.email, workerAccount.email);
  const login = await signIn(page, hrAccount);
  const fallback = await request.post(`/api/v1/hr/leave/requests/${seeded.id}/fallback`, {
    headers: { Authorization: `Bearer ${login.accessToken}` },
    data: {
      expected_revision: 1, reason_code: 'manager_temporarily_unavailable',
      reason: 'Synthetic temporary route for LM-12', until: seeded.leaveDate
    }
  });
  expect(fallback.status()).toBe(200);
  await page.goto('/hr');
  await page.getByRole('button', { name: 'Leave', exact: true }).click();
  const row = page.getByTestId(`leave-request-${seeded.id}`);
  await expect(row.getByRole('button', { name: 'Approve', exact: true })).toBeVisible();
  await expect(row.getByRole('button', { name: 'Reject', exact: true })).toBeDisabled();
  await row.getByLabel('Rejection reason').fill('Synthetic stale decision');
  let writes = 0;
  page.on('request', (event) => {
    if (new URL(event.url()).pathname === `/api/v1/hr/leave/requests/${seeded.id}/decision` && event.method() === 'POST') writes += 1;
  });
  updateLm12Fixture(seeded.id, 'expire_fallback');
  const conflict = page.waitForResponse((event) =>
    new URL(event.url()).pathname === `/api/v1/hr/leave/requests/${seeded.id}/decision` && event.request().method() === 'POST'
  );
  const reload = page.waitForResponse((event) =>
    new URL(event.url()).pathname === '/api/v1/hr/leave/requests' && event.request().method() === 'GET'
  );
  await row.getByRole('button', { name: 'Reject', exact: true }).click();
  expect((await conflict).status()).toBe(409);
  expect((await reload).status()).toBe(200);
  await expect(row).toContainText('Review assignment needs refreshing.');
  await expect(row.getByRole('button', { name: 'Approve', exact: true })).toHaveCount(0);
  await expect(row.getByRole('button', { name: 'Refresh review assignment', exact: true })).toBeEnabled();
  expect(writes).toBe(1);
  const filtered = page.waitForResponse((event) => {
    const url = new URL(event.url());
    return url.pathname === '/api/v1/hr/leave/requests' && url.searchParams.get('needs_attention') === 'true';
  });
  await page.getByLabel('Needs rerouting or setup').check();
  expect((await filtered).status()).toBe(200);
  await expect(row).toBeVisible();
  await row.getByRole('button', { name: 'Refresh review assignment', exact: true }).click();
  await expect(row).toHaveCount(0);
  await page.getByLabel('Needs rerouting or setup').uncheck();
  await expect(row).toContainText('Pending decision: direct supervisor');
  expect(writes).toBe(1);
  await row.getByText('Record HR fallback', { exact: true }).click();
  await row.getByLabel('Temporary fallback through').fill(seeded.leaveDate);
  await row.getByLabel('Reason (recorded in the audit trail)').fill('Synthetic reviewed fallback');
  await row.getByRole('button', { name: 'Route to HR', exact: true }).click();
  await expect(row).toContainText('Pending decision: HR fallback');
  await row.getByLabel('Rejection reason').fill('Synthetic HR final rejection');
  const finalDecision = page.waitForResponse((event) =>
    new URL(event.url()).pathname === `/api/v1/hr/leave/requests/${seeded.id}/decision` &&
    event.request().method() === 'POST'
  );
  await row.getByRole('button', { name: 'Reject', exact: true }).click();
  expect((await finalDecision).status()).toBe(200);
  await expect(row).toContainText('Final decision by Browser Test Hr Manager');
  await expect(row.getByRole('button', { name: 'Approve', exact: true })).toHaveCount(0);
  await expect(row.getByRole('button', { name: 'Reject', exact: true })).toHaveCount(0);
  expect(writes).toBe(2); // The second write was a new, explicit decision on the refreshed route.
  checkErrors();
});
