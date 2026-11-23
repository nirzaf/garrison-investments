import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import { useState } from 'react';
import { Link, useSearchParams } from 'react-router-dom';

import { formatApiError } from '../../api/errors';
import {
  createInventoryRegistration,
  decideInventoryRegistration,
  listInventoryRegistrationHistory,
  listInventoryRegistrations,
  listRequestProjects,
  submitInventoryRegistration,
  type InventoryItemRecord,
  type InventoryRegistration,
  type InventoryRegistrationDraft,
  type StorageLocationRecord
} from '../../api/inventory';
import { getPhotoDownloadUrl, listPhotos, prepareMediaFiles, uploadMediaFiles } from '../../api/photos';
import { useAuth } from '../../context/useAuth';
import { useDebouncedSearch } from '../../useDebouncedSearch';

const pageSize = 25;
const units = ['Nos', 'KG', 'TON', 'SQM', 'bag', 'm', 'm2'] as const;
const supervisorRoles = new Set(['site_supervisor', 'senior_site_supervisor']);
const readerRoles = new Set([
  'managing_director', 'operations_director', 'group_project_manager', 'mep_project_manager',
  'quantity_surveyor'
]);

type InventoryOptions = { items: InventoryItemRecord[]; locations: StorageLocationRecord[] };

export function InventoryRegistrationPanel({ items, locations, refreshStock }: InventoryOptions & {
  refreshStock: () => void;
}) {
  const { user } = useAuth();
  const [params] = useSearchParams();
  const focusedId = params.get('registrationId') ?? undefined;
  const [offset, setOffset] = useState(0);
  const [formOpen, setFormOpen] = useState(false);
  const [correction, setCorrection] = useState<InventoryRegistration>();
  const queryClient = useQueryClient();
  const supervisor = user != null && supervisorRoles.has(user.role);
  const canRead = supervisor || (user != null && readerRoles.has(user.role));
  const query = useQuery({
    queryKey: ['inventory-registrations', focusedId, offset],
    queryFn: () => listInventoryRegistrations({ registration_id: focusedId, offset, limit: pageSize }),
    enabled: canRead
  });

  function refresh() {
    void queryClient.invalidateQueries({ queryKey: ['inventory-registrations'] });
    void queryClient.invalidateQueries({ queryKey: ['inventory-registration-history'] });
    refreshStock();
  }

  if (!canRead) return null;
  return (
    <section className="space-y-4 rounded-lg border border-theme-border bg-theme-card p-4">
      <div className="flex flex-wrap items-center justify-between gap-2">
        <h3 className="font-semibold">Site inventory registrations</h3>
        {focusedId && <Link className="text-brand-600 underline" to="/materials">All registrations</Link>}
        {supervisor && !formOpen && (
          <button type="button" className="form-button" onClick={() => setFormOpen(true)}>
            Register received items
          </button>
        )}
      </div>
      {supervisor && formOpen && (
        <RegistrationForm
          key={correction?.id ?? 'new'}
          items={items}
          locations={locations}
          previous={correction}
          onClose={() => { setFormOpen(false); setCorrection(undefined); }}
          onSuccess={() => { setFormOpen(false); setCorrection(undefined); refresh(); }}
        />
      )}
      {query.isPending && <p role="status">Loading registrations…</p>}
      {query.isError && <p role="alert">{formatApiError(query.error, 'Unable to load registrations.')}</p>}
      {query.isSuccess && query.data.items.length === 0 && <p>No visible registrations.</p>}
      {query.data?.items.map((record) => (
        <RegistrationDetails
          key={record.id}
          record={record}
          isOwner={supervisor && record.created_by === user?.id}
          canReview={user?.role === 'mep_project_manager' && record.reviewer_id === user.id}
          onCorrection={() => { setCorrection(record); setFormOpen(true); }}
          refresh={refresh}
        />
      ))}
      {!focusedId && (query.data?.total ?? 0) > pageSize && (
        <div className="flex gap-3">
          <button type="button" className="form-button" disabled={offset === 0 || query.isFetching}
            onClick={() => setOffset(offset - pageSize)}>Previous registrations</button>
          <button type="button" className="form-button"
            disabled={offset + pageSize >= (query.data?.total ?? 0) || query.isFetching}
            onClick={() => setOffset(offset + pageSize)}>Next registrations</button>
        </div>
      )}
    </section>
  );
}

