import { useState } from 'react';

import { updateApplicationStage, type ApplicationRecord, type HrSchemas } from '../../api/hr';
import { hrButtonClass, hrInputClass } from './HRAccessForms';

type Withdrawal = HrSchemas['ApplicationWithdrawalRequest'];
const withdrawableStages: ReadonlySet<string> = new Set<Withdrawal['expected_stage']>([
  'applied',
  'screening',
  'shortlisted',
  'interview',
  'evaluation',
  'offer'
]);

export function HRApplicationWithdrawal({
  application,
  pending,
  change
}: {
  application: ApplicationRecord;
  pending: boolean;
  change: (action: () => Promise<unknown>) => Promise<void>;
}) {
  const [reviewedStage, setReviewedStage] = useState<Withdrawal['expected_stage'] | null>(null);
  const [retention, setRetention] = useState<Withdrawal['retention_decision'] | ''>('');

  if (application.stage === 'withdrawn') {
    return (
      <div className="mt-2 space-y-1 text-sm">
        {application.withdrawal_reason && <p>{application.withdrawal_reason}</p>}
        {application.retention_decision === 'retain_until_review' ? (
          <p>
            Retain until review on {application.retention_review_on}
            {' · '}Policy {application.retention_policy_reference}
          </p>
        ) : (
          <p>
            {application.retention_decision
              ? 'Retention policy review required'
              : 'Recorded before retention decisions were available'}
          </p>
        )}
      </div>
    );
  }

  if (!withdrawableStages.has(application.stage)) return null;

  if (!reviewedStage)
    return (
      <button
        className={hrButtonClass}
        type="button"
        disabled={pending}
        onClick={() => setReviewedStage(application.stage as Withdrawal['expected_stage'])}
      >
        Withdraw application
      </button>
    );

  return (
    <form
      className="mt-2 space-y-2 rounded border border-theme-border p-2"
      onSubmit={(event) => {
        event.preventDefault();
        if (pending || !retention) return;
        const data = new FormData(event.currentTarget);
        const withdrawal: Withdrawal = {
          expected_stage: reviewedStage,
          reason: String(data.get('reason')).trim(),
          retention_decision: retention
        };
        if (retention === 'retain_until_review') {
          withdrawal.retention_review_on = String(data.get('review_on'));
          withdrawal.retention_policy_reference = String(data.get('policy')).trim();
        }
        void change(() =>
          updateApplicationStage(application.id, { stage: 'withdrawn', withdrawal })
        );
      }}
    >
      <fieldset className="grid gap-2 sm:grid-cols-2" disabled={pending}>
        <label className="sm:col-span-2">
          Withdrawal reason
          <textarea name="reason" minLength={2} maxLength={500} required className={hrInputClass} />
        </label>
        <label className="sm:col-span-2">
          Retention decision
          <select
            required
            value={retention}
            onChange={(event) => setRetention(event.target.value as typeof retention)}
            className={hrInputClass}
          >
            <option value="">Choose retention decision</option>
            <option value="policy_review_required">Refer for retention policy review</option>
            <option value="retain_until_review">Retain under policy until review</option>
          </select>
        </label>
        {retention === 'retain_until_review' && (
          <>
            <label>
              Retention review date
              <input name="review_on" type="date" required className={hrInputClass} />
            </label>
            <label>
              Approved retention policy reference
              <input name="policy" maxLength={120} required className={hrInputClass} />
            </label>
          </>
        )}
        <div className="flex gap-2 sm:col-span-2">
          <button type="submit" className={hrButtonClass} disabled={!retention}>
            Confirm withdrawal
          </button>
          <button
            type="button"
            className={hrButtonClass}
            onClick={() => {
              setRetention('');
              setReviewedStage(null);
            }}
          >
            Keep application
          </button>
        </div>
      </fieldset>
    </form>
  );
}
