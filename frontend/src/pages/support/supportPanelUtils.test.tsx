import { renderToString } from 'react-dom/server';
import { describe, expect, it, vi } from 'vitest';

import { SupportLoginPage } from '../admin/SupportLoginPage';
import { SupportBackupsPanel } from './SupportBackupsPanel';
import { SupportConfigPanel } from './SupportConfigPanel';
import { SupportIncidentsPanel } from './SupportIncidentsPanel';
import { SupportJobsPanel } from './SupportJobsPanel';
import { SupportOverviewPanel } from './SupportOverviewPanel';
import { SupportPolicyExplainPanel } from './SupportPolicyExplainPanel';
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
});
