import { renderToString } from 'react-dom/server';
import { describe, expect, it, vi } from 'vitest';

import { SupportLoginPage } from '../admin/SupportLoginPage';
import { SupportBackupsPanel } from './SupportBackupsPanel';
import { SupportConfigPanel } from './SupportConfigPanel';
import { SupportIncidentsPanel } from './SupportIncidentsPanel';
import { SupportJobsPanel } from './SupportJobsPanel';
import { SupportOverviewPanel } from './SupportOverviewPanel';
import { SupportOwnerSecurityPanel } from './SupportOwnerSecurityPanel';
import { SupportPolicyExplainPanel } from './SupportPolicyExplainPanel';
import { SupportSafeSettingsPanel } from './SupportSafeSettingsPanel';
import { SupportShell } from './SupportShell';
import { SupportUsersPage } from './SupportUsersPage';
import { formatMetricValue } from './supportPanelUtils';

describe('support oversight UI helpers and gating', () => {
  it('formats metric states honestly without fabricating zero values', () => {
    expect(
      formatMetricValue({
        key: 'w',
        label: 'Workforce',
        value: null,
        state: 'suppressed',
        source: 'hr_employees',
        note: null
      })
    ).toBe('Suppressed (< 5 threshold)');
    expect(
      formatMetricValue({
        key: 'c',
        label: 'Company',
        value: null,
        state: 'unavailable',
        source: 'database',
        note: null
      })
    ).toBe('Unavailable');
    expect(
      formatMetricValue({
        key: 'p',
        label: 'Projects',
        value: 0,
        state: 'observed',
        source: 'projects',
        note: null
      })
    ).toBe('0');
  });

  it('hides overview panel when no overview capabilities are granted', () => {
    const html = renderToString(
      <SupportOverviewPanel capabilities={['health.read']} onExpired={vi.fn()} />
    );
    expect(html).toBe('');
  });

  it('renders only granted domain tabs and never mounts dangerous write buttons', () => {
    const html = renderToString(
      <>
        <SupportOverviewPanel
          capabilities={['overview.company.read', 'overview.finance.read']}
          onExpired={vi.fn()}
        />
        <SupportJobsPanel onExpired={vi.fn()} />
        <SupportBackupsPanel onExpired={vi.fn()} />
        <SupportConfigPanel onExpired={vi.fn()} />
        <SupportIncidentsPanel onExpired={vi.fn()} />
        <SupportPolicyExplainPanel onExpired={vi.fn()} />
      </>
    );

    expect(html).toContain('Company');
    expect(html).toContain('Finance');
    expect(html).not.toContain('Workforce');
    expect(html).not.toContain('Suppliers');
    expect(html).toContain('Check job status');
    expect(html).toContain('Check recovery posture');
    expect(html).toContain('Check configuration posture');
    expect(html).toContain('Load incident summary');
    expect(html).toContain('Explain policy rule');
    expect(html).toContain('value="report"');
    expect(html).toContain('value="image"');
    expect(html).not.toContain('Restore backup');
    expect(html).not.toContain('Retry job');
    expect(html).not.toContain('Save config');
  });

  it('renders unauthenticated sign-in screen without leaking operational panels', () => {
    const html = renderToString(<SupportLoginPage />);
    expect(html).toContain('Garrisons Super Admin');
    expect(html).toContain('Sign in with a passkey');
    expect(html).not.toContain('Enterprise oversight');
  });

  it('renders Company Control Centre shell with 7 task-oriented navigation sections', () => {
    const html = renderToString(
      <SupportShell
        session={{
          operator_id: '00000000-0000-0000-0000-000000000001',
          expires_at: '2026-11-20T18:00:00Z',
          capabilities: ['company.directory.read', 'overview.company.read']
        }}
        pending={false}
        onSignOut={vi.fn()}
        onExpired={vi.fn()}
      />
    );
    expect(html).toContain('Company Control Centre');
    expect(html).toContain('Single-company deployment');
    expect(html).toContain('Overview');
    expect(html).toContain('People &amp; Access');
    expect(html).toContain('Projects &amp; Operations');
    expect(html).toContain('Support &amp; Audit');
    expect(html).toContain('Recovery');
    expect(html).toContain('Settings');
    expect(html).toContain('Owner Security');
    expect(html).toContain('Business workflow');
    expect(html).toContain('Inspect account access');
    expect(html).not.toContain('Dependencies');
    expect(html).not.toContain('Prepare a job retry');
    expect(html).not.toContain('Enterprise oversight');
  });

  it('enforces capability gates on People & Access directory and safe settings editor', () => {
    const deniedHtml = renderToString(
      <SupportUsersPage
        capabilities={['directory.read']}
        selectedUserId={null}
        onSelectUser={vi.fn()}
        onExpired={vi.fn()}
      />
    );
    expect(deniedHtml).toContain('company.directory.read');
    expect(deniedHtml).not.toContain('Search directory');

    const grantedHtml = renderToString(
      <SupportUsersPage
        capabilities={['company.directory.read', 'company.accounts.manage']}
        selectedUserId={null}
        onSelectUser={vi.fn()}
        onExpired={vi.fn()}
      />
    );
    expect(grantedHtml).toContain('People &amp; Access Directory');
    expect(grantedHtml).toContain('+ Create or invite user');

    const settingsHtml = renderToString(
      <SupportSafeSettingsPanel canManage={false} onExpired={vi.fn()} />
    );
    expect(settingsHtml).toContain('Allowlisted non-secret operational settings');

    const securityHtml = renderToString(
      <SupportOwnerSecurityPanel canManageOperators={false} onExpired={vi.fn()} />
    );
    expect(securityHtml).toContain('Owner Security &amp; Enrolled Devices');
  });
});