function RegistrationForm({ items, locations, previous, onClose, onSuccess }: InventoryOptions & {
  previous?: InventoryRegistration;
  onClose: () => void;
  onSuccess: () => void;
}) {
  const [search, setSearch] = useState('');
  const term = useDebouncedSearch(search);
  const [draft, setDraft] = useState<InventoryRegistrationDraft>(
    previous?.requirements ?? {
      project_id: '', location_id: '', name: '', description: '', category: 'material',
      unit: 'Nos', quantity: '', condition: 'new', received_date: ''
    }
  );
  const projects = useQuery({
    queryKey: ['inventory-request-projects', term],
    queryFn: () => listRequestProjects(term || undefined),
    enabled: !previous
  });
  const save = useMutation({
    mutationFn: () => createInventoryRegistration(draft, previous),
    onSuccess
  });

  return (
    <form onSubmit={(event) => { event.preventDefault(); if (!save.isPending) save.mutate(); }}>
      <fieldset className="grid gap-3 sm:grid-cols-2" disabled={save.isPending}>
        <legend className="mb-3 font-medium">{previous ? 'Correct registration' : 'New registration draft'}</legend>
        {!previous && <>
          <label>Search projects
            <input className="form-field" value={search} onChange={(event) => setSearch(event.target.value)} />
          </label>
          <label>Registration project
            <select required className="form-field" value={draft.project_id}
              onChange={(event) => setDraft({ ...draft, project_id: event.target.value, location_id: '' })}>
              <option value="">Choose an assigned project</option>
              {draft.project_id && !projects.data?.items.some((item) => item.id === draft.project_id) && (
                <option value={draft.project_id}>Previously selected project</option>
              )}
              {projects.data?.items.map((item) => <option key={item.id} value={item.id}>{item.name}</option>)}
            </select>
            {projects.isError && <span role="alert">Unable to load assigned projects.</span>}
          </label>
        </>}
        <label>Receipt location
          <select required className="form-field" value={draft.location_id}
            onChange={(event) => setDraft({ ...draft, location_id: event.target.value })}>
            <option value="">Choose a project location</option>
            {locations.filter((row) => row.is_active && row.project_id === draft.project_id)
              .map((row) => <option key={row.id} value={row.id}>{row.name}</option>)}
          </select>
        </label>
        <label>Item name
          <input required className="form-field" maxLength={180} value={draft.name}
            onChange={(event) => setDraft({ ...draft, name: event.target.value })} />
        </label>
        <label>Item description
          <textarea required className="form-field" maxLength={2000} value={draft.description}
            onChange={(event) => setDraft({ ...draft, description: event.target.value })} />
        </label>
        <label>Category
          <select className="form-field" value={draft.category}
            onChange={(event) => setDraft({
              ...draft, category: event.target.value as typeof draft.category, catalog_item_id: null,
              unit: 'Nos'
            })}>
            <option value="material">Material</option>
            <option value="tool">Tool</option>
            <option value="equipment">Equipment</option>
          </select>
        </label>
        <label>Unit
          <select className="form-field" value={draft.unit}
            onChange={(event) => setDraft({
              ...draft, unit: event.target.value as typeof draft.unit, catalog_item_id: null
            })}>
            {(draft.category === 'material' ? units : ['Nos']).map((unit) => (
              <option key={unit} value={unit}>{unit}</option>
            ))}
          </select>
        </label>
        <label>Received quantity
          <input className="form-field" type="number" required value={draft.quantity}
            min={draft.category === 'material' ? '0.001' : '1'}
            step={draft.category === 'material' ? '0.001' : '1'}
            max={draft.category === 'material' ? undefined : 100}
            onChange={(event) => setDraft({ ...draft, quantity: event.target.value })} />
        </label>
        <label>Condition
          <select className="form-field" value={draft.condition}
            onChange={(event) => setDraft({ ...draft, condition: event.target.value as typeof draft.condition })}>
            <option value="new">New</option><option value="used">Used</option>
          </select>
        </label>
        <label>Date received
          <input className="form-field" type="date" required value={draft.received_date}
            onChange={(event) => setDraft({ ...draft, received_date: event.target.value })} />
        </label>
        <label>Catalogue match
          <select className="form-field" value={draft.catalog_item_id ?? ''}
            onChange={(event) => setDraft({ ...draft, catalog_item_id: event.target.value || null })}>
            <option value="">Create catalogue item on approval</option>
            {items.filter((item) => item.is_active && item.unit === draft.unit &&
              item.item_type === (draft.category === 'material' ? 'consumable' : 'asset'))
              .map((item) => <option key={item.id} value={item.id}>{item.name}</option>)}
          </select>
        </label>
        {([
          ['source', 'Supplier or source', 160],
          ['brand', 'Brand', 100],
          ['model_number', 'Model number', 100],
          ['serial_number', 'Serial number', 80],
          ['remarks', 'Remarks', 2000]
        ] as const).map(([key, label, limit]) => (
          <label key={key}>{label}
            <input className="form-field" maxLength={limit} value={draft[key] ?? ''}
              onChange={(event) => setDraft({ ...draft, [key]: event.target.value || null })} />
          </label>
        ))}
        <p className="text-sm">Upload a photograph and any delivery documents after saving the draft.</p>
        <div className="flex gap-3">
          <button type="submit" className="form-button">{save.isPending ? 'Saving…' : 'Save registration draft'}</button>
          <button type="button" onClick={onClose}>Cancel</button>
        </div>
      </fieldset>
      {save.isError && <p role="alert">{formatApiError(save.error, 'Unable to save registration.')}</p>}
    </form>
  );
}

