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
import { SupportCustodyPanel } from './SupportCustodyPanel';
import { SupportDataInspectorPanel } from './SupportDataInspectorPanel';
import { SupportEvidenceExportPanel } from './SupportEvidenceExportPanel';
import { SupportHealthPanel } from './SupportHealthPanel';
import { SupportIncidentsPanel } from './SupportIncidentsPanel';
import { SupportJobsPanel } from './SupportJobsPanel';
import { SupportLogs } from './SupportLogs';
import { SupportOverviewPanel } from './SupportOverviewPanel';
import { SupportOwnerSecurityPanel } from './SupportOwnerSecurityPanel';
import { SupportPermissionViewPanel } from './SupportPermissionViewPanel';
import { SupportPolicyExplainPanel } from './SupportPolicyExplainPanel';
import { SupportRecoveryStatusPanel } from './SupportRecoveryStatusPanel';
import { SupportSafeSettingsPanel } from './SupportSafeSettingsPanel';
import { SupportUsersPage } from './SupportUsersPage';
import { buttonClass, panelCardClass } from './supportPanelUtils';

type Session = components['schemas']['SupportProfile'];
type CompanyContext = components['schemas']['SupportCompanyContextRead'];

export type SupportSectionKey =
  'overview' | 'people' | 'operations' | 'support' | 'recovery' | 'settings' | 'security';

