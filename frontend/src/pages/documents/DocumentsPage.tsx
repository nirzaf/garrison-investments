import { useQuery, useQueryClient } from '@tanstack/react-query';
import { AlertTriangle, Check, Download, Eye, FileUp, Search, X } from 'lucide-react';
import { FormEvent, useEffect, useMemo, useRef, useState } from 'react';
import { useSearchParams } from 'react-router-dom';

import {
  approveDocumentVersion,
  getDocument,
  getDocumentDownloadUrl,
  listDocuments,
  uploadDocument,
  uploadDocumentVersion,
  type DocumentListResponse,
  type DocumentRecord
} from '../../api/documents';
import { formatApiError } from '../../api/errors';
import { PDF_IMAGE_ACCEPT, validateDocumentFile } from '../../api/fileValidation';
import { listDocumentProjectOptions, type ProjectOption } from '../../api/projects';
import { EmptyState } from '../../components/shared/EmptyState';
import { StatusBadge } from '../../components/shared/StatusBadge';
import { useAuth } from '../../context/useAuth';

const documentPageSize = 25;
const documentTypes = [
  ['mar', 'MAR'],
  ['mir', 'MIR'],
  ['wir', 'WIR'],
  ['delivery_note', 'Delivery note'],
  ['drawing', 'Drawing'],
  ['contract', 'Contract'],
  ['invoice', 'Invoice']
] as const;

