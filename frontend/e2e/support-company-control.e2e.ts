import { execFileSync } from 'node:child_process';
import { randomUUID } from 'node:crypto';
import { env } from 'node:process';
import { fileURLToPath } from 'node:url';

import { expect, test, type Page } from '@playwright/test';

const supportHost = 'superadmin.garrisons.lk';
const supportOrigin = `https://${supportHost}`;
const backend = fileURLToPath(new URL('../../backend/', import.meta.url));

test.use({ trace: 'off' });

type OperatorFixture = { operator: string; credential: string; handle: string; key: string };

async function setupOperator(page: Page, fixture: OperatorFixture) {
  const cdp = await page.context().newCDPSession(page);
  await cdp.send('WebAuthn.enable');
  const { authenticatorId } = await cdp.send('WebAuthn.addVirtualAuthenticator', {
    options: {
      protocol: 'ctap2',
      transport: 'internal',
      hasResidentKey: true,
      hasUserVerification: true,
      isUserVerified: true,
      automaticPresenceSimulation: true
    }
  });
  await cdp.send('WebAuthn.addCredential', {
    authenticatorId,
    credential: {
      credentialId: fixture.credential,
      userHandle: fixture.handle,
      privateKey: fixture.key,
      rpId: supportHost,
      isResidentCredential: true,
      signCount: 0
    }
  });
  await page.route(`${supportOrigin}/**`, async (route) => {
    const request = route.request();
    const { pathname, search } = new URL(request.url());
    const isApi = pathname.startsWith('/api/v1/support/');
    const upstream = isApi ? 'http://127.0.0.1:8425' : 'http://127.0.0.1:4325';
    const fetchOptions = {
      url: upstream + pathname + search,
      headers: { ...(await request.allHeaders()), ...(isApi ? { host: supportHost } : {}) }
    };
    const isIdempotentRead = request.method() === 'GET' || request.method() === 'HEAD';
    let response;
    try {
      response = await route.fetch(fetchOptions);
    } catch (error) {
      if (!isIdempotentRead || !/ECONNRESET|socket hang up/i.test(String(error))) {
        throw error;
      }
      response = await route.fetch(fetchOptions);
    }
    await route.fulfill({ response });
  });
}

