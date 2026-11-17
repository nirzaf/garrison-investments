import { useState, type FormEvent } from 'react';

import type { components } from '../../api/schema';
import { supportRequest } from '../../api/support';

type Audit = components['schemas']['SupportAuditPage'];

export function SupportCaseAuditPanel({ onExpired }: { onExpired: () => void }) {
  const [audit, setAudit] = useState<Audit | null>(null);
  const [pending, setPending] = useState(false);
  const [error, setError] = useState('');

  async function load(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (pending) return;
    const fields = new FormData(event.currentTarget);
    const caseId = encodeURIComponent(String(fields.get('audit_case')));
    const now = Date.now();
    const params = new URLSearchParams({
      started_at: new Date(now - Number(fields.get('audit_hours')) * 3600000).toISOString(),
      ended_at: new Date(now).toISOString()
    });
    setPending(true);
    setAudit(null);
    setError('');
    try {
      const response = await supportRequest('/cases/' + caseId + '/audit?' + params);
      if (response.status === 401) onExpired();
      else if (!response.ok) setError('Audit evidence is unavailable for this case.');
      else setAudit(await response.json() as Audit);
    } catch {
      setError('The case audit could not be loaded.');
    } finally {
      setPending(false);
    }
  }

  return (
    <section aria-label="Case audit" className="space-y-2 border-t pt-3">
      <h2 className="font-semibold">Case audit</h2>
      <form className="space-y-2" onSubmit={(event) => void load(event)} onChange={() => setAudit(null)}>
        <label className="block">
          Case ID for audit
          <input name="audit_case" required maxLength={36} className="block w-full rounded border p-2" />
        </label>
        <label className="block">
          Audit time window
          <select name="audit_hours" className="block rounded border p-2">
            <option value="1">Last hour</option>
            <option value="6">Last 6 hours</option>
            <option value="24">Last 24 hours</option>
          </select>
        </label>
        <button type="submit" disabled={pending}>Read case audit</button>
      </form>
      {pending && <p role="status">Loading audit…</p>}
      {error && <p role="alert">{error}</p>}
      {audit && (
        <>
          {audit.events.length === 0 ? <p>No recorded audit events in this window.</p> : (
            <ul className="space-y-3">
              {audit.events.map((event) => (
                <li key={event.reference_id + ':' + event.operator_id} className="break-all">
                  <p>{event.family.replace(/_/g, ' ')} · {event.event.replace(/_/g, ' ')}</p>
                  <time dateTime={event.occurred_at}>{new Date(event.occurred_at).toLocaleString()}</time>
                  <p>Operator {event.operator_id}</p>
                </li>
              ))}
            </ul>
          )}
          {audit.truncated && <p>Showing the 25 most recent events in this window.</p>}
        </>
      )}
    </section>
  );
}
