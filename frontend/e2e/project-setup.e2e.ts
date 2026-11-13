import { execFileSync } from 'node:child_process';
import { randomUUID } from 'node:crypto';
import { env } from 'node:process';
import { fileURLToPath } from 'node:url';

import { expect, test, type Page } from '@playwright/test';

type TestAccount = { email: string; password: string };
const backendDirectory = fileURLToPath(new URL('../../backend/', import.meta.url));

function seedAdministrator(): TestAccount {
  return JSON.parse(
    execFileSync(env.BROWSER_TEST_PYTHON ?? 'python', ['-m', 'tests.browser_fixtures', 'seed'], {
      cwd: backendDirectory,
      encoding: 'utf8'
    })
  );
}

async function signIn(page: Page, account: TestAccount): Promise<string> {
  await page.goto('/login');
  await page.getByLabel('Email', { exact: true }).fill(account.email);
  await page.getByLabel('Password', { exact: true }).fill(account.password);
  await page.getByRole('button', { name: 'Continue' }).click();
  const developmentCode = page.getByText(/^Development code:/);
  await expect(developmentCode).toBeVisible();
  const code = (await developmentCode.innerText()).match(/\d{6}/)?.[0];
  if (!code) throw new Error('The test API did not expose the verification code.');
  await page.getByLabel('Verification code').fill(code);
  const verification = page.waitForResponse(
    (response) => response.url().endsWith('/api/v1/auth/verify-otp') && response.ok()
  );
  await page.getByRole('button', { name: 'Verify and sign in' }).click();
  const { access_token } = (await (await verification).json()) as { access_token: string };
  return access_token;
}

async function openSetup(page: Page, name: string) {
  await page.getByRole('link', { name: 'Projects', exact: true }).click();
  await page.getByRole('button', { name: 'New project', exact: true }).click();
  await page.getByLabel('Project name', { exact: true }).fill(name);
  await page
    .getByLabel('Scope of work')
    .fill('Browser verification of the project setup workflow.');
  await page.getByLabel('Target end date').fill('2027-12-31');
}

test('minimal project setup recovers validation, persists a renamed milestone, and sends one create', async ({
  page
}) => {
  const errors: Error[] = [];
  page.on('pageerror', (error) => errors.push(error));
  await signIn(page, seedAdministrator());
  const name = `Minimal project ${randomUUID().slice(0, 8)}`;
  await openSetup(page, name);
  await page.getByLabel('Milestone name').fill('Renamed site preparation');
  await page.getByLabel('BOQ description').fill('Prepare the site');
  await page.getByLabel('Planned start').fill('2027-03-12');
  await page.getByLabel('Planned end').fill('2027-03-11');
  const create = page.getByRole('button', { name: 'Create project', exact: true });
  await create.click();
  await expect(page.getByText('End date precedes the start date.')).toBeVisible();
  await expect(page.getByLabel('Project name')).toHaveValue(name);
  await expect(page.getByLabel('BOQ description')).toHaveValue('Prepare the site');
  await page.getByLabel('Planned start').fill('');
  await page.getByLabel('Planned end').fill('');

  let creates = 0;
  page.on('request', (request) => {
    if (request.method() === 'POST' && request.url().endsWith('/api/v1/projects')) creates += 1;
  });
  const created = page.waitForResponse(
    (response) =>
      response.url().endsWith('/api/v1/projects') && response.request().method() === 'POST'
  );
  await create.evaluate((button: HTMLButtonElement) => {
    button.click();
    button.click();
  });
  expect((await created).status()).toBe(201);
  await expect(page.getByRole('heading', { name, exact: true })).toBeVisible();
  await page.reload();
  await page.getByRole('button', { name, exact: true }).click();
  const boq = page.getByRole('table', { name: 'Bill of quantities' });
  await expect(boq.getByRole('row').filter({ hasText: 'Prepare the site' })).toContainText(
    'Renamed site preparation'
  );
  expect(creates).toBe(1);
  expect(errors).toEqual([]);
});