test('single owner uses Company Control Centre People & Access, User 360, Settings, and Security', async ({
  page
}) => {
  const fixture = JSON.parse(
    execFileSync(
      env.BROWSER_TEST_PYTHON ?? 'python',
      [
        '-c',
        `
from tests.browser_fixtures import configure
configure()
import asyncio
import json
from base64 import b64encode
from datetime import date
from uuid import uuid4
from cryptography.hazmat.primitives import serialization
from sqlalchemy import delete
from app.database import AsyncSessionLocal
from app.models.project import Project
from app.models.support_cases import SupportOperatorGrant
from app.models.support_oversight import COMPANY_CONTROL_CAPABILITIES
from app.models.support_registration import SupportBootstrap
from app.models.user import User
from app.utils.permissions import ROLE_SITE_SUPERVISOR
from app.utils.security import utc_now
from tests.test_support_identity import seed_operator

async def seed():
    operator, credential, key = await seed_operator()
    suffix = uuid4().hex[:6]
    user_id, project_id = uuid4(), uuid4()
    async with AsyncSessionLocal() as session:
        await session.execute(delete(SupportBootstrap))
        session.add(SupportBootstrap(
            id=1, first_id=operator, custody_mode="single_owner",
            approval_digest="e" * 64, started_at=utc_now(), activated_at=utc_now(),
        ))
        for cap in (*COMPANY_CONTROL_CAPABILITIES, "config.read"):
            session.add(SupportOperatorGrant(operator_id=operator, capability=cap))
        session.add(User(
            id=user_id,
            full_name=f"E2E Supervisor {suffix}",
            email=f"e2e.sup.{suffix}@garrisons.lk",
            employee_code=f"E2E-{suffix}",
            phone="0774445555",
            role=ROLE_SITE_SUPERVISOR,
            is_active=True,
        ))
        session.add(Project(
            id=project_id,
            code=f"E2P-{suffix}",
            name=f"E2E Tower {suffix}",
            status="active",
            scope_of_work="E2E verification tower",
            target_end_date=date(2029, 12, 31),
        ))
        await session.commit()
    return {
        "operator": str(operator),
        "credential": b64encode(credential).decode(),
        "handle": b64encode(operator.bytes).decode(),
        "key": b64encode(key.private_bytes(
            serialization.Encoding.DER,
            serialization.PrivateFormat.PKCS8,
            serialization.NoEncryption(),
        )).decode(),
        "userName": f"E2E Supervisor {suffix}",
        "projectCode": f"E2P-{suffix}",
    }

print(json.dumps(asyncio.run(seed())))
`
      ],
      { cwd: backend, encoding: 'utf8' }
    )
  ) as OperatorFixture & { userName: string; projectCode: string };

  await setupOperator(page, fixture);
  await page.goto(supportOrigin);
  await page.getByLabel('Operator reference').fill(fixture.operator);
  await page.getByRole('button', { name: 'Sign in with a passkey' }).click();
  await expect(page.getByText('Technical session active')).toBeVisible();

  // Navigate to People & Access without typing any UUID
  const nav = page.getByRole('navigation', { name: 'Company control centre navigation' });
  await nav.getByRole('button', { name: 'People & Access' }).click();
  const directory = page.getByRole('region', { name: 'People and access directory' });
  await directory.getByLabel('Search accounts').fill(fixture.userName);
  await directory.getByRole('button', { name: 'Search directory' }).click();
  await expect(directory.getByText(fixture.userName)).toBeVisible();

  // Open User 360 profile
  await directory.getByRole('button', { name: 'Open User 360' }).first().click();
  const profile = page.getByRole('region', { name: 'User 360 profile' });
  await expect(profile.getByText(fixture.userName)).toBeVisible();
  await expect(profile.getByText('***-5555')).toBeVisible();
  await expect(profile.getByText('0774445555')).toHaveCount(0);

  // Switch to Access tab and confirm effective access explanations
  await profile.getByRole('tab', { name: 'Access' }).click();
  await expect(profile.getByText(/Self-approval prohibited/i)).toBeVisible();

  // Switch to Projects & Operations and inspect non-sensitive projects
  await nav.getByRole('button', { name: 'Projects & Operations' }).click();
  const inspector = page.getByRole('region', {
    name: 'Registered non-sensitive data inspector'
  });
  await inspector.getByLabel('Inspector search').fill(fixture.projectCode);
  await inspector.getByRole('button', { name: 'Inspect entity' }).click();
  await expect(inspector.getByText(fixture.projectCode)).toBeVisible();

  // Switch to Settings and verify locked controls & allowlisted setting editor
  await nav.getByRole('button', { name: 'Settings' }).click();
  const safeSettings = page.getByRole('region', { name: 'Allowlisted operational settings' });
  await expect(safeSettings.getByText(/LOG_PURGE_ENABLED/)).toBeVisible();

  // Switch to Owner Security and confirm loaded passkey session assurance & recovery guidance
  await nav.getByRole('button', { name: 'Owner Security' }).click();
  const sec = page.getByRole('region', { name: 'Owner security posture' });
  await expect(sec.getByText('Owner custody & recovery guardrails')).toBeVisible();
  await expect(sec.getByText('passkey', { exact: true }).first()).toBeVisible();
  await page.unrouteAll({ behavior: 'ignoreErrors' });
});

