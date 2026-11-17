import { isAxiosError } from 'axios';
import { useEffect, useState, type FormEvent } from 'react';

import { formatApiError } from '../../api/errors';
import {
  getHrCase,
  listHrCases,
  createHrCase,
  updateHrCase,
  type HrSchemas
} from '../../api/hr';
import { hrInputClass } from './HRAccessForms';

type CaseList = HrSchemas['HrCaseListResponse'];
type NewCase = HrSchemas['HrCaseCreateRequest'];
type CaseStatus = HrSchemas['HrCaseCloseRequest']['status'];

const pageSize = 20;
const types = ['grievance', 'disciplinary', 'whistleblower', 'safety', 'other'] as const;
const severities = ['low', 'medium', 'high', 'critical'] as const;
const statuses = {
  investigating: 'Investigating',
  action_taken: 'Action taken',
  closed: 'Closed'
} satisfies Record<CaseStatus, string>;

function CaseReview({ id, onChange }: { id: string; onChange: () => void }) {
  const [review, setReview] = useState<Awaited<ReturnType<typeof getHrCase>>>();
  const [refresh, setRefresh] = useState(0);
  const [loading, setLoading] = useState(true);
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState('');
  const [loadError, setLoadError] = useState('');
  const [notice, setNotice] = useState('');
  const [status, setStatus] = useState<CaseStatus>('investigating');
  const [notes, setNotes] = useState('');

  useEffect(() => {
    const request = new AbortController();
    getHrCase(id, request.signal).then(
      (result) => {
        if (request.signal.aborted) return;
        setReview(result);
        setLoading(false);
      },
      (failure: unknown) => {
        if (request.signal.aborted) return;
        setLoadError(formatApiError(failure, 'Unable to load the case.'));
        setLoading(false);
      }
    );
    return () => request.abort();
  }, [id, refresh]);

  function reload() {
    setReview(undefined);
    setLoadError('');
    setError('');
    setLoading(true);
    setRefresh((number) => number + 1);
  }

  async function save(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (saving || !review) return;
    setSaving(true);
    setError('');
    setNotice('');
    try {
      await updateHrCase(id, {
        status,
        expected_state_sha256: review.digest,
        ...(notes.trim() ? { resolution_notes: notes.trim() } : {})
      });
      setNotes('');
      setNotice('Case updated.');
      reload();
      onChange();
    } catch (failure) {
      const message = formatApiError(failure, 'Unable to update the case.');
      const code = isAxiosError(failure) ? failure.response?.status : undefined;
      if (code === 401 || code === 403 || code === 404) {
        setReview(undefined);
        setNotes('');
        setLoadError(message);
        onChange();
      } else {
        setError(message);
      }
    } finally {
      setSaving(false);
    }
  }

  return (
    <section className="space-y-3 rounded-lg border border-theme-border bg-theme-card p-4">
      <div className="flex flex-wrap items-center justify-between gap-2">
        <h3 className="font-semibold">Case review</h3>
        <button type="button" onClick={reload} disabled={loading || saving}>Reload case</button>
      </div>
      {loading && <p role="status">Loading case…</p>}
      {notice && <p role="status">{notice}</p>}
      {loadError && <p role="alert">{loadError}</p>}
      {review && (
        <>
          <h4 className="font-medium">{review.data.title}</h4>
          <p>Case status {review.data.status.replace(/_/g, ' ')}</p>
          <p className="whitespace-pre-wrap break-words">{review.data.details_plain}</p>
          {review.data.resolution_notes && (
            <div>
              <h5 className="font-medium">Current resolution notes</h5>
              <p className="whitespace-pre-wrap break-words">{review.data.resolution_notes}</p>
            </div>
          )}
          {review.data.status !== 'closed' && (
            <form className="space-y-2" onSubmit={(event) => void save(event)}>
              <label className="block">
                New status
                <select
                  className={hrInputClass}
                  value={status}
                  onChange={(event) => setStatus(event.target.value as CaseStatus)}
                  disabled={saving}
                >
                  {Object.entries(statuses).map(([value, label]) => (
                    <option key={value} value={value}>{label}</option>
                  ))}
                </select>
              </label>
              <label className="block">
                New resolution notes
                <textarea
                  className={hrInputClass}
                  value={notes}
                  onChange={(event) => setNotes(event.target.value)}
                  disabled={saving}
                />
              </label>
              <p className="text-sm text-theme-text-muted">Leave blank to keep the current notes.</p>
              {error && <p role="alert">{error}</p>}
              <button className="rounded bg-brand-600 px-3 py-2 text-white" disabled={saving}>
                {saving ? 'Saving…' : 'Save case update'}
              </button>
            </form>
          )}
        </>
      )}
    </section>
  );
}