export function DocumentsPage() {
  const { user } = useAuth();
  const queryClient = useQueryClient();
  const [searchParams] = useSearchParams();
  const focusedDocumentId = searchParams.get('documentId');
  const focusedVersionId = searchParams.get('versionId');
  const [projectSearch, setProjectSearch] = useState('');
  const [projectOptions, setProjectOptions] = useState<ProjectOption[]>([]);
  const [search, setSearch] = useState('');
  const [committedSearch, setCommittedSearch] = useState('');
  const [page, setPage] = useState(0);
  const [projectId, setProjectId] = useState('');
  const [filterType, setFilterType] = useState('');
  const [uploadProjectId, setUploadProjectId] = useState('');
  const [replacementDocumentId, setReplacementDocumentId] = useState<string | null>(null);
  const [replacementFile, setReplacementFile] = useState<File | null>(null);
  const [pending, setPending] = useState(false);
  const pendingWrite = useRef(false);
  const replacementKey = useRef('');
  const uploadFileInput = useRef<HTMLInputElement>(null);
  const [title, setTitle] = useState('');
  const [documentType, setDocumentType] = useState('wir');
  const [expiryDate, setExpiryDate] = useState('');
  const [file, setFile] = useState<File | null>(null);
  const [notice, setNotice] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [preview, setPreview] = useState<{
    documentId: string;
    versionId: string;
    title: string;
    url: string;
  } | null>(null);
  const [previewPending, setPreviewPending] = useState(false);
  const [previewError, setPreviewError] = useState<string | null>(null);
  const previewRequest = useRef(0);
  const documentRefs = useRef<Record<string, HTMLElement | null>>({});
  const canManageDocuments = user?.permissions?.includes('documents:manage') ?? false;
  const canUseCompanyScope = ['managing_director', 'operations_director'].includes(user?.role ?? '');
  const projectsQuery = useQuery({
    queryKey: ['documents', 'project-options', projectSearch],
    queryFn: () => listDocumentProjectOptions({ search: projectSearch || undefined, limit: 100 })
  });
  const projects = [...(projectsQuery.data?.items ?? []), ...projectOptions.filter(
    (option) => !projectsQuery.data?.items.some((item) => item.id === option.id)
  )];

  const normalizedType = filterType.trim().toLowerCase();
  const documentList = useQuery({
    queryKey: ['documents', 'page', projectId, committedSearch, normalizedType, page],
    queryFn: ({ signal }) => listDocuments({
      search: committedSearch || undefined,
      project_id: projectId || undefined,
      document_type: normalizedType || undefined,
      limit: documentPageSize,
      offset: page * documentPageSize
    }, signal)
  });
  const focusedDocument = useQuery({
    queryKey: ['documents', 'detail', focusedDocumentId],
    queryFn: ({ signal }) => getDocument(focusedDocumentId!, signal),
    enabled: Boolean(focusedDocumentId)
  });
  const documents = useMemo(() => {
    const items = documentList.data?.items ?? [];
    const focused = focusedDocument.data;
    if (focused && !items.some((item) => item.id === focused.id)) {
      return [focused, ...items];
    }
    return items;
  }, [documentList.data, focusedDocument.data]);
  const totalPages = Math.max(1, Math.ceil((documentList.data?.total ?? 0) / documentPageSize));
  const pagingDisabled = documentList.isPending || search.trim() !== committedSearch;
  const resultTotal = !pagingDisabled && documentList.isSuccess ? documentList.data.total : null;

  useEffect(() => {
    const timer = window.setTimeout(() => {
      setCommittedSearch(search.trim());
      setPage(0);
    }, 300);
    return () => window.clearTimeout(timer);
  }, [search]);

  useEffect(() => {
    if (!focusedDocumentId) return;
    const element = documentRefs.current[focusedDocumentId];
    element?.scrollIntoView({ behavior: 'smooth', block: 'center' });
  }, [documents, focusedDocumentId]);

  async function saveDocument(action: () => Promise<void>, fallback: string) {
    if (pendingWrite.current) return;
    pendingWrite.current = true;
    setPending(true);
    setError(null);
    setNotice(null);
    try {
      await action();
      await queryClient.invalidateQueries({ queryKey: ['documents'] });
    } catch (reason) {
      setError(formatApiError(reason, reason instanceof Error && reason.name !== 'AxiosError'
        ? reason.message : fallback));
    } finally {
      setPending(false);
      pendingWrite.current = false;
    }
  }

  function retainProjectOption(id: string) {
    const option = projects.find((project) => project.id === id);
    if (option) setProjectOptions((previous) => previous.some((project) => project.id === id)
      ? previous : [...previous, option]);
  }

  function submitUpload(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (!file) {
      setError('Select a document file.');
      return;
    }
    void saveDocument(async () => {
      await validateDocumentFile(file);
      await uploadDocument({
        title,
        documentType,
        projectId: uploadProjectId || undefined,
        expiryDate: expiryDate || undefined,
        file
      });
      setTitle('');
      setExpiryDate('');
      setFile(null);
      if (uploadFileInput.current) uploadFileInput.current.value = '';
      setNotice('Document uploaded for approval.');
      setPage(0);
    }, 'Unable to upload document.');
  }

  function submitReplacement(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (!replacementDocumentId || !replacementFile) return;
    void saveDocument(async () => {
      await validateDocumentFile(replacementFile);
      await uploadDocumentVersion(replacementDocumentId, replacementFile, replacementKey.current);
      setReplacementDocumentId(null);
      setReplacementFile(null);
      setNotice('Replacement uploaded for approval.');
    }, 'Unable to upload the replacement.');
  }

  function approve(document: DocumentRecord, versionId: string) {
    void saveDocument(async () => {
      const approved = await approveDocumentVersion({ documentId: document.id, versionId });
      const listQueries = { queryKey: ['documents', 'page'] };
      const detailQuery = { queryKey: ['documents', 'detail', approved.id], exact: true };
      await Promise.all([
        queryClient.cancelQueries(listQueries),
        queryClient.cancelQueries(detailQuery)
      ]);
      queryClient.setQueriesData<DocumentListResponse>(listQueries, (previous) =>
        previous?.items.some((item) => item.id === approved.id)
          ? { ...previous, items: previous.items.map((item) => item.id === approved.id ? approved : item) }
          : previous
      );
      queryClient.setQueryData<DocumentRecord>(detailQuery.queryKey, approved);
      setNotice('Document version approved.');
    }, 'Unable to approve document version.');
  }

  async function download(document: DocumentRecord, versionId?: string) {
    try {
      const response = await getDocumentDownloadUrl(document.id, versionId);
      if (response.superseded_warning) {
        setNotice('This is a superseded document version.');
      }
      window.open(response.url, '_blank', 'noopener,noreferrer');
    } catch (reason) {
      setError(formatApiError(reason, 'Unable to create download link.'));
    }
  }

  async function openPreview(documentId: string, versionId: string, title: string) {
    const request = ++previewRequest.current;
    setPreviewPending(true);
    setPreviewError(null);
    setError(null);
    try {
      const response = await getDocumentDownloadUrl(documentId, versionId);
      if (request !== previewRequest.current) return;
      setPreview({ documentId, versionId, title, url: response.url });
      if (response.superseded_warning) setNotice('This is a superseded document version.');
    } catch (reason) {
      if (request !== previewRequest.current) return;
      const message = formatApiError(reason, 'Unable to load document preview.');
      if (preview) setPreviewError(message);
      else setError(message);
    } finally {
      if (request === previewRequest.current) setPreviewPending(false);
    }
  }

  return (
    <div className="space-y-6">
      <div className="flex flex-col justify-between gap-3 lg:flex-row lg:items-end">
        <div>
          <p className="text-sm font-medium text-brand-600">Documents</p>
          <h2 className="text-2xl font-semibold text-theme-text-primary">Document Library</h2>
        </div>
        <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-4">
          <input
            aria-label="Find projects by name or code"
            className="form-field"
            maxLength={100}
            onChange={(event) => setProjectSearch(event.target.value)}
            placeholder="Find projects"
            value={projectSearch}
          />
          <select
            aria-label="Filter documents by project"
            className="form-field"
            onChange={(event) => {
              retainProjectOption(event.target.value);
              setProjectId(event.target.value);
              setPage(0);
            }}
            value={projectId}
          >
            <option value="">All projects</option>
            {projects.map((project) => (
              <option key={project.id} value={project.id}>
                {project.code} - {project.name}
              </option>
            ))}
          </select>
          <input
            aria-label="Filter documents by type"
            className="form-field"
            list="document-type-options"
            onChange={(event) => {
              setFilterType(event.target.value);
              setPage(0);
            }}
            placeholder="All types"
            value={filterType}
          />
          <datalist id="document-type-options">
            {documentTypes.map(([value, label]) => <option key={value} value={value}>{label}</option>)}
          </datalist>
          <div className="relative">
            <Search className="pointer-events-none absolute left-3 top-3 h-4 w-4 text-theme-text-muted" />
            <input
              aria-label="Search documents"
              className="form-field pl-9"
              onChange={(event) => setSearch(event.target.value)}
              placeholder="Search documents"
              value={search}
            />
          </div>
        </div>
      </div>

      {notice ? <Alert tone="success" message={notice} /> : null}
      {error ? <Alert tone="error" message={error} /> : null}
      {projectsQuery.isError ? (
        <Alert tone="error" message={formatApiError(projectsQuery.error, 'Unable to load project options.')} />
      ) : null}
      {documentList.isError ? (
        <div>
          <Alert tone="error" message={formatApiError(documentList.error, 'Unable to load documents.')} />
          <button onClick={() => void documentList.refetch()} type="button">Retry loading documents</button>
        </div>
      ) : null}
      {focusedDocument.isError ? (
        <Alert tone="error" message={formatApiError(focusedDocument.error, 'Unable to open linked document.')} />
      ) : null}
      {projectId || projectSearch || filterType || search ? (
        <button
          className="form-field"
          onClick={() => {
            setProjectId('');
            setProjectSearch('');
            setFilterType('');
            setSearch('');
            setCommittedSearch('');
            setPage(0);
          }}
          type="button"
        >
          Clear filters
        </button>
      ) : null}

      <p className="text-sm text-theme-text-secondary" role="status">
        {resultTotal === null
          ? ''
          : `${resultTotal} matching document${resultTotal === 1 ? '' : 's'}`}
      </p>

      {canManageDocuments ? (
        <form
          className="grid gap-3 rounded-lg border border-theme-border bg-theme-card p-4 shadow-xs lg:grid-cols-[1fr_160px_180px_180px_1fr_auto]"
          onSubmit={submitUpload}
        >
          <input
            aria-label="Document title"
            className="form-field"
            disabled={pending}
            onChange={(event) => setTitle(event.target.value)}
            placeholder="Document title"
            required
            value={title}
          />
          <select
            aria-label="Upload document type"
            className="form-field"
            disabled={pending}
            onChange={(event) => setDocumentType(event.target.value)}
            value={documentType}
          >
            {documentTypes.map(([value, label]) => <option key={value} value={value}>{label}</option>)}
          </select>
          <select
            aria-label="Upload document project"
            className="form-field"
            disabled={pending}
            onChange={(event) => {
              retainProjectOption(event.target.value);
              setUploadProjectId(event.target.value);
            }}
            required={!canUseCompanyScope}
            value={uploadProjectId}
          >
            <option value="">{canUseCompanyScope ? 'Company-wide document' : 'Select a project'}</option>
            {projects.map((project) => (
              <option key={project.id} value={project.id}>{project.code} - {project.name}</option>
            ))}
          </select>
          <input
            aria-label="Document expiry date"
            className="form-field"
            disabled={pending}
            onChange={(event) => setExpiryDate(event.target.value)}
            type="date"
            value={expiryDate}
          />
          <input
            accept={PDF_IMAGE_ACCEPT}
            aria-label="Document file"
            className="form-field"
            disabled={pending}
            onChange={(event) => setFile(event.target.files?.[0] ?? null)}
            ref={uploadFileInput}
            required
            type="file"
          />
          <button
            className="inline-flex min-h-10 items-center justify-center gap-2 rounded-md bg-brand-600 px-4 py-2 text-sm font-semibold text-white hover:bg-brand-700"
            disabled={pending}
            type="submit"
          >
            <FileUp className="h-4 w-4" />
            Upload
          </button>
        </form>
      ) : null}

      {documents.length === 0 ? (
        documentList.isError ? null : (
          <EmptyState
            description={documentList.isPending ? 'Fetching document records.' : 'No documents match these filters.'}
            title={documentList.isPending ? 'Loading documents' : 'No documents found'}
          />
        )
      ) : (
        <div className="grid gap-4">
          {documents.map((document) => {
            const canApprove = canManageDocuments && document.status !== 'archived';
            const outsideResults = document.id === focusedDocumentId &&
              !documentList.data?.items.some((item) => item.id === document.id);
            const active = document.versions.find(
              (version) => version.version === document.active_version
            );
            return (
              <article
                className={`rounded-lg border bg-theme-card p-4 shadow-xs ${
                  document.id === focusedDocumentId
                    ? 'border-brand-600 ring-2 ring-brand-600/20'
                    : 'border-theme-border'
                }`}
                key={document.id}
                ref={(element) => {
                  documentRefs.current[document.id] = element;
                }}
              >
                <div className="flex flex-col justify-between gap-3 lg:flex-row lg:items-start">
                  <div>
                    <div className="flex flex-wrap items-center gap-2">
                      <h3 className="text-base font-semibold text-theme-text-primary">
                        {document.title}
                      </h3>
                      <StatusBadge tone={document.status === 'active' ? 'success' : 'warning'}>
                        {document.status.replace('_', ' ')}
                      </StatusBadge>
                    </div>
                    {outsideResults ? (
                      <p className="mt-1 text-sm text-theme-text-muted">Linked document outside the current results</p>
                    ) : null}
                    <p className="mt-1 text-sm text-theme-text-muted">
                      {document.document_type} · {projects.find((project) => project.id === document.project_id)?.name ??
                        (document.project_id ? 'Project document' : 'Company-wide')} · {active ? `Active v${active.version}` : 'No active version'}
                    </p>
                  </div>
                  <div className="flex flex-wrap gap-2">
                    {canManageDocuments && document.status !== 'archived' && replacementDocumentId !== document.id ? (
                      <button
                        className="form-field"
                        disabled={pending}
                        onClick={() => {
                          setReplacementFile(null);
                          setReplacementDocumentId(document.id);
                        }}
                        type="button"
                      >
                        Upload replacement
                      </button>
                    ) : null}
                    {active ? (
                      <>
                        <button
                          className="inline-flex min-h-10 items-center gap-2 rounded-md border border-theme-border px-3 py-2 text-sm font-semibold text-theme-text-secondary"
                          disabled={previewPending}
                          onClick={() => void openPreview(document.id, active.id, document.title)}
                          type="button"
                        >
                          <Eye className="h-4 w-4" />
                          View
                        </button>
                        <button
                          className="inline-flex min-h-10 items-center gap-2 rounded-md border border-theme-border px-3 py-2 text-sm font-semibold text-theme-text-secondary"
                          onClick={() => void download(document)}
                          type="button"
                        >
                          <Download className="h-4 w-4" />
                          Download
                        </button>
                      </>
                    ) : null}
                  </div>
                </div>
                {replacementDocumentId === document.id ? (
                  <form className="mt-4 flex flex-wrap items-center gap-3" onSubmit={submitReplacement}>
                    <label className="text-sm">
                      Replacement file · PDF, JPEG, PNG up to 60 MiB
                      <input
                        accept={PDF_IMAGE_ACCEPT}
                        className="form-field block"
                        disabled={pending}
                        onChange={(event) => {
                          setReplacementFile(event.target.files?.[0] ?? null);
                          replacementKey.current = crypto.randomUUID();
                        }}
                        type="file"
                      />
                    </label>
                    <button className="form-field" disabled={pending || !replacementFile} type="submit">
                      Upload for approval
                    </button>
                    <button
                      className="form-field"
                      disabled={pending}
                      onClick={() => {
                        setReplacementDocumentId(null);
                        setReplacementFile(null);
                      }}
                      type="button"
                    >
                      Cancel replacement
                    </button>
                  </form>
                ) : null}
                <div className="mt-4 grid gap-2 text-sm text-theme-text-secondary">
                  {document.versions.map((version) => (
                    <div
                      className={`flex items-center justify-between gap-3 rounded-md px-2 py-1 ${
                        version.id === focusedVersionId ? 'bg-theme-main' : ''
                      }`}
                      key={version.id}
                    >
                      <span>
                        v{version.version} - {version.original_name}
                      </span>
                      <div className="flex flex-wrap items-center gap-2">
                        <span>{version.status.replace('_', ' ')}</span>
                        <button
                          className="form-field"
                          onClick={() => void download(document, version.id)}
                          type="button"
                        >
                          Download v{version.version}
                        </button>
                        {canApprove && version.status === 'pending_approval' &&
                        version.uploaded_by !== user?.id ? (
                          <button
                            className="form-field"
                            disabled={pending}
                            onClick={() => approve(document, version.id)}
                            type="button"
                          >
                            Approve v{version.version}
                          </button>
                        ) : null}
                        {canApprove && version.status === 'pending_approval' &&
                        version.uploaded_by === user?.id ? (
                          <span className="text-sm text-theme-text-muted">
                            Awaiting approval by another authorized user
                          </span>
                        ) : null}
                      </div>
                    </div>
                  ))}
                </div>
              </article>
            );
          })}
        </div>
      )}

      {page > 0 || totalPages > 1 ? (
        <nav aria-label="Document pages" className="flex items-center justify-end gap-3">
          <button
            className="form-field disabled:opacity-50"
            disabled={page === 0 || pagingDisabled}
            onClick={() => setPage(page - 1)}
            type="button"
          >
            Previous
          </button>
          <span className="text-sm text-theme-text-secondary" aria-live="polite">
            Page {page + 1}{documentList.data ? ` of ${totalPages}` : ''}
          </span>
          <button
            className="form-field disabled:opacity-50"
            disabled={page + 1 >= totalPages || pagingDisabled}
            onClick={() => setPage(page + 1)}
            type="button"
          >
            Next
          </button>
        </nav>
      ) : null}

      {preview ? (
        <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/60">
          <div
            aria-label={preview.title}
            aria-modal="true"
            className="relative max-h-[90vh] w-full max-w-4xl rounded-lg bg-theme-card shadow-xl"
            role="dialog"
          >
            <div className="flex items-center justify-between border-b border-theme-border px-4 py-3">
              <h3 className="text-sm font-semibold text-theme-text-primary truncate">
                {preview.title}
              </h3>
              <div className="flex shrink-0 items-center gap-2">
                <button
                  className="form-button"
                  disabled={previewPending}
                  onClick={() => void openPreview(preview.documentId, preview.versionId, preview.title)}
                  type="button"
                >
                  {previewPending ? 'Refreshing…' : 'Refresh preview'}
                </button>
                <button
                  aria-label="Close preview"
                  className="rounded-md p-1 text-theme-text-muted hover:bg-theme-card-elevated"
                  onClick={() => {
                    previewRequest.current += 1;
                    setPreview(null);
                    setPreviewPending(false);
                    setPreviewError(null);
                  }}
                  type="button"
                >
                  <X className="h-5 w-5" />
                </button>
              </div>
            </div>
            {previewError ? <Alert tone="error" message={previewError} /> : (
              <iframe className="h-[80vh] w-full" src={preview.url} title={preview.title} />
            )}
          </div>
        </div>
      ) : null}
    </div>
  );
}

function Alert({ message, tone }: { message: string; tone: 'error' | 'success' }) {
  const Icon = tone === 'success' ? Check : AlertTriangle;
  const cls = tone === 'success' ? 'alert-success' : 'alert-error';
  return (
    <div className={`flex items-center gap-2 rounded-md px-3 py-2 text-sm ${cls}`} role={tone === 'error' ? 'alert' : 'status'}>
      <Icon className="h-4 w-4" />
      <span>{message}</span>
    </div>
  );
}
