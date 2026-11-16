import { useQuery } from '@tanstack/react-query';
import { useRef, useState, type FormEvent } from 'react';

import { formatApiError } from '../../api/errors';
import {
  closePayrollPeriod,
  downloadPayrollExport,
  listPayrollSettlementEvents,
  previewPayrollExport,
  readPayrollSettlement,
  recordPayrollSettlement,
  registerPayrollExport,
  type PayrollSettlementRequest
} from '../../api/hr';
import { hrButtonClass, hrInputClass } from './HRAccessForms';

type Props = { runId: string; snapshotDigest: string; actorId: string; canRegister: boolean; canClose: boolean; onClosed: () => Promise<unknown> };

export function HRPayrollFinance({ runId, snapshotDigest, actorId, canRegister, canClose, onClosed }: Props) {
  const key = ['hr', 'payroll-finance', actorId, runId, snapshotDigest];
  const [open, setOpen] = useState(false);
  const [pending, setPending] = useState(false);
  const [error, setError] = useState('');
  const [notice, setNotice] = useState('');
  const [paymentReference, setPaymentReference] = useState('');
  const [offset, setOffset] = useState(0);
  const [kind, setKind] = useState<PayrollSettlementRequest['kind']>('paid');
  const saving = useRef(false);
  const attempt = useRef<{ signature: string; id: string } | null>(null);

  const preview = useQuery({
    queryKey: [...key, 'export'],
    queryFn: async ({ signal }) => {
      const value = await previewPayrollExport(runId, signal);
      if (value.run_id !== runId || value.snapshot_digest !== snapshotDigest) {
        throw new Error('The export differs from the reviewed snapshot. Reopen the snapshot.');
      }
      return value;
    },
    enabled: open,
    gcTime: 0,
    retry: false
  });
  const exportData = preview.isSuccess ? preview.data : undefined;
  const receipt = exportData?.receipt;
  const reconciliationDigest = receipt?.csv_sha256 ??
    (exportData?.payment_count === 0 ? exportData.csv_sha256 : undefined);
  const settlement = useQuery({
    queryKey: [...key, 'settlements', reconciliationDigest],
    queryFn: async ({ signal }) => {
      const value = await readPayrollSettlement(runId, signal);
      if (value.run_id !== runId || value.csv_sha256 !== reconciliationDigest) {
        throw new Error('The settlement differs from the registered export.');
      }
      return value;
    },
    enabled: open && Boolean(reconciliationDigest),
    gcTime: 0,
    retry: false
  });
  const summary = settlement.isSuccess ? settlement.data : undefined;
  const payment = summary?.payments.find((line) => line.payment_reference === paymentReference);
  const events = useQuery({
    queryKey: [...key, 'events', paymentReference, offset],
    queryFn: ({ signal }) => listPayrollSettlementEvents(runId, paymentReference, offset, signal),
    enabled: open && Boolean(payment),
    gcTime: 0,
    retry: false
  });

  async function perform(action: () => Promise<void>, message: string) {
    if (saving.current) return;
    saving.current = true;
    setPending(true);
    setError('');
    setNotice('');
    try {
      await action();
      setNotice(message);
    } catch (failure) {
      setError(formatApiError(failure, 'Unable to complete the Finance action.'));
    } finally {
      saving.current = false;
      setPending(false);
    }
  }

  function record(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (!payment || !summary || saving.current) return;
    const form = event.currentTarget;
    const fields = new FormData(form);
    const original = String(fields.get('original') ?? '').trim().toLowerCase();
    const details = {
      payment_reference: payment.payment_reference,
      expected_csv_sha256: summary.csv_sha256,
      kind,
      amount: kind === 'failed' ? '0' : String(fields.get('amount')).trim(),
      occurred_on: String(fields.get('date')),
      evidence_reference: String(fields.get('evidence')).trim(),
      reverses_event_id: kind === 'reversed' ? original : null
    } satisfies Omit<PayrollSettlementRequest, 'event_id'>;
    const signature = JSON.stringify(details);
    if (attempt.current?.signature !== signature) {
      attempt.current = { signature, id: crypto.randomUUID() };
    }
    const eventId = attempt.current.id;
    void perform(async () => {
      await recordPayrollSettlement(runId, { ...details, event_id: eventId });
      attempt.current = null;
      form.reset();
      setKind('paid');
      setOffset(0);
      await Promise.all([settlement.refetch(), events.refetch()]);
    }, 'External settlement recorded.');
  }

  function download(digest: string) {
    void perform(async () => {
      const file = await downloadPayrollExport(runId, digest);
      const url = URL.createObjectURL(file);
      try {
        const link = document.createElement('a');
        link.href = url;
        link.download = `payroll-handoff-${runId}.csv`;
        link.click();
      } finally {
        window.setTimeout(() => URL.revokeObjectURL(url), 1000);
      }
    }, 'Verified payroll handoff downloaded.');
  }

  if (!open) {
    return <button className={hrButtonClass} type="button" onClick={() => setOpen(true)}>Open Finance handoff</button>;
  }

  return (
    <section aria-label="Payroll Finance handoff" className="space-y-3 border-t border-theme-border pt-3">
      <h5 className="font-semibold">Finance handoff</h5>
      {preview.isPending && <p role="status">Loading export preview…</p>}
      {preview.isError && <p role="alert">{formatApiError(preview.error, 'Unable to preview export.')}{' '}
        <button className={hrButtonClass} type="button" onClick={() => void preview.refetch()}>Retry export preview</button>
      </p>}
      {exportData && (
        <>
          <p>Payments: {exportData.payment_count} · Zero-net lines: {exportData.zero_net_count} · {exportData.currency} {exportData.net}</p>
          <p className="break-all text-sm">CSV SHA-256 <code aria-label="Export checksum">{exportData.csv_sha256}</code></p>
          {receipt ? (
            <button className={hrButtonClass} type="button" disabled={pending}
              onClick={() => download(receipt.csv_sha256)}>Download verified payroll CSV</button>
          ) : exportData.payment_count === 0 ? (
            <p>There are no positive amounts to export.</p>
          ) : canRegister ? (
            <button className={hrButtonClass} type="button" disabled={pending} onClick={() => void perform(async () => {
              await registerPayrollExport(runId, {
                expected_snapshot_digest: snapshotDigest,
                expected_csv_sha256: exportData.csv_sha256
              });
              await preview.refetch();
            }, 'Payroll export registered.')}>Register reviewed export</button>
          ) : <p>The payroll approver must register this export before download.</p>}
        </>
      )}
      {reconciliationDigest && settlement.isPending && <p role="status">Loading reconciliation…</p>}
      {reconciliationDigest && settlement.isError && <p role="alert">{formatApiError(settlement.error, 'Unable to load reconciliation.')}{' '}
        <button className={hrButtonClass} type="button" onClick={() => void settlement.refetch()}>Retry reconciliation</button>
      </p>}
      {summary && (
        <>
          <p aria-label="Reconciliation totals">
            Expected {summary.currency} {summary.expected} · Paid {summary.currency} {summary.net_paid} · Outstanding {summary.currency} {summary.outstanding}
          </p>
          {summary.closure && <p role="status">Payroll period closed.</p>}
          {!summary.closure && canClose && summary.fully_reconciled && (
            <form className="space-y-2" onSubmit={(event) => {
              event.preventDefault();
              void perform(async () => {
                await closePayrollPeriod(runId, {
                  expected_snapshot_digest: snapshotDigest,
                  expected_csv_sha256: summary.csv_sha256,
                  expected_settlement_digest: summary.settlement_digest
                });
                await Promise.all([settlement.refetch(), onClosed()]);
              }, 'Payroll closure recorded.');
            }}>
              <label className="flex items-center gap-2">
                <input type="checkbox" required disabled={pending} /> I reviewed the final reconciliation.
              </label>
              <button className={hrButtonClass} type="submit"
                disabled={pending || settlement.isFetching}>Close payroll period</button>
            </form>
          )}
          {summary.payments.length ? (
            <label className="block">Exported payment
              <select className={hrInputClass} value={paymentReference} disabled={pending} onChange={(event) => {
                setPaymentReference(event.target.value);
                setOffset(0);
                setKind('paid');
              }}>
                <option value="">Select payment reference</option>
                {summary.payments.map((line) => (
                  <option key={line.payment_reference} value={line.payment_reference}>{line.payment_reference}</option>
                ))}
              </select>
            </label>
          ) : <p>This export has no payments to reconcile.</p>}
        </>
      )}
      {payment && (
        <>
          <p aria-label="Selected payment balance">{payment.status} · Outstanding {summary?.currency} {payment.outstanding}</p>
          {!summary?.closure && <form key={paymentReference} onSubmit={record} aria-label="Record external settlement" className="space-y-2">
            <fieldset disabled={pending} className="grid gap-2 sm:grid-cols-2">
              <label>Payment outcome
                <select className={hrInputClass} value={kind} onChange={(event) => {
                  const value = event.target.value;
                  if (value === 'paid' || value === 'failed' || value === 'reversed') setKind(value);
                }}>
                  <option value="paid">Payment confirmed</option>
                  <option value="failed">Payment failed</option>
                  <option value="reversed">Payment reversed</option>
                </select>
              </label>
              {kind !== 'failed' && <label>Settlement amount
                <input className={hrInputClass} name="amount" inputMode="decimal" required pattern="(?:0|[1-9][0-9]{0,15})(?:\.[0-9]{1,2})?" />
              </label>}
              <label>Settlement date<input className={hrInputClass} name="date" type="date" required /></label>
              <label>External evidence reference
                <input className={hrInputClass} name="evidence" required maxLength={100} />
              </label>
              {kind === 'reversed' && <label>Original payment event ID
                <input className={hrInputClass} name="original" required pattern="[0-9A-Fa-f]{8}(-[0-9A-Fa-f]{4}){3}-[0-9A-Fa-f]{12}" />
              </label>}
              <label className="flex items-center gap-2 sm:col-span-2">
                <input type="checkbox" required /> I verified this outcome in the external payment records.
              </label>
              <button className={hrButtonClass} type="submit">Record external settlement</button>
            </fieldset>
          </form>}
          <h6 className="font-semibold">Settlement history</h6>
          {events.isPending && <p role="status">Loading payment history…</p>}
          {events.isError && <p role="alert">{formatApiError(events.error, 'Unable to load payment history.')}{' '}
            <button className={hrButtonClass} type="button" onClick={() => void events.refetch()}>Retry payment history</button>
          </p>}
          {events.isSuccess && (events.data.total ? (
            <>
              <ul className="space-y-1 break-all text-sm">
                {events.data.items.map((item) => (
                  <li key={item.id}>{item.occurred_on} · {item.kind} · {item.amount} · {item.evidence_reference} · Event <code>{item.id}</code></li>
                ))}
              </ul>
              <div className="flex gap-2">
                <button className={hrButtonClass} type="button" disabled={!offset || pending} onClick={() => setOffset(offset - 20)}>Previous events</button>
                <button className={hrButtonClass} type="button" disabled={offset + 20 >= events.data.total || pending} onClick={() => setOffset(offset + 20)}>Next events</button>
              </div>
            </>
          ) : <p>No external settlements recorded.</p>)}
        </>
      )}
      {notice && <p role="status">{notice}</p>}
      {error && <p role="alert">{error}</p>}
    </section>
  );
}
