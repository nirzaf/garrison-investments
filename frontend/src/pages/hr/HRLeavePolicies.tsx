import { useQuery, useQueryClient } from '@tanstack/react-query';
import { useState } from 'react';

import { formatApiError } from '../../api/errors';
import {
  createLeavePolicy,
  decideLeavePolicy,
  listLeavePolicies,
  type HrSchemas,
  type LeaveTypeRecord
} from '../../api/hr';

const categories = [
  'permanent',
  'contract',
  'probation',
  'daily_wage',
  'intern',
  'consultant'
] as const;
type PolicyInput = HrSchemas['LeavePolicyCreateRequest'];

export function HRLeavePolicies({
  userId,
  leaveTypes
}: {
  userId: string;
  leaveTypes: LeaveTypeRecord[];
}) {
  const client = useQueryClient();
  const key = ['hr', 'leave-policies', userId];
  const policies = useQuery({ queryKey: key, queryFn: listLeavePolicies });
  const [pending, setPending] = useState(false);
  const [error, setError] = useState('');
  const [notice, setNotice] = useState('');

  async function change(action: () => Promise<unknown>, success: string) {
    if (pending) return;
    setPending(true);
    setError('');
    setNotice('');
    try {
      await action();
      await client.invalidateQueries({ queryKey: key });
      setNotice(success);
    } catch (failure) {
      setError(formatApiError(failure, 'Could not save the leave policy.'));
    } finally {
      setPending(false);
    }
  }

  return (
    <details className="border-t border-theme-border pt-3 text-sm">
      <summary>Leave policy proposals</summary>
      {error && <p role="alert">{error}</p>}
      {notice && <p role="status">{notice}</p>}
      <form
        className="mt-2 grid gap-2"
        onSubmit={(event) => {
          event.preventDefault();
          const form = event.currentTarget;
          const values = new FormData(form);
          const field = (name: string) => String(values.get(name) ?? '');
          void change(async () => {
            await createLeavePolicy({
              code: field('code'),
              name: field('name'),
              leave_type_id: field('type'),
              employment_category:
                (field('category') as PolicyInput['employment_category']) || null,
              effective_from: field('from'),
              effective_to: field('to'),
              annual_entitlement_days: field('entitlement'),
              accrual_frequency: field('frequency') as PolicyInput['accrual_frequency'],
              prorate_by_calendar_day: values.has('prorate'),
              max_carry_forward_days: field('carry'),
              allow_negative_balance: values.has('negative'),
              expire_excess_on_rollover: values.has('expireExcess'),
              approve_immediately: false
            });
            form.reset();
          }, 'Leave policy proposed for independent review.');
        }}
      >
        <label>
          Policy code <input name="code" maxLength={40} required />
        </label>
        <label>
          Policy name <input name="name" maxLength={160} required />
        </label>
        <label>
          Policy leave type{' '}
          <select name="type" required>
            {leaveTypes
              .filter((type) => type.is_active)
              .map((type) => (
                <option key={type.id} value={type.id}>
                  {type.name}
                </option>
              ))}
          </select>
        </label>
        <label>
          Employment category{' '}
          <select name="category">
            <option value="">All categories</option>
            {categories.map((category) => (
              <option key={category}>{category}</option>
            ))}
          </select>
        </label>
        <label>
          Effective from <input name="from" type="date" required />
        </label>
        <label>
          Effective through <input name="to" type="date" required />
        </label>
        <label>
          Annual entitlement{' '}
          <input name="entitlement" type="number" min="0" max="999.99" step="0.01" required />
        </label>
        <label>
          Accrual frequency{' '}
          <select name="frequency" defaultValue="manual">
            <option value="manual">Manual</option>
            <option value="monthly">Monthly</option>
            <option value="annual">Annual</option>
          </select>
        </label>
        <label>
          <input name="prorate" type="checkbox" /> Prorate eligible calendar days in a partial
          monthly or annual period
        </label>
        <label>
          Maximum carry-forward{' '}
          <input
            name="carry"
            type="number"
            min="0"
            max="999.99"
            step="0.01"
            defaultValue="0"
            required
          />
        </label>
        <label>
          <input name="negative" type="checkbox" /> Allow negative leave balance
        </label>
        <label>
          <input name="expireExcess" type="checkbox" /> Expire days above the carry-forward cap at
          year-end
        </label>
        <button
          type="submit"
          disabled={pending}
          className="rounded bg-brand-600 px-3 py-1 text-white"
        >
          Propose leave policy
        </button>
      </form>
      {policies.isPending && <p role="status">Loading leave policies…</p>}
      {policies.isError && (
        <p role="alert">
          {formatApiError(policies.error, 'Could not load leave policies.')}{' '}
          <button type="button" onClick={() => void policies.refetch()}>
            Retry
          </button>
        </p>
      )}
      {policies.data?.items.length === 0 && <p>No leave policies yet.</p>}
      {policies.data?.items.map((policy) => (
        <article key={policy.id} className="mt-3 space-y-2 border-t border-theme-border pt-2">
          <p>
            {policy.code} · {policy.name} · {policy.status}
          </p>
          <p>
            {leaveTypes.find((type) => type.id === policy.leave_type_id)?.name ??
              'Archived leave type'}
            {' · '}
            {policy.employment_category ?? 'All categories'}
            {' · '}
            {policy.effective_from
              ? `${policy.effective_from} through ${policy.effective_to}`
              : 'Undated'}
          </p>
          <p>
            {policy.annual_entitlement_days} days · {policy.accrual_frequency} accrual ·
            Carry-forward {policy.max_carry_forward_days} days
          </p>
          <p>Negative balance {policy.allow_negative_balance ? 'allowed' : 'blocked'}</p>
          <p>Year-end expiry {policy.expire_excess_on_rollover ? 'authorized' : 'blocked'}</p>
          <p>
            {policy.prorate_by_calendar_day
              ? 'Partial periods prorated by eligible calendar days'
              : 'Full periods only'}
          </p>
          {policy.rejection_reason && <p>Rejection reason: {policy.rejection_reason}</p>}
          {policy.status === 'draft' && policy.created_by_id && policy.created_by_id !== userId && (
            <>
              <button
                type="button"
                disabled={pending}
                onClick={() =>
                  void change(
                    () => decideLeavePolicy(policy.id, { decision: 'approved' }),
                    'Leave policy approved.'
                  )
                }
              >
                Approve leave policy
              </button>
              <form
                onSubmit={(event) => {
                  event.preventDefault();
                  const reason = String(new FormData(event.currentTarget).get('reason') ?? '');
                  void change(
                    () => decideLeavePolicy(policy.id, { decision: 'rejected', reason }),
                    'Leave policy rejected.'
                  );
                }}
              >
                <label>
                  Rejection reason <input name="reason" maxLength={500} required />
                </label>
                <button type="submit" disabled={pending}>
                  Reject leave policy
                </button>
              </form>
            </>
          )}
        </article>
      ))}
    </details>
  );
}
