import { isAxiosError } from 'axios';
import { AlertTriangle, Check, Forward, X } from 'lucide-react';
import { useCallback, useEffect, useRef, useState } from 'react';
import { Link, useSearchParams } from 'react-router-dom';

import {
  approveGenericApproval,
  delegateGenericApproval,
  getGenericApproval,
  listApprovals,
  listDelegationCandidates,
  rejectGenericApproval,
  type ApprovalDelegate,
  type ApprovalRecord
} from '../../api/approvals';
import { formatApiError } from '../../api/errors';
import {
  approveDailyReport,
  getDailyReport,
  listDailyReports,
  rejectDailyReport,
  type DailyReportRecord
} from '../../api/reports';
import { EmptyState } from '../../components/shared/EmptyState';
import { StatusBadge } from '../../components/shared/StatusBadge';
import { useAuth } from '../../context/useAuth';
import { labelledAmount } from '../../api/businessPolicy';
import { ReportSupervisorEvidence } from '../reports/SupervisorEvidence';

function roleLabel(role: string) {
  return role
    .split('_')
    .map((part) => part[0].toUpperCase() + part.slice(1))
    .join(' ');
}

function delegateOptionPrompt(loading: boolean, total: number) {
  if (loading) return 'Loading eligible approvers…';
  if (total === 0) return 'No eligible approvers found';
  return 'Select an eligible approver';
}

