import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import { ArrowRightLeft, ClipboardList, MapPinned, PackagePlus, Warehouse } from 'lucide-react';
import { useState } from 'react';

import {
  cancelMaterialRequest,
  createAsset,
  createInventoryItem,
  createLocation,
  createMaterialRequest,
  createMovement,
  createSupplier,
  getSupplierTdsDocumentUrl,
  issueMaterialRequest,
  listAssets,
  listInventoryItems,
  listLocations,
  listLowStock,
  listMaterialRequests,
  listMovements,
  listSuppliers,
  receiveStock,
  reserveMaterialRequest,
  uploadSupplierTdsDocument
} from '../../api/inventory';
import { listProjects } from '../../api/projects';
import { EmptyState } from '../../components/shared/EmptyState';
import { StatusBadge } from '../../components/shared/StatusBadge';

export function InventoryPage() {
  const queryClient = useQueryClient();
  const [selectedItemId, setSelectedItemId] = useState<string | null>(null);
  const locations = useQuery({ queryKey: ['inventory-locations'], queryFn: listLocations });
  const suppliers = useQuery({ queryKey: ['suppliers'], queryFn: listSuppliers });
  const items = useQuery({ queryKey: ['inventory-items'], queryFn: () => listInventoryItems() });
  const lowStock = useQuery({ queryKey: ['inventory-low-stock'], queryFn: listLowStock });
  const assets = useQuery({ queryKey: ['inventory-assets'], queryFn: listAssets });
  const movements = useQuery({ queryKey: ['inventory-movements'], queryFn: () => listMovements() });
  const materialRequests = useQuery({
    queryKey: ['material-requests'],
    queryFn: listMaterialRequests
  });
  const projects = useQuery({
    queryKey: ['projects', 'active'],
    queryFn: () => listProjects({ status: 'active' })
  });

  const createLocationMutation = useMutation({
    mutationFn: createLocation,
    onSuccess: () => void queryClient.invalidateQueries({ queryKey: ['inventory-locations'] })
  });
  const createItemMutation = useMutation({
    mutationFn: createInventoryItem,
    onSuccess: () => void queryClient.invalidateQueries({ queryKey: ['inventory-items'] })
  });
  const createSupplierMutation = useMutation({
    mutationFn: createSupplier,
    onSuccess: () => void queryClient.invalidateQueries({ queryKey: ['suppliers'] })
  });
  const receiveMutation = useMutation({
    mutationFn: receiveStock,
    onSuccess: () => {
      void queryClient.invalidateQueries({ queryKey: ['inventory-items'] });
      void queryClient.invalidateQueries({ queryKey: ['inventory-low-stock'] });
      void queryClient.invalidateQueries({ queryKey: ['inventory-movements'] });
    }
  });
  const createAssetMutation = useMutation({
    mutationFn: createAsset,
    onSuccess: () => void queryClient.invalidateQueries({ queryKey: ['inventory-assets'] })
  });
  const createMovementMutation = useMutation({
    mutationFn: createMovement,
    onSuccess: () => {
      void queryClient.invalidateQueries({ queryKey: ['inventory-movements'] });
      void queryClient.invalidateQueries({ queryKey: ['inventory-low-stock'] });
      void queryClient.invalidateQueries({ queryKey: ['inventory-assets'] });
    }
  });
  const createRequestMutation = useMutation({
    mutationFn: createMaterialRequest,
    onSuccess: () => void queryClient.invalidateQueries({ queryKey: ['material-requests'] })
  });
  const reserveRequestMutation = useMutation({
    mutationFn: reserveMaterialRequest,
    onSuccess: () => void queryClient.invalidateQueries({ queryKey: ['material-requests'] })
  });
  const issueRequestMutation = useMutation({
    mutationFn: issueMaterialRequest,
    onSuccess: () => {
      void queryClient.invalidateQueries({ queryKey: ['material-requests'] });
      void queryClient.invalidateQueries({ queryKey: ['inventory-movements'] });
      void queryClient.invalidateQueries({ queryKey: ['inventory-low-stock'] });
    }
  });
  const cancelRequestMutation = useMutation({
    mutationFn: cancelMaterialRequest,
    onSuccess: () => void queryClient.invalidateQueries({ queryKey: ['material-requests'] })
  });
  const supplierTdsMutation = useMutation({
    mutationFn: ({ supplierId, file }: { supplierId: string; file: File }) =>
      uploadSupplierTdsDocument(supplierId, file),
    onSuccess: () => void queryClient.invalidateQueries({ queryKey: ['suppliers'] })
  });

  async function openSupplierTdsDocument(supplierId: string) {
    const { url } = await getSupplierTdsDocumentUrl(supplierId);
    window.open(url, '_blank', 'noopener,noreferrer');
  }

  const selectedItem = items.data?.find((item) => item.id === selectedItemId) ?? items.data?.[0];
  const firstLocation = locations.data?.[0];

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

      <div className="grid gap-4 lg:grid-cols-3">
        <form
          className="rounded-lg border border-theme-border bg-theme-card p-4"
          onSubmit={(event) => {
            event.preventDefault();
            const form = new FormData(event.currentTarget);
            createSupplierMutation.mutate({
              name: String(form.get('name')),
              category: String(form.get('category')),
              rating: String(form.get('rating')),
              payment_terms: String(form.get('payment_terms')),
              contact_person: String(form.get('contact_person')),
              phone: String(form.get('phone')),
              email: String(form.get('email')),
              address: String(form.get('address')),
              tax_registration_number: String(form.get('tax_registration_number')),
              tds_certificate_number: String(form.get('tds_certificate_number') || ''),
              compliance_status: String(form.get('compliance_status'))
            });
            event.currentTarget.reset();
          }}
        >
          <h3 className="text-base font-semibold text-theme-text-primary">Supplier</h3>
          <div className="mt-3 grid gap-3">
            <input className="form-field" name="name" placeholder="Supplier name" required />
            <input className="form-field" name="category" placeholder="Category" required />
            <input className="form-field" name="rating" placeholder="Rating" required />
            <input
              className="form-field"
              name="payment_terms"
              placeholder="Payment terms"
              required
            />
            <input
              className="form-field"
              name="contact_person"
              placeholder="Contact person"
              required
            />
            <input className="form-field" name="phone" placeholder="Phone" required />
            <input className="form-field" name="email" placeholder="Email" required type="email" />
            <input className="form-field" name="address" placeholder="Address" required />
            <input
              className="form-field"
              name="tax_registration_number"
              placeholder="Tax registration"
              required
            />
            <input
              className="form-field"
              name="tds_certificate_number"
              placeholder="TDS certificate"
            />
            <select className="form-field" name="compliance_status">
              <option value="compliant">Compliant</option>
              <option value="pending">Pending</option>
              <option value="expired">Expired</option>
              <option value="blocked">Blocked</option>
            </select>
          </div>
          <button className="mt-3 rounded-md bg-brand-600 px-4 py-2 text-sm font-semibold text-white hover:bg-brand-700">
            Add supplier
          </button>
        </form>

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
            </select>
            <input className="form-field" name="unit_cost" placeholder="Unit cost" type="number" />
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

      <div className="grid gap-4 lg:grid-cols-[1.2fr_0.8fr]">
        <div className="rounded-lg border border-theme-border bg-theme-card">
          <div className="border-b border-theme-border px-4 py-3">
            <h3 className="text-base font-semibold text-theme-text-primary">Stock matrix</h3>
          </div>
          {items.data && items.data.length > 0 ? (
            <div className="divide-y divide-theme-border">
              {items.data.map((item) => (
                <button
                  className="flex w-full items-center justify-between px-4 py-3 text-left hover:bg-theme-main"
                  key={item.id}
                  onClick={() => setSelectedItemId(item.id)}
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
            <EmptyState title="No inventory items" description="Create an item to start stock." />
          )}
        </div>

        <div className="rounded-lg border border-theme-border bg-theme-card p-4">
          <h3 className="text-base font-semibold text-theme-text-primary">Quick receive</h3>
          <p className="mt-1 text-sm text-theme-text-secondary">
            {selectedItem ? selectedItem.name : 'Select an item'} into{' '}
            {firstLocation ? firstLocation.name : 'a location'}.
          </p>
          <form
            className="mt-3 space-y-3"
            onSubmit={(event) => {
              event.preventDefault();
              const form = new FormData(event.currentTarget);
              if (!selectedItem || !firstLocation) return;
              receiveMutation.mutate({
                item_id: selectedItem.id,
                to_location_id: firstLocation.id,
                quantity: String(form.get('quantity') || '0'),
                notes: String(form.get('notes') || '')
              });
              event.currentTarget.reset();
            }}
          >
            <input className="form-field" name="quantity" placeholder="Quantity" required />
            <input className="form-field" name="notes" placeholder="Notes" />
            <button className="w-full rounded-md bg-brand-600 px-4 py-2 text-sm font-semibold text-white hover:bg-brand-700">
              Receive stock
            </button>
          </form>
        </div>
      </div>

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
          className="rounded-lg border border-theme-border bg-theme-card p-4"
          onSubmit={(event) => {
            event.preventDefault();
            const form = new FormData(event.currentTarget);
            createMovementMutation.mutate({
              item_id: String(form.get('item_id')),
              asset_id: String(form.get('asset_id') || '') || undefined,
              movement_type: String(form.get('movement_type')),
              quantity: String(form.get('quantity') || '0'),
              from_location_id: String(form.get('from_location_id') || '') || undefined,
              to_location_id: String(form.get('to_location_id') || '') || undefined,
              project_id: String(form.get('project_id') || '') || undefined,
              notes: String(form.get('notes') || '')
            });
            event.currentTarget.reset();
          }}
        >
          <h3 className="flex items-center gap-2 text-base font-semibold text-theme-text-primary">
            <ArrowRightLeft className="h-4 w-4" />
            Movement
          </h3>
          <div className="mt-3 grid gap-3 sm:grid-cols-2">
            <select className="form-field" name="movement_type">
              <option value="transfer">Transfer</option>
              <option value="issue">Issue</option>
              <option value="return">Return</option>
              <option value="consume">Consume</option>
              <option value="adjustment">Adjustment</option>
              <option value="wastage">Wastage</option>
              <option value="damaged">Damaged</option>
            </select>
            <select className="form-field" name="item_id" required>
              <option value="">Item</option>
              {items.data?.map((item) => (
                <option key={item.id} value={item.id}>
                  {item.name}
                </option>
              ))}
            </select>
            <select className="form-field" name="asset_id">
              <option value="">No asset tag</option>
              {assets.data?.map((asset) => (
                <option key={asset.id} value={asset.id}>
                  {asset.asset_tag}
                </option>
              ))}
            </select>
            <input className="form-field" name="quantity" placeholder="Quantity" required />
            <LocationSelect locations={locations.data ?? []} name="from_location_id" label="From" />
            <LocationSelect locations={locations.data ?? []} name="to_location_id" label="To" />
            <select className="form-field" name="project_id">
              <option value="">No project</option>
              {projects.data?.items.map((project) => (
                <option key={project.id} value={project.id}>
                  {project.code} - {project.name}
                </option>
              ))}
            </select>
            <input className="form-field" name="notes" placeholder="Notes" />
          </div>
          <button className="mt-3 rounded-md bg-brand-600 px-4 py-2 text-sm font-semibold text-white hover:bg-brand-700">
            Record movement
          </button>
        </form>
      </div>

      <div className="grid gap-4 lg:grid-cols-[0.9fr_1.1fr]">
        <form
          className="rounded-lg border border-theme-border bg-theme-card p-4"
          onSubmit={(event) => {
            event.preventDefault();
            const form = new FormData(event.currentTarget);
            createRequestMutation.mutate({
              project_id: String(form.get('project_id')),
              from_location_id: String(form.get('from_location_id')),
              notes: String(form.get('notes') || ''),
              lines: [
                {
                  item_id: String(form.get('item_id')),
                  quantity: String(form.get('quantity') || '0')
                }
              ]
            });
            event.currentTarget.reset();
          }}
        >
          <h3 className="flex items-center gap-2 text-base font-semibold text-theme-text-primary">
            <ClipboardList className="h-4 w-4" />
            Material request
          </h3>
          <div className="mt-3 grid gap-3">
            <select className="form-field" name="project_id" required>
              <option value="">Project</option>
              {projects.data?.items.map((project) => (
                <option key={project.id} value={project.id}>
                  {project.code} - {project.name}
                </option>
              ))}
            </select>
            <LocationSelect
              locations={locations.data ?? []}
              name="from_location_id"
              label="Source"
              required
            />
            <select className="form-field" name="item_id" required>
              <option value="">Item</option>
              {items.data?.map((item) => (
                <option key={item.id} value={item.id}>
                  {item.name}
                </option>
              ))}
            </select>
            <input className="form-field" name="quantity" placeholder="Quantity" required />
            <input className="form-field" name="notes" placeholder="Notes" />
          </div>
          <button className="mt-3 rounded-md bg-brand-600 px-4 py-2 text-sm font-semibold text-white hover:bg-brand-700">
            Create request
          </button>
        </form>

        <div className="rounded-lg border border-theme-border bg-theme-card">
          <div className="border-b border-theme-border px-4 py-3">
            <h3 className="text-base font-semibold text-theme-text-primary">Request lifecycle</h3>
          </div>
          {materialRequests.data?.length ? (
            <div className="divide-y divide-theme-border">
              {materialRequests.data.map((request) => (
                <article className="px-4 py-3 text-sm" key={request.id}>
                  <div className="flex flex-col justify-between gap-2 sm:flex-row sm:items-center">
                    <div>
                      <p className="font-medium text-theme-text-primary">
                        {request.request_number}
                      </p>
                      <p className="text-theme-text-muted">
                        {request.lines.length} line(s) · estimated {request.total_estimated_cost}
                      </p>
                    </div>
                    <StatusBadge tone={request.status === 'issued' ? 'success' : 'warning'}>
                      {request.status}
                    </StatusBadge>
                  </div>
                  <div className="mt-3 flex flex-wrap gap-2">
                    <button
                      className="rounded-md border border-theme-border px-3 py-1.5 text-xs font-semibold text-theme-text-secondary hover:bg-theme-main"
                      onClick={() => reserveRequestMutation.mutate(request.id)}
                      type="button"
                    >
                      Reserve
                    </button>
                    <button
                      className="rounded-md bg-brand-600 px-3 py-1.5 text-xs font-semibold text-white hover:bg-brand-700"
                      onClick={() => issueRequestMutation.mutate(request.id)}
                      type="button"
                    >
                      Issue
                    </button>
                    <button
                      className="rounded-md border border-theme-border px-3 py-1.5 text-xs font-semibold text-[var(--status-error-text)] hover:bg-theme-main"
                      onClick={() => cancelRequestMutation.mutate(request.id)}
                      type="button"
                    >
                      Cancel
                    </button>
                  </div>
                </article>
              ))}
            </div>
          ) : (
            <EmptyState
              title="No material requests"
              description="Create a request to reserve and issue stock."
            />
          )}
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
          {movements.data?.length ? (
            <div className="divide-y divide-theme-border">
              {movements.data.slice(0, 8).map((movement) => (
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
        </div>
      </div>

      {suppliers.data && suppliers.data.length > 0 ? (
        <div className="rounded-lg border border-theme-border bg-theme-card">
          <div className="border-b border-theme-border px-4 py-3">
            <h3 className="text-base font-semibold text-theme-text-primary">Supplier compliance</h3>
          </div>
          <div className="divide-y divide-theme-border">
            {suppliers.data.map((supplier) => {
              const isExpiring =
                supplier.tds_expiry_date &&
                new Date(supplier.tds_expiry_date).getTime() - Date.now() <
                  1000 * 60 * 60 * 24 * 30;
              return (
                <div
                  className="grid gap-3 px-4 py-3 text-sm md:grid-cols-[1fr_auto_auto]"
                  key={supplier.id}
                >
                  <div>
                    <p className="font-medium text-theme-text-primary">{supplier.name}</p>
                    <p
                      className={
                        isExpiring ? 'text-[var(--status-warning-text)]' : 'text-theme-text-muted'
                      }
                    >
                      TDS {supplier.tds_certificate_number ?? '-'} expires{' '}
                      {supplier.tds_expiry_date ?? '-'}
                    </p>
                  </div>
                  <input
                    accept=".pdf,image/png,image/jpeg"
                    className="text-xs"
                    onChange={(event) => {
                      const file = event.target.files?.[0];
                      if (file) supplierTdsMutation.mutate({ supplierId: supplier.id, file });
                    }}
                    type="file"
                  />
                  {supplier.tds_document_key ? (
                    <button
                      className="text-left text-xs font-semibold text-brand-600"
                      onClick={() => void openSupplierTdsDocument(supplier.id)}
                      type="button"
                    >
                      View TDS
                    </button>
                  ) : null}
                </div>
              );
            })}
          </div>
        </div>
      ) : null}
    </section>
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
    <select className="form-field" name={name} required={required}>
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
