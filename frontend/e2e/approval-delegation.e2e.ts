import { execFileSync } from 'node:child_process';
import { randomUUID } from 'node:crypto';
import { env } from 'node:process';
import { fileURLToPath } from 'node:url';

import { expect, test, type APIRequestContext, type Locator, type Page } from '@playwright/test';

type Account = { email: string; password: string };
type SeedAccount = Account & { projectId: string };
type Role = 'project_manager' | 'operation_manager' | 'civil_engineer';
type Headers = Record<string, string>;

const backendDirectory = fileURLToPath(new URL('../../backend/', import.meta.url));
const python = env.BROWSER_TEST_PYTHON ?? 'python';
const inbox = '/approvals?tab=workflow';

test.use({ trace: 'off' });

function seedAdmin(): SeedAccount {
  return JSON.parse(
    execFileSync(python, ['-m', 'tests.browser_fixtures', 'seed'], {
      cwd: backendDirectory,
      encoding: 'utf8'
    })
  );
}

async function signIn(page: Page, account: Account): Promise<Headers> {
  await page.goto('/login');
  await page.getByLabel('Email', { exact: true }).fill(account.email);
  await page.getByLabel('Password', { exact: true }).fill(account.password);
  await page.getByRole('button', { name: 'Continue' }).click();
  const code = (await page.getByText(/^Development code:/).innerText()).match(/\d{6}/)?.[0];
  if (!code) throw new Error('The test API did not expose the verification code.');
  await page.getByLabel('Verification code').fill(code);
  const verified = page.waitForResponse(
    (response) => response.url().endsWith('/api/v1/auth/verify-otp') && response.ok()
  );
  await page.getByRole('button', { name: 'Verify and sign in' }).click();
  const { access_token } = (await (await verified).json()) as { access_token: string };
  return { Authorization: `Bearer ${access_token}` };
}

async function createAccount(request: APIRequestContext, admin: Headers, role: Role, name: string) {
  const suffix = randomUUID().slice(0, 8);
  const email = `approval-${suffix}@example.com`;
  const password = `BrowserFixture!${randomUUID()}`;
  const response = await request.post('/api/v1/users', {
    headers: admin,
    data: {
      email,
      temporary_password: password,
      full_name: `${name} ${suffix}`,
      role,
      employee_code: `APR-${suffix}`,
      phone: '5550124'
    }
  });
  expect(response.status()).toBe(201);
  return { email, password, id: ((await response.json()) as { id: string }).id };
}

function processOverdueApproval(approvalId: string, observerId: string) {
  // Assign this test’s Operations Manager so parallel account creation cannot change the fixture.
  // The approval service creates the escalation and sends the notification.
  execFileSync(
    python,
    [
      '-c',
      `
import asyncio
import sys
from datetime import timedelta
from uuid import UUID
from tests.browser_fixtures import configure

configure()

from app.database import AsyncSessionLocal, engine
from app.models.approval import Approval
from app.services.approval_service import ApprovalService
from app.utils.security import utc_now

async def run():
    try:
        async with AsyncSessionLocal() as session:
            approval = await session.get(Approval, UUID(sys.argv[1]))
            assert approval is not None and approval.status == "delegated"
            approval.due_at = utc_now() - timedelta(hours=25)
            approval.escalation_user_id = UUID(sys.argv[2])
            await session.commit()
            await ApprovalService(session).send_reminders_and_escalations()
            await session.refresh(approval)
            assert approval.status == "escalated"
    finally:
        await engine.dispose()

asyncio.run(run())
`,
      approvalId,
      observerId
    ],
    { cwd: backendDirectory, stdio: ['ignore', 'pipe', 'pipe'] }
  );
}

async function expectReadOnly(card: Locator) {
  await expect(
    card.getByRole('button', { name: /^(Approve|Reject|Delegate|Override)$/ })
  ).toHaveCount(0);
  await expect(card.getByLabel('Approval or rejection comments')).toHaveCount(0);
}

