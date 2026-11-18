import { useEffect, useRef, useState } from 'react';

import type { components } from '../../api/schema';
import { supportRequest } from '../../api/support';
import { buttonClass, formatObserved, panelCardClass, statusLabel } from './supportPanelUtils';

type BackupsMonitor = components['schemas']['SupportBackupsMonitorRead'];

export function SupportBackupsPanel({ onExpired }: { onExpired: () => void }) {
  const [pending, setPending] = useState(false);
  const [error, setError] = useState('');
  const [data, setData] = useState<BackupsMonitor | null>(null);
  const active = useRef<AbortController | null>(null);

  useEffect(() => () => active.current?.abort(), []);

  async function load() {
    active.current?.abort();
    const controller = new AbortController();
    active.current = controller;
    setPending(true);
    setError('');
    try {
      const response = await supportRequest('/monitor/backups', { signal: controller.signal });
      if (controller.signal.aborted) return;
      if (response.status === 401) {
        onExpired();
        return;
      }
      if (response.status === 403) {
        setError('Backup provenance is unavailable to your operator account.');
        return;
      }
      if (!response.ok) throw new Error();
      const payload = (await response.json()) as BackupsMonitor;
      if (!controller.signal.aborted) setData(payload);
    } catch {
      if (!controller.signal.aborted) {
        setData(null);
        setError('Backup status could not be loaded.');
      }
    } finally {
      if (!controller.signal.aborted) setPending(false);
    }
  }

  return (
    <section aria-label="Backup and recovery provenance" className={panelCardClass}>
      <h2 className="font-semibold">Backup and recovery provenance</h2>
      <button type="button" className={buttonClass} disabled={pending} onClick={() => void load()}>
        {pending ? 'Checking…' : 'Check recovery posture'}
      </button>
      {error && <p role="alert" className="text-sm">{error}</p>}
      {data && (
        <div className="space-y-3 text-xs">
          <div className="grid gap-2 sm:grid-cols-2">
            <div className="rounded border border-theme-border p-2">
              <p className="text-theme-text-secondary">Overall recovery posture</p>
              <p className="font-medium">{statusLabel(data.overall_recovery_posture)}</p>
            </div>
            <div className="rounded border border-theme-border p-2">
              <p className="text-theme-text-secondary">Scheduled DB backup</p>
              <p className="font-medium">{statusLabel(data.database_backup_status)}</p>
            </div>
            <div className="rounded border border-theme-border p-2">
              <p className="text-theme-text-secondary">Off-host DB + object backup set</p>
              <p className="font-medium">{statusLabel(data.authenticated_backup_set_status)}</p>
            </div>
            <div className="rounded border border-theme-border p-2">
              <p className="text-theme-text-secondary">Isolated restore drill</p>
              <p className="font-medium">{statusLabel(data.isolated_restore_status)}</p>
              <p className="text-[11px] text-theme-text-secondary">
                {data.latest_restore_covers_database && data.latest_restore_covers_objects
                  ? 'Coverage: Database + objects'
                  : data.latest_restore_covers_database
                    ? 'Coverage: Database only'
                    : data.latest_restore_covers_objects
                      ? 'Coverage: Objects only'
                      : 'Coverage: No verified drill'}
                {data.latest_restore_backup_set_id
                  ? data.latest_restore_matches_latest_set
                    ? ' · Matches latest set'
                    : ' · Periodic drill / different set'
                  : ''}
              </p>
            </div>
          </div>
          <p className="text-theme-text-secondary">
            Escalation procedure: <code>{data.escalation_reference}</code> · Observed{' '}
            <time dateTime={data.observed_at}>{formatObserved(data.observed_at)}</time>
          </p>
          {data.receipts.length > 0 ? (
            <div className="overflow-x-auto">
              <table className="min-w-full text-left">
                <thead>
                  <tr className="border-b border-theme-border">
                    <th className="py-1 pr-3">Kind</th>
                    <th className="py-1 pr-3">Domain</th>
                    <th className="py-1 pr-3">Outcome</th>
                    <th className="py-1 pr-3">Coverage</th>
                    <th className="py-1">Captured</th>
                  </tr>
                </thead>
                <tbody>
                  {data.receipts.map((row) => (
                    <tr key={row.receipt_id} className="border-b border-theme-border/50">
                      <td className="py-1 pr-3">{statusLabel(row.receipt_kind)}</td>
                      <td className="py-1 pr-3">{statusLabel(row.target_domain)}</td>
                      <td className="py-1 pr-3">{row.outcome}</td>
                      <td className="py-1 pr-3">
                        {row.covers_database ? 'DB ' : ''}
                        {row.covers_objects ? 'Objects' : 'No objects'}
                      </td>
                      <td className="py-1">
                        <time dateTime={row.captured_at}>{formatObserved(row.captured_at)}</time>
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          ) : (
            <p>No signed backup or restore receipts recorded.</p>
          )}
        </div>
      )}
    </section>
  );
}
