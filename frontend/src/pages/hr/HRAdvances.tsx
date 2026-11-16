import { useQuery, useQueryClient } from '@tanstack/react-query';
import { useEffect, useRef, useState, type FormEvent } from 'react';

import { formatApiError } from '../../api/errors';
import {
  confirmAdvanceDisbursement,
  decideEmployeeAdvance,
  getEmployeeAdvance,
  listEmployeeAdvanceCoverage,
  listEmployeeAdvances,
  recordAdvanceRepayment,
  submitEmployeeAdvance,
  type EmployeeAdvance,
  type HrSchemas
} from '../../api/hr';
import { hrButtonClass, hrInputClass } from './HRAccessForms';

type Props = {
  employeeId: string;
  employeeUserId?: string | null;
  actorId: string;
  canReview: boolean;
};
type Decision = HrSchemas['EmployeeAdvanceDecision']['decision'];

const pageSize = 20;
const amountPattern = '[0-9]{1,13}(\\.[0-9]{1,2})?';
const statusLabels: Record<string, string> = {
  submitted: 'Pending independent review',
  approved: 'Approved for disbursement',
  disbursed: 'Disbursement recorded',
  settled: 'Fully repaid',
  rejected: 'Rejected',
  cancelled: 'Cancelled'
};

export function HRAdvances(props: Props) {
  const [open, setOpen] = useState(false);
  return (
    <details
      className="rounded border border-theme-border p-3"
      onToggle={(event) => setOpen(event.currentTarget.open)}
    >
      <summary className="cursor-pointer font-semibold">Employee advances</summary>
      {open && <AdvancePanel {...props} />}
    </details>
  );
}

