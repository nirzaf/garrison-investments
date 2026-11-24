import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import { isAxiosError } from 'axios';
import { useRef, useState } from 'react';

import { getDocumentVersionDownloadUrl, listDocuments } from '../../api/documents';
import { formatApiError } from '../../api/errors';
import {
  createMaterialRequest,
  createMaterialRequestDraft,
  fulfillMaterialRequest,
  listItemStock,
  listRequestProjects,
  materialSubmissionHistory,
  replaceMaterialRequest,
  resubmitMaterialRequest,
  type InventoryItemRecord,
  type MaterialQuantityCommand,
  type MaterialRequestCreatePayload,
  type MaterialRequestRecord,
  type RequestProjectOption,
  type StorageLocationRecord
} from '../../api/inventory';
import { deletePhoto, getPhotoDownloadUrl, listPhotos, uploadEntityFiles } from '../../api/photos';
import { useAuth } from '../../context/useAuth';
import { useDebouncedSearch } from '../../useDebouncedSearch';

function stockMilliquantity(value: string) {
  const [whole, fraction = ''] = value.split('.');
  return BigInt(whole) * 1000n + BigInt(fraction.padEnd(3, '0'));
}

function unissuedQuantity(quantity: string, issued: string) {
  const remainder = stockMilliquantity(quantity) - stockMilliquantity(issued);
  return `${remainder / 1000n}.${String(remainder % 1000n).padStart(3, '0')}`;
}

const newLine = () => ({ key: crypto.randomUUID(), item_id: '', quantity: '' });

type MaterialCorrection = {
  request: MaterialRequestRecord;
  snapshot?: MaterialRequestCreatePayload;
  replaceRemainder?: boolean;
};

