import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import { useState, type FormEvent } from 'react';

import { formatApiError } from '../../api/errors';
import {
  applyEmploymentChange,
  decideEmploymentChange,
  getEmployee,
  listEmployees,
  listEmploymentChanges,
  listEmploymentPeriods,
  listOffboardingCases,
  proposeEmploymentChange,
  type DepartmentRecord,
  type EmployeeDetailRecord,
  type HrSchemas,
  type PositionRecord
} from '../../api/hr';
import {
  HRContractRenewal,
  HRContractVersionLink,
  type ContractVersion
} from './HRContractRenewal';

type Proposal = HrSchemas['EmploymentChangeProposal'];
const kinds = {
  transfer: 'Transfer',
  promotion: 'Promotion',
  category_amendment: 'Employment category amendment',
  profile_correction: 'Profile name correction',
  contract_renewal: 'Contract renewal',
  rehire: 'Rehire'
} satisfies Record<Proposal['change_type'], string>;
const categories = [
  'permanent',
  'contract',
  'probation',
  'daily_wage',
  'intern',
  'consultant'
] as const;
const pageSize = 20;
const selectClass = 'block rounded border border-theme-border bg-theme-input px-2 py-1';

function ProposedManager({ id }: { id: string }) {
  const manager = useQuery({
    queryKey: ['hr', 'employment-change-manager', id],
    queryFn: async () => {
      const employee = await getEmployee(id);
      return `${employee.full_name} (${employee.employee_code})`;
    }
  });
  return manager.data ?? (manager.isPending ? 'Loading manager…' : 'Manager unavailable');
}

