import { useRef, useState, type FormEvent } from 'react';

import { formatApiError } from '../../api/errors';
import { createInvoice, updateInvoice, type InvoiceRecord } from '../../api/finance';
import { businessDate } from '../../businessDate';
import { FinancePicker } from './FinancePicker';

export function InvoiceForm({
  invoice,
  onSaved,
  onCancel
}: {
  invoice?: InvoiceRecord;
  onSaved: (saved: InvoiceRecord) => void;
  onCancel: () => void;
}) {
  const [draft, setDraft] = useState({
    invoice_number: invoice?.invoice_number ?? '',
    project_id: invoice?.project_id ?? '',
    supplier_id: invoice?.supplier_id ?? '',
    invoice_date: invoice?.invoice_date ?? businessDate(),
    due_date: invoice?.due_date ?? '',
    amount: invoice?.amount ?? '',
    tax_amount: invoice?.tax_amount ?? '0',
    notes: invoice?.notes ?? ''
  });
  const revision = useRef(invoice?.revision);
  const locked = useRef(false);
  const [pending, setPending] = useState(false);
  const [error, setError] = useState('');

  async function submit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (locked.current) return;
    locked.current = true;
    setPending(true);
    setError('');
    const { project_id, ...fields } = draft;
    const payload = {
      ...fields,
      invoice_number: fields.invoice_number.trim(),
      supplier_id: fields.supplier_id || null,
      amount: fields.amount.trim(),
      tax_amount: fields.tax_amount.trim() || '0',
      notes: fields.notes.trim() || null
    };
    try {
      const saved = invoice
        ? await updateInvoice(invoice.id, { ...payload, expected_revision: revision.current })
        : await createInvoice({ ...payload, project_id });
      onSaved(saved);
    } catch (failure) {
      setError(formatApiError(failure, 'Unable to save invoice.'));
    } finally {
      locked.current = false;
      setPending(false);
    }
  }

  return (
    <form
      className="space-y-3 rounded-md border border-theme-border bg-theme-card p-4"
      onSubmit={(event) => void submit(event)}
    >
      <h3 className="font-semibold">{invoice ? 'Correct rejected invoice' : 'New invoice'}</h3>
      {error && (
        <p className="alert-error rounded-md p-2 text-sm" role="alert">
          {error}
        </p>
      )}
      <fieldset disabled={pending} className="grid gap-3 sm:grid-cols-2 xl:grid-cols-3">
        <label className="block text-sm">
          Invoice number
          <input
            className="form-field mt-1 w-full"
            required
            minLength={2}
            maxLength={80}
            value={draft.invoice_number}
            onChange={(event) => setDraft({ ...draft, invoice_number: event.target.value })}
          />
        </label>
        {invoice ? (
          <p className="text-sm">Project {invoice.project_name || 'Unavailable'}</p>
        ) : (
          <FinancePicker
            kind="project"
            label="Invoice project"
            value={draft.project_id}
            required
            onChange={(id) => setDraft({ ...draft, project_id: id })}
          />
        )}
        <FinancePicker
          kind="supplier"
          label="Supplier"
          value={draft.supplier_id}
          selectedName={invoice?.supplier_name}
          onChange={(id) => setDraft({ ...draft, supplier_id: id })}
        />
        {(
          [
            ['invoice_date', 'Invoice date', 'date'],
            ['due_date', 'Due date', 'date'],
            ['amount', 'Amount', 'text'],
            ['tax_amount', 'Tax amount', 'text']
          ] as const
        ).map(([field, label, type]) => (
          <label className="block text-sm" key={field}>
            {label}
            <input
              className="form-field mt-1 w-full"
              required={field !== 'tax_amount'}
              type={type}
              inputMode={type === 'text' ? 'decimal' : undefined}
              value={draft[field]}
              onChange={(event) => setDraft({ ...draft, [field]: event.target.value })}
            />
          </label>
        ))}
        <label className="block text-sm sm:col-span-2">
          Notes
          <textarea
            className="form-field mt-1 w-full"
            value={draft.notes}
            onChange={(event) => setDraft({ ...draft, notes: event.target.value })}
          />
        </label>
        <div className="flex flex-wrap items-center gap-3 sm:col-span-2 xl:col-span-3">
          <button
            className="rounded-md bg-brand-600 px-3 py-2 font-medium text-white disabled:opacity-50"
            type="submit"
          >
            {pending ? 'Saving…' : invoice ? 'Save corrections' : 'Submit invoice'}
          </button>
          <button className="text-sm underline" type="button" onClick={onCancel}>
            Discard invoice edits
          </button>
        </div>
      </fieldset>
    </form>
  );
}
