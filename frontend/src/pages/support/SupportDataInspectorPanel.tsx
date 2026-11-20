import { useCallback, useEffect, useState, type FormEvent } from 'react';

import type { components } from '../../api/schema';
import { supportRequest } from '../../api/support';
import { buttonClass, panelCardClass } from './supportPanelUtils';

type CatalogRead = components['schemas']['SupportDataInspectorCatalogRead'];
type PageRead = components['schemas']['SupportDataInspectorPage'];

export function SupportDataInspectorPanel({ onExpired }: { onExpired: () => void }) {
  const [catalog, setCatalog] = useState<CatalogRead | null>(null);
  const [selectedEntity, setSelectedEntity] = useState('projects');
  const [search, setSearch] = useState('');
  const [status, setStatus] = useState('');
  const [page, setPage] = useState<PageRead | null>(null);
  const [pending, setPending] = useState(false);
  const [error, setError] = useState('');

  const loadCatalog = useCallback(async () => {
    try {
      const resp = await supportRequest('/company/data-inspector/entities');
      if (resp.status === 401) {
        onExpired();
        return;
      }
      if (resp.ok) {
        setCatalog((await resp.json()) as CatalogRead);
      }
    } catch {
      // Handled by query action
    }
  }, [onExpired]);

  useEffect(() => {
    void loadCatalog();
  }, [loadCatalog]);

  async function runQuery(e?: FormEvent<HTMLFormElement>) {
    e?.preventDefault();
    setPending(true);
    setError('');
    try {
      const params = new URLSearchParams();
      if (search.trim()) params.set('search', search.trim());
      if (status) params.set('status', status);
      params.set('limit', '25');
      const resp = await supportRequest(
        `/company/data-inspector/${encodeURIComponent(selectedEntity)}?${params.toString()}`
      );
      if (resp.status === 401) {
        onExpired();
        return;
      }
      if (!resp.ok) {
        setError('Inspector query could not be completed.');
        return;
      }
      setPage((await resp.json()) as PageRead);
    } catch {
      setError('Inspector query could not be completed.');
    } finally {
      setPending(false);
    }
  }

  const currentMeta = catalog?.entities.find((e) => e.entity_key === selectedEntity);

  return (
    <section aria-label="Registered non-sensitive data inspector" className={panelCardClass}>
      <h3 className="font-semibold">Registered non-sensitive data inspector</h3>
      <p className="text-xs text-theme-text-secondary">
        {catalog?.excluded_domains_notice ??
          'Read-only inspection of allowlisted non-sensitive operational records.'}
      </p>

      <form onSubmit={(e) => void runQuery(e)} className="grid gap-2 sm:grid-cols-4 text-xs">
        <label className="block">
          Registered entity
          <select
            aria-label="Registered entity"
            value={selectedEntity}
            onChange={(e) => {
              setSelectedEntity(e.target.value);
              setStatus('');
              setPage(null);
            }}
            className="mt-1 block w-full rounded border border-theme-border bg-theme-card px-2 py-1"
          >
            {(catalog?.entities ?? []).map((ent) => (
              <option key={ent.entity_key} value={ent.entity_key}>
                {ent.label}
              </option>
            ))}
          </select>
        </label>
        <label className="block">
          Search text
          <input
            type="search"
            aria-label="Inspector search"
            value={search}
            onChange={(e) => setSearch(e.target.value)}
            maxLength={120}
            className="mt-1 block w-full rounded border border-theme-border bg-theme-card px-2 py-1"
          />
        </label>
        <label className="block">
          Status filter
          <select
            aria-label="Inspector status filter"
            value={status}
            onChange={(e) => setStatus(e.target.value)}
            className="mt-1 block w-full rounded border border-theme-border bg-theme-card px-2 py-1"
          >
            <option value="">All statuses</option>
            {(currentMeta?.filterable_statuses ?? []).map((st) => (
              <option key={st} value={st}>
                {st}
              </option>
            ))}
          </select>
        </label>
        <div className="flex items-end">
          <button type="submit" className={buttonClass} disabled={pending}>
            {pending ? 'Querying…' : 'Inspect entity'}
          </button>
        </div>
      </form>

      {error && (
        <p role="alert" className="text-xs text-red-700">
          {error}
        </p>
      )}

      {page && (
        <div className="space-y-2 text-xs">
          <p className="text-theme-text-secondary">
            Total records in {page.entity_key}: <strong>{page.total}</strong>
          </p>
          <div className="overflow-x-auto">
            <table className="w-full border-collapse text-left">
              <thead>
                <tr className="border-b border-theme-border text-theme-text-secondary">
                  {page.columns.map((col) => (
                    <th key={col} className="py-1 pr-2 font-mono">
                      {col}
                    </th>
                  ))}
                </tr>
              </thead>
              <tbody>
                {page.rows.map((row, idx) => (
                  <tr key={String(row.id ?? idx)} className="border-b border-theme-border/50">
                    {page.columns.map((col) => (
                      <td key={col} className="py-1 pr-2 font-mono text-[11px]">
                        {String(row[col] ?? '—')}
                      </td>
                    ))}
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </div>
      )}
    </section>
  );
}