export function MaterialRequestForm({
  items,
  locations,
  correction,
  onSuccess
}: {
  items: InventoryItemRecord[];
  locations: StorageLocationRecord[];
  correction?: MaterialCorrection;
  onSuccess: () => void;
}) {
  const snapshot = correction?.snapshot;
  const { user } = useAuth();
  const queryClient = useQueryClient();
  const [draft, setDraft] = useState<MaterialRequestRecord | undefined>(
    correction?.request.status === 'draft' ? correction.request : undefined
  );
  const supervisor = user?.role === 'site_supervisor' || user?.role === 'senior_site_supervisor';
  const [search, setSearch] = useState('');
  const [project, setProject] = useState<RequestProjectOption>();
  const projectId = correction?.request.project_id ?? project?.id;
  const [locationId, setLocationId] = useState(correction?.request.from_location_id ?? '');
  const [reason, setReason] = useState('');
  const [notes, setNotes] = useState(snapshot?.notes ?? correction?.request.notes ?? '');
  const [requirements, setRequirements] = useState<MaterialRequestCreatePayload['requirements']>(
    snapshot?.requirements ?? { required_date: '', urgency: 'routine', purpose: '', specification: '' }
  );
  const [evidence, setEvidence] = useState<Record<string, string>>(() =>
    Object.fromEntries((snapshot?.requirements.supporting_document_ids ?? [])
      .map((id, index) => [id, `Previously selected document ${index + 1}`]))
  );
  const [documentSearch, setDocumentSearch] = useState('');
  const [documentOffset, setDocumentOffset] = useState(0);
  const documentTerm = useDebouncedSearch(documentSearch);
  const documents = useQuery({
    queryKey: ['material-evidence-documents', projectId, documentTerm, documentOffset],
    queryFn: ({ signal }) => listDocuments({
      project_id: projectId,
      search: documentTerm || undefined,
      limit: 20,
      offset: documentOffset
    }, signal),
    enabled: Boolean(projectId)
  });
  const [lines, setLines] = useState(() =>
    correction?.request.lines.length ? correction.request.lines.filter((line) => !correction.replaceRemainder || stockMilliquantity(line.issued_quantity) < stockMilliquantity(line.quantity)).map((line) => ({
      key: line.id, item_id: line.item_id, quantity: String(correction.replaceRemainder ? unissuedQuantity(line.quantity, line.issued_quantity) : line.quantity)
    })) : [newLine()]
  );
  const [error, setError] = useState<string | null>(null);
  const pending = useRef(false);
  const term = useDebouncedSearch(search);
  const projects = useQuery({
    queryKey: ['inventory-request-projects', term],
    queryFn: () => listRequestProjects(term || undefined),
    enabled: !correction
  });
  const attached = useQuery({
    queryKey: ['material-request-files', draft?.id],
    queryFn: () => listPhotos({ entityType: 'material_request', entityId: draft?.id }),
    enabled: Boolean(draft)
  });
  const media = useMutation({
    mutationFn: async (action: { files: File[] } | { remove: string }) => {
      if ('remove' in action) {
        await deletePhoto(action.remove);
        return;
      }
      const owner = draft ?? await createMaterialRequestDraft(projectId!);
      setDraft(owner);
      try {
        for (const file of action.files) {
          await uploadEntityFiles({
            entityType: 'material_request', entityId: owner.id, files: [file],
            kind: file.type === 'application/pdf' ? 'attachment' : 'photo',
            idempotencyKey: crypto.randomUUID()
          });
        }
      } finally {
        await queryClient.invalidateQueries({ queryKey: ['material-request-files', owner.id] });
      }
    },
    onSettled: (_result, _error, action) => {
      if ('remove' in action && draft) void attached.refetch();
    }
  });
  const create = useMutation({
    mutationFn: (payload: MaterialRequestCreatePayload) => {
      const existing = draft ?? correction?.request;
      if (existing && correction?.replaceRemainder) {
        return replaceMaterialRequest(existing.id, { ...payload, expected_revision: existing.revision, reason });
      }
      return existing
        ? resubmitMaterialRequest(existing.id, { ...payload, expected_revision: existing.revision, reason: reason || undefined })
        : createMaterialRequest(payload);
    }
  });
  const options = projects.data?.items ?? [];

  return (
    <form
      className="space-y-3 rounded-lg border border-theme-border bg-theme-card p-4"
      onSubmit={async (event) => {
        event.preventDefault();
        if (!projectId || !locationId || pending.current || media.isPending) return;
        if (new Set(lines.map((line) => line.item_id)).size !== lines.length) {
          setError('Select each inventory item once.');
          return;
        }
        pending.current = true;
        setError(null);
        try {
          await create.mutateAsync({
            project_id: projectId,
            from_location_id: locationId,
            notes,
            requirements: {
              ...requirements,
              supporting_document_ids: Object.keys(evidence)
            },
            lines: lines.map(({ item_id, quantity }) => ({ item_id, quantity }))
          });
          setEvidence({});
          setDraft(undefined);
          setNotes('');
          setLines([newLine()]);
          onSuccess();
        } catch (cause) {
          setError(formatApiError(cause, 'Unable to create the material request.'));
        } finally {
          pending.current = false;
        }
      }}
    >
      <h3 className="font-semibold">
        {correction ? 'Correct material request' : 'Material request'}
      </h3>
      {!correction && <>
      <label className="block text-sm">
        Search eligible projects
        <input
          className="form-field"
          value={search}
          onChange={(event) => setSearch(event.target.value)}
        />
      </label>
      <label className="block text-sm">
        Request project
        <select
          className="form-field"
          required
          disabled={Boolean(draft) || media.isPending}
          value={project?.id ?? ''}
          onChange={(event) => {
            setEvidence({}); setDocumentOffset(0); setProject(options.find((option) => option.id === event.target.value));
            setLocationId('');
          }}
        >
          <option value="">Select a project</option>
          {project && !options.some((item) => item.id === project.id) && (
            <option value={project.id}>{project.name}</option>
          )}
          {options.map((option) => (
            <option key={option.id} value={option.id}>
              {option.code} · {option.name}
            </option>
          ))}
        </select>
      </label>
      {projects.isPending && <p role="status">Loading eligible projects…</p>}
      {projects.isError && (
        <p role="alert">{formatApiError(projects.error, 'Unable to load eligible projects.')}</p>
      )}
      {projects.data?.total === 0 && <p>No eligible projects match your search.</p>}
      </>}
      <label className="block text-sm">
        Source location
        <select
          className="form-field"
          required
          value={locationId}
          onChange={(event) => setLocationId(event.target.value)}
        >
          <option value="">Select a location</option>
          {locations
            .filter(
              (location) =>
                location.is_active && (!location.project_id || location.project_id === projectId)
            )
            .map((location) => (
              <option key={location.id} value={location.id}>
                {location.name}
              </option>
            ))}
        </select>
      </label>
      {lines.map((line, index) => (
        <div className="grid gap-2 sm:grid-cols-[2fr_1fr_auto]" key={line.key}>
          <label className="text-sm">
            Item {index + 1}
            <select
              aria-label={`Item ${index + 1}`}
              className="form-field"
              required
              value={line.item_id}
              onChange={(event) =>
                setLines((current) =>
                  current.map((entry) =>
                    entry.key === line.key ? { ...entry, item_id: event.target.value } : entry
                  )
                )
              }
            >
              <option value="">Select an item</option>
              {items
                .filter((item) => item.is_active)
                .map((item) => (
                  <option key={item.id} value={item.id}>
                    {item.name} · {item.unit}
                  </option>
                ))}
            </select>
          </label>
          <label className="text-sm">
            Quantity {index + 1}
            <input
              className="form-field"
              required
              type="number"
              min="0.001"
              step="0.001"
              value={line.quantity}
              onChange={(event) =>
                setLines((current) =>
                  current.map((entry) =>
                    entry.key === line.key ? { ...entry, quantity: event.target.value } : entry
                  )
                )
              }
            />
          </label>
          <button
            type="button"
            aria-label={`Remove line ${index + 1}`}
            disabled={lines.length === 1 || create.isPending}
            onClick={() => setLines((current) => current.filter((entry) => entry.key !== line.key))}
          >
            Remove
          </button>
        </div>
      ))}
      <button
        className="text-brand-600 underline"
        type="button"
        disabled={lines.length >= 100 || create.isPending}
        onClick={() => setLines((current) => [...current, newLine()])}
      >
        Add line
      </button>
      <label className="block text-sm">
        Notes
        <input
          className="form-field"
          value={notes}
          onChange={(event) => setNotes(event.target.value)}
        />
      </label>
      <div className="grid gap-3 sm:grid-cols-2">
        <label className="text-sm">
          Required delivery date
          <input className="form-field" type="date" required value={requirements.required_date}
            onChange={(event) => setRequirements({ ...requirements, required_date: event.target.value })} />
        </label>
        <label className="text-sm">
          Urgency
          <select className="form-field" value={requirements.urgency}
            onChange={(event) => setRequirements({
              ...requirements, urgency: event.target.value as typeof requirements.urgency
            })}>
            <option value="routine">Routine</option>
            <option value="urgent">Urgent</option>
            <option value="critical">Critical</option>
          </select>
        </label>
      </div>
      <label className="block text-sm">
        Purpose and work scope
        <textarea className="form-field" required maxLength={2000} value={requirements.purpose}
          onChange={(event) => setRequirements({ ...requirements, purpose: event.target.value })} />
      </label>
      <label className="block text-sm">
        Material description and specification
        <textarea className="form-field" required maxLength={2000} value={requirements.specification}
          onChange={(event) => setRequirements({ ...requirements, specification: event.target.value })} />
      </label>
      <label className="block text-sm">
        Known stock availability (optional)
        <input className="form-field" maxLength={1000} value={requirements.stock_availability ?? ''}
          onChange={(event) => setRequirements({ ...requirements, stock_availability: event.target.value })} />
      </label>
      {projectId && (
        <fieldset className="space-y-2">
          <legend>Supporting project documents ({Object.keys(evidence).length}/10)</legend>
          <label className="block text-sm">Search supporting documents
            <input className="form-field" value={documentSearch} onChange={(event) => {
              setDocumentSearch(event.target.value);
              setDocumentOffset(0);
            }} />
          </label>
          {documents.isPending && <p role="status">Loading documents…</p>}
          {documents.isError && <p role="alert">Unable to load supporting documents.</p>}
          {documents.data?.items.filter((document) => document.active_version != null).map((document) => (
            <button className="form-button" key={document.id} type="button"
              disabled={Boolean(evidence[document.id]) || Object.keys(evidence).length >= 10}
              onClick={() => setEvidence((selected) => ({ ...selected, [document.id]: document.title }))}>
              Select {document.title}
            </button>
          ))}
          {documents.data && !documents.data.items.some((document) => document.active_version != null) &&
            <p>No active documents on this page.</p>}
          {documentOffset > 0 && <button type="button" onClick={() => setDocumentOffset(documentOffset - 20)}>Previous documents</button>}
          {documentOffset + 20 < (documents.data?.total ?? 0) &&
            <button type="button" onClick={() => setDocumentOffset(documentOffset + 20)}>Next documents</button>}
          {Object.entries(evidence).map(([id, label]) => (
            <button type="button" key={id} onClick={() => setEvidence((selected) =>
              Object.fromEntries(Object.entries(selected).filter(([key]) => key !== id)))}>
              Remove {label}
            </button>
          ))}
        </fieldset>
      )}
      {supervisor && projectId && (!correction || draft) && (
        <div className="space-y-2">
          <label className="block text-sm">Upload request evidence
            <input type="file" className="form-field" multiple accept="image/jpeg,image/png,.heic,application/pdf"
              disabled={media.isPending || create.isPending}
              onChange={(event) => {
                const files = Array.from(event.target.files ?? []);
                if (files.length) media.mutate({ files });
                event.target.value = '';
              }} />
          </label>
          {media.isError && <p role="alert">{formatApiError(media.error, 'Unable to update evidence.')}</p>}
          {attached.data?.items.map((file) => (
            <div className="flex gap-2" key={file.id}>
              <span>{file.original_name}</span>
              <button type="button" disabled={media.isPending || create.isPending}
                onClick={() => media.mutate({ remove: file.id })}>Remove {file.original_name}</button>
            </div>
          ))}
        </div>
      )}
      {(correction?.replaceRemainder || correction?.request.status === 'approved') && (
        <label className="block text-sm">Correction reason
          <textarea className="form-field" required maxLength={2000} value={reason}
            onChange={(event) => setReason(event.target.value)} />
        </label>
      )}
      {error && <p role="alert">{error}</p>}
      <button className="form-button" type="submit" disabled={!projectId || create.isPending || media.isPending}>
        {create.isPending ? 'Submitting…' : correction ? 'Resubmit request' : 'Submit request'}
      </button>
    </form>
  );
}

