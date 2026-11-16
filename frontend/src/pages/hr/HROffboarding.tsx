import { useState } from 'react';

import { formatApiError } from '../../api/errors';
import {
  completeOffboarding,
  initiateOffboarding,
  updateOffboardingStep,
  type EmployeeDirectoryRecord,
  type OffboardingCaseRecord
} from '../../api/hr';
import type { components } from '../../api/schema';
import { hrButtonClass, hrInputClass } from './HRAccessForms';
import { HROffboardingCustody } from './HROffboardingCustody';
import { HRSeparationSettlement } from './HRSeparationSettlement';

type Separation = components['schemas']['OffboardingInitiateRequest']['separation_type'];

export function HROffboarding({
  employees,
  cases,
  onChange
}: {
  employees: EmployeeDirectoryRecord[];
  cases: OffboardingCaseRecord[];
  onChange: () => Promise<void>;
}) {
  const [pending, setPending] = useState(false);
  const [error, setError] = useState('');
  async function run(action: () => Promise<unknown>) {
    if (pending) return;
    setPending(true);
    setError('');
    try {
      await action();
      await onChange();
    } catch (failure) {
      setError(formatApiError(failure, 'Could not update offboarding.'));
    } finally {
      setPending(false);
    }
  }

  return (
    <section className="space-y-3 border-t border-theme-border pt-3">
      <h4 className="font-semibold">Offboarding</h4>
      {error && (
        <p role="alert" className="text-red-700">
          {error}
        </p>
      )}
      <form
        className="space-y-2"
        onSubmit={(event) => {
          event.preventDefault();
          const form = event.currentTarget;
          const data = new FormData(form);
          void run(async () => {
            await initiateOffboarding({
              employee_id: String(data.get('employee')),
              separation_type: String(data.get('type')) as Separation,
              last_working_date: String(data.get('last_day')),
              reason: String(data.get('reason') ?? '') || null
            });
            form.reset();
          });
        }}
      >
        <label className="block">
          Employee{' '}
          <input name="employee" list="hr-exit-employees" className={hrInputClass} required />
        </label>
        <datalist id="hr-exit-employees">
          {employees.map((employee) => (
            <option value={employee.id} key={employee.id}>
              {employee.full_name}
            </option>
          ))}
        </datalist>
        <label className="block">
          Separation type{' '}
          <select name="type" className={hrInputClass} required defaultValue="">
            <option value="" disabled>
              Select a type
            </option>
            <option value="resignation">Resignation</option>
            <option value="termination">Termination</option>
            <option value="contract_end">End of contract</option>
            <option value="retirement">Retirement</option>
            <option value="mutual">Mutual agreement</option>
          </select>
        </label>
        <label className="block">
          Last working day <input className={hrInputClass} name="last_day" type="date" required />
        </label>
        <label className="block">
          Reason <textarea className={hrInputClass} name="reason" />
        </label>
        <button className={hrButtonClass} type="submit" disabled={pending}>
          Start offboarding
        </button>
      </form>
      {cases.map((record) => (
        <article key={record.id} className="space-y-2 rounded border border-theme-border p-3">
          <p className="font-semibold">
            {employees.find((employee) => employee.id === record.employee_id)?.full_name ??
              record.employee_id}
          </p>
          <p>
            {record.last_working_date} · {record.status.replace(/_/g, ' ')}
          </p>
          {(record.steps ?? []).map((step) => (
            <div className="border-t border-theme-border pt-2" key={step.id}>
              <p>
                {step.title} · {step.status}
              </p>
              {step.department_area === 'store_inventory' || step.department_area === 'it_admin' ? (
                <HROffboardingCustody
                  area={step.department_area}
                  caseId={record.id}
                  onRefresh={onChange}
                />
              ) : step.department_area === 'finance_accounts' ? (
                <HRSeparationSettlement caseId={record.id} onRefresh={onChange} />
              ) : (
                record.status !== 'completed' &&
                !['cleared', 'waived'].includes(step.status) && (
                  <form
                    className="mt-1 flex items-end gap-2"
                    onSubmit={(event) => {
                      event.preventDefault();
                      const notes = String(new FormData(event.currentTarget).get('reference'));
                      void run(() => updateOffboardingStep(step.id, { status: 'cleared', notes }));
                    }}
                  >
                    <label>
                      Clearance reference{' '}
                      <input className={hrInputClass} name="reference" required />
                    </label>
                    <button className={hrButtonClass} type="submit" disabled={pending}>
                      Record clearance
                    </button>
                  </form>
                )
              )}
            </div>
          ))}
          {record.status !== 'completed' &&
            (record.steps?.length ?? 0) > 0 &&
            record.steps?.every((step) => ['cleared', 'waived'].includes(step.status)) && (
              <form
                className="space-y-2"
                onSubmit={(event) => {
                  event.preventDefault();
                  const eligibility = new FormData(event.currentTarget).get('rehire_eligible');
                  void run(() =>
                    completeOffboarding(record.id, {
                      rehire_eligible:
                        eligibility === 'yes' ? true : eligibility === 'no' ? false : null
                    })
                  );
                }}
              >
                <label className="block">
                  Rehire eligibility
                  <select name="rehire_eligible" className={hrInputClass} defaultValue="">
                    <option value="">Undetermined</option>
                    <option value="yes">Eligible</option>
                    <option value="no">Ineligible</option>
                  </select>
                </label>
                <button className={hrButtonClass} type="submit" disabled={pending}>
                  Complete offboarding
                </button>
              </form>
            )}
        </article>
      ))}
    </section>
  );
}