function RegistrationDetails({ record, isOwner, canReview, onCorrection, refresh }: {
  record: InventoryRegistration;
  isOwner: boolean;
  canReview: boolean;
  onCorrection: () => void;
  refresh: () => void;
}) {
  const [open, setOpen] = useState(false);
  const [comments, setComments] = useState('');
  const [fileError, setFileError] = useState('');
  const [filePending, setFilePending] = useState(false);
  const history = useQuery({
    queryKey: ['inventory-registration-history', record.id, record.status],
    queryFn: () => listInventoryRegistrationHistory(record.id),
    enabled: open
  });
  const files = useQuery({
    queryKey: ['inventory-registration-files', record.id],
    queryFn: () => listPhotos({ entityType: 'inventory_registration', entityId: record.id }),
    enabled: open
  });
  const submit = useMutation({ mutationFn: () => submitInventoryRegistration(record), onSuccess: refresh });
  const decide = useMutation({
    mutationFn: (decision: 'approved' | 'returned' | 'rejected') =>
      decideInventoryRegistration(record, decision, comments),
    onSuccess: refresh
  });

  async function upload(filesToUpload: FileList, kind: 'photo' | 'attachment') {
    if (filePending) return;
    setFilePending(true);
    setFileError('');
    try {
      const remaining = 5 - (files.data?.items.filter((item) => item.kind === 'photo').length ?? 0);
      const prepared = await prepareMediaFiles(filesToUpload, kind, remaining);
      const result = await uploadMediaFiles('inventory_registration', record.id, prepared.items);
      setFileError([...prepared.errors, ...result.errors].join(' '));
      await files.refetch();
    } catch (error) {
      setFileError(formatApiError(error, 'Unable to upload evidence.'));
    } finally {
      setFilePending(false);
    }
  }

  async function openEvidence(fileId: string) {
    try {
      const url = await getPhotoDownloadUrl(fileId);
      window.open(url, '_blank', 'noopener,noreferrer');
    } catch (error) {
      setFileError(formatApiError(error, 'Unable to open evidence.'));
    }
  }

  return (
    <details className="rounded-md border border-theme-border p-3" onToggle={(event) => setOpen(event.currentTarget.open)}>
      <summary className="cursor-pointer">
        {record.requirements.name} · {record.requirements.quantity} {record.requirements.unit} · {record.status.replace(/_/g, ' ')}
      </summary>
      <div className="mt-3 space-y-2">
        <p>{record.requirements.description}</p>
        <p>{record.requirements.category} · {record.requirements.condition} · Received {record.requirements.received_date}</p>
        <p>{[record.requirements.brand, record.requirements.model_number, record.requirements.serial_number,
          record.requirements.source, record.requirements.remarks].filter(Boolean).join(' · ')}</p>
        {history.data?.map((version) => (
          <p key={version.id}>Submission {version.submission_revision} · {version.status.replace(/_/g, ' ')}
            {version.decision_comments && ` · ${version.decision_comments}`}</p>
        ))}
        {history.isError && <p role="alert">Unable to load earlier submissions.</p>}
        {open && files.isPending && <p role="status">Loading evidence…</p>}
        {files.isError && <p role="alert">Unable to load evidence.</p>}
        {files.data?.items.map((file) => (
          <button key={file.id} type="button" className="block text-brand-600 underline"
            onClick={() => void openEvidence(file.id)}>{file.original_name}</button>
        ))}
        {fileError && <p role="alert">{fileError}</p>}
        {isOwner && record.status === 'draft' && (
          <div className="space-y-2">
            <label className="block">Item photographs
              <input type="file" accept="image/jpeg,image/png,image/heic,.heic" multiple
                disabled={filePending || submit.isPending}
                onChange={(event) => {
                  if (event.target.files?.length) void upload(event.target.files, 'photo');
                  event.target.value = '';
                }} />
            </label>
            <label className="block">Delivery documents
              <input type="file" accept=".pdf,image/jpeg,image/png" multiple
                disabled={filePending || submit.isPending}
                onChange={(event) => {
                  if (event.target.files?.length) void upload(event.target.files, 'attachment');
                  event.target.value = '';
                }} />
            </label>
            <button type="button" className="form-button"
              disabled={filePending || submit.isPending || !files.data?.items.some((file) => file.kind === 'photo')}
              onClick={() => submit.mutate()}>Submit registration</button>
          </div>
        )}
        {isOwner && ['returned', 'rejected'].includes(record.status) && (
          <button type="button" className="form-button" onClick={onCorrection}>Correct registration</button>
        )}
        {canReview && record.status === 'pending_engineer' && (
          <div className="space-y-2">
            <label className="block">Engineer decision comments
              <textarea className="form-field" maxLength={2000} value={comments}
                onChange={(event) => setComments(event.target.value)} />
            </label>
            <div className="flex flex-wrap gap-3">
              {([['approved', 'Confirm receipt'], ['returned', 'Return for correction'], ['rejected', 'Reject registration']] as const)
                .map(([decision, label]) => (
                  <button key={decision} type="button" className="form-button"
                    disabled={decide.isPending || (decision !== 'approved' && !comments.trim())}
                    onClick={() => decide.mutate(decision)}>{label}</button>
                ))}
            </div>
          </div>
        )}
        {(submit.isError || decide.isError) && (
          <p role="alert">{formatApiError(submit.error ?? decide.error, 'Unable to update registration.')}</p>
        )}
      </div>
    </details>
  );
}