function AdvancePanel({ employeeId, employeeUserId, actorId, canReview }: Props) {
  const client = useQueryClient();
  const [offset, setOffset] = useState(0);
  const [selected, setSelected] = useState('');
  const [assignmentId, setAssignmentId] = useState('');
  const [writing, setWriting] = useState(false);
  const [error, setError] = useState('');
  const [notice, setNotice] = useState('');
  const writeInProgress = useRef(false);
  const mounted = useRef(false);
  const submission = useRef<{ payload: string; key: string } | null>(null);
  const baseKey = ['hr', 'advances', actorId, employeeId];
  const detailKey = [...baseKey, 'detail', selected];
  const history = useQuery({
    queryKey: [...baseKey, 'history', offset],
    queryFn: ({ signal }) => listEmployeeAdvances(employeeId, offset, signal),
    retry: false,
    gcTime: 0
  });
  const coverage = useQuery({
    queryKey: [...baseKey, 'coverage'],
    queryFn: ({ signal }) => listEmployeeAdvanceCoverage(employeeId, signal),
    retry: false,
    gcTime: 0
  });
  const detail = useQuery({
    queryKey: detailKey,
    queryFn: async ({ signal }) => {
      const row = await getEmployeeAdvance(selected, signal);
      if (row.id !== selected || row.employee_id !== employeeId) {
        throw new Error('Unexpected advance record');
      }
      return row;
    },
    enabled: Boolean(selected),
    retry: false,
    gcTime: 0
  });
  const assignment = coverage.data?.find((item) => item.id === assignmentId);
  const row = detail.data;

  useEffect(() => {
    mounted.current = true;
    return () => { mounted.current = false; };
  }, []);

  async function save(action: () => Promise<EmployeeAdvance>, message: string) {
    if (writeInProgress.current) return false;
    writeInProgress.current = true;
    setWriting(true);
    setError('');
    setNotice('');
    try {
      const saved = await action();
      if (saved.employee_id !== employeeId) throw new Error('Unexpected employee');
      if (!mounted.current) return false;
      client.setQueryData([...baseKey, 'detail', saved.id], saved);
      setSelected(saved.id);
      setNotice(message);
      await client.invalidateQueries({ queryKey: [...baseKey, 'history'] });
      return true;
    } catch (err) {
      setError(formatApiError(err, 'Unable to save the advance. Refresh the record to verify its state.'));
      return false;
    } finally {
      writeInProgress.current = false;
      setWriting(false);
    }
  }

  async function submit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (!assignment || writeInProgress.current) return;
    const form = event.currentTarget;
    const fields = new FormData(form);
    const payload = {
      employee_id: employeeId,
      benefit_assignment_id: assignment.id,
      requested_on: String(fields.get('date')),
      amount: String(fields.get('amount')),
      currency: assignment.currency
    };
    const serialized = JSON.stringify(payload);
    if (submission.current?.payload !== serialized) {
      submission.current = { payload: serialized, key: crypto.randomUUID() };
    }
    const { key } = submission.current;
    if (await save(() => submitEmployeeAdvance(payload, key), 'Advance submitted.')) {
      submission.current = null;
      setOffset(0);
      setAssignmentId('');
      form.reset();
    }
  }

  async function recordPayment(event: FormEvent<HTMLFormElement>, current: EmployeeAdvance) {
    event.preventDefault();
    const form = event.currentTarget;
    const fields = new FormData(form);
    const payload = {
      occurred_on: String(fields.get('date')),
      amount: String(fields.get('amount')),
      reference: String(fields.get('reference')).trim(),
      currency: current.currency
    };
    const digest = current.payable_sha256;
    if (!payload.reference) {
      setError('Enter the external payment reference.');
      return;
    }
    if (current.status === 'approved' && digest) {
      await save(
        () => confirmAdvanceDisbursement(current.id, { ...payload, expected_payable_sha256: digest }),
        'External disbursement recorded.'
      );
    } else if (current.status === 'disbursed') {
      if (await save(() => recordAdvanceRepayment(current.id, payload), 'External repayment recorded.')) {
        form.reset();
      }
    }
  }

  function decide(current: EmployeeAdvance, decision: Decision) {
    const message = { approved: 'Advance approved.', rejected: 'Advance rejected.', cancelled: 'Advance cancelled.' };
    void save(() => decideEmployeeAdvance(current.id, { decision }), message[decision]);
  }

  const independent =
    canReview && row?.submitted_by_id && row.submitted_by_id !== actorId && employeeUserId !== actorId;
  const canRecord = Boolean(independent && row?.decided_by_id && row.decided_by_id !== actorId);
  const recordDisbursement = row?.status === 'approved' && Boolean(row.payable_sha256);

  return (
    <section className="mt-3 space-y-3" aria-label="Advance records">
      {error && <p role="alert">{error}</p>}
      {notice && <p role="status">{notice}</p>}
      {history.isPending && <p role="status">Loading advances…</p>}
      {history.isError && (
        <p role="alert">
          {formatApiError(history.error, 'Unable to load advances.')}{' '}
          <button className={hrButtonClass} type="button" onClick={() => void history.refetch()}>
            Retry advance list
          </button>
        </p>
      )}
      {history.data?.total === 0 && <p>No advances recorded.</p>}
      {history.data && history.data.items.length > 0 && (
        <ul className="space-y-2">
          {history.data.items.map((item) => (
            <li key={item.id} className="flex flex-wrap items-center justify-between gap-2">
              <span>{item.requested_on} · {statusLabels[item.status] ?? item.status}</span>
              <button
                className={hrButtonClass}
                type="button"
                disabled={writing}
                onClick={() => { setSelected(item.id); setError(''); setNotice(''); }}
              >
                Open advance
              </button>
            </li>
          ))}
        </ul>
      )}
      {history.data && history.data.total > pageSize && (
        <div className="flex gap-2">
          <button className={hrButtonClass} type="button" disabled={!offset || writing}
            onClick={() => setOffset(offset - pageSize)}>
            Previous advances
          </button>
          <button className={hrButtonClass} type="button"
            disabled={offset + pageSize >= history.data.total || writing}
            onClick={() => setOffset(offset + pageSize)}>
            Next advances
          </button>
        </div>
      )}
      {selected && detail.isPending && <p role="status">Opening advance…</p>}
      {selected && detail.isError && (
        <p role="alert">
          {formatApiError(detail.error, 'Unable to open this advance.')}{' '}
          <button className={hrButtonClass} type="button" onClick={() => void detail.refetch()}>
            Retry advance details
          </button>
        </p>
      )}
      {selected && row && (
        <article className="space-y-2 rounded border border-theme-border p-3" aria-label="Advance detail">
          <header className="flex flex-wrap items-center justify-between gap-2">
            <h4 className="font-semibold">Advance requested {row.requested_on}</h4>
            <button className={hrButtonClass} type="button" disabled={writing} onClick={() => setSelected('')}>
              Close advance
            </button>
          </header>
          <p>{statusLabels[row.status] ?? row.status}</p>
          <dl className="grid grid-cols-2 gap-1">
            <dt>Principal</dt><dd>{row.currency} {row.amount}</dd>
            <dt>Recovered</dt><dd>{row.currency} {row.recovered}</dd>
            <dt>Outstanding</dt><dd>{row.currency} {row.outstanding}</dd>
            {row.disbursed_on && <><dt>Disbursed on</dt><dd>{row.disbursed_on}</dd></>}
            {row.disbursement_reference && (
              <><dt>Disbursement reference</dt><dd className="break-all">{row.disbursement_reference}</dd></>
            )}
          </dl>
          {row.recoveries.length > 0 && (
            <ul aria-label="Recorded repayments" className="space-y-1">
              {row.recoveries.map((item) => (
                <li key={item.reference}>{item.occurred_on} · {row.currency} {item.amount} · {item.reference}</li>
              ))}
            </ul>
          )}
          <button className={hrButtonClass} type="button" disabled={writing} onClick={() => void detail.refetch()}>
            Refresh advance
          </button>
          {row.status === 'submitted' && independent && (
            <div className="flex flex-wrap gap-2">
              <button className={hrButtonClass} type="button" disabled={writing}
                onClick={() => decide(row, 'approved')}>Approve advance</button>
              <button className={hrButtonClass} type="button" disabled={writing}
                onClick={() => decide(row, 'rejected')}>Reject advance</button>
              <button className={hrButtonClass} type="button" disabled={writing}
                onClick={() => decide(row, 'cancelled')}>Cancel advance</button>
            </div>
          )}
          {recordDisbursement && (
            <button className={hrButtonClass} type="button" onClick={() => downloadPayable(row)}>
              Download approved payable
            </button>
          )}
          {canRecord && (recordDisbursement || row.status === 'disbursed') && (
            <form key={`${row.id}:${row.status}`} className="space-y-2"
              onSubmit={(event) => void recordPayment(event, row)}>
              <fieldset disabled={writing} className="grid gap-2 sm:grid-cols-2">
                <label>
                  External reference
                  <input className={hrInputClass} name="reference" maxLength={100} required />
                </label>
                <label>
                  Payment date
                  <input type="date" className={hrInputClass} name="date"
                    min={row.disbursed_on ?? row.requested_on} required />
                </label>
                <label>
                  Actual amount ({row.currency})
                  <input className={hrInputClass} name="amount" inputMode="decimal" pattern={amountPattern} required />
                </label>
              </fieldset>
              <button className={hrButtonClass} type="submit" disabled={writing}>
                {recordDisbursement ? 'Record external disbursement' : 'Record external repayment'}
              </button>
            </form>
          )}
        </article>
      )}
      {coverage.isPending && <p role="status">Loading advance coverage…</p>}
      {coverage.isError && (
        <p role="alert">
          {formatApiError(coverage.error, 'Unable to load approved coverage.')}{' '}
          <button className={hrButtonClass} type="button" onClick={() => void coverage.refetch()}>
            Retry coverage
          </button>
        </p>
      )}
      {coverage.data?.length === 0 && <p>No approved benefit coverage allows advances for this employee.</p>}
      {coverage.data && coverage.data.length > 0 && (
        <form onSubmit={(event) => void submit(event)} className="space-y-2 border-t border-theme-border pt-3">
          <h4 className="font-semibold">Request an advance</h4>
          <fieldset disabled={writing} className="grid gap-2 sm:grid-cols-2">
            <label className="sm:col-span-2">
              Benefit coverage
              <select className={hrInputClass} value={assignmentId}
                onChange={(event) => setAssignmentId(event.target.value)} required>
                <option value="">Select approved coverage</option>
                {coverage.data.map((item) => (
                  <option key={item.id} value={item.id}>{item.name} · {item.from} to {item.to} · {item.currency}</option>
                ))}
              </select>
            </label>
            <label>
              Advance request date
              <input className={hrInputClass} name="date" type="date"
                min={assignment?.from} max={assignment?.to} required />
            </label>
            <label>
              Requested amount{assignment && ` (${assignment.currency})`}
              <input className={hrInputClass} name="amount" inputMode="decimal" pattern={amountPattern} required />
            </label>
          </fieldset>
          <button className={hrButtonClass} type="submit" disabled={!assignment || writing}>
            Submit advance
          </button>
        </form>
      )}
    </section>
  );
}

function downloadPayable(row: EmployeeAdvance) {
  const exportData = {
    advance_id: row.id,
    employee_id: row.employee_id,
    benefit_assignment_id: row.benefit_assignment_id,
    amount: row.amount,
    currency: row.currency,
    approved_at: row.decided_at,
    payable_sha256: row.payable_sha256
  };
  const url = URL.createObjectURL(
    new Blob([JSON.stringify(exportData, null, 2) + '\n'], { type: 'application/json' })
  );
  const link = document.createElement('a');
  link.href = url;
  link.download = `advance-${row.id}.json`;
  try {
    link.click();
  } finally {
    window.setTimeout(() => URL.revokeObjectURL(url), 0);
  }
}
