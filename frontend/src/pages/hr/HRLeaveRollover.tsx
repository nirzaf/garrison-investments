import { useState } from 'react';

import { formatApiError } from '../../api/errors';
import {
  applyLeaveRollover,
  previewLeaveRollover,
  type EmployeeDirectoryRecord,
  type HrSchemas,
  type LeaveTypeRecord
} from '../../api/hr';

type Input = HrSchemas['LeaveRolloverRequest'];
type Plan = HrSchemas['LeaveRolloverResponse'];

export function HRLeaveRollover({
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
      const plan = digest
        ? await applyLeaveRollover({ ...input, expected_digest: digest })
        : await previewLeaveRollover(input);
      setPreview({ input, plan });
    } catch (failure) {
      setError(formatApiError(failure, 'Could not process leave rollover.'));
    } finally {
      setPending(false);
    }
  }

  return (
    <details className="border-t border-theme-border pt-3 text-sm">
      <summary>Review year-end leave rollover</summary>
      <form
        className="mt-2 grid gap-2"
        onChange={() => {
          setPreview(null);
          setError('');
        }}
        onSubmit={(event) => {
          event.preventDefault();
          setPreview(null);
          const data = new FormData(event.currentTarget);
          void run({
            employee_id: String(data.get('employee')),
            leave_type_id: String(data.get('type')),
            source_year: Number(data.get('year'))
          });
        }}
      >
        <fieldset className="grid gap-2" disabled={pending}>
          <label>
            Rollover employee{' '}
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
            Rollover leave type{' '}
            <select name="type" defaultValue="" required>
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
            Source leave year <input name="year" type="number" min="2020" max="2099" required />
          </label>
          <button type="submit">Preview rollover</button>
        </fieldset>
      </form>
      {pending && <p role="status">Processing leave rollover…</p>}
      {error && <p role="alert">{error}</p>}
      {preview && (
        <div className="mt-2 space-y-2" aria-live="polite">
          <p>
            {preview.plan.source_year} closing balance: {preview.plan.source_balance} days
          </p>
          <p>
            Carry to {preview.plan.target_year}: {preview.plan.carried_days} days
          </p>
          <p>Year-end expiry: {preview.plan.expired_days} days</p>
          {preview.plan.receipt_id ? (
            <p>Rollover posted. Receipt {preview.plan.receipt_id}</p>
          ) : (
            preview.plan.digest && (
              <>
                <p>Posting closes the source leave year for this employee and leave type.</p>
                <button
                  type="button"
                  disabled={pending}
                  onClick={() => void run(preview.input, preview.plan.digest ?? undefined)}
                >
                  Confirm and close leave year
                </button>
              </>
            )
          )}
        </div>
      )}
    </details>
  );
}