export function ApprovalInboxPage() {
  const { user } = useAuth();
  const [searchParams] = useSearchParams();
  const canApprove = user?.permissions?.includes('reports:approve') ?? false;
  const requestedTab =
    !canApprove || searchParams.get('tab') === 'outbox'
      ? 'outbox'
      : searchParams.get('tab') === 'workflow'
        ? 'workflow'
        : 'reports';
  const focusedApprovalId = searchParams.get('approvalId');
  const focusedReportId = searchParams.get('reportId');
  const [reports, setReports] = useState<DailyReportRecord[]>([]);
  const [genericApprovals, setGenericApprovals] = useState<ApprovalRecord[]>([]);
  const [commentsByReport, setCommentsByReport] = useState<Record<string, string>>({});
  const [targetCoveredByReport, setTargetCoveredByReport] = useState<Record<string, boolean>>({});
  const [commentsByApproval, setCommentsByApproval] = useState<Record<string, string>>({});
  const [delegateByApproval, setDelegateByApproval] = useState<
    Record<string, { delegated_to_id: string; reason: string }>
  >({});
  const [delegatesByApproval, setDelegatesByApproval] = useState<
    Record<string, ApprovalDelegate[]>
  >({});
  const [delegateSearchByApproval, setDelegateSearchByApproval] = useState<Record<string, string>>(
    {}
  );
  const [delegateTotalByApproval, setDelegateTotalByApproval] = useState<Record<string, number>>(
    {}
  );
  const [delegateNextOffsetByApproval, setDelegateNextOffsetByApproval] = useState<
    Record<string, number>
  >({});
  const [delegateLoadingByApproval, setDelegateLoadingByApproval] = useState<
    Record<string, boolean>
  >({});
  const [tab, setTab] = useState<'reports' | 'workflow' | 'outbox'>(requestedTab);
  const [statusFilter, setStatusFilter] = useState('open');
  const [offset, setOffset] = useState(0);
  const [total, setTotal] = useState(0);
  const requestVersion = useRef(0);
  const [notice, setNotice] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [isLoading, setIsLoading] = useState(true);
  const approvalRefs = useRef<Record<string, HTMLElement | null>>({});
  const reportRefs = useRef<Record<string, HTMLElement | null>>({});
  // Re-entry guard for decision buttons: the ref blocks a second click in the same tick,
  // the state drives `disabled` so a double approve/reject cannot reach the server.
  const pendingActionsRef = useRef<Set<string>>(new Set());
  const [pendingActions, setPendingActions] = useState<Record<string, true>>({});
  // Ignore stale search responses so a slow earlier query cannot replace newer results.
  const delegateRequestVersionsRef = useRef<Record<string, number>>({});

  async function loadDelegates(
    approvalId: string,
    search = delegateSearchByApproval[approvalId] ?? '',
    pageOffset = 0,
    append = false
  ) {
    const requestVersion = (delegateRequestVersionsRef.current[approvalId] ?? 0) + 1;
    delegateRequestVersionsRef.current[approvalId] = requestVersion;
    setDelegateLoadingByApproval((current) => ({ ...current, [approvalId]: true }));
    try {
      const response = await listDelegationCandidates(approvalId, {
        search: search.trim() || undefined,
        limit: 50,
        offset: pageOffset
      });
      if (delegateRequestVersionsRef.current[approvalId] !== requestVersion) return;
      setDelegatesByApproval((current) => {
        const items = append ? [...(current[approvalId] ?? []), ...response.items] : response.items;
        const selectedId = delegateByApproval[approvalId]?.delegated_to_id;
        const selected = selectedId
          ? current[approvalId]?.find((candidate) => candidate.id === selectedId)
          : undefined;
        if (selected && !items.some((candidate) => candidate.id === selected.id)) {
          items.push(selected);
        }
        return { ...current, [approvalId]: items };
      });
      setDelegateTotalByApproval((current) => ({ ...current, [approvalId]: response.total }));
      setDelegateNextOffsetByApproval((current) => ({
        ...current,
        [approvalId]: pageOffset + response.items.length
      }));
    } catch {
      if (delegateRequestVersionsRef.current[approvalId] === requestVersion) {
        setError('Unable to load eligible delegates.');
      }
    } finally {
      if (delegateRequestVersionsRef.current[approvalId] === requestVersion) {
        setDelegateLoadingByApproval((current) => ({ ...current, [approvalId]: false }));
      }
    }
  }

  function isEntityPending(entityKey: string) {
    return pendingActions[entityKey] === true;
  }

  async function runAction(entityKey: string, action: () => Promise<void>) {
    if (pendingActionsRef.current.has(entityKey)) return;
    pendingActionsRef.current.add(entityKey);
    setPendingActions((current) => ({ ...current, [entityKey]: true }));
    try {
      await action();
    } finally {
      pendingActionsRef.current.delete(entityKey);
      setPendingActions((current) => {
        const next = { ...current };
        delete next[entityKey];
        return next;
      });
    }
  }

  const loadReports = useCallback(async () => {
    const version = ++requestVersion.current;
    setIsLoading(true);
    setError(null);
    try {
      if (tab === 'reports' && canApprove) {
        const response = await listDailyReports({ status: 'submitted' });
        const focusedReport =
          focusedReportId && !response.items.some((report) => report.id === focusedReportId)
            ? await getDailyReport(focusedReportId).catch(() => null)
            : null;
        if (version === requestVersion.current) {
          setReports(
            focusedReport?.status === 'submitted' ? [focusedReport, ...response.items] : response.items
          );
        }
        return;
      }
      const box = tab === 'workflow' && canApprove ? 'inbox' : 'outbox';
      const [genericResponse, focusedApproval] = await Promise.all([
        listApprovals({
          box,
          status_group: statusFilter === 'open' ? 'open' : 'all',
          status: ['open', 'all'].includes(statusFilter) ? undefined : statusFilter,
          limit: 20,
          offset
        }),
        focusedApprovalId
          ? getGenericApproval(focusedApprovalId).catch(() => null)
          : Promise.resolve(null)
      ]);
      if (version !== requestVersion.current) return;
      setTotal(genericResponse.total);
      setGenericApprovals(
        focusedApproval && !genericResponse.items.some((item) => item.id === focusedApproval.id)
          ? [focusedApproval, ...genericResponse.items]
          : genericResponse.items
      );
    } catch (cause) {
      if (version !== requestVersion.current) return;
      setReports([]);
      setGenericApprovals([]);
      setError(formatApiError(cause, 'Unable to load approvals.'));
    } finally {
      if (version === requestVersion.current) setIsLoading(false);
    }
  }, [canApprove, focusedApprovalId, focusedReportId, offset, statusFilter, tab]);

  useEffect(() => {
    void loadReports();
  }, [loadReports]);

  useEffect(() => {
    setTab(requestedTab);
  }, [requestedTab]);

  useEffect(() => {
    if (tab === 'reports' || !focusedApprovalId) return;
    const element = approvalRefs.current[focusedApprovalId];
    element?.scrollIntoView({ behavior: 'smooth', block: 'center' });
  }, [focusedApprovalId, genericApprovals, tab]);

  useEffect(() => {
    if (tab !== 'reports' || !focusedReportId) return;
    const element = reportRefs.current[focusedReportId];
    element?.scrollIntoView({ behavior: 'smooth', block: 'center' });
  }, [focusedReportId, reports, tab]);

  async function showDecisionError(cause: unknown, fallback: string) {
    const detail = formatApiError(cause, fallback);
    if (isAxiosError(cause) && cause.response?.status === 409) {
      await loadReports();
      setError((current) =>
        ['The approval changed while this page was open.', detail, current]
          .filter(Boolean)
          .join(' ')
      );
      return;
    }
    setError(detail);
  }

  async function approve(report: DailyReportRecord) {
    setError(null);
    setNotice(null);
    if (!targetCoveredByReport[report.id]) {
      setError('Confirm that the report target was covered before approval.');
      return;
    }
    try {
      const updated = await approveDailyReport(
        report.id,
        commentsByReport[report.id],
        targetCoveredByReport[report.id]
      );
      setNotice(`Approved ${updated.report_number}.`);
      await loadReports();
    } catch (cause) {
      await showDecisionError(cause, 'Unable to approve the report.');
    }
  }

  async function reject(report: DailyReportRecord) {
    setError(null);
    setNotice(null);
    const comments = commentsByReport[report.id]?.trim();
    if (!comments) {
      setError('Rejection reason is required.');
      return;
    }
    try {
      await rejectDailyReport(report.id, comments);
      setNotice('Report rejected and returned to draft.');
      await loadReports();
    } catch (cause) {
      await showDecisionError(cause, 'Unable to reject the report.');
    }
  }

  async function approveWorkflow(approval: ApprovalRecord) {
    setError(null);
    setNotice(null);
    try {
      await approveGenericApproval(
        approval.id, commentsByApproval[approval.id], approval.submission_revision
      );
      setNotice('Approval completed.');
      await loadReports();
    } catch (cause) {
      await showDecisionError(cause, 'Unable to approve the workflow item.');
    }
  }

  async function rejectWorkflow(approval: ApprovalRecord, returnForCorrection = false) {
    setError(null);
    setNotice(null);
    const comments = commentsByApproval[approval.id]?.trim();
    if (!comments) {
      setError('Rejection reason is required.');
      return;
    }
    try {
      await rejectGenericApproval(
        approval.id, comments, approval.submission_revision, returnForCorrection
      );
      setNotice(returnForCorrection ? 'Submission returned for correction.' : 'Approval rejected.');
      await loadReports();
    } catch (cause) {
      await showDecisionError(cause, 'Unable to reject the workflow item.');
    }
  }

  async function delegateWorkflow(approval: ApprovalRecord) {
    setError(null);
    setNotice(null);
    const payload = delegateByApproval[approval.id];
    if (!payload?.delegated_to_id.trim() || !payload.reason.trim()) {
      setError('Select a delegate and provide a reason.');
      return;
    }
    try {
      await delegateGenericApproval(approval.id, {
        delegated_to_id: payload.delegated_to_id.trim(),
        reason: payload.reason.trim(),
        expected_submission_revision: approval.submission_revision
      });
      setNotice('Approval delegated.');
      await loadReports();
    } catch (cause) {
      await showDecisionError(cause, 'Unable to delegate the workflow item.');
    }
  }

  return (
    <div className="space-y-6">
      <div className="flex flex-col justify-between gap-3 sm:flex-row sm:items-end">
        <div>
          <p className="text-sm font-medium text-brand-600">Approvals</p>
          <h2 className="text-2xl font-semibold text-theme-text-primary">Approvals</h2>
        </div>
        <StatusBadge tone="info">
          {isLoading ? 'Loading' : `${tab === 'reports' ? reports.length : total} matching`}
        </StatusBadge>
      </div>

      <div className="inline-flex rounded-md border border-theme-border bg-theme-card p-1">
        {canApprove && (
          <>
            <button
              className={`rounded px-3 py-2 text-sm font-medium ${
                tab === 'reports'
                  ? 'bg-brand-600 text-white'
                  : 'text-theme-text-secondary hover:bg-theme-card-elevated'
              }`}
              onClick={() => setTab('reports')}
              type="button"
            >
              Report approvals
            </button>
            <button
              className={`rounded px-3 py-2 text-sm font-medium ${
                tab === 'workflow'
                  ? 'bg-brand-600 text-white'
                  : 'text-theme-text-secondary hover:bg-theme-card-elevated'
              }`}
              onClick={() => {
                setTab('workflow');
                setOffset(0);
              }}
              type="button"
            >
              Inbox
            </button>
          </>
        )}
        <button
          className={`rounded px-3 py-2 text-sm font-medium ${tab === 'outbox' ? 'bg-brand-600 text-white' : 'text-theme-text-secondary'}`}
          onClick={() => {
            setTab('outbox');
            setOffset(0);
          }}
          type="button"
        >
          My submitted requests
        </button>
      </div>

      {tab !== 'reports' && (
        <div className="flex flex-wrap items-end gap-3">
          <label className="text-sm">
            Approval status
            <select
              className="form-field"
              value={statusFilter}
              onChange={(event) => {
                setStatusFilter(event.target.value);
                setOffset(0);
              }}
            >
              <option value="open">Open</option>
              <option value="all">All statuses</option>
              {[
                'pending',
                'delegated',
                'escalated',
                'approved',
                'rejected',
                'cancelled'
              ].map((status) => (
                <option value={status} key={status}>
                  {roleLabel(status)}
                </option>
              ))}
            </select>
          </label>
          <button
            type="button"
            className="form-button"
            disabled={offset === 0 || isLoading}
            onClick={() => setOffset(offset - 20)}
          >
            Previous
          </button>
          <button
            type="button"
            className="form-button"
            disabled={offset + 20 >= total || isLoading}
            onClick={() => setOffset(offset + 20)}
          >
            Next
          </button>
        </div>
      )}

      {notice ? (
        <div className="alert-success flex items-center gap-2 rounded-md px-3 py-2 text-sm">
          <Check className="h-4 w-4" />
          <span>{notice}</span>
        </div>
      ) : null}
      {error ? (
        <div
          className="alert-error flex items-center gap-2 rounded-md px-3 py-2 text-sm"
          role="alert"
        >
          <AlertTriangle className="h-4 w-4" />
          <span>{error}</span>
        </div>
      ) : null}

      {isLoading ? (
        <p role="status">Loading approvals…</p>
      ) : tab !== 'reports' ? (
        genericApprovals.length === 0 ? (
          <EmptyState
            description="Matching workflow requests will appear here."
            title="No workflow approvals"
          />
        ) : (
          <div className="grid gap-4">
            {genericApprovals.map((approval) => (
              <article
                className={`rounded-lg border bg-theme-card p-4 shadow-xs ${
                  approval.id === focusedApprovalId
                    ? 'border-brand-600 ring-2 ring-brand-600/20'
                    : 'border-theme-border'
                }`}
                key={approval.id}
                ref={(element) => {
                  approvalRefs.current[approval.id] = element;
                }}
              >
                <div className="flex flex-col justify-between gap-3 lg:flex-row lg:items-start">
                  <div>
                    <div className="flex flex-wrap items-center gap-2">
                      <h3 className="text-base font-semibold text-theme-text-primary">
                        {approval.title}
                      </h3>
                      <StatusBadge tone="info">{approval.status}</StatusBadge>
                    </div>
                    <p className="mt-1 text-sm text-theme-text-muted">
                      {approval.request_type} - due {new Date(approval.due_at).toLocaleString()}
                    </p>
                  </div>
                  {approval.submission_revision != null && (
                    <Link
                      className="text-brand-600 underline"
                      to={`/materials?materialRequestId=${approval.request_id}`}
                    >
                      View submission {approval.submission_revision}
                    </Link>
                  )}
                  {approval.amount ? (
                    <p className="text-sm font-medium text-theme-text-secondary">
                      {labelledAmount(approval.amount, approval.currency)}
                    </p>
                  ) : null}
                </div>
                <p className="mt-3 text-sm text-theme-text-secondary">
                  {approval.submitter_comments ?? 'No submitter comments.'}
                </p>
                {approval.decision_comments && (
                  <p className="mt-2 text-sm">{approval.decision_comments}</p>
                )}
                {approval.allowed_actions?.some(
                  (action) => action === 'approve' || action === 'reject'
                ) && (
                  <label className="mt-4 block">
                    <span className="mb-1 block text-sm font-medium text-theme-text-secondary">
                      Approval or rejection comments
                    </span>
                    <textarea
                      className="form-field min-h-20"
                      onChange={(event) =>
                        setCommentsByApproval({
                          ...commentsByApproval,
                          [approval.id]: event.target.value
                        })
                      }
                      value={commentsByApproval[approval.id] ?? ''}
                    />
                  </label>
                )}
                {approval.allowed_actions?.includes('delegate') && (
                  <div className="mt-4 grid gap-3 rounded-md border border-theme-border bg-theme-main p-3 lg:grid-cols-2">
                    {approval.allowed_actions?.includes('delegate') && (
                      <div>
                        <p className="text-sm font-semibold text-theme-text-primary">Delegate</p>
                        <div className="mt-2 grid gap-2">
                          <input
                            aria-label={`Search eligible approvers for ${approval.title}`}
                            className="form-field"
                            onChange={(event) => {
                              const search = event.target.value;
                              setDelegateSearchByApproval((current) => ({
                                ...current,
                                [approval.id]: search
                              }));
                              void loadDelegates(approval.id, search);
                            }}
                            placeholder="Search eligible approvers"
                            type="search"
                            value={delegateSearchByApproval[approval.id] ?? ''}
                          />
                          <select
                            aria-label={`Eligible approver for ${approval.title}`}
                            className="form-field"
                            onChange={(event) =>
                              setDelegateByApproval({
                                ...delegateByApproval,
                                [approval.id]: {
                                  delegated_to_id: event.target.value,
                                  reason: delegateByApproval[approval.id]?.reason ?? ''
                                }
                              })
                            }
                            onFocus={() => {
                              if (
                                !delegatesByApproval[approval.id]?.length &&
                                !delegateLoadingByApproval[approval.id]
                              ) {
                                void loadDelegates(approval.id);
                              }
                            }}
                            value={delegateByApproval[approval.id]?.delegated_to_id ?? ''}
                          >
                            <option value="">
                              {delegateOptionPrompt(
                                delegateLoadingByApproval[approval.id] ?? false,
                                delegateTotalByApproval[approval.id] ?? 0
                              )}
                            </option>
                            {(delegatesByApproval[approval.id] ?? []).map((candidate) => (
                              <option key={candidate.id} value={candidate.id}>
                                {candidate.full_name} — {roleLabel(candidate.role)}
                              </option>
                            ))}
                          </select>
                          <div className="flex flex-wrap items-center justify-between gap-2 text-xs text-theme-text-secondary">
                            <span role="status">
                              {delegateLoadingByApproval[approval.id]
                                ? 'Loading eligible approvers…'
                                : `Showing ${(delegatesByApproval[approval.id] ?? []).length} of ${delegateTotalByApproval[approval.id] ?? 0} eligible approvers`}
                            </span>
                            {(delegateNextOffsetByApproval[approval.id] ?? 0) <
                              (delegateTotalByApproval[approval.id] ?? 0) && (
                              <button
                                className="underline"
                                disabled={delegateLoadingByApproval[approval.id]}
                                onClick={() =>
                                  void loadDelegates(
                                    approval.id,
                                    delegateSearchByApproval[approval.id] ?? '',
                                    delegateNextOffsetByApproval[approval.id] ?? 0,
                                    true
                                  )
                                }
                                type="button"
                              >
                                Load more
                              </button>
                            )}
                          </div>
                          <input
                            className="form-field"
                            onChange={(event) =>
                              setDelegateByApproval({
                                ...delegateByApproval,
                                [approval.id]: {
                                  delegated_to_id:
                                    delegateByApproval[approval.id]?.delegated_to_id ?? '',
                                  reason: event.target.value
                                }
                              })
                            }
                            placeholder="Reason"
                            value={delegateByApproval[approval.id]?.reason ?? ''}
                          />
                          <button
                            className="inline-flex min-h-10 items-center justify-center gap-2 rounded-md border border-theme-border px-3 py-2 text-sm font-semibold text-theme-text-secondary hover:bg-theme-card disabled:cursor-not-allowed disabled:opacity-60"
                            disabled={isEntityPending(`approval:${approval.id}`)}
                            onClick={() =>
                              void runAction(`approval:${approval.id}`, () =>
                                delegateWorkflow(approval)
                              )
                            }
                            type="button"
                          >
                            <Forward className="h-4 w-4" />
                            Delegate
                          </button>
                        </div>
                      </div>
                    )}
                  </div>
                )}
                <div className="mt-4 flex flex-col-reverse gap-3 sm:flex-row sm:justify-end">
                  {approval.allowed_actions?.includes('return') && (
                    <button
                      className="form-button"
                      disabled={isEntityPending(`approval:${approval.id}`)}
                      onClick={() =>
                        void runAction(`approval:${approval.id}`, () => rejectWorkflow(approval, true))
                      }
                      type="button"
                    >
                      Return for correction
                    </button>
                  )}
                  {approval.allowed_actions?.includes('reject') && (
                    <button
                      className="btn-reject inline-flex min-h-11 items-center justify-center gap-2 rounded-md border px-4 py-2 text-sm font-semibold disabled:cursor-not-allowed disabled:opacity-60"
                      disabled={isEntityPending(`approval:${approval.id}`)}
                      onClick={() =>
                        void runAction(`approval:${approval.id}`, () => rejectWorkflow(approval))
                      }
                      type="button"
                    >
                      <X className="h-4 w-4" />
                      Reject
                    </button>
                  )}
                  {approval.allowed_actions?.includes('approve') && (
                    <button
                      className="inline-flex min-h-11 items-center justify-center gap-2 rounded-md bg-brand-600 px-4 py-2 text-sm font-semibold text-white hover:bg-brand-700 disabled:cursor-not-allowed disabled:opacity-60"
                      disabled={isEntityPending(`approval:${approval.id}`)}
                      onClick={() =>
                        void runAction(`approval:${approval.id}`, () => approveWorkflow(approval))
                      }
                      type="button"
                    >
                      <Check className="h-4 w-4" />
                      {approval.submission_revision != null && approval.step_order === 1
                        ? 'Verify'
                        : 'Approve'}
                    </button>
                  )}
                </div>
              </article>
            ))}
          </div>
        )
      ) : reports.length === 0 ? (
        <EmptyState
          description="Submitted engineer reports awaiting approval will appear here."
          title="No pending reports"
        />
      ) : (
        <div className="grid gap-4">
          {reports.map((report) => (
            <article
              className={`rounded-lg border bg-theme-card p-4 shadow-xs ${
                report.id === focusedReportId
                  ? 'border-brand-600 ring-2 ring-brand-600/20'
                  : 'border-theme-border'
              }`}
              key={report.id}
              ref={(element) => {
                reportRefs.current[report.id] = element;
              }}
            >
              <div className="flex flex-col justify-between gap-3 lg:flex-row lg:items-start">
                <div>
                  <div className="flex flex-wrap items-center gap-2">
                    <h3 className="text-base font-semibold text-theme-text-primary">
                      {report.report_number}
                    </h3>
                    <StatusBadge tone="info">{report.status}</StatusBadge>
                  </div>
                  <p className="mt-1 text-sm text-theme-text-muted">
                    {report.report_date} - {report.work_location}
                  </p>
                </div>
                <p className="text-sm font-medium text-theme-text-secondary">
                  {report.progress_percentage}% progress
                </p>
              </div>

              <div className="mt-4 grid gap-4 lg:grid-cols-2">
                <div>
                  <h4 className="text-sm font-semibold text-theme-text-primary">Work completed</h4>
                  <p className="mt-1 text-sm text-theme-text-secondary">{report.work_completed}</p>
                </div>
                <div>
                  <h4 className="text-sm font-semibold text-theme-text-primary">Next-day plan</h4>
                  <p className="mt-1 text-sm text-theme-text-secondary">{report.next_day_plan}</p>
                </div>
                <div>
                  <h4 className="text-sm font-semibold text-theme-text-primary">Safety</h4>
                  <p className="mt-1 text-sm text-theme-text-secondary">
                    {report.safety_incidents} incidents. {report.safety_notes || 'No notes.'}
                  </p>
                </div>
                <div>
                  <h4 className="text-sm font-semibold text-theme-text-primary">History</h4>
                  <p className="mt-1 text-sm text-theme-text-secondary">
                    {report.approval_history.length} workflow events recorded.
                  </p>
                </div>
              </div>

              {report.supervisor_update_ids.length > 0 && (
                <ReportSupervisorEvidence reportId={report.id} />
              )}

              <div className="mt-4">
                <label className="block">
                  <span className="mb-1 block text-sm font-medium text-theme-text-secondary">
                    Approval or rejection comments
                  </span>
                  <textarea
                    className="form-field min-h-20"
                    onChange={(event) =>
                      setCommentsByReport({
                        ...commentsByReport,
                        [report.id]: event.target.value
                      })
                    }
                    value={commentsByReport[report.id] ?? ''}
                  />
                </label>
                <label className="mt-3 flex items-start gap-2 rounded-md border border-theme-border bg-theme-main p-3 text-sm text-theme-text-secondary">
                  <input
                    checked={targetCoveredByReport[report.id] ?? false}
                    className="mt-1"
                    onChange={(event) =>
                      setTargetCoveredByReport({
                        ...targetCoveredByReport,
                        [report.id]: event.target.checked
                      })
                    }
                    type="checkbox"
                  />
                  <span>
                    Target covered confirmation reviewed against report content, attachments, and
                    history.
                  </span>
                </label>
              </div>

              <div className="mt-4 flex flex-col-reverse gap-3 sm:flex-row sm:justify-end">
                <button
                  className="btn-reject inline-flex min-h-11 items-center justify-center gap-2 rounded-md border px-4 py-2 text-sm font-semibold disabled:cursor-not-allowed disabled:opacity-60"
                  disabled={isEntityPending(`report:${report.id}`)}
                  onClick={() => void runAction(`report:${report.id}`, () => reject(report))}
                  type="button"
                >
                  <X className="h-4 w-4" />
                  Reject
                </button>
                <button
                  className="inline-flex min-h-11 items-center justify-center gap-2 rounded-md bg-brand-600 px-4 py-2 text-sm font-semibold text-white hover:bg-brand-700 disabled:cursor-not-allowed disabled:opacity-60"
                  disabled={isEntityPending(`report:${report.id}`)}
                  onClick={() => void runAction(`report:${report.id}`, () => approve(report))}
                  type="button"
                >
                  <Check className="h-4 w-4" />
                  Approve
                </button>
              </div>
            </article>
          ))}
        </div>
      )}
    </div>
  );
}
