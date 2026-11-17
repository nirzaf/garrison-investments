import { useEffect, useRef, useState, type FormEvent } from 'react';

import type { components } from '../../api/schema';
import { supportPasskey, supportPost } from '../../api/support';

type Receipt = components['schemas']['SupportEvidenceExportRead'];
type ProofOptions = components['schemas']['SupportEvidenceProofOptions'];
type Stage = 'review' | 'download';
type Prepared = { stage: Stage; options: ProofOptions; path: string };

function ExportReceipt({ item }: { item: Receipt }) {
  return (
    <dl className="space-y-1 break-all">
      <dt>Export reference</dt><dd>{item.id}</dd>
      <dt>Case reference</dt><dd>{item.case_id}</dd>
      <dt>Linked request</dt><dd>{item.filters.request_id}</dd>
      <dt>UTC window</dt><dd>{item.filters.started_at} to {item.filters.ended_at}</dd>
      <dt>Purpose</dt><dd>{item.reason === 'audit_review' ? 'Audit review' : 'Incident review'}</dd>
      <dt>Status filter</dt><dd>{item.filters.status_code ?? 'All projected statuses'}</dd>
      <dt>Row limit</dt><dd>{item.filters.limit}</dd>
      <dt>Included events</dt><dd>{item.row_count}{item.truncated && ' · Truncated'}</dd>
      <dt>Review expires</dt><dd>{item.expires_at}</dd>
      <dt>SHA-256</dt><dd>{item.sha256}</dd>
    </dl>
  );
}

async function saveExport(response: Response, receipt: Receipt, signal: AbortSignal) {
  const maxSize = 10 * 1024 * 1024;
  if (response.headers.get('content-type')?.split(';')[0] !== 'text/csv'
    || response.headers.get('X-Support-Export-Sha256') !== receipt.sha256
    || Number(response.headers.get('Content-Length')) > maxSize) throw new Error();
  const blob = await response.blob();
  if (blob.size > maxSize) throw new Error();
  const digest = await crypto.subtle.digest('SHA-256', await blob.arrayBuffer());
  const actual = Array.from(new Uint8Array(digest), (byte) => byte.toString(16).padStart(2, '0')).join('');
  if (actual !== receipt.sha256) throw new Error();
  if (signal.aborted) return;
  const url = URL.createObjectURL(blob);
  try {
    const link = document.createElement('a');
    link.href = url;
    link.download = `support-evidence-${receipt.id}.csv`;
    link.click();
  } finally {
    window.setTimeout(() => URL.revokeObjectURL(url), 0);
  }
}

