import { useMutation, useQuery } from '@tanstack/react-query';
import { useRef, useState } from 'react';

import { formatApiError } from '../../api/errors';
import {
  createMaterialRequest,
  fulfillMaterialRequest,
  listItemStock,
  listRequestProjects,
  type InventoryItemRecord,
  type MaterialQuantityCommand,
  type MaterialRequestRecord,
  type RequestProjectOption,
  type StorageLocationRecord
} from '../../api/inventory';
import { useDebouncedSearch } from '../../useDebouncedSearch';

const newLine = () => ({ key: crypto.randomUUID(), item_id: '', quantity: '' });

export function MaterialRequestForm({
  items,
  locations,
  onSuccess
}: {
  items: InventoryItemRecord[];
  locations: StorageLocationRecord[];
  onSuccess: () => void;
}) {
  const [search, setSearch] = useState('');
  const [project, setProject] = useState<RequestProjectOption>();
  const [locationId, setLocationId] = useState('');
  const [notes, setNotes] = useState('');
  const [lines, setLines] = useState(() => [newLine()]);
  const [error, setError] = useState<string | null>(null);
  const pending = useRef(false);
  const term = useDebouncedSearch(search);
  const projects = useQuery({
    queryKey: ['inventory-request-projects', term],
    queryFn: () => listRequestProjects(term || undefined)
  });
  const create = useMutation({ mutationFn: createMaterialRequest });
  const options = projects.data?.items ?? [];

  return (
    <form
      className="space-y-3 rounded-lg border border-theme-border bg-theme-card p-4"
      onSubmit={async (event) => {
        event.preventDefault();
        if (!project || !locationId || pending.current) return;
        if (new Set(lines.map((line) => line.item_id)).size !== lines.length) {
          setError('Select each inventory item once.');
          return;
        }
        pending.current = true;
        setError(null);
        try {
          await create.mutateAsync({
            project_id: project.id,
            from_location_id: locationId,
            notes,
            lines: lines.map(({ item_id, quantity }) => ({ item_id, quantity }))
          });
          setNotes('');
          setLines([newLine()]);
          onSuccess();
        } catch (cause) {
          setError(formatApiError(cause, 'Unable to create the material request.'));
        } finally {
          pending.current = false;
        }
      }}
    >
      <h3 className="font-semibold">Material request</h3>
      <label className="block text-sm">
        Search eligible projects
        <input
          className="form-field"
          value={search}
          onChange={(event) => setSearch(event.target.value)}
        />
      </label>
      <label className="block text-sm">
        Request project
        <select
          className="form-field"
          required
          value={project?.id ?? ''}
          onChange={(event) => {
            setProject(options.find((option) => option.id === event.target.value));
            setLocationId('');
          }}
        >
          <option value="">Select a project</option>
          {project && !options.some((item) => item.id === project.id) && (
            <option value={project.id}>{project.name}</option>
          )}
          {options.map((option) => (
            <option key={option.id} value={option.id}>
              {option.code} · {option.name}
            </option>
          ))}
        </select>
      </label>
      {projects.isPending && <p role="status">Loading eligible projects…</p>}
      {projects.isError && (
        <p role="alert">{formatApiError(projects.error, 'Unable to load eligible projects.')}</p>
      )}
      {projects.data?.total === 0 && <p>No eligible projects match your search.</p>}
      <label className="block text-sm">
        Source location
        <select
          className="form-field"
          required
          value={locationId}
          onChange={(event) => setLocationId(event.target.value)}
        >
          <option value="">Select a location</option>
          {locations
            .filter(
              (location) =>
                location.is_active && (!location.project_id || location.project_id === project?.id)
            )
            .map((location) => (
              <option key={location.id} value={location.id}>
                {location.name}
              </option>
            ))}
        </select>
      </label>
      {lines.map((line, index) => (
        <div className="grid gap-2 sm:grid-cols-[2fr_1fr_auto]" key={line.key}>
          <label className="text-sm">
            Item {index + 1}
            <select
              className="form-field"
              required
              value={line.item_id}
              onChange={(event) =>
                setLines((current) =>
                  current.map((entry) =>
                    entry.key === line.key ? { ...entry, item_id: event.target.value } : entry
                  )
                )
              }
            >
              <option value="">Select an item</option>
              {items
                .filter((item) => item.is_active)
                .map((item) => (
                  <option key={item.id} value={item.id}>
                    {item.name} · {item.unit}
                  </option>
                ))}
            </select>
          </label>
          <label className="text-sm">
            Quantity {index + 1}
            <input
              className="form-field"
              required
              type="number"
              min="0.001"
              step="0.001"
              value={line.quantity}
              onChange={(event) =>
                setLines((current) =>
                  current.map((entry) =>
                    entry.key === line.key ? { ...entry, quantity: event.target.value } : entry
                  )
                )
              }
            />
          </label>
          <button
            type="button"
            aria-label={`Remove line ${index + 1}`}
            disabled={lines.length === 1 || create.isPending}
            onClick={() => setLines((current) => current.filter((entry) => entry.key !== line.key))}
          >
            Remove
          </button>
        </div>
      ))}
      <button
        className="text-brand-600 underline"
        type="button"
        disabled={lines.length >= 100 || create.isPending}
        onClick={() => setLines((current) => [...current, newLine()])}
      >
        Add line
      </button>
      <label className="block text-sm">
        Notes
        <input
          className="form-field"
          value={notes}
          onChange={(event) => setNotes(event.target.value)}
        />
      </label>
      {error && <p role="alert">{error}</p>}
      <button className="form-button" type="submit" disabled={!project || create.isPending}>
        {create.isPending ? 'Creating…' : 'Create request'}
      </button>
    </form>
  );
}

