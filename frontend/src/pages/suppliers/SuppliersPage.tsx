import { keepPreviousData, useQuery, useQueryClient } from '@tanstack/react-query';
import { useRef, useState, type FormEvent } from 'react';

import { formatApiError } from '../../api/errors';
import {
  createSupplier,
  getSupplierTdsDocumentUrl,
  uploadSupplierTdsDocument,
  type SupplierCreatePayload,
  type SupplierRecord
} from '../../api/inventory';
import { deactivateSupplier, listSupplierRegister, updateSupplier } from '../../api/suppliers';
import { StatusBadge } from '../../components/shared/StatusBadge';
import { useDebouncedSearch } from '../../useDebouncedSearch';
import { supplierExpiry } from './supplierExpiry';

const pageSize = 25;
const complianceOptions = ['compliant', 'pending', 'expired', 'blocked'];
const tones = {
  compliant: 'success',
  pending: 'warning',
  expired: 'danger',
  blocked: 'danger'
} as const;
const buttonClass = 'rounded-md border border-theme-border px-3 py-2 text-sm disabled:opacity-50';
const submitClass =
  'rounded-md bg-brand-600 px-3 py-2 text-sm font-medium text-white disabled:opacity-50';
const fields = [
  ['name', 'Supplier name', 'text'],
  ['category', 'Category', 'text'],
  ['rating', 'Rating', 'text'],
  ['payment_terms', 'Payment terms', 'text'],
  ['contact_person', 'Contact person', 'text'],
  ['phone', 'Phone', 'tel'],
  ['email', 'Email', 'email'],
  ['address', 'Address', 'text'],
  ['tax_registration_number', 'Tax registration number', 'text'],
  ['tds_certificate_number', 'TDS certificate number', 'text'],
  ['tds_expiry_date', 'TDS expiry date', 'date']
] as const;

export function SuppliersPage() {
  const queryClient = useQueryClient();
  const [search, setSearch] = useState('');
  const [active, setActive] = useState('active');
  const [compliance, setCompliance] = useState('');
  const [page, setPage] = useState(0);
  const [editor, setEditor] = useState<SupplierRecord | 'new' | null>(null);
  const query = useDebouncedSearch(search);
  const suppliers = useQuery({
    queryKey: ['suppliers', 'register', query, active, compliance, page],
    queryFn: () =>
      listSupplierRegister({
        active: active ? active === 'active' : undefined,
        compliance_status: compliance || undefined,
        search: query || undefined,
        limit: pageSize,
        offset: page * pageSize
      }),
    placeholderData: keepPreviousData
  });

  function refresh() {
    void queryClient.invalidateQueries({ queryKey: ['suppliers'] });
    void queryClient.invalidateQueries({ queryKey: ['finance-supplier-options'] });
    void queryClient.invalidateQueries({ queryKey: ['invoices'] });
    void queryClient.invalidateQueries({ queryKey: ['invoice-detail'] });
  }

  return (
    <section className="space-y-4">
      <div className="flex flex-wrap items-center justify-between gap-2">
        <h2 className="text-2xl font-semibold">Suppliers And Compliance</h2>
        {!editor && (
          <button className={submitClass} type="button" onClick={() => setEditor('new')}>
            New supplier
          </button>
        )}
      </div>
      {editor && (
        <SupplierForm
          key={editor === 'new' ? 'new' : editor.id}
          supplier={editor === 'new' ? undefined : editor}
          onCancel={() => setEditor(null)}
          onSaved={() => {
            setEditor(null);
            refresh();
          }}
        />
      )}
      <div className="grid gap-3 rounded-md border border-theme-border bg-theme-card p-4 sm:grid-cols-3">
        <label className="block text-sm">
          Search suppliers
          <input
            type="search"
            maxLength={100}
            className="form-field mt-1 w-full"
            value={search}
            onChange={(event) => {
              setSearch(event.target.value);
              setPage(0);
            }}
          />
        </label>
        <div>
          <label className="block text-sm" htmlFor="supplier-active">
            Supplier state
          </label>
          <select
            id="supplier-active"
            className="form-field mt-1 w-full"
            value={active}
            onChange={(event) => {
              setActive(event.target.value);
              setPage(0);
            }}
          >
            <option value="active">Active</option>
            <option value="inactive">Inactive</option>
            <option value="">All states</option>
          </select>
        </div>
        <div>
          <label className="block text-sm" htmlFor="supplier-compliance">
            Compliance filter
          </label>
          <select
            id="supplier-compliance"
            className="form-field mt-1 w-full"
            value={compliance}
            onChange={(event) => {
              setCompliance(event.target.value);
              setPage(0);
            }}
          >
            <option value="">All compliance states</option>
            {complianceOptions.map((value) => (
              <option key={value} value={value}>
                {value}
              </option>
            ))}
          </select>
        </div>
      </div>
      {suppliers.isPending && <p role="status">Loading suppliers…</p>}
      {suppliers.isError && (
        <p role="alert">
          {formatApiError(suppliers.error, 'Unable to load suppliers.')}{' '}
          <button type="button" className="underline" onClick={() => void suppliers.refetch()}>
            Retry suppliers
          </button>
        </p>
      )}
      {suppliers.isFetching && suppliers.data && <p role="status">Refreshing suppliers…</p>}
      {suppliers.isError && suppliers.data && (
        <p className="text-sm">Showing the last loaded suppliers.</p>
      )}
      {suppliers.data && (
        <div className="rounded-md border border-theme-border bg-theme-card p-4">
          <div className="flex flex-wrap gap-3 text-sm">
            <p>{suppliers.data.total} matching suppliers</p>
            {suppliers.data.items.length > 0 && (
              <p>
                On this page{' '}
                {complianceOptions
                  .map(
                    (status) =>
                      `${suppliers.data.items.filter((item) => item.compliance_status === status).length} ${status}`
                  )
                  .join(' · ')}
              </p>
            )}
          </div>
          <div className="divide-y divide-theme-border">
            {suppliers.data.items.map((supplier) => (
              <SupplierCard
                key={supplier.id}
                supplier={supplier}
                refresh={refresh}
                canEdit={!editor}
                onEdit={setEditor}
              />
            ))}
          </div>
          {!suppliers.data.items.length && (
            <p className="py-3 text-sm">No suppliers match the selected filters.</p>
          )}
          <div className="mt-3 flex gap-2">
            <button
              type="button"
              className={buttonClass}
              disabled={!page || suppliers.isFetching}
              onClick={() => setPage(page - 1)}
            >
              Previous suppliers
            </button>
            <button
              type="button"
              className={buttonClass}
              disabled={(page + 1) * pageSize >= suppliers.data.total || suppliers.isFetching}
              onClick={() => setPage(page + 1)}
            >
              Next suppliers
            </button>
          </div>
        </div>
      )}
    </section>
  );
}

