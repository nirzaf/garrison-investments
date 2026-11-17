import { useState, type FormEvent } from 'react';

import type { components } from '../../api/schema';
import { supportRequest } from '../../api/support';

type RecoveryStatus = components['schemas']['SupportRecoveryStatus'];
const uuidPattern = '[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}';

const deliveryLabels: Record<RecoveryStatus['delivery_state'], string> = {
  not_queued: 'Not queued',
  pending: 'Queued',
  dispatching: 'Sending',
  accepted: 'Accepted by the mail provider',
  unknown: 'Delivery outcome unknown',
  cancelled: 'Cancelled before sending'
};

const resetLabels: Record<RecoveryStatus['reset_state'], string> = {
  not_issued: 'Not issued',
  waiting: 'Waiting for delivery',
  ready: 'Ready for the account owner',
  unavailable: 'Unavailable',
  completed: 'Password reset completed',
  expired: 'Expired',
  revoked: 'Revoked'
};

export function SupportRecoveryStatusPanel({ onExpired }: { onExpired: () => void }) {
  const [result, setResult] = useState<RecoveryStatus | null>(null);
  const [pending, setPending] = useState(false);
  const [error, setError] = useState('');

  async function check(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (pending) return;
    const fields = new FormData(event.currentTarget);
    const caseId = String(fields.get('case_id')).toLowerCase();
    const actionId = String(fields.get('action_id')).toLowerCase();
    setPending(true);
    setError('');
    setResult(null);
    try {
      const response = await supportRequest(
        '/cases/' + encodeURIComponent(caseId) + '/account-actions/' +
        encodeURIComponent(actionId) + '/recovery-status'
      );
      if (response.status === 401) return onExpired();
      if (response.status === 403 || response.status === 404) {
        setError('Recovery status is unavailable for this case and action.');
        return;
      }
      if (!response.ok) throw new Error();
      const status = await response.json() as RecoveryStatus;
      if (status.case_id !== caseId || status.action_id !== actionId) throw new Error();
      setResult(status);
    } catch {
      setError('The recovery status could not be loaded.');
    } finally {
      setPending(false);
    }
  }

  return (
    <section aria-label="Recovery status" className="space-y-2 border-t pt-3">
      <h2 className="font-semibold">Recovery status</h2>
      <form onSubmit={(event) => void check(event)}
        onChange={() => { setResult(null); setError(''); }}>
        <fieldset className="space-y-2" disabled={pending}>
          <label className="block">
            Case ID for recovery status
            <input name="case_id" required pattern={uuidPattern}
              className="block w-full rounded border p-2" />
          </label>
          <label className="block">
            Recovery action reference
            <input name="action_id" required pattern={uuidPattern}
              className="block w-full rounded border p-2" />
          </label>
          <button type="submit">{pending ? 'Checking…' : 'Check recovery status'}</button>
        </fieldset>
      </form>
      {error && <p role="alert">{error}</p>}
      {result && (
        <div role="status" className="space-y-1">
          <p>Delivery {deliveryLabels[result.delivery_state]}</p>
          <p>Reset {resetLabels[result.reset_state]}</p>
          {([
            ['Queued', result.queued_at],
            ['Delivery updated', result.delivery_resolved_at],
            ['Reset completed', result.completed_at]
          ] as const).map(([label, value]) => value && (
            <p key={label}>{label} <time dateTime={value}>{new Date(value).toLocaleString()}</time></p>
          ))}
        </div>
      )}
    </section>
  );
}
