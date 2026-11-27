import { useState } from 'react';

import { formatApiError } from '../../api/errors';
import {
  applyLeaveAccrual,
  applyLeaveAccrualCatchUp,
  previewLeaveAccrual,
  previewLeaveAccrualCatchUp,
  type EmployeeDirectoryRecord,
  type HrSchemas,
  type LeaveTypeRecord
} from '../../api/hr';

type Input = HrSchemas['LeaveAccrualRequest'] | HrSchemas['LeaveAccrualCatchUpRequest'];
type Plan = HrSchemas['LeaveAccrualCatchUpResponse'];
type Period = Plan['periods'][number];

function isActionableLeaveAccrualPeriod(period: Period): boolean {
  return (
    !period.ledger_entry_id &&
    Number(period.days) > 0 &&
    (period.outcome === 'preview' || period.outcome == null)
  );
}

function hasActionableLeaveAccrualDays(plan: Plan): boolean {
  return Number(plan.pending_days) > 0 && plan.periods.some(isActionableLeaveAccrualPeriod);
}

function canConfirmLeaveAccrual(plan: Plan): boolean {
  return Boolean(plan.digest && hasActionableLeaveAccrualDays(plan));
}

function outcomeLabel(period: Period, planDigest?: string | null): string {
  if (period.ledger_entry_id) {
    return `Posted. Ledger reference ${period.ledger_entry_id}`;
  }
  switch (period.outcome) {
    case 'not_due':
      return 'Not due';
    case 'baseline_recognized':
      return 'Recognized in reviewed baseline';
    case 'posted':
    case 'already_posted':
      return 'Posted. Ledger reference unavailable';
    case 'reconciliation_required':
      return 'Reconciliation required';
    case 'preview':
      return isActionableLeaveAccrualPeriod(period) && (period.digest || planDigest)
        ? 'Ready for confirmation'
        : 'Not actionable';
    default:
      return 'Legacy preview';
  }
}

export function LeaveAccrualPlan({
  plan,
  pending,
  onConfirm
}: {
  plan: Plan;
  pending: boolean;
  onConfirm: () => void;
}) {
  return (
    <div className="mt-2 space-y-2" aria-live="polite">
      <ul>
        {plan.periods.map((period) => (
          <li key={period.period_start}>
            {period.period_start} through {period.period_end} · {period.days} days
            {period.due_date ? ` · Due ${period.due_date}` : ''}
            {period.service_year_band ? ` · Service year ${period.service_year_band}` : ''}
            {period.eligible_from && period.eligible_through
              ? ` · Prorated for ${period.eligible_from} through ${period.eligible_through}`
              : ''}
            {` · ${outcomeLabel(period, plan.digest)}`}
          </li>
        ))}
      </ul>
      {hasActionableLeaveAccrualDays(plan) && <p>Days to credit: {plan.pending_days}</p>}
      {canConfirmLeaveAccrual(plan) && (
        <button type="button" disabled={pending} onClick={onConfirm}>
          Confirm and post accrual
        </button>
      )}
    </div>
  );
}

export function HRLeaveAccrual({
  employees,
  leaveTypes
}: {
  employees: EmployeeDirectoryRecord[];
  leaveTypes: LeaveTypeRecord[];
}) {
  const [preview, setPreview] = useState<{ input: Input; plan: Plan } | null>(null);
  const [pending, setPending] = useState(false);
  const [error, setError] = useState('');

  async function run(input: Input, digest?: string) {
    if (pending) return;
    setPending(true);
    setError('');
    try {
      if ('start_month' in input) {
        const plan = digest
          ? await applyLeaveAccrualCatchUp({ ...input, expected_digest: digest })
          : await previewLeaveAccrualCatchUp(input);
        setPreview({ input, plan });
      } else {
        const period = digest
          ? await applyLeaveAccrual({ ...input, expected_digest: digest })
          : await previewLeaveAccrual(input);
        setPreview({
          input,
          plan: {
            periods: [period],
            pending_days: isActionableLeaveAccrualPeriod(period) ? period.days : '0.00',
            digest: period.digest
          }
        });
      }
    } catch (failure) {
      if (digest) setPreview(null);
      setError(formatApiError(failure, 'Could not process leave accrual.'));
    } finally {
      setPending(false);
    }
  }

  return (
    <details className="border-t border-theme-border pt-3 text-sm">
      <summary>Post approved leave accrual</summary>
      <form
        className="mt-2 grid gap-2"
        onChange={() => {
          setPreview(null);
          setError('');
        }}
        onSubmit={(event) => {
          event.preventDefault();
          const values = new FormData(event.currentTarget);
          setPreview(null);
          const selection = {
            employee_id: String(values.get('employee')),
            leave_type_id: String(values.get('leaveType')),
            year: Number(values.get('year'))
          };
          const month = values.get('month') ? Number(values.get('month')) : null;
          const through = values.get('through') ? Number(values.get('through')) : null;
          if (through !== null && (month === null || through < month)) {
            setError('Enter a first month at or before the catch-up end month.');
            return;
          }
          void run(
            month !== null && through !== null
              ? { ...selection, start_month: month, end_month: through }
              : { ...selection, month }
          );
        }}
      >
        <fieldset disabled={pending} className="grid gap-2">
          <label>
            Accrual employee{' '}
            <select name="employee" defaultValue="" required>
              <option value="" disabled>
                Select employee
              </option>
              {employees.map((employee) => (
                <option key={employee.id} value={employee.id}>
                  {employee.employee_code} · {employee.full_name}
                </option>
              ))}
            </select>
          </label>
          <label>
            Accrual leave type{' '}
            <select name="leaveType" defaultValue="" required>
              <option value="" disabled>
                Select paid leave type
              </option>
              {leaveTypes
                .filter((type) => type.is_paid && type.is_active)
                .map((type) => (
                  <option key={type.id} value={type.id}>
                    {type.name}
                  </option>
                ))}
            </select>
          </label>
          <label>
            Accrual year <input name="year" type="number" min="2020" max="2100" required />
          </label>
          <label>
            Accrual month (blank for full year){' '}
            <input name="month" type="number" min="1" max="12" />
          </label>
          <label>
            Catch-up end month (optional) <input name="through" type="number" min="1" max="12" />
          </label>
          <button type="submit">Preview accrual</button>
        </fieldset>
      </form>
      {pending && <p role="status">Processing leave accrual…</p>}
      {error && <p role="alert">{error}</p>}
      {preview && (
        <LeaveAccrualPlan
          plan={preview.plan}
          pending={pending}
          onConfirm={() => void run(preview.input, preview.plan.digest ?? undefined)}
        />
      )}
    </details>
  );
}
