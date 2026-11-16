import { useQuery } from '@tanstack/react-query';
import { useRef, useState, type FormEvent } from 'react';

import { formatApiError } from '../../api/errors';
import {
  decideLeaveDateEvidence,
  listMissingLeaveDates,
  proposeLeaveDateEvidence,
  readLeaveDateEvidence,
  type LeaveDateEvidenceCreate
} from '../../api/hr';
import { hrButtonClass, hrInputClass } from './HRAccessForms';

const uuidPattern = '[0-9A-Fa-f]{8}(-[0-9A-Fa-f]{4}){3}-[0-9A-Fa-f]{12}';

export function HRLeaveDateEvidence({ actorId }: { actorId: string }) {
  const [requestId, setRequestId] = useState('');
  const [requestInput, setRequestInput] = useState('');
  const [finding, setFinding] = useState(false);
  const [candidateOffset, setCandidateOffset] = useState(0);
  const [offset, setOffset] = useState(0);
  const [pending, setPending] = useState(false);
  const [notice, setNotice] = useState('');
  const [error, setError] = useState('');
  const saving = useRef(false);
  const attempt = useRef<{ signature: string; id: string } | null>(null);

  const evidence = useQuery({
    queryKey: ['hr', 'leave-date-evidence', actorId, requestId, offset],
    queryFn: async ({ signal }) => {
      const page = await readLeaveDateEvidence(requestId, offset, signal);
      if (page.request_id !== requestId) throw new Error('Unexpected leave request');
      return page;
    },
    enabled: Boolean(requestId),
    gcTime: 0,
    retry: false
  });
  const data = evidence.isSuccess ? evidence.data : undefined;
  const candidates = useQuery({
    queryKey: ['hr', 'missing-leave-dates', actorId, candidateOffset],
    queryFn: ({ signal }) => listMissingLeaveDates(candidateOffset, signal),
    enabled: finding,
    gcTime: 0,
    retry: false
  });

  function openRequest(id: string) {
    setRequestInput(id);
    setError('');
    setNotice('');
    if (id === requestId && offset === 0) void evidence.refetch();
    else {
      setOffset(0);
      setRequestId(id);
    }
  }


  async function save(action: () => Promise<void>, message: string) {
    if (saving.current) return;
    saving.current = true;
    setPending(true);
    setNotice('');
    setError('');
    try {
      await action();
      await evidence.refetch();
      if (finding) await candidates.refetch();
      setNotice(message);
    } catch (failure) {
      setError(formatApiError(failure, 'Unable to save the historical leave dates.'));
    } finally {
      saving.current = false;
      setPending(false);
    }
  }

  function propose(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (!data?.can_propose || saving.current) return;
    const form = event.currentTarget;
    const fields = new FormData(form);
    const dates = String(fields.get('dates')).trim().split(/[\s,]+/).sort();
    if (dates.some((date) => !/^\d{4}-\d{2}-\d{2}$/.test(date)) || dates.length !== new Set(dates).size) {
      setError('Enter each historical work date once using YYYY-MM-DD.');
      setNotice('');
      return;
    }
    const detail = {
      expected_revision: data.request_revision,
      work_dates: dates,
      evidence_reference: String(fields.get('reference')).trim()
    } satisfies Omit<LeaveDateEvidenceCreate, 'proposal_id'>;
    const signature = JSON.stringify({ requestId, ...detail });
    if (attempt.current?.signature !== signature) attempt.current = { signature, id: crypto.randomUUID() };
    const proposalId = attempt.current.id;
    void save(async () => {
      await proposeLeaveDateEvidence(requestId, { ...detail, proposal_id: proposalId });
      attempt.current = null;
      form.reset();
    }, 'Historical dates proposed.');
  }

  return (
    <section aria-label="Legacy leave work dates" className="space-y-3 rounded border border-theme-border bg-theme-card p-4">
      <h3 className="font-semibold">Legacy leave work dates</h3>
      <p className="text-sm">Use historical evidence for approved leave spanning months when the work dates are missing.</p>
      <form className="space-y-2" onSubmit={(event) => {
        event.preventDefault();
        openRequest(requestInput.toLowerCase());
      }}>
        <label className="block">Legacy leave request ID
          <input className={hrInputClass} name="request" pattern={uuidPattern} required disabled={pending}
            value={requestInput} onChange={(event) => setRequestInput(event.target.value)} />
        </label>
        <button className={hrButtonClass} type="submit" disabled={pending}>Open historical work dates</button>
      </form>
      <button className={hrButtonClass} type="button" disabled={pending || candidates.isFetching}
        onClick={() => {
          if (finding) void candidates.refetch();
          else setFinding(true);
        }}>
        {finding ? 'Refresh missing dates list' : 'Find leave with missing work dates'}
      </button>
      {finding && candidates.isFetching && <p role="status">Finding missing work dates…</p>}
      {finding && candidates.isError && <p role="alert">{formatApiError(candidates.error, 'Unable to find legacy requests.')}</p>}
      {finding && candidates.isSuccess && !candidates.isFetching && (
        <>
          {candidates.data.total === 0 ? <p>No approved cross-month leave is missing work dates.</p> : (
            <>
              <ul aria-label="Requests missing historical dates" className="space-y-2">
                {candidates.data.items.map((row) => (
                  <li key={row.request_id} className="space-y-1 border-t border-theme-border pt-2">
                    <p>{row.start_date} to {row.end_date} · Approved days {row.approved_units}</p>
                    <p className="break-all text-sm">Employee <code>{row.employee_id}</code></p>
                    {row.requires_payroll_correction && <p>Approved payroll already covers these dates.</p>}
                    <button className={hrButtonClass} type="button" disabled={pending}
                      onClick={() => openRequest(row.request_id)}>View historical request</button>
                  </li>
                ))}
              </ul>
              <div className="flex gap-2">
                <button className={hrButtonClass} type="button" disabled={pending || !candidateOffset}
                  onClick={() => setCandidateOffset(candidateOffset - 20)}>Previous requests</button>
                <button className={hrButtonClass} type="button"
                  disabled={pending || candidateOffset + 20 >= candidates.data.total}
                  onClick={() => setCandidateOffset(candidateOffset + 20)}>Next requests</button>
              </div>
            </>
          )}
        </>
      )}
      {requestId && evidence.isFetching && <p role="status">Loading historical leave…</p>}
      {evidence.isError && <p role="alert">{formatApiError(evidence.error, 'Unable to open this leave request.')}</p>}
      {data && (
        <>
          <p>Approved range {data.start_date} to {data.end_date} · Approved days {data.approved_units}</p>
          {data.scheduled_work_dates && <p>Retained work dates: {data.scheduled_work_dates.join(', ')}</p>}
          {data.requires_payroll_correction && <p>Use payroll corrections for dates covered by approved payroll.</p>}
          {!data.requires_payroll_correction && !data.can_propose && !data.scheduled_work_dates && <p>This request is unavailable for historical date review.</p>}
          {data.can_propose && offset === 0 && !data.items.some((item) => item.status === 'submitted') && (
            <form key={requestId} className="space-y-2" onSubmit={propose}>
              <fieldset className="grid gap-2" disabled={pending || evidence.isFetching}>
                <label>Historical work dates
                  <textarea className={hrInputClass} name="dates" required rows={3} />
                </label>
                <label>Historical evidence reference
                  <input className={hrInputClass} name="reference" required maxLength={100} />
                </label>
              </fieldset>
              <button className={hrButtonClass} type="submit" disabled={pending || evidence.isFetching}>Propose historical dates</button>
            </form>
          )}
          {data.items.length > 0 && (
            <ul className="space-y-2">
              {data.items.map((row) => (
                <li key={row.id} className="space-y-1 break-all border-t border-theme-border pt-2">
                  <p>{row.evidence_reference} · {row.status}</p>
                  <p>{row.work_dates.join(', ')}</p>
                  {data.can_review && row.status === 'submitted' && row.submitted_by_id !== actorId && (
                    <div className="flex gap-2">
                      {!data.requires_payroll_correction && (
                        <button className={hrButtonClass} type="button" disabled={pending} onClick={() => void save(
                          () => decideLeaveDateEvidence(requestId, row.id, { decision: 'approved', expected_digest: row.digest }),
                          'Historical work dates retained.'
                        )}>Approve historical dates</button>
                      )}
                      <button className={hrButtonClass} type="button" disabled={pending} onClick={() => void save(
                        () => decideLeaveDateEvidence(requestId, row.id, { decision: 'rejected', expected_digest: row.digest }),
                        'Historical work dates rejected.'
                      )}>Reject historical dates</button>
                    </div>
                  )}
                </li>
              ))}
            </ul>
          )}
          {data.total > 20 && (
            <div className="flex gap-2">
              <button className={hrButtonClass} type="button" disabled={pending || !offset} onClick={() => setOffset(offset - 20)}>Previous proposals</button>
              <button className={hrButtonClass} type="button" disabled={pending || offset + 20 >= data.total} onClick={() => setOffset(offset + 20)}>Next proposals</button>
            </div>
          )}
        </>
      )}
      {notice && <p role="status">{notice}</p>}
      {error && <p role="alert">{error}</p>}
    </section>
  );
}
