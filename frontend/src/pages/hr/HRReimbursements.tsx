import { useQuery, useQueryClient } from '@tanstack/react-query';
import { useRef, useState, type FormEvent } from 'react';

import { formatApiError } from '../../api/errors';
import {
  decideHrDocumentVersion, decideReimbursement, getHrDocument, getHrDocumentDownloadUrl,
  getReimbursementPayable, listEmployeeCappedCoverage, listHrDocuments, listReimbursements,
  submitReimbursement, uploadHrDocument, type HrDocumentRecord, type ReimbursementClaim,
  type ReimbursementPayable
} from '../../api/hr';
import { hrButtonClass, hrInputClass } from './HRAccessForms';

type Props = {
  employeeId: string; employeeUserId?: string | null; actorId: string; canReview: boolean;
  canManageReceipts: boolean; canReviewReceipts: boolean;
};
type Evidence = { documentId: string; version: number; versionId: string; url: string };
const amountPattern = '[0-9]{1,13}(\\.[0-9]{1,2})?';
const pageSize = 20;

export function HRReimbursements(props: Props) {
  const [open, setOpen] = useState(false);
  return (
    <details className="rounded border border-theme-border p-3"
      onToggle={(event) => setOpen(event.currentTarget.open)}>
      <summary className="cursor-pointer font-semibold">Reimbursements</summary>
      {open && <ReimbursementPanel {...props} />}
    </details>
  );
}

