import { execFileSync } from 'node:child_process';
import { env } from 'node:process';
import { fileURLToPath } from 'node:url';

import { expect, test } from '@playwright/test';

test('a managing director creates a user, changes their role, and sees the audit entry', async ({
  page
}) => {
  const director: { email: string; password: string } = JSON.parse(
    execFileSync(env.BROWSER_TEST_PYTHON ?? 'python', ['-m', 'tests.browser_fixtures', 'seed'], {
      cwd: fileURLToPath(new URL('../../backend/', import.meta.url)),
      encoding: 'utf8'
    })
  );

  await page.goto('/login');
  await page.getByLabel('Email', { exact: true }).fill(director.email);
  await page.getByLabel('Password', { exact: true }).fill(director.password);
  await page.getByRole('button', { name: 'Continue' }).click();
  const code = (await page.getByText(/^Development code:/).innerText()).match(/\d{6}/)?.[0];
  if (!code) throw new Error('The test API did not expose the verification code.');
  await page.getByLabel('Verification code').fill(code);
  await page.getByRole('button', { name: 'Verify and sign in' }).click();

  await page.getByRole('link', { name: 'Users', exact: true }).click();
  const email = director.email.replace('browser-', 'role-');
  await page.getByPlaceholder('Full name', { exact: true }).fill('Role Test User');
  await page.getByPlaceholder('Email', { exact: true }).fill(email);
  const role = page.getByRole('combobox', { name: 'Role for new user', exact: true });
  await expect(role).toBeVisible();
  await expect(role.getByRole('option', { name: 'Quantity Surveyor', exact: true })).toHaveCount(1);
  await role.selectOption('quantity_surveyor');
  await page.getByPlaceholder('Employee code').fill(email.split('@')[0]);
  await page.getByPlaceholder('Phone').fill('+97455550123');
  await page.getByPlaceholder('Temporary password').fill('BrowserFixture42!');
  const created = page.waitForResponse(
    (response) => response.url().endsWith('/api/v1/users') && response.request().method() === 'POST'
  );
  await page.getByRole('button', { name: 'Create user' }).click();
  const createResponse = await created;
  expect(createResponse.status()).toBe(201);
  const { id }: { id: string } = await createResponse.json();
  const searchUsers = page.getByPlaceholder('Search', { exact: true });
  const ownRow = page.getByRole('row').filter({ hasText: director.email });
  await searchUsers.fill(director.email);
  await expect(ownRow).toBeVisible();
  await expect(ownRow.getByRole('button', { name: 'Change role' })).toHaveCount(0);
  await expect(ownRow.getByRole('button', { name: 'Reset password' })).toHaveCount(0);
  await expect(ownRow.getByRole('button', { name: 'Deactivate' })).toHaveCount(0);

  const row = page.getByRole('row').filter({ hasText: email });
  await searchUsers.fill(email);
  await expect(row.getByRole('cell', { name: /Quantity Surveyor/ })).toBeVisible();

  await row.getByRole('button', { name: 'Change role' }).click({ timeout: 5_000 });
  await expect(row.getByRole('button', { name: 'Save role' })).toBeDisabled();
  await row.getByRole('combobox', { name: /New role/ }).selectOption('site_supervisor');
  await row.getByRole('button', { name: 'Cancel' }).click();
  await expect(row.getByRole('cell', { name: /Quantity Surveyor/ })).toBeVisible();

  await row.getByRole('button', { name: 'Change role' }).click();
  await row.getByRole('combobox', { name: /New role/ }).selectOption('site_supervisor');
  await row.getByRole('button', { name: 'Save role' }).click();
  await expect(
    page.getByRole('status').filter({ hasText: 'Role updated for Role Test User.' })
  ).toBeVisible();
  await expect(row.getByRole('cell', { name: /Site Supervisor/ })).toBeVisible();
  await page.reload();
  await searchUsers.fill(email);
  await expect(row.getByRole('cell', { name: /Site Supervisor/ })).toBeVisible();

  await page.getByRole('link', { name: 'Audit', exact: true }).click();
  await expect(
    page.getByRole('row').filter({ hasText: id }).getByText('users / updated', { exact: true })
  ).toBeVisible();

  const searchInput = page.getByPlaceholder('Action, entity, comment');
  const filtered = page.waitForResponse((response) => {
    const url = new URL(response.url());
    return url.pathname === '/api/v1/audit-logs' && url.searchParams.get('search') === 'users.updated';
  });
  await searchInput.fill('  users.updated  ');
  const filteredResponse = await filtered;
  expect(filteredResponse.ok()).toBe(true);
  const audit = (await filteredResponse.json()) as { items: Array<{ action: string; entity_id: string }> };
  expect(audit.items).toEqual(expect.arrayContaining([
    expect.objectContaining({ action: 'users.updated', entity_id: id })
  ]));
  await expect(
    page.getByRole('row').filter({ hasText: id }).getByText('users / updated', { exact: true })
  ).toBeVisible();
});
