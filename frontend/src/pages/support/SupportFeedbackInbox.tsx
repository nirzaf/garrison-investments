import { useEffect, useState, type FormEvent } from 'react';

import type { components } from '../../api/schema';
import { supportCsrf, supportRequest } from '../../api/support';
import { buttonClass, formatObserved, panelCardClass } from './supportPanelUtils';

type Report = components['schemas']['FeedbackInboxItem'];
type Inbox = components['schemas']['FeedbackInboxPage'];

const pageSize = 20;
const statusLabels: Record<Report['status'], string> = {
  new: 'New',
  investigating: 'Investigating',
  resolved: 'Resolved'
};
const categoryLabels: Record<Report['category'], string> = {
  bug: 'Bug report',
  suggestion: 'Suggestion',
  other: 'Other feedback'
};
const selectClass = 'min-h-10 rounded-md border border-theme-border bg-theme-card px-2 text-sm';

function StatusOptions() {
  return Object.entries(statusLabels).map(([value, label]) => (
    <option key={value} value={value}>
      {label}
    </option>
  ));
}

function ReportRow({
  report,
  onExpired,
  onSaved
}: {
  report: Report;
  onExpired: () => void;
  onSaved: () => void;
}) {
  const [status, setStatus] = useState(report.status);
  const [pending, setPending] = useState(false);
  const [error, setError] = useState('');

  async function save(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (pending || status === report.status) return;
    setPending(true);
    setError('');
    try {
      const headers = new Headers({ 'Content-Type': 'application/json' });
      const csrf = supportCsrf();
      if (csrf) headers.set('X-Support-CSRF', csrf);
      const response = await supportRequest(`/feedback/${report.id}/status`, {
        method: 'PATCH',
        headers,
        body: JSON.stringify({ status, expected_revision: report.revision })
      });
      if (response.status === 401) {
        onExpired();
      } else if (response.ok) {
        onSaved();
      } else if (response.status === 409) {
        setError('This report changed. Refresh the inbox and review its current status.');
      } else if (response.status === 403) {
        setError('Your session could not update this report.');
      } else {
        setError('The status could not be saved.');
      }
    } catch {
      setError('The status could not be saved.');
    } finally {
      setPending(false);
    }
  }

  return (
    <details className="rounded-lg border border-theme-border bg-theme-card">
      <summary className="cursor-pointer rounded-lg px-4 py-3 focus-visible:outline-2 focus-visible:outline-brand-600">
        <span className="break-words font-medium">{report.title}</span>
        <span className="mt-0.5 block text-xs text-theme-text-secondary">
          {statusLabels[report.status]} · {categoryLabels[report.category]} ·{' '}
          {formatObserved(report.created_at)} · {report.diagnostics.length} request summaries
        </span>
      </summary>
      <div className="space-y-4 border-t border-theme-border p-4 text-sm">
        <dl className="space-y-1 text-xs text-theme-text-secondary">
          <div>
            <dt className="inline">Report reference </dt>
            <dd className="inline break-all font-mono">{report.id}</dd>
          </div>
          <div>
            <dt className="inline">Reporter reference </dt>
            <dd className="inline break-all font-mono">
              {report.reporter_id ?? 'Account removed'}
            </dd>
          </div>
        </dl>
        <p className="break-words whitespace-pre-wrap">{report.description}</p>
        <section aria-label="Attached request summaries" className="space-y-2">
          <h3 className="font-semibold">Attached request summaries</h3>
          {report.diagnostics.length ? (
            <ul className="divide-y divide-theme-border">
              {report.diagnostics.map((entry) => (
                <li key={entry.request_id} className="py-2 text-xs">
                  <p>
                    <strong>
                      {entry.method} {entry.area} · HTTP {entry.status_code}
                    </strong>{' '}
                    · {formatObserved(entry.occurred_at)}
                  </p>
                  <code className="break-all text-theme-text-secondary">{entry.request_id}</code>
                </li>
              ))}
            </ul>
          ) : (
            <p className="text-theme-text-secondary">No request summaries attached.</p>
          )}
        </section>
        <form className="flex flex-wrap items-end gap-2" onSubmit={(event) => void save(event)}>
          <label className="grid gap-1">
            Report status
            <select
              className={selectClass}
              value={status}
              disabled={pending}
              onChange={(event) => setStatus(event.target.value as Report['status'])}
            >
              <StatusOptions />
            </select>
          </label>
          <button
            type="submit"
            className={`${buttonClass} min-h-10`}
            disabled={pending || status === report.status}
          >
            {pending ? 'Saving…' : 'Save status'}
          </button>
        </form>
        {error && (
          <p role="alert" className="text-red-700 dark:text-red-300">
            {error}
          </p>
        )}
      </div>
    </details>
  );
}

