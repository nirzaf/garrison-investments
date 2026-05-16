import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import { PackagePlus, Warehouse } from 'lucide-react';
import { useState } from 'react';

import {
  createInventoryItem,
  createLocation,
  createSupplier,
  listInventoryItems,
  listLocations,
  listLowStock,
  listSuppliers,
  receiveStock
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

  const selectedItem = items.data?.find((item) => item.id === selectedItemId) ?? items.data?.[0];
  const firstLocation = locations.data?.[0];

  return (
    <section className="space-y-6">
      <div className="flex flex-col justify-between gap-3 sm:flex-row sm:items-end">
        <div>
          <p className="text-sm font-medium text-brand-700">Materials</p>
          <h2 className="text-2xl font-semibold text-slate-950">Inventory And Stores</h2>
        </div>
        <StatusBadge tone={lowStock.data && lowStock.data.length > 0 ? 'warning' : 'success'}>
          {`${lowStock.data?.length ?? 0} low stock`}
        </StatusBadge>
      </div>

      <div className="grid gap-4 lg:grid-cols-3">
        <form
          className="rounded-lg border border-slate-200 bg-white p-4"
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
          <h3 className="text-base font-semibold text-slate-950">Supplier</h3>
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
          <button className="mt-3 rounded-md bg-brand-700 px-4 py-2 text-sm font-semibold text-white">
            Add supplier
          </button>
        </form>

        <form
          className="rounded-lg border border-slate-200 bg-white p-4"
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
          <h3 className="flex items-center gap-2 text-base font-semibold text-slate-950">
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
          <button className="mt-3 rounded-md bg-brand-700 px-4 py-2 text-sm font-semibold text-white">
            Add location
          </button>
        </form>

        <form
          className="rounded-lg border border-slate-200 bg-white p-4"
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
          <h3 className="flex items-center gap-2 text-base font-semibold text-slate-950">
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
          <button className="mt-3 rounded-md bg-brand-700 px-4 py-2 text-sm font-semibold text-white">
            Add item
          </button>
        </form>
      </div>

      <div className="grid gap-4 lg:grid-cols-[1.2fr_0.8fr]">
        <div className="rounded-lg border border-slate-200 bg-white">
          <div className="border-b border-slate-200 px-4 py-3">
            <h3 className="text-base font-semibold text-slate-950">Stock matrix</h3>
          </div>
          {items.data && items.data.length > 0 ? (
            <div className="divide-y divide-slate-100">
              {items.data.map((item) => (
                <button
                  className="flex w-full items-center justify-between px-4 py-3 text-left hover:bg-slate-50"
                  key={item.id}
                  onClick={() => setSelectedItemId(item.id)}
                  type="button"
                >
                  <span>
                    <span className="block font-medium text-slate-950">{item.name}</span>
                    <span className="text-sm text-slate-500">
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

        <div className="rounded-lg border border-slate-200 bg-white p-4">
          <h3 className="text-base font-semibold text-slate-950">Quick receive</h3>
          <p className="mt-1 text-sm text-slate-600">
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
            <button className="w-full rounded-md bg-brand-700 px-4 py-2 text-sm font-semibold text-white">
              Receive stock
            </button>
          </form>
        </div>
      </div>
    </section>
  );
}
