import { execFileSync } from 'node:child_process';
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
