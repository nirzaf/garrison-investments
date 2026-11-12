import { keepPreviousData, useQuery, useQueryClient } from '@tanstack/react-query';
import { isAxiosError } from 'axios';
import { useRef, useState, type FormEvent } from 'react';
import { useSearchParams } from 'react-router-dom';

import { formatApiError } from '../../api/errors';
import {
  createPayment,
  getBudgetSummary,
  getInvoice,
  getInvoiceAttachmentUrl,
  listInvoices,
  updateInvoice,
  uploadInvoiceAttachment,
  type InvoiceRecord,
  type PaymentCreatePayload
} from '../../api/finance';
import { businessDate } from '../../businessDate';
import { useAuth } from '../../context/useAuth';
import { FinancePicker } from './FinancePicker';
import { InvoiceForm } from './InvoiceForm';

const pageSize = 25;
const actionClass = 'rounded-md border border-theme-border px-3 py-2 text-sm disabled:opacity-50';
const submitClass =
  'rounded-md bg-brand-600 px-3 py-2 text-sm font-medium text-white disabled:opacity-50';
const paymentRejectedCodes = new Set([
  'VALIDATION_ERROR',
  'INVOICE_NOT_APPROVED',
  'INVOICE_ALREADY_PAID',
  'PAYMENT_EXCEEDS_BALANCE'
]);

