import { execFileSync } from 'node:child_process';
import { constants, createDecipheriv, createHash, generateKeyPairSync, privateDecrypt, randomBytes, randomUUID } from 'node:crypto';
import { readFileSync } from 'node:fs';
import { env } from 'node:process';
import { fileURLToPath } from 'node:url';

import { expect, test, type Page } from '@playwright/test';

const supportHost = 'superadmin.garrisons.lk';
const supportOrigin = `https://${supportHost}`;
const backend = fileURLToPath(new URL('../../backend/', import.meta.url));

test.use({ trace: 'off' });

type OperatorFixture = { operator: string; credential: string; handle: string; key: string };

async function setupOperator(page: Page, fixture?: OperatorFixture) {
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
  if (fixture) await cdp.send('WebAuthn.addCredential', {
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

async function signIn(page: Page, operator: string) {
  await page.goto(supportOrigin);
  await page.getByLabel('Operator reference').fill(operator);
  await page.getByRole('button', { name: 'Sign in with a passkey' }).click();
  await expect(page.getByText('Technical session active')).toBeVisible();
}

async function openWorkspace(page: Page, name: string) {
  await page.getByRole('navigation', { name: 'Company control centre navigation' })
    .getByRole('button', { name, exact: true }).click();
}

test('synthetic operator signs in with a verified passkey and signs out', async ({ page, request }) => {
  const fixture = JSON.parse(execFileSync(
    env.BROWSER_TEST_PYTHON ?? 'python',
    ['-c', `
from tests.browser_fixtures import configure
configure()
import asyncio
import json
from base64 import b64encode
from cryptography.hazmat.primitives import serialization
from uuid import uuid4
from tests.test_support_identity import seed_operator
from app.database import AsyncSessionLocal
from app.models.activity_log import ActivityLog
from app.models.support_cases import (
    SupportCase, SupportCaseMember, SupportCaseRequest, SupportOperatorGrant,
)

async def seed():
    operator, credential, key = await seed_operator()
    case, request = uuid4(), uuid4().hex
    async with AsyncSessionLocal() as session:
        session.add(SupportCase(id=case, status="open"))
        session.add(ActivityLog(request_id=request, action="http.request",
            entity_type="request", http_method="GET", status_code=200,
            comments="synthetic-private-marker"))
        await session.flush()
        session.add(SupportCaseMember(case_id=case, operator_id=operator))
        session.add(SupportCaseRequest(case_id=case, request_id=request))
        session.add(SupportOperatorGrant(operator_id=operator, capability="logs.runtime"))
        session.add(SupportOperatorGrant(operator_id=operator, capability="logs.stream"))
        session.add(SupportOperatorGrant(operator_id=operator, capability="cases.manage"))
        session.add(SupportOperatorGrant(operator_id=operator, capability="health.read"))
        await session.commit()
    return operator, credential, key, case, request

operator, credential, key, case, request = asyncio.run(seed())
print(json.dumps({
    "operator": str(operator),
    "credential": b64encode(credential).decode(),
    "handle": b64encode(operator.bytes).decode(),
    "case": str(case),
    "request": request,
    "key": b64encode(key.private_bytes(
        serialization.Encoding.DER,
        serialization.PrivateFormat.PKCS8,
        serialization.NoEncryption(),
    )).decode(),
}))
`],
    { cwd: backend, encoding: 'utf8' }
  )) as {
    operator: string; credential: string; handle: string; key: string;
    case: string; request: string;
  };
  await setupOperator(page, fixture);
  await signIn(page, fixture.operator);
  await page.reload();
  await expect(page.getByText('Technical session active')).toBeVisible();
  await openWorkspace(page, 'Support & Audit');
  await page.getByLabel('Case reference').fill(fixture.case);
  await page.getByLabel('Request ID').fill('00000000000000000000000000000000');
  await page.getByRole('button', { name: 'Search request evidence' }).click();
  await expect(page.getByRole('alert')).toContainText('unavailable to your operator account');
  await page.getByLabel('Request ID').fill(fixture.request);
  await page.getByRole('button', { name: 'Search request evidence' }).click();
  await expect(page.getByRole('region', { name: 'Request evidence' }))
    .toContainText('request · GET · 200');
  await expect(page.getByRole('main')).not.toContainText('synthetic-private-marker');
  const evidence = page.getByRole('region', { name: 'Request evidence' });
  const cursor = randomUUID();
  let connections = 0;
  await page.route('**/logs/stream?*', async (route) => {
    connections += 1;
    expect(route.request().headers()['last-event-id']).toBe(connections === 1 ? undefined : cursor);
    const item = { id: cursor, occurred_at: new Date().toISOString(), kind: 'request',
      method: 'PATCH', status_code: 202 };
    await route.fulfill({
      contentType: 'text/event-stream',
      body: connections === 1
        ? `: keep-alive\n\nid: ${cursor}\ndata: ${JSON.stringify(item)}\n\nevent: closed\ndata: {"reason":"time_limit"}\n\n`
        : 'event: closed\ndata: {"reason":"access_ended"}\n\n'
    });
  });
  await evidence.getByRole('button', { name: 'Follow live evidence' }).click();
  await expect(evidence).toContainText('request · PATCH · 202');
  await evidence.getByRole('button', { name: 'Resume live evidence' }).click();
  await expect(evidence.getByRole('alert')).toHaveText('Access to this evidence ended.');
  await expect(evidence).not.toContainText('request · PATCH · 202');
  expect(connections).toBe(2);
  await openWorkspace(page, 'Overview');
  await expect(page.getByRole('region', { name: 'Dependencies' })).toContainText('operational');
  await page.getByRole('button', { name: 'Inspect service health' }).click();
  await expect(page).toHaveURL(/#\/operations\/health$/);
  await expect(page.locator('#tool-health')).toBeFocused();
  const health = page.getByRole('region', { name: 'Service health' });
  await health.getByRole('button', { name: 'Check service health' }).click();
  await expect(health.getByText('Operational').first()).toBeVisible();
  await expect(health.getByText('Redis')).toBeVisible();
  await openWorkspace(page, 'Support & Audit');
  const reference = 'incident-' + randomUUID();
  await expect(page.getByText('No assigned cases.')).toBeVisible();
  await page.getByLabel('Incident reference').fill(reference);
  await page.getByRole('button', { name: 'Create case' }).click();
  const details = page.getByRole('region', { name: 'Case details' });
  await expect(details.getByRole('heading', { name: reference, exact: true })).toBeVisible();
  await page.getByLabel('Incident reference').fill(reference);
  await page.getByRole('button', { name: 'Create case' }).click();
  await expect(page.getByRole('region', { name: 'Support cases' }).getByRole('alert'))
    .toContainText('That case reference cannot be used');
  await expect(page.getByLabel('Incident reference')).toHaveValue(reference);
  await details.getByRole('button', { name: 'Start investigation' }).click();
  await expect(details.getByText('Investigating', { exact: true })).toBeVisible();
  await details.getByRole('button', { name: 'Mark mitigated' }).click();
  await expect(details.getByText('Mitigated', { exact: true })).toBeVisible();
  await page.reload();
  await page.getByRole('button', { name: reference + ' · Mitigated' }).click();
  await expect(details.getByText('Mitigated', { exact: true })).toBeVisible();
  await expect(details.getByRole('button', { name: 'Close case' })).toHaveCount(0);
  await page.getByRole('button', { name: 'Sign out' }).click();
  await expect(page.getByRole('button', { name: 'Sign in with a passkey' })).toBeVisible();
  await expect.poll(async () => (await page.context().cookies(supportOrigin)).length).toBe(0);
  const terminal = 'http://127.0.0.1:8425/api/v1/support';
  const headers = { Host: supportHost, Origin: supportOrigin };
  const token = randomBytes(32).toString('base64url');
  const csrf = randomBytes(32).toString('base64url');
  const pairing = randomBytes(6).toString('hex');
  const digest = (value: string) => createHash('sha256').update(value).digest('hex');
  const handoff = await request.post(terminal + '/auth/cli/start', { headers, data: {
    operator_id: fixture.operator, token_hash: digest(token), csrf_hash: digest(csrf),
    code_hash: digest(pairing)
  } });
  expect(handoff.ok()).toBeTruthy();
  const { challenge_id } = await handoff.json() as { challenge_id: string };
  await page.goto(supportOrigin + '/#cli=' + challenge_id);
  await page.getByLabel('Terminal pairing code').fill(pairing);
  await page.getByRole('button', { name: 'Approve CLI sign-in with passkey' }).click();
  await expect(page.getByText('CLI sign-in approved. Return to your terminal.')).toBeVisible();
  await expect.poll(async () => (await page.context().cookies(supportOrigin)).length).toBe(0);
  const cookie = '__Host-garrison-support=' + token;
  const cli = await request.get(terminal + '/me', { headers: { ...headers, Cookie: cookie } });
  expect(cli.ok()).toBeTruthy();
  expect((await cli.json()).operator_id).toBe(fixture.operator);
  const loggedOut = await request.post(terminal + '/auth/logout', {
    headers: { ...headers, Cookie: cookie, 'X-Support-CSRF': csrf }
  });
  expect(loggedOut.status()).toBe(204);
});

test('synthetic custodians review grants, enroll two passkeys and close a case in Chrome', async ({ browser }) => {
  const [maker, reviewer, target, pendingOperator, caseUser, caseProject, projectUser] = JSON.parse(execFileSync(
    env.BROWSER_TEST_PYTHON ?? 'python',
    ['-c', `
from tests.browser_fixtures import configure
configure()
import asyncio
import json
import os
from datetime import date, timedelta
from base64 import b64encode
from cryptography.hazmat.primitives import serialization
from pydantic import SecretStr
from uuid import UUID, uuid4
from app.config import Settings
from app.database import AsyncSessionLocal
from app.models.project import Project
from app.models.project_member import ProjectMember
from app.models.support_identity import SupportOperator
from app.models.support_cases import SupportOperatorGrant
from app.models.user import User
from app.utils.permissions import ROLE_GROUP_PROJECT_MANAGER, ROLE_HR_EXECUTIVE
from app.utils.recovery_destination import recovery_destination_digest
from app.utils.security import utc_now
from tests.test_support_custody import seed_custody_operator

async def seed():
    fixtures = []
    for custodian in (True, True, False):
        operator, credential, key = await seed_custody_operator(custodian=custodian)
        fixtures.append({
            "operator": str(operator),
            "credential": b64encode(credential).decode(),
            "handle": b64encode(operator.bytes).decode(),
            "key": b64encode(key.private_bytes(
                serialization.Encoding.DER,
                serialization.PrivateFormat.PKCS8,
                serialization.NoEncryption(),
            )).decode(),
        })
    pending, subject, project, project_user = uuid4(), uuid4(), uuid4(), uuid4()
    address = f"employee-{subject.hex}@example.com"
    recovery_settings = Settings(support_recovery_key=SecretStr(
        os.environ["BROWSER_TEST_SUPPORT_RECOVERY_KEY"]))
    async with AsyncSessionLocal() as session:
        session.add(Project(id=project, name="Private synthetic project", code=project.hex[:12],
            scope_of_work="Private synthetic scope", target_end_date=date(2030, 1, 1)))
        session.add(User(id=project_user, email=f"project-{project_user.hex}@example.com",
            full_name="Synthetic Project Manager", role=ROLE_GROUP_PROJECT_MANAGER))
        await session.flush()
        session.add(ProjectMember(project_id=project, user_id=project_user))
        session.add(SupportOperatorGrant(operator_id=UUID(fixtures[0]["operator"]), capability="cases.manage"))
        session.add(SupportOperatorGrant(operator_id=UUID(fixtures[2]["operator"]), capability="company.directory.read"))
        for fixture in (fixtures[0], fixtures[2]):
            for capability in ("directory.read", "account.request", "logs.audit", "simulation.start",
                               "logs.runtime", "logs.export"):
                session.add(SupportOperatorGrant(operator_id=UUID(fixture["operator"]), capability=capability))
        session.add(User(id=subject, email=address,
            full_name="Synthetic Case Employee", role=ROLE_HR_EXECUTIVE, phone="555-private-fixture",
            recovery_email_digest=recovery_destination_digest(recovery_settings, subject, address),
            recovery_email_verified_at=utc_now(),
            failed_login_attempts=4, locked_until=utc_now() + timedelta(minutes=30)))
        session.add(SupportOperator(
            id=pending, display_label="Synthetic pending", status="pending", grant_epoch=1,
        ))
        await session.commit()
    fixtures.extend([str(pending), str(subject), str(project), str(project_user)])
    return fixtures
print(json.dumps(asyncio.run(seed())))
`],
    { cwd: backend, encoding: 'utf8' }
  )) as [OperatorFixture, OperatorFixture, OperatorFixture, string, string, string, string];
  const [requestPage, reviewPage, targetPage, firstDevice, secondDevice] = await Promise.all([
    browser.newPage(), browser.newPage(), browser.newPage(), browser.newPage(), browser.newPage()
  ]);
  try {
    await Promise.all([
      setupOperator(requestPage, maker), setupOperator(reviewPage, reviewer),
      setupOperator(targetPage, target)
    ]);
    await Promise.all([
      signIn(requestPage, maker.operator), signIn(reviewPage, reviewer.operator),
      signIn(targetPage, target.operator)
    ]);
    await Promise.all([
      openWorkspace(requestPage, 'Owner Security'),
      openWorkspace(reviewPage, 'Owner Security'),
      openWorkspace(targetPage, 'Owner Security')
    ]);
    await expect(targetPage.getByRole('region', { name: 'Operator custody' })).toHaveCount(0);
    await openWorkspace(targetPage, 'Support & Audit');
    await expect(targetPage.getByRole('region', { name: 'Support cases' })).toHaveCount(0);
    await requestPage.getByLabel('Custody action').selectOption('grant-changes');
    await requestPage.getByLabel('Target operator reference').fill(target.operator);
    await requestPage.getByRole('button', { name: 'Create custody proposal' }).click();
    await expect(requestPage.getByText('Proposal created.', { exact: false })).toBeVisible();
    const proposal = await requestPage.getByLabel('Proposal reference', { exact: true }).inputValue();
    await requestPage.getByRole('button', { name: 'Prepare passkey proof' }).click();
    await expect(requestPage.getByRole('alert')).toContainText('cannot perform this action');

    await reviewPage.getByLabel('Custody action').selectOption('grant-changes');
    await reviewPage.getByLabel('Proposal reference', { exact: true }).fill(proposal);
    await reviewPage.getByRole('button', { name: 'Prepare passkey proof' }).click();
    const review = reviewPage.getByRole('region', { name: 'Confirm custody decision' });
    await expect(review).toContainText(target.operator);
    await expect(review).toContainText('Grant until revoked · Manage support cases');
    await review.getByRole('button', { name: 'Approve with passkey' }).click();
    await expect(reviewPage.getByText('Independent review recorded.')).toBeVisible();

    await requestPage.getByLabel('Decision').selectOption('execute');
    await requestPage.getByRole('button', { name: 'Prepare passkey proof' }).click();
    const execute = requestPage.getByRole('region', { name: 'Confirm custody decision' });
    await expect(execute).toContainText(target.operator);
    await execute.getByRole('button', { name: 'Execute with passkey' }).click();
    await expect(requestPage.getByText('Custody decision applied.')).toBeVisible();

    await targetPage.reload();
    await expect(targetPage.getByLabel('Operator reference')).toBeVisible();
    await signIn(targetPage, target.operator);
    await openWorkspace(targetPage, 'Support & Audit');
    await expect(targetPage.getByRole('region', { name: 'Support cases' })).toBeVisible();
    await openWorkspace(targetPage, 'Projects & Operations');
    await expect(targetPage.getByRole('region', { name: 'Service health' })).toHaveCount(0);
    await openWorkspace(targetPage, 'Support & Audit');

    await requestPage.getByLabel('Custody action').selectOption('enroll');
    await requestPage.getByLabel('Target operator reference').fill(pendingOperator);
    await requestPage.getByRole('button', { name: 'Create custody proposal' }).click();
    await expect(requestPage.getByText('Proposal created.', { exact: false })).toBeVisible();
    const enrollment = await requestPage.getByLabel('Proposal reference', { exact: true }).inputValue();
    await reviewPage.getByLabel('Custody action').selectOption('enroll');
    await reviewPage.getByLabel('Proposal reference', { exact: true }).fill(enrollment);
    await reviewPage.getByRole('button', { name: 'Prepare passkey proof' }).click();
    await expect(review).toContainText('Issue two one-use passkey invitations.');
    await review.getByRole('button', { name: 'Approve with passkey' }).click();
    await expect(reviewPage.getByText('Independent review recorded.')).toBeVisible();
    await requestPage.getByRole('button', { name: 'Prepare passkey proof' }).click();
    await execute.getByRole('button', { name: 'Execute with passkey' }).click();
    const invitations = requestPage.getByRole('region', { name: 'One-use registration invitations' });
    await expect(invitations).toBeVisible();
    const codes = await Promise.all([invitations.getByLabel('Invitation 1').inputValue(),
      invitations.getByLabel('Invitation 2').inputValue()]);
    await invitations.getByRole('button', { name: 'Hide invitations' }).click();

    await Promise.all([setupOperator(firstDevice), setupOperator(secondDevice)]);
    for (const [index, device] of [firstDevice, secondDevice].entries()) {
      if (index === 0) {
        await device.goto(supportOrigin + '/#register');
        const file = device.getByLabel('Single-device invitation file');
        const choose = (operator_reference: string) => file.setInputFiles({
          name: 'invitation.json', mimeType: 'application/json',
          buffer: Buffer.from(JSON.stringify({ version: 1, operator_reference, invitation: codes[index] }))
        });
        await choose(randomUUID());
        await device.getByRole('button', { name: 'Register this device' }).click();
        await expect(device.getByRole('alert')).toContainText('The passkey could not be registered');
        await choose(pendingOperator);
        await expect(device.getByText('Invitation loaded.')).toBeVisible();
      } else {
        await device.goto(supportOrigin);
        await device.getByText('Register a passkey', { exact: true }).click();
        await device.getByLabel('Registration invitation').fill(codes[index]);
      }
      await device.getByRole('button', { name: 'Register this device' }).click();
      await expect(device.getByRole('status')).toContainText(index === 0
        ? 'Use the second invitation on the other device.'
        : 'Both passkeys are registered.');
    }
    await signIn(firstDevice, pendingOperator);
    await openWorkspace(firstDevice, 'Owner Security');
    await expect(firstDevice.getByRole('region', { name: 'Operator custody' })).toHaveCount(0);

    await openWorkspace(requestPage, 'Support & Audit');
    await openWorkspace(reviewPage, 'Support & Audit');
    const reference = 'reviewed-case-' + randomUUID();
    await requestPage.getByLabel('Incident reference').fill(reference);
    await requestPage.getByRole('button', { name: 'Create case' }).click();
    const details = requestPage.getByRole('region', { name: 'Case details' });
    await expect(details.getByRole('heading', { name: reference })).toBeVisible();
    const caseId = (await details.getByText(/^Case ID /).innerText()).replace('Case ID ', '');
    const proposeAction = async (kind: string, field?: string, value?: string) => {
      await details.getByRole('combobox', { name: 'Case action', exact: true }).selectOption(kind);
      if (field && value) await details.getByLabel(field).fill(value);
      await details.getByRole('button', { name: 'Prepare case decision' }).click();
      return (await details.getByLabel('Case proposal ID').innerText()).trim();
    };
    const approveAction = async (page: Page, id: string, expected: string) => {
      const section = page.getByRole('region', { name: 'Review case action' });
      await section.getByLabel('Case ID for review').fill(caseId);
      await section.getByLabel('Case proposal reference').fill(id);
      await section.getByRole('button', { name: 'Load case proposal' }).click();
      const confirmation = section.getByRole('region', { name: 'Confirm case action' });
      await expect(confirmation).toContainText(expected);
      await confirmation.getByRole('button', { name: 'Approve case action with passkey' }).click();
      await expect(section.getByText('Case action applied.')).toBeVisible();
    };
    const reopen = async (status: string) => {
      await requestPage.reload();
      await requestPage.getByRole('button', { name: reference + ' · ' + status }).click();
      await expect(details.getByText(status, { exact: true })).toBeVisible();
    };
    const member = await proposeAction('member_add', 'Member operator reference', target.operator);
    const supportPost = (page: Page, path: string, data: object) => page.evaluate(async ({ path, data }) => {
      const prefix = '__Host-garrison-support-csrf=';
      const csrf = document.cookie.split('; ').find((cookie) => cookie.startsWith(prefix))?.slice(prefix.length);
      const response = await fetch('/api/v1/support' + path, {
        method: 'POST', headers: { 'Content-Type': 'application/json', 'X-Support-CSRF': csrf ?? '' },
        body: JSON.stringify(data)
      });
      return { status: response.status, body: response.status === 204 ? null : await response.json() };
    }, { path, data });
    const base = '/cases/' + caseId + '/actions/' + member;
    const options = await supportPost(reviewPage, base + '/options', {});
    expect(options.status).toBe(200);
    const keys = generateKeyPairSync('rsa', { modulusLength: 2048 });
    const pairing = randomBytes(6).toString('hex');
    const relay = '/auth/cli-proof';
    const opened = await supportPost(reviewPage, relay + '/start', {
      proof_id: options.body.challenge_id,
      pairing_hash: createHash('sha256').update(pairing).digest('hex'),
      encryption_key: keys.publicKey.export({ type: 'spki', format: 'der' }).toString('base64url')
    });
    expect(opened.status).toBe(200);
    const handoff = opened.body.reference as string;
    await reviewPage.goto(supportOrigin + '/#proof=' + handoff);
    await reviewPage.getByLabel('Action pairing code').fill(pairing);
    await reviewPage.getByRole('button', { name: 'Load CLI action' }).click();
    await expect(reviewPage.getByRole('region', { name: 'Approve CLI action' })).toContainText(member);
    await reviewPage.getByRole('button', { name: 'Approve CLI action with passkey' }).click();
    await expect(reviewPage.getByText('Passkey proof sent. Return to your terminal.')).toBeVisible();
    const collected = await supportPost(reviewPage, relay + '/take', { reference: handoff });
    expect(collected.status).toBe(200);
    const sealed = Buffer.from(collected.body.sealed as string, 'base64url');
    const aes = privateDecrypt({ key: keys.privateKey, padding: constants.RSA_PKCS1_OAEP_PADDING,
      oaepHash: 'sha256' }, sealed.subarray(0, 256));
    const decrypt = createDecipheriv('aes-256-gcm', aes, sealed.subarray(256, 268));
    decrypt.setAAD(Buffer.from(handoff));
    decrypt.setAuthTag(sealed.subarray(-16));
    const assertion = JSON.parse(Buffer.concat([
      decrypt.update(sealed.subarray(268, -16)), decrypt.final()
    ]).toString()) as object;
    const applied = await supportPost(reviewPage, base + '/apply', assertion);
    expect(applied.status).toBe(200);
    await reopen('Open');
    await approveAction(targetPage, await proposeAction('project_add', 'Project reference', caseProject), caseProject);
    await reopen('Open');
    await approveAction(targetPage, await proposeAction('project_remove', 'Project reference', caseProject), caseProject);
    await reopen('Open');
    await approveAction(targetPage, await proposeAction('subject_set', 'Account reference', caseUser), caseUser);
    await reviewPage.goto(supportOrigin + '/#/support');
    const directory = targetPage.getByRole('region', { name: 'Case account' });
    await directory.getByLabel('Case ID for account lookup').fill(caseId);
    await directory.getByLabel('Match approved account by').selectOption('name');
    await directory.getByLabel('Account search value').fill('Unrelated person');
    await directory.getByRole('button', { name: 'Look up case account' }).click();
    await expect(directory.getByRole('alert')).toContainText('The approved case account could not be loaded.');
    await directory.getByLabel('Account search value').fill('Case Employee');
    await directory.getByRole('button', { name: 'Look up case account' }).click();
    const masked = directory.getByRole('region', { name: 'Masked account details' });
    await expect(masked.getByText('e***@example.com')).toBeVisible();
    await directory.getByLabel('Match approved account by').selectOption('reference');
    await directory.getByRole('button', { name: 'Look up case account' }).click();
    await expect(masked).not.toContainText('555-private-fixture');
    await expect(masked.getByText('Sign-in locked')).toBeVisible();
    await expect(masked.getByText('Recovery destination verified')).toBeVisible();

    await masked.getByLabel('Business account action').selectOption('unlock');
    await masked.getByLabel('Operational reason').fill('Synthetic employee reported a failed sign-in.');
    await masked.getByRole('button', { name: 'Request reviewed account action' }).click();
    const businessAction = (await masked.getByLabel('New account action reference').innerText()).trim();
    const recoveryStatus = targetPage.getByRole('region', { name: 'Recovery status' });
    await recoveryStatus.getByLabel('Case ID for recovery status').fill(caseId);
    await recoveryStatus.getByLabel('Recovery action reference').fill(businessAction);
    await recoveryStatus.getByRole('button', { name: 'Check recovery status' }).click();
    await expect(recoveryStatus.getByRole('alert')).toHaveText(
      'Recovery status is unavailable for this case and action.'
    );
    await expect(requestPage.getByLabel(/Verified offline owner-contact reference/)).toBeVisible();
    await expect(targetPage.getByLabel(/Verified offline owner-contact reference/)).toHaveCount(0);
    const accountDecision = async (
      page: Page, stage: 'review' | 'execute', action: string, label: string, subject = caseUser
    ) => {
      const section = page.getByRole('region', { name: 'Review account action' });
      await section.getByLabel('Case ID for account action').fill(caseId);
      await section.getByLabel('Account action reference', { exact: true }).fill(action);
      await section.getByLabel('Account action stage').selectOption(stage);
      await section.getByRole('button', { name: 'Load account action' }).click();
      const confirmation = section.getByRole('region', { name: 'Confirm account action' });
      await expect(confirmation).toContainText(label);
      await expect(confirmation).toContainText(subject);
      await confirmation.getByRole('button', { name: stage === 'review'
        ? 'Approve account action with passkey' : 'Execute account action with passkey' }).click();
      await expect(section.getByText(stage === 'review'
        ? 'Independent account review recorded.' : label === 'Queue account recovery'
          ? 'Recovery queued. Delivery is pending.' : 'Account action applied.')).toBeVisible();
    };
    await accountDecision(requestPage, 'review', businessAction, 'Clear failed sign-in lock');
    await accountDecision(targetPage, 'execute', businessAction, 'Clear failed sign-in lock');
    const audit = targetPage.getByRole('region', { name: 'Case audit' });
    await audit.getByLabel('Case ID for audit').fill(caseId);
    await audit.getByRole('button', { name: 'Read case audit' }).click();
    await expect(audit.getByText('account decision · applied')).toBeVisible();
    await expect(audit).not.toContainText(caseUser);
    await directory.getByRole('button', { name: 'Look up case account' }).click();
    await expect(masked.getByText('hr executive reader', { exact: false })).toBeVisible();
    await expect(masked.getByText('Sign-in locked')).toHaveCount(0);
    for (const [kind, label, status] of [
      ['disable', 'Disable business sign-in', 'Inactive'],
      ['reactivate', 'Reactivate business sign-in', 'Active']
    ]) {
      await masked.getByLabel('Business account action').selectOption(kind);
      await masked.getByLabel('Operational reason').fill('Synthetic access authorization exercise.');
      await masked.getByRole('button', { name: 'Request reviewed account action' }).click();
      const action = (await masked.getByLabel('New account action reference').innerText()).trim();
      await accountDecision(requestPage, 'review', action, label);
      await accountDecision(targetPage, 'execute', action, label);
      await directory.getByRole('button', { name: 'Look up case account' }).click();
      await expect(masked.getByText('hr executive reader · ' + status, { exact: true })).toBeVisible();
    }
    await masked.getByLabel('Business account action').selectOption('permission_view');
    await masked.getByLabel('Business permission key').fill('projects:read');
    await masked.getByLabel('Operational reason').fill('Synthetic case permission triage exercise.');
    await masked.getByRole('button', { name: 'Request reviewed account action' }).click();
    const permissionAction = (await masked.getByLabel('New account action reference').innerText()).trim();
    await accountDecision(requestPage, 'review', permissionAction, 'Explain a role permission');
    await accountDecision(targetPage, 'execute', permissionAction, 'Explain a role permission');
    const view = targetPage.getByRole('region', { name: 'Reviewed support view' });
    await view.getByLabel('Approved support view reference').fill(permissionAction);
    await view.getByRole('button', { name: 'Load support view' }).click();
    await expect(view.getByText('Absent from the account role')).toBeVisible();
    await expect(view.getByText('projects:read', { exact: true })).toBeVisible();
    await view.getByRole('button', { name: 'End support view' }).click();
    await expect(view.getByText('Support view ended.')).toBeVisible();
    await expect(view.getByText('Absent from the account role')).toHaveCount(0);
    await masked.getByLabel('Business account action').selectOption('navigation_view');
    await masked.getByLabel('Operational reason').fill('Synthetic navigation triage exercise.');
    await masked.getByRole('button', { name: 'Request reviewed account action' }).click();
    const navigationAction = (await masked.getByLabel('New account action reference').innerText()).trim();
    await accountDecision(requestPage, 'review', navigationAction, 'Inspect portal navigation');
    await accountDecision(targetPage, 'execute', navigationAction, 'Inspect portal navigation');
    await view.getByLabel('View type').selectOption('navigation');
    await view.getByLabel('Approved support view reference').fill(navigationAction);
    await view.getByRole('button', { name: 'Load support view' }).click();
    const menu = view.getByRole('list', { name: 'Portal menu visibility' });
    await expect(menu.getByText('documents Visible', { exact: true })).toBeVisible();
    await expect(menu.getByText('projects Hidden', { exact: true })).toBeVisible();
    await expect(menu.getByRole('link')).toHaveCount(0);
    await view.getByRole('button', { name: 'End support view' }).click();
    await expect(view.getByText('Support view ended.')).toBeVisible();
    await masked.getByLabel('Business account action').selectOption('recover');
    await masked.getByLabel('Operational reason').fill('Synthetic recovery authorisation exercise.');
    await masked.getByRole('button', { name: 'Request reviewed account action' }).click();
    const recoveryAction = (await masked.getByLabel('New account action reference').innerText()).trim();
    await accountDecision(requestPage, 'review', recoveryAction, 'Queue account recovery');
    await accountDecision(targetPage, 'execute', recoveryAction, 'Queue account recovery');
    await recoveryStatus.getByLabel('Recovery action reference').fill(recoveryAction);
    await recoveryStatus.getByRole('button', { name: 'Check recovery status' }).click();
    await expect(recoveryStatus.getByText('Delivery Queued')).toBeVisible();
    await expect(recoveryStatus.getByText('Reset Waiting for delivery')).toBeVisible();
    await expect(recoveryStatus).not.toContainText('@example.com');
    await reopen('Open');
    await details.getByRole('button', { name: 'Start investigation' }).click();
    await expect(details.getByText('Investigating', { exact: true })).toBeVisible();

    const seedEvent = (source = randomUUID().replace(/-/g, '')) => execFileSync(env.BROWSER_TEST_PYTHON ?? 'python', ['-c', `
from tests.browser_fixtures import configure
configure()
import asyncio
from uuid import UUID, uuid4
from app.database import AsyncSessionLocal
from app.models.activity_log import ActivityLog
from app.utils.security import utc_now

async def seed():
    event = uuid4()
    async with AsyncSessionLocal() as session:
        session.add(ActivityLog(id=event, request_id="${source}", entity_type="request",
            user_id=UUID("${caseUser}"), endpoint="/private/synthetic-path",
            action="http.request", http_method="GET", status_code=200, created_at=utc_now()))
        await session.commit()
    return event
print(asyncio.run(seed()))
`], { cwd: backend, encoding: 'utf8' }).trim();
    const source = randomUUID().replace(/-/g, '');
    const event = seedEvent(source);
    await approveAction(targetPage, await proposeAction('evidence_link', 'Source event reference', event), event);
    await reopen('Investigating');
    const requestExport = requestPage.getByRole('region', { name: 'Evidence export' });
    const reviewExport = targetPage.getByRole('region', { name: 'Evidence export' });
    await requestExport.getByLabel('Export case reference').fill(caseId);
    await requestExport.getByLabel('Linked request ID').fill(source);
    await requestExport.getByRole('button', { name: 'Request evidence export' }).click();
    await expect(requestExport.getByRole('status')).toContainText('Export requested');
    const exportId = (await requestExport.locator('dd').first().innerText()).trim();
    await reviewExport.getByLabel('Reviewed case reference').fill(caseId);
    await reviewExport.getByLabel('Existing export reference').fill(exportId);
    await reviewExport.getByRole('button', { name: 'Show export details' }).click();
    await expect(reviewExport.getByText(source, { exact: true })).toBeVisible();
    const digest = (await reviewExport.locator('dd').last().innerText()).trim();
    await reviewExport.getByRole('button', { name: 'Approve export with passkey' }).click();
    await expect(reviewExport.getByRole('status')).toContainText('Independent approval recorded');
    await requestExport.getByLabel('Reviewed case reference').fill(caseId);
    await requestExport.getByLabel('Existing export reference').fill(exportId);
    await requestExport.getByLabel('Export action').selectOption('download');
    await requestExport.getByRole('button', { name: 'Show export details' }).click();
    const transfer = requestPage.waitForEvent('download');
    await requestExport.getByRole('button', { name: 'Download once with passkey' }).click();
    const preparedFile = await transfer;
    const file = readFileSync((await preparedFile.path())!);
    expect(createHash('sha256').update(file).digest('hex')).toBe(digest);
    expect(file.toString('utf8')).not.toContain('/private/synthetic-path');
    await expect(requestExport.getByRole('status')).toContainText('one-use download has been consumed');
    await requestExport.getByRole('button', { name: 'Show export details' }).click();
    await expect(requestExport.getByRole('alert')).toContainText('This export is unavailable');
    await directory.getByRole('button', { name: 'Look up case account' }).click();
    await masked.getByLabel('Business account action').selectOption('request_summary');
    await masked.getByLabel('Reviewed request event reference').fill(event);
    await masked.getByLabel('Operational reason').fill('Synthetic request summary review.');
    await masked.getByRole('button', { name: 'Request reviewed account action' }).click();
    const requestView = (await masked.getByLabel('New account action reference').innerText()).trim();
    await accountDecision(requestPage, 'review', requestView, 'Summarize a linked request');
    await accountDecision(targetPage, 'execute', requestView, 'Summarize a linked request');
    await view.getByLabel('View type').selectOption('request-summary');
    await view.getByLabel('Approved support view reference').fill(requestView);
    await view.getByRole('button', { name: 'Load support view' }).click();
    await expect(view.getByText('HTTP GET 200')).toBeVisible();
    await expect(view).not.toContainText('/private/synthetic-path');
    await view.getByRole('button', { name: 'End support view' }).click();
    await expect(view.getByText('Support view ended.')).toBeVisible();
    await approveAction(targetPage,
      await proposeAction('project_add', 'Project reference', caseProject), caseProject);
    await reopen('Investigating');
    await approveAction(targetPage,
      await proposeAction('subject_set', 'Account reference', projectUser), projectUser);
    await reopen('Investigating');
    await directory.getByLabel('Approved account reference').fill(projectUser);
    await directory.getByRole('button', { name: 'Look up case account' }).click();
    await expect(masked.getByText('Approved case project memberships')).toBeVisible();
    for (const [kind, adapter, label] of [
      ['project_list', 'project-list', 'Inspect masked project list'],
      ['project_detail', 'project-detail-summary', 'Inspect masked project detail']
    ]) {
      await masked.getByLabel('Business account action').selectOption(kind);
      if (kind === 'project_detail') {
        await masked.getByLabel('Approved case project reference').fill(caseProject);
      }
      await masked.getByLabel('Operational reason').fill('Synthetic project scope exercise.');
      await masked.getByRole('button', { name: 'Request reviewed account action' }).click();
      const projectView = (await masked.getByLabel('New account action reference').innerText()).trim();
      await accountDecision(requestPage, 'review', projectView, label, projectUser);
      await accountDecision(targetPage, 'execute', projectView, label, projectUser);
      await view.getByLabel('View type').selectOption(adapter);
      await view.getByLabel('Approved support view reference').fill(projectView);
      await view.getByRole('button', { name: 'Load support view' }).click();
      await expect(view.getByText('Project 01 · planning', { exact: true })).toBeVisible();
      await expect(view).not.toContainText('Private synthetic project');
      await expect(view).not.toContainText(caseProject);
      if (kind === 'project_detail') {
        await expect(view.getByText('Milestones 0 · Tasks 0', { exact: true })).toBeVisible();
      }
      await view.getByRole('button', { name: 'End support view' }).click();
      await expect(view.getByText('Support view ended.')).toBeVisible();
    }
    await openWorkspace(targetPage, 'People & Access');
    const people = targetPage.getByRole('region', { name: 'People and access directory' });
    await people.getByLabel('Search accounts').fill('Synthetic Project Manager');
    await people.getByRole('button', { name: 'Search directory' }).click();
    await people.getByRole('button', { name: 'Open User 360' }).first().click();
    await targetPage.getByRole('button', { name: 'View as User', exact: true }).click();
    const previewRequest = targetPage.getByRole('region', { name: 'Request read-only portal preview' });
    await previewRequest.getByLabel('Support case').selectOption(caseId);
    await previewRequest.getByLabel('Investigation reason').fill('Reproduce restricted project navigation.');
    await previewRequest.getByRole('button', { name: 'Request reviewed preview' }).click();
    await expect(previewRequest.getByRole('status')).toContainText('An independent operator must review');
    const actionReference = await previewRequest.getByLabel('Account action reference', { exact: true }).inputValue();
    await accountDecision(requestPage, 'review', actionReference, 'View as User (read-only)', projectUser);
    await previewRequest.getByRole('button', { name: 'Load account action' }).click();
    await previewRequest.getByRole('button', { name: 'Execute account action with passkey' }).click();

    const previewBanner = targetPage.getByRole('banner', { name: 'Read-only support session' });
    await expect(previewBanner).toContainText('Viewing as: Synthetic Project Manager');
    await expect(previewBanner).toContainText(reference);
    const previewNav = targetPage.getByRole('navigation', { name: 'Preview navigation' });
    await previewNav.getByRole('button', { name: 'Projects', exact: true }).click();
    await targetPage.getByRole('button', { name: 'Project 01', exact: true }).click();
    await expect(targetPage.getByText('Milestones 0 · Tasks 0')).toBeVisible();
    await expect(previewBanner).toBeVisible();
    await expect(targetPage.getByText('Private synthetic project')).toHaveCount(0);
    expect(await targetPage.evaluate(async (id) => (
      await fetch('/api/v1/support/portal-preview/' + id, {
        method: 'PATCH', headers: { 'Content-Type': 'application/json' }, body: '{}'
      })
    ).status, actionReference)).toBe(403);
    await previewBanner.getByRole('button', { name: 'Exit User View' }).click();
    await expect(targetPage.getByRole('region', { name: 'User 360 profile' })).toBeVisible();
    await openWorkspace(targetPage, 'Support & Audit');
    await reopen('Investigating');

    await approveAction(targetPage,
      await proposeAction('subject_set', 'Account reference', caseUser), caseUser);
    await reopen('Investigating');
    await details.getByRole('button', { name: 'Mark mitigated' }).click();
    await reopen('Mitigated');
    const mitigationEvent = seedEvent();
    await approveAction(targetPage,
      await proposeAction('evidence_link', 'Source event reference', mitigationEvent), mitigationEvent);
    await reopen('Mitigated');
    await approveAction(targetPage,
      await proposeAction('verify', 'Source event reference', mitigationEvent), 'HTTP 200');
    await reopen('Verified');
    await approveAction(targetPage, await proposeAction('close'), 'Close verified case');
    await reopen('Closed');
    await targetPage.reload();
    await targetPage.getByRole('button', { name: reference + ' · Closed' }).click();
    const timeline = targetPage.getByRole('region', { name: 'Case timeline' });
    await timeline.getByRole('button', { name: 'Load case timeline' }).click();
    await expect(timeline.getByText('Resolution verified · verified')).toBeVisible();
    await expect(timeline).toContainText('HTTP 200');
  } finally {
    await Promise.all([requestPage.close(), reviewPage.close(), targetPage.close(),
      firstDevice.close(), secondDevice.close()]);
  }
});

test('technical oversight dashboard, monitors, policy explainer, and sign-out cleanup', async ({
  page
}) => {
  const fixture = JSON.parse(execFileSync(
    env.BROWSER_TEST_PYTHON ?? 'python',
    ['-c', `
from tests.browser_fixtures import configure
configure()
import asyncio
import json
from base64 import b64encode
from cryptography.hazmat.primitives import serialization
from tests.test_support_identity import seed_operator
from app.database import AsyncSessionLocal
from app.models.support_cases import SupportOperatorGrant

async def seed():
    operator, credential, key = await seed_operator()
    async with AsyncSessionLocal() as session:
        for cap in (
            "overview.company.read",
            "overview.workforce.read",
            "overview.finance.read",
            "jobs.read",
            "backups.read",
            "config.read",
            "incidents.read",
            "simulation.start",
        ):
            session.add(SupportOperatorGrant(operator_id=operator, capability=cap))
        await session.commit()
    return operator, credential, key

operator, credential, key = asyncio.run(seed())
print(json.dumps({
    "operator": str(operator),
    "credential": b64encode(credential).decode(),
    "handle": b64encode(operator.bytes).decode(),
    "key": b64encode(key.private_bytes(
        serialization.Encoding.DER,
        serialization.PrivateFormat.PKCS8,
        serialization.NoEncryption(),
    )).decode(),
}))
`],
    { cwd: backend, encoding: 'utf8' }
  )) as OperatorFixture;

  await setupOperator(page, fixture);
  await signIn(page, fixture.operator);

  const snapshot = page.getByRole('region', { name: 'Operations overview' });
  await expect(snapshot.getByRole('region', { name: 'Business workflow' })).toContainText('Active projects');
  await expect(snapshot.getByRole('region', { name: 'Dependencies' })).toHaveCount(0);
  await expect(snapshot.getByRole('region', { name: 'Backup readiness' })).toContainText('Isolated restore');
  await expect(snapshot.getByRole('region', { name: 'Runtime configuration' })).toContainText('Audit retention');
  await page.route('**/api/v1/support/incidents/summary?hours=24', (route) => route.fulfill({ status: 429 }));
  await snapshot.getByRole('button', { name: 'Refresh snapshot' }).click();
  await expect(snapshot.getByRole('region', { name: 'Security signals' })).toContainText('Read limit reached');
  await expect(snapshot.getByRole('region', { name: 'Job delivery' })).toContainText('Failed outbox entries');
  await page.unroute('**/api/v1/support/incidents/summary?hours=24');
  await page.setViewportSize({ width: 390, height: 844 });
  expect(await page.evaluate(() => document.documentElement.scrollWidth)).toBeLessThanOrEqual(390);
  await snapshot.getByRole('button', { name: 'Analyze business domains' }).focus();
  await page.keyboard.press('Enter');
  await expect(page).toHaveURL(/#\/operations\/analytics$/);
  await page.goBack();
  await expect(snapshot).toBeVisible();
  await page.goForward();
  await expect(page).toHaveURL(/#\/operations\/analytics$/);
  await page.reload();
  await expect(page.locator('#tool-analytics')).toBeFocused();
  await page.setViewportSize({ width: 1280, height: 800 });

  const overview = page.getByRole('region', { name: 'Enterprise oversight' });
  await overview.getByRole('button', { name: 'Load company overview' }).click();
  await expect(overview).toContainText('Source status: operational');
  await overview.getByRole('tab', { name: 'Workforce' }).click();
  await overview.getByRole('button', { name: 'Load workforce overview' }).click();
  await expect(overview).toContainText('Small-cell privacy threshold: counts below 5 are suppressed.');
  await overview.getByRole('tab', { name: 'Finance' }).click();
  await overview.getByRole('button', { name: 'Load finance overview' }).click();
  await expect(overview).toContainText('Finance writes policy: blocked');

  const jobs = page.getByRole('region', { name: 'Jobs and scheduler monitor' });
  await jobs.getByRole('button', { name: 'Check job status' }).click();
  await expect(jobs).toContainText('dispatch_task_outbox');

  await openWorkspace(page, 'Recovery');
  const backups = page.getByRole('region', { name: 'Backup and recovery provenance' });
  await backups.getByRole('button', { name: 'Check recovery posture' }).click();
  await expect(backups).toContainText('Overall recovery posture');

  await openWorkspace(page, 'Settings');
  const config = page.getByRole('region', { name: 'Safe runtime configuration status' });
  await config.getByRole('button', { name: 'Check configuration posture' }).click();
  await expect(config).toContainText('Audit purge disabled');

  await openWorkspace(page, 'Support & Audit');
  const incidents = page.getByRole('region', { name: 'Security incidents summary' });
  await incidents.getByRole('button', { name: 'Load incident summary' }).click();
  await expect(incidents).toContainText('Support authentication failures');

  const policy = page.getByRole('region', { name: 'Role policy explainer' });
  await policy.getByLabel('Role').selectOption('hr_executive_reader');
  await policy.getByLabel('Permission key').fill('reports:view');
  await policy.getByRole('button', { name: 'Explain policy rule' }).click();
  await expect(policy).toContainText('HR Executive (reports:view): Allowed');

  await page.getByRole('button', { name: 'Sign out' }).click();
  await expect(page.getByRole('button', { name: 'Sign in with a passkey' })).toBeVisible();
  await expect(page.getByRole('region', { name: 'Enterprise oversight' })).toHaveCount(0);
});

test('single owner confirms a protected account action only in the proposing session', async ({ browser }) => {
  test.skip(env.SUPPORT_CUSTODY_MODE !== 'single_owner', 'Run against a dedicated single-owner browser database.');
  const [first, second, caseId, subject] = JSON.parse(execFileSync(
    env.BROWSER_TEST_PYTHON ?? 'python',
    ['-c', `
from tests.browser_fixtures import configure
configure()
import asyncio
import cbor2
import json
from datetime import timedelta
from base64 import b64encode
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import ec
from hashlib import sha256
from uuid import uuid4
from app.database import AsyncSessionLocal
from app.models.support_cases import SupportCase, SupportCaseMember, SupportOperatorGrant
from app.models.support_directory import SupportCaseSubject
from app.models.support_identity import SupportCredential
from app.models.support_registration import SupportBootstrap
from app.models.user import User
from app.utils.permissions import ROLE_MANAGING_DIRECTOR
from app.utils.security import utc_now
from tests.test_support_identity import seed_operator

async def seed():
    owner, credential, key = await seed_operator()
    other_credential, other_key = uuid4().bytes, ec.generate_private_key(ec.SECP256R1())
    numbers = other_key.public_key().public_numbers()
    case, subject = uuid4(), uuid4()
    async with AsyncSessionLocal() as session:
        session.add(SupportCredential(
            id=uuid4(), operator_id=owner, credential_hash=sha256(other_credential).hexdigest(),
            public_key=cbor2.dumps({
                1: 2, 3: -7, -1: 1, -2: numbers.x.to_bytes(32), -3: numbers.y.to_bytes(32),
            }), sign_count=0,
        ))
        session.add(SupportBootstrap(
            id=1, first_id=owner, custody_mode="single_owner", approval_digest="a" * 64,
            started_at=utc_now(), activated_at=utc_now(),
        ))
        session.add(SupportCase(
            id=case, owner_id=owner, status="open", severity="medium",
            external_ref=f"chrome-owner-{case}", reason_code="access",
        ))
        session.add(User(
            id=subject, email="director-fixture@example.test", full_name="Synthetic Director",
            role=ROLE_MANAGING_DIRECTOR, is_active=True, failed_login_attempts=3,
            locked_until=utc_now() + timedelta(minutes=10),
        ))
        await session.flush()
        session.add(SupportCaseSubject(case_id=case, user_id=subject))
        session.add(SupportCaseMember(case_id=case, operator_id=owner))
        for capability in ("cases.manage", "directory.read", "account.request"):
            session.add(SupportOperatorGrant(operator_id=owner, capability=capability))
        await session.commit()
    fixtures = [{
        "operator": str(owner), "credential": b64encode(identifier).decode(),
        "handle": b64encode(owner.bytes).decode(),
        "key": b64encode(private_key.private_bytes(
            serialization.Encoding.DER, serialization.PrivateFormat.PKCS8,
            serialization.NoEncryption(),
        )).decode(),
    } for identifier, private_key in ((credential, key), (other_credential, other_key))]
    return [*fixtures, str(case), str(subject)]

print(json.dumps(asyncio.run(seed())))
`],
    { cwd: backend, encoding: 'utf8' }
  )) as [OperatorFixture, OperatorFixture, string, string];
  const [ownerPage, otherPage] = await Promise.all([browser.newPage(), browser.newPage()]);
  try {
    await setupOperator(ownerPage, first);
    await signIn(ownerPage, first.operator);
    await openWorkspace(ownerPage, 'Support & Audit');
    const directory = ownerPage.getByRole('region', { name: 'Case account' });
    await directory.getByLabel('Case ID for account lookup').fill(caseId);
    await directory.getByLabel('Match approved account by').selectOption('reference');
    await directory.getByLabel('Approved account reference (optional)').fill(subject);
    await directory.getByRole('button', { name: 'Look up case account' }).click();
    const account = directory.getByRole('region', { name: 'Masked account details' });
    await expect(account.getByText('Sign-in locked')).toBeVisible();
    const propose = async (kind: 'disable' | 'unlock') => {
      const response = ownerPage.waitForResponse((reply) =>
        reply.url().endsWith('/account-actions') && reply.request().method() === 'POST');
      await account.getByLabel('Business account action').selectOption(kind);
      await account.getByLabel('Operational reason').fill('Synthetic director account access incident.');
      await account.getByRole('button', { name: 'Request reviewed account action' }).click();
      const proposal = await response;
      expect(proposal.status()).toBe(201);
      const receipt = await proposal.json() as { id: string; authorization_mode: string };
      expect(receipt.authorization_mode).toBe('single_owner');
      return receipt.id;
    };
    const load = async (page: Page, action: string, status: number) => {
      const section = page.getByRole('region', { name: 'Review account action' });
      await section.getByLabel('Case ID for account action').fill(caseId);
      await section.getByLabel('Account action reference', { exact: true }).fill(action);
      await section.getByLabel('Account action stage').selectOption('execute');
      const reply = page.waitForResponse((response) => response.url().endsWith('/execute/options'));
      await section.getByRole('button', { name: 'Load account action' }).click();
      expect((await reply).status()).toBe(status);
      return section;
    };
    const disable = await propose('disable');
    await setupOperator(otherPage, second);
    await signIn(otherPage, second.operator);
    await openWorkspace(otherPage, 'Support & Audit');
    await expect((await load(otherPage, disable, 403)).getByRole('alert')).toBeVisible();

    const section = await load(ownerPage, disable, 200);
    await expect(section.getByText(/in the session that proposed it/)).toBeVisible();
    const execute = section.getByRole('button', { name: 'Execute account action with passkey' });
    const reply = ownerPage.waitForResponse((response) => response.url().endsWith('/execute'));
    await execute.click();
    const blocked = await reply;
    expect(blocked.status()).toBe(409);
    await expect(section.getByRole('alert')).toBeVisible();

    await load(ownerPage, await propose('unlock'), 200);
    await execute.click();
    await expect(section.getByText('Account action applied.')).toBeVisible();
    await directory.getByRole('button', { name: 'Look up case account' }).click();
    await expect(account.getByRole('heading', { name: 'Synthetic Director' })).toBeVisible();
    await expect(account.getByText('Sign-in locked')).toHaveCount(0);
  } finally {
    await Promise.all([ownerPage.close(), otherPage.close()]);
  }
});
