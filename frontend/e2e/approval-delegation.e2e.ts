import { execFileSync } from 'node:child_process';
import { randomUUID } from 'node:crypto';
import { env } from 'node:process';
import { fileURLToPath } from 'node:url';

import { expect, test, type Page } from '@playwright/test';

type Account = { email: string; password: string; projectId: string };
type DelegationFixture = {
  email: string;
  password: string;
  approvalId: string;
  approvalTitle: string;
  candidateId: string;
  candidateName: string;
};
type Headers = Record<string, string>;

const backendDirectory = fileURLToPath(new URL('../../backend/', import.meta.url));
const python = env.BROWSER_TEST_PYTHON ?? 'python';

test.use({ trace: 'off' });

function seedDirector(): Account {
  return JSON.parse(
    execFileSync(python, ['-m', 'tests.browser_fixtures', 'seed'], {
      cwd: backendDirectory,
      encoding: 'utf8'
    })
  );
}

function seedDelegation(): DelegationFixture {
  return JSON.parse(
    execFileSync(python, ['-m', 'tests.browser_fixtures', 'seed-delegation'], {
      cwd: backendDirectory,
      encoding: 'utf8'
    })
  );
}

async function signIn(
  page: Page,
  account: Pick<Account, 'email' | 'password'>
): Promise<Headers> {
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

test('unsupported generic and invoice approval requests cannot bypass their owning workflows', async ({
  page,
  request
}) => {
  const account = seedDirector();
  const headers = await signIn(page, account);
  await page.goto('/approvals');
  await expect(page.getByRole('button', { name: 'My submitted requests' })).toBeVisible();
  await expect(page.getByRole('button', { name: 'Inbox', exact: true })).toBeVisible();

  for (const requestType of ['project_change', 'invoice']) {
    const title = `Rejected ${requestType} ${randomUUID().slice(0, 8)}`;
    const response = await request.post('/api/v1/approvals', {
      headers,
      data: {
        request_type: requestType,
        request_id: randomUUID(),
        project_id: account.projectId,
        title
      }
    });
    expect(response.status()).toBe(403);
    expect((await response.json()).error_code).toBe('APPROVAL_TYPE_FORBIDDEN');
    await page.reload();
    await page.getByRole('button', { name: 'My submitted requests' }).click();
    await expect(page.getByText(title, { exact: true })).toHaveCount(0);
  }
});

test('a delegate beyond the first candidate page can be searched and selected', async ({
  page,
  request
}) => {
  const fixture = seedDelegation();
  const headers = await signIn(page, fixture);
  const approvalUrl = `/api/v1/approvals/${fixture.approvalId}`;
  await page.goto(`/approvals?tab=workflow&approvalId=${fixture.approvalId}`);

  const card = page
    .getByRole('article')
    .filter({ has: page.getByRole('heading', { name: fixture.approvalTitle }) });
  await expect(card).toBeVisible();

  const picker = card.getByRole('combobox', {
    name: `Eligible approver for ${fixture.approvalTitle}`
  });
  await picker.focus();
  const search = card.getByRole('searchbox', {
    name: `Search eligible approvers for ${fixture.approvalTitle}`
  });
  await search.fill(fixture.candidateName);
  await expect(picker.locator(`option[value="${fixture.candidateId}"]`)).toHaveCount(1);
  await picker.selectOption(fixture.candidateId);
  await card.getByPlaceholder('Reason', { exact: true }).fill('Coverage during planned leave');

  const delegatedResponse = page.waitForResponse(
    (response) =>
      response.url().endsWith(`/api/v1/approvals/${fixture.approvalId}/delegate`) &&
      response.request().method() === 'POST'
  );
  await card.getByRole('button', { name: 'Delegate', exact: true }).click();
  expect((await delegatedResponse).status()).toBe(200);
  await expect(page.getByText('Approval delegated.')).toBeVisible();

  const persisted = await request.get(approvalUrl, { headers });
  expect(persisted.ok()).toBe(true);
  expect(await persisted.json()).toMatchObject({
    status: 'delegated',
    delegated_to_id: fixture.candidateId,
    delegation_reason: 'Coverage during planned leave'
  });
});