export function SupportFeedbackInbox({ onExpired }: { onExpired: () => void }) {
  const [status, setStatus] = useState<Report['status'] | 'all'>('new');
  const [offset, setOffset] = useState(0);
  const [refresh, setRefresh] = useState(0);
  const [data, setData] = useState<Inbox | null>(null);
  const [error, setError] = useState('');
  const [pending, setPending] = useState(true);

  useEffect(() => {
    const controller = new AbortController();
    async function load() {
      setPending(true);
      setError('');
      setData(null);
      try {
        const query = new URLSearchParams({ limit: String(pageSize), offset: String(offset) });
        if (status !== 'all') query.set('status', status);
        const response = await supportRequest(`/feedback?${query}`, { signal: controller.signal });
        if (controller.signal.aborted) return;
        if (response.status === 401) {
          onExpired();
        } else if (response.ok) {
          const next = (await response.json()) as Inbox;
          if (!controller.signal.aborted) setData(next);
        } else {
          setError(
            response.status === 403
              ? 'Your session cannot read the feedback inbox.'
              : 'Feedback could not be loaded.'
          );
        }
      } catch {
        if (!controller.signal.aborted) setError('Feedback could not be loaded.');
      } finally {
        if (!controller.signal.aborted) setPending(false);
      }
    }
    void load();
    return () => controller.abort();
  }, [status, offset, refresh, onExpired]);

  const reload = () => setRefresh((previous) => previous + 1);

  return (
    <section aria-labelledby="feedback-inbox-title" className={panelCardClass}>
      <div className="flex flex-wrap items-end justify-between gap-3">
        <div>
          <h2 id="feedback-inbox-title" className="text-lg font-semibold">
            Feedback inbox
          </h2>
          <p className="mt-1 text-sm text-theme-text-secondary">
            Triage reports and suggestions submitted by portal users.
          </p>
        </div>
        <div className="flex items-end gap-2">
          <label className="grid gap-1 text-sm">
            Status filter
            <select
              className={selectClass}
              value={status}
              onChange={(event) => {
                setStatus(event.target.value as typeof status);
                setOffset(0);
              }}
            >
              <option value="all">All statuses</option>
              <StatusOptions />
            </select>
          </label>
          <button
            type="button"
            className={`${buttonClass} min-h-10`}
            disabled={pending}
            onClick={reload}
          >
            Refresh inbox
          </button>
        </div>
      </div>
      {pending && (
        <p role="status" className="text-sm text-theme-text-secondary">
          Loading feedback…
        </p>
      )}
      {error && (
        <p role="alert" className="text-sm text-red-700 dark:text-red-300">
          {error}
        </p>
      )}
      {data && !data.items.length && (
        <p className="text-sm text-theme-text-secondary">No feedback matches this filter.</p>
      )}
      {data?.items.map((report) => (
        <ReportRow
          key={`${report.id}:${report.revision}`}
          report={report}
          onExpired={onExpired}
          onSaved={reload}
        />
      ))}
      {(offset > 0 || data?.has_more) && (
        <div className="flex items-center gap-3 text-sm">
          <button
            type="button"
            className={buttonClass}
            disabled={offset === 0 || pending}
            onClick={() => setOffset((previous) => Math.max(0, previous - pageSize))}
          >
            Previous page
          </button>
          <span>Page {offset / pageSize + 1}</span>
          <button
            type="button"
            className={buttonClass}
            disabled={!data?.has_more || pending}
            onClick={() => setOffset((previous) => previous + pageSize)}
          >
            Next page
          </button>
        </div>
      )}
    </section>
  );
}
