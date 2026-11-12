import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import { isAxiosError } from 'axios';
import { ArrowRightLeft, MapPinned, PackagePlus, Warehouse } from 'lucide-react';
import { useEffect, useRef, useState } from 'react';
import { useSearchParams } from 'react-router-dom';

import {
  cancelMaterialRequest,
  createAsset,
  createInventoryItem,
  createLocation,
  createMovement,
  listAssets,
  listInventoryItemPage,
  listInventoryItems,
  listItemStock,
  listLocations,
  listLowStock,
  listMaterialRequests,
  listMovements,
  listSuppliers,
  type InventoryItemRecord,
  type MovementCreatePayload
} from '../../api/inventory';
import { formatApiError } from '../../api/errors';
import { listProjects } from '../../api/projects';
import { EmptyState } from '../../components/shared/EmptyState';
import { StatusBadge } from '../../components/shared/StatusBadge';
import { useAuth } from '../../context/useAuth';
import { MaterialFulfillment, MaterialRequestForm } from './MaterialRequestControls';

const inventoryPageSize = 20;
const movementPageSize = 8;
type MovementForm = 'receipt' | 'movement';
type MovementAttempt = { form: MovementForm; payload: MovementCreatePayload; key: string };

export function InventoryPage() {
  const { user } = useAuth();
  const [searchParams] = useSearchParams();
  const focusedRequestId = searchParams.get('materialRequestId');
  const queryClient = useQueryClient();
  const [pickedItem, setPickedItem] = useState<InventoryItemRecord>();
  const movementInFlight = useRef(false);
  const [movementAttempt, setMovementAttempt] = useState<MovementAttempt | null>(null);
  const [movementError, setMovementError] = useState<{ form: MovementForm; detail: string } | null>(
    null
  );
  const [stockLocation, setStockLocation] = useState('');
  const [itemSearch, setItemSearch] = useState('');
  const [committedSearch, setCommittedSearch] = useState('');
  const [itemOffset, setItemOffset] = useState(0);
  const [requestOffset, setRequestOffset] = useState(0);
  const [movementOffset, setMovementOffset] = useState(0);
  const materialRequestRefs = useRef<Record<string, HTMLElement | null>>({});
  const canManageInventory = user?.permissions?.includes('inventory:manage') ?? false;
  const canCreateMaterialRequest =
    user?.role === 'admin' ||
    user?.role === 'project_manager' ||
    user?.role === 'civil_engineer' ||
    user?.role === 'store_keeper';
  const locations = useQuery({ queryKey: ['inventory-locations'], queryFn: listLocations });
  const suppliers = useQuery({
    queryKey: ['suppliers'],
    queryFn: listSuppliers,
    enabled: canManageInventory
  });
  const items = useQuery({ queryKey: ['inventory-items'], queryFn: () => listInventoryItems() });
  const visibleItems = useQuery({
    queryKey: ['inventory-items', committedSearch, itemOffset],
    queryFn: ({ signal }) =>
      listInventoryItemPage(
        {
          search: committedSearch || undefined,
          limit: inventoryPageSize,
          offset: itemOffset
        },
        signal
      )
  });
  const lowStock = useQuery({ queryKey: ['inventory-low-stock'], queryFn: listLowStock });
  const assets = useQuery({ queryKey: ['inventory-assets'], queryFn: listAssets });
  const movements = useQuery({
    queryKey: ['inventory-movements', movementOffset],
    queryFn: ({ signal }) =>
      listMovements({ limit: movementPageSize, offset: movementOffset }, signal)
  });
  const materialRequests = useQuery({
    queryKey: ['material-requests', requestOffset],
    queryFn: ({ signal }) =>
      listMaterialRequests({ limit: inventoryPageSize, offset: requestOffset }, signal)
  });
  const focusedRequest = useQuery({
    queryKey: ['material-requests', 'detail', focusedRequestId],
    queryFn: ({ signal }) =>
      listMaterialRequests(
        {
          limit: 1,
          offset: 0,
          request_id: focusedRequestId ?? undefined
        },
        signal
      ),
    enabled: Boolean(focusedRequestId) && requestOffset === 0
  });
  const pageRequests = materialRequests.data?.items ?? [];
  const linkedRequest = focusedRequest.data?.items[0];
  const visibleRequests =
    requestOffset === 0 && linkedRequest && !pageRequests.some((row) => row.id === linkedRequest.id)
      ? [linkedRequest, ...pageRequests]
      : pageRequests;
  const projects = useQuery({
    queryKey: ['projects', 'active'],
    queryFn: () => listProjects({ status: 'active' }),
    enabled: canManageInventory && (user?.permissions?.includes('projects:read') ?? false)
  });
  const selectedItem = pickedItem ?? items.data?.[0];
  const stock = useQuery({
    queryKey: ['inventory-stock', selectedItem?.id],
    queryFn: () => listItemStock(selectedItem!.id),
    enabled: Boolean(selectedItem)
  });
  const balances =
    stock.data?.filter((row) => !stockLocation || row.location_id === stockLocation) ?? [];

  function refreshInventory() {
    for (const key of [
      'material-requests',
      'inventory-stock',
      'inventory-low-stock',
      'inventory-movements',
      'approvals'
    ]) {
      void queryClient.invalidateQueries({ queryKey: [key] });
    }
  }

  const createLocationMutation = useMutation({
    mutationFn: createLocation,
    onSuccess: () => void queryClient.invalidateQueries({ queryKey: ['inventory-locations'] })
  });
  const createItemMutation = useMutation({
    mutationFn: createInventoryItem,
    onSuccess: () => void queryClient.invalidateQueries({ queryKey: ['inventory-items'] })
  });
  const createAssetMutation = useMutation({
    mutationFn: createAsset,
    onSuccess: () => void queryClient.invalidateQueries({ queryKey: ['inventory-assets'] })
  });
  const createMovementMutation = useMutation({
    mutationFn: ({ payload, key }: MovementAttempt) => createMovement(payload, key),
    onSuccess: () => {
      refreshInventory();
      void queryClient.invalidateQueries({ queryKey: ['inventory-assets'] });
    }
  });
  async function submitMovement(
    form: MovementForm,
    element: HTMLFormElement,
    payload: MovementCreatePayload
  ) {
    if (movementInFlight.current || (movementAttempt && movementAttempt.form !== form)) return;
    const attempt = movementAttempt ?? { form, payload, key: crypto.randomUUID() };
    movementInFlight.current = true;
    setMovementAttempt(attempt);
    setMovementError(null);
    try {
      await createMovementMutation.mutateAsync(attempt);
      setMovementAttempt(null);
      element.reset();
    } catch (failure) {
      const response = isAxiosError<{ error_code?: string }>(failure)
        ? failure.response
        : undefined;
      const status = response?.status;
      const code = response?.data?.error_code;
      const rejected =
        Boolean(code) &&
        (status === 400 ||
          status === 404 ||
          status === 422 ||
          (status === 409 && code !== 'MOVEMENT_REPLAY_CONFLICT'));
      if (rejected) setMovementAttempt(null);
      setMovementError({
        form,
        detail:
          rejected || code === 'MOVEMENT_REPLAY_CONFLICT'
            ? formatApiError(failure, 'Unable to record stock movement.')
            : 'The stock movement result could not be confirmed. Retry this movement to check the result.'
      });
    } finally {
      movementInFlight.current = false;
    }
  }

  const cancelRequestMutation = useMutation({
    mutationFn: cancelMaterialRequest,
    onSuccess: refreshInventory
  });
  useEffect(() => {
    if (!focusedRequestId) return;
    const element = materialRequestRefs.current[focusedRequestId];
    element?.scrollIntoView({ behavior: 'smooth', block: 'center' });
  }, [focusedRequestId, materialRequests.data, focusedRequest.data]);

  useEffect(() => {
    const timer = window.setTimeout(() => {
      setCommittedSearch(itemSearch.trim());
      setItemOffset(0);
    }, 300);
    return () => window.clearTimeout(timer);
  }, [itemSearch]);

  return (
    <section className="space-y-6">
      <div className="flex flex-col justify-between gap-3 sm:flex-row sm:items-end">
        <div>
          <p className="text-sm font-medium text-brand-600">Materials</p>
          <h2 className="text-2xl font-semibold text-theme-text-primary">Inventory And Stores</h2>
        </div>
        <StatusBadge tone={lowStock.data && lowStock.data.length > 0 ? 'warning' : 'success'}>
          {`${lowStock.data?.length ?? 0} low stock`}
        </StatusBadge>
      </div>

      {canManageInventory ? (
        <div className="grid gap-4 lg:grid-cols-2">
          <form
            className="rounded-lg border border-theme-border bg-theme-card p-4"
            onSubmit={(event) => {
              event.preventDefault();
              const form = new FormData(event.currentTarget);
              createLocationMutation.mutate({
                name: String(form.get('name')),
                code: String(form.get('code')),
                location_type: String(form.get('location_type')),
                address: String(form.get('address') || '')
              });
              event.currentTarget.reset();
            }}
          >
            <h3 className="flex items-center gap-2 text-base font-semibold text-theme-text-primary">
              <Warehouse className="h-4 w-4" />
              Storage location
            </h3>
            <div className="mt-3 grid gap-3 sm:grid-cols-2">
              <input className="form-field" name="name" placeholder="Location name" required />
              <input className="form-field" name="code" placeholder="Code" required />
              <select className="form-field" name="location_type">
                <option value="warehouse">Warehouse</option>
                <option value="site_store">Site store</option>
                <option value="project_site">Project site</option>
              </select>
              <input className="form-field" name="address" placeholder="Address" />
            </div>
            <button className="mt-3 rounded-md bg-brand-600 px-4 py-2 text-sm font-semibold text-white hover:bg-brand-700">
              Add location
            </button>
          </form>

          <form
            className="rounded-lg border border-theme-border bg-theme-card p-4"
            onSubmit={(event) => {
              event.preventDefault();
              const form = new FormData(event.currentTarget);
              createItemMutation.mutate({
                name: String(form.get('name')),
                item_code: String(form.get('item_code') || ''),
                category: String(form.get('category')),
                item_type: String(form.get('item_type')),
                unit: String(form.get('unit')),
                minimum_stock: String(form.get('minimum_stock') || '0'),
                reorder_level: String(form.get('reorder_level') || '0'),
                unit_cost: String(form.get('unit_cost') || ''),
                supplier_id: String(form.get('supplier_id'))
              });
              event.currentTarget.reset();
            }}
          >
            <h3 className="flex items-center gap-2 text-base font-semibold text-theme-text-primary">
              <PackagePlus className="h-4 w-4" />
              Inventory item
            </h3>
            <div className="mt-3 grid gap-3 sm:grid-cols-2">
              <input className="form-field" name="name" placeholder="Item name" required />
              <input className="form-field" name="item_code" placeholder="Code" />
              <input className="form-field" name="category" placeholder="Category" required />
              <select className="form-field" name="item_type">
                <option value="consumable">Consumable</option>
                <option value="asset">Asset tagged</option>
              </select>
              <select className="form-field" name="unit">
                <option>Nos</option>
                <option>KG</option>
                <option>TON</option>
                <option>SQM</option>
                <option>bag</option>
                <option>m</option>
                <option>m2</option>
              </select>
              <input
                className="form-field"
                name="unit_cost"
                placeholder="Unit cost"
                type="number"
              />
              <input className="form-field" name="minimum_stock" placeholder="Minimum stock" />
              <input className="form-field" name="reorder_level" placeholder="Reorder level" />
              <select className="form-field sm:col-span-2" name="supplier_id" required>
                <option value="">Select supplier</option>
                {suppliers.data?.map((supplier) => (
                  <option key={supplier.id} value={supplier.id}>
                    {supplier.name}
                  </option>
                ))}
              </select>
            </div>
            <button className="mt-3 rounded-md bg-brand-600 px-4 py-2 text-sm font-semibold text-white hover:bg-brand-700">
              Add item
            </button>
          </form>
        </div>
      ) : null}

      <div className="grid gap-4 lg:grid-cols-[1.2fr_0.8fr]">
        <div className="rounded-lg border border-theme-border bg-theme-card">
          <div className="border-b border-theme-border px-4 py-3">
            <h3 className="text-base font-semibold text-theme-text-primary">Inventory items</h3>
            <input
              aria-label="Search inventory"
              className="form-field mt-2"
              onChange={(event) => setItemSearch(event.target.value)}
              placeholder="Search inventory"
              value={itemSearch}
            />
          </div>
          {visibleItems.data?.items.length ? (
            <div className="divide-y divide-theme-border">
              {visibleItems.data.items.map((item) => (
                <button
                  className="flex w-full items-center justify-between px-4 py-3 text-left hover:bg-theme-main"
                  key={item.id}
                  aria-pressed={item.id === selectedItem?.id}
                  disabled={movementAttempt?.form === 'receipt'}
                  onClick={() => {
                    setPickedItem(item);
                    setStockLocation('');
                  }}
                  type="button"
                >
                  <span>
                    <span className="block font-medium text-theme-text-primary">{item.name}</span>
                    <span className="text-sm text-theme-text-muted">
                      {item.item_code ?? 'No code'} - {item.category}
                    </span>
                  </span>
                  <StatusBadge tone="info">{item.item_type}</StatusBadge>
                </button>
              ))}
            </div>
          ) : (
            <EmptyState
              title={visibleItems.isPending ? 'Loading inventory' : 'No inventory items found'}
              description={visibleItems.isError ? 'Unable to load inventory items.' : ''}
            />
          )}
          <InventoryPager
            label="Inventory item pages"
            offset={itemOffset}
            setOffset={setItemOffset}
            size={inventoryPageSize}
            total={visibleItems.data?.total ?? 0}
            disabled={visibleItems.isPending || itemSearch.trim() !== committedSearch}
          />
          {selectedItem && (
            <div className="space-y-3 border-t border-theme-border p-4">
              <h4 className="font-semibold">
                Stock matrix · {selectedItem.name} ({selectedItem.unit})
              </h4>
              <label className="text-sm">
                Filter by location
                <select
                  className="form-field"
                  value={stockLocation}
                  onChange={(event) => setStockLocation(event.target.value)}
                >
                  <option value="">All locations</option>
                  {stock.data?.map((row) => (
                    <option key={row.id} value={row.location_id}>
                      {row.location_name}
                    </option>
                  ))}
                </select>
              </label>
              {stock.isPending && <p role="status">Loading stock balances…</p>}
              {stock.isError && (
                <p role="alert">
                  {stock.data
                    ? 'Unable to refresh stock balances. Showing the last loaded balances.'
                    : 'Unable to load stock balances.'}
                </p>
              )}
              {stock.isSuccess && balances.length === 0 && (
                <p>No recorded balances for this selection.</p>
              )}
              {balances.length > 0 && (
                <table className="w-full text-left text-sm">
                  <thead>
                    <tr>
                      <th scope="col">Location</th>
                      <th scope="col">On hand</th>
                      <th scope="col">Reserved</th>
                      <th scope="col">Available</th>
                    </tr>
                  </thead>
                  <tbody>
                    {balances.map((row) => (
                      <tr className="border-t border-theme-border" key={row.id}>
                        <th scope="row" className="py-2 font-medium">
                          {row.location_name}
                        </th>
                        <td>{row.on_hand_qty}</td>
                        <td>{row.reserved_qty}</td>
                        <td>
                          {row.available_qty}
                          {row.available_qty.startsWith('-') && (
                            <span role="alert"> · Reconciliation required</span>
                          )}
                        </td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              )}
            </div>
          )}
        </div>

        {canManageInventory ? (
          <div className="rounded-lg border border-theme-border bg-theme-card p-4">
            <h3 className="text-base font-semibold text-theme-text-primary">Quick receive</h3>
            <p className="mt-1 text-sm text-theme-text-secondary">
              {selectedItem ? `Receive ${selectedItem.name}` : 'Select an item to receive stock.'}
            </p>
            <form
              aria-label="Receive stock"
              className="mt-3 space-y-3"
              onSubmit={(event) => {
                event.preventDefault();
                if (!selectedItem) return;
                const form = new FormData(event.currentTarget);
                void submitMovement('receipt', event.currentTarget, {
                  item_id: selectedItem.id,
                  movement_type: 'receive',
                  to_location_id: String(form.get('location_id')),
                  quantity: String(form.get('quantity') || '0'),
                  notes: String(form.get('notes') || '')
                });
              }}
            >
              <fieldset className="min-w-0 space-y-3" disabled={movementAttempt !== null}>
                <LocationSelect
                  locations={locations.data?.filter((location) => location.is_active) ?? []}
                  name="location_id"
                  label="Receipt destination"
                  required
                />
                <input className="form-field" name="quantity" placeholder="Quantity" required />
                <input className="form-field" name="notes" placeholder="Notes" />
              </fieldset>
              {locations.isError && <p role="alert">Unable to load receipt destinations.</p>}
              {movementError?.form === 'receipt' && <p role="alert">{movementError.detail}</p>}
              <button
                disabled={
                  !selectedItem ||
                  createMovementMutation.isPending ||
                  movementAttempt?.form === 'movement' ||
                  (!movementAttempt && (locations.isPending || locations.isError))
                }
                className="w-full rounded-md bg-brand-600 px-4 py-2 text-sm font-semibold text-white hover:bg-brand-700 disabled:opacity-50"
              >
                {movementAttempt?.form === 'receipt'
                  ? createMovementMutation.isPending
                    ? 'Receiving…'
                    : 'Retry receipt'
                  : 'Receive stock'}
              </button>
            </form>
          </div>
        ) : null}
      </div>

      {canManageInventory ? (
        <div className="grid gap-4 lg:grid-cols-2">
          <form
            className="rounded-lg border border-theme-border bg-theme-card p-4"
            onSubmit={(event) => {
              event.preventDefault();
              const form = new FormData(event.currentTarget);
              createAssetMutation.mutate({
                item_id: String(form.get('item_id')),
                asset_tag: String(form.get('asset_tag')),
                current_location_id: String(form.get('current_location_id')),
                condition: String(form.get('condition') || 'good')
              });
              event.currentTarget.reset();
            }}
          >
            <h3 className="flex items-center gap-2 text-base font-semibold text-theme-text-primary">
              <MapPinned className="h-4 w-4" />
              Asset tracker
            </h3>
            <div className="mt-3 grid gap-3 sm:grid-cols-2">
              <select className="form-field" name="item_id" required>
                <option value="">Asset item</option>
                {items.data
                  ?.filter((item) => item.item_type === 'asset')
                  .map((item) => (
                    <option key={item.id} value={item.id}>
                      {item.name}
                    </option>
                  ))}
              </select>
              <input className="form-field" name="asset_tag" placeholder="Asset tag" required />
              <select className="form-field" name="current_location_id" required>
                <option value="">Current location</option>
                {locations.data?.map((location) => (
                  <option key={location.id} value={location.id}>
                    {location.name}
                  </option>
                ))}
              </select>
              <select className="form-field" name="condition">
                <option value="good">Good</option>
                <option value="calibration_due">Calibration due</option>
                <option value="repair">Repair</option>
                <option value="damaged">Damaged</option>
              </select>
            </div>
            <button className="mt-3 rounded-md bg-brand-600 px-4 py-2 text-sm font-semibold text-white hover:bg-brand-700">
              Add asset
            </button>
          </form>

          <form
            aria-label="Record stock movement"
            className="rounded-lg border border-theme-border bg-theme-card p-4"
            onSubmit={(event) => {
              event.preventDefault();
              const form = new FormData(event.currentTarget);
              void submitMovement('movement', event.currentTarget, {
                item_id: String(form.get('item_id')),
                asset_id: String(form.get('asset_id') || '') || undefined,
                movement_type: String(form.get('movement_type')),
                quantity: String(form.get('quantity') || '0'),
                from_location_id: String(form.get('from_location_id') || '') || undefined,
                to_location_id: String(form.get('to_location_id') || '') || undefined,
                project_id: String(form.get('project_id') || '') || undefined,
                notes: String(form.get('notes') || '')
              });
            }}
          >
            <h3 className="flex items-center gap-2 text-base font-semibold text-theme-text-primary">
              <ArrowRightLeft className="h-4 w-4" />
              Movement
            </h3>
            <fieldset
              className="mt-3 grid min-w-0 gap-3 sm:grid-cols-2"
              disabled={movementAttempt !== null}
            >
              <select aria-label="Movement type" className="form-field" name="movement_type">
                <option value="transfer">Transfer</option>
                <option value="issue">Issue</option>
                <option value="return">Return</option>
                <option value="consume">Consume</option>
                <option value="adjustment">Adjustment</option>
                <option value="wastage">Wastage</option>
                <option value="damaged">Damaged</option>
              </select>
              <select aria-label="Movement item" className="form-field" name="item_id" required>
                <option value="">Item</option>
                {items.data?.map((item) => (
                  <option key={item.id} value={item.id}>
                    {item.name}
                  </option>
                ))}
              </select>
              <select aria-label="Movement asset tag" className="form-field" name="asset_id">
                <option value="">No asset tag</option>
                {assets.data?.map((asset) => (
                  <option key={asset.id} value={asset.id}>
                    {asset.asset_tag}
                  </option>
                ))}
              </select>
              <input className="form-field" name="quantity" placeholder="Quantity" required />
              <LocationSelect
                locations={locations.data ?? []}
                name="from_location_id"
                label="From"
              />
              <LocationSelect locations={locations.data ?? []} name="to_location_id" label="To" />
              <select aria-label="Movement project" className="form-field" name="project_id">
                <option value="">No project</option>
                {projects.data?.items.map((project) => (
                  <option key={project.id} value={project.id}>
                    {project.code} - {project.name}
                  </option>
                ))}
              </select>
              <input className="form-field" name="notes" placeholder="Notes" />
            </fieldset>
            {movementError?.form === 'movement' && (
              <p className="mt-3" role="alert">
                {movementError.detail}
              </p>
            )}
            <button
              className="mt-3 rounded-md bg-brand-600 px-4 py-2 text-sm font-semibold text-white hover:bg-brand-700 disabled:opacity-50"
              disabled={createMovementMutation.isPending || movementAttempt?.form === 'receipt'}
            >
              {movementAttempt?.form === 'movement'
                ? createMovementMutation.isPending
                  ? 'Recording…'
                  : 'Retry movement'
                : 'Record movement'}
            </button>
          </form>
        </div>
      ) : null}

      <div className="grid gap-4 lg:grid-cols-[0.9fr_1.1fr]">
        {canCreateMaterialRequest && (
          <MaterialRequestForm
            items={items.data ?? []}
            locations={locations.data ?? []}
            onSuccess={refreshInventory}
          />
        )}

        <div className="rounded-lg border border-theme-border bg-theme-card">
          <div className="border-b border-theme-border px-4 py-3">
            <h3 className="text-base font-semibold text-theme-text-primary">Request lifecycle</h3>
          </div>
          {visibleRequests.length ? (
            <div className="divide-y divide-theme-border">
              {visibleRequests.map((request) => (
                <article
                  className={`px-4 py-3 text-sm ${
                    request.id === focusedRequestId ? 'bg-theme-main' : ''
                  }`}
                  key={request.id}
                  ref={(element) => {
                    materialRequestRefs.current[request.id] = element;
                  }}
                >
                  <div className="flex flex-wrap justify-between gap-2">
                    <p className="font-medium">
                      {request.request_number} · {request.lines.length} lines
                    </p>
                    <StatusBadge tone={request.status === 'issued' ? 'success' : 'warning'}>
                      {request.status}
                    </StatusBadge>
                  </div>
                  <MaterialFulfillment
                    request={request}
                    items={items.data ?? []}
                    canManage={canManageInventory && !cancelRequestMutation.isPending}
                    onSuccess={refreshInventory}
                  />
                  {(canManageInventory || request.requester_id === user?.id) &&
                    !['cancelled', 'issued'].includes(request.status) && (
                      <button
                        className="mt-2 text-sm text-[var(--status-error-text)] underline"
                        type="button"
                        disabled={cancelRequestMutation.isPending}
                        onClick={() => cancelRequestMutation.mutate(request.id)}
                      >
                        Cancel request
                      </button>
                    )}
                  {cancelRequestMutation.isError &&
                    cancelRequestMutation.variables === request.id && (
                      <p role="alert">
                        {formatApiError(
                          cancelRequestMutation.error,
                          'Unable to cancel the request.'
                        )}
                      </p>
                    )}
                </article>
              ))}
            </div>
          ) : (
            <EmptyState
              title="No material requests"
              description="Create a request to reserve and issue stock."
            />
          )}
          <InventoryPager
            label="Material request pages"
            offset={requestOffset}
            setOffset={setRequestOffset}
            size={inventoryPageSize}
            total={materialRequests.data?.total ?? 0}
            disabled={materialRequests.isPending}
          />
        </div>
      </div>

      <div className="grid gap-4 lg:grid-cols-2">
        <div className="rounded-lg border border-theme-border bg-theme-card">
          <div className="border-b border-theme-border px-4 py-3">
            <h3 className="text-base font-semibold text-theme-text-primary">
              Current tool locations
            </h3>
          </div>
          {assets.data?.length ? (
            <div className="divide-y divide-theme-border">
              {assets.data.map((asset) => (
                <div className="flex items-center justify-between px-4 py-3 text-sm" key={asset.id}>
                  <span>
                    <span className="block font-medium text-theme-text-primary">
                      {asset.asset_tag}
                    </span>
                    <span className="text-theme-text-muted">
                      {locationName(locations.data, asset.current_location_id)} · {asset.condition}
                    </span>
                  </span>
                  <StatusBadge tone={asset.status === 'available' ? 'success' : 'warning'}>
                    {asset.status}
                  </StatusBadge>
                </div>
              ))}
            </div>
          ) : (
            <EmptyState
              title="No assets tracked"
              description="Asset-tagged tools will appear here."
            />
          )}
        </div>

        <div className="rounded-lg border border-theme-border bg-theme-card">
          <div className="border-b border-theme-border px-4 py-3">
            <h3 className="text-base font-semibold text-theme-text-primary">Recent movements</h3>
          </div>
          {movements.data?.items.length ? (
            <div className="divide-y divide-theme-border">
              {movements.data.items.map((movement) => (
                <div
                  className="grid gap-2 px-4 py-3 text-sm sm:grid-cols-[1fr_auto]"
                  key={movement.id}
                >
                  <div>
                    <p className="font-medium text-theme-text-primary">
                      {itemName(items.data, movement.item_id)} · {movement.quantity}
                    </p>
                    <p className="text-theme-text-muted">
                      {movement.movement_type} from{' '}
                      {locationName(locations.data, movement.from_location_id)} to{' '}
                      {locationName(locations.data, movement.to_location_id)}
                    </p>
                  </div>
                  <StatusBadge tone="info">
                    {new Date(movement.created_at).toLocaleDateString()}
                  </StatusBadge>
                </div>
              ))}
            </div>
          ) : (
            <EmptyState title="No movements" description="Stock movements will appear here." />
          )}
          <InventoryPager
            label="Stock movement pages"
            offset={movementOffset}
            setOffset={setMovementOffset}
            size={movementPageSize}
            total={movements.data?.total ?? 0}
            disabled={movements.isPending}
          />
        </div>
      </div>
    </section>
  );
}

function InventoryPager({
  label,
  offset,
  setOffset,
  size,
  total,
  disabled
}: {
  label: string;
  offset: number;
  setOffset: (offset: number) => void;
  size: number;
  total: number;
  disabled: boolean;
}) {
  if (offset === 0 && total <= size) return null;
  return (
    <nav
      aria-label={label}
      className="flex items-center justify-end gap-3 border-t border-theme-border px-4 py-3"
    >
      <button
        className="form-field disabled:opacity-50"
        disabled={disabled || offset === 0}
        onClick={() => setOffset(offset - size)}
        type="button"
      >
        Previous
      </button>
      <span aria-live="polite" className="text-sm text-theme-text-secondary">
        Page {offset / size + 1}
      </span>
      <button
        className="form-field disabled:opacity-50"
        disabled={disabled || offset + size >= total}
        onClick={() => setOffset(offset + size)}
        type="button"
      >
        Next
      </button>
    </nav>
  );
}

function LocationSelect({
  label,
  locations,
  name,
  required
}: {
  label: string;
  locations: Array<{ id: string; name: string }>;
  name: string;
  required?: boolean;
}) {
  return (
    <select aria-label={label} className="form-field" name={name} required={required}>
      <option value="">{label} location</option>
      {locations.map((location) => (
        <option key={location.id} value={location.id}>
          {location.name}
        </option>
      ))}
    </select>
  );
}

function locationName(
  locations: Array<{ id: string; name: string }> | undefined,
  locationId: string | null
) {
  if (!locationId) return '-';
  return locations?.find((location) => location.id === locationId)?.name ?? locationId;
}

function itemName(items: Array<{ id: string; name: string }> | undefined, itemId: string) {
  return items?.find((item) => item.id === itemId)?.name ?? itemId;
}