test('a site supervisor sends a redacted failure report and Super Admin triages it', async ({
  page, browser
}) => {
  const fixture = JSON.parse(execFileSync(
    env.BROWSER_TEST_PYTHON ?? 'python', ['-c', `
from tests.browser_fixtures import configure
configure()
import asyncio
import json
from base64 import b64encode
from cryptography.hazmat.primitives import serialization
from app.database import AsyncSessionLocal
from app.models.support_cases import SupportOperatorGrant
from tests.browser_fixtures import seed_accounts
from tests.test_support_identity import seed_operator

async def seed():
    reporter, = await seed_accounts(["site_supervisor"])
    operator, credential, key = await seed_operator()
    async with AsyncSessionLocal() as session:
        session.add(SupportOperatorGrant(operator_id=operator, capability="operator.manage"))
        await session.commit()
    return {
        "reporter": reporter, "operator": str(operator),
        "credential": b64encode(credential).decode(), "handle": b64encode(operator.bytes).decode(),
        "key": b64encode(key.private_bytes(
            serialization.Encoding.DER, serialization.PrivateFormat.PKCS8, serialization.NoEncryption()
        )).decode()
    }
print(json.dumps(asyncio.run(seed())))
`], { cwd: backend, encoding: 'utf8' }
  )) as OperatorFixture & { reporter: {email: string; password: string} };

  // Feed an actual authenticated validation failure to the business HTTP client.
  await page.route('**/api/v1/notifications/unread-count', async (route) => {
    const url = new URL('/api/v1/projects/not-a-uuid', route.request().url()).href;
    await route.fulfill({ response: await route.fetch({ url }) });
  }, { times: 1 });
  const failedRequest = page.waitForResponse((response) =>
    response.url().endsWith('/api/v1/notifications/unread-count') && response.status() === 422
  );
  await page.goto('/login');
  await page.getByLabel('Email', { exact: true }).fill(fixture.reporter.email);
  await page.getByLabel('Password', { exact: true }).fill(fixture.reporter.password);
  await page.getByRole('button', { name: 'Continue' }).click();
  const code = (await page.getByText(/^Development code:/).textContent())?.match(/\d{6}/)?.[0];
  if (!code) throw new Error('Expected disposable test OTP');
  await page.getByLabel('Verification code').fill(code);
  await page.getByRole('button', { name: 'Verify and sign in' }).click();
  const requestId = (await failedRequest).headers()['x-request-id'];
  expect(requestId).toBeTruthy();

  let firstSubmission: string | undefined;
  await page.route('**/api/v1/feedback', async (route) => {
    const payload = route.request().postDataJSON() as { submission_id: string; request_ids: string[] };
    expect(payload.request_ids).toContain(requestId);
    if (!firstSubmission) {
      firstSubmission = payload.submission_id;
      await route.fulfill({ status: 503, json: { detail: 'Synthetic temporary submission failure.' } });
    } else {
      expect(payload.submission_id).toBe(firstSubmission);
      await route.continue();
    }
  });

  await page.setViewportSize({ width: 390, height: 844 });
  const trigger = page.getByRole('button', { name: 'Send feedback' });
  await trigger.click();
  const dialog = page.getByRole('dialog', { name: 'Send feedback' });
  const title = 'Project screen did not load · ' + randomUUID();
  const description = 'I expected the project to open. Link: https://example.com/?secret=fixture';
  await dialog.getByLabel('Summary').fill(title);
  await dialog.getByLabel('Details').fill(description);
  const include = dialog.getByRole('checkbox', { name: /Include recent failed request summaries/ });
  await expect(include).not.toBeChecked();
  await include.check();
  await dialog.getByRole('button', { name: 'Send report' }).click();
  await expect(dialog.getByRole('alert')).toContainText('temporary submission failure');
  await expect(dialog.getByLabel('Details')).toHaveValue(description);
  await dialog.getByRole('button', { name: 'Send report' }).click();
  await expect(dialog.getByRole('status')).toContainText('1 failed request summary attached');
  await dialog.getByRole('button', { name: 'Done' }).click();
  await expect(trigger).toBeFocused();

  const operator = await browser.newPage();
  try {
    await setupOperator(operator, fixture);
    await operator.goto(supportOrigin);
    await operator.getByLabel('Operator reference').fill(fixture.operator);
    await operator.getByRole('button', { name: 'Sign in with a passkey' }).click();
    await operator.getByRole('button', { name: 'Triage user feedback' }).click();
    const inbox = operator.getByRole('region', { name: 'Feedback inbox' });
    await inbox.getByText(title, { exact: true }).click();
    const row = inbox.locator('details').filter({ hasText: title });
    await expect(row.getByRole('region', { name: 'Attached request summaries' })).toContainText(requestId);
    await expect(row).toContainText('GET projects · HTTP 422');
    await expect(row).toContainText('[link removed]');
    await expect(row).not.toContainText('secret=fixture');
    await row.getByLabel('Report status').selectOption('investigating');
    await row.getByRole('button', { name: 'Save status' }).click();
    await expect(row).toHaveCount(0);
    await operator.reload();
    await inbox.getByLabel('Status filter').selectOption('investigating');
    await expect(row).toContainText('Investigating');
  } finally {
    await operator.close();
  }
});