test('a project delegate decides an escalated approval while Operations observes and a stale tab refreshes', async ({
  page,
  browser,
  request,
  baseURL
}) => {
  const seeded = seedAdmin();
  const admin = await signIn(page, seeded);
  const candidate = await createAccount(request, admin, 'project_manager', 'Delegate');
  const primary = await createAccount(request, admin, 'project_manager', 'Approver');
  const unrelated = await createAccount(request, admin, 'project_manager', 'Unassigned');
  const observer = await createAccount(request, admin, 'operation_manager', 'Oversight');
  const requester = await createAccount(request, admin, 'civil_engineer', 'Submitter');
  // The most recently assigned eligible Project Manager receives the initial decision.
  for (const member of [candidate, primary, requester]) {
    const response = await request.post(`/api/v1/projects/${seeded.projectId}/members`, {
      headers: admin,
      data: { user_id: member.id }
    });
    expect(response.status()).toBe(201);
  }

  const primaryPage = await browser.newPage({ baseURL });
  const delegatePage = await browser.newPage({ baseURL });
  const observerPage = await browser.newPage({ baseURL });
  const requesterPage = await browser.newPage({ baseURL });
  try {
    const primaryHeaders = await signIn(primaryPage, primary);
    const delegateHeaders = await signIn(delegatePage, candidate);
    const observerHeaders = await signIn(observerPage, observer);
    const requesterHeaders = await signIn(requesterPage, requester);
    const title = `Site sequence change ${randomUUID().slice(0, 8)}`;
    const created = await request.post('/api/v1/approvals', {
      headers: requesterHeaders,
      data: {
        request_type: 'project_change',
        request_id: randomUUID(),
        project_id: seeded.projectId,
        title
      }
    });
    expect(created.status()).toBe(201);
    const approval = (await created.json()) as {
      id: string;
      approver_id: string;
    };
    expect(approval.approver_id).toBe(primary.id);

    const path = `/api/v1/approvals/${approval.id}`;
    const link = `${inbox}&approvalId=${approval.id}`;
    const cardOn = (surface: Page) =>
      surface.getByRole('article').filter({ has: surface.getByRole('heading', { name: title }) });

    const requesterReportCalls: string[] = [];
    requesterPage.on('request', (entry) => {
      const pathname = new URL(entry.url()).pathname;
      if (pathname === '/api/v1/reports') requesterReportCalls.push(pathname);
    });
    await requesterPage.goto(inbox);
    await expect(cardOn(requesterPage)).toBeVisible();
    await expect(requesterPage.getByRole('button', { name: 'Report approvals' })).toHaveCount(0);
    await expect(requesterPage.getByRole('button', { name: 'Inbox', exact: true })).toHaveCount(0);
    await expectReadOnly(cardOn(requesterPage));
    expect(requesterReportCalls).toEqual([]);

    await primaryPage.goto(link);
    const primaryCard = cardOn(primaryPage);
    await expect(primaryCard.getByText('pending', { exact: true })).toBeVisible();
    const picker = primaryCard.getByRole('combobox');
    await picker.focus();
    await expect(picker.locator(`option[value="${candidate.id}"]`)).toHaveCount(1);
    await expect(picker.locator(`option[value="${unrelated.id}"]`)).toHaveCount(0);
    await expect(picker.locator(`option[value="${requester.id}"]`)).toHaveCount(0);
    await expect(picker.locator(`option[value="${primary.id}"]`)).toHaveCount(0);
    await picker.selectOption(candidate.id);
    await primaryCard.getByPlaceholder('Reason', { exact: true }).fill('Site handover coverage');
    await primaryCard.getByRole('button', { name: 'Delegate', exact: true }).click();
    await expect(primaryCard.getByText('delegated', { exact: true })).toBeVisible();
    const delegated = await request.get(path, { headers: primaryHeaders });
    expect(delegated.ok()).toBe(true);
    expect(await delegated.json()).toMatchObject({
      delegated_to_id: candidate.id,
      delegation_reason: 'Site handover coverage'
    });

    await delegatePage.goto(inbox);
    await delegatePage.getByLabel('Approval status').selectOption('delegated');
    await expect(
      cardOn(delegatePage).getByRole('button', { name: 'Approve', exact: true })
    ).toBeVisible();
    const pendingInbox = observerPage.waitForResponse((response) => {
      const url = new URL(response.url());
      return url.pathname === '/api/v1/approvals' && url.searchParams.get('box') === 'inbox';
    });
    await observerPage.goto(inbox);
    expect((await pendingInbox).ok()).toBe(true);
    await expect(cardOn(observerPage)).toHaveCount(0);

    processOverdueApproval(approval.id, observer.id);

    await observerPage.reload();
    const oversight = cardOn(observerPage);
    await expect(oversight.getByText('escalated', { exact: true })).toBeVisible();
    await expectReadOnly(oversight);
    const denied = await request.post(`${path}/approve`, {
      headers: observerHeaders,
      data: { comments: 'Oversight is read-only' }
    });
    expect(denied.status()).toBe(403);

    await delegatePage.goto(link);
    const delegatedCard = cardOn(delegatePage);
    await expect(delegatedCard.getByText('escalated', { exact: true })).toBeVisible();
    await delegatedCard
      .getByLabel('Approval or rejection comments')
      .fill('Reviewed the site sequence.');
    await delegatedCard.getByRole('button', { name: 'Approve', exact: true }).click();
    await expect(delegatedCard.getByText('approved', { exact: true })).toBeVisible();
    await expectReadOnly(delegatedCard);

    await primaryCard.getByLabel('Approval or rejection comments').fill('Stale decision attempt.');
    const stale = primaryPage.waitForResponse(
      (response) =>
        response.url().endsWith(`${path}/reject`) && response.request().method() === 'POST'
    );
    await primaryCard.getByRole('button', { name: 'Reject', exact: true }).click();
    expect((await stale).status()).toBe(409);
    await expect(
      primaryPage.getByText(/already (been decided|final)|approval.*changed/i)
    ).toBeVisible();
    await expect(primaryCard.getByText('approved', { exact: true })).toBeVisible();
    await expectReadOnly(primaryCard);

    await requesterPage.reload();
    await requesterPage.getByLabel('Approval status').selectOption('all');
    await expect(cardOn(requesterPage).getByText('Reviewed the site sequence.')).toBeVisible();
    await expectReadOnly(cardOn(requesterPage));
    expect(requesterReportCalls).toEqual([]);

    const decided = await request.get(path, { headers: delegateHeaders });
    expect(decided.ok()).toBe(true);
    expect(await decided.json()).toMatchObject({
      status: 'approved',
      decision_comments: 'Reviewed the site sequence.',
      allowed_actions: []
    });
  } finally {
    await Promise.all([
      primaryPage.close(),
      delegatePage.close(),
      observerPage.close(),
      requesterPage.close()
    ]);
  }
});
