import { useQuery, useQueryClient } from '@tanstack/react-query';
import { useRef, useState, type FormEvent } from 'react';

import { formatApiError } from '../../api/errors';
import {
  approveBenefitType,
  assignEmployeeBenefit,
  isApprovedBenefitPolicy,
  listBenefitTypes,
  listEmployeeBenefits,
  proposeBenefitType
} from '../../api/hr';
import { hrButtonClass, hrInputClass } from './HRAccessForms';

type Props = { employeeId: string; actorId: string; canReview: boolean };
const ceilingPattern = '[0-9]{1,13}(\\.[0-9]{1,2})?';

export function HRBenefits(props: Props) {
  const [open, setOpen] = useState(false);
  return (
    <details
      className="rounded border border-theme-border p-3"
      onToggle={(event) => setOpen(event.currentTarget.open)}
    >
      <summary className="cursor-pointer font-semibold">Benefit policies and coverage</summary>
      {open && <BenefitsPanel {...props} />}
    </details>
  );
}

function BenefitsPanel({ employeeId, actorId, canReview }: Props) {
  const client = useQueryClient();
  const [policyId, setPolicyId] = useState('');
  const [assignmentType, setAssignmentType] = useState('');
  const [pending, setPending] = useState(false);
  const [error, setError] = useState('');
  const [notice, setNotice] = useState('');
  const writing = useRef(false);
  const policies = useQuery({
    queryKey: ['hr', 'benefits', actorId, 'types'],
    queryFn: ({ signal }) => listBenefitTypes(signal),
    retry: false,
    gcTime: 0
  });
  const assignments = useQuery({
    queryKey: ['hr', 'benefits', actorId, employeeId, 'assignments'],
    queryFn: ({ signal }) => listEmployeeBenefits(employeeId, signal),
    retry: false,
    gcTime: 0
  });
  const capped = policies.data?.filter((item) => item.reimbursement_ceiling !== null) ?? [];
  const selected = capped.find((item) => item.id === policyId);
  const eligible = capped.filter(isApprovedBenefitPolicy);

  async function save(action: () => Promise<void>, message: string) {
    if (writing.current) return;
    writing.current = true;
    setPending(true);
    setError('');
    setNotice('');
    try {
      await action();
      setNotice(message);
      await client.invalidateQueries({ queryKey: ['hr', 'benefits', actorId] });
      await client.invalidateQueries({ queryKey: ['hr', 'advances', actorId, employeeId, 'coverage'] });
      await client.invalidateQueries({ queryKey: ['hr', 'reimbursements', actorId, employeeId, 'coverage'] });
    } catch (err) {
      setError(formatApiError(err, 'Unable to save the benefit record.'));
    } finally {
      writing.current = false;
      setPending(false);
    }
  }

  function propose(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    const form = event.currentTarget;
    const fields = new FormData(form);
    void save(async () => {
      const created = await proposeBenefitType({
        code: String(fields.get('code')).trim(),
        name: String(fields.get('name')).trim(),
        category: String(fields.get('category')).trim(),
        reimbursement_ceiling: String(fields.get('ceiling')),
        reimbursement_currency: String(fields.get('currency')).toUpperCase(),
        allows_advances: fields.has('advances'),
        requires_policy_approval: true
      });
      setPolicyId(created.id);
      form.reset();
    }, 'Benefit policy proposed.');
  }

  function assign(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (!eligible.some((item) => item.id === assignmentType)) return;
    const form = event.currentTarget;
    const fields = new FormData(form);
    void save(async () => {
      await assignEmployeeBenefit({
        employee_id: employeeId,
        benefit_type_id: assignmentType,
        effective_from: String(fields.get('from')),
        effective_to: String(fields.get('to')),
        coverage_notes: String(fields.get('notes')).trim() || null
      });
      setAssignmentType('');
      form.reset();
    }, 'Benefit coverage assigned.');
  }

  function reload() {
    setNotice('');
    setError('');
    void Promise.all([policies.refetch(), assignments.refetch()]);
  }

  return (
    <section className="mt-3 space-y-3" aria-label="Benefit administration">
      {error && <p role="alert">{error}</p>}
      {notice && <p role="status">{notice}</p>}
      {(policies.isPending || assignments.isPending) && <p role="status">Loading benefit records…</p>}
      {(policies.isError || assignments.isError) && (
        <p role="alert">{formatApiError(policies.error ?? assignments.error, 'Unable to load benefit records.')}</p>
      )}
      <button className={hrButtonClass} type="button" disabled={pending} onClick={reload}>
        Refresh benefit records
      </button>
      {policies.isSuccess && (
        <>
          <label className="block">
            Benefit policy
            <select className={hrInputClass} value={policyId} disabled={pending}
              onChange={(event) => setPolicyId(event.target.value)}>
              <option value="">Select a benefit policy</option>
              {capped.map((item) => <option key={item.id} value={item.id}>{item.code} · {item.name}</option>)}
            </select>
          </label>
          {capped.length === 0 && <p>No capped benefit policies recorded.</p>}
          {selected && (
            <article className="space-y-2 rounded border border-theme-border p-3" aria-label="Selected benefit policy">
              <h4 className="font-semibold">{selected.name}</h4>
              <p>{selected.category} · Ceiling {selected.reimbursement_currency} {selected.reimbursement_ceiling}</p>
              <p>{selected.allows_advances ? 'Advances enabled' : 'Reimbursements only'}</p>
              <p>{!selected.is_active ? 'Inactive' : isApprovedBenefitPolicy(selected)
                ? 'Approved policy' : 'Pending independent approval'}</p>
              {canReview && selected.is_active && !selected.approved_at &&
                selected.proposed_by_id && selected.proposed_by_id !== actorId && (
                <button className={hrButtonClass} type="button" disabled={pending}
                  onClick={() => void save(async () => { await approveBenefitType(selected.id); }, 'Benefit policy approved.')}>
                  Approve benefit policy
                </button>
              )}
            </article>
          )}
          <form className="space-y-2 border-t border-theme-border pt-3" onSubmit={propose}>
            <h4 className="font-semibold">Propose a benefit policy</h4>
            <fieldset className="grid gap-2 sm:grid-cols-2" disabled={pending}>
              <label>Policy code<input className={hrInputClass} name="code" maxLength={40} required /></label>
              <label>Policy name<input className={hrInputClass} name="name" minLength={2} maxLength={160} required /></label>
              <label>Benefit category<input className={hrInputClass} name="category" minLength={2} maxLength={40} required /></label>
              <label>Coverage ceiling<input className={hrInputClass} name="ceiling" inputMode="decimal" pattern={ceilingPattern} required /></label>
              <label>Benefit currency<input className={hrInputClass} name="currency" pattern="[A-Za-z]{3}" required /></label>
              <label className="flex items-center gap-2"><input type="checkbox" name="advances" /> Allow advances</label>
            </fieldset>
            <button className={hrButtonClass} type="submit" disabled={pending}>Submit benefit policy</button>
          </form>
        </>
      )}
      {assignments.isSuccess && (
        <div className="space-y-2 border-t border-theme-border pt-3">
          <h4 className="font-semibold">Employee benefit coverage</h4>
          {assignments.data.length === 0 && <p>No benefit coverage assigned.</p>}
          {assignments.data.length > 0 && (
            <ul className="space-y-1" aria-label="Assigned benefit coverage">
              {assignments.data.map((item) => (
                <li key={item.id}>
                  {policies.data?.find((type) => type.id === item.benefit_type_id)?.name ?? 'Benefit'} ·{' '}
                  {item.effective_from} to {item.effective_to ?? 'Open ended'} · {item.status}
                </li>
              ))}
            </ul>
          )}
          {policies.isSuccess && eligible.length === 0 && <p>Approve a capped policy before assigning coverage.</p>}
          {eligible.length > 0 && (
            <form onSubmit={assign} className="space-y-2">
              <fieldset className="grid gap-2 sm:grid-cols-2" disabled={pending}>
                <label className="sm:col-span-2">
                  Approved policy for coverage
                  <select className={hrInputClass} value={assignmentType}
                    onChange={(event) => setAssignmentType(event.target.value)} required>
                    <option value="">Select approved policy</option>
                    {eligible.map((item) => <option key={item.id} value={item.id}>{item.code} · {item.name}</option>)}
                  </select>
                </label>
                <label>Coverage start<input className={hrInputClass} name="from" type="date" required /></label>
                <label>Coverage end<input className={hrInputClass} name="to" type="date" required /></label>
                <label className="sm:col-span-2">
                  Coverage notes (optional)
                  <textarea className={hrInputClass} name="notes" rows={2} />
                </label>
              </fieldset>
              <button className={hrButtonClass} type="submit" disabled={!assignmentType || pending}>Assign benefit coverage</button>
            </form>
          )}
        </div>
      )}
    </section>
  );
}
