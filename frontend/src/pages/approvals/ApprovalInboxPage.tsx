import { AlertTriangle, Check, X } from 'lucide-react';
import { useCallback, useEffect, useState } from 'react';

import {
  approveGenericApproval,
  listApprovals,
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

  return (
    <div className="space-y-6">
      <div className="flex flex-col justify-between gap-3 sm:flex-row sm:items-end">
        <div>
          <p className="text-sm font-medium text-brand-700">Approvals</p>
          <h2 className="text-2xl font-semibold text-slate-950">Daily Report Inbox</h2>
        </div>
        <StatusBadge tone="info">
          {isLoading ? 'Loading' : `${reports.length + genericApprovals.length} pending`}
        </StatusBadge>
      </div>

      <div className="inline-flex rounded-md border border-slate-300 bg-white p-1">
        <button
          className={`rounded px-3 py-2 text-sm font-medium ${
            tab === 'reports' ? 'bg-brand-700 text-white' : 'text-slate-700 hover:bg-slate-100'
          }`}
          onClick={() => setTab('reports')}
          type="button"
        >
          Report approvals
        </button>
        <button
          className={`rounded px-3 py-2 text-sm font-medium ${
            tab === 'workflow' ? 'bg-brand-700 text-white' : 'text-slate-700 hover:bg-slate-100'
          }`}
          onClick={() => setTab('workflow')}
          type="button"
        >
          Workflow approvals
        </button>
      </div>

      {notice ? (
        <div className="flex items-center gap-2 rounded-md bg-emerald-50 px-3 py-2 text-sm text-emerald-800">
          <Check className="h-4 w-4" />
          <span>{notice}</span>
        </div>
      ) : null}
      {error ? (
        <div className="flex items-center gap-2 rounded-md bg-red-50 px-3 py-2 text-sm text-red-700">
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
                className="rounded-lg border border-slate-200 bg-white p-4 shadow-sm"
                key={approval.id}
              >
                <div className="flex flex-col justify-between gap-3 lg:flex-row lg:items-start">
                  <div>
                    <div className="flex flex-wrap items-center gap-2">
                      <h3 className="text-base font-semibold text-slate-950">{approval.title}</h3>
                      <StatusBadge tone="info">{approval.status}</StatusBadge>
                    </div>
                    <p className="mt-1 text-sm text-slate-500">
                      {approval.request_type} - due {new Date(approval.due_at).toLocaleString()}
                    </p>
                  </div>
                  {approval.amount ? (
                    <p className="text-sm font-medium text-slate-700">
                      {approval.currency ?? 'USD'} {approval.amount}
                    </p>
                  ) : null}
                </div>
                <p className="mt-3 text-sm text-slate-600">
                  {approval.submitter_comments ?? 'No submitter comments.'}
                </p>
                <label className="mt-4 block">
                  <span className="mb-1 block text-sm font-medium text-slate-700">
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
                <div className="mt-4 flex flex-col-reverse gap-3 sm:flex-row sm:justify-end">
                  <button
                    className="inline-flex min-h-11 items-center justify-center gap-2 rounded-md border border-red-300 px-4 py-2 text-sm font-semibold text-red-700 hover:bg-red-50"
                    onClick={() => void rejectWorkflow(approval)}
                    type="button"
                  >
                    <X className="h-4 w-4" />
                    Reject
                  </button>
                  <button
                    className="inline-flex min-h-11 items-center justify-center gap-2 rounded-md bg-brand-700 px-4 py-2 text-sm font-semibold text-white hover:bg-brand-800"
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
              className="rounded-lg border border-slate-200 bg-white p-4 shadow-sm"
              key={report.id}
            >
              <div className="flex flex-col justify-between gap-3 lg:flex-row lg:items-start">
                <div>
                  <div className="flex flex-wrap items-center gap-2">
                    <h3 className="text-base font-semibold text-slate-950">
                      {report.report_number}
                    </h3>
                    <StatusBadge tone="info">{report.status}</StatusBadge>
                  </div>
                  <p className="mt-1 text-sm text-slate-500">
                    {report.report_date} - {report.work_location}
                  </p>
                </div>
                <p className="text-sm font-medium text-slate-700">
                  {report.progress_percentage}% progress
                </p>
              </div>

              <div className="mt-4 grid gap-4 lg:grid-cols-2">
                <div>
                  <h4 className="text-sm font-semibold text-slate-950">Work completed</h4>
                  <p className="mt-1 text-sm text-slate-600">{report.work_completed}</p>
                </div>
                <div>
                  <h4 className="text-sm font-semibold text-slate-950">Next-day plan</h4>
                  <p className="mt-1 text-sm text-slate-600">{report.next_day_plan}</p>
                </div>
                <div>
                  <h4 className="text-sm font-semibold text-slate-950">Safety</h4>
                  <p className="mt-1 text-sm text-slate-600">
                    {report.safety_incidents} incidents. {report.safety_notes || 'No notes.'}
                  </p>
                </div>
                <div>
                  <h4 className="text-sm font-semibold text-slate-950">History</h4>
                  <p className="mt-1 text-sm text-slate-600">
                    {report.approval_history.length} workflow events recorded.
                  </p>
                </div>
              </div>

              <div className="mt-4">
                <label className="block">
                  <span className="mb-1 block text-sm font-medium text-slate-700">
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
                  className="inline-flex min-h-11 items-center justify-center gap-2 rounded-md border border-red-300 px-4 py-2 text-sm font-semibold text-red-700 hover:bg-red-50"
                  onClick={() => void reject(report)}
                  type="button"
                >
                  <X className="h-4 w-4" />
                  Reject
                </button>
                <button
                  className="inline-flex min-h-11 items-center justify-center gap-2 rounded-md bg-brand-700 px-4 py-2 text-sm font-semibold text-white hover:bg-brand-800"
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
