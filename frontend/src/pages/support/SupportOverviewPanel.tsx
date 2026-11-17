import { useEffect, useMemo, useRef, useState } from 'react';

import type { components } from '../../api/schema';
import { supportRequest } from '../../api/support';
import {
  buttonClass,
  formatMetricValue,
  formatObserved,
  inputClass,
  panelCardClass,
  statusLabel,
  uuidPattern
} from './supportPanelUtils';

type CompanyOverview = components['schemas']['SupportCompanyOverviewRead'];
type ProjectsOverview = components['schemas']['SupportProjectsOverviewRead'];
type WorkforceOverview = components['schemas']['SupportWorkforceOverviewRead'];
type InventoryOverview = components['schemas']['SupportInventoryOverviewRead'];
type SuppliersOverview = components['schemas']['SupportSuppliersOverviewRead'];
type DocumentsOverview = components['schemas']['SupportDocumentsOverviewRead'];
type FinanceOverview = components['schemas']['SupportFinanceOverviewRead'];
type ApprovalsOverview = components['schemas']['SupportApprovalsOverviewRead'];
type AnyOverview =
  | CompanyOverview
  | ProjectsOverview
  | WorkforceOverview
  | InventoryOverview
  | SuppliersOverview
  | DocumentsOverview
  | FinanceOverview
  | ApprovalsOverview;
type OverviewDomain = NonNullable<AnyOverview['domain']>;

const DOMAIN_DEFS: ReadonlyArray<{
  domain: OverviewDomain;
  capability: string;
  label: string;
  path: string;
  supportsCaseScope?: boolean;
}> = [
  { domain: 'company', capability: 'overview.company.read', label: 'Company', path: '/overview' },
  {
    domain: 'projects',
    capability: 'overview.projects.read',
    label: 'Projects',
    path: '/overview/projects',
    supportsCaseScope: true
  },
  {
    domain: 'workforce',
    capability: 'overview.workforce.read',
    label: 'Workforce',
    path: '/overview/workforce'
  },
  {
    domain: 'inventory',
    capability: 'overview.inventory.read',
    label: 'Inventory',
    path: '/overview/inventory',
    supportsCaseScope: true
  },
  {
    domain: 'suppliers',
    capability: 'overview.suppliers.read',
    label: 'Suppliers',
    path: '/overview/suppliers'
  },
  {
    domain: 'documents',
    capability: 'overview.documents.read',
    label: 'Documents',
    path: '/overview/documents'
  },
  { domain: 'finance', capability: 'overview.finance.read', label: 'Finance', path: '/overview/finance' },
  {
    domain: 'approvals',
    capability: 'overview.approvals.read',
    label: 'Approvals',
    path: '/overview/approvals'
  }
];