export function MaterialRequestReview({
  request,
  items,
  locations,
  userId,
  canManage,
  canSubmit,
  isAssignedProcessorRole,
  onSuccess
}: {
  request: MaterialRequestRecord;
  items: InventoryItemRecord[];
  locations: StorageLocationRecord[];
  userId?: string;
  canManage: boolean;
  canSubmit: boolean;
  isAssignedProcessorRole: boolean;
  onSuccess: () => void;
}) {
  const [expanded, setExpanded] = useState(false);
  const [evidenceError, setEvidenceError] = useState<string>();
  const [editing, setEditing] = useState(false);
  const history = useQuery({
    queryKey: ['material-submissions', request.id, request.revision],
    queryFn: () => materialSubmissionHistory(request.id),
    enabled: expanded || isAssignedProcessorRole
  });
  const recent = history.data?.submissions[0];
  const hasStock = request.lines.some((line) =>
    stockMilliquantity(line.reserved_quantity) > 0n || stockMilliquantity(line.issued_quantity) > 0n);
  const replaceRemainder = canManage && hasStock &&
    ['approved', 'reserved', 'partially_reserved', 'partially_issued'].includes(request.status);
  const canCorrect = replaceRemainder || (!hasStock && canSubmit && (canManage || request.requester_id === userId) &&
    (['draft', 'approved', 'returned', 'rejected'].includes(request.status) ||
      (request.submission_revision == null && ['requested', 'approved'].includes(request.status))));
  const canFulfill = request.submission_revision != null &&
    (canManage || (isAssignedProcessorRole && recent?.processor_id === userId));

  return (
    <div className="mt-2 space-y-2">
      {request.submission_revision == null && request.status !== 'draft' && (
        <p>Legacy request. Technical verification and GPM approval are required before fulfillment.</p>
      )}
      <details open={expanded} onToggle={(event) => setExpanded(event.currentTarget.open)}>
        <summary className="cursor-pointer text-brand-600">Submission and decision history</summary>
        {evidenceError && <p role="alert">{evidenceError}</p>}
        {history.isPending && expanded && <p role="status">Loading history…</p>}
        {history.isError && (
          <p role="alert">{formatApiError(history.error, 'Unable to load submission history.')}</p>
        )}
        {history.data?.submissions.map((submission) => (
          <section className="my-2 border-l border-theme-border pl-3" key={submission.submission_revision}>
            <h4 className="font-medium">Submission {submission.submission_revision}</h4>
            <p>Required {submission.requirements.requirements.required_date} · {submission.requirements.requirements.urgency}</p>
            <p>{submission.requirements.requirements.purpose}</p>
            <p>{submission.requirements.requirements.specification}</p>
            <ul>
              {Object.entries(submission.requirements.evidence_versions).map(([documentId, version], index) => (
                <li key={documentId}>
                  <button type="button" onClick={async () => {
                    try {
                      const file = await getDocumentVersionDownloadUrl(documentId, version);
                      window.open(file.url, '_blank', 'noopener,noreferrer');
                    } catch (cause) {
                      setEvidenceError(formatApiError(cause, 'Unable to open the submitted document.'));
                    }
                  }}>Open supporting document {index + 1} (version {version})</button>
                </li>
              ))}
              {submission.requirements.evidence_file_ids?.map((fileId, index) => (
                <li key={fileId}>
                  <button type="button" onClick={async () => {
                    try {
                      const file = await getPhotoDownloadUrl(fileId);
                      window.open(file, '_blank', 'noopener,noreferrer');
                    } catch (cause) {
                      setEvidenceError(formatApiError(cause, 'Unable to open evidence.'));
                    }
                  }}>Open evidence file {index + 1}</button>
                </li>
              ))}
              {submission.requirements.lines.map((line) => (
                <li key={line.item_id}>{line.name} · {line.quantity} {line.unit}</li>
              ))}
              {history.data?.decisions.filter(
                (decision) => decision.submission_revision === submission.submission_revision
              ).map((decision) => (
                <li key={decision.id}>
                  {decision.step_order === 1 ? 'Site Engineer' : 'Group Project Manager'} · {decision.status}
                  {decision.decision_comments && ` · ${decision.decision_comments}`}
                </li>
              ))}
            </ul>
          </section>
        ))}
        {canCorrect && !editing && history.isSuccess && (
          <button className="form-button" type="button" onClick={() => setEditing(true)}>
            {request.status === 'draft' ? 'Resume draft' : replaceRemainder ? 'Replace unissued remainder' : 'Correct and resubmit'}
          </button>
        )}
        {editing && canCorrect && (
          <MaterialRequestForm
            items={items} locations={locations}
            correction={{ request, snapshot: recent?.requirements, replaceRemainder }}
            onSuccess={() => { setEditing(false); onSuccess(); }}
          />
        )}
      </details>
      <MaterialFulfillment request={request} items={items} canManage={canFulfill} onSuccess={onSuccess} />
    </div>
  );
}

