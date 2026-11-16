import { useMutation, useQuery } from '@tanstack/react-query';
import { useRef, useState, type FormEvent } from 'react';

import { formatApiError } from '../../api/errors';
import { listOffboardingCustody, recordOffboardingCustody, type HrSchemas } from '../../api/hr';
import { hrButtonClass, hrInputClass } from './HRAccessForms';
import { HRSeparationSettlement } from './HRSeparationSettlement';

const PAGE_SIZE = 20;
type Area = HrSchemas['OffboardingCustodyResponse']['area'];
type CustodyRequest = HrSchemas['OffboardingCustodyRequest'];

function ITCustodyForm({
  caseId,
  outstanding,
  onSaved
}: {
  caseId: string;
  outstanding: number;
  onSaved: () => Promise<void>;
}) {
  const [kind, setKind] = useState<CustodyRequest['kind']>('flagged');
  const intent = useRef<{ fields: string; id: string } | null>(null);
  const record = useMutation({
    mutationFn: (payload: CustodyRequest) => recordOffboardingCustody(caseId, payload)
  });

  function submit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (record.isPending) return;
    const form = event.currentTarget;
    const data = new FormData(form);
    const evidence_reference = String(data.get('evidence') ?? '').trim();
    const device_reference = kind === 'cleared' ? null : String(data.get('device') ?? '').trim();
    const fields = JSON.stringify([kind, device_reference, evidence_reference]);
    if (intent.current?.fields !== fields) intent.current = { fields, id: crypto.randomUUID() };
    record.mutate(
      {
        event_id: intent.current.id,
        area: 'it_admin',
        kind,
        device_reference,
        evidence_reference
      },
      {
        onSuccess: async () => {
          intent.current = null;
          form.reset();
          await onSaved();
        }
      }
    );
  }

  return (
    <form onSubmit={submit} className="space-y-2">
      <fieldset disabled={record.isPending} className="space-y-2">
        <label className="block">
          IT custody action
          <select
            className={hrInputClass}
            value={kind}
            onChange={(event) => setKind(event.target.value as CustodyRequest['kind'])}
          >
            <option value="flagged">Flag outstanding device</option>
            <option value="returned">Record returned device</option>
            <option value="waived">Record approved device exception</option>
            <option value="cleared" disabled={outstanding > 0}>
              Sign off IT handover
            </option>
          </select>
        </label>
        {kind === 'cleared' ? (
          <p>Confirm equipment is accounted for and external credentials were revoked.</p>
        ) : (
          <label className="block">
            Device reference
            <input
              name="device"
              className={hrInputClass}
              pattern="[A-Za-z0-9][A-Za-z0-9._:\-]{0,99}"
              required
            />
          </label>
        )}
        <label className="block">
          IT evidence reference
          <input
            name="evidence"
            className={hrInputClass}
            pattern="[A-Za-z0-9][A-Za-z0-9._:\-]{0,99}"
            required
          />
        </label>
        <button
          className={hrButtonClass}
          type="submit"
          disabled={kind === 'cleared' && outstanding > 0}
        >
          Record IT custody
        </button>
      </fieldset>
      {record.isError && (
        <p role="alert">{formatApiError(record.error, 'Could not save IT custody.')}</p>
      )}
    </form>
  );
}

