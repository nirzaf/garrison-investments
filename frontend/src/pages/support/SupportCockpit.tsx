import {
  Settings2,
  Activity,
  ArrowUpRight,
  ChartNoAxesColumn,
  DatabaseBackup,
  ListTodo,
  RefreshCw,
  ShieldAlert
} from 'lucide-react';
import { useEffect, useState, type ReactNode } from 'react';

import type { components } from '../../api/schema';
import { supportRequest } from '../../api/support';
import type { SupportSectionKey } from './SupportShell';
import { formatMetricValue, formatObserved, statusLabel, type Metric } from './supportPanelUtils';

type Schemas = components['schemas'];
type Observation = { observed_at: string };
export type SupportTool =
  | 'analytics'
  | 'health'
  | 'jobs'
  | 'backups'
  | 'incidents'
  | 'configuration'
  | 'retry'
  | 'case-audit'
  | 'safe-settings';
type SnapshotState<T> =
  { status: 'loading' } | { status: 'ready'; data: T } | { status: 'error'; message: string };

const linkClass =
  'inline-flex min-h-11 items-center gap-2 rounded-md font-medium text-brand-600 underline-offset-4 hover:underline focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-brand-600 dark:text-brand-400';

function SnapshotCard<T extends Observation>({
  title,
  icon,
  path,
  onExpired,
  onOpen,
  linkLabel,
  children
}: {
  title: string;
  icon: ReactNode;
  path: string;
  onExpired: () => void;
  onOpen: () => void;
  linkLabel: string;
  children: (data: T) => ReactNode;
}) {
  const [state, setState] = useState<SnapshotState<T>>({ status: 'loading' });

  useEffect(() => {
    const controller = new AbortController();
    async function load() {
      try {
        const response = await supportRequest(path, { signal: controller.signal });
        if (controller.signal.aborted) return;
        if (response.status === 401) {
          onExpired();
          return;
        }
        if (response.status === 403 || response.status === 429) {
          setState({
            status: 'error',
            message:
              response.status === 403
                ? 'Your session cannot read this source.'
                : 'Read limit reached. Wait before refreshing.'
          });
          return;
        }
        if (!response.ok) throw new Error('Snapshot request failed');
        const data = (await response.json()) as T;
        if (!controller.signal.aborted) setState({ status: 'ready', data });
      } catch {
        if (!controller.signal.aborted) {
          setState({ status: 'error', message: 'This source could not be reached.' });
        }
      }
    }
    void load();
    return () => controller.abort();
  }, [onExpired, path]);

  return (
    <section
      aria-label={title}
      className="flex min-w-0 flex-col rounded-xl border border-theme-border bg-theme-card px-4 pt-4 pb-2 sm:px-5"
    >
      <h3 className="flex items-center gap-2 text-sm font-semibold">
        {icon}
        {title}
      </h3>
      <div className="flex-1 py-3" aria-live="polite">
        {state.status === 'loading' && (
          <p className="text-sm text-theme-text-secondary">Checking…</p>
        )}
        {state.status === 'error' && (
          <p className="text-sm text-theme-text-secondary">{state.message}</p>
        )}
        {state.status === 'ready' && (
          <>
            {children(state.data)}
            <p className="mt-3 text-xs text-theme-text-secondary">
              Observed{' '}
              <time dateTime={state.data.observed_at}>
                {formatObserved(state.data.observed_at)}
              </time>
            </p>
          </>
        )}
      </div>
      <button type="button" onClick={onOpen} className={`self-start text-sm ${linkClass}`}>
        {linkLabel} <ArrowUpRight size={14} aria-hidden="true" />
      </button>
    </section>
  );
}

function Values({ entries }: { entries: [string, string | number | null][] }) {
  return (
    <dl className="divide-y divide-theme-border text-sm">
      {entries.map(([label, value]) => (
        <div key={label} className="flex flex-wrap items-baseline justify-between gap-x-3 py-1.5">
          <dt className="text-theme-text-secondary">{label}</dt>
          <dd className="font-medium tabular-nums">{value ?? 'Unavailable'}</dd>
        </div>
      ))}
    </dl>
  );
}

function metricValue(metrics: Metric[], key: string) {
  const metric = metrics.find((entry) => entry.key === key);
  return metric ? formatMetricValue(metric) : 'Unavailable';
}

function SourceStatus({ source, freshness }: { source: string; freshness: string }) {
  return (
    <p className="mb-1 text-xs text-theme-text-secondary">
      Source: {statusLabel(source)} · Freshness: {statusLabel(freshness)}
    </p>
  );
}