export function HRCasePage() {
  const [listing, setListing] = useState<CaseList>();
  const [offset, setOffset] = useState(0);
  const [selected, setSelected] = useState<string>();
  const [refresh, setRefresh] = useState(0);
  const [loadError, setLoadError] = useState('');
  const [createError, setCreateError] = useState('');
  const [creating, setCreating] = useState(false);

  useEffect(() => {
    const request = new AbortController();
    listHrCases(offset, pageSize, request.signal).then(
      (result) => {
        if (!request.signal.aborted) setListing(result);
      },
      (failure: unknown) => {
        if (!request.signal.aborted) {
          setLoadError(formatApiError(failure, 'Unable to load cases.'));
        }
      }
    );
    return () => request.abort();
  }, [offset, refresh]);

  function reloadList() {
    setListing(undefined);
    setLoadError('');
    setRefresh((number) => number + 1);
  }

  async function create(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (creating) return;
    const form = event.currentTarget;
    const fields = new FormData(form);
    const text = (key: string) => String(fields.get(key) ?? '').trim();
    setCreating(true);
    setCreateError('');
    try {
      const { id: caseId } = await createHrCase({
        case_code: text('case_code'),
        employee_id: text('employee_id') || null,
        case_type: text('case_type') as NewCase['case_type'],
        severity: text('severity') as NewCase['severity'],
        title: text('title'),
        details: text('details')
      });
      form.reset();
      setOffset(0);
      setSelected(caseId);
      reloadList();
    } catch (failure) {
      setCreateError(formatApiError(failure, 'Unable to open the case.'));
    } finally {
      setCreating(false);
    }
  }

  function changePage(next: number) {
    setListing(undefined);
    setOffset(next);
  }

  return (
    <div className="space-y-4">
      <h2 className="text-2xl font-semibold">Employee relations</h2>
      <form
        className="space-y-2 rounded-lg border border-theme-border bg-theme-card p-4"
        onSubmit={(event) => void create(event)}
      >
        <fieldset className="space-y-2" disabled={creating}>
          <legend className="font-semibold">Open a case</legend>
          <div className="grid gap-2 sm:grid-cols-2">
            <label>Case code<input className={hrInputClass} name="case_code" maxLength={40} required /></label>
            <label>Employee ID (optional)<input className={hrInputClass} name="employee_id" /></label>
            <label>
              Case type
              <select className={hrInputClass} name="case_type">
                {types.map((value) => <option key={value} value={value}>{value}</option>)}
              </select>
            </label>
            <label>
              Severity
              <select className={hrInputClass} name="severity" defaultValue="medium">
                {severities.map((value) => <option key={value} value={value}>{value}</option>)}
              </select>
            </label>
          </div>
          <label className="block">Case title<input className={hrInputClass} name="title" minLength={2} maxLength={200} required /></label>
          <label className="block">Case details<textarea className={hrInputClass} name="details" minLength={5} required /></label>
          {createError && <p role="alert">{createError}</p>}
          <button className="rounded bg-brand-600 px-3 py-2 text-white">
            {creating ? 'Opening…' : 'Open case'}
          </button>
        </fieldset>
      </form>

      <section className="space-y-2 rounded-lg border border-theme-border bg-theme-card p-4">
        <h3 className="font-semibold">Cases you opened</h3>
        {!listing && !loadError && <p role="status">Loading cases…</p>}
        {loadError && (
          <>
            <p role="alert">{loadError}</p>
            <button type="button" onClick={reloadList}>Retry case list</button>
          </>
        )}
        {listing && (
          <>
            {listing.total === 0 && <p>You have no cases.</p>}
            <ul className="space-y-2">
              {listing.items.map((item) => (
                <li key={item.id} className="flex flex-wrap items-center justify-between gap-2">
                  <span>{item.case_code} · {item.title} · {item.status.replace(/_/g, ' ')}</span>
                  <button type="button" onClick={() => setSelected(item.id)} aria-label={`Review ${item.case_code}`}>
                    Review case
                  </button>
                </li>
              ))}
            </ul>
            <nav className="flex gap-4" aria-label="Case list pages">
              <button type="button" disabled={offset === 0} onClick={() => changePage(offset - pageSize)}>Previous</button>
              <button type="button" disabled={offset + pageSize >= listing.total} onClick={() => changePage(offset + pageSize)}>Next</button>
            </nav>
          </>
        )}
      </section>

      {selected && (
        <>
          <button type="button" onClick={() => setSelected(undefined)}>Hide case details</button>
          <CaseReview key={selected} id={selected} onChange={reloadList} />
        </>
      )}
    </div>
  );
}