function ReimbursementPanel({ employeeId, employeeUserId, actorId, canReview, canManageReceipts, canReviewReceipts }: Props) {
  const client = useQueryClient();
  const [offset, setOffset] = useState(0);
  const [receiptOffset, setReceiptOffset] = useState(0);
  const [selected, setSelected] = useState('');
  const [assignmentId, setAssignmentId] = useState('');
  const [receiptId, setReceiptId] = useState('');
  const [receiptPreview, setReceiptPreview] = useState<Evidence | null>(null);
  const [claimPreview, setClaimPreview] = useState<Evidence | null>(null);
  const [payable, setPayable] = useState<ReimbursementPayable | null>(null);
  const [pending, setPending] = useState(false);
  const [error, setError] = useState('');
  const [notice, setNotice] = useState('');
  const busy = useRef(false);
  const intent = useRef<{ body: string; key: string } | null>(null);
  const key = ['hr', 'reimbursements', actorId, employeeId];
  const history = useQuery({
    queryKey: [...key, 'history', offset],
    queryFn: ({ signal }) => listReimbursements(employeeId, offset, signal), gcTime: 0, retry: false
  });
  const coverage = useQuery({
    queryKey: [...key, 'coverage'], gcTime: 0, retry: false,
    queryFn: ({ signal }) => listEmployeeCappedCoverage(employeeId, signal)
  });
  const receipts = useQuery({
    queryKey: [...key, 'receipts', receiptOffset], gcTime: 0, retry: false,
    queryFn: ({ signal }) => listHrDocuments({
      employee_id: employeeId, category: 'compensation', document_type: 'reimbursement_receipt',
      limit: pageSize, offset: receiptOffset
    }, signal),
    enabled: canManageReceipts
  });
  const documents = receipts.data?.items.filter((item) => item.employee_id === employeeId) ?? [];
  const activeReceipts = documents.filter((item) =>
    item.status === 'active' && item.versions?.some((v) => v.version_number === item.current_version && v.status === 'active')
  );
  const receipt = activeReceipts.find((item) => item.id === receiptId);
  const assignment = coverage.data?.find((item) => item.id === assignmentId);
  const claim = history.data?.items.find((item) => item.id === selected && item.employee_id === employeeId);

  async function action(work: () => Promise<void>, message?: string) {
    if (busy.current) return;
    busy.current = true;
    setPending(true);
    setError('');
    setNotice('');
    try {
      await work();
      if (message) setNotice(message);
    } catch (err) {
      setError(formatApiError(err, 'Unable to complete this reimbursement action.'));
    } finally {
      busy.current = false;
      setPending(false);
    }
  }

  function upload(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    const form = event.currentTarget;
    const fields = new FormData(form);
    const file = fields.get('file');
    if (!(file instanceof File) || !file.size) return;
    void action(async () => {
      await uploadHrDocument({
        file, title: String(fields.get('title')).trim(), category: 'compensation',
        document_type: 'reimbursement_receipt', employee_id: employeeId, is_employee_visible: false
      });
      form.reset();
      setReceiptOffset(0);
      await client.invalidateQueries({ queryKey: [...key, 'receipts'] });
    }, 'Receipt uploaded for independent review.');
  }

  async function evidence(doc: HrDocumentRecord, versionId: string): Promise<Evidence> {
    const version = doc.versions?.find((item) => item.id === versionId);
    if (!version || doc.employee_id !== employeeId) throw new Error('Receipt version is unavailable');
    const result = await getHrDocumentDownloadUrl(doc.id, version.version_number);
    if (result.document_id !== doc.id || result.version_number !== version.version_number) {
      throw new Error('Unexpected receipt version');
    }
    const link = new URL(result.download_url);
    if (!['http:', 'https:'].includes(link.protocol)) throw new Error('Invalid receipt URL');
    return { documentId: doc.id, versionId, version: version.version_number, url: link.href };
  }

  function submit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (!receipt || !assignment) return;
    const form = event.currentTarget;
    const fields = new FormData(form);
    const payload = {
      employee_id: employeeId, benefit_assignment_id: assignment.id, claim_type: assignment.code,
      claim_date: String(fields.get('date')), amount: String(fields.get('amount')), currency: assignment.currency,
      description: String(fields.get('description')).trim(), receipt_document_id: receipt.id,
      receipt_version_number: receipt.current_version
    };
    const body = JSON.stringify(payload);
    if (intent.current?.body !== body) intent.current = { body, key: crypto.randomUUID() };
    const idempotencyKey = intent.current.key;
    void action(async () => {
      const saved = await submitReimbursement(payload, idempotencyKey);
      if (saved.employee_id !== employeeId) throw new Error('Unexpected employee');
      intent.current = null;
      form.reset();
      setReceiptId('');
      setAssignmentId('');
      setOffset(0);
      setSelected(saved.id);
      setClaimPreview(null);
      setPayable(null);
      await client.invalidateQueries({ queryKey: [...key, 'history'] });
    }, 'Reimbursement submitted.');
  }

  function decide(current: ReimbursementClaim, decision: 'approved' | 'rejected' | 'cancelled', notes?: string) {
    void action(async () => {
      await decideReimbursement(current.id, { decision, notes });
      setClaimPreview(null);
      await history.refetch();
    }, `Reimbursement ${decision}.`);
  }

  function settle(event: FormEvent<HTMLFormElement>, current: ReimbursementClaim) {
    event.preventDefault();
    if (!payable || payable.reference.claim_id !== current.id || payable.status !== 'approved') return;
    const fields = new FormData(event.currentTarget);
    void action(async () => {
      await decideReimbursement(current.id, {
        decision: 'paid', expected_payable_sha256: payable.reference_sha256,
        settled_amount: String(fields.get('amount')), settled_currency: String(fields.get('currency')).toUpperCase(),
        settlement_reference: String(fields.get('reference')).trim()
      });
      setPayable(null);
      await history.refetch();
    }, 'External settlement confirmed.');
  }

  const independent = Boolean(canReview && claim?.submitted_by_id &&
    claim.submitted_by_id !== actorId && employeeUserId !== actorId);
  const pinned = claimPreview?.versionId === claim?.receipt_version_id && Boolean(claimPreview);
  const problem = history.error ?? coverage.error ?? receipts.error;
  const openClaim = (id: string) => { setSelected(id); setClaimPreview(null); setPayable(null); setError(''); setNotice(''); };

  return (
    <section className="mt-3 space-y-3" aria-label="Reimbursement records">
      {error && <p role="alert">{error}</p>}
      {notice && <p role="status">{notice}</p>}
      {problem && <p role="alert">{formatApiError(problem, 'Unable to load reimbursement records.')}</p>}
      <button className={hrButtonClass} disabled={pending} type="button" onClick={() => {
        void history.refetch(); void coverage.refetch(); if (canManageReceipts) void receipts.refetch();
      }}>Refresh reimbursements</button>
      {history.isPending && <p role="status">Loading reimbursement claims…</p>}
      {history.data?.total === 0 && <p>No reimbursement claims recorded.</p>}
      <ul className="space-y-1" aria-label="Claims">
        {history.data?.items.map((item) => (
          <li key={item.id} className="flex justify-between gap-2">
            <span>{item.claim_code} · {item.claim_date} · {item.status}</span>
            <button type="button" className={hrButtonClass} disabled={pending} onClick={() => openClaim(item.id)}>Open claim</button>
          </li>
        ))}
      </ul>
      <Pages label="claims" offset={offset} total={history.data?.total ?? 0} change={(next) => { setOffset(next); openClaim(''); }} disabled={pending} />
      {claim && (
        <article key={claim.id} aria-label="Claim details" className="space-y-2 rounded border border-theme-border p-3">
          <h4 className="font-semibold">{claim.claim_code}</h4>
          <p>{claim.status} · {claim.currency} {claim.amount}</p><p>{claim.description}</p>
          {claim.settlement_reference && <p className="break-all">Settlement reference {claim.settlement_reference}</p>}
          {canManageReceipts && claim.receipt_document_id && claim.receipt_version_id && (
            <button className={hrButtonClass} type="button" disabled={pending} onClick={() => void action(async () => {
              const doc = await getHrDocument(claim.receipt_document_id!);
              setClaimPreview(await evidence(doc, claim.receipt_version_id!));
            })}>Prepare pinned receipt link</button>
          )}
          {pinned && <a className="underline" href={claimPreview?.url} target="_blank" rel="noreferrer">Open pinned receipt</a>}
          {independent && claim.status === 'submitted' && (
            <form className="space-y-2" onSubmit={(event) => {
              event.preventDefault();
              const decision = (event.nativeEvent as SubmitEvent).submitter?.getAttribute('value');
              const notes = String(new FormData(event.currentTarget).get('notes')).trim();
              if (decision === 'rejected' || decision === 'cancelled') {
                if (!notes) { setError('Enter the reason for this decision.'); return; }
                decide(claim, decision, notes);
              }
            }}>
              <label className="block">Claim decision reason<textarea name="notes" className={hrInputClass} maxLength={1000} /></label>
              <div className="flex flex-wrap gap-2">
                <button className={hrButtonClass} type="button" disabled={pending || !pinned} onClick={() => decide(claim, 'approved')}>Approve reimbursement</button>
                <button className={hrButtonClass} type="submit" value="rejected" disabled={pending}>Reject reimbursement</button>
                <button className={hrButtonClass} type="submit" value="cancelled" disabled={pending}>Cancel reimbursement</button>
              </div>
            </form>
          )}
          {claim.status === 'approved' && (
            <button className={hrButtonClass} type="button" disabled={pending} onClick={() => void action(async () => {
              const reviewed = await getReimbursementPayable(claim.id);
              if (reviewed.reference.employee_id !== employeeId || reviewed.reference.claim_id !== claim.id ||
                reviewed.status !== 'approved') throw new Error('Payable is unavailable');
              setPayable(reviewed);
            })}>Review payable</button>
          )}
          {payable?.reference.claim_id === claim.id && claim.status === 'approved' && (
            <>
              <p>Approved payable {payable.reference.currency} {payable.reference.amount}</p>
              <button className={hrButtonClass} type="button" onClick={() => downloadPayable(payable)}>Download reimbursement payable</button>
              {independent && claim.decided_by_id && claim.decided_by_id !== actorId && (
                <form onSubmit={(event) => settle(event, claim)} className="space-y-2">
                  <fieldset disabled={pending} className="grid gap-2 sm:grid-cols-2">
                    <label>External settlement reference<input name="reference" className={hrInputClass} maxLength={100} required /></label>
                    <label>Actual settled amount<input name="amount" className={hrInputClass} inputMode="decimal" pattern={amountPattern} required /></label>
                    <label>Actual settled currency<input name="currency" className={hrInputClass} pattern="[A-Za-z]{3}" required /></label>
                  </fieldset>
                  <button className={hrButtonClass} type="submit" disabled={pending}>Confirm external settlement</button>
                </form>
              )}
            </>
          )}
        </article>
      )}
      {canManageReceipts && (
        <div className="space-y-2 border-t border-theme-border pt-3">
          <h4 className="font-semibold">Private receipts</h4>
          <form onSubmit={upload} className="space-y-2">
            <fieldset disabled={pending} className="grid gap-2 sm:grid-cols-2">
              <label>Receipt title<input name="title" className={hrInputClass} maxLength={255} required /></label>
              <label>Receipt file<input type="file" name="file" className={hrInputClass} accept=".pdf,.png,.jpg,.jpeg" required /></label>
            </fieldset>
            <button className={hrButtonClass} type="submit" disabled={pending}>Upload private receipt</button>
          </form>
          {documents.map((doc) => {
            const version = doc.versions?.find((item) => item.status === 'pending');
            if (!version) return null;
            const prepared = receiptPreview?.versionId === version.id ? receiptPreview : null;
            return (
              <div key={doc.id} className="space-y-1">
                <p>{doc.title} · Pending receipt review</p>
                {canReviewReceipts && version.uploaded_by_id !== actorId && (
                  <div className="flex flex-wrap gap-2">
                    <button type="button" className={hrButtonClass} disabled={pending}
                      onClick={() => void action(async () => { setReceiptPreview(await evidence(doc, version.id)); })}>
                      Prepare receipt review link
                    </button>
                    {prepared && (
                      <>
                        <a className="underline" href={prepared.url} target="_blank" rel="noreferrer">Open receipt for review</a>
                        <button type="button" className={hrButtonClass} disabled={pending} onClick={() => void action(async () => {
                          await decideHrDocumentVersion(doc.id, version.version_number, { decision: 'approve' });
                          setReceiptPreview(null);
                          await receipts.refetch();
                        }, 'Receipt approved.')}>Approve receipt</button>
                      </>
                    )}
                  </div>
                )}
              </div>
            );
          })}
          <Pages label="receipts" offset={receiptOffset} total={receipts.data?.total ?? 0} disabled={pending}
            change={(next) => { setReceiptOffset(next); setReceiptId(''); setReceiptPreview(null); }} />
        </div>
      )}
      {coverage.data?.length === 0 && <p>No approved reimbursement coverage for this employee.</p>}
      {coverage.data && coverage.data.length > 0 && canManageReceipts && (
        <form onSubmit={submit} className="space-y-2 border-t border-theme-border pt-3">
          <h4 className="font-semibold">Submit a reimbursement</h4>
          <fieldset disabled={pending} className="grid gap-2 sm:grid-cols-2">
            <label>Reimbursement coverage
              <select className={hrInputClass} value={assignmentId} onChange={(e) => setAssignmentId(e.target.value)} required>
                <option value="">Select coverage</option>
                {coverage.data.map((item) => <option key={item.id} value={item.id}>{item.name} · {item.from} to {item.to}</option>)}
              </select>
            </label>
            <label>Approved receipt
              <select className={hrInputClass} value={receiptId} onChange={(e) => setReceiptId(e.target.value)} required>
                <option value="">Select receipt</option>
                {activeReceipts.map((item) => <option key={item.id} value={item.id}>{item.title} · v{item.current_version}</option>)}
              </select>
            </label>
            <label>Expense date<input type="date" name="date" className={hrInputClass} min={assignment?.from} max={assignment?.to} required /></label>
            <label>Claim amount{assignment && ` (${assignment.currency})`}<input name="amount" className={hrInputClass} inputMode="decimal" pattern={amountPattern} required /></label>
            <label className="sm:col-span-2">Claim description<textarea name="description" className={hrInputClass} minLength={2} maxLength={2000} required /></label>
          </fieldset>
          <button className={hrButtonClass} type="submit" disabled={pending || !receipt || !assignment}>Submit reimbursement</button>
        </form>
      )}
    </section>
  );
}

function Pages({ label, offset, total, change, disabled }: {
  label: string; offset: number; total: number; change: (offset: number) => void; disabled: boolean
}) {
  if (total <= pageSize) return null;
  return (
    <div className="flex gap-2">
      <button className={hrButtonClass} type="button" disabled={disabled || offset === 0}
        onClick={() => change(offset - pageSize)}>Previous {label}</button>
      <button className={hrButtonClass} type="button" disabled={disabled || offset + pageSize >= total}
        onClick={() => change(offset + pageSize)}>Next {label}</button>
    </div>
  );
}

function downloadPayable(payable: ReimbursementPayable) {
  const url = URL.createObjectURL(new Blob([JSON.stringify(payable, null, 2) + '\n'], { type: 'application/json' }));
  const link = document.createElement('a');
  link.href = url;
  link.download = `reimbursement-${payable.reference.claim_id}.json`;
  try { link.click(); } finally { window.setTimeout(() => URL.revokeObjectURL(url), 0); }
}
