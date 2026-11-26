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
            const rawRules = field('entitlement_rules').trim();
            const selectedProfile = field('profile');
            if (selectedProfile && !rawRules) {
              throw new Error('Paste the full HR-approved rules for the selected profile.');
            }
            let rules: PolicyInput['entitlement_rules'] = null;
            if (rawRules) {
              try {
                rules = JSON.parse(rawRules) as PolicyInput['entitlement_rules'];
              } catch {
                throw new Error('The managed entitlement profile must be valid JSON.');
              }
              if (selectedProfile && rules?.profile !== selectedProfile) {
                throw new Error('The JSON profile does not match the selected profile.');
              }
            }
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
              approve_immediately: false,
              entitlement_rules: rules
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
            {leaveTypes.map((type) => (
              <option key={type.id} value={type.id}>
                {type.name}{type.is_active ? '' : ' (policy setup required)'}
              </option>
            ))}
          </select>
        </label>
        <label>
          Garrisons managed entitlement profile
          <select name="profile" defaultValue="">
            <option value="">Existing generic policy rules</option>
            <option value="garrisons_annual_v1">Annual leave (14 days from service year 3)</option>
            <option value="garrisons_casual_v1">Casual leave (0.5 days per completed month)</option>
          </select>
        </label>
        <label>
          Approved rule profile JSON (optional for generic policies)
          <textarea
            className="min-h-40 font-mono"
            name="entitlement_rules"
            placeholder={'Paste the complete HR-approved JSON profile. Annual profiles require all 366 month/day entries in second_year_brackets; no bracket values are prefilled.'}
          />
        </label>
        <p className="text-xs text-theme-text-muted">
          Managed profiles stay inactive until approved by a different policy reviewer. Do not
          enter unapproved bracket values. The annual profile requires the complete HR-approved
          second-year calendar and the approved seven-day block basis.
        </p>
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
