import { useCallback, useEffect, useState } from 'react';

import type { components } from '../../api/schema';
import { supportRequest } from '../../api/support';
import { SupportAccountPanel } from './SupportAccountPanel';
import { SupportAdminActionDialog } from './SupportAdminActionDialog';
import { SupportBackupsPanel } from './SupportBackupsPanel';
import { SupportBusinessActionReview } from './SupportBusinessActionsPanel';
import { SupportCaseReview } from './SupportCaseActionsPanel';
import { SupportCaseAuditPanel } from './SupportCaseAuditPanel';
import { SupportCasesPanel } from './SupportCasesPanel';
import { SupportConfigPanel } from './SupportConfigPanel';
import { SupportCockpit, type SupportTool } from './SupportCockpit';
import { SupportDataInspectorPanel } from './SupportDataInspectorPanel';
import { SupportEvidenceExportPanel } from './SupportEvidenceExportPanel';
import { SupportFeedbackInbox } from './SupportFeedbackInbox';
import { SupportHealthPanel } from './SupportHealthPanel';
import { SupportIncidentsPanel } from './SupportIncidentsPanel';
import { SupportJobsPanel } from './SupportJobsPanel';
import { SupportLogs } from './SupportLogs';
import { SupportOverviewPanel } from './SupportOverviewPanel';
import { SupportOwnerSecurityPanel } from './SupportOwnerSecurityPanel';
import { SupportPermissionViewPanel } from './SupportPermissionViewPanel';
import { SupportPortalPreview } from './SupportPortalPreview';
import { SupportPolicyExplainPanel } from './SupportPolicyExplainPanel';
import { SupportRecoveryStatusPanel } from './SupportRecoveryStatusPanel';
import { SupportSafeSettingsPanel } from './SupportSafeSettingsPanel';
import { SupportUsersPage } from './SupportUsersPage';
import { buttonClass, panelCardClass } from './supportPanelUtils';

type Session = components['schemas']['SupportProfile'];
type CompanyContext = components['schemas']['SupportCompanyContextRead'];

export type SupportSectionKey =
  | 'overview'
  | 'people'
  | 'operations'
  | 'support'
  | 'feedback'
  | 'recovery'
  | 'settings'
  | 'security';

const workspaceSections: ReadonlyArray<{ key: SupportSectionKey; label: string }> = [
  { key: 'overview', label: 'Overview' },
  { key: 'people', label: 'People & Access' },
  { key: 'operations', label: 'Projects & Operations' },
  { key: 'support', label: 'Support & Audit' },
  { key: 'feedback', label: 'Feedback inbox' },
  { key: 'recovery', label: 'Recovery' },
  { key: 'settings', label: 'Settings' },
  { key: 'security', label: 'Owner Security' }
];

function parseLocationRoute(): {
  section: SupportSectionKey;
  userId: string | null;
  tool: string | null;
} {
  if (typeof window === 'undefined') return { section: 'overview', userId: null, tool: null };
  // The restricted Nginx virtual host only serves the app shell at "/".
  // Separate workspace fragments from authentication links such as "#cli=".
  const hash = window.location.hash;
  const [name, detail] = (hash.startsWith('#/') ? hash.slice(1) : window.location.pathname)
    .split('/')
    .slice(1);
  const section = workspaceSections.find(({ key }) => key === name)?.key ?? 'overview';
  if (section === 'people') {
    return {
      section,
      userId: detail && /^[0-9a-fA-F-]{36}$/.test(detail) ? detail : null,
      tool: null
    };
  }
  return { section, userId: null, tool: hash.startsWith('#/') ? (detail ?? null) : null };
}