export function SupportCockpit({
  capabilities,
  onExpired,
  onNavigate
}: {
  capabilities: string[];
  onExpired: () => void;
  onNavigate: (section: SupportSectionKey, tool?: SupportTool) => void;
}) {
  const [refresh, setRefresh] = useState(0);
  const showSnapshot = [
    'health.read',
    'jobs.read',
    'backups.read',
    'incidents.read',
    'overview.company.read',
    'config.read'
  ].some((capability) => capabilities.includes(capability));
  const tools: {
    section: SupportSectionKey;
    tool?: SupportTool;
    label: string;
    description: string;
    capability?: string;
  }[] = [
    {
      section: 'feedback',
      label: 'Triage user feedback',
      description: 'Review reports, suggestions, and attached request summaries.',
      capability: 'operator.manage'
    },
    {
      section: 'people',
      label: 'Inspect account access',
      description: 'Look up users, sessions and project memberships.',
      capability: 'company.directory.read'
    },
    {
      section: 'operations',
      tool: 'retry',
      label: 'Prepare a job retry',
      description: 'Review a retry for an eligible job or recovery delivery.',
      capability: 'company.jobs.retry'
    },
    {
      section: 'support',
      tool: 'case-audit',
      label: 'Review case audit',
      description: 'Inspect the audit history for a case you can access.',
      capability: 'logs.audit'
    },
    {
      section: 'settings',
      tool: 'safe-settings',
      label: 'Manage operational settings',
      description: 'Preview changes to allowlisted settings.',
      capability: 'company.settings.manage'
    },
    {
      section: 'security',
      label: 'Review owner security',
      description: 'Inspect enrolled passkeys and session assurance.'
    }
  ];
  return (
    <div className="space-y-6">
      <section aria-labelledby="cockpit-title">
        <div className="mb-4 flex flex-wrap items-center justify-between gap-3">
          <div>
            <h2 id="cockpit-title" className="text-2xl font-semibold tracking-tight">
              Operations overview
            </h2>
            <p className="mt-1 text-sm text-theme-text-secondary">
              Recent observations from the services and workflows you can access.
            </p>
          </div>
          {showSnapshot && (
            <button
              type="button"
              className="inline-flex min-h-11 items-center gap-2 rounded-md border border-theme-border bg-theme-card px-3 text-sm font-medium hover:bg-theme-main focus-visible:outline-2 focus-visible:outline-brand-600"
              onClick={() => setRefresh((previous) => previous + 1)}
            >
              <RefreshCw size={16} aria-hidden="true" /> Refresh snapshot
            </button>
          )}
        </div>
        {showSnapshot ? (
          <div key={refresh} className="grid gap-3 sm:grid-cols-2 xl:grid-cols-3">
            {capabilities.includes('health.read') && (
              <SnapshotCard<Schemas['SupportHealthRead']>
                title="Dependencies"
                icon={<Activity size={18} aria-hidden="true" />}
                path="/health"
                onExpired={onExpired}
                onOpen={() => onNavigate('operations', 'health')}
                linkLabel="Inspect service health"
              >
                {(data) => (
                  <Values
                    entries={[
                      ['PostgreSQL', statusLabel(data.database)],
                      ['Redis', statusLabel(data.redis)],
                      ['Object storage', statusLabel(data.object_storage)]
                    ]}
                  />
                )}
              </SnapshotCard>
            )}
            {capabilities.includes('jobs.read') && (
              <SnapshotCard<Schemas['SupportJobsMonitorRead']>
                title="Job delivery"
                icon={<ListTodo size={18} aria-hidden="true" />}
                path="/monitor/jobs?hours=24&limit=1"
                onExpired={onExpired}
                onOpen={() => onNavigate('operations', 'jobs')}
                linkLabel="Inspect jobs"
              >
                {(data) => (
                  <>
                    <SourceStatus source={data.source_status} freshness={data.freshness} />
                    <Values
                      entries={[
                        ['Failed outbox entries', data.outbox_failed],
                        ['Stale dispatched entries', data.outbox_stale_dispatched],
                        ['Unknown recovery deliveries', data.recovery_unknown],
                        ['Worker heartbeat', statusLabel(data.worker_status)]
                      ]}
                    />
                  </>
                )}
              </SnapshotCard>
            )}
            {capabilities.includes('backups.read') && (
              <SnapshotCard<Schemas['SupportBackupsMonitorRead']>
                title="Backup readiness"
                icon={<DatabaseBackup size={18} aria-hidden="true" />}
                path="/monitor/backups"
                onExpired={onExpired}
                onOpen={() => onNavigate('recovery', 'backups')}
                linkLabel="Inspect recovery evidence"
              >
                {(data) => (
                  <Values
                    entries={[
                      ['Overall posture', statusLabel(data.overall_recovery_posture)],
                      ['Scheduled database backup', statusLabel(data.database_backup_status)],
                      [
                        'Authenticated backup set',
                        statusLabel(data.authenticated_backup_set_status)
                      ],
                      ['Isolated restore', statusLabel(data.isolated_restore_status)]
                    ]}
                  />
                )}
              </SnapshotCard>
            )}
            {capabilities.includes('incidents.read') && (
              <SnapshotCard<Schemas['SupportIncidentsSummaryRead']>
                title="Security signals"
                icon={<ShieldAlert size={18} aria-hidden="true" />}
                path="/incidents/summary?hours=24"
                onExpired={onExpired}
                onOpen={() => onNavigate('support', 'incidents')}
                linkLabel="Inspect security incidents"
              >
                {(data) => (
                  <>
                    <SourceStatus source={data.source_status} freshness={data.freshness} />
                    <Values
                      entries={[
                        [
                          `Support sign-in failures (${data.window_hours}h)`,
                          metricValue(data.metrics, 'support_auth_failures')
                        ],
                        [
                          `Business sign-in failures (${data.window_hours}h)`,
                          metricValue(data.metrics, 'business_login_failures')
                        ],
                        [
                          `HTTP 5xx events (${data.window_hours}h)`,
                          metricValue(data.metrics, 'http_5xx_events')
                        ]
                      ]}
                    />
                  </>
                )}
              </SnapshotCard>
            )}
            {capabilities.includes('overview.company.read') && (
              <SnapshotCard<Schemas['SupportCompanyOverviewRead']>
                title="Business workflow"
                icon={<ChartNoAxesColumn size={18} aria-hidden="true" />}
                path="/overview"
                onExpired={onExpired}
                onOpen={() => onNavigate('operations', 'analytics')}
                linkLabel="Analyze business domains"
              >
                {(data) => (
                  <>
                    <SourceStatus source={data.source_status} freshness={data.freshness} />
                    <Values
                      entries={[
                        ['Active projects', metricValue(data.metrics, 'active_projects')],
                        ['Pending approvals', metricValue(data.metrics, 'open_approvals')],
                        ['Overdue approvals', metricValue(data.metrics, 'overdue_approvals')]
                      ]}
                    />
                  </>
                )}
              </SnapshotCard>
            )}
            {capabilities.includes('config.read') && (
              <SnapshotCard<Schemas['SupportConfigStatusRead']>
                title="Runtime configuration"
                icon={<Settings2 size={18} aria-hidden="true" />}
                path="/config/status"
                onExpired={onExpired}
                onOpen={() => onNavigate('settings', 'configuration')}
                linkLabel="Inspect configuration"
              >
                {(data) => (
                  <Values
                    entries={[
                      ['Configuration source', statusLabel(data.source_status)],
                      ['TLS certificate', statusLabel(data.tls_status)],
                      [
                        'Mail transport',
                        data.source_status === 'operational'
                          ? data.mail_configured
                            ? 'Configured'
                            : 'Not configured'
                          : null
                      ],
                      [
                        'Audit retention',
                        data.source_status === 'operational'
                          ? data.audit_purge_disabled
                            ? 'Retain only'
                            : 'Purge enabled'
                          : null
                      ]
                    ]}
                  />
                )}
              </SnapshotCard>
            )}
          </div>
        ) : (
          <p className="text-sm text-theme-text-secondary">
            Your session has no monitoring grants.
          </p>
        )}
      </section>
      <section aria-labelledby="cockpit-tools">
        <h2 id="cockpit-tools" className="mb-3 text-lg font-semibold">
          Operator tools
        </h2>
        <ul className="grid gap-3 sm:grid-cols-2 xl:grid-cols-3">
          {tools
            .filter(({ capability }) => !capability || capabilities.includes(capability))
            .map((tool) => (
              <li
                key={tool.section}
                className="rounded-xl border border-theme-border bg-theme-card px-4 pb-3"
              >
                <button
                  type="button"
                  className={linkClass}
                  onClick={() => onNavigate(tool.section, tool.tool)}
                >
                  {tool.label} <ArrowUpRight size={14} aria-hidden="true" />
                </button>
                <p className="text-sm text-theme-text-secondary">{tool.description}</p>
              </li>
            ))}
        </ul>
      </section>
    </div>
  );
}
