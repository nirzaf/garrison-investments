import { useState } from 'react';

import { formatApiError } from '../../api/errors';
import {
  applyLeaveEntitlementBaseline,
  previewLeaveEntitlementBaseline,
  type EmployeeDirectoryRecord,
  type HrSchemas,
  type LeaveTypeRecord
} from '../../api/hr';

type Input = HrSchemas['LeaveEntitlementBaselineRequest'];
type Plan = HrSchemas['LeaveEntitlementBaselineResponse'];

export function HRLeaveBaseline({
  employees,
  leaveTypes
}: {
  employees: EmployeeDirectoryRecord[];
  leaveTypes: LeaveTypeRecord[];
}) {
  const [input, setInput] = useState<Input | null>(null);
  const [plan, setPlan] = useState<Plan | null>(null);
  const [pending, setPending] = useState(false);
  const [error, setError] = useState('');

  async function preview(payload: Input) {
    if (pending) return;
    setPending(true);
    setError('');
    setInput(payload);
    try {
      setPlan(await previewLeaveEntitlementBaseline(payload));
    } catch (failure) {
      setPlan(null);
      setError(formatApiError(failure, 'Could not preview the leave balance baseline.'));
    } finally {
      setPending(false);
    }
  }

  async function apply() {
    if (!input || !plan?.digest || pending) return;
    setPending(true);
    setError('');
    try {
      setPlan(await applyLeaveEntitlementBaseline({
        ...input,
        expected_digest: plan.digest
      }));
    } catch (failure) {
      setError(formatApiError(failure, 'Could not reconcile the leave balance baseline.'));
    } finally {
      setPending(false);
    }
  }

  return (
    <details className="border-t border-theme-border pt-3 text-sm">
      <summary>Reconcile a verified managed leave balance</summary>
      <p className="mt-2 text-theme-text-muted">
        Use an approved managed leave policy and a verified HR source. Recognized credit dates
        identify entitlements already included in the verified balance; do not estimate them.
        Locked payroll years cannot be changed.
      </p>
      <form
        className="mt-3 grid gap-2"
        onChange={() => {
          setInput(null);
          setPlan(null);
          setError('');
        }}
        onSubmit={(event) => {
          event.preventDefault();
          const values = new FormData(event.currentTarget);
          const recognized = String(values.get('recognized') ?? '')
            .split(/[\n,]/)
            .map((value) => value.trim())
            .filter(Boolean);
          void preview({
            employee_id: String(values.get('employee')),
            leave_type_id: String(values.get('leaveType')),
            year: Number(values.get('year')),
            as_of_date: String(values.get('asOf')),
            verified_balance: String(values.get('balance')),
            recognized_due_dates: recognized,
            supporting_reference: String(values.get('reference') ?? '').trim()
          });
        }}
      >
        <fieldset className="grid gap-2" disabled={pending}>
          <label>
            Employee{' '}
            <select name="employee" defaultValue="" required>
              <option value="" disabled>Select employee</option>
              {employees.map((employee) => (
                <option key={employee.id} value={employee.id}>
                  {employee.employee_code} · {employee.full_name}
                </option>
              ))}
            </select>
          </label>
          <label>
            Paid leave type{' '}
            <select name="leaveType" defaultValue="" required>
              <option value="" disabled>Select leave type</option>
              {leaveTypes.filter((type) => type.is_active && type.is_paid).map((type) => (
                <option key={type.id} value={type.id}>{type.name}</option>
              ))}
            </select>
          </label>
          <label>Leave year <input name="year" type="number" min="2020" max="2100" required /></label>
          <label>Verified as-of date <input name="asOf" type="date" required /></label>
          <label>
            Verified balance (days){' '}
            <input name="balance" type="number" min="0" step="0.01" required />
          </label>
          <label>
            Already-credited due dates (one YYYY-MM-DD per line){' '}
            <textarea name="recognized" rows={3} />
          </label>
          <label>
            HR source reference{' '}
            <input name="reference" maxLength={200} required />
          </label>
          <button className="rounded bg-brand-600 px-3 py-2 text-white" type="submit">
            Preview reconciliation
          </button>
        </fieldset>
      </form>
      {pending && <p role="status">Reviewing verified leave balance…</p>}
      {error && <p role="alert">{error}</p>}
      {plan && (
        <div className="mt-3 space-y-2" aria-live="polite">
          <p>Ledger balance: {plan.current_balance} days</p>
          <p>Verified HR balance: {plan.verified_balance} days</p>
          <p>Adjustment to post: {plan.adjustment_days} days</p>
          <p>Recognized due periods: {plan.recognized_due_dates.length}</p>
          {plan.receipt_id ? (
            <p>Baseline recorded. Receipt {plan.receipt_id}</p>
          ) : plan.digest ? (
            <button
              className="rounded border border-theme-border px-3 py-2"
              disabled={pending}
              onClick={() => void apply()}
              type="button"
            >
              Confirm reviewed balance
            </button>
          ) : null}
        </div>
      )}
    </details>
  );
}
