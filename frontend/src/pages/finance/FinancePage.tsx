import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import { Receipt } from 'lucide-react';
import { useEffect, useRef, useState } from 'react';
import { useSearchParams } from 'react-router-dom';

import { formatApiError } from '../../api/errors';
import {
  createInvoice,
  createPayment,
  getInvoiceAttachmentUrl,
  listInvoices,
  uploadInvoiceAttachment
} from '../../api/finance';
import { listProjects } from '../../api/projects';
import { listSuppliers } from '../../api/inventory';
import { businessDate } from '../../businessDate';
import { EmptyState } from '../../components/shared/EmptyState';
import { StatusBadge } from '../../components/shared/StatusBadge';

export function FinancePage() {
  const [searchParams] = useSearchParams();
  const focusedInvoiceId = searchParams.get('invoiceId');
  const queryClient = useQueryClient();
  const invoiceRefs = useRef<Record<string, HTMLTableRowElement | null>>({});
  const [paymentAmounts, setPaymentAmounts] = useState<Record<string, string>>({});
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
        payment_date: businessDate(),
        amount,
        method: 'bank_transfer'
      }),
    onSuccess: (_data, variables) => {
      // Drop the typed amount so the input re-defaults to the new outstanding balance.
      setPaymentAmounts((current) => {
        const next = { ...current };
        delete next[variables.invoiceId];
        return next;
      });
      void queryClient.invalidateQueries({ queryKey: ['invoices'] });
    }
  });
  const uploadAttachmentMutation = useMutation({
    mutationFn: ({ invoiceId, file }: { invoiceId: string; file: File }) =>
      uploadInvoiceAttachment(invoiceId, file),
    onSuccess: () => void queryClient.invalidateQueries({ queryKey: ['invoices'] })
  });

  async function openAttachment(invoiceId: string) {
    const { url } = await getInvoiceAttachmentUrl(invoiceId);
    window.open(url, '_blank', 'noopener,noreferrer');
  }

  useEffect(() => {
    if (!focusedInvoiceId) return;
    const element = invoiceRefs.current[focusedInvoiceId];
    element?.scrollIntoView({ behavior: 'smooth', block: 'center' });
  }, [focusedInvoiceId, invoices.data?.items]);

  return (
    <section className="space-y-6">
      <div>
        <p className="text-sm font-medium text-brand-600">Accounts</p>
        <h2 className="text-2xl font-semibold text-theme-text-primary">Invoices And Payments</h2>
      </div>

      <form
        className="rounded-lg border border-theme-border bg-theme-card p-4"
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
        <h3 className="flex items-center gap-2 text-base font-semibold text-theme-text-primary">
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
        <button className="mt-3 rounded-md bg-brand-600 px-4 py-2 text-sm font-semibold text-white hover:bg-brand-700">
          Submit invoice
        </button>
      </form>

      {invoices.data && invoices.data.items.length > 0 ? (
        <div className="overflow-hidden rounded-lg border border-theme-border bg-theme-card">
          <table className="min-w-full divide-y divide-theme-border text-sm">
            <thead className="bg-theme-main text-left text-xs uppercase tracking-wide text-theme-text-muted">
              <tr>
                <th className="px-4 py-3">Invoice</th>
                <th className="px-4 py-3">Amount</th>
                <th className="px-4 py-3">Status</th>
                <th className="px-4 py-3">Payment</th>
                <th className="px-4 py-3">Attachment</th>
                <th className="px-4 py-3">Action</th>
              </tr>
            </thead>
            <tbody className="divide-y divide-theme-border">
              {invoices.data.items.map((invoice) => {
                const paidTotal = invoice.payments.reduce(
                  (sum, payment) => sum + Number(payment.amount),
                  0
                );
                const outstanding = Math.max(0, Number(invoice.total_amount) - paidTotal);
                const amountValue = paymentAmounts[invoice.id] ?? outstanding.toFixed(2);
                const paymentBlocked =
                  invoice.status !== 'approved' || invoice.payment_status === 'paid';
                return (
                <tr
                  className={invoice.id === focusedInvoiceId ? 'bg-theme-main' : undefined}
                  key={invoice.id}
                  ref={(element) => {
                    invoiceRefs.current[invoice.id] = element;
                  }}
                >
                  <td className="px-4 py-3 font-medium text-theme-text-primary">
                    {invoice.invoice_number}
                  </td>
                  <td className="px-4 py-3 text-theme-text-secondary">{invoice.total_amount}</td>
                  <td className="px-4 py-3">
                    <StatusBadge tone="info">{invoice.status}</StatusBadge>
                  </td>
                  <td className="px-4 py-3">
                    <StatusBadge tone={invoice.payment_status === 'paid' ? 'success' : 'warning'}>
                      {invoice.payment_status}
                    </StatusBadge>
                    {invoice.payments.length > 0 ? (
                      <p className="mt-1 text-xs text-theme-text-muted">
                        {invoice.payments.length} payment{invoice.payments.length > 1 ? 's' : ''}
                      </p>
                    ) : null}
                  </td>
                  <td className="px-4 py-3">
                    <div className="flex flex-col gap-2">
                      <input
                        accept=".pdf,image/png,image/jpeg"
                        className="text-xs"
                        onChange={(event) => {
                          const file = event.target.files?.[0];
                          if (file)
                            uploadAttachmentMutation.mutate({ invoiceId: invoice.id, file });
                        }}
                        type="file"
                      />
                      {invoice.attachment_key ? (
                        <button
                          className="text-left text-xs font-semibold text-brand-600"
                          onClick={() => void openAttachment(invoice.id)}
                          type="button"
                        >
                          View attachment
                        </button>
                      ) : null}
                    </div>
                  </td>
                  <td className="px-4 py-3">
                    <div className="flex flex-col gap-2">
                      <input
                        aria-label={`Payment amount for ${invoice.invoice_number}`}
                        className="form-field text-xs"
                        disabled={paymentBlocked}
                        min="0"
                        onChange={(event) =>
                          setPaymentAmounts((current) => ({
                            ...current,
                            [invoice.id]: event.target.value
                          }))
                        }
                        step="0.01"
                        type="number"
                        value={amountValue}
                      />
                      <button
                        className="rounded-md border border-theme-border px-3 py-2 text-xs font-semibold text-theme-text-secondary disabled:cursor-not-allowed disabled:opacity-50"
                        disabled={
                          paymentBlocked ||
                          createPaymentMutation.isPending ||
                          amountValue.trim() === '' ||
                          Number(amountValue) <= 0
                        }
                        onClick={() =>
                          createPaymentMutation.mutate({
                            invoiceId: invoice.id,
                            amount: amountValue
                          })
                        }
                        type="button"
                      >
                        Record payment
                      </button>
                      {createPaymentMutation.isError &&
                      createPaymentMutation.variables?.invoiceId === invoice.id ? (
                        <p className="alert-error rounded px-2 py-1 text-xs" role="alert">
                          {formatApiError(
                            createPaymentMutation.error,
                            'Unable to record the payment.'
                          )}
                        </p>
                      ) : null}
                    </div>
                  </td>
                </tr>
                );
              })}
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
