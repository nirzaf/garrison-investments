import { useQuery, useQueryClient } from '@tanstack/react-query';
import { useRef, useState, type FormEvent } from 'react';

import { formatApiError } from '../../api/errors';
import {
  approvePayrollPolicy, createPayrollPolicy, readPayrollPolicy, updatePayrollPolicyDraft,
  type PayrollPolicyRecord
} from '../../api/hr';
import { hrButtonClass, hrInputClass } from './HRAccessForms';

type Props = { actorId: string; canPrepare: boolean; canApprove: boolean };
const policyIdPattern = '[0-9A-Fa-f]{8}(-[0-9A-Fa-f]{4}){3}-[0-9A-Fa-f]{12}';
const exampleFields = [
  ['base_salary', 'Example base salary'],
  ['earnings', 'Example additional earnings'],
  ['extra_deductions', 'Example additional deductions'],
  ['expected_gross', 'Expected gross'],
  ['expected_deductions', 'Expected deductions'],
  ['expected_net', 'Expected net']
] as const;

export function HRPayrollPolicy({ actorId, canPrepare, canApprove }: Props) {
  const client = useQueryClient();
  const [policyId, setPolicyId] = useState('');
  const [createdId, setCreatedId] = useState('');
  const [editing, setEditing] = useState<PayrollPolicyRecord>();
  const [examples, setExamples] = useState(['initial']);
  const [pending, setPending] = useState(false);
  const [error, setError] = useState('');
  const [notice, setNotice] = useState('');
  const saving = useRef(false);
  const review = useQuery({
    queryKey: ['hr', 'payroll', actorId, 'policy', policyId],
    queryFn: async ({ signal }) => {
      const policy = await readPayrollPolicy(policyId, signal);
      if (policy.id !== policyId) throw new Error('Unexpected payroll policy');
      return policy;
    },
    enabled: (canPrepare || canApprove) && Boolean(policyId),
    gcTime: 0,
    refetchOnWindowFocus: false,
    refetchOnReconnect: false,
    retry: false
  });
  const policy = (canPrepare || canApprove) && review.isSuccess ? review.data : undefined;
  const editRecord = editing?.controlled_record;
  const editRules = editing?.rules_json;

  async function save(action: () => Promise<void>, message: string) {
    if (saving.current) return;
    saving.current = true;
    setPending(true);
    setError('');
    setNotice('');
    try {
      await action();
      await client.invalidateQueries({ queryKey: ['hr', 'payroll', actorId] });
      setNotice(message);
    } catch (failure) {
      setError(formatApiError(failure, 'Unable to save payroll policy.'));
    } finally {
      saving.current = false;
      setPending(false);
    }
  }

  function create(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (saving.current) return;
    const form = event.currentTarget;
    const fields = new FormData(form);
    const code = String(fields.get('code')).trim();
    const name = String(fields.get('name')).trim();
    if (!code || name.length < 2) {
      setError('Enter a policy code and a name of at least two characters.');
      setNotice('');
      return;
    }
    void save(async () => {
      const payload = {
        name,
        controlled_record: {
          document_reference: String(fields.get('reference')).trim(),
          version: String(fields.get('version')).trim(),
          effective_from: String(fields.get('effective_from')),
          approval_reference: String(fields.get('approval_reference')).trim(),
          worked_examples: examples.map((id) => ({
            base_salary: String(fields.get(`${id}:base_salary`)),
            earnings: String(fields.get(`${id}:earnings`) || '0.00'),
            extra_deductions: String(fields.get(`${id}:extra_deductions`) || '0.00'),
            expected_gross: String(fields.get(`${id}:expected_gross`)),
            expected_deductions: String(fields.get(`${id}:expected_deductions`)),
            expected_net: String(fields.get(`${id}:expected_net`))
          }))
        },
        rules_json: {
          calculation_basis: String(fields.get('basis')),
          pay_frequency: 'monthly',
          currency: String(fields.get('currency')).toUpperCase(),
          rounding: String(fields.get('rounding')),
          employee_deduction_rate: String(fields.get('rate'))
        }
      };
      const created = editing
        ? await updatePayrollPolicyDraft(editing.id, {
          ...payload, expected_updated_at: editing.updated_at
        })
        : await createPayrollPolicy({ ...payload, code });
      setCreatedId(created.id);
      setEditing(undefined);
      setExamples(['initial']);
      form.reset();
    }, editing ? 'Payroll policy draft updated.' : 'Payroll policy proposed.');
  }

  return (
    <section className="space-y-4 rounded border border-theme-border bg-theme-card p-4" aria-label="Payroll policy administration">
      <h3 className="font-semibold">Payroll policies</h3>
      {canPrepare && (
        <form key={editing?.id ?? 'new'} onSubmit={create} className="space-y-2">
          <h4 className="font-semibold">{editing ? 'Correct payroll policy draft' : 'Propose monthly payroll policy'}</h4>
          <fieldset disabled={pending} className="grid gap-2 sm:grid-cols-2">
            <label>Payroll policy code<input className={hrInputClass} name="code" maxLength={40} defaultValue={editing?.code} readOnly={Boolean(editing)} required /></label>
            <label>Payroll policy name<input className={hrInputClass} name="name" minLength={2} maxLength={160} defaultValue={editing?.name} required /></label>
            <label>Controlled document reference<input className={hrInputClass} name="reference" maxLength={120} defaultValue={editRecord?.document_reference} required /></label>
            <label>Document version<input className={hrInputClass} name="version" maxLength={40} defaultValue={editRecord?.version} required /></label>
            <label>Policy effective from<input className={hrInputClass} name="effective_from" type="date" defaultValue={editRecord?.effective_from} required /></label>
            <label>Business approval reference<input className={hrInputClass} name="approval_reference" maxLength={120} defaultValue={editRecord?.approval_reference} required /></label>
            <label>Calculation basis
              <select className={hrInputClass} name="basis" defaultValue={String(editRules?.calculation_basis ?? 'base_salary_only')}>
                <option value="base_salary_only">Base salary only</option>
                <option value="base_salary_with_reviewed_adjustments">Base salary with reviewed adjustments</option>
              </select>
            </label>
            <label>Currency code<input className={hrInputClass} name="currency" maxLength={3} pattern="[A-Za-z]{3}" defaultValue={String(editRules?.currency ?? '')} required /></label>
            <label>Rounding method
              <select className={hrInputClass} name="rounding" defaultValue={String(editRules?.rounding ?? '')} required>
                <option value="">Choose rounding method</option>
                <option value="half_even">Half even</option>
                <option value="half_up">Half up</option>
              </select>
            </label>
            <label>Employee deduction fraction (0–1)
              <input className={hrInputClass} name="rate" inputMode="decimal" pattern="(?:0(?:\.[0-9]{1,8})?|1(?:\.0{1,8})?)" defaultValue={String(editRules?.employee_deduction_rate ?? '')} required />
            </label>
          </fieldset>
          <p className="text-sm text-theme-text-muted">Enter the record IDs from HR’s restricted policy system.</p>
          <p className="text-sm text-theme-text-muted">Enter approved worked examples using synthetic amounts.</p>
          {examples.map((id, index) => (
            <fieldset key={id} disabled={pending} className="grid gap-2 sm:grid-cols-2">
              <legend>Worked example {index + 1}</legend>
              {exampleFields.map(([field, label]) => (
                <label key={field}>{label}
                  <input className={hrInputClass} name={`${id}:${field}`} inputMode="decimal"
                    pattern="[0-9]{1,16}(\.[0-9]{1,2})?"
                    defaultValue={String(editRecord?.worked_examples[Number(id)]?.[field] ?? '')}
                    required={field !== 'earnings' && field !== 'extra_deductions'} />
                </label>
              ))}
              {examples.length > 1 && (
                <button type="button" className={hrButtonClass}
                  onClick={() => setExamples((items) => items.filter((key) => key !== id))}>
                  Remove example {index + 1}
                </button>
              )}
            </fieldset>
          ))}
          <button className={hrButtonClass} type="button" disabled={pending || examples.length >= 12}
            onClick={() => setExamples((items) => [...items, crypto.randomUUID()])}>Add worked example</button>{' '}
          <button className={hrButtonClass} type="submit" disabled={pending}>
            {editing ? 'Save policy draft corrections' : 'Propose payroll policy'}
          </button>
          {editing && <button type="button" className={hrButtonClass} disabled={pending} onClick={() => {
            setEditing(undefined);
            setExamples(['initial']);
          }}>Cancel editing</button>}
          {createdId && <p>Share this policy ID with a separate reviewer. <code className="break-all" aria-label="Proposed payroll policy ID">{createdId}</code></p>}
        </form>
      )}
      {(canApprove || canPrepare) && (
        <form className="space-y-2" onSubmit={(event) => {
          event.preventDefault();
          setNotice('');
          setError('');
          const fields = new FormData(event.currentTarget);
          const id = String(fields.get('policy')).toLowerCase();
          if (id === policyId) void review.refetch();
          else setPolicyId(id);
        }}>
          <h4 className="font-semibold">Review a payroll policy</h4>
          <label className="block">Payroll policy ID
            <input className={hrInputClass} name="policy" required pattern={policyIdPattern} disabled={pending} />
          </label>
          <button className={hrButtonClass} type="submit" disabled={pending}>Open policy by ID</button>
        </form>
      )}
      {policyId && review.isFetching && <p role="status">Loading payroll policy…</p>}
      {policyId && review.isError && <p role="alert">{formatApiError(review.error, 'Unable to open this policy.')}</p>}
      {policy && (
        <article aria-label="Reviewed payroll policy" className="space-y-2 border-t border-theme-border pt-3">
          <h4 className="font-semibold">{policy.code} · {policy.name}</h4>
          <p>{policy.is_approved ? 'Approved payroll policy' : 'Awaiting independent approval'}</p>
          {policy.controlled_record ? (
            <dl className="grid grid-cols-2 gap-1">
              <dt>Controlled document reference</dt><dd>{policy.controlled_record.document_reference}</dd>
              <dt>Document version</dt><dd>{policy.controlled_record.version}</dd>
              <dt>Policy effective from</dt><dd>{policy.controlled_record.effective_from}</dd>
              <dt>Business approval reference</dt><dd>{policy.controlled_record.approval_reference}</dd>
            </dl>
          ) : <p>Legacy policy record without a controlled document reference.</p>}
          <pre aria-label="Proposed calculation rules" className="overflow-x-auto text-sm">{JSON.stringify(policy.rules_json, null, 2)}</pre>
          {policy.controlled_record && (
            <pre aria-label="Worked payroll examples" className="overflow-x-auto text-sm">
              {JSON.stringify(policy.controlled_record.worked_examples, null, 2)}
            </pre>
          )}
          {!policy.is_approved && policy.approved_by_id === actorId && <p>A different reviewer must approve this policy.</p>}
          {canPrepare && !editing && !policy.is_approved && policy.approved_by_id === actorId &&
            policy.controlled_record && (
              <button className={hrButtonClass} type="button" disabled={pending} onClick={() => {
                setEditing(policy);
                setExamples(policy.controlled_record?.worked_examples.map((_, index) => String(index)) ?? ['initial']);
              }}>Edit policy draft</button>
            )}
          {canApprove && !policy.is_approved && policy.approved_by_id && policy.approved_by_id !== actorId && (
            <button className={hrButtonClass} type="button" disabled={pending || review.isFetching}
              onClick={() => void save(async () => {
                await approvePayrollPolicy(policy.id, policy.updated_at);
              }, 'Payroll policy approved.')}>Approve reviewed payroll policy</button>
          )}
        </article>
      )}
      {error && <p role="alert">{error}</p>}
      {notice && <p role="status">{notice}</p>}
    </section>
  );
}