function SupplierForm({
  supplier,
  onSaved,
  onCancel
}: {
  supplier?: SupplierRecord;
  onSaved: () => void;
  onCancel: () => void;
}) {
  const [draft, setDraft] = useState({
    name: supplier?.name ?? '',
    category: supplier?.category ?? '',
    rating: supplier?.rating ?? '',
    payment_terms: supplier?.payment_terms ?? '',
    contact_person: supplier?.contact_person ?? '',
    phone: supplier?.phone ?? '',
    email: supplier?.email ?? '',
    address: supplier?.address ?? '',
    tax_registration_number: supplier?.tax_registration_number ?? '',
    tds_certificate_number: supplier?.tds_certificate_number ?? '',
    tds_expiry_date: supplier?.tds_expiry_date ?? '',
    compliance_status: supplier?.compliance_status ?? 'pending'
  });
  const [error, setError] = useState('');
  const [pending, setPending] = useState(false);
  const locked = useRef(false);

  async function submit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (locked.current) return;
    locked.current = true;
    setPending(true);
    setError('');
    const payload: SupplierCreatePayload = {
      ...draft,
      tds_certificate_number: draft.tds_certificate_number.trim() || null,
      tds_expiry_date: draft.tds_expiry_date || null
    };
    try {
      if (supplier)
        await updateSupplier(supplier.id, { ...payload, expected_revision: supplier.revision });
      else await createSupplier(payload);
      onSaved();
    } catch (failure) {
      setError(formatApiError(failure, 'Unable to save supplier.'));
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
      <h3 className="font-semibold">{supplier ? `Edit ${supplier.name}` : 'New supplier'}</h3>
      {error && (
        <p className="alert-error rounded-md p-2 text-sm" role="alert">
          {error}
        </p>
      )}
      <fieldset disabled={pending} className="grid gap-3 sm:grid-cols-2 xl:grid-cols-3">
        {fields.map(([field, label, type]) => (
          <label className="block text-sm" key={field}>
            {label}
            <input
              className="form-field mt-1 w-full"
              required={!field.startsWith('tds_')}
              type={type}
              value={draft[field]}
              onChange={(event) => setDraft({ ...draft, [field]: event.target.value })}
            />
          </label>
        ))}
        <div>
          <label className="block text-sm" htmlFor="supplier-form-compliance">
            Compliance status
          </label>
          <select
            id="supplier-form-compliance"
            className="form-field mt-1 w-full"
            value={draft.compliance_status}
            onChange={(event) => setDraft({ ...draft, compliance_status: event.target.value })}
          >
            {complianceOptions.map((value) => (
              <option key={value} value={value}>
                {value}
              </option>
            ))}
          </select>
        </div>
        <div className="flex flex-wrap items-center gap-3">
          <button type="submit" className={submitClass}>
            {pending ? 'Saving…' : supplier ? 'Save supplier' : 'Add supplier'}
          </button>
          <button type="button" className={buttonClass} onClick={onCancel}>
            Discard supplier edits
          </button>
        </div>
      </fieldset>
    </form>
  );
}