function RequestLineAvailability({ itemId, locationId }: { itemId: string; locationId: string }) {
  const stock = useQuery({
    queryKey: ['inventory-stock', itemId],
    queryFn: () => listItemStock(itemId)
  });
  const balance = stock.data?.find((row) => row.location_id === locationId);
  if (stock.isPending) return <span>Loading availability…</span>;
  if (stock.isError) return <span role="alert">Availability unavailable</span>;
  return <span>{balance?.available_qty ?? '0'} available at source</span>;
}

function MaterialFulfillment({
  request,
  items,
  canManage,
  onSuccess
}: {
  request: MaterialRequestRecord;
  items: InventoryItemRecord[];
  canManage: boolean;
  onSuccess: () => void;
}) {
  const [expanded, setExpanded] = useState(false);
  const [quantities, setQuantities] = useState<Record<string, string>>({});
  const [pending, setPending] = useState<'reserve' | 'issue' | null>(null);
  const [error, setError] = useState<string | null>(null);
  const attempt = useRef<{
    signature: string;
    command: MaterialQuantityCommand;
    key: string;
  } | null>(null);
  const inFlight = useRef(false);
  const eligible =
    canManage &&
    ['approved', 'reserved', 'partially_reserved', 'partially_issued'].includes(request.status);

  async function fulfill(action: 'reserve' | 'issue') {
    if (inFlight.current) return;
    const command: MaterialQuantityCommand = {
      expected_revision: request.revision,
      lines: request.lines
        .filter((line) => quantities[line.id]?.trim())
        .map((line) => ({ line_id: line.id, quantity: quantities[line.id] }))
    };
    if (!command.lines.length) {
      setError('Enter a quantity for at least one line.');
      return;
    }
    const signature = JSON.stringify([action, command.lines]);
    if (attempt.current?.signature !== signature) {
      attempt.current = { signature, command, key: crypto.randomUUID() };
    }
    const intent = attempt.current;
    inFlight.current = true;
    setPending(action);
    setError(null);
    try {
      await fulfillMaterialRequest(request.id, action, intent.command, intent.key);
      setQuantities({});
      attempt.current = null;
      onSuccess();
    } catch (cause) {
      const status = isAxiosError(cause) ? cause.response?.status : undefined;
      if (status && status >= 400 && status < 500) {
        attempt.current = null;
        if (status === 409) onSuccess();
      }
      setError(
        formatApiError(
          cause,
          'Unable to confirm the change. Retry the same quantities to check the result.'
        )
      );
    } finally {
      inFlight.current = false;
      setPending(null);
    }
  }

  return (
    <details
      className="mt-2 rounded-md border border-theme-border p-2"
      onToggle={(event) => setExpanded(event.currentTarget.open)}
    >
      <summary className="cursor-pointer font-medium">Request lines</summary>
      {request.lines.map((line) => {
        const item = items.find((candidate) => candidate.id === line.item_id);
        const outstanding = unissuedQuantity(line.quantity, line.issued_quantity);
        return (
          <div className="mt-2 border-t border-theme-border pt-2" key={line.id}>
            <p>
              {item?.name ?? line.item_id} {item?.unit && `(${item.unit})`}
            </p>
            <p className="text-xs text-theme-text-muted">
              {line.quantity} requested · {outstanding} outstanding · {line.reserved_quantity}{' '}
              reserved · {line.issued_quantity} issued
            </p>
            {eligible && (
              <label className="block text-sm">
                Quantity for {item?.name ?? 'this line'}
                <input
                  className="form-field"
                  type="number"
                  min="0.001"
                  step="0.001"
                  disabled={pending !== null}
                  value={quantities[line.id] ?? ''}
                  onChange={(event) =>
                    setQuantities({ ...quantities, [line.id]: event.target.value })
                  }
                />
                {expanded && request.from_location_id && (
                  <RequestLineAvailability
                    itemId={line.item_id}
                    locationId={request.from_location_id}
                  />
                )}
              </label>
            )}
          </div>
        );
      })}
      {error && (
        <p role="alert" className="mt-2">
          {error}
        </p>
      )}
      {eligible && (
        <div className="mt-2 flex flex-wrap gap-2">
          <button
            className="form-button"
            type="button"
            disabled={pending !== null}
            onClick={() => void fulfill('reserve')}
          >
            {pending === 'reserve' ? 'Reserving…' : 'Reserve selected'}
          </button>
          <button
            className="form-button"
            type="button"
            disabled={pending !== null}
            onClick={() => void fulfill('issue')}
          >
            {pending === 'issue' ? 'Issuing…' : 'Issue selected'}
          </button>
        </div>
      )}
    </details>
  );
}