function parseLocationRoute(): { section: SupportSectionKey; userId: string | null } {
  if (typeof window === 'undefined') return { section: 'overview', userId: null };
  const path = window.location.pathname;
  const peopleUserMatch = /^\/people\/([0-9a-fA-F-]{36})\/?$/.exec(path);
  if (peopleUserMatch) {
    return { section: 'people', userId: peopleUserMatch[1] };
  }
  if (path === '/people') return { section: 'people', userId: null };
  if (path === '/operations') return { section: 'operations', userId: null };
  if (path === '/support') return { section: 'support', userId: null };
  if (path === '/recovery') return { section: 'recovery', userId: null };
  if (path === '/settings') return { section: 'settings', userId: null };
  if (path === '/security') return { section: 'security', userId: null };
  return { section: 'overview', userId: null };
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
      // Context banner degrades gracefully to defaults
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
    };
    window.addEventListener('popstate', onPopState);
    return () => window.removeEventListener('popstate', onPopState);
  }, []);

  function navigateTo(nextSection: SupportSectionKey, nextUserId: string | null = null) {
    setSection(nextSection);
    setSelectedUserId(nextUserId);
    if (typeof window !== 'undefined') {
      const targetPath =
        nextSection === 'people' && nextUserId
          ? `/people/${nextUserId}`
          : nextSection === 'overview'
            ? '/'
            : `/${nextSection}`;
      if (window.location.pathname !== targetPath) {
        window.history.pushState({}, '', targetPath);
      }
    }
  }

  const caps = session.capabilities;

  const sections: Array<{ key: SupportSectionKey; label: string }> = [
    { key: 'overview', label: 'Overview' },
    { key: 'people', label: 'People & Access' },
    { key: 'operations', label: 'Projects & Operations' },
    { key: 'support', label: 'Support & Audit' },
    { key: 'recovery', label: 'Recovery' },
    { key: 'settings', label: 'Settings' },
    { key: 'security', label: 'Owner Security' }
  ];

  return (
    <div key={session.operator_id} className="space-y-4">
      <header
        aria-label="Company control centre header"
        className="space-y-2 rounded-lg border border-theme-border bg-theme-main p-3 text-xs"
      >
        <div className="flex flex-wrap items-center justify-between gap-2">
          <div>
            <p className="font-semibold text-sm">
              {context?.company_name ?? 'Garrisons Investments'} · Company Control Centre
            </p>
            <p className="text-theme-text-secondary">
              Technical session active · Single-company deployment · Policy{' '}
              {context?.policy_version ?? '2026-11-v1'}
            </p>
          </div>
          <div className="flex flex-wrap items-center gap-1.5">
            <span className="rounded border border-theme-border px-2 py-0.5 font-mono uppercase">
              Env: {context?.environment ?? 'production'}
            </span>
            <span className="rounded border border-theme-border px-2 py-0.5 font-mono">
              Mode: {context?.custody_mode ?? 'single_owner'}
            </span>
            <button disabled={pending} onClick={onSignOut} type="button" className={buttonClass}>
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
          className="flex flex-wrap gap-1.5 border-t border-theme-border pt-2"
        >
          {sections.map((item) => (
            <button
              key={item.key}
              type="button"
              aria-current={section === item.key ? 'page' : undefined}
              onClick={() => navigateTo(item.key, null)}
              className={`${buttonClass} ${
                section === item.key ? 'bg-brand-600 text-white border-brand-600' : ''
              }`}
            >
              {item.label}
            </button>
          ))}
        </nav>
      </header>

      {section === 'overview' && (
        <div className="space-y-4">
          <section aria-label="Control centre quick actions" className={panelCardClass}>
            <div className="flex flex-wrap items-center justify-between gap-2">
              <div>
                <h2 className="font-semibold">Company Control Centre Overview</h2>
                <p className="text-xs text-theme-text-secondary">
                  Manage people, access, and operational issues for Garrisons from one place, with a
                  clear explanation before every sensitive change.
                </p>
              </div>
              <div className="flex flex-wrap gap-1.5">
                <button
                  type="button"
                  className={buttonClass}
                  onClick={() => navigateTo('people', null)}
                >
                  Open People & Access
                </button>
                <button
                  type="button"
                  className={buttonClass}
                  onClick={() => navigateTo('operations', null)}
                >
                  Inspect Operations & Jobs
                </button>
                <button
                  type="button"
                  className={buttonClass}
                  onClick={() => navigateTo('recovery', null)}
                >
                  Check Recovery Posture
                </button>
              </div>
            </div>
          </section>

          <SupportOverviewPanel capabilities={caps} onExpired={onExpired} />
          {caps.includes('jobs.read') && <SupportJobsPanel onExpired={onExpired} />}
          {caps.includes('backups.read') && <SupportBackupsPanel onExpired={onExpired} />}
          {caps.includes('config.read') && <SupportConfigPanel onExpired={onExpired} />}
          {caps.includes('incidents.read') && <SupportIncidentsPanel onExpired={onExpired} />}
          {caps.includes('cases.manage') && (
            <SupportCasesPanel
              onExpired={onExpired}
              operatorId={session.operator_id}
              canReadDirectory={caps.includes('directory.read')}
              canReviewProjectScope={caps.includes('simulation.start')}
              canReadTimeline={caps.includes('logs.runtime')}
            />
          )}
          {caps.includes('operator.manage') && <SupportCustodyPanel onExpired={onExpired} />}
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
          {caps.includes('account.request') && (
            <SupportRecoveryStatusPanel
              key={'recovery-status:' + session.operator_id}
              onExpired={onExpired}
            />
          )}
          {caps.includes('logs.audit') && <SupportCaseAuditPanel onExpired={onExpired} />}
          {caps.includes('health.read') && <SupportHealthPanel onExpired={onExpired} />}
          {caps.includes('logs.runtime') && (
            <SupportLogs onExpired={onExpired} canFollow={caps.includes('logs.stream')} />
          )}
          {caps.includes('logs.runtime') && caps.includes('logs.export') && (
            <SupportEvidenceExportPanel onExpired={onExpired} />
          )}
        </div>
      )}

      {section === 'people' && (
        <SupportUsersPage
          capabilities={caps}
          selectedUserId={selectedUserId}
          onSelectUser={(uid) => navigateTo('people', uid)}
          onExpired={onExpired}
        />
      )}

      {section === 'operations' && (
        <div className="space-y-4">
          <SupportOverviewPanel capabilities={caps} onExpired={onExpired} />
          {caps.includes('jobs.read') && <SupportJobsPanel onExpired={onExpired} />}
          {caps.includes('company.jobs.retry') && (
            <section aria-label="Safe terminal job retry" className={panelCardClass}>
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
          {caps.includes('health.read') && <SupportHealthPanel onExpired={onExpired} />}
        </div>
      )}

      {section === 'support' && (
        <div className="space-y-4">
          {caps.includes('incidents.read') && <SupportIncidentsPanel onExpired={onExpired} />}
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
          {caps.includes('logs.audit') && <SupportCaseAuditPanel onExpired={onExpired} />}
          {caps.includes('logs.runtime') && (
            <SupportLogs onExpired={onExpired} canFollow={caps.includes('logs.stream')} />
          )}
          {caps.includes('logs.runtime') && caps.includes('logs.export') && (
            <SupportEvidenceExportPanel onExpired={onExpired} />
          )}
        </div>
      )}

      {section === 'recovery' && (
        <div className="space-y-4">
          {caps.includes('backups.read') ? (
            <SupportBackupsPanel onExpired={onExpired} />
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
          {caps.includes('config.read') && <SupportConfigPanel onExpired={onExpired} />}
          {(caps.includes('config.read') || caps.includes('company.settings.manage')) && (
            <SupportSafeSettingsPanel
              canManage={caps.includes('company.settings.manage')}
              onExpired={onExpired}
              onUpdated={() => void loadContext()}
            />
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