export function SupportShell({
  session,
  pending,
  onSignOut,
  onExpired
}: {
  session: Session;
  pending: boolean;
  onSignOut: () => void;
  onExpired: () => void;
}) {
  const initialRoute = parseLocationRoute();
  const [section, setSection] = useState<SupportSectionKey>(initialRoute.section);
  const [selectedUserId, setSelectedUserId] = useState<string | null>(initialRoute.userId);
  const [portalPreview, setPortalPreview] = useState<string | null>(null);
  const [activeTool, setActiveTool] = useState(initialRoute.tool);
  const [context, setContext] = useState<CompanyContext | null>(null);

  // Safe job retry state (T-26)
  const [retrySource, setRetrySource] = useState<'task_outbox' | 'support_recovery_delivery'>(
    'task_outbox'
  );
  const [retryJobId, setRetryJobId] = useState('');
  const [retryReason, setRetryReason] = useState('');
  const [showRetryDialog, setShowRetryDialog] = useState(false);

  const loadContext = useCallback(async () => {
    try {
      const resp = await supportRequest('/company/context');
      if (resp.status === 401) {
        onExpired();
        return;
      }
      if (resp.ok) {
        setContext((await resp.json()) as CompanyContext);
      }
    } catch {
      // The context badges remain hidden when their source cannot be reached.
    }
  }, [onExpired]);

  useEffect(() => {
    void loadContext();
  }, [loadContext]);

  useEffect(() => {
    const onPopState = () => {
      const next = parseLocationRoute();
      setSection(next.section);
      setSelectedUserId(next.userId);
      setActiveTool(next.tool);
    };
    window.addEventListener('popstate', onPopState);
    return () => window.removeEventListener('popstate', onPopState);
  }, []);

  useEffect(() => {
    if (!activeTool) return;
    const target = document.getElementById('tool-' + activeTool);
    target?.scrollIntoView({ block: 'start' });
    target?.focus({ preventScroll: true });
  }, [section, activeTool]);

  function navigateTo(
    nextSection: SupportSectionKey,
    nextUserId: string | null = null,
    tool?: SupportTool
  ) {
    setSection(nextSection);
    setSelectedUserId(nextUserId);
    if (typeof window !== 'undefined') {
      const detail = nextUserId ?? tool;
      const hash =
        nextSection === 'overview' ? '' : `#/${nextSection}${detail ? '/' + detail : ''}`;
      if (window.location.pathname !== '/' || window.location.hash !== hash) {
        window.history.pushState({}, '', '/' + hash);
        setActiveTool(tool ?? null);
        if (!tool) window.scrollTo(0, 0);
      }
    }
  }

  const caps = session.capabilities;

  if (portalPreview && caps.includes('simulation.start')) {
    return (
      <SupportPortalPreview
        key={portalPreview}
        viewId={portalPreview}
        onExit={() => setPortalPreview(null)}
        onExpired={onExpired}
      />
    );
  }

  return (
    <div key={session.operator_id} className="space-y-4">
      <header
        aria-label="Company control centre header"
        className="space-y-3 rounded-xl border border-theme-border bg-theme-card p-4 sm:px-5"
      >
        <div className="flex flex-wrap items-center justify-between gap-2">
          <div>
            <h1 className="text-lg font-semibold tracking-tight">Garrisons Super Admin</h1>
            <p className="text-xs text-theme-text-secondary">
              Company Control Centre · Technical session active · Single-company deployment
            </p>
          </div>
          <div className="flex flex-wrap items-center gap-1.5">
            {context && (
              <p className="rounded-md border border-theme-border px-2 py-1 text-xs text-theme-text-secondary">
                {context.environment} · {context.custody_mode.replace(/_/g, ' ')} · Policy{' '}
                {context.policy_version}
              </p>
            )}
            <button
              disabled={pending}
              onClick={onSignOut}
              type="button"
              className={`${buttonClass} min-h-11`}
            >
              Sign out
            </button>
          </div>
        </div>

        {context?.banner_notice && (
          <p role="status" className="rounded border border-brand-600/40 bg-brand-600/10 px-2 py-1">
            Notice: {context.banner_notice}
          </p>
        )}
        {context?.maintenance_window_notice && (
          <p role="status" className="rounded border border-amber-500/40 bg-amber-500/10 px-2 py-1">
            Maintenance: {context.maintenance_window_notice}
          </p>
        )}

        <nav
          aria-label="Company control centre navigation"
          className="flex flex-wrap gap-1 border-t border-theme-border pt-2"
        >
          {workspaceSections
            .filter((item) => item.key !== 'feedback' || caps.includes('operator.manage'))
            .map((item) => (
              <button
                key={item.key}
                type="button"
                aria-current={section === item.key ? 'page' : undefined}
                onClick={() => navigateTo(item.key, null)}
                className={`min-h-11 rounded-md px-3 text-sm font-medium focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-brand-600 ${
                  section === item.key
                    ? 'bg-brand-600 text-white'
                    : 'text-theme-text-secondary hover:bg-theme-main hover:text-theme-text'
                }`}
              >
                {item.label}
              </button>
            ))}
        </nav>
      </header>

      {section === 'overview' && (
        <SupportCockpit
          capabilities={caps}
          onExpired={onExpired}
          onNavigate={(destination, tool) => navigateTo(destination, null, tool)}
        />
      )}

      {section === 'people' && (
        <SupportUsersPage
          capabilities={caps}
          selectedUserId={selectedUserId}
          onSelectUser={(uid) => navigateTo('people', uid)}
          onPortalPreview={setPortalPreview}
          onExpired={onExpired}
        />
      )}

      {section === 'operations' && (
        <div className="space-y-4">
          {caps.some((capability) => capability.startsWith('overview.')) && (
            <div id="tool-analytics" tabIndex={-1}>
              <SupportOverviewPanel capabilities={caps} onExpired={onExpired} />
            </div>
          )}
          {caps.includes('jobs.read') && (
            <div id="tool-jobs" tabIndex={-1}>
              <SupportJobsPanel onExpired={onExpired} />
            </div>
          )}
          {caps.includes('company.jobs.retry') && (
            <section
              id="tool-retry"
              tabIndex={-1}
              aria-label="Safe terminal job retry"
              className={panelCardClass}
            >
              <h3 className="font-semibold">Allowlisted terminal job re-queue</h3>
              <p className="text-xs text-theme-text-secondary">
                Re-queues only eligible terminal failed outbox entries or unknown recovery
                deliveries with their original scope and payload.
              </p>
              <div className="grid gap-2 sm:grid-cols-3 text-xs">
                <label className="block">
                  Job source
                  <select
                    aria-label="Retry job source"
                    value={retrySource}
                    onChange={(e) =>
                      setRetrySource(e.target.value as 'task_outbox' | 'support_recovery_delivery')
                    }
                    className="mt-1 block w-full rounded border border-theme-border bg-theme-card px-2 py-1"
                  >
                    <option value="task_outbox">Task outbox (failed import/report)</option>
                    <option value="support_recovery_delivery">
                      Support recovery delivery (unknown state)
                    </option>
                  </select>
                </label>
                <label className="block">
                  Job / Action UUID
                  <input
                    type="text"
                    aria-label="Retry job UUID"
                    value={retryJobId}
                    onChange={(e) => setRetryJobId(e.target.value)}
                    maxLength={36}
                    className="mt-1 block w-full rounded border border-theme-border bg-theme-card px-2 py-1"
                  />
                </label>
                <label className="block">
                  Operational reason (10–300 chars)
                  <input
                    type="text"
                    aria-label="Retry job reason"
                    value={retryReason}
                    onChange={(e) => setRetryReason(e.target.value)}
                    minLength={10}
                    maxLength={300}
                    className="mt-1 block w-full rounded border border-theme-border bg-theme-card px-2 py-1"
                  />
                </label>
              </div>
              {!showRetryDialog ? (
                <button
                  type="button"
                  className={buttonClass}
                  onClick={() => setShowRetryDialog(true)}
                >
                  Prepare job retry command
                </button>
              ) : (
                <SupportAdminActionDialog
                  title="Re-queue terminal failed job"
                  description="Preserves original payload, actor, and target scope."
                  onExpired={onExpired}
                  onCancel={() => setShowRetryDialog(false)}
                  onCompleted={() => setShowRetryDialog(false)}
                  buildRequest={() =>
                    retryJobId.trim() && retryReason.trim().length >= 10
                      ? {
                          command_kind: 'retry_safe_job',
                          job_source: retrySource,
                          job_id: retryJobId.trim(),
                          reason_code: 'operational_recovery',
                          reason: retryReason.trim()
                        }
                      : null
                  }
                />
              )}
            </section>
          )}
          {caps.includes('company.data.inspect') && (
            <SupportDataInspectorPanel onExpired={onExpired} />
          )}
          {caps.includes('health.read') && (
            <div id="tool-health" tabIndex={-1}>
              <SupportHealthPanel onExpired={onExpired} />
            </div>
          )}
        </div>
      )}

      {section === 'support' && (
        <div className="space-y-4">
          {caps.includes('incidents.read') && (
            <div id="tool-incidents" tabIndex={-1}>
              <SupportIncidentsPanel onExpired={onExpired} />
            </div>
          )}
          {caps.includes('cases.manage') && (
            <SupportCasesPanel
              onExpired={onExpired}
              operatorId={session.operator_id}
              canReadDirectory={caps.includes('directory.read')}
              canReviewProjectScope={caps.includes('simulation.start')}
              canReadTimeline={caps.includes('logs.runtime')}
            />
          )}
          {(caps.includes('operator.manage') ||
            (caps.includes('cases.manage') &&
              (caps.includes('logs.runtime') || caps.includes('directory.read')))) && (
            <SupportCaseReview onExpired={onExpired} />
          )}
          {caps.includes('directory.read') && (
            <SupportAccountPanel
              onExpired={onExpired}
              canRequest={caps.includes('account.request')}
              canExplain={caps.includes('simulation.start')}
            />
          )}
          {(caps.includes('account.request') || caps.includes('simulation.start')) && (
            <SupportBusinessActionReview
              onExpired={onExpired}
              onPortalPreview={setPortalPreview}
              canRecordContact={
                caps.includes('operator.manage') && caps.includes('account.request')
              }
            />
          )}
          {caps.includes('simulation.start') && (
            <>
              <SupportPermissionViewPanel key={session.operator_id} onExpired={onExpired} />
              <SupportPolicyExplainPanel onExpired={onExpired} />
            </>
          )}
          {caps.includes('account.request') && <SupportRecoveryStatusPanel onExpired={onExpired} />}
          {caps.includes('logs.audit') && (
            <div id="tool-case-audit" tabIndex={-1}>
              <SupportCaseAuditPanel onExpired={onExpired} />
            </div>
          )}
          {caps.includes('logs.runtime') && (
            <SupportLogs onExpired={onExpired} canFollow={caps.includes('logs.stream')} />
          )}
          {caps.includes('logs.runtime') && caps.includes('logs.export') && (
            <SupportEvidenceExportPanel onExpired={onExpired} />
          )}
        </div>
      )}

      {section === 'feedback' &&
        (caps.includes('operator.manage') ? (
          <SupportFeedbackInbox onExpired={onExpired} />
        ) : (
          <p role="alert" className="text-sm text-theme-text-secondary">
            Your session cannot read the feedback inbox.
          </p>
        ))}

      {section === 'recovery' && (
        <div className="space-y-4">
          {caps.includes('backups.read') ? (
            <div id="tool-backups" tabIndex={-1}>
              <SupportBackupsPanel onExpired={onExpired} />
            </div>
          ) : (
            <p role="alert" className="text-xs text-theme-text-secondary">
              Recovery monitoring requires the <code>backups.read</code> capability.
            </p>
          )}
          {caps.includes('account.request') && (
            <SupportRecoveryStatusPanel
              key={'recovery-status:' + session.operator_id}
              onExpired={onExpired}
            />
          )}
        </div>
      )}

      {section === 'settings' && (
        <div className="space-y-4">
          {caps.includes('config.read') && (
            <div id="tool-configuration" tabIndex={-1}>
              <SupportConfigPanel onExpired={onExpired} />
            </div>
          )}
          {(caps.includes('config.read') || caps.includes('company.settings.manage')) && (
            <div id="tool-safe-settings" tabIndex={-1}>
              <SupportSafeSettingsPanel
                canManage={caps.includes('company.settings.manage')}
                onExpired={onExpired}
                onUpdated={() => void loadContext()}
              />
            </div>
          )}
        </div>
      )}

      {section === 'security' && (
        <SupportOwnerSecurityPanel
          canManageOperators={caps.includes('operator.manage')}
          onExpired={onExpired}
        />
      )}
    </div>
  );
}