function SupplierCard({
  supplier: registerSupplier,
  canEdit,
  refresh,
  onEdit
}: {
  supplier: SupplierRecord;
  canEdit: boolean;
  refresh: () => void;
  onEdit: (supplier: SupplierRecord) => void;
}) {
  const [uploadedSupplier, setUploadedSupplier] = useState<SupplierRecord>();
  // Keep the committed revision while the register refresh catches up.
  const supplier =
    uploadedSupplier && uploadedSupplier.revision > registerSupplier.revision
      ? uploadedSupplier
      : registerSupplier;
  const [file, setFile] = useState<File>();
  const [link, setLink] = useState('');
  const [confirming, setConfirming] = useState(false);
  const [pending, setPending] = useState(false);
  const [error, setError] = useState('');
  const locked = useRef(false);
  const input = useRef<HTMLInputElement>(null);

  async function action(run: () => Promise<void>) {
    if (locked.current) return;
    locked.current = true;
    setPending(true);
    setError('');
    try {
      await run();
    } catch (failure) {
      setError(formatApiError(failure, 'Unable to complete supplier action.'));
    } finally {
      locked.current = false;
      setPending(false);
    }
  }

  return (
    <article className="space-y-2 py-4" aria-label={supplier.name}>
      <div className="flex flex-wrap items-center justify-between gap-2">
        <h3 className="font-semibold">{supplier.name}</h3>
        <div className="flex flex-wrap gap-2">
          <StatusBadge tone={tones[supplier.compliance_status as keyof typeof tones] ?? 'info'}>
            {supplier.compliance_status}
          </StatusBadge>
          <StatusBadge tone={supplier.is_active ? 'success' : 'info'}>
            {supplier.is_active ? 'Active' : 'Inactive'}
          </StatusBadge>
        </div>
      </div>
      <p className="text-sm text-theme-text-secondary">
        {supplier.category} · {supplier.contact_person} · {supplier.payment_terms}
      </p>
      <p className="text-sm">
        TDS expiry {supplier.tds_expiry_date || '—'} · {supplierExpiry(supplier.tds_days_remaining)}
      </p>
      {error && (
        <p role="alert" className="alert-error rounded-md p-2 text-sm">
          {error}
        </p>
      )}
      <fieldset disabled={pending || !canEdit} className="flex flex-wrap items-end gap-2">
        <button type="button" className={buttonClass} onClick={() => onEdit(supplier)}>
          Edit supplier
        </button>
        {supplier.is_active && (
          <button type="button" className={buttonClass} onClick={() => setConfirming(!confirming)}>
            Deactivate supplier
          </button>
        )}
        <label className="block text-sm">
          TDS document (30 MiB)
          <input
            ref={input}
            className="form-field mt-1 w-full"
            type="file"
            accept=".pdf,.jpg,.jpeg,.png"
            onChange={(event) => setFile(event.target.files?.[0])}
          />
        </label>
        <button
          type="button"
          className={buttonClass}
          disabled={!file}
          onClick={() => {
            if (!file) return;
            if (file.size > 30 * 1024 * 1024) {
              setError('TDS documents must be 30 MiB or smaller.');
              return;
            }
            void action(async () => {
              setUploadedSupplier(await uploadSupplierTdsDocument(supplier.id, file));
              setFile(undefined);
              setLink('');
              if (input.current) input.current.value = '';
              refresh();
            });
          }}
        >
          Upload TDS document
        </button>
        {supplier.tds_document_key && (
          <button
            type="button"
            className={buttonClass}
            onClick={() =>
              void action(async () => {
                setLink((await getSupplierTdsDocumentUrl(supplier.id)).url);
              })
            }
          >
            Get TDS link
          </button>
        )}
      </fieldset>
      {pending && (
        <p role="status" className="text-sm">
          Processing supplier action…
        </p>
      )}
      {link && (
        <a href={link} className="text-sm underline" target="_blank" rel="noopener noreferrer">
          Open TDS document
        </a>
      )}
      {confirming && supplier.is_active && (
        <div className="space-y-2 rounded-md border border-theme-border p-3">
          <p className="text-sm">
            Deactivate {supplier.name}? It will be unavailable for new selection. Existing records
            and TDS documents stay linked.
          </p>
          <button
            type="button"
            className={buttonClass}
            disabled={pending || !canEdit}
            onClick={() =>
              void action(async () => {
                await deactivateSupplier(supplier.id, supplier.revision);
                setConfirming(false);
                refresh();
              })
            }
          >
            Confirm deactivation
          </button>
          <button
            type="button"
            className="ml-2 text-sm underline"
            disabled={pending}
            onClick={() => setConfirming(false)}
          >
            Cancel deactivation
          </button>
        </div>
      )}
    </article>
  );
}
