import { useState } from 'react';

import { recordProbationReview } from '../../api/hr';
import { hrButtonClass, hrInputClass } from './HRAccessForms';

type Decision = Omit<Parameters<typeof recordProbationReview>[1], 'expected_employee_revision'>;

export function HRProbationReview({
  category,
  pending,
  onReview
}: {
  category?: string | null;
  pending: boolean;
  onReview: (decision: Decision) => void;
}) {
  const [outcome, setOutcome] = useState<Decision['outcome']>('confirm');
  return (
    <form
      className="space-y-2 rounded border border-theme-border p-3"
      onSubmit={(event) => {
        event.preventDefault();
        const data = new FormData(event.currentTarget);
        onReview({
          outcome,
          reason: String(data.get('reason') ?? '').trim(),
          new_end_date: outcome === 'extend' ? String(data.get('new_date')) : null,
          confirmed_category:
            outcome === 'confirm' && category === 'probation'
              ? (data.get('category') as Decision['confirmed_category'])
              : null
        });
      }}
    >
      <label className="block">
        Probation outcome
        <select
          className={hrInputClass}
          value={outcome}
          onChange={(event) => setOutcome(event.target.value as Decision['outcome'])}
          disabled={pending}
        >
          <option value="confirm">Confirm employment</option>
          <option value="extend">Extend probation</option>
        </select>
      </label>
      {outcome === 'extend' && (
        <label className="block">
          New probation end date
          <input name="new_date" type="date" className={hrInputClass} required disabled={pending} />
        </label>
      )}
      {outcome === 'confirm' && category === 'probation' && (
        <label className="block">
          Confirmed employment category
          <select
            name="category"
            className={hrInputClass}
            defaultValue=""
            required
            disabled={pending}
          >
            <option value="">Choose a category</option>
            <option value="permanent">Permanent</option>
            <option value="contract">Contract</option>
            <option value="daily_wage">Daily wage</option>
            <option value="intern">Intern</option>
            <option value="consultant">Consultant</option>
          </select>
        </label>
      )}
      <label className="block">
        Probation review reason
        <input name="reason" className={hrInputClass} maxLength={500} required disabled={pending} />
      </label>
      <button className={hrButtonClass} type="submit" disabled={pending}>
        Record probation decision
      </button>
    </form>
  );
}
