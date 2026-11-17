import { useEffect, useRef, useState } from 'react';

import type { components } from '../../api/schema';
import { supportRequest } from '../../api/support';
import { buttonClass, formatObserved, inputClass, panelCardClass, statusLabel } from './supportPanelUtils';

type JobsMonitor = components['schemas']['SupportJobsMonitorRead'];

export function SupportJobsPanel({ onExpired }: { onExpired: () => void }) {
  const [hours, setHours] = useState('24');
  const [queue, setQueue] = useState('');
  const [pending, setPending] = useState(false);
  const [error, setError] = useState('');
  const [data, setData] = useState<JobsMonitor | null>(null);
  const active = useRef<AbortController | null>(null);

  useEffect(() => () => active.current?.abort(), []);

  async function load() {
    active.current?.abort();
    const controller = new AbortController();
    active.current = controller;
    setPending(true);
    setError('');
    try {
      const params = new URLSearchParams({ hours, limit: '25' });
      if (queue) params.set('queue', queue);
      const response = await supportRequest(`/monitor/jobs?${params}`, {
        signal: controller.signal
      });
      if (controller.signal.aborted) return;
      if (response.status === 401) {
        onExpired();
        return;
      }
      if (response.status === 403) {
        setError('Jobs monitoring is unavailable to your operator account.');
        return;
      }
      if (!response.ok) throw new Error();
      const payload = (await response.json()) as JobsMonitor;
      if (!controller.signal.aborted) setData(payload);
    } catch {
      if (!controller.signal.aborted) {
        setData(null);
        setError('Job monitor state could not be loaded.');
      }
    } finally {
      if (!controller.signal.aborted) setPending(false);
    }
  }

  return (
    <section aria-label="Jobs and scheduler monitor" className={panelCardClass}>
      <h2 className="font-semibold">Jobs and scheduler monitor</h2>
      <div className="flex flex-wrap items-end gap-2">
        <label className="text-xs">
          Window
          <select
            value={hours}
            disabled={pending}
            onChange={(event) => setHours(event.target.value)}
            className={inputClass}
          >
            <option value="1">1 hour</option>
            <option value="24">24 hours</option>
            <option value="72">72 hours</option>
            <option value="168">7 days</option>
          </select>
        </label>
        <label className="text-xs">
          Queue
          <select
            value={queue}
            disabled={pending}
            onChange={(event) => setQueue(event.target.value)}
            className={inputClass}
          >
            <option value="">All queues</option>
            <option value="maintenance">Maintenance</option>
            <option value="backup">Backup</option>
            <option value="email">Email</option>
            <option value="reports">Reports</option>
            <option value="images">Images</option>
          </select>
        </label>
        <button type="button" className={buttonClass} disabled={pending} onClick={() => void load()}>
          {pending ? 'Checking…' : 'Check job status'}
        </button>
      </div>
      {error && <p role="alert" className="text-sm">{error}</p>}
      {data && (
        <div className="space-y-3 text-xs">
          <div className="flex flex-wrap gap-3 text-theme-text-secondary">
            <span>Broker: {statusLabel(data.broker_status)}</span>
            <span>Source: {statusLabel(data.source_status)}</span>
            <span>
              Observed: <time dateTime={data.observed_at}>{formatObserved(data.observed_at)}</time>
            </span>
          </div>
          <div className="grid gap-2 sm:grid-cols-3">
            <div className="rounded border border-theme-border p-2">
              <p className="text-theme-text-secondary">Outbox queue</p>
              <p className="font-medium">
                Pending {data.outbox_pending ?? 'Unavailable'} · Failed{' '}
                {data.outbox_failed ?? 'Unavailable'}
              </p>
              {data.outbox_oldest_age_seconds != null && (
                <p>Oldest age: {data.outbox_oldest_age_seconds}s</p>
              )}
            </div>
            <div className="rounded border border-theme-border p-2">
              <p className="text-theme-text-secondary">Recovery deliveries</p>
              <p className="font-medium">
                Pending {data.recovery_pending ?? 'Unavailable'} · Unknown{' '}
                {data.recovery_unknown ?? 'Unavailable'}
              </p>
            </div>
            <div className="rounded border border-theme-border p-2">
              <p className="text-theme-text-secondary">Configured beat tasks</p>
              <p className="font-medium">{data.schedules.length}</p>
            </div>
          </div>
          <div className="overflow-x-auto">
            <table className="min-w-full text-left">
              <thead>
                <tr className="border-b border-theme-border">
                  <th className="py-1 pr-3">Task</th>
                  <th className="py-1 pr-3">Queue</th>
                  <th className="py-1 pr-3">State</th>
                  <th className="py-1">Schedule</th>
                </tr>
              </thead>
              <tbody>
                {data.schedules.map((item) => (
                  <tr key={item.job_name} className="border-b border-theme-border/50">
                    <td className="py-1 pr-3 font-mono">{item.task_name}</td>
                    <td className="py-1 pr-3">{item.queue}</td>
                    <td className="py-1 pr-3">{statusLabel(item.state)}</td>
                    <td className="py-1">{item.schedule_summary}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
          {data.recent_events.length > 0 && (
            <ul aria-label="Recent task lifecycle events" className="space-y-1">
              {data.recent_events.map((ev) => (
                <li key={ev.event_id}>
                  <code>{ev.task_name}</code> · {ev.event} ·{' '}
                  <time dateTime={ev.occurred_at}>{formatObserved(ev.occurred_at)}</time>
                </li>
              ))}
            </ul>
          )}
        </div>
      )}
    </section>
  );
}
