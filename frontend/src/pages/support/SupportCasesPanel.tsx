import { useEffect, useState, type FormEvent } from 'react';

import type { components } from '../../api/schema';
import { supportPost, supportRequest } from '../../api/support';
import { SupportCaseProposal } from './SupportCaseActionsPanel';
import { SupportTimelinePanel } from './SupportTimelinePanel';

type Case = components['schemas']['SupportCaseRead'];
type CasePage = components['schemas']['SupportCasePage'];
type CaseCreate = components['schemas']['SupportCaseCreate'];
type Transition = components['schemas']['SupportCaseTransition'];

const reasons: Record<CaseCreate['reason_code'], string> = {
  availability: 'Availability',
  access: 'Access',
  functional: 'Functionality',
  data_integrity: 'Data integrity'
};
const statusLabels: Record<Case['status'], string> = {
  open: 'Open', investigating: 'Investigating', mitigated: 'Mitigated',
  verified: 'Verified', closed: 'Closed'
};
const initialForm: CaseCreate = { external_ref: '', severity: 'medium', reason_code: 'availability' };

function ReasonOptions() {
  return Object.entries(reasons).map(([value, label]) => (
    <option key={value} value={value}>{label}</option>
  ));
}

export function SupportCasesPanel({ onExpired, operatorId, canReadDirectory, canReadTimeline, canReviewProjectScope }: {
  onExpired: () => void; operatorId: string; canReadDirectory: boolean; canReadTimeline: boolean;
  canReviewProjectScope: boolean;
}) {
  const [form, setForm] = useState<CaseCreate>(initialForm);
  const [reason, setReason] = useState<Transition['reason_code']>('availability');
  const [page, setPage] = useState<CasePage | null>(null);
  const [selected, setSelected] = useState<Case | null>(null);
  const [cursor, setCursor] = useState<string | null>(null);
  const [refresh, setRefresh] = useState(0);
  const [loading, setLoading] = useState(true);
  const [listError, setListError] = useState('');
  const [actionError, setActionError] = useState('');
  const [pending, setPending] = useState(false);

  useEffect(() => {
    const controller = new AbortController();
    const query = cursor ? '?cursor=' + encodeURIComponent(cursor) : '';
    void supportRequest('/cases' + query, { signal: controller.signal })
      .then(async (response) => {
        if (controller.signal.aborted) return;
        if (response.status === 401) {
          onExpired();
          return;
        }
        if (!response.ok) throw new Error();
        const result = await response.json() as CasePage;
        if (!controller.signal.aborted) setPage(result);
      })
      .catch(() => {
        if (!controller.signal.aborted) setListError('Cases could not be loaded.');
      })
      .finally(() => {
        if (!controller.signal.aborted) setLoading(false);
      });
    return () => controller.abort();
  }, [cursor, refresh, onExpired]);

  function reload(next: string | null) {
    setLoading(true);
    setListError('');
    setCursor(next);
    setRefresh((value) => value + 1);
  }

  async function create(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (pending) return;
    setPending(true);
    setActionError('');
    try {
      const response = await supportPost('/cases', form);
      if (response.status === 401) {
        onExpired();
        return;
      }
      if (response.status === 409) {
        setActionError('That case reference cannot be used. Enter a different reference.');
        return;
      }
      if (!response.ok) throw new Error();
      setSelected(await response.json() as Case);
      setForm(initialForm);
      reload(null);
    } catch {
      setActionError('The case could not be created.');
    } finally {
      setPending(false);
    }
  }

  async function selectCase(id: string) {
    if (pending) return;
    setPending(true);
    setSelected(null);
    setActionError('');
    try {
      const response = await supportRequest('/cases/' + encodeURIComponent(id));
      if (response.status === 401) {
        onExpired();
        return;
      }
      if (!response.ok) throw new Error();
      setSelected(await response.json() as Case);
      setReason('availability');
    } catch {
      setActionError('This case could not be opened.');
    } finally {
      setPending(false);
    }
  }

  async function transition(status: Transition['status']) {
    if (!selected || pending) return;
    setPending(true);
    setActionError('');
    try {
      const response = await supportPost(
        '/cases/' + encodeURIComponent(selected.id) + '/transitions',
        { status, reason_code: reason },
        { headers: { 'If-Match': '"' + selected.revision + '"' } }
      );
      if (response.status === 401) {
        onExpired();
        return;
      }
      if (response.status === 409) {
        setActionError('The case changed. Reopen it before trying again.');
        return;
      }
      if (!response.ok) throw new Error();
      setSelected(await response.json() as Case);
      reload(cursor);
    } catch {
      setActionError('The case status could not be updated.');
    } finally {
      setPending(false);
    }
  }

  return (
    <section aria-label="Support cases" className="space-y-4">
      <h2 className="font-semibold">Support cases</h2>
      <form className="space-y-2" onSubmit={(event) => void create(event)}>
        <label className="block">
          Incident reference
          <input
            className="block w-full rounded border p-2" maxLength={120} pattern="[A-Za-z0-9_.\\-]+"
            required value={form.external_ref}
            onChange={(event) => setForm({ ...form, external_ref: event.target.value })}
          />
        </label>
        <label className="block">
          Severity
          <select
            value={form.severity}
            onChange={(event) =>
              setForm({ ...form, severity: event.target.value as CaseCreate['severity'] })}
            className="block rounded border p-2"
          >
            <option value="low">Low</option><option value="medium">Medium</option>
            <option value="high">High</option><option value="critical">Critical</option>
          </select>
        </label>
        <label className="block">
          Case reason
          <select
            value={form.reason_code}
            onChange={(event) =>
              setForm({ ...form, reason_code: event.target.value as CaseCreate['reason_code'] })}
            className="block rounded border p-2"
          ><ReasonOptions /></select>
        </label>
        <button type="submit" disabled={pending}>Create case</button>
      </form>
      {pending && <p role="status">Working…</p>}
      {actionError && <p role="alert">{actionError}</p>}
      {loading && <p role="status">Loading cases…</p>}
      {listError && <p role="alert">{listError} <button type="button" onClick={() => reload(null)}>Retry</button></p>}
      {!loading && !listError && page && (
        <>
          {page.items.length === 0 && <p>No assigned cases.</p>}
          <ul className="space-y-2">
            {page.items.map((item) => (
              <li key={item.id}>
                <button type="button" disabled={pending} onClick={() => void selectCase(item.id)}>
                  {item.external_ref} · {statusLabels[item.status]}
                </button>
              </li>
            ))}
          </ul>
          <div className="flex gap-4">
            {cursor && <button type="button" onClick={() => reload(null)}>First page</button>}
            {page.next_cursor && (
              <button type="button" onClick={() => reload(page.next_cursor)}>Next page</button>
            )}
          </div>
        </>
      )}
      {selected && (
        <section aria-label="Case details" className="space-y-2 border-t pt-3">
          <h3 className="font-semibold">{selected.external_ref}</h3>
          <p>{statusLabels[selected.status]}</p>
          <p className="break-all">Case ID {selected.id}</p>
          {canReadTimeline && <SupportTimelinePanel key={selected.id} caseId={selected.id} onExpired={onExpired} />}
          {selected.owner_id === operatorId && selected.status !== 'closed' && (
            <SupportCaseProposal key={selected.id} onExpired={onExpired}
              selected={selected} disabled={pending} canReadDirectory={canReadDirectory}
              canReviewProjectScope={canReviewProjectScope} />
          )}
          {(selected.status === 'open' || selected.status === 'investigating') && (
            <>
              <label className="block">
                Transition reason
                <select
                  value={reason}
                  onChange={(event) => setReason(event.target.value as Transition['reason_code'])}
                  className="block rounded border p-2"
                ><ReasonOptions /></select>
              </label>
              <button
                type="button" disabled={pending}
                onClick={() => void transition(selected.status === 'open' ? 'investigating' : 'mitigated')}
              >
                {selected.status === 'open' ? 'Start investigation' : 'Mark mitigated'}
              </button>
            </>
          )}
        </section>
      )}
    </section>
  );
}
