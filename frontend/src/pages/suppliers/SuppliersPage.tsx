import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';

import {
  createSupplier,
  getSupplierTdsDocumentUrl,
  listSuppliers,
  uploadSupplierTdsDocument
} from '../../api/inventory';
import { EmptyState } from '../../components/shared/EmptyState';
import { StatusBadge } from '../../components/shared/StatusBadge';

const complianceTones: Record<string, 'info' | 'success' | 'warning' | 'danger'> = {
  compliant: 'success',
  pending: 'warning',
  expired: 'danger',
  blocked: 'danger'
};

export function SuppliersPage() {
  const queryClient = useQueryClient();
  const suppliers = useQuery({ queryKey: ['suppliers'], queryFn: listSuppliers });
  const createSupplierMutation = useMutation({
    mutationFn: createSupplier,
    onSuccess: () => void queryClient.invalidateQueries({ queryKey: ['suppliers'] })
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

  const complianceSummary = summarizeCompliance(suppliers.data ?? []);

  return (
    <section className="space-y-6">
      <div className="flex flex-col justify-between gap-3 sm:flex-row sm:items-end">
        <div>
          <p className="text-sm font-medium text-brand-600">Vendor network</p>
          <h2 className="text-2xl font-semibold text-theme-text-primary">
            Suppliers And Compliance
          </h2>
          <p className="mt-1 max-w-2xl text-sm text-theme-text-secondary">
            Manage supplier records, track compliance status, and maintain TDS supporting
            documents from one place.
          </p>
        </div>
        <StatusBadge tone={complianceSummary.expired > 0 ? 'warning' : 'success'}>
          {`${suppliers.data?.length ?? 0} active suppliers`}
        </StatusBadge>
      </div>

      <div className="grid gap-4 sm:grid-cols-2 xl:grid-cols-4">
        <SummaryCard label="Compliant" tone="success" value={complianceSummary.compliant} />
        <SummaryCard label="Pending" tone="warning" value={complianceSummary.pending} />
        <SummaryCard label="Expired" tone="danger" value={complianceSummary.expired} />
        <SummaryCard label="Blocked" tone="danger" value={complianceSummary.blocked} />
      </div>

      <div className="grid gap-4 xl:grid-cols-[0.85fr_1.15fr]">
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
          <h3 className="text-base font-semibold text-theme-text-primary">New supplier</h3>
          <p className="mt-1 text-sm text-theme-text-secondary">
            Capture the vendor profile used by Materials and Finance.
          </p>
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

        <div className="rounded-lg border border-theme-border bg-theme-card">
          <div className="border-b border-theme-border px-4 py-3">
            <h3 className="text-base font-semibold text-theme-text-primary">Compliance register</h3>
            <p className="mt-1 text-sm text-theme-text-secondary">
              Track TDS evidence and highlight suppliers that need attention.
            </p>
          </div>
          {suppliers.data && suppliers.data.length > 0 ? (
            <div className="divide-y divide-theme-border">
              {suppliers.data.map((supplier) => {
                const isExpiring =
                  supplier.tds_expiry_date &&
                  new Date(supplier.tds_expiry_date).getTime() - Date.now() <
                    1000 * 60 * 60 * 24 * 30;

                return (
                  <article
                    className="grid gap-4 px-4 py-4 lg:grid-cols-[1fr_auto]"
                    key={supplier.id}
                  >
                    <div className="space-y-3">
                      <div className="flex flex-col gap-2 sm:flex-row sm:items-center sm:justify-between">
                        <div>
                          <p className="font-medium text-theme-text-primary">{supplier.name}</p>
                          <p className="text-sm text-theme-text-muted">
                            {supplier.category} · {supplier.contact_person} · {supplier.phone}
                          </p>
                        </div>
                        <StatusBadge tone={complianceTones[supplier.compliance_status] ?? 'info'}>
                          {supplier.compliance_status}
                        </StatusBadge>
                      </div>

                      <div className="grid gap-3 text-sm text-theme-text-secondary sm:grid-cols-2">
                        <div>
                          <p className="font-medium text-theme-text-primary">Commercial terms</p>
                          <p>{supplier.payment_terms}</p>
                          <p>{supplier.email}</p>
                        </div>
                        <div>
                          <p className="font-medium text-theme-text-primary">Tax and TDS</p>
                          <p>Tax registration: {supplier.tax_registration_number}</p>
                          <p
                            className={
                              isExpiring
                                ? 'text-[var(--status-warning-text)]'
                                : 'text-theme-text-secondary'
                            }
                          >
                            TDS {supplier.tds_certificate_number ?? '-'} expires{' '}
                            {supplier.tds_expiry_date ?? '-'}
                          </p>
                        </div>
                      </div>
                    </div>

                    <div className="flex flex-col gap-3 lg:min-w-48">
                      <input
                        accept=".pdf,image/png,image/jpeg"
                        className="text-xs text-theme-text-secondary"
                        onChange={(event) => {
                          const file = event.target.files?.[0];
                          if (file) {
                            supplierTdsMutation.mutate({ supplierId: supplier.id, file });
                          }
                        }}
                        type="file"
                      />
                      {supplier.tds_document_key ? (
                        <button
                          className="rounded-md border border-theme-border px-3 py-2 text-sm font-semibold text-brand-600 hover:bg-theme-main"
                          onClick={() => void openSupplierTdsDocument(supplier.id)}
                          type="button"
                        >
                          View TDS
                        </button>
                      ) : (
                        <p className="text-xs text-theme-text-muted">No TDS document uploaded yet.</p>
                      )}
                    </div>
                  </article>
                );
              })}
            </div>
          ) : (
            <div className="p-4">
              <EmptyState
                title="No suppliers configured"
                description="Create a supplier record to start linking inventory items and invoices."
              />
            </div>
          )}
        </div>
      </div>
    </section>
  );
}

function SummaryCard({
  label,
  tone,
  value
}: {
  label: string;
  tone: 'info' | 'success' | 'warning' | 'danger';
  value: number;
}) {
  return (
    <div className="rounded-lg border border-theme-border bg-theme-card p-4">
      <div className="flex items-center justify-between gap-3">
        <p className="text-sm font-medium text-theme-text-muted">{label}</p>
        <StatusBadge tone={tone}>{String(value)}</StatusBadge>
      </div>
    </div>
  );
}

function summarizeCompliance(
  suppliers: Array<{ compliance_status: string }>
): Record<'blocked' | 'compliant' | 'expired' | 'pending', number> {
  return suppliers.reduce(
    (summary, supplier) => {
      if (supplier.compliance_status in summary) {
        summary[supplier.compliance_status as keyof typeof summary] += 1;
      }
      return summary;
    },
    { blocked: 0, compliant: 0, expired: 0, pending: 0 }
  );
}
