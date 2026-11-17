import { useEffect, useRef, useState, type FormEvent, type MouseEvent } from 'react';

import type { components } from '../../api/schema';
import { readSupportLogStream, supportRequest } from '../../api/support';

type LogPage = components['schemas']['SupportRequestLogPage'];

export function SupportLogs({ onExpired, canFollow }: {
  onExpired: () => void;
  canFollow: boolean;
}) {
  const [result, setResult] = useState<LogPage | null>(null);
  const [mode, setMode] = useState<'search' | 'follow' | 'paused' | null>(null);
  const [error, setError] = useState('');
  const active = useRef<AbortController | null>(null);
  const cursor = useRef<string | null>(null);

  useEffect(() => () => active.current?.abort(), []);

  function reset() {
    cursor.current = null;
    setMode(null);
    setResult(null);
    setError('');
  }

  function pause(event: MouseEvent<HTMLButtonElement>) {
    event.preventDefault();
    active.current?.abort();
    active.current = null;
    setMode('paused');
  }

  async function load(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (active.current) return;
    const submitter = (event.nativeEvent as SubmitEvent).submitter;
    const follow = canFollow && submitter instanceof HTMLButtonElement && submitter.value === 'follow';
    const fields = new FormData(event.currentTarget);
    const caseId = encodeURIComponent(String(fields.get('case_id')).trim());
    const requestId = String(fields.get('request_id')).trim();
    const hours = String(fields.get('hours'));
    const now = Date.now();
    const params = new URLSearchParams(follow ? { request_id: requestId, hours } : {
      request_id: requestId,
      started_at: new Date(now - Number(hours) * 3600000).toISOString(),
      ended_at: new Date(now).toISOString()
    });
    const resume = follow ? cursor.current : null;
    if (!resume) reset();
    const controller = new AbortController();
    active.current = controller;
    setMode(follow ? 'follow' : 'search');
    setError('');
    try {
      const response = await supportRequest(
        `/cases/${caseId}/logs${follow ? '/stream' : ''}?${params}`,
        { signal: controller.signal, headers: resume ? { 'Last-Event-ID': resume } : {} }
      );
      if (controller.signal.aborted) return;
      if (response.status === 401) {
        onExpired();
      } else if (response.status === 403 || response.status === 404) {
        reset();
        setError('This case or request is unavailable to your operator account.');
      } else if (response.status === 429) {
        setError(follow ? 'Close another live stream before retrying.' : 'Wait before searching again.');
      } else if (follow && response.status === 409) {
        reset();
        setError('The previous stream position is unavailable. Start a new stream.');
      } else if (!response.ok) {
        setError('Request evidence could not be loaded.');
      } else if (follow) {
        for await (const frame of readSupportLogStream(response)) {
          if (controller.signal.aborted) return;
          if (frame.kind === 'closed') {
            if (frame.reason === 'session_ended') onExpired();
            else if (frame.reason === 'access_ended') {
              reset();
              setError('Access to this evidence ended.');
            } else if (frame.reason !== 'time_limit') {
              setError('The evidence stream is temporarily unavailable.');
            }
            return;
          }
          const item = frame.event;
          cursor.current = item.id;
          setResult((current) => {
            const events = [item, ...(current?.events ?? []).filter((entry) => entry.id !== item.id)];
            return {
              request_id: requestId,
              events: events.slice(0, 100),
              truncated: events.length > 100 || Boolean(current?.truncated)
            };
          });
        }
        if (!controller.signal.aborted) setError('The evidence stream disconnected. Resume to reconnect.');
      } else {
        const page = await response.json() as LogPage;
        if (!controller.signal.aborted) setResult(page);
      }
    } catch {
      if (!controller.signal.aborted) setError('Request evidence could not be loaded.');
    } finally {
      if (active.current === controller) {
        active.current = null;
        setMode(follow && cursor.current ? 'paused' : null);
      }
    }
  }

  const pending = mode === 'search' || mode === 'follow';
  return (
    <section aria-label="Request evidence" className="space-y-4">
      <h2 className="font-semibold">Request evidence</h2>
      <form className="space-y-3" onSubmit={(event) => void load(event)} onChange={reset}>
        <label className="block">
          Case reference
          <input className="block w-full rounded border p-2" maxLength={36}
            name="case_id" required disabled={pending} />
        </label>
        <label className="block">
          Request ID
          <input className="block w-full rounded border p-2" maxLength={36}
            name="request_id" required disabled={pending} />
        </label>
        <label className="block">
          Time window
          <select className="block rounded border p-2" name="hours" disabled={pending}>
            <option value="1">Last hour</option>
            <option value="6">Last 6 hours</option>
            <option value="24">Last 24 hours</option>
          </select>
        </label>
        <button disabled={pending} type="submit">Search request evidence</button>
        {mode === 'follow' ? <button type="button" onClick={pause}>Pause live evidence</button> : canFollow && (
          <button disabled={pending} value="follow" type="submit">
            {mode === 'paused' ? 'Resume live evidence' : 'Follow live evidence'}
          </button>
        )}
      </form>
      {pending && <p role="status">{mode === 'follow' ? 'Following live evidence…' : 'Searching…'}</p>}
      {error && <p role="alert">{error}</p>}
      {result && (
        result.events.length ? (
          <>
            <ul className="space-y-2">
              {result.events.map((item) => (
                <li key={item.id}>
                  <time dateTime={item.occurred_at}>{new Date(item.occurred_at).toLocaleString()}</time>
                  {' · '}{item.kind.replace(/_/g, ' ')}{' · '}
                  {item.method ?? 'Unknown method'}{' · '}{item.status_code ?? 'Unknown status'}
                </li>
              ))}
            </ul>
            {result.truncated && <p>Showing the most recent matching events.</p>}
          </>
        ) : <p>No matching request evidence.</p>
      )}
    </section>
  );
}
