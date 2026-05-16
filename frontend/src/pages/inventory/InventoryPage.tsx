import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import { PackagePlus, Warehouse } from 'lucide-react';
import { useState } from 'react';

import {
  createInventoryItem,
  createLocation,
  createSupplier,
  getSupplierTdsDocumentUrl,
  listInventoryItems,
  listLocations,
  listLowStock,
  listSuppliers,
  receiveStock,
  uploadSupplierTdsDocument
} from '../../api/inventory';
import { EmptyState } from '../../components/shared/EmptyState';
import { StatusBadge } from '../../components/shared/StatusBadge';

export function InventoryPage() {
  const queryClient = useQueryClient();
  const [selectedItemId, setSelectedItemId] = useState<string | null>(null);
  const locations = useQuery({ queryKey: ['inventory-locations'], queryFn: listLocations });
  const suppliers = useQuery({ queryKey: ['suppliers'], queryFn: listSuppliers });
  const items = useQuery({ queryKey: ['inventory-items'], queryFn: () => listInventoryItems() });
  const lowStock = useQuery({ queryKey: ['inventory-low-stock'], queryFn: listLowStock });

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
    }
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
                    <p className={isExpiring ? 'text-amber-700' : 'text-theme-text-muted'}>
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
