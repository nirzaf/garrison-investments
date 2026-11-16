import { useMutation, useQuery } from '@tanstack/react-query';
import { useRef, useState, type FormEvent } from 'react';

import { formatApiError } from '../../api/errors';
import {
  listSeparationSettlements,
  proposeSeparationSettlement,
  reviewSeparationSettlement,
  type HrSchemas
} from '../../api/hr';
import { hrButtonClass, hrInputClass } from './HRAccessForms';

type Proposal = HrSchemas['SeparationSettlementProposal'];
type Review = HrSchemas['SeparationSettlementReview'];
const labels = {
  outstanding: 'Obligations outstanding',
  settled: 'Settlement reconciled',
  nothing_due: 'Nothing due'
} satisfies Record<Proposal['outcome'], string>;
const pageSize = 20;
const referencePattern = '[A-Za-z0-9][A-Za-z0-9._:\\-]{0,99}';

export function HRSeparationSettlement({
  caseId,
  directorId,
  onRefresh
}: {
  caseId: string;
  directorId?: string;
  onRefresh?: () => Promise<void>;
}) {
  const [open, setOpen] = useState(false);
  const [offset, setOffset] = useState(0);
  const intent = useRef<{ fields: string; id: string } | null>(null);
  const records = useQuery({
    queryKey: ['hr', 'offboarding', caseId, 'settlement', offset],
    queryFn: ({ signal }) => listSeparationSettlements(caseId, pageSize, offset, signal),
    enabled: open
  });
  const current = records.data?.items.find((row) => row.id === records.data?.current_record_id);
  const refresh = async () => {
    await records.refetch();
    await onRefresh?.();
  };
  const propose = useMutation({
    mutationFn: (payload: Proposal) => proposeSeparationSettlement(caseId, payload),
    onSuccess: refresh
  });
  const review = useMutation({
    mutationFn: ({ id, payload }: { id: string; payload: Review }) =>
      reviewSeparationSettlement(caseId, id, payload),
    onSuccess: refresh
  });

  function submitProposal(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (propose.isPending || !records.data) return;
    const form = event.currentTarget;
    const data = new FormData(form);
    const outcome = String(data.get('outcome')) as Proposal['outcome'];
    const evidence_reference = String(data.get('evidence'));
    const expected_record_id = records.data.current_record_id;
    const fields = JSON.stringify([outcome, evidence_reference, expected_record_id]);
    if (intent.current?.fields !== fields) intent.current = { fields, id: crypto.randomUUID() };
    propose.mutate(
      { outcome, evidence_reference, expected_record_id, event_id: intent.current.id },
      {
        onSuccess: () => {
          intent.current = null;
          form.reset();
        }
      }
    );
  }

  function submitReview(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (review.isPending || !current) return;
    const form = event.currentTarget;
    const data = new FormData(form);
    review.mutate(
      {
        id: current.id,
        payload: {
          decision: String(data.get('decision')) as Review['decision'],
          evidence_reference: String(data.get('evidence'))
        }
      },
      { onSuccess: () => form.reset() }
    );
  }

  return (
    <details onToggle={(event) => setOpen(event.currentTarget.open)}>
      <summary>Finance settlement evidence</summary>
      {open && (
        <div className="space-y-2 py-2">
          {!directorId && <p>Give a director this case ID for settlement review.</p>}
          <p className="break-all">
            <code>{caseId}</code>
          </p>
          {records.isPending && <p role="status">Loading settlement evidence…</p>}
          {records.isError && (
            <p role="alert">
              {formatApiError(records.error, 'Could not load settlement evidence.')}
            </p>
          )}
          <button
            className={hrButtonClass}
            type="button"
            onClick={() => void refresh()}
            disabled={records.isFetching}
          >
            Refresh settlement evidence
          </button>
          {records.data && (
            <>
              <p>Finance clearance {records.data.clearance_status}</p>
              {records.data.total === 0 && <p>No settlement evidence recorded.</p>}
              {directorId &&
                !records.data.case_closed &&
                offset === 0 &&
                (current?.status === 'proposed' ? (
                  current.proposed_by_id === directorId ? (
                    <p>A different director must review this proposal.</p>
                  ) : (
                    <form className="space-y-2" onSubmit={submitReview}>
                      <fieldset className="space-y-2" disabled={review.isPending}>
                        <label className="block">
                          Settlement decision
                          <select required defaultValue="" className={hrInputClass} name="decision">
                            <option value="">Select a decision</option>
                            <option value="approved">Approve</option>
                            <option value="rejected">Reject</option>
                          </select>
                        </label>
                        <label className="block">
                          Settlement review reference
                          <input
                            name="evidence"
                            className={hrInputClass}
                            pattern={referencePattern}
                            required
                          />
                        </label>
                        <button className={hrButtonClass} type="submit">
                          Record settlement review
                        </button>
                      </fieldset>
                    </form>
                  )
                ) : (
                  <form className="space-y-2" onSubmit={submitProposal}>
                    <fieldset className="space-y-2" disabled={propose.isPending}>
                      <label className="block">
                        Settlement outcome
                        <select required defaultValue="" className={hrInputClass} name="outcome">
                          <option value="">Select an outcome</option>
                          {Object.entries(labels).map(([value, label]) => (
                            <option value={value} key={value}>
                              {label}
                            </option>
                          ))}
                        </select>
                      </label>
                      <label className="block">
                        Settlement evidence reference
                        <input
                          name="evidence"
                          className={hrInputClass}
                          pattern={referencePattern}
                          required
                        />
                      </label>
                      <button className={hrButtonClass} type="submit">
                        Propose settlement
                      </button>
                    </fieldset>
                  </form>
                ))}
              {(propose.isError || review.isError) && (
                <p role="alert">
                  {formatApiError(
                    propose.error ?? review.error,
                    'Could not update settlement evidence.'
                  )}
                </p>
              )}
              <ul className="space-y-1">
                {records.data.items.map((row) => (
                  <li className="break-all" key={row.id}>
                    {labels[row.outcome]} · {row.status} · {row.evidence_reference}
                    {row.review_reference && <> · Review {row.review_reference}</>}
                  </li>
                ))}
              </ul>
              {records.data.total > pageSize && (
                <nav className="flex gap-2" aria-label="Settlement evidence pages">
                  <button
                    className={hrButtonClass}
                    type="button"
                    disabled={!offset}
                    onClick={() => setOffset(offset - pageSize)}
                  >
                    Previous
                  </button>
                  <button
                    className={hrButtonClass}
                    type="button"
                    disabled={offset + pageSize >= records.data.total}
                    onClick={() => setOffset(offset + pageSize)}
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