export function HROffboardingCustody({
  area,
  caseId,
  onRefresh,
  canRecord = false
}: {
  area: Area;
  caseId: string;
  onRefresh?: () => Promise<void>;
  canRecord?: boolean;
}) {
  const [open, setOpen] = useState(canRecord);
  const [offset, setOffset] = useState(0);
  const events = useQuery({
    queryKey: ['hr', 'offboarding', caseId, 'custody', area, offset],
    queryFn: ({ signal }) => listOffboardingCustody(caseId, PAGE_SIZE, offset, area, signal),
    enabled: open,
    staleTime: 0
  });
  return (
    <details open={open} onToggle={(event) => setOpen(event.currentTarget.open)}>
      <summary>
        {area === 'it_admin' ? 'IT handover evidence' : 'Inventory custody evidence'}
      </summary>
      {open && (
        <div className="space-y-2 py-2">
          {!canRecord && (
            <p>
              {area === 'it_admin'
                ? 'Give a director this case ID to record IT handover.'
                : 'Give the inventory owner this case ID to record returns and sign off.'}
            </p>
          )}
          <p className="break-all">
            <code>{caseId}</code>
          </p>
          {events.isPending && <p role="status">Loading custody evidence…</p>}
          {events.isError && (
            <p role="alert">{formatApiError(events.error, 'Could not load custody evidence.')}</p>
          )}
          <button
            className={hrButtonClass}
            type="button"
            disabled={events.isFetching}
            onClick={() => {
              void events.refetch();
              void onRefresh?.();
            }}
          >
            Refresh custody evidence
          </button>
          {events.data && (
            <>
              <p>Current custody status {events.data.clearance_status}</p>
              {area === 'it_admin' && <p>Outstanding devices {events.data.outstanding_devices}</p>}
              {canRecord && area === 'it_admin' && !events.data.case_closed && (
                <ITCustodyForm
                  caseId={caseId}
                  outstanding={events.data.outstanding_devices}
                  onSaved={async () => {
                    await events.refetch();
                  }}
                />
              )}
              {events.data.total === 0 && <p>No custody evidence recorded.</p>}
              <ul className="space-y-1">
                {events.data.items.map((event) => (
                  <li className="break-all" key={event.id}>
                    <time dateTime={event.recorded_at}>
                      {new Date(event.recorded_at).toLocaleString()}
                    </time>
                    {' · '}
                    {event.kind}
                    {' · '}
                    {event.evidence_reference}
                    {event.device_reference && <> · Device {event.device_reference}</>}
                    {event.movement_id && <> · Stock return {event.movement_id}</>}
                  </li>
                ))}
              </ul>
              {events.data.total > PAGE_SIZE && (
                <nav aria-label="Custody evidence pages" className="flex gap-2">
                  <button
                    className={hrButtonClass}
                    type="button"
                    disabled={!offset}
                    onClick={() => setOffset(offset - PAGE_SIZE)}
                  >
                    Previous
                  </button>
                  <button
                    className={hrButtonClass}
                    type="button"
                    disabled={offset + PAGE_SIZE >= events.data.total}
                    onClick={() => setOffset(offset + PAGE_SIZE)}
                  >
                    Next
                  </button>
                </nav>
              )}
            </>
          )}
        </div>
      )}
    </details>
  );
}

export function HRDirectorOffboarding({
  actorId,
  canReviewSettlement
}: {
  actorId?: string;
  canReviewSettlement: boolean;
}) {
  const [caseId, setCaseId] = useState('');
  return (
    <section className="rounded-lg border border-theme-border bg-theme-card p-5 space-y-3">
      <section aria-label="Offboarding IT handover" className="space-y-3">
        <h3 className="font-semibold">Offboarding IT handover</h3>
        <form
          className="space-y-2"
          onSubmit={(event) => {
            event.preventDefault();
            setCaseId(String(new FormData(event.currentTarget).get('case_id')).trim());
          }}
        >
          <label className="block">
            Offboarding case ID
            <input
              name="case_id"
              className={hrInputClass}
              required
              pattern="[0-9A-Fa-f]{8}\-[0-9A-Fa-f]{4}\-[0-9A-Fa-f]{4}\-[0-9A-Fa-f]{4}\-[0-9A-Fa-f]{12}"
            />
          </label>
          <button className={hrButtonClass} type="submit">
            Open offboarding case
          </button>
        </form>
        {caseId && <HROffboardingCustody key={caseId} area="it_admin" caseId={caseId} canRecord />}
      </section>
      {caseId && canReviewSettlement && actorId && (
        <section
          aria-label="Offboarding Finance settlement"
          className="space-y-3 border-t border-theme-border pt-3"
        >
          <HRSeparationSettlement key={caseId} caseId={caseId} directorId={actorId} />
        </section>
      )}
    </section>
  );
}