test('project teams and task dates persist through reload at narrow and desktop widths', async ({
  browser,
  page,
  request,
  baseURL
}) => {
  test.setTimeout(70_000);
  const errors: Error[] = [];
  page.on('pageerror', (error) => errors.push(error));
  const token = await signIn(page, seedAdministrator());
  const headers = { Authorization: `Bearer ${token}` };
  const suffix = randomUUID().slice(0, 8);
  const name = `Project workflow ${suffix}`;
  await openSetup(page, name);

  for (const milestone of ['Structure', 'Finishes']) {
    await page.getByRole('button', { name: 'Add milestone' }).click();
    await page.getByLabel('Milestone name').last().fill(milestone);
  }
  for (let index = 0; index < 6; index += 1) {
    if (index) await page.getByRole('button', { name: 'Add BOQ item' }).click();
    const row = page.getByRole('group', { name: `BOQ item ${index + 1}`, exact: true });
    await row.getByLabel('Item code').fill(`ROW-${index}`);
    await row.getByLabel('BOQ description').fill(`Work item ${index}`);
    await row.getByLabel('Planned quantity').fill('1.105');
    await row.getByLabel('Unit rate').fill('4.60');
    await row
      .getByLabel('Linked milestone')
      .selectOption({ label: ['Mobilization', 'Structure', 'Finishes'][Math.floor(index / 2)] });
  }
  await page
    .getByRole('group', { name: 'BOQ item 6', exact: true })
    .getByRole('button', { name: 'Move up' })
    .click();
  await expect(
    page.getByRole('group', { name: 'BOQ item 5', exact: true }).getByLabel('BOQ description')
  ).toHaveValue('Work item 5');

  const created = page.waitForResponse(
    (response) => response.url().endsWith('/api/v1/projects') && response.status() === 201
  );
  await page.getByRole('button', { name: 'Create project', exact: true }).click();
  const project = (await (await created).json()) as { id: string; revision: number };
  const detail = page.getByRole('region', { name: 'Project details', exact: true });
  const boq = detail.getByRole('table', { name: 'Bill of quantities' });
  await expect(boq.getByRole('row')).toHaveCount(7);
  await expect(boq.getByRole('row').filter({ hasText: 'Work item 5' })).toContainText('Finishes');
  await expect(boq.getByRole('row').filter({ hasText: 'Work item 5' })).toContainText('5.08');

  const projectUrl = `/api/v1/projects/${project.id}`;
  const secondEditor = await browser.newPage({ baseURL });
  try {
    await signIn(secondEditor, seedAdministrator());
    await secondEditor.goto('/projects');
    await secondEditor.getByRole('button', { name, exact: true }).click();
    const editors = [page, secondEditor].map((editorPage, index) => ({
      page: editorPage,
      detail: editorPage.getByRole('region', { name: 'Project details', exact: true }),
      location: `Site office ${index + 1}`
    }));
    let releaseSaves!: () => void;
    const bothSavesReady = new Promise<void>((resolve) => {
      releaseSaves = resolve;
    });
    const revisions: number[] = [];
    for (const editor of editors) {
      await editor.detail.getByRole('button', { name: 'Edit project', exact: true }).click();
      await editor.detail.getByLabel('Location', { exact: true }).fill(editor.location);
      await editor.page.route(`**${projectUrl}`, async (route) => {
        if (route.request().method() !== 'PATCH') return route.continue();
        revisions.push(route.request().postDataJSON().expected_revision);
        if (revisions.length === editors.length) releaseSaves();
        await bothSavesReady;
        await route.continue();
      });
    }
    const saves = await Promise.all(
      editors.map(async (editor) => {
        const [response] = await Promise.all([
          editor.page.waitForResponse(
            (reply) =>
              reply.request().method() === 'PATCH' && new URL(reply.url()).pathname === projectUrl
          ),
          editor.detail.getByRole('button', { name: 'Save project', exact: true }).click()
        ]);
        await editor.page.unroute(`**${projectUrl}`);
        return { ...editor, response };
      })
    );
    expect(revisions).toEqual([project.revision, project.revision]);
    expect(saves.map(({ response }) => response.status()).sort()).toEqual([200, 409]);
    const winner = saves.find(({ response }) => response.status() === 200)!;
    const loser = saves.find(({ response }) => response.status() === 409)!;
    expect(await loser.response.json()).toMatchObject({ error_code: 'PROJECT_REVISION_CONFLICT' });
    await expect(loser.detail.getByRole('alert')).toContainText('This record changed.');
    await expect(loser.detail.getByLabel('Location', { exact: true })).toHaveValue(loser.location);
    await loser.detail.getByRole('button', { name: 'Compare saved details' }).click();
    await expect(loser.detail.getByText(winner.location, { exact: true })).toBeVisible();
    await expect(
      loser.detail.getByRole('button', { name: 'Save project', exact: true })
    ).toBeDisabled();
    const saved = await request.get(projectUrl, { headers });
    expect(saved.ok()).toBe(true);
    expect(await saved.json()).toMatchObject({
      location: winner.location,
      revision: project.revision + 1
    });
  } finally {
    await secondEditor.close();
  }
  await page.reload();
  await page.getByRole('button', { name, exact: true }).click();
  await detail.getByRole('button', { name: 'Edit project', exact: true }).click();
  await detail.getByLabel('Location', { exact: true }).fill('Site office');
  await detail.getByRole('button', { name: 'Save project', exact: true }).click();
  await expect(detail.getByText('Site office', { exact: true })).toBeVisible();

  const engineer = { email: `engineer-${suffix}@example.com`, password: 'BrowserFixture!2027' };
  const invited = await request.post('/api/v1/users', {
    headers,
    data: {
      email: engineer.email,
      temporary_password: engineer.password,
      full_name: `Assigned engineer ${suffix}`,
      role: 'civil_engineer',
      employee_code: `ENG-${suffix}`,
      phone: '5550123'
    }
  });
  expect(invited.status()).toBe(201);
  const engineerId = ((await invited.json()) as { id: string }).id;
  await detail.getByRole('button', { name: 'Team', exact: true }).click();
  await detail.getByLabel('Search team member options').fill(engineer.email);
  await expect(detail.getByRole('option', { name: new RegExp(engineer.email) })).toHaveCount(1);
  await detail.getByLabel('Team member', { exact: true }).selectOption(engineerId);
  await detail.getByLabel('Role in project').fill('Site engineer');
  await detail.getByRole('button', { name: 'Assign member', exact: true }).click();
  await expect(detail.getByText('Site engineer', { exact: false })).toBeVisible();

  await detail.getByRole('button', { name: 'Timeline', exact: true }).click();
  await detail.getByRole('button', { name: 'New task', exact: true }).click();
  await detail.getByLabel('Task name').fill('Prepare site');
  await detail.getByLabel('Baseline start').fill('2027-02-10');
  await detail.getByLabel('Baseline end').fill('2027-02-12');
  await detail.getByLabel('Planned start').fill('2027-02-11');
  await detail.getByLabel('Planned end').fill('2027-02-13');
  await detail.getByRole('button', { name: 'Add task', exact: true }).click();
  const editTask = detail.getByRole('button', { name: 'Edit task Prepare site' });
  await expect(editTask).toBeVisible();
  await page.setViewportSize({ width: 390, height: 844 });
  await editTask.focus();
  await page.keyboard.press('Enter');
  await detail.getByLabel('Actual start').fill('2027-02-14');
  await detail.getByLabel('Actual end').fill('2027-02-15');
  await detail.getByLabel('Progress %').fill('25');
  await detail.getByRole('button', { name: 'Save task', exact: true }).click();
  const chart = detail.getByRole('region', { name: 'Scrollable task Gantt chart' });
  await expect(chart.getByRole('img', { name: 'Actual 2027-02-14 to 2027-02-15' })).toBeVisible();
  expect(await chart.evaluate((node) => node.scrollWidth > node.clientWidth)).toBe(true);

  await page.reload();
  await page.getByRole('button', { name, exact: true }).click();
  await expect(detail.getByText('Site office', { exact: true })).toBeVisible();
  await detail.getByRole('button', { name: 'Team', exact: true }).click();
  await expect(detail.getByText('Site engineer', { exact: false })).toBeVisible();
  await detail.getByRole('button', { name: 'Timeline', exact: true }).click();
  await expect(
    detail
      .getByRole('table', { name: 'Project tasks' })
      .getByRole('row')
      .filter({ hasText: 'Prepare site' })
  ).toContainText('2027-02-14 to 2027-02-15');

  const engineerPage = await browser.newPage({ baseURL });
  try {
    await signIn(engineerPage, engineer);
    await engineerPage.getByRole('link', { name: 'Projects', exact: true }).click();
    await engineerPage.getByRole('button', { name, exact: true }).click();
    const engineerDetails = engineerPage.getByRole('region', { name: 'Project details' });
    await expect(engineerDetails.getByRole('heading', { name, exact: true })).toBeVisible();
    await expect(
      engineerDetails.getByRole('button', { name: 'Edit project', exact: true })
    ).toHaveCount(0);
    await engineerDetails.getByRole('button', { name: 'Timeline', exact: true }).click();
    await expect(engineerDetails.getByRole('table', { name: 'Project tasks' })).toContainText(
      'Prepare site'
    );
    await expect(
      engineerDetails.getByRole('button', { name: 'Edit task Prepare site' })
    ).toHaveCount(0);
  } finally {
    await engineerPage.close();
  }
  const persisted = await request.get(`/api/v1/projects/${project.id}/timeline`, { headers });
  expect(persisted.status()).toBe(200);
  expect((await persisted.json()).tasks[0]).toMatchObject({
    baseline_end_date: '2027-02-12',
    planned_end_date: '2027-02-13',
    actual_end_date: '2027-02-15',
    revision: 2
  });
  await detail.getByRole('button', { name: 'Overview', exact: true }).click();
  await detail.getByRole('button', { name: 'Edit project', exact: true }).click();
  await detail.getByLabel('Location', { exact: true }).fill('');
  await detail.getByLabel('Status', { exact: true }).selectOption('completed');
  const completed = page.waitForResponse(
    (reply) => reply.request().method() === 'PATCH' && new URL(reply.url()).pathname === projectUrl
  );
  await detail.getByRole('button', { name: 'Save project', exact: true }).click();
  const completion = await completed;
  expect(completion.status()).toBe(200);
  const closed = await completion.json();
  expect(closed).toMatchObject({ location: null, status: 'completed' });
  await page.reload();
  await page.getByRole('button', { name, exact: true }).click();
  await expect(detail.getByText('Completed and cancelled projects are read-only.')).toBeVisible();
  await expect(detail.getByRole('button', { name: 'Edit project', exact: true })).toHaveCount(0);
  const denied = await request.patch(projectUrl, {
    headers,
    data: { expected_revision: closed.revision, location: 'Unauthorized change to closed project' }
  });
  expect(denied.status()).toBe(409);
  expect(await denied.json()).toMatchObject({ error_code: 'PROJECT_READ_ONLY' });
  const reloaded = await request.get(projectUrl, { headers });
  expect(reloaded.ok()).toBe(true);
  expect(await reloaded.json()).toMatchObject({
    location: null,
    status: 'completed',
    is_read_only: true,
    revision: closed.revision
  });
  expect(errors).toEqual([]);
});
