import { useQuery } from '@tanstack/react-query';
import { useRef, useState, type FormEvent } from 'react';

import { formatApiError } from '../../api/errors';
import {
  decidePayrollCorrection,
  listPayrollCorrections,
  proposePayrollCorrection,
  type PayrollCorrectionCreate,
  type PayrollSnapshot
} from '../../api/hr';
import { hrButtonClass, hrInputClass } from './HRAccessForms';

type Props = {
  runId: string;
  snapshotDigest: string;
  actorId: string;
  canPropose: boolean;
  canReview: boolean;
  lines: PayrollSnapshot['lines'];
};

const amountPattern = '(?:0|[1-9][0-9]{0,15})(?:\\.[0-9]{1,2})?';

export function HRPayrollCorrections({ runId, snapshotDigest, actorId, canPropose, canReview, lines }: Props) {
  const [lineId, setLineId] = useState('');
  const [offset, setOffset] = useState(0);
  const [pending, setPending] = useState(false);
  const [error, setError] = useState('');
  const [notice, setNotice] = useState('');
  const saving = useRef(false);
  const attempt = useRef<{ signature: string; id: string } | null>(null);
  const history = useQuery({
    queryKey: ['hr', 'payroll-corrections', actorId, runId, snapshotDigest, lineId, offset],
    queryFn: async ({ signal }) => {
      const items = await listPayrollCorrections(runId, lineId, offset, signal);
      if (items.line_id !== lineId) throw new Error('Unexpected payroll line');
      return items;
    },
    enabled: Boolean(lineId),
    gcTime: 0,
    retry: false
  });

  async function save(action: () => Promise<void>, success: string) {
    if (saving.current) return;
    saving.current = true;
    setPending(true);
    setError('');
    setNotice('');
    try {
      await action();
      await history.refetch();
      setNotice(success);
    } catch (failure) {
      setError(formatApiError(failure, 'Unable to save this payroll correction.'));
    } finally {
      saving.current = false;
      setPending(false);
    }
  }

  function propose(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (saving.current || !history.data || !canPropose) return;
    const form = event.currentTarget;
    const fields = new FormData(form);
    const detail = {
      expected_snapshot_digest: snapshotDigest,
      expected_previous_id: history.data.current_correction_id,
      gross: String(fields.get('gross')),
      deductions: String(fields.get('deductions')),
      evidence_reference: String(fields.get('evidence')).trim()
    } satisfies Omit<PayrollCorrectionCreate, 'correction_id'>;
    const signature = JSON.stringify({ lineId, ...detail });
    if (attempt.current?.signature !== signature) {
      attempt.current = { signature, id: crypto.randomUUID() };
    }
    const correctionId = attempt.current.id;
    void save(async () => {
      await proposePayrollCorrection(runId, lineId, { ...detail, correction_id: correctionId });
      attempt.current = null;
      form.reset();
    }, 'Payroll correction proposed.');
  }

  return (
    <section aria-label="Closed payroll corrections" className="space-y-3 border-t border-theme-border pt-3">
      <h5 className="font-semibold">Closed payroll corrections</h5>
      <p className="text-sm">Reviewed corrections document revised amounts for Finance follow-up. Original payroll records stay available.</p>
      <label className="block">Employee for correction
        <select className={hrInputClass} value={lineId} disabled={pending} onChange={(event) => {
          setLineId(event.target.value);
          setOffset(0);
          setError('');
          setNotice('');
        }}>
          <option value="">Select a payroll employee</option>
          {lines.map((line) => (
            <option key={line.payment_reference} value={line.payment_reference}>{line.employee_id}</option>
          ))}
        </select>
      </label>
      {lineId && history.isFetching && <p role="status">Loading correction history…</p>}
      {history.isError && (
        <p role="alert">{formatApiError(history.error, 'Unable to load correction history.')}{' '}
          <button className={hrButtonClass} type="button" onClick={() => void history.refetch()}>Retry corrections</button>
        </p>
      )}
      {history.isSuccess && (
        <>
          <p>Current reviewed net {history.data.currency} {history.data.baseline.net}</p>
          {canPropose && offset === 0 && !history.data.items.some((item) => item.status === 'submitted') && (
            <form key={lineId} aria-label="Propose payroll correction" className="space-y-2" onSubmit={propose}>
              <fieldset className="grid gap-2 sm:grid-cols-2" disabled={pending || history.isFetching}>
                <label>Corrected gross<input className={hrInputClass} name="gross" inputMode="decimal" pattern={amountPattern} required /></label>
                <label>Corrected deductions<input className={hrInputClass} name="deductions" inputMode="decimal" pattern={amountPattern} required /></label>
                <label>Correction evidence reference<input className={hrInputClass} name="evidence" maxLength={100} required /></label>
              </fieldset>
              <button className={hrButtonClass} type="submit" disabled={pending || history.isFetching}>Propose payroll correction</button>
            </form>
          )}
          {history.data.total === 0 && <p>No corrections for this payroll line.</p>}
          {history.data.items.length > 0 && (
            <ul className="space-y-2">
              {history.data.items.map((row) => (
                <li key={row.id} className="space-y-1 break-all border-t border-theme-border pt-2">
                  <p>{row.evidence_reference} · {row.status}</p>
                  <p>Gross {row.currency} {row.baseline.gross} → {row.proposed.gross} · Deductions {row.currency} {row.baseline.deductions} → {row.proposed.deductions}</p>
                  <p>Previous net {row.currency} {row.baseline.net} · Proposed net {row.currency} {row.proposed.net} · Net change {row.currency} {row.net_delta}</p>
                  {row.previous_id && <p className="text-sm">Previous correction <code>{row.previous_id}</code></p>}
                  <p className="text-sm">Correction <code>{row.id}</code></p>
                  {canReview && row.status === 'submitted' && row.submitted_by_id !== actorId && (
                    <div className="flex gap-2">
                      <button className={hrButtonClass} type="button" disabled={pending} onClick={() => void save(
                        () => decidePayrollCorrection(runId, lineId, row.id, { decision: 'approved', expected_digest: row.digest }),
                        'Payroll correction approved.'
                      )}>Approve correction</button>
                      <button className={hrButtonClass} type="button" disabled={pending} onClick={() => void save(
                        () => decidePayrollCorrection(runId, lineId, row.id, { decision: 'rejected', expected_digest: row.digest }),
                        'Payroll correction rejected.'
                      )}>Reject correction</button>
                    </div>
                  )}
                </li>
              ))}
            </ul>
          )}
          {history.data.total > 20 && (
            <div className="flex gap-2">
              <button className={hrButtonClass} type="button" disabled={pending || offset === 0}
                onClick={() => setOffset(offset - 20)}>Previous corrections</button>
              <button className={hrButtonClass} type="button" disabled={pending || offset + 20 >= history.data.total}
                onClick={() => setOffset(offset + 20)}>Next corrections</button>
            </div>
          )}
        </>
      )}
      {error && <p role="alert">{error}</p>}
      {notice && <p role="status">{notice}</p>}
    </section>
  );
}