export function FinancePage() {
  const { user } = useAuth();
  const [params, setParams] = useSearchParams();
  const invoiceId = params.get('invoiceId');
  const [projectId, setProjectId] = useState('');
  const [status, setStatus] = useState('');
  const [page, setPage] = useState(0);
  const [creating, setCreating] = useState(false);
  const queryClient = useQueryClient();
  const invoices = useQuery({
    queryKey: ['invoices', 'list', projectId, status, page],
    queryFn: () =>
      listInvoices({
        project_id: projectId || undefined,
        status: status || undefined,
        limit: pageSize,
        offset: page * pageSize
      }),
    placeholderData: keepPreviousData
  });
  const budget = useQuery({
    queryKey: ['finance', 'budget', projectId],
    queryFn: () => getBudgetSummary(projectId),
    enabled: Boolean(projectId)
  });
  const detail = useQuery({
    queryKey: ['invoice-detail', invoiceId],
    queryFn: () => getInvoice(invoiceId!),
    enabled: Boolean(invoiceId)
  });

  function focus(id?: string) {
    setParams((current) => {
      const next = new URLSearchParams(current);
      if (id) next.set('invoiceId', id);
      else next.delete('invoiceId');
      return next;
    });
  }

  function refresh(invoice: InvoiceRecord) {
    queryClient.setQueryData(['invoice-detail', invoice.id], invoice);
    void queryClient.invalidateQueries({ queryKey: ['invoices'] });
    void queryClient.invalidateQueries({ queryKey: ['approvals'] });
    void queryClient.invalidateQueries({ queryKey: ['finance', 'budget', invoice.project_id] });
    void queryClient.invalidateQueries({ queryKey: ['analytics'] });
  }

  return (
    <section className="space-y-4">
      <div className="flex flex-wrap items-center justify-between gap-3">
        <h2 className="text-2xl font-semibold text-theme-text-primary">Invoices and payments</h2>
        {!creating && (
          <button type="button" className={submitClass} onClick={() => setCreating(true)}>
            New invoice
          </button>
        )}
      </div>
      {creating && (
        <InvoiceForm
          onCancel={() => setCreating(false)}
          onSaved={(invoice) => {
            refresh(invoice);
            setCreating(false);
            focus(invoice.id);
          }}
        />
      )}
      <div className="rounded-lg border border-theme-border bg-theme-card p-4">
        <div className="grid gap-3 sm:grid-cols-2">
          <FinancePicker
            kind="project"
            label="Project filter"
            value={projectId}
            onChange={(id) => {
              setProjectId(id);
              setPage(0);
            }}
          />
          <div>
            <label className="block text-sm" htmlFor="invoice-status-filter">
              Invoice status filter
            </label>
            <select
              id="invoice-status-filter"
              className="form-field mt-1 w-full"
              value={status}
              onChange={(event) => {
                setStatus(event.target.value);
                setPage(0);
              }}
            >
              <option value="">All statuses</option>
              <option value="draft">Draft</option>
              <option value="submitted">Submitted</option>
              <option value="approved">Approved</option>
              <option value="rejected">Rejected</option>
            </select>
          </div>
        </div>
        {projectId && (
          <div className="mt-4 border-t border-theme-border pt-3">
            <h3 className="font-semibold">Project budget and billable invoices</h3>
            <p className="text-xs text-theme-text-secondary">
              Billable invoices exclude drafts and rejected invoices. Payments reflect recorded
              payments for the project.
            </p>
            {budget.isPending && <p role="status">Loading budget summary…</p>}
            {budget.isError && (
              <p role="alert">
                {formatApiError(budget.error, 'Unable to load project budget.')}{' '}
                <button type="button" className="underline" onClick={() => void budget.refetch()}>
                  Retry budget
                </button>
              </p>
            )}
            {budget.data && (
              <dl className="mt-2 grid grid-cols-2 gap-2 text-sm lg:grid-cols-4">
                {(
                  [
                    ['Project budget', budget.data.budget_amount],
                    ['Billable invoices', budget.data.invoiced_total],
                    ['Recorded payments', budget.data.paid_total],
                    ['Remaining budget', budget.data.remaining_budget]
                  ] as const
                ).map(([label, value]) => (
                  <div key={label}>
                    <dt>{label}</dt>
                    <dd className="font-semibold">{value}</dd>
                  </div>
                ))}
              </dl>
            )}
          </div>
        )}
      </div>
      {invoiceId && (
        <div
          className="rounded-lg border border-theme-border bg-theme-card p-4"
          aria-label="Invoice details"
          role="region"
        >
          <div className="flex flex-wrap items-center justify-between gap-2">
            <h3 className="font-semibold">{detail.data?.invoice_number ?? 'Invoice details'}</h3>
            <button type="button" className={actionClass} onClick={() => focus()}>
              Close invoice details
            </button>
          </div>
          {detail.isPending && <p role="status">Loading invoice…</p>}
          {detail.isFetching && detail.data && <p role="status">Refreshing invoice details…</p>}
          {detail.isError && (
            <p role="alert">
              {formatApiError(detail.error, 'Unable to open invoice.')}{' '}
              <button type="button" className="underline" onClick={() => void detail.refetch()}>
                Retry details
              </button>
            </p>
          )}
          {detail.isError && detail.data && (
            <p className="text-sm">Showing the last loaded invoice details.</p>
          )}
          {detail.data && (
            <InvoiceDetails
              key={`${user?.id}:${invoiceId}`}
              invoice={detail.data}
              refresh={refresh}
              reload={() => void detail.refetch()}
            />
          )}
        </div>
      )}
      <div className="rounded-lg border border-theme-border bg-theme-card p-4">
        {invoices.isPending && <p role="status">Loading invoices…</p>}
        {invoices.isError && (
          <p role="alert">
            {formatApiError(invoices.error, 'Unable to load invoices.')}{' '}
            <button type="button" className="underline" onClick={() => void invoices.refetch()}>
              Retry invoices
            </button>
          </p>
        )}
        {invoices.isFetching && invoices.data && <p role="status">Refreshing invoice list…</p>}
        {invoices.isError && invoices.data && (
          <p className="text-sm">Showing the last loaded invoices.</p>
        )}
        {invoices.data && (
          <>
            {invoices.data.items.length ? (
              <div className="overflow-x-auto">
                <table className="w-full text-left text-sm">
                  <caption className="mb-2 text-left font-semibold">Invoice register</caption>
                  <thead className="bg-theme-main">
                    <tr>
                      {['Invoice', 'Project', 'Supplier', 'Total', 'Outstanding', 'Status'].map(
                        (heading) => (
                          <th key={heading} scope="col" className="p-2">
                            {heading}
                          </th>
                        )
                      )}
                    </tr>
                  </thead>
                  <tbody className="divide-y divide-theme-border">
                    {invoices.data.items.map((invoice) => (
                      <tr key={invoice.id}>
                        <td className="p-2">
                          <button
                            type="button"
                            className="font-semibold text-brand-600 hover:underline"
                            onClick={() => focus(invoice.id)}
                          >
                            {invoice.invoice_number}
                          </button>
                        </td>
                        <td className="p-2">{invoice.project_name || '—'}</td>
                        <td className="p-2">{invoice.supplier_name || '—'}</td>
                        <td className="p-2">{invoice.total_amount}</td>
                        <td className="p-2">{invoice.outstanding_amount}</td>
                        <td className="p-2 capitalize">{invoice.status}</td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            ) : (
              <p>No invoices match the selected filters.</p>
            )}
            <div className="mt-3 flex flex-wrap items-center justify-between gap-2 text-sm">
              <span>{invoices.data.total} matching invoices</span>
              <div className="flex gap-2">
                <button
                  className={actionClass}
                  type="button"
                  disabled={!page || invoices.isFetching}
                  onClick={() => setPage(page - 1)}
                >
                  Previous invoices
                </button>
                <button
                  className={actionClass}
                  type="button"
                  disabled={(page + 1) * pageSize >= invoices.data.total || invoices.isFetching}
                  onClick={() => setPage(page + 1)}
                >
                  Next invoices
                </button>
              </div>
            </div>
          </>
        )}
      </div>
    </section>
  );
}

function InvoiceDetails({
  invoice,
  refresh,
  reload
}: {
  invoice: InvoiceRecord;
  refresh: (invoice: InvoiceRecord) => void;
  reload: () => void;
}) {
  const [editing, setEditing] = useState(false);
  const [pending, setPending] = useState(false);
  const [error, setError] = useState('');
  const [paymentAmount, setPaymentAmount] = useState<string | null>(null);
  const [paymentAttempt, setPaymentAttempt] = useState<{
    key: string;
    payload: PaymentCreatePayload;
  } | null>(null);
  const [attachment, setAttachment] = useState<File>();
  const [downloadUrl, setDownloadUrl] = useState('');
  const [rejecting, setRejecting] = useState(false);
  const [decisionNotes, setDecisionNotes] = useState('');
  const fileInput = useRef<HTMLInputElement>(null);
  const locked = useRef(false);
  const actions = invoice.allowed_actions ?? [];

  async function mutate(
    action: () => Promise<InvoiceRecord>,
    done?: () => void,
    describeFailure = (failure: unknown) =>
      formatApiError(failure, 'Unable to complete invoice action.')
  ) {
    if (locked.current) return;
    locked.current = true;
    setPending(true);
    setError('');
    try {
      refresh(await action());
      done?.();
    } catch (failure) {
      setError(describeFailure(failure));
    } finally {
      locked.current = false;
      setPending(false);
    }
  }

  function decide(status: 'approved' | 'rejected' | 'submitted') {
    void mutate(
      () =>
        updateInvoice(invoice.id, {
          status,
          expected_revision: invoice.revision,
          ...(status === 'rejected' && decisionNotes.trim() ? { notes: decisionNotes.trim() } : {})
        }),
      () => {
        setRejecting(false);
        setDecisionNotes('');
      }
    );
  }

  function pay(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (locked.current) return;
    const attempt = paymentAttempt ?? {
      key: crypto.randomUUID(),
      payload: {
        amount: paymentAmount ?? invoice.outstanding_amount,
        payment_date: businessDate(),
        method: 'bank_transfer'
      }
    };
    setPaymentAttempt(attempt);
    void mutate(
      () => createPayment(invoice.id, attempt.payload, attempt.key),
      () => {
        setPaymentAttempt(null);
        setPaymentAmount(null);
      },
      (failure) => {
        const code = isAxiosError<{ error_code?: string }>(failure)
          ? failure.response?.data?.error_code
          : undefined;
        if (code && paymentRejectedCodes.has(code)) {
          setPaymentAttempt(null);
          return formatApiError(failure, 'Unable to record payment.');
        }
        return 'The payment result could not be confirmed. Retry this payment to check the result.';
      }
    );
  }

  async function downloadAttachment() {
    if (locked.current) return;
    locked.current = true;
    setPending(true);
    setError('');
    try {
      const { url } = await getInvoiceAttachmentUrl(invoice.id);
      setDownloadUrl(url);
    } catch (failure) {
      setError(formatApiError(failure, 'Unable to open the attachment.'));
    } finally {
      locked.current = false;
      setPending(false);
    }
  }

  return (
    <div className="mt-3 space-y-3">
      <dl className="grid grid-cols-2 gap-2 text-sm sm:grid-cols-4">
        {(
          [
            ['Project', invoice.project_name],
            ['Supplier', invoice.supplier_name],
            ['Invoice date', invoice.invoice_date],
            ['Due date', invoice.due_date],
            ['Amount', invoice.amount],
            ['Tax', invoice.tax_amount],
            ['Total', invoice.total_amount],
            ['Paid', invoice.paid_total],
            ['Outstanding', invoice.outstanding_amount],
            ['Invoice status', invoice.status],
            ['Payment status', invoice.payment_status]
          ] as const
        ).map(([label, value]) => (
          <div key={label}>
            <dt>{label}</dt>
            <dd className="font-semibold">{value || '—'}</dd>
          </div>
        ))}
      </dl>
      {invoice.notes && <p className="text-sm">Notes {invoice.notes}</p>}
      {error && (
        <div className="alert-error rounded-md p-2 text-sm" role="alert">
          <p>{error}</p>
          <button className="underline" type="button" onClick={reload}>
            Refresh invoice
          </button>
        </div>
      )}
      {editing ? (
        <InvoiceForm
          invoice={invoice}
          onCancel={() => setEditing(false)}
          onSaved={(saved) => {
            refresh(saved);
            setEditing(false);
          }}
        />
      ) : (
        <fieldset disabled={pending} className="space-y-3">
          <div className="flex flex-wrap gap-2">
            {actions.includes('correct') && (
              <button className={actionClass} type="button" onClick={() => setEditing(true)}>
                Correct invoice
              </button>
            )}
            {actions.includes('resubmit') && (
              <button className={submitClass} type="button" onClick={() => decide('submitted')}>
                Resubmit invoice
              </button>
            )}
            {actions.includes('approve') && (
              <button className={submitClass} type="button" onClick={() => decide('approved')}>
                Approve invoice
              </button>
            )}
            {actions.includes('reject') && (
              <button
                className={actionClass}
                type="button"
                onClick={() => setRejecting(!rejecting)}
              >
                Reject invoice
              </button>
            )}
          </div>
          {rejecting && actions.includes('reject') && (
            <div className="space-y-2">
              <label className="block text-sm">
                Rejection notes
                <textarea
                  className="form-field mt-1 w-full"
                  value={decisionNotes}
                  onChange={(event) => setDecisionNotes(event.target.value)}
                />
              </label>
              <button type="button" className={actionClass} onClick={() => decide('rejected')}>
                Confirm rejection
              </button>
            </div>
          )}
          {(paymentAttempt || actions.includes('record_payment')) && (
            <form className="flex flex-wrap items-end gap-2" onSubmit={pay}>
              <label className="block text-sm">
                Payment amount
                <input
                  required
                  className="form-field mt-1 w-full"
                  inputMode="decimal"
                  readOnly={paymentAttempt !== null}
                  value={
                    paymentAttempt?.payload.amount ?? paymentAmount ?? invoice.outstanding_amount
                  }
                  onChange={(event) => setPaymentAmount(event.target.value)}
                />
              </label>
              <button type="submit" className={submitClass}>
                {paymentAttempt && !pending ? 'Retry payment' : 'Record payment'}
              </button>
            </form>
          )}
          <div className="flex flex-wrap items-end gap-2">
            <label className="block text-sm">
              Invoice attachment (10 MiB)
              <input
                ref={fileInput}
                className="form-field mt-1 w-full"
                type="file"
                accept=".pdf,.jpg,.jpeg,.png"
                onChange={(event) => setAttachment(event.target.files?.[0])}
              />
            </label>
            <button
              className={actionClass}
              type="button"
              disabled={!attachment}
              onClick={() => {
                if (!attachment) return;
                if (attachment.size > 10 * 1024 * 1024) {
                  setError('Invoice attachments must be 10 MiB or smaller.');
                  return;
                }
                void mutate(
                  () => uploadInvoiceAttachment(invoice.id, attachment),
                  () => {
                    setAttachment(undefined);
                    setDownloadUrl('');
                    if (fileInput.current) fileInput.current.value = '';
                  }
                );
              }}
            >
              Upload attachment
            </button>
            {invoice.attachment_key && (
              <button
                className={actionClass}
                type="button"
                onClick={() => void downloadAttachment()}
              >
                Get attachment link
              </button>
            )}
            {downloadUrl && (
              <a
                href={downloadUrl}
                target="_blank"
                rel="noopener noreferrer"
                className="text-sm underline"
              >
                Open attachment
              </a>
            )}
          </div>
        </fieldset>
      )}
      {pending && (
        <p role="status" className="text-sm">
          Processing invoice action…
        </p>
      )}
      <div className="overflow-x-auto">
        <table className="w-full text-left text-sm">
          <caption className="mb-1 text-left font-semibold">Payment history</caption>
          <thead className="bg-theme-main">
            <tr>
              {['Date', 'Amount', 'Method', 'Reference'].map((heading) => (
                <th className="p-2" scope="col" key={heading}>
                  {heading}
                </th>
              ))}
            </tr>
          </thead>
          <tbody className="divide-y divide-theme-border">
            {invoice.payments.map((payment) => (
              <tr key={payment.id}>
                <td className="p-2">{payment.payment_date}</td>
                <td className="p-2">{payment.amount}</td>
                <td className="p-2">{payment.method.replace(/_/g, ' ')}</td>
                <td className="p-2">{payment.reference_number || '—'}</td>
              </tr>
            ))}
          </tbody>
        </table>
        {!invoice.payments.length && <p className="text-sm">No recorded payments.</p>}
      </div>
    </div>
  );
}
