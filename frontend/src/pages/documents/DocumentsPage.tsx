import { AlertTriangle, Check, Download, Eye, FileUp, Search, X } from 'lucide-react';
import { FormEvent, useCallback, useEffect, useState } from 'react';

import {
  approveDocumentVersion,
  getDocumentDownloadUrl,
  listDocuments,
  uploadDocument,
  type DocumentRecord
} from '../../api/documents';
import { listProjects, type ProjectRecord } from '../../api/projects';
import { EmptyState } from '../../components/shared/EmptyState';
import { StatusBadge } from '../../components/shared/StatusBadge';
import { useAuth } from '../../context/useAuth';

export function DocumentsPage() {
  const { user } = useAuth();
  const [documents, setDocuments] = useState<DocumentRecord[]>([]);
  const [projects, setProjects] = useState<ProjectRecord[]>([]);
  const [search, setSearch] = useState('');
  const [projectId, setProjectId] = useState('');
  const [title, setTitle] = useState('');
  const [documentType, setDocumentType] = useState('wir');
  const [expiryDate, setExpiryDate] = useState('');
  const [file, setFile] = useState<File | null>(null);
  const [notice, setNotice] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [isLoading, setIsLoading] = useState(false);
  const [previewUrl, setPreviewUrl] = useState<string | null>(null);
  const [previewTitle, setPreviewTitle] = useState('');
  const canManageDocuments = user?.permissions?.includes('documents:manage') ?? false;

  const loadDocuments = useCallback(async () => {
    setIsLoading(true);
    setError(null);
    try {
      const response = await listDocuments({
        search: search || undefined,
        project_id: projectId || undefined
      });
      setDocuments(response.items);
    } catch {
      setError('Unable to load documents.');
    } finally {
      setIsLoading(false);
    }
  }, [projectId, search]);

  useEffect(() => {
    void listProjects({ status: 'active' }).then((response) => setProjects(response.items));
  }, []);

  useEffect(() => {
    void loadDocuments();
  }, [loadDocuments]);

  async function submitUpload(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (!file) {
      setError('Select a document file.');
      return;
    }
    if (file.size > 60 * 1024 * 1024) {
      setError('Document exceeds the 60 MB size limit.');
      return;
    }
    setError(null);
    setNotice(null);
    try {
      await uploadDocument({
        title,
        documentType,
        projectId: projectId || undefined,
        expiryDate: expiryDate || undefined,
        file
      });
      setTitle('');
      setExpiryDate('');
      setFile(null);
      setNotice('Document uploaded for approval.');
      await loadDocuments();
    } catch {
      setError('Unable to upload document.');
    }
  }

  async function approve(document: DocumentRecord) {
    const pending = document.versions.find((version) => version.status === 'pending_approval');
    if (!pending) return;
    try {
      await approveDocumentVersion({
        documentId: document.id,
        versionId: pending.id,
        comments: 'Approved from document library.'
      });
      setNotice('Document version approved.');
      await loadDocuments();
    } catch {
      setError('Unable to approve document.');
    }
  }

  async function download(document: DocumentRecord, versionId?: string) {
    try {
      const response = await getDocumentDownloadUrl(document.id, versionId);
      if (response.superseded_warning) {
        setNotice('This is a superseded document version.');
      }
      window.open(response.url, '_blank', 'noopener,noreferrer');
    } catch {
      setError('Unable to create download link.');
    }
  }

  async function preview(document: DocumentRecord, versionId?: string) {
    try {
      const response = await getDocumentDownloadUrl(document.id, versionId);
      setPreviewUrl(response.url);
      setPreviewTitle(document.title);
    } catch {
      setError('Unable to load document preview.');
    }
  }

  return (
    <div className="space-y-6">
      <div className="flex flex-col justify-between gap-3 lg:flex-row lg:items-end">
        <div>
          <p className="text-sm font-medium text-brand-600">Documents</p>
          <h2 className="text-2xl font-semibold text-theme-text-primary">Document Library</h2>
        </div>
        <div className="grid gap-3 sm:grid-cols-[220px_260px]">
          <select
            className="form-field"
            onChange={(event) => setProjectId(event.target.value)}
            value={projectId}
          >
            <option value="">All projects</option>
            {projects.map((project) => (
              <option key={project.id} value={project.id}>
                {project.code} - {project.name}
              </option>
            ))}
          </select>
          <div className="relative">
            <Search className="pointer-events-none absolute left-3 top-3 h-4 w-4 text-theme-text-muted" />
            <input
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

      {canManageDocuments ? (
        <form
          className="grid gap-3 rounded-lg border border-theme-border bg-theme-card p-4 shadow-sm lg:grid-cols-[1fr_160px_180px_180px_1fr_auto]"
          onSubmit={submitUpload}
        >
          <input
            className="form-field"
            onChange={(event) => setTitle(event.target.value)}
            placeholder="Document title"
            required
            value={title}
          />
          <select
            className="form-field"
            onChange={(event) => setDocumentType(event.target.value)}
            value={documentType}
          >
            <option value="mar">MAR</option>
            <option value="mir">MIR</option>
            <option value="wir">WIR</option>
            <option value="delivery_note">Delivery note</option>
            <option value="drawing">Drawing</option>
            <option value="contract">Contract</option>
            <option value="invoice">Invoice</option>
          </select>
          <input
            className="form-field"
            onChange={(event) => setExpiryDate(event.target.value)}
            type="date"
            value={expiryDate}
          />
          <input
            accept="application/pdf,image/jpeg,image/png"
            className="form-field"
            onChange={(event) => setFile(event.target.files?.[0] ?? null)}
            required
            type="file"
          />
          <button
            className="inline-flex min-h-10 items-center justify-center gap-2 rounded-md bg-brand-600 px-4 py-2 text-sm font-semibold text-white hover:bg-brand-700"
            type="submit"
          >
            <FileUp className="h-4 w-4" />
            Upload
          </button>
        </form>
      ) : null}

      {documents.length === 0 ? (
        <EmptyState
          description={isLoading ? 'Loading documents.' : 'Uploaded documents will appear here.'}
          title="No documents found"
        />
      ) : (
        <div className="grid gap-4">
          {documents.map((document) => {
            const pending = document.versions.find(
              (version) => version.status === 'pending_approval'
            );
            const active = document.versions.find(
              (version) => version.version === document.active_version
            );
            return (
              <article
                className="rounded-lg border border-theme-border bg-theme-card p-4 shadow-sm"
                key={document.id}
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
                    <p className="mt-1 text-sm text-theme-text-muted">
                      {document.document_type} - active v{document.active_version ?? '-'}
                    </p>
                  </div>
                  <div className="flex flex-wrap gap-2">
                    {canManageDocuments && pending ? (
                      <button
                        className="inline-flex min-h-10 items-center gap-2 rounded-md bg-brand-600 px-3 py-2 text-sm font-semibold text-white"
                        onClick={() => void approve(document)}
                        type="button"
                      >
                        <Check className="h-4 w-4" />
                        Approve
                      </button>
                    ) : null}
                    {active ? (
                      <>
                        <button
                          className="inline-flex min-h-10 items-center gap-2 rounded-md border border-theme-border px-3 py-2 text-sm font-semibold text-theme-text-secondary"
                          onClick={() => void preview(document)}
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
                <div className="mt-4 grid gap-2 text-sm text-theme-text-secondary">
                  {document.versions.map((version) => (
                    <div className="flex items-center justify-between gap-3" key={version.id}>
                      <span>
                        v{version.version} - {version.original_name}
                      </span>
                      <button
                        className="text-sm font-semibold text-brand-600"
                        onClick={() => void download(document, version.id)}
                        type="button"
                      >
                        {version.status}
                      </button>
                    </div>
                  ))}
                </div>
              </article>
            );
          })}
        </div>
      )}

      {previewUrl ? (
        <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/60">
          <div className="relative max-h-[90vh] w-full max-w-4xl rounded-lg bg-theme-card shadow-xl">
            <div className="flex items-center justify-between border-b border-theme-border px-4 py-3">
              <h3 className="text-sm font-semibold text-theme-text-primary truncate">
                {previewTitle}
              </h3>
              <button
                aria-label="Close preview"
                className="rounded-md p-1 text-theme-text-muted hover:bg-theme-card-elevated"
                onClick={() => {
                  setPreviewUrl(null);
                  setPreviewTitle('');
                }}
                type="button"
              >
                <X className="h-5 w-5" />
              </button>
            </div>
            <iframe className="h-[80vh] w-full" src={previewUrl} title={previewTitle} />
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
    <div className={`flex items-center gap-2 rounded-md px-3 py-2 text-sm ${cls}`}>
      <Icon className="h-4 w-4" />
      <span>{message}</span>
    </div>
  );
}
