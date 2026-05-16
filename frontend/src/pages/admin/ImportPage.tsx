import { useState } from 'react';
import { Download, Upload } from 'lucide-react';

import {
  downloadTemplate,
  getImportBatchStatus,
  importTemplates,
  previewImport,
  runImportAsync,
  runImport,
  type ImportPreview,
  type ImportRunResult
} from '../../api/imports';
import { StatusBadge } from '../../components/shared/StatusBadge';

export function ImportPage() {
  const [template, setTemplate] = useState(importTemplates[0]);
  const [file, setFile] = useState<File | null>(null);
  const [preview, setPreview] = useState<ImportPreview | null>(null);
  const [result, setResult] = useState<ImportRunResult | null>(null);
  const [batchId, setBatchId] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);

  async function previewSelected() {
    if (!file) return;
    setError(null);
    setResult(null);
    try {
      setPreview(await previewImport(template, file));
    } catch {
      setError('Unable to validate import file.');
    }
  }

  async function runSelected() {
    if (!file || !preview?.valid) return;
    setError(null);
    try {
      setResult(await runImport(template, file));
    } catch {
      setError('Unable to run import.');
    }
  }

  async function runAsyncSelected() {
    if (!file || !preview?.valid) return;
    setError(null);
    setResult(null);
    try {
      const queued = await runImportAsync(template, file);
      setBatchId(queued.batch_id);
      setResult({
        batch_id: queued.batch_id,
        template_type: queued.template_type,
        status: queued.status,
        row_count: 0,
        error_count: 0,
        summary: { task_id: queued.task_id }
      });
    } catch {
      setError('Unable to queue import.');
    }
  }

  async function refreshBatch() {
    if (!batchId) return;
    setError(null);
    try {
      setResult(await getImportBatchStatus(batchId));
    } catch {
      setError('Unable to refresh import status.');
    }
  }

  async function downloadSelectedTemplate() {
    setError(null);
    try {
      const blob = await downloadTemplate(template);
      const url = window.URL.createObjectURL(blob);
      const link = document.createElement('a');
      link.href = url;
      link.download = `${template}.csv`;
      link.click();
      window.URL.revokeObjectURL(url);
    } catch {
      setError('Unable to download import template.');
    }
  }

  return (
    <section className="space-y-6">
      <div>
        <p className="text-sm font-medium text-brand-600">Admin</p>
        <h2 className="text-2xl font-semibold text-theme-text-primary">Data Imports</h2>
      </div>

      <div className="rounded-lg border border-theme-border bg-theme-card p-4">
        <div className="grid gap-3 md:grid-cols-[220px_1fr_auto_auto]">
          <select
            className="form-field"
            onChange={(event) => {
              setTemplate(event.target.value);
              setPreview(null);
              setResult(null);
            }}
            value={template}
          >
            {importTemplates.map((name) => (
              <option key={name} value={name}>
                {name.replace('_', ' ')}
              </option>
            ))}
          </select>
          <input
            accept=".csv,.xlsx"
            className="form-field"
            onChange={(event) => setFile(event.target.files?.[0] ?? null)}
            type="file"
          />
          <button
            className="inline-flex items-center justify-center gap-2 rounded-md border border-theme-border px-3 py-2 text-sm font-semibold text-theme-text-secondary"
            onClick={() => void downloadSelectedTemplate()}
            type="button"
          >
            <Download className="h-4 w-4" />
            Template
          </button>
          <button
            className="inline-flex items-center justify-center gap-2 rounded-md bg-brand-600 px-3 py-2 text-sm font-semibold text-white"
            onClick={() => void previewSelected()}
            type="button"
          >
            <Upload className="h-4 w-4" />
            Preview
          </button>
        </div>
      </div>

      {error ? <p className="alert-error rounded-md px-3 py-2 text-sm">{error}</p> : null}

      {preview ? (
        <div className="rounded-lg border border-theme-border bg-theme-card p-4">
          <div className="flex items-center justify-between">
            <div>
              <h3 className="font-semibold text-theme-text-primary">Validation preview</h3>
              <p className="text-sm text-theme-text-muted">{preview.row_count} rows checked.</p>
            </div>
            <StatusBadge tone={preview.valid ? 'success' : 'warning'}>
              {preview.valid ? 'valid' : `${preview.errors.length} errors`}
            </StatusBadge>
          </div>
          {preview.errors.length > 0 ? (
            <div className="mt-4 divide-y divide-theme-border">
              {preview.errors.map((item) => (
                <p
                  className="py-2 text-sm text-[var(--status-error-text)]"
                  key={`${item.row}-${item.field}`}
                >
                  Row {item.row}, {item.field}: {item.message}
                </p>
              ))}
            </div>
          ) : (
            <div className="mt-4 flex flex-wrap gap-3">
              <button
                className="rounded-md bg-brand-600 px-4 py-2 text-sm font-semibold text-white"
                onClick={() => void runSelected()}
                type="button"
              >
                Run import
              </button>
              <button
                className="rounded-md border border-theme-border px-4 py-2 text-sm font-semibold text-theme-text-secondary"
                onClick={() => void runAsyncSelected()}
                type="button"
              >
                Queue async import
              </button>
            </div>
          )}
        </div>
      ) : null}

      {result ? (
        <div className="alert-success rounded-lg border border-[var(--status-success-border)] p-4 text-sm">
          <div className="flex flex-col justify-between gap-3 sm:flex-row sm:items-center">
            <span>
              Import {result.status}: {result.row_count} rows, {result.error_count} errors.
            </span>
            {batchId ? (
              <button
                className="rounded-md border border-[var(--status-success-border)] px-3 py-1.5 text-xs font-semibold"
                onClick={() => void refreshBatch()}
                type="button"
              >
                Refresh status
              </button>
            ) : null}
          </div>
        </div>
      ) : null}
    </section>
  );
}
