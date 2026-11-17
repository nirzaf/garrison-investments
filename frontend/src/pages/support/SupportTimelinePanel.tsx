import { useState } from 'react';

import type { components } from '../../api/schema';
import { supportRequest } from '../../api/support';

type Timeline = components['schemas']['SupportTimelineRead'];

const labels: Record<string, string> = {
  created: 'Case opened',
  transitioned: 'Status changed',
  member_add: 'Member added',
  member_remove: 'Member removed',
  evidence_link: 'Request evidence linked',
  verify: 'Resolution verified',
  close: 'Case closed',
  subject_set: 'Case account approved',
  subject_remove: 'Case account removed',
  project_add: 'Project added to case scope',
  project_remove: 'Project removed from case scope'
};

export function SupportTimelinePanel({ caseId, onExpired }: {
  caseId: string; onExpired: () => void;
}) {
  const [timeline, setTimeline] = useState<Timeline | null>(null);
  const [pending, setPending] = useState(false);
  const [error, setError] = useState('');

  async function load() {
    if (pending) return;
    setPending(true);
    setTimeline(null);
    setError('');
    try {
      const response = await supportRequest('/cases/' + caseId + '/timeline');
      if (response.status === 401) onExpired();
      else if (!response.ok) setError('The case timeline could not be loaded.');
      else setTimeline(await response.json() as Timeline);
    } catch {
      setError('The case timeline could not be loaded.');
    } finally {
      setPending(false);
    }
  }

  return (
    <section aria-label="Case timeline" className="space-y-2 border-t pt-3">
      <h4 className="font-semibold">Case timeline</h4>
      <button type="button" disabled={pending} onClick={() => void load()}>Load case timeline</button>
      {pending && <p role="status">Loading timeline…</p>}
      {error && <p role="alert">{error}</p>}
      {timeline && (
        <>
          {timeline.events.length === 0 ? <p>No recorded events.</p> : (
            <ul className="space-y-3">
              {timeline.events.map((event) => (
                <li key={event.id}>
                  <p>{labels[event.kind] ?? 'Case decision'}{event.status && ' · ' + event.status}</p>
                  <time dateTime={event.occurred_at}>{new Date(event.occurred_at).toLocaleString()}</time>
                  {event.request_id && <p className="break-all">
                    Request {event.request_id}{event.request_status !== null && ' · HTTP ' + event.request_status}
                  </p>}
                </li>
              ))}
            </ul>
          )}
          {timeline.truncated && <p>Showing the 25 most recent events.</p>}
        </>
      )}
    </section>
  );
}
