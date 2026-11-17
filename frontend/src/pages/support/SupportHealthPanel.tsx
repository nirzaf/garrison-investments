import { useState } from 'react';

import type { components } from '../../api/schema';
import { supportRequest } from '../../api/support';

type Health = components['schemas']['SupportHealthRead'];

const componentsToShow = {
  database: 'PostgreSQL',
  redis: 'Redis',
  object_storage: 'Object storage'
} as const;

const labels: Record<Health['database'], string> = {
  operational: 'Operational',
  unavailable: 'Unavailable',
  unknown: 'Unknown'
};

export function SupportHealthPanel({ onExpired }: { onExpired: () => void }) {
  const [result, setResult] = useState<Health | null>(null);
  const [pending, setPending] = useState(false);
  const [message, setMessage] = useState('');

  async function check() {
    if (pending) return;
    setPending(true);
    setMessage('');
    setResult(null);
    try {
      const response = await supportRequest('/health');
      if (response.status === 401) {
        onExpired();
        return;
      }
      if (!response.ok) throw new Error();
      setResult(await response.json() as Health);
    } catch {
      setMessage('Service health could not be checked.');
    } finally {
      setPending(false);
    }
  }

  return (
    <section aria-label="Service health" className="space-y-2">
      <h2 className="font-semibold">Service health</h2>
      <button type="button" disabled={pending} onClick={() => void check()}>Check service health</button>
      {pending && <p role="status">Checking dependencies…</p>}
      {message && <p role="alert">{message}</p>}
      {result && (
        <>
          <dl className="space-y-1">
            {(Object.keys(componentsToShow) as (keyof typeof componentsToShow)[]).map((key) => (
              <div key={key} className="flex justify-between gap-2">
                <dt>{componentsToShow[key]}</dt>
                <dd>{labels[result[key]]}</dd>
              </div>
            ))}
          </dl>
          <time className="text-sm" dateTime={result.observed_at}>
            {new Date(result.observed_at).toLocaleString()}
          </time>
        </>
      )}
    </section>
  );
}