export function HREmploymentChanges({
  employee,
  actorId,
  departments,
  positions,
  refreshEmployee
}: {
  employee: EmployeeDetailRecord;
  actorId?: string;
  departments: DepartmentRecord[];
  positions: PositionRecord[];
  refreshEmployee: () => Promise<void>;
}) {
  const [open, setOpen] = useState(false);
  const separated = ['resigned', 'terminated', 'archived'].includes(employee.employment_status);
  const [activeKind, setKind] = useState<Exclude<Proposal['change_type'], 'rehire'>>('transfer');
  const kind = separated ? 'rehire' : activeKind;
  const [category, setCategory] = useState('');
  const [periodOffset, setPeriodOffset] = useState(0);
  const [managerSearch, setManagerSearch] = useState('');
  const [contract, setContract] = useState<{
    current?: ContractVersion;
    renewal?: ContractVersion;
  }>({});
  const [offset, setOffset] = useState(0);
  const [reasons, setReasons] = useState<Record<string, string>>({});
  const client = useQueryClient();
  const key = ['hr', 'employment-changes', employee.id];
  const periodKey = ['hr', 'employment-periods', employee.id];
  const periods = useQuery({
    queryKey: [...periodKey, periodOffset],
    queryFn: () => listEmploymentPeriods(employee.id, periodOffset, pageSize),
    enabled: open
  });
  const cases = useQuery({
    queryKey: ['hr', 'offboarding', 'employee', employee.id],
    queryFn: () => listOffboardingCases(employee.id),
    enabled: open && separated
  });
  const latestSeparation = cases.data?.items.find((row) => row.status === 'completed');
  const eligibleSeparation = latestSeparation?.rehire_eligible ? latestSeparation : undefined;
  const managerCandidates = useQuery({
    queryKey: ['hr', 'employment-change-managers', managerSearch],
    queryFn: () => listEmployees({ search: managerSearch.trim(), limit: 20 }),
    enabled: open && kind === 'transfer' && managerSearch.trim().length > 1
  });
  const changes = useQuery({
    queryKey: [...key, offset],
    queryFn: () => listEmploymentChanges(employee.id, offset, pageSize),
    enabled: open
  });

  const propose = useMutation({
    mutationFn: (payload: Proposal) => proposeEmploymentChange(employee.id, payload),
    onSuccess: async () => {
      setOffset(0);
      await client.invalidateQueries({ queryKey: key });
    }
  });
  const update = useMutation({
    mutationFn: ({ id, action }: { id: string; action: 'approved' | 'rejected' | 'apply' }) =>
      action === 'apply'
        ? applyEmploymentChange(employee.id, id)
        : decideEmploymentChange(employee.id, id, {
            decision: action,
            reason: action === 'rejected' ? reasons[id]?.trim() : undefined
          }),
    onSuccess: async (row) => {
      await client.invalidateQueries({ queryKey: key });
      if (row.status === 'applied') {
        await client.invalidateQueries({ queryKey: periodKey });
        await refreshEmployee();
      }
    }
  });
  const busy = propose.isPending || update.isPending;

  function proposeChange(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (busy) return;
    const form = event.currentTarget;
    const data = new FormData(form);
    const fields = [
      'department_id',
      'manager_employee_id',
      'work_location',
      'position_id',
      'employment_category',
      'first_name',
      'last_name',
      'full_name'
    ];
    const updates = Object.fromEntries(
      fields.flatMap((name) => {
        const value = data.get(name);
        return typeof value === 'string' && value.trim()
          ? [[name, name.endsWith('_id') && value === 'clear' ? null : value.trim()]]
          : [];
      })
    ) as Proposal['updates'];
    if (kind === 'rehire') {
      if (!eligibleSeparation) return;
      updates.separation_case_id = eligibleSeparation.id;
      if (category === 'probation') updates.probation_days = Number(data.get('probation_days'));
    }
    if (kind === 'contract_renewal') {
      if (!contract.current || !contract.renewal) return;
      Object.assign(updates, {
        current_contract_document_id: contract.current.documentId,
        current_contract_version: contract.current.version,
        renewal_contract_document_id: contract.renewal.documentId,
        renewal_contract_version: contract.renewal.version,
        contract_end_date: contract.renewal.expires
      });
    }
    propose.mutate(
      {
        change_type: kind,
        effective_date: String(data.get('effective_date')),
        employee_revision: employee.record_revision,
        reason: String(data.get('reason')).trim(),
        updates
      },
      {
        onSuccess: () => {
          form.reset();
          setManagerSearch('');
          setContract({});
          setCategory('');
        }
      }
    );
  }

  function displayUpdates(updates: Record<string, string | number | null | undefined>) {
    if (
      typeof updates.current_contract_document_id === 'string' &&
      typeof updates.current_contract_version === 'number' &&
      typeof updates.renewal_contract_document_id === 'string' &&
      typeof updates.renewal_contract_version === 'number'
    ) {
      return (
        <>
          <p>Renewed contract ends {updates.contract_end_date}</p>
          <HRContractVersionLink
            documentId={updates.current_contract_document_id}
            version={updates.current_contract_version}
            label="Open current contract evidence"
          />
          <HRContractVersionLink
            documentId={updates.renewal_contract_document_id}
            version={updates.renewal_contract_version}
            label="Open renewal contract evidence"
          />
        </>
      );
    }
    const labels: Record<string, string> = {
      department_id: 'Department',
      position_id: 'Position',
      manager_employee_id: 'Reporting manager',
      work_location: 'Work location',
      employment_category: 'Employment category',
      first_name: 'First name',
      last_name: 'Last name',
      full_name: 'Full name',
      separation_case_id: 'Completed separation',
      probation_days: 'Probation days'
    };
    return Object.entries(updates).map(([field, value]) => (
      <p key={field}>
        {labels[field] ?? field}:{' '}
        {value === null ? (
          'Clear current value'
        ) : field === 'department_id' ? (
          (departments.find((department) => department.id === value)?.name ?? value)
        ) : field === 'position_id' ? (
          (positions.find((position) => position.id === value)?.title ?? value)
        ) : field === 'manager_employee_id' && typeof value === 'string' ? (
          <ProposedManager id={value} />
        ) : (
          value
        )}
      </p>
    ));
  }

  return (
    <details onToggle={(event) => setOpen(event.currentTarget.open)} className="space-y-2">
      <summary>Reviewed employment changes</summary>
      <form onSubmit={proposeChange} className="space-y-2">
        <fieldset disabled={busy || (separated && !eligibleSeparation)} className="space-y-2">
          {separated ? (
            <>
              <p>
                Rehire starts a new onboarding case. Portal access follows the separate access
                request workflow.
              </p>
              {eligibleSeparation && (
                <p>Prior last working day {eligibleSeparation.last_working_date}</p>
              )}
              <label className="block">
                Rehire employment category
                <select
                  name="employment_category"
                  required
                  className={selectClass}
                  value={category}
                  onChange={(event) => setCategory(event.target.value)}
                >
                  <option value="">Select a category</option>
                  {categories.map((value) => (
                    <option key={value} value={value}>
                      {value.replace(/_/g, ' ')}
                    </option>
                  ))}
                </select>
              </label>
              {category === 'probation' && (
                <label className="block">
                  Rehire probation days
                  <input
                    name="probation_days"
                    type="number"
                    min={1}
                    max={365}
                    required
                    className={selectClass}
                  />
                </label>
              )}
            </>
          ) : (
            <label className="block">
              Change type
              <select
                value={kind}
                className={selectClass}
                onChange={(event) => setKind(event.target.value as typeof activeKind)}
              >
                {Object.entries(kinds)
                  .filter(([value]) => value !== 'rehire')
                  .filter(
                    ([value]) =>
                      value !== 'contract_renewal' || employee.employment_category === 'contract'
                  )
                  .map(([value, name]) => (
                    <option key={value} value={value}>
                      {name}
                    </option>
                  ))}
              </select>
            </label>
          )}
          {kind === 'transfer' && (
            <>
              <label className="block">
                Transfer department
                <select name="department_id" defaultValue="" className={selectClass}>
                  <option value="">Keep current department</option>
                  <option value="clear">Clear department</option>
                  {departments
                    .filter((item) => item.is_active)
                    .map((item) => (
                      <option key={item.id} value={item.id}>
                        {item.name}
                      </option>
                    ))}
                </select>
              </label>
              <label className="block">
                Search by manager name or code
                <input
                  value={managerSearch}
                  className={selectClass}
                  onChange={(event) => setManagerSearch(event.target.value)}
                />
              </label>
              <label className="block">
                Transfer reporting manager
                <select name="manager_employee_id" defaultValue="" className={selectClass}>
                  <option value="">Keep current manager</option>
                  <option value="clear">Clear manager</option>
                  {managerCandidates.data?.items
                    .filter(
                      (row) =>
                        row.id !== employee.id &&
                        ['active', 'on_probation', 'on_leave', 'notice_period'].includes(
                          row.employment_status
                        )
                    )
                    .map((row) => (
                      <option key={row.id} value={row.id}>
                        {row.full_name}
                      </option>
                    ))}
                </select>
              </label>
              {managerCandidates.isError && (
                <p role="alert">
                  {formatApiError(managerCandidates.error, 'Could not find managers.')}
                </p>
              )}
              <label className="block">
                New work location (optional)
                <input name="work_location" className={selectClass} maxLength={160} />
              </label>
            </>
          )}
          {kind === 'promotion' && (
            <label className="block">
              Promotion position
              <select name="position_id" defaultValue="" required className={selectClass}>
                <option value="">Select a position</option>
                {positions
                  .filter((item) => item.is_active && item.id !== employee.position_id)
                  .map((item) => (
                    <option key={item.id} value={item.id}>
                      {item.title}
                    </option>
                  ))}
              </select>
            </label>
          )}
          {kind === 'category_amendment' && (
            <label className="block">
              New employment category
              <select name="employment_category" defaultValue="" required className={selectClass}>
                <option value="">Select a category</option>
                {categories
                  .filter((value) => value !== employee.employment_category)
                  .map((value) => (
                    <option key={value} value={value}>
                      {value.replace(/_/g, ' ')}
                    </option>
                  ))}
              </select>
            </label>
          )}
          {kind === 'contract_renewal' && (
            <HRContractRenewal
              employeeId={employee.id}
              current={contract.current}
              renewal={contract.renewal}
              onChange={(field, value) => setContract((prior) => ({ ...prior, [field]: value }))}
            />
          )}
          {kind === 'profile_correction' && (
            <>
              <p>Enter the names that need correction. Leave the other fields blank.</p>
              <label className="block">
                Corrected first name
                <input name="first_name" maxLength={120} className={selectClass} />
              </label>
              <label className="block">
                Corrected last name
                <input name="last_name" maxLength={120} className={selectClass} />
              </label>
              <label className="block">
                Corrected full name
                <input name="full_name" maxLength={255} className={selectClass} />
              </label>
            </>
          )}
          <label className="block">
            Effective date
            <input name="effective_date" type="date" required className={selectClass} />
          </label>
          <label className="block">
            Employment change reason
            <input name="reason" required minLength={2} maxLength={500} className={selectClass} />
          </label>
          <button type="submit" className="rounded bg-brand-600 px-2 py-1 text-white">
            {separated ? 'Propose rehire' : 'Propose employment change'}
          </button>
        </fieldset>
      </form>
      {separated && cases.isPending && open && <p role="status">Checking rehire eligibility…</p>}
      {separated && cases.isError && (
        <p role="alert">
          {formatApiError(cases.error, 'Unable to check rehire eligibility.')}{' '}
          <button type="button" onClick={() => void cases.refetch()}>
            Retry
          </button>
        </p>
      )}
      {separated && cases.isSuccess && !eligibleSeparation && (
        <p>The latest completed separation must confirm rehire eligibility.</p>
      )}
      {open && periods.isPending && <p role="status">Loading employment periods…</p>}
      {periods.isError && (
        <p role="alert">
          {formatApiError(periods.error, 'Unable to load employment periods.')}{' '}
          <button type="button" onClick={() => void periods.refetch()}>
            Retry
          </button>
        </p>
      )}
      {periods.data && periods.data.total > 0 && (
        <section aria-label="Recorded employment periods" className="space-y-1">
          <h4 className="font-medium">Recorded employment periods</h4>
          <ul>
            {periods.data.items.map((period) => (
              <li key={period.id}>
                {period.started_on ?? 'Start date unrecorded'} to {period.ended_on ?? 'present'}
              </li>
            ))}
          </ul>
          {periods.data.total > pageSize && (
            <nav aria-label="Employment period pages">
              <button
                type="button"
                disabled={!periodOffset}
                onClick={() => setPeriodOffset(periodOffset - pageSize)}
              >
                Previous periods
              </button>
              <button
                type="button"
                disabled={periodOffset + pageSize >= periods.data.total}
                onClick={() => setPeriodOffset(periodOffset + pageSize)}
              >
                Next periods
              </button>
            </nav>
          )}
        </section>
      )}
      {propose.isError && (
        <p role="alert">{formatApiError(propose.error, 'Unable to save the proposal.')}</p>
      )}
      {update.isError && (
        <p role="alert">{formatApiError(update.error, 'Unable to update this change.')}</p>
      )}
      {open && changes.isPending && <p role="status">Loading employment changes…</p>}
      {changes.isError && (
        <p role="alert">
          {formatApiError(changes.error, 'Unable to load changes.')}{' '}
          <button type="button" onClick={() => void changes.refetch()}>
            Retry
          </button>
        </p>
      )}
      {changes.data?.total === 0 && <p>No employment changes recorded.</p>}
      {changes.data?.items.map((row) => (
        <article key={row.id} className="space-y-1 rounded border border-theme-border p-2">
          <h4 className="font-medium">
            {kinds[row.change_type]} · {row.effective_date} · {row.status}
          </h4>
          {displayUpdates(row.updates)}
          <p>{row.reason}</p>
          {row.decision_reason && <p>{row.decision_reason}</p>}
          {row.status === 'proposed' &&
            actorId !== row.proposed_by &&
            actorId !== employee.user_id && (
              <div className="flex flex-wrap items-end gap-2">
                <button
                  type="button"
                  disabled={busy}
                  onClick={() => update.mutate({ id: row.id, action: 'approved' })}
                >
                  Approve employment change
                </button>
                <label className="block">
                  Change rejection reason
                  <input
                    className={selectClass}
                    maxLength={500}
                    value={reasons[row.id] ?? ''}
                    onChange={(event) => setReasons({ ...reasons, [row.id]: event.target.value })}
                  />
                </label>
                <button
                  type="button"
                  disabled={busy || !reasons[row.id]?.trim()}
                  onClick={() => update.mutate({ id: row.id, action: 'rejected' })}
                >
                  Reject employment change
                </button>
              </div>
            )}
          {['proposed', 'approved'].includes(row.status) &&
            row.employee_revision !== employee.record_revision && (
              <p>
                The employee changed after this proposal. A new proposal is required to apply it.
              </p>
            )}
          {row.status === 'approved' && row.employee_revision === employee.record_revision && (
            <button
              type="button"
              disabled={busy}
              onClick={() => update.mutate({ id: row.id, action: 'apply' })}
            >
              Apply due employment change
            </button>
          )}
        </article>
      ))}
      {changes.data && changes.data.total > pageSize && (
        <div className="flex gap-2">
          <button type="button" disabled={!offset} onClick={() => setOffset(offset - pageSize)}>
            Previous changes
          </button>
          <button
            type="button"
            disabled={offset + pageSize >= changes.data.total}
            onClick={() => setOffset(offset + pageSize)}
          >
            Next changes
          </button>
        </div>
      )}
    </details>
  );
}
