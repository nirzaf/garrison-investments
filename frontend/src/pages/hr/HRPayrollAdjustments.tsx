import { useQuery } from '@tanstack/react-query';
import { useRef, useState, type FormEvent } from 'react';

import { formatApiError } from '../../api/errors';
import {
  proposePayrollAdjustment,
  readPayrollAdjustments,
  reviewPayrollAdjustment,
  type PayrollAdjustmentCreate
} from '../../api/hr';
import { hrButtonClass, hrInputClass } from './HRAccessForms';

const uuidPattern = '[0-9A-Fa-f]{8}(-[0-9A-Fa-f]{4}){3}-[0-9A-Fa-f]{12}';

export function HRPayrollAdjustments({ actorId }: { actorId: string }) {
  const [runId, setRunId] = useState('');
  const [pending, setPending] = useState(false);
  const [error, setError] = useState('');
  const [notice, setNotice] = useState('');
  const saving = useRef(false);
  const attempt = useRef<{ signature: string; id: string } | null>(null);
  const review = useQuery({
    queryKey: ['hr', 'payroll', actorId, 'adjustments', runId],
    queryFn: async ({ signal }) => {
      const result = await readPayrollAdjustments(runId, signal);
      if (result.run_id !== runId) throw new Error('Unexpected payroll run');
      return result;
    },
    enabled: Boolean(runId),
    gcTime: 0,
    retry: false
  });

  async function save(action: () => Promise<void>, message: string) {
    if (saving.current) return;
    saving.current = true;
    setPending(true);
    setError('');
    setNotice('');
    try {
      await action();
      await review.refetch();
      setNotice(message);
    } catch (failure) {
      setError(formatApiError(failure, 'Unable to save the payroll adjustment.'));
    } finally {
      saving.current = false;
      setPending(false);
    }
  }

  function propose(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (saving.current || !review.data?.can_submit) return;
    const form = event.currentTarget;
    const fields = new FormData(form);
    const kind = fields.get('kind');
    if (kind !== 'earning' && kind !== 'deduction') return;
    const amount = String(fields.get('amount'));
    if (!/[1-9]/.test(amount)) {
      setError('Enter a positive adjustment amount.');
      setNotice('');
      return;
    }
    const detail = {
      employee_id: String(fields.get('employee')).toLowerCase(),
      kind,
      amount,
      evidence_reference: String(fields.get('reference'))
    } satisfies Omit<PayrollAdjustmentCreate, 'adjustment_id'>;
    const signature = JSON.stringify({ runId, ...detail });
    if (attempt.current?.signature !== signature) {
      attempt.current = { signature, id: crypto.randomUUID() };
    }
    const id = attempt.current.id;
    void save(async () => {
      await proposePayrollAdjustment(runId, { ...detail, adjustment_id: id });
      attempt.current = null;
      form.reset();
    }, 'Payroll adjustment proposed.');
  }

  return (
    <section aria-label="Payroll adjustments" className="space-y-3 rounded border border-theme-border bg-theme-card p-4">
      <h3 className="font-semibold">Payroll adjustments</h3>
      <form className="space-y-2" onSubmit={(event) => {
        event.preventDefault();
        const id = String(new FormData(event.currentTarget).get('run')).toLowerCase();
        setError('');
        setNotice('');
        if (id === runId) void review.refetch();
        else setRunId(id);
      }}>
        <label className="block">Adjustment payroll run ID
          <input name="run" className={hrInputClass} pattern={uuidPattern} required disabled={pending} />
        </label>
        <button className={hrButtonClass} type="submit" disabled={pending}>Open run adjustments</button>
        {runId && <button className={hrButtonClass} type="button" disabled={pending} onClick={() => {
          setRunId('');
          setError('');
          setNotice('');
        }}>Close adjustments</button>}
      </form>
      {runId && review.isFetching && <p role="status">Loading payroll adjustments…</p>}
      {runId && review.isError && <p role="alert">{formatApiError(review.error, 'Unable to load payroll adjustments.')}</p>}
      {review.isSuccess && (
        <>
          {review.data.can_submit && (
            <form key={runId} aria-label="Propose payroll adjustment" className="space-y-2" onSubmit={propose}>
              <fieldset className="grid gap-2 sm:grid-cols-2" disabled={pending}>
                <label>Adjustment employee ID
                  <input name="employee" className={hrInputClass} pattern={uuidPattern} required />
                </label>
                <label>Adjustment type
                  <select name="kind" className={hrInputClass} required>
                    <option value="earning">Earning</option>
                    <option value="deduction">Deduction</option>
                  </select>
                </label>
                <label>Adjustment amount in policy currency
                  <input name="amount" className={hrInputClass} inputMode="decimal" required
                    pattern="(?:0|[1-9][0-9]{0,15})(?:\.[0-9]{1,2})?" />
                </label>
                <label>Approved evidence reference
                  <input name="reference" className={hrInputClass} maxLength={100} required />
                </label>
              </fieldset>
              <button className={hrButtonClass} type="submit" disabled={pending}>Propose payroll adjustment</button>
            </form>
          )}
          {review.data.items.length === 0 && <p>No adjustments recorded for this run.</p>}
          {review.data.items.length > 0 && (
            <ul className="space-y-2">
              {review.data.items.map((row) => (
                <li key={row.id} className="space-y-1 break-all border-t border-theme-border pt-2">
                  <p>{row.kind} · {row.amount} · {row.evidence_reference} · {row.status}</p>
                  <p className="text-sm">Employee <code>{row.employee_id}</code></p>
                  {review.data.can_review && row.status === 'submitted' && row.submitted_by_id !== actorId && (
                    <div className="flex gap-2">
                      <button className={hrButtonClass} type="button" disabled={pending} onClick={() => void save(
                        () => reviewPayrollAdjustment(runId, row.id, { decision: 'approved', expected_digest: row.digest }),
                        'Payroll adjustment approved.'
                      )}>Approve reviewed adjustment</button>
                      <button className={hrButtonClass} type="button" disabled={pending} onClick={() => void save(
                        () => reviewPayrollAdjustment(runId, row.id, { decision: 'rejected', expected_digest: row.digest }),
                        'Payroll adjustment rejected.'
                      )}>Reject reviewed adjustment</button>
                    </div>
                  )}
                </li>
              ))}
            </ul>
          )}
        </>
      )}
      {error && <p role="alert">{error}</p>}
      {notice && <p role="status">{notice}</p>}
    </section>
  );
}
