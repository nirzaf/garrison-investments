import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import { Receipt } from 'lucide-react';

import { createInvoice, createPayment, listInvoices } from '../../api/finance';
import { listProjects } from '../../api/projects';
import { listSuppliers } from '../../api/inventory';
import { EmptyState } from '../../components/shared/EmptyState';
import { StatusBadge } from '../../components/shared/StatusBadge';

export function FinancePage() {
  const queryClient = useQueryClient();
  const invoices = useQuery({ queryKey: ['invoices'], queryFn: listInvoices });
  const projects = useQuery({ queryKey: ['projects'], queryFn: () => listProjects({}) });
  const suppliers = useQuery({ queryKey: ['suppliers'], queryFn: listSuppliers });
  const createInvoiceMutation = useMutation({
    mutationFn: createInvoice,
    onSuccess: () => void queryClient.invalidateQueries({ queryKey: ['invoices'] })
  });
  const createPaymentMutation = useMutation({
    mutationFn: ({ invoiceId, amount }: { invoiceId: string; amount: string }) =>
      createPayment(invoiceId, {
        payment_date: new Date().toISOString().slice(0, 10),
        amount,
        method: 'bank_transfer'
      }),
    onSuccess: () => void queryClient.invalidateQueries({ queryKey: ['invoices'] })
  });

  return (
    <section className="space-y-6">
      <div>
        <p className="text-sm font-medium text-brand-700">Accounts</p>
        <h2 className="text-2xl font-semibold text-slate-950">Invoices And Payments</h2>
      </div>

      <form
        className="rounded-lg border border-slate-200 bg-white p-4"
        onSubmit={(event) => {
          event.preventDefault();
          const form = new FormData(event.currentTarget);
          createInvoiceMutation.mutate({
            invoice_number: String(form.get('invoice_number')),
            project_id: String(form.get('project_id')),
            supplier_id: String(form.get('supplier_id') || ''),
            invoice_date: String(form.get('invoice_date')),
            due_date: String(form.get('due_date')),
            amount: String(form.get('amount')),
            tax_amount: String(form.get('tax_amount') || '0'),
            notes: String(form.get('notes') || '')
          });
          event.currentTarget.reset();
        }}
      >
        <h3 className="flex items-center gap-2 text-base font-semibold text-slate-950">
          <Receipt className="h-4 w-4" />
          New invoice
        </h3>
        <div className="mt-3 grid gap-3 md:grid-cols-3">
          <input
            className="form-field"
            name="invoice_number"
            placeholder="Invoice number"
            required
          />
          <select className="form-field" name="project_id" required>
            <option value="">Project</option>
            {projects.data?.items.map((project) => (
              <option key={project.id} value={project.id}>
                {project.name}
              </option>
            ))}
          </select>
          <select className="form-field" name="supplier_id">
            <option value="">Supplier</option>
            {suppliers.data?.map((supplier) => (
              <option key={supplier.id} value={supplier.id}>
                {supplier.name}
              </option>
            ))}
          </select>
          <input className="form-field" name="invoice_date" required type="date" />
          <input className="form-field" name="due_date" required type="date" />
          <input className="form-field" name="amount" placeholder="Amount" required type="number" />
          <input className="form-field" name="tax_amount" placeholder="Tax" type="number" />
          <input className="form-field md:col-span-2" name="notes" placeholder="Notes" />
        </div>
        <button className="mt-3 rounded-md bg-brand-700 px-4 py-2 text-sm font-semibold text-white">
          Submit invoice
        </button>
      </form>

      {invoices.data && invoices.data.items.length > 0 ? (
        <div className="overflow-hidden rounded-lg border border-slate-200 bg-white">
          <table className="min-w-full divide-y divide-slate-200 text-sm">
            <thead className="bg-slate-50 text-left text-xs uppercase tracking-wide text-slate-500">
              <tr>
                <th className="px-4 py-3">Invoice</th>
                <th className="px-4 py-3">Amount</th>
                <th className="px-4 py-3">Status</th>
                <th className="px-4 py-3">Payment</th>
                <th className="px-4 py-3">Action</th>
              </tr>
            </thead>
            <tbody className="divide-y divide-slate-100">
              {invoices.data.items.map((invoice) => (
                <tr key={invoice.id}>
                  <td className="px-4 py-3 font-medium text-slate-950">{invoice.invoice_number}</td>
                  <td className="px-4 py-3 text-slate-700">{invoice.total_amount}</td>
                  <td className="px-4 py-3">
                    <StatusBadge tone="info">{invoice.status}</StatusBadge>
                  </td>
                  <td className="px-4 py-3">
                    <StatusBadge tone={invoice.payment_status === 'paid' ? 'success' : 'warning'}>
                      {invoice.payment_status}
                    </StatusBadge>
                  </td>
                  <td className="px-4 py-3">
                    <button
                      className="rounded-md border border-slate-300 px-3 py-2 text-xs font-semibold text-slate-700"
                      onClick={() =>
                        createPaymentMutation.mutate({
                          invoiceId: invoice.id,
                          amount: invoice.total_amount
                        })
                      }
                      type="button"
                    >
                      Record payment
                    </button>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      ) : (
        <EmptyState
          title="No invoices"
          description="Create an invoice to start finance tracking."
        />
      )}
    </section>
  );
}