export function SupportOverviewPanel({
  capabilities,
  onExpired
}: {
  capabilities: string[];
  onExpired: () => void;
}) {
  const allowed = useMemo(
    () => DOMAIN_DEFS.filter((item) => capabilities.includes(item.capability)),
    [capabilities]
  );
  const [selected, setSelected] = useState<OverviewDomain>(() => allowed[0]?.domain ?? 'company');
  const [caseId, setCaseId] = useState('');
  const [projectId, setProjectId] = useState('');
  const [pending, setPending] = useState(false);
  const [error, setError] = useState('');
  const [data, setData] = useState<AnyOverview | null>(null);
  const activeRequest = useRef<AbortController | null>(null);

  useEffect(() => () => activeRequest.current?.abort(), []);

  useEffect(() => {
    if (allowed.length > 0 && !allowed.some((item) => item.domain === selected)) {
      setSelected(allowed[0].domain);
    }
  }, [allowed, selected]);

  if (allowed.length === 0) return null;
  const activeDef = allowed.find((item) => item.domain === selected) ?? allowed[0];

  async function load(domainToLoad = activeDef) {
    activeRequest.current?.abort();
    const controller = new AbortController();
    activeRequest.current = controller;
    setPending(true);
    setError('');
    try {
      const params = new URLSearchParams();
      if (domainToLoad.supportsCaseScope && caseId.trim()) {
        params.set('case_id', caseId.trim());
        if (projectId.trim()) params.set('project_id', projectId.trim());
      }
      const query = params.toString();
      const response = await supportRequest(
        query ? `${domainToLoad.path}?${query}` : domainToLoad.path,
        { signal: controller.signal }
      );
      if (controller.signal.aborted) return;
      if (response.status === 401) {
        onExpired();
        return;
      }
      if (response.status === 403 || response.status === 404) {
        setData(null);
        setError('This oversight view or case scope is unavailable.');
        return;
      }
      if (response.status === 429) {
        setError('Rate limit reached. Wait briefly before refreshing metrics.');
        return;
      }
      if (!response.ok) throw new Error();
      const payload = (await response.json()) as AnyOverview;
      if (!controller.signal.aborted) setData(payload);
    } catch {
      if (!controller.signal.aborted) {
        setData(null);
        setError('Overview metrics could not be loaded.');
      }
    } finally {
      if (!controller.signal.aborted) setPending(false);
    }
  }

  return (
    <section aria-label="Enterprise oversight" className={panelCardClass}>
      <div className="flex flex-wrap items-center justify-between gap-2">
        <h2 className="font-semibold">Enterprise oversight</h2>
        <div className="flex flex-wrap gap-1.5" role="tablist" aria-label="Oversight domains">
          {allowed.map((item) => (
            <button
              key={item.domain}
              type="button"
              role="tab"
              aria-selected={item.domain === activeDef.domain}
              disabled={pending}
              onClick={() => {
                setSelected(item.domain);
                setData(null);
                setError('');
                setCaseId('');
                setProjectId('');
              }}
              className={
                item.domain === activeDef.domain
                  ? 'rounded bg-brand-600 px-2.5 py-1 text-xs font-medium text-white'
                  : 'rounded border border-theme-border px-2.5 py-1 text-xs'
              }
            >
              {item.label}
            </button>
          ))}
        </div>
      </div>

      {activeDef.supportsCaseScope && (
        <div className="grid gap-2 sm:grid-cols-2">
          <label className="text-xs">
            Optional linked case ID
            <input
              value={caseId}
              pattern={uuidPattern}
              disabled={pending}
              onChange={(event) => {
                setCaseId(event.target.value);
                if (!event.target.value.trim()) setProjectId('');
                setData(null);
                setError('');
              }}
              placeholder="Leave blank for company totals"
              className={inputClass}
            />
          </label>
          <label className="text-xs">
            Optional case project ID
            <input
              value={projectId}
              pattern={uuidPattern}
              disabled={pending || !caseId.trim()}
              onChange={(event) => {
                setProjectId(event.target.value);
                setData(null);
                setError('');
              }}
              placeholder="Requires linked case ID"
              className={inputClass}
            />
          </label>
        </div>
      )}

      <div className="flex items-center gap-3">
        <button type="button" className={buttonClass} disabled={pending} onClick={() => void load()}>
          {pending ? 'Loading…' : `Load ${activeDef.label.toLowerCase()} overview`}
        </button>
      </div>

      {error && <p role="alert" className="text-sm">{error}</p>}

      {data && (
        <div className="space-y-3">
          <div className="flex flex-wrap gap-3 text-xs text-theme-text-secondary">
            <span>Scope: {statusLabel(data.scope.kind)}</span>
            <span>Source status: {statusLabel(data.source_status)}</span>
            <span>Freshness: {statusLabel(data.freshness)}</span>
            <span>
              Observed: <time dateTime={data.observed_at}>{formatObserved(data.observed_at)}</time>
            </span>
          </div>

          <dl className="grid gap-2 sm:grid-cols-2">
            {data.metrics.map((metric) => (
              <div key={metric.key} className="rounded border border-theme-border p-2.5 text-sm">
                <dt className="text-xs text-theme-text-secondary">{metric.label}</dt>
                <dd className="mt-0.5 font-medium">{formatMetricValue(metric)}</dd>
                {metric.note && <p className="mt-1 text-xs text-theme-text-secondary">{metric.note}</p>}
              </div>
            ))}
          </dl>

          {data.domain === 'projects' && data.by_status && data.by_status.length > 0 && (
            <div className="overflow-x-auto">
              <table className="min-w-full text-left text-xs">
                <thead>
                  <tr className="border-b border-theme-border">
                    <th className="py-1 pr-3">Project status</th>
                    <th className="py-1">Count</th>
                  </tr>
                </thead>
                <tbody>
                  {data.by_status.map((row) => (
                    <tr key={row.status} className="border-b border-theme-border/50">
                      <td className="py-1 pr-3">{statusLabel(row.status)}</td>
                      <td className="py-1">{row.count}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          )}

          {data.domain === 'projects' && data.case_projects && data.case_projects.length > 0 && (
            <ul aria-label="Case project summaries" className="space-y-1 text-xs">
              {data.case_projects.map((item) => (
                <li key={item.label}>
                  {item.label} · {statusLabel(item.status)} · Progress {item.progress_band}
                </li>
              ))}
            </ul>
          )}

          {data.domain === 'workforce' && (
            <div className="space-y-2 text-xs">
              <p className="text-theme-text-secondary">
                Small-cell privacy threshold: counts below {data.suppression_threshold} are suppressed.
              </p>
              {data.by_status && data.by_status.length > 0 && (
                <ul aria-label="Workforce by status" className="grid gap-1 sm:grid-cols-2">
                  {data.by_status.map((row) => (
                    <li key={row.status}>
                      {statusLabel(row.status)}:{' '}
                      {row.state === 'suppressed' ? 'Suppressed (< 5)' : row.count}
                    </li>
                  ))}
                </ul>
              )}
              {data.by_project && data.by_project.length > 0 && (
                <ul aria-label="Workforce by project group" className="grid gap-1 sm:grid-cols-2">
                  {data.by_project.map((row) => (
                    <li key={row.project_label}>
                      {row.project_label}:{' '}
                      {row.state === 'suppressed' ? 'Suppressed (< 5)' : row.headcount}
                    </li>
                  ))}
                </ul>
              )}
            </div>
          )}

          {data.domain === 'finance' && (
            <p className="text-xs text-theme-text-secondary">
              Finance writes policy: {statusLabel(data.finance_writes_policy)} · Currency:{' '}
              {data.operating_currency}
            </p>
          )}

          {data.domain === 'approvals' && data.by_workflow && data.by_workflow.length > 0 && (
            <div className="overflow-x-auto">
              <table className="min-w-full text-left text-xs">
                <thead>
                  <tr className="border-b border-theme-border">
                    <th className="py-1 pr-3">Workflow</th>
                    <th className="py-1 pr-3">Pending</th>
                    <th className="py-1 pr-3">Overdue</th>
                    <th className="py-1 pr-3">Escalated</th>
                    <th className="py-1">Rejected</th>
                  </tr>
                </thead>
                <tbody>
                  {data.by_workflow.map((row) => (
                    <tr key={row.request_type} className="border-b border-theme-border/50">
                      <td className="py-1 pr-3">{statusLabel(row.request_type)}</td>
                      <td className="py-1 pr-3">{row.pending}</td>
                      <td className="py-1 pr-3">{row.overdue}</td>
                      <td className="py-1 pr-3">{row.escalated}</td>
                      <td className="py-1">{row.rejected}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          )}
        </div>
      )}
    </section>
  );
}