function RequestLineAvailability({ itemId, locationId }: { itemId: string; locationId: string }) {
  const stock = useQuery({
    queryKey: ['inventory-stock', itemId],
    queryFn: () => listItemStock(itemId)
  });
  const balance = stock.data?.find((row) => row.location_id === locationId);
  if (stock.isPending) return <span>Loading availability…</span>;
  if (stock.isError) return <span role="alert">Availability unavailable</span>;
  return <span>{balance?.available_qty ?? '0'} available at source</span>;
}

export function MaterialFulfillment({
  request,
  items,
  canManage,
  onSuccess
}: {
  request: MaterialRequestRecord;
  items: InventoryItemRecord[];
  canManage: boolean;
  onSuccess: () => void;
}) {
  const [quantities, setQuantities] = useState<Record<string, string>>({});
  const [pending, setPending] = useState<'reserve' | 'issue' | null>(null);
  const [error, setError] = useState<string | null>(null);
  const attempt = useRef<{ signature: string; key: string } | null>(null);
  const inFlight = useRef(false);
  const eligible =
    canManage &&
    ['approved', 'reserved', 'partially_reserved', 'partially_issued'].includes(request.status);

  async function fulfill(action: 'reserve' | 'issue') {
    if (inFlight.current) return;
    const command: MaterialQuantityCommand = {
      expected_revision: request.revision,
      lines: request.lines
        .filter((line) => quantities[line.id]?.trim())
        .map((line) => ({ line_id: line.id, quantity: quantities[line.id] }))
    };
    if (!command.lines.length) {
      setError('Enter a quantity for at least one line.');
      return;
    }
    const signature = JSON.stringify([action, command]);
    if (attempt.current?.signature !== signature)
      attempt.current = { signature, key: crypto.randomUUID() };
    inFlight.current = true;
    setPending(action);
    setError(null);
    try {
      await fulfillMaterialRequest(request.id, action, command, attempt.current.key);
      setQuantities({});
      attempt.current = null;
      onSuccess();
    } catch (cause) {
      setError(formatApiError(cause, 'Unable to apply the selected quantities.'));
    } finally {
      inFlight.current = false;
      setPending(null);
    }
  }

  return (
    <details className="mt-2 rounded-md border border-theme-border p-2">
      <summary className="cursor-pointer font-medium">Request lines</summary>
      {request.lines.map((line) => {
        const item = items.find((candidate) => candidate.id === line.item_id);
        const outstanding = (Number(line.quantity) - Number(line.issued_quantity)).toFixed(3);
        return (
          <div className="mt-2 border-t border-theme-border pt-2" key={line.id}>
            <p>
              {item?.name ?? line.item_id} {item?.unit && `(${item.unit})`}
            </p>
            <p className="text-xs text-theme-text-muted">
              {line.quantity} requested · {outstanding} outstanding · {line.reserved_quantity}{' '}
              reserved · {line.issued_quantity} issued
            </p>
            {eligible && (
              <label className="block text-sm">
                Quantity for {item?.name ?? 'this line'}
                <input
                  className="form-field"
                  type="number"
                  min="0.001"
                  step="0.001"
                  disabled={pending !== null}
                  value={quantities[line.id] ?? ''}
                  onChange={(event) =>
                    setQuantities({ ...quantities, [line.id]: event.target.value })
                  }
                />
                {request.from_location_id && (
                  <RequestLineAvailability
                    itemId={line.item_id}
                    locationId={request.from_location_id}
                  />
                )}
              </label>
            )}
          </div>
        );
      })}
      {error && (
        <p role="alert" className="mt-2">
          {error}
        </p>
      )}
      {eligible && (
        <div className="mt-2 flex flex-wrap gap-2">
          <button
            className="form-button"
            type="button"
            disabled={pending !== null}
            onClick={() => void fulfill('reserve')}
          >
            {pending === 'reserve' ? 'Reserving…' : 'Reserve selected'}
          </button>
          <button
            className="form-button"
            type="button"
            disabled={pending !== null}
            onClick={() => void fulfill('issue')}
          >
            {pending === 'issue' ? 'Issuing…' : 'Issue selected'}
          </button>
        </div>
      )}
    </details>
  );
}
