import { useQuery, useQueryClient } from '@tanstack/react-query';
import { useRef, useState, type FormEvent } from 'react';

import { formatApiError } from '../../api/errors';
import {
  approvePayrollRun,
  calculatePayrollRun,
  createPayrollPeriod,
  createPayrollRun,
  listPayrollPeriods,
  listPayrollPolicies,
  listPayrollRuns,
  publishPayrollPayslips,
  readPayrollSnapshot,
  type PayrollSourceEvidence
} from '../../api/hr';
import { hrButtonClass, hrInputClass } from './HRAccessForms';
import { HRPayrollAdjustments } from './HRPayrollAdjustments';
import { HRPayrollCorrections } from './HRPayrollCorrections';
import { HRPayrollFinance } from './HRPayrollFinance';
import { FrozenPayrollInputs, HRPayrollInputs } from './HRPayrollInputs';
import { HRPayrollPolicy } from './HRPayrollPolicy';

type Props = { actorId: string; canPrepare: boolean; canRead: boolean; canApprove: boolean };
const uuidPattern = '[0-9A-Fa-f]{8}(-[0-9A-Fa-f]{4}){3}-[0-9A-Fa-f]{12}';
const uuid = new RegExp(`^${uuidPattern}$`);

export function HRPayroll({ actorId, canPrepare, canRead, canApprove }: Props) {
  const client = useQueryClient();
  const key = ['hr', 'payroll', actorId];
  const [selected, setSelected] = useState('');
  const [rosterInput, setRosterInput] = useState('');
  const [evidence, setEvidence] = useState<PayrollSourceEvidence>();
  const [snapshotId, setSnapshotId] = useState('');
  const [periodId, setPeriodId] = useState('');
  const [pending, setPending] = useState(false);
  const [notice, setNotice] = useState('');
  const [error, setError] = useState('');
  const saving = useRef(false);
  const setup = useQuery({
    queryKey: [...key, 'setup'],
    queryFn: async () => {
      const [periods, policies, runs] = await Promise.all([
        listPayrollPeriods(), listPayrollPolicies(), listPayrollRuns()
      ]);
      return { periods: periods.items, policies: policies.items, runs: runs.items };
    },
    enabled: canPrepare,
    retry: false,
    gcTime: 0
  });
  const snapshot = useQuery({
    queryKey: [...key, 'snapshot', snapshotId],
    queryFn: async ({ signal }) => {
      const row = await readPayrollSnapshot(snapshotId, signal);
      if (row.run_id !== snapshotId) throw new Error('Unexpected payroll run');
      return row;
    },
    enabled: Boolean(canRead && snapshotId),
    gcTime: 0,
    retry: false
  });
  const run = setup.data?.runs.find((item) => item.id === selected);
  const reviewed = canRead ? snapshot.data : undefined;
  const roster = rosterInput.trim().toLowerCase().split(/[\s,]+/).sort();
  const validRoster = roster.every((id) => uuid.test(id)) &&
    roster.length <= 1000 && new Set(roster).size === roster.length;
  const approvedPolicies = setup.data?.policies.filter((item) =>
    item.is_approved && item.approved_at && item.approved_by_id && item.second_approved_by_id &&
    item.approved_by_id !== item.second_approved_by_id
  ) ?? [];
  const openPeriods = setup.data?.periods.filter((item) => item.status === 'open') ?? [];

  async function write(action: () => Promise<void>, message: string) {
    if (saving.current) return;
    saving.current = true;
    setPending(true);
    setNotice('');
    setError('');
    try {
      await action();
      await client.invalidateQueries({ queryKey: key });
      setNotice(message);
    } catch (err) {
      setError(formatApiError(err, 'The payroll operation could not be saved.'));
    } finally {
      saving.current = false;
      setPending(false);
    }
  }

  function openPeriod(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    const form = event.currentTarget;
    const fields = new FormData(form);
    void write(async () => {
      const row = await createPayrollPeriod({
        period_code: String(fields.get('code')).trim(),
        period_start: String(fields.get('start')),
        period_end: String(fields.get('end')),
        pay_date: String(fields.get('pay_date'))
      });
      setPeriodId(row.id);
      form.reset();
    }, 'Payroll period opened.');
  }

  function newRun(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    const form = event.currentTarget;
    const fields = new FormData(form);
    void write(async () => {
      const saved = await createPayrollRun({
        payroll_period_id: periodId,
        policy_id: String(fields.get('policy')),
      });
      selectRun(saved.id);
    }, 'Draft payroll run created.');
  }

  function calculate(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (!run || run.status !== 'draft' || run.prepared_by_id !== actorId) return;
    if (!validRoster) {
      setError('Enter 1 to 1,000 unique employee IDs.');
      return;
    }
    void write(async () => {
      await calculatePayrollRun(run.id, roster, evidence);
    }, 'Payroll snapshot calculated.');
  }

  function selectRun(id: string) {
    setSelected(id);
    setRosterInput('');
    setEvidence(undefined);
    setSnapshotId('');
    setNotice('');
    setError('');
  }

  return (
    <section aria-label="Payroll operations" className="space-y-4">
      {error && <p role="alert">{error}</p>}
      {notice && <p role="status">{notice}</p>}
      {(canPrepare || canApprove) && <HRPayrollPolicy actorId={actorId} canPrepare={canPrepare} canApprove={canApprove} />}
      {canPrepare && (
        <div className="space-y-4 rounded border border-theme-border bg-theme-card p-4">
          <h3 className="font-semibold">Prepare payroll</h3>
          <p className="text-sm text-theme-text-muted">
            Calculate a closed calendar month using an approved policy and an explicit employee roster.
          </p>
          {setup.isPending && <p role="status">Loading payroll setup…</p>}
          {setup.isError && (
            <p role="alert">{formatApiError(setup.error, 'Unable to load payroll setup.')}{' '}
              <button className={hrButtonClass} type="button" onClick={() => void setup.refetch()}>Retry payroll setup</button>
            </p>
          )}
          {setup.isSuccess && (
            <>
              <form onSubmit={openPeriod} className="space-y-2">
                <h4 className="font-semibold">Open period</h4>
                <fieldset disabled={pending} className="grid gap-2 sm:grid-cols-2">
                  <label>Period code<input name="code" className={hrInputClass} required maxLength={40} /></label>
                  <label>Period start<input name="start" type="date" className={hrInputClass} required /></label>
                  <label>Period end<input name="end" type="date" className={hrInputClass} required /></label>
                  <label>Pay date<input name="pay_date" type="date" className={hrInputClass} required /></label>
                </fieldset>
                <button className={hrButtonClass} type="submit" disabled={pending}>Open payroll period</button>
              </form>
              {approvedPolicies.length === 0 && <p>No approved payroll policies are available.</p>}
              {approvedPolicies.length > 0 && openPeriods.length > 0 && (
                <form onSubmit={newRun} className="space-y-2 border-t border-theme-border pt-3">
                  <h4 className="font-semibold">Create draft run</h4>
                  <fieldset disabled={pending} className="grid gap-2 sm:grid-cols-2">
                    <label>Open payroll period
                      <select className={hrInputClass} value={periodId} required onChange={(event) => setPeriodId(event.target.value)}>
                        <option value="">Select an open period</option>
                        {openPeriods.map((period) => (
                          <option key={period.id} value={period.id}>{period.period_code} · {period.period_start} to {period.period_end}</option>
                        ))}
                      </select>
                    </label>
                    <label>Approved payroll policy
                      <select className={hrInputClass} name="policy" required defaultValue="">
                        <option value="">Select approved policy</option>
                        {approvedPolicies.map((policy) => <option key={policy.id} value={policy.id}>{policy.code} · {policy.name}</option>)}
                      </select>
                    </label>
                  </fieldset>
                  <button className={hrButtonClass} type="submit" disabled={pending}>Create payroll run</button>
                </form>
              )}
              {setup.data.runs.length > 0 && (
                <label className="block">Payroll run
                  <select className={hrInputClass} value={selected} disabled={pending} onChange={(event) => selectRun(event.target.value)}>
                    <option value="">Select a payroll run</option>
                    {setup.data.runs.map((item) => (
                      <option key={item.id} value={item.id}>
                        {setup.data.periods.find((period) => period.id === item.payroll_period_id)?.period_code ?? item.payroll_period_id} · {item.status} · {item.id}
                      </option>
                    ))}
                  </select>
                </label>
              )}
              {run && <p className="break-all">Run ID <code>{run.id}</code></p>}
              {run?.status === 'draft' && run.prepared_by_id === actorId && (
                <form key={run.id} className="space-y-2" onSubmit={calculate}>
                  <label className="block">Roster employee IDs
                    <textarea className={hrInputClass} name="employees" rows={3} required
                      aria-describedby="payroll-roster-help" value={rosterInput} disabled={pending}
                      onChange={(event) => {
                        setRosterInput(event.target.value);
                        setEvidence(undefined);
                      }} />
                  </label>
                  <p id="payroll-roster-help" className="text-sm text-theme-text-muted">Separate employee UUIDs with a comma or a new line.</p>
                  {validRoster && <HRPayrollInputs key={`${run.id}:${roster.join(',')}`}
                    actorId={actorId} periodId={run.payroll_period_id} employeeIds={roster} disabled={pending}
                    evidence={evidence} onEvidenceChange={setEvidence} />}
                  <button className={hrButtonClass} type="submit" disabled={pending}>Calculate snapshot</button>
                </form>
              )}
              {canRead && run && ['calculated', 'approved'].includes(run.status) && (
                <button className={hrButtonClass} type="button" disabled={pending}
                  onClick={() => setSnapshotId(run.id)}>Review selected snapshot</button>
              )}
            </>
          )}
        </div>
      )}
      {canRead && <HRPayrollAdjustments actorId={actorId} />}
      {canRead && (
        <div className="space-y-3 rounded border border-theme-border bg-theme-card p-4">
          <form className="space-y-2" onSubmit={(event) => {
            event.preventDefault();
            setSnapshotId(String(new FormData(event.currentTarget).get('run')).trim().toLowerCase());
            setError('');
            setNotice('');
          }}>
            <h3 className="font-semibold">Review a payroll snapshot</h3>
            <label className="block">Payroll run ID<input className={hrInputClass} name="run" pattern={uuidPattern} required /></label>
            <button className={hrButtonClass} type="submit" disabled={pending}>Open snapshot by ID</button>
          </form>
          {snapshotId && snapshot.isPending && <p role="status">Opening private payroll snapshot…</p>}
          {snapshotId && snapshot.isError && (
            <p role="alert">{formatApiError(snapshot.error, 'Unable to open this snapshot.')}{' '}
              <button className={hrButtonClass} type="button" onClick={() => void snapshot.refetch()}>Retry snapshot</button>
            </p>
          )}
          {reviewed && (
            <article aria-label="Reviewed payroll snapshot" className="space-y-2 border-t border-theme-border pt-3">
              <header className="flex flex-wrap items-center justify-between gap-2">
                <h4 className="font-semibold">{reviewed.period_start} to {reviewed.period_end}</h4>
                <button className={hrButtonClass} type="button" disabled={pending} onClick={() => setSnapshotId('')}>Close snapshot</button>
              </header>
              <p>{reviewed.status === 'approved' ? 'Approved and locked' : 'Awaiting independent approval'} · Pay date {reviewed.pay_date}</p>
              <dl className="grid grid-cols-2 gap-1">
                <dt>Gross</dt><dd>{reviewed.currency} {reviewed.gross}</dd>
                <dt>Deductions</dt><dd>{reviewed.currency} {reviewed.deductions}</dd>
                <dt>Net</dt><dd>{reviewed.currency} {reviewed.net}</dd>
              </dl>
              <p className="break-all text-sm">Snapshot digest <code>{reviewed.digest}</code></p>
              {reviewed.controlled_policy_record && (
                <dl aria-label="Controlled payroll policy" className="grid grid-cols-2 gap-1">
                  <dt>Document reference</dt><dd>{reviewed.controlled_policy_record.document_reference}</dd>
                  <dt>Version</dt><dd>{reviewed.controlled_policy_record.version}</dd>
                  <dt>Effective from</dt><dd>{reviewed.controlled_policy_record.effective_from}</dd>
                  <dt>Approval reference</dt><dd>{reviewed.controlled_policy_record.approval_reference}</dd>
                </dl>
              )}
              <div className="overflow-x-auto">
                <table className="w-full text-left text-sm">
                  <thead><tr><th scope="col">Employee ID</th><th scope="col">Gross</th><th scope="col">Deductions</th><th scope="col">Net</th></tr></thead>
                  <tbody>{reviewed.lines.map((line) => (
                    <tr key={line.employee_id}><td>{line.employee_id}</td><td>{line.gross}</td><td>{line.deductions}</td><td>{line.net}</td></tr>
                  ))}</tbody>
                </table>
              </div>
              {reviewed.source_evidence && (
                <FrozenPayrollInputs key={reviewed.digest} runId={reviewed.run_id} evidence={reviewed.source_evidence} />
              )}
              {reviewed.lines.some((line) => line.adjustments?.length) && (
                <details>
                  <summary>Frozen payroll adjustments</summary>
                  <ul className="space-y-1">
                    {reviewed.lines.flatMap((line) => (line.adjustments ?? []).map((adjustment) => (
                      <li key={adjustment.id} className="break-all">
                        {line.employee_id} · {adjustment.kind} · {reviewed.currency} {adjustment.amount} · {adjustment.evidence_reference}
                      </li>
                    )))}
                  </ul>
                </details>
              )}
              {canApprove && reviewed.status === 'calculated' && reviewed.prepared_by_id && reviewed.prepared_by_id !== actorId && (
                <button className={hrButtonClass} type="button" disabled={pending} onClick={() => void write(async () => {
                  await approvePayrollRun(reviewed.run_id, reviewed.digest);
                }, 'Payroll approved and period locked.')}>Approve and lock reviewed payroll</button>
              )}
              {canApprove && reviewed.status === 'approved' && reviewed.approved_by_id === actorId && !reviewed.payslips_published_at && (
                <button className={hrButtonClass} type="button" disabled={pending} onClick={() => void write(async () => {
                  await publishPayrollPayslips(reviewed.run_id, reviewed.digest);
                }, 'Payslips published.')}>Publish payslips</button>
              )}
              {reviewed.payslips_published_at && <p>Payslips are published.</p>}
              {reviewed.closed_at && (
                <HRPayrollCorrections key={reviewed.digest} runId={reviewed.run_id} snapshotDigest={reviewed.digest}
                  actorId={actorId} canPropose={canPrepare} canReview={canApprove} lines={reviewed.lines} />
              )}
              {canApprove && reviewed.status === 'approved' && (
                <HRPayrollFinance key={`${actorId}:${reviewed.run_id}:${reviewed.digest}`}
                  actorId={actorId} runId={reviewed.run_id} snapshotDigest={reviewed.digest} onClosed={snapshot.refetch}
                  canRegister={reviewed.approved_by_id === actorId && reviewed.prepared_by_id !== actorId}
                  canClose={Boolean(reviewed.prepared_by_id && reviewed.prepared_by_id !== actorId && reviewed.payslips_published_at)} />
              )}
            </article>
          )}
        </div>
      )}
    </section>
  );
}
