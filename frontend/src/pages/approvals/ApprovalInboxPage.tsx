import { AlertTriangle, Check, Forward, ShieldCheck, X } from 'lucide-react';
import { useCallback, useEffect, useState } from 'react';

import {
  approveGenericApproval,
  delegateGenericApproval,
  listApprovals,
  overrideGenericApproval,
  rejectGenericApproval,
  type ApprovalRecord
} from '../../api/approvals';
import {
  approveDailyReport,
  listDailyReports,
  rejectDailyReport,
  type DailyReportRecord
} from '../../api/reports';
import { EmptyState } from '../../components/shared/EmptyState';
import { StatusBadge } from '../../components/shared/StatusBadge';

export function ApprovalInboxPage() {
  const [reports, setReports] = useState<DailyReportRecord[]>([]);
  const [genericApprovals, setGenericApprovals] = useState<ApprovalRecord[]>([]);
  const [commentsByReport, setCommentsByReport] = useState<Record<string, string>>({});
  const [commentsByApproval, setCommentsByApproval] = useState<Record<string, string>>({});
  const [delegateByApproval, setDelegateByApproval] = useState<
    Record<string, { delegated_to_id: string; reason: string }>
  >({});
  const [overrideByApproval, setOverrideByApproval] = useState<
    Record<string, { decision: 'approved' | 'rejected'; reason: string }>
  >({});
  const [tab, setTab] = useState<'reports' | 'workflow'>('reports');
  const [notice, setNotice] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [isLoading, setIsLoading] = useState(true);

  const loadReports = useCallback(async () => {
    setIsLoading(true);
    setError(null);
    try {
      const response = await listDailyReports({ status: 'submitted' });
      setReports(response.items);
      const genericResponse = await listApprovals({ box: 'inbox', status: 'pending' });
      setGenericApprovals(genericResponse.items);
    } catch {
      setError('Unable to load approval inbox.');
    } finally {
      setIsLoading(false);
    }
  }, []);

  useEffect(() => {
    void loadReports();
  }, [loadReports]);

  async function approve(report: DailyReportRecord) {
    setError(null);
    setNotice(null);
    try {
      const updated = await approveDailyReport(report.id, commentsByReport[report.id]);
      setNotice(`Approved ${updated.report_number}.`);
      await loadReports();
    } catch {
      setError('Unable to approve the report.');
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
    } catch {
      setError('Unable to reject the report.');
    }
  }

  async function approveWorkflow(approval: ApprovalRecord) {
    setError(null);
    setNotice(null);
    try {
      await approveGenericApproval(approval.id, commentsByApproval[approval.id]);
      setNotice('Approval completed.');
      await loadReports();
    } catch {
      setError('Unable to approve the workflow item.');
    }
  }

  async function rejectWorkflow(approval: ApprovalRecord) {
    setError(null);
    setNotice(null);
    const comments = commentsByApproval[approval.id]?.trim();
    if (!comments) {
      setError('Rejection reason is required.');
      return;
    }
    try {
      await rejectGenericApproval(approval.id, comments);
      setNotice('Approval rejected.');
      await loadReports();
    } catch {
      setError('Unable to reject the workflow item.');
    }
  }

  async function delegateWorkflow(approval: ApprovalRecord) {
    setError(null);
    setNotice(null);
    const payload = delegateByApproval[approval.id];
    if (!payload?.delegated_to_id.trim() || !payload.reason.trim()) {
      setError('Delegate user ID and reason are required.');
      return;
    }
    try {
      await delegateGenericApproval(approval.id, {
        delegated_to_id: payload.delegated_to_id.trim(),
        reason: payload.reason.trim()
      });
      setNotice('Approval delegated.');
      await loadReports();
    } catch {
      setError('Unable to delegate the workflow item.');
    }
  }

  async function overrideWorkflow(approval: ApprovalRecord) {
    setError(null);
    setNotice(null);
    const payload = overrideByApproval[approval.id];
    if (!payload?.reason.trim()) {
      setError('Override reason is required.');
      return;
    }
    try {
      await overrideGenericApproval(approval.id, {
        decision: payload.decision,
        reason: payload.reason.trim()
      });
      setNotice(`Approval override ${payload.decision}.`);
      await loadReports();
    } catch {
      setError('Unable to override the workflow item.');
    }
  }

  return (
    <div className="space-y-6">
      <div className="flex flex-col justify-between gap-3 sm:flex-row sm:items-end">
        <div>
          <p className="text-sm font-medium text-brand-600">Approvals</p>
          <h2 className="text-2xl font-semibold text-theme-text-primary">Daily Report Inbox</h2>
        </div>
        <StatusBadge tone="info">
          {isLoading ? 'Loading' : `${reports.length + genericApprovals.length} pending`}
        </StatusBadge>
      </div>

      <div className="inline-flex rounded-md border border-theme-border bg-theme-card p-1">
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
          onClick={() => setTab('workflow')}
          type="button"
        >
          Workflow approvals
        </button>
      </div>

      {notice ? (
        <div className="alert-success flex items-center gap-2 rounded-md px-3 py-2 text-sm">
          <Check className="h-4 w-4" />
          <span>{notice}</span>
        </div>
      ) : null}
      {error ? (
        <div className="alert-error flex items-center gap-2 rounded-md px-3 py-2 text-sm">
          <AlertTriangle className="h-4 w-4" />
          <span>{error}</span>
        </div>
      ) : null}

      {tab === 'workflow' ? (
        genericApprovals.length === 0 ? (
          <EmptyState
            description="Material, invoice, document, and delegated approvals will appear here."
            title="No workflow approvals"
          />
        ) : (
          <div className="grid gap-4">
            {genericApprovals.map((approval) => (
              <article
                className="rounded-lg border border-theme-border bg-theme-card p-4 shadow-sm"
                key={approval.id}
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
                  {approval.amount ? (
                    <p className="text-sm font-medium text-theme-text-secondary">
                      {approval.currency ?? 'USD'} {approval.amount}
                    </p>
                  ) : null}
                </div>
                <p className="mt-3 text-sm text-theme-text-secondary">
                  {approval.submitter_comments ?? 'No submitter comments.'}
                </p>
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
                <div className="mt-4 grid gap-3 rounded-md border border-theme-border bg-theme-main p-3 lg:grid-cols-2">
                  <div>
                    <p className="text-sm font-semibold text-theme-text-primary">Delegate</p>
                    <div className="mt-2 grid gap-2">
                      <input
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
                        placeholder="Delegate user UUID"
                        value={delegateByApproval[approval.id]?.delegated_to_id ?? ''}
                      />
                      <input
                        className="form-field"
                        onChange={(event) =>
                          setDelegateByApproval({
                            ...delegateByApproval,
                            [approval.id]: {
                              delegated_to_id: delegateByApproval[approval.id]?.delegated_to_id ?? '',
                              reason: event.target.value
                            }
                          })
                        }
                        placeholder="Reason"
                        value={delegateByApproval[approval.id]?.reason ?? ''}
                      />
                      <button
                        className="inline-flex min-h-10 items-center justify-center gap-2 rounded-md border border-theme-border px-3 py-2 text-sm font-semibold text-theme-text-secondary hover:bg-theme-card"
                        onClick={() => void delegateWorkflow(approval)}
                        type="button"
                      >
                        <Forward className="h-4 w-4" />
                        Delegate
                      </button>
                    </div>
                  </div>
                  <div>
                    <p className="text-sm font-semibold text-theme-text-primary">Admin override</p>
                    <div className="mt-2 grid gap-2">
                      <select
                        className="form-field"
                        onChange={(event) =>
                          setOverrideByApproval({
                            ...overrideByApproval,
                            [approval.id]: {
                              decision: event.target.value as 'approved' | 'rejected',
                              reason: overrideByApproval[approval.id]?.reason ?? ''
                            }
                          })
                        }
                        value={overrideByApproval[approval.id]?.decision ?? 'approved'}
                      >
                        <option value="approved">Approve override</option>
                        <option value="rejected">Reject override</option>
                      </select>
                      <input
                        className="form-field"
                        onChange={(event) =>
                          setOverrideByApproval({
                            ...overrideByApproval,
                            [approval.id]: {
                              decision: overrideByApproval[approval.id]?.decision ?? 'approved',
                              reason: event.target.value
                            }
                          })
                        }
                        placeholder="Override reason"
                        value={overrideByApproval[approval.id]?.reason ?? ''}
                      />
                      <button
                        className="inline-flex min-h-10 items-center justify-center gap-2 rounded-md border border-theme-border px-3 py-2 text-sm font-semibold text-theme-text-secondary hover:bg-theme-card"
                        onClick={() => void overrideWorkflow(approval)}
                        type="button"
                      >
                        <ShieldCheck className="h-4 w-4" />
                        Override
                      </button>
                    </div>
                  </div>
                </div>
                <div className="mt-4 flex flex-col-reverse gap-3 sm:flex-row sm:justify-end">
                  <button
                    className="btn-reject inline-flex min-h-11 items-center justify-center gap-2 rounded-md border px-4 py-2 text-sm font-semibold"
                    onClick={() => void rejectWorkflow(approval)}
                    type="button"
                  >
                    <X className="h-4 w-4" />
                    Reject
                  </button>
                  <button
                    className="inline-flex min-h-11 items-center justify-center gap-2 rounded-md bg-brand-600 px-4 py-2 text-sm font-semibold text-white hover:bg-brand-700"
                    onClick={() => void approveWorkflow(approval)}
                    type="button"
                  >
                    <Check className="h-4 w-4" />
                    Approve
                  </button>
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
              className="rounded-lg border border-theme-border bg-theme-card p-4 shadow-sm"
              key={report.id}
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
              </div>

              <div className="mt-4 flex flex-col-reverse gap-3 sm:flex-row sm:justify-end">
                <button
                  className="btn-reject inline-flex min-h-11 items-center justify-center gap-2 rounded-md border px-4 py-2 text-sm font-semibold"
                  onClick={() => void reject(report)}
                  type="button"
                >
                  <X className="h-4 w-4" />
                  Reject
                </button>
                <button
                  className="inline-flex min-h-11 items-center justify-center gap-2 rounded-md bg-brand-600 px-4 py-2 text-sm font-semibold text-white hover:bg-brand-700"
                  onClick={() => void approve(report)}
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
