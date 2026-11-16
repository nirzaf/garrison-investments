import { useQuery } from '@tanstack/react-query';
import { useEffect, useRef, useState, type FormEvent } from 'react';

import { formatApiError } from '../../api/errors';
import {
  decideCompensationTerm,
  listCompensationTerms,
  proposeCompensationTerm,
  revealCompensationTerm,
  type CompensationTerm,
  type HrSchemas
} from '../../api/hr';
import { hrButtonClass, hrInputClass } from './HRAccessForms';

type Props = {
  employeeId: string;
  employeeUserId?: string | null;
  actorId: string;
  canReview: boolean;
};

type Proposal = HrSchemas['CompensationTermCreateRequest'];

export function HRCompensation(props: Props) {
  const [open, setOpen] = useState(false);
  return (
    <details
      className="rounded border border-theme-border p-3"
      onToggle={(event) => setOpen(event.currentTarget.open)}
    >
      <summary className="cursor-pointer font-semibold">Compensation history</summary>
      {open && <CompensationPanel {...props} />}
    </details>
  );
}

function CompensationPanel({ employeeId, employeeUserId, actorId, canReview }: Props) {
  const [privateTerm, setPrivateTerm] = useState<CompensationTerm | null>(null);
  const [revealing, setRevealing] = useState(false);
  const [writing, setWriting] = useState(false);
  const [message, setMessage] = useState('');
  const [error, setError] = useState('');
  const revealRequest = useRef<AbortController | null>(null);
  const activeWrite = useRef(false);
  const history = useQuery({
    queryKey: ['hr', 'compensation', actorId, employeeId],
    queryFn: ({ signal }) => listCompensationTerms(employeeId, signal),
    gcTime: 0,
    retry: false
  });

  useEffect(() => () => revealRequest.current?.abort(), []);

  function hidePrivateTerms() {
    revealRequest.current?.abort();
    setPrivateTerm(null);
    setRevealing(false);
  }

  async function reveal(termId: string) {
    if (activeWrite.current) return;
    hidePrivateTerms();
    const controller = new AbortController();
    revealRequest.current = controller;
    setError('');
    setRevealing(true);
    try {
      const row = await revealCompensationTerm(employeeId, termId, controller.signal);
      if (controller.signal.aborted) return;
      if (!row) {
        setError('Unable to open the selected compensation term.');
        return;
      }
      setPrivateTerm(row);
    } catch (err) {
      if (!controller.signal.aborted) {
        setError(formatApiError(err, 'Unable to open the selected compensation term.'));
      }
    } finally {
      if (!controller.signal.aborted) setRevealing(false);
    }
  }

  async function write(save: () => Promise<void>, success: string) {
    if (activeWrite.current) return;
    activeWrite.current = true;
    setWriting(true);
    setMessage('');
    setError('');
    try {
      await save();
      hidePrivateTerms();
      setMessage(success);
      await history.refetch();
    } catch (err) {
      setError(formatApiError(err, 'Unable to save the compensation record.'));
    } finally {
      activeWrite.current = false;
      setWriting(false);
    }
  }

  function propose(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (!history.isSuccess || history.data.some((term) => term.approval_status === 'proposed')) {
      return;
    }
    const form = event.currentTarget;
    const fields = new FormData(form);
    const rawAllowances = String(fields.get('allowances') ?? '').trim();
    let allowances: Proposal['allowances_json'] = null;
    if (rawAllowances) {
      try {
        const parsed: unknown = JSON.parse(rawAllowances);
        if (typeof parsed !== 'object' || parsed === null || Array.isArray(parsed)) throw new Error();
        allowances = parsed as NonNullable<Proposal['allowances_json']>;
      } catch {
        setError('Enter allowances as a JSON object or leave the field blank.');
        return;
      }
    }
    void write(async () => {
      await proposeCompensationTerm({
        employee_id: employeeId,
        effective_from: String(fields.get('effective_from')),
        pay_frequency: String(fields.get('frequency')) as Proposal['pay_frequency'],
        currency: String(fields.get('currency')).trim().toUpperCase(),
        base_salary: String(fields.get('base_salary')).trim(),
        allowances_json: allowances
      });
      form.reset();
    }, 'Compensation term sent for independent review.');
  }

  const canDecide =
    canReview &&
    privateTerm?.approval_status === 'proposed' &&
    Boolean(privateTerm.proposed_by_id) &&
    privateTerm.proposed_by_id !== actorId &&
    employeeUserId !== actorId;
  const pendingTerm = history.data?.some((term) => term.approval_status === 'proposed');

  return (
    <section className="mt-3 space-y-3" aria-label="Compensation terms">
      {error && <p role="alert">{error}</p>}
      {message && <p role="status">{message}</p>}
      {history.isPending && <p role="status">Loading compensation history…</p>}
      {history.isError && (
        <p role="alert">
          {formatApiError(history.error, 'Unable to load compensation history.')}{' '}
          <button className={hrButtonClass} type="button" onClick={() => void history.refetch()}>
            Retry
          </button>
        </p>
      )}
      {history.data?.length === 0 && <p>No compensation terms recorded.</p>}
      {history.data && history.data.length > 0 && (
        <ul className="space-y-2">
          {history.data.map((term) => (
            <li key={term.id} className="flex flex-wrap items-center justify-between gap-2">
              <span>
                {term.effective_from} · {term.currency} · {term.pay_frequency} ·{' '}
                <span><Status term={term} /></span>
              </span>
              <button
                className={hrButtonClass}
                type="button"
                disabled={writing || privateTerm?.id === term.id}
                onClick={() => void reveal(term.id)}
              >
                Reveal term for {term.effective_from}
              </button>
            </li>
          ))}
        </ul>
      )}
      {revealing && <p role="status">Opening private terms…</p>}
      {privateTerm && (
        <article className="space-y-2 rounded border border-theme-border p-3">
          <header className="flex flex-wrap items-center justify-between gap-2">
            <h4 className="font-semibold">Private term effective {privateTerm.effective_from}</h4>
            <button type="button" className={hrButtonClass} onClick={hidePrivateTerms}>
              Hide private terms
            </button>
          </header>
          <p>Base salary {privateTerm.currency} {privateTerm.base_salary_plain}</p>
          {privateTerm.allowances_json && (
            <details>
              <summary>Allowances</summary>
              <pre className="whitespace-pre-wrap break-all">
                {JSON.stringify(privateTerm.allowances_json, null, 2)}
              </pre>
            </details>
          )}
          {privateTerm.rejection_reason && <p>Reason for rejection: {privateTerm.rejection_reason}</p>}
          {canDecide && (
            <form
              className="space-y-2"
              onSubmit={(event) => {
                event.preventDefault();
                const reason = String(new FormData(event.currentTarget).get('reason')).trim();
                if (!reason) {
                  setError('Give a reason for rejecting the proposal.');
                  return;
                }
                void write(async () => {
                  await decideCompensationTerm(privateTerm.id, { decision: 'reject', reason });
                }, 'Compensation proposal rejected.');
              }}
            >
              <label className="block">
                Rejection reason
                <textarea className={hrInputClass} name="reason" required maxLength={1000} />
              </label>
              <div className="flex flex-wrap gap-2">
                <button className={hrButtonClass} type="submit" disabled={writing}>
                  Reject proposal
                </button>
                <button
                  className={hrButtonClass}
                  type="button"
                  disabled={writing}
                  onClick={() => void write(async () => {
                    await decideCompensationTerm(privateTerm.id, { decision: 'approve' });
                  }, 'Compensation proposal approved.')}
                >
                  Approve reviewed term
                </button>
              </div>
            </form>
          )}
        </article>
      )}
      {history.isSuccess && !pendingTerm && (
        <form className="space-y-2 border-t border-theme-border pt-3" onSubmit={propose}>
          <h4 className="font-semibold">Propose compensation</h4>
          <fieldset className="grid gap-2 sm:grid-cols-2" disabled={writing}>
            <label>
              Effective date
              <input className={hrInputClass} name="effective_from" type="date" required />
            </label>
            <label>
              Pay frequency
              <select className={hrInputClass} name="frequency">
                <option value="monthly">Monthly</option>
                <option value="biweekly">Biweekly</option>
                <option value="weekly">Weekly</option>
                <option value="daily">Daily</option>
              </select>
            </label>
            <label>
              Currency code
              <input className={hrInputClass} name="currency" pattern="[A-Za-z]{3}" required />
            </label>
            <label>
              Base salary
              <input
                className={hrInputClass}
                name="base_salary"
                type="password"
                inputMode="decimal"
                autoComplete="off"
                maxLength={19}
                pattern="[0-9]{1,16}(\.[0-9]{1,2})?"
                required
              />
            </label>
            <label className="sm:col-span-2">
              Allowances (optional JSON object)
              <textarea className={hrInputClass} name="allowances" rows={2} autoComplete="off" />
            </label>
          </fieldset>
          <button className={hrButtonClass} type="submit" disabled={writing}>
            Submit compensation proposal
          </button>
        </form>
      )}
    </section>
  );
}

function Status({ term }: { term: CompensationTerm }) {
  if (term.is_current) return <>Current approved term</>;
  if (term.approval_status === 'proposed') return <>Pending independent review</>;
  if (term.approval_status === 'rejected') return <>Rejected</>;
  return <>Approved</>;
}
