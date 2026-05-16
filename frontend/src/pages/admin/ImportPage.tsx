import { useState } from 'react';
import { Download, Upload } from 'lucide-react';

import {
  importTemplates,
  previewImport,
  runImport,
  templateUrl,
  type ImportPreview,
  type ImportRunResult
} from '../../api/imports';
import { StatusBadge } from '../../components/shared/StatusBadge';

export function ImportPage() {
  const [template, setTemplate] = useState(importTemplates[0]);
  const [file, setFile] = useState<File | null>(null);
  const [preview, setPreview] = useState<ImportPreview | null>(null);
  const [result, setResult] = useState<ImportRunResult | null>(null);
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

  return (
    <section className="space-y-6">
      <div>
        <p className="text-sm font-medium text-brand-700">Admin</p>
        <h2 className="text-2xl font-semibold text-slate-950">Data Imports</h2>
      </div>

      <div className="rounded-lg border border-slate-200 bg-white p-4">
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
            accept=".csv"
            className="form-field"
            onChange={(event) => setFile(event.target.files?.[0] ?? null)}
            type="file"
          />
          <a
            className="inline-flex items-center justify-center gap-2 rounded-md border border-slate-300 px-3 py-2 text-sm font-semibold text-slate-700"
            href={templateUrl(template)}
          >
            <Download className="h-4 w-4" />
            Template
          </a>
          <button
            className="inline-flex items-center justify-center gap-2 rounded-md bg-brand-700 px-3 py-2 text-sm font-semibold text-white"
            onClick={() => void previewSelected()}
            type="button"
          >
            <Upload className="h-4 w-4" />
            Preview
          </button>
        </div>
      </div>

      {error ? (
        <p className="rounded-md bg-red-50 px-3 py-2 text-sm text-red-700">{error}</p>
      ) : null}

      {preview ? (
        <div className="rounded-lg border border-slate-200 bg-white p-4">
          <div className="flex items-center justify-between">
            <div>
              <h3 className="font-semibold text-slate-950">Validation preview</h3>
              <p className="text-sm text-slate-500">{preview.row_count} rows checked.</p>
            </div>
            <StatusBadge tone={preview.valid ? 'success' : 'warning'}>
              {preview.valid ? 'valid' : `${preview.errors.length} errors`}
            </StatusBadge>
          </div>
          {preview.errors.length > 0 ? (
            <div className="mt-4 divide-y divide-slate-100">
              {preview.errors.map((item) => (
                <p className="py-2 text-sm text-red-700" key={`${item.row}-${item.field}`}>
                  Row {item.row}, {item.field}: {item.message}
                </p>
              ))}
            </div>
          ) : (
            <button
              className="mt-4 rounded-md bg-brand-700 px-4 py-2 text-sm font-semibold text-white"
              onClick={() => void runSelected()}
              type="button"
            >
              Run import
            </button>
          )}
        </div>
      ) : null}

      {result ? (
        <div className="rounded-lg border border-emerald-200 bg-emerald-50 p-4 text-sm text-emerald-900">
          Import {result.status}: {result.row_count} rows, {result.error_count} errors.
        </div>
      ) : null}
    </section>
  );
}