export function SupportEvidenceExportPanel({ onExpired }: { onExpired: () => void }) {
  const active = useRef<AbortController | null>(null);
  const [pending, setPending] = useState(false);
  const [receipt, setReceipt] = useState<Receipt | null>(null);
  const [prepared, setPrepared] = useState<Prepared | null>(null);
  const [notice, setNotice] = useState('');
  const [error, setError] = useState('');

  useEffect(() => () => active.current?.abort(), []);

  async function run(operation: (signal: AbortSignal) => Promise<void>) {
    if (active.current) return;
    const controller = new AbortController();
    active.current = controller;
    setPending(true);
    setError('');
    setNotice('');
    try {
      await operation(controller.signal);
    } catch {
      if (!controller.signal.aborted) setError('The evidence operation could not be completed.');
    } finally {
      if (!controller.signal.aborted) {
        active.current = null;
        setPending(false);
      }
    }
  }

  function accepted(response: Response) {
    if (response.status === 401) onExpired();
    else if (response.status === 409) setError('This export is unavailable. Check its approval or request a new review.');
    else if (!response.ok) setError('The evidence operation was denied or is unavailable.');
    return response.ok;
  }

  async function propose(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    const fields = new FormData(event.currentTarget);
    const caseId = encodeURIComponent(String(fields.get('case_id')).trim());
    const now = Date.now();
    await run(async (signal) => {
      setPrepared(null);
      setReceipt(null);
      const response = await supportPost(`/cases/${caseId}/exports`, {
        filters: {
          request_id: String(fields.get('request_id')).trim(),
          started_at: new Date(now - Number(fields.get('hours')) * 3600_000).toISOString(),
          ended_at: new Date(now).toISOString()
        },
        reason: fields.get('reason')
      }, { signal });
      if (!accepted(response) || signal.aborted) return;
      setReceipt(await response.json() as Receipt);
      setNotice('Export requested. Provide its reference to an independent case reviewer.');
    });
  }

  async function inspect(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    const fields = new FormData(event.currentTarget);
    const stage: Stage = fields.get('stage') === 'download' ? 'download' : 'review';
    const caseId = encodeURIComponent(String(fields.get('case_id')).trim());
    const exportId = encodeURIComponent(String(fields.get('export_id')).trim());
    const path = `/cases/${caseId}/exports/${exportId}/${stage}`;
    await run(async (signal) => {
      setPrepared(null);
      setReceipt(null);
      const response = await supportPost(path + '/options', {}, { signal });
      if (!accepted(response) || signal.aborted) return;
      const options = await response.json() as ProofOptions;
      setPrepared({ stage, path, options });
      setReceipt(options.export);
    });
  }

  async function decide() {
    if (!prepared) return;
    await run(async (signal) => {
      const { stage, options, path } = prepared;
      const proof = await supportPasskey(options);
      if (signal.aborted) return;
      const response = await supportPost(path, { ...proof, expected_sha256: options.export.sha256 }, { signal });
      setPrepared(null);
      if (!accepted(response) || signal.aborted) return;
      if (stage === 'review') {
        setReceipt(await response.json() as Receipt);
        setNotice('Independent approval recorded.');
      } else {
        try {
          await saveExport(response, options.export, signal);
          if (!signal.aborted) setNotice('Evidence file verified. The one-use download has been consumed.');
        } catch {
          if (!signal.aborted) setError('The download was consumed, but the file could not be verified or saved.');
        }
      }
    });
  }

  function clearPrepared() {
    setPrepared(null);
    setReceipt(null);
    setNotice('');
    setError('');
  }

  return (
    <section aria-label="Evidence export" className="space-y-3 border-t pt-3">
      <h2 className="font-semibold">Evidence export</h2>
      <form className="space-y-2" onSubmit={(event) => void propose(event)} onChange={clearPrepared}>
        <fieldset disabled={pending} className="space-y-2">
          <legend>Request an export</legend>
          <label className="block">Export case reference
            <input name="case_id" maxLength={36} required className="block w-full rounded border p-2" />
          </label>
          <label className="block">Linked request ID
            <input name="request_id" maxLength={36} required className="block w-full rounded border p-2" />
          </label>
          <label className="block">Export window
            <select name="hours" defaultValue="24" className="block rounded border p-2">
              <option value="1">Last hour</option><option value="24">Last 24 hours</option>
              <option value="168">Last 7 days</option>
            </select>
          </label>
          <label className="block">Export purpose
            <select name="reason" className="block rounded border p-2">
              <option value="incident_review">Incident review</option><option value="audit_review">Audit review</option>
            </select>
          </label>
          <button type="submit">Request evidence export</button>
        </fieldset>
      </form>
      <form className="space-y-2" onSubmit={(event) => void inspect(event)} onChange={clearPrepared}>
        <fieldset disabled={pending} className="space-y-2">
          <legend>Review or download an export</legend>
          <label className="block">Reviewed case reference
            <input name="case_id" maxLength={36} required className="block w-full rounded border p-2" />
          </label>
          <label className="block">Existing export reference
            <input name="export_id" maxLength={36} required className="block w-full rounded border p-2" />
          </label>
          <label className="block">Export action
            <select name="stage" className="block rounded border p-2">
              <option value="review">Review</option><option value="download">Download once</option>
            </select>
          </label>
          <button type="submit">Show export details</button>
        </fieldset>
      </form>
      {receipt && <ExportReceipt item={receipt} />}
      {prepared && (
        <button type="button" disabled={pending} onClick={() => void decide()}>
          {prepared.stage === 'review' ? 'Approve export with passkey' : 'Download once with passkey'}
        </button>
      )}
      {pending && <p role="status">Checking evidence export…</p>}
      {notice && <p role="status">{notice}</p>}
      {error && <p role="alert">{error}</p>}
    </section>
  );
}
