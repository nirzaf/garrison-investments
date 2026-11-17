import { useEffect, useRef, useState } from 'react';

import type { components } from '../../api/schema';
import { supportRequest } from '../../api/support';
import {
  buttonClass,
  formatMetricValue,
  formatObserved,
  inputClass,
  panelCardClass,
  statusLabel,
  uuidPattern
} from './supportPanelUtils';

type IncidentsSummary = components['schemas']['SupportIncidentsSummaryRead'];

export function SupportIncidentsPanel({ onExpired }: { onExpired: () => void }) {
  const [hours, setHours] = useState('24');
  const [caseId, setCaseId] = useState('');
  const [pending, setPending] = useState(false);
  const [error, setError] = useState('');
  const [data, setData] = useState<IncidentsSummary | null>(null);
  const active = useRef<AbortController | null>(null);

  useEffect(() => () => active.current?.abort(), []);

  async function load() {
    active.current?.abort();
    const controller = new AbortController();
    active.current = controller;
    setPending(true);
    setError('');
    try {
      const params = new URLSearchParams({ hours });
      if (caseId.trim()) params.set('case_id', caseId.trim());
      const response = await supportRequest(`/incidents/summary?${params}`, {
        signal: controller.signal
      });
      if (controller.signal.aborted) return;
      if (response.status === 401) {
        onExpired();
        return;
      }
      if (response.status === 403 || response.status === 404) {
        setData(null);
        setError('Security summary is unavailable for this scope.');
        return;
      }
      if (!response.ok) throw new Error();
      const payload = (await response.json()) as IncidentsSummary;
      if (!controller.signal.aborted) setData(payload);
    } catch {
      if (!controller.signal.aborted) {
        setData(null);
        setError('Security incident summary could not be loaded.');
      }
    } finally {
      if (!controller.signal.aborted) setPending(false);
    }
  }

  return (
    <section aria-label="Security incidents summary" className={panelCardClass}>
      <h2 className="font-semibold">Security incidents summary</h2>
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
            <option value="6">6 hours</option>
            <option value="24">24 hours</option>
          </select>
        </label>
        <label className="text-xs">
          Optional case ID
          <input
            value={caseId}
            pattern={uuidPattern}
            disabled={pending}
            onChange={(event) => setCaseId(event.target.value)}
            placeholder="All approved event counts"
            className={inputClass}
          />
        </label>
        <button type="button" className={buttonClass} disabled={pending} onClick={() => void load()}>
          {pending ? 'Loading…' : 'Load incident summary'}
        </button>
      </div>
      {error && <p role="alert" className="text-sm">{error}</p>}
      {data && (
        <div className="space-y-2 text-xs">
          <div className="flex flex-wrap gap-3 text-theme-text-secondary">
            <span>Scope: {statusLabel(data.scope.kind)}</span>
            <span>Source: {statusLabel(data.source_status)}</span>
            <span>Freshness: {statusLabel(data.freshness)}</span>
            <span>
              Observed: <time dateTime={data.observed_at}>{formatObserved(data.observed_at)}</time>
            </span>
          </div>
          <dl className="grid gap-2 sm:grid-cols-2">
            {data.metrics.map((metric) => (
              <div key={metric.key} className="rounded border border-theme-border p-2">
                <dt className="text-theme-text-secondary">{metric.label}</dt>
                <dd className="font-medium">{formatMetricValue(metric)}</dd>
              </div>
            ))}
          </dl>
        </div>
      )}
    </section>
  );
}
