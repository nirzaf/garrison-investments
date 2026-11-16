import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import { useState } from 'react';

import { formatApiError } from '../../api/errors';
import {
  decideCandidateCorrespondence,
  draftCandidateCorrespondence,
  getCandidateCorrespondence,
  listCandidateCorrespondence,
  listCandidateRejectionTemplates,
  updateApplicationStage,
  type ApplicationRecord,
  type HrSchemas
} from '../../api/hr';
import { hrButtonClass, hrInputClass } from './HRAccessForms';

const pageSize = 20;

function Correspondence({ id }: { id: string }) {
  const client = useQueryClient();
  const [opened, setOpened] = useState(false);
  const [template, setTemplate] = useState('');
  const [draftId, setDraftId] = useState(() => crypto.randomUUID());
  const [offset, setOffset] = useState(0);
  const [selected, setSelected] = useState('');
  const [reason, setReason] = useState('');
  const prefix = ['hr', 'candidate-correspondence', id];
  const templates = useQuery({
    queryKey: ['hr', 'letter-templates', 'candidate'],
    queryFn: listCandidateRejectionTemplates,
    enabled: opened
  });
  const history = useQuery({
    queryKey: [...prefix, 'list', offset],
    queryFn: () => listCandidateCorrespondence(id, offset, pageSize),
    enabled: opened
  });
  const detailKey = [...prefix, 'detail', selected];
  const detail = useQuery({
    queryKey: detailKey,
    queryFn: () => getCandidateCorrespondence(id, selected),
    enabled: opened && Boolean(selected)
  });
  const draft = useMutation({
    mutationFn: () =>
      draftCandidateCorrespondence(id, { draft_id: draftId, template_id: template }),
    onSuccess: async (row) => {
      setOffset(0);
      setSelected(row.id);
      setDraftId(crypto.randomUUID());
      client.setQueryData([...prefix, 'detail', row.id], row);
      await client.invalidateQueries({ queryKey: [...prefix, 'list'] });
    }
  });
  const decide = useMutation({
    mutationFn: (payload: HrSchemas['CandidateCorrespondenceDecisionRequest']) =>
      decideCandidateCorrespondence(id, selected, payload),
    onSuccess: async (row) => {
      setReason('');
      client.setQueryData([...prefix, 'detail', row.id], row);
      await client.invalidateQueries({ queryKey: [...prefix, 'list'] });
    }
  });
  const busy = draft.isPending || decide.isPending;
  const activeTemplates = templates.data?.items.filter((row) => row.is_active) ?? [];
  const record = detail.data;

  return (
    <details className="mt-2 space-y-2" onToggle={(event) => setOpened(event.currentTarget.open)}>
      <summary>Candidate correspondence</summary>
      {opened && (
        <>
          <p>Prepare the rejection letter for independent review and manual handoff.</p>
          <form
            className="flex flex-wrap items-end gap-2"
            onSubmit={(event) => {
              event.preventDefault();
              if (!busy && template) draft.mutate();
            }}
          >
            <label>
              Candidate rejection template
              <select
                required
                className={hrInputClass}
                disabled={busy}
                value={template}
                onChange={(event) => {
                  setTemplate(event.target.value);
                  setDraftId(crypto.randomUUID());
                  draft.reset();
                }}
              >
                <option value="">Choose a template</option>
                {activeTemplates.map((row) => (
                  <option key={row.id} value={row.id}>
                    {row.name}
                  </option>
                ))}
              </select>
            </label>
            <button type="submit" className={hrButtonClass} disabled={busy || !template}>
              Draft candidate correspondence
            </button>
          </form>
          {templates.isPending && <p role="status">Loading candidate templates…</p>}
          {templates.isSuccess && activeTemplates.length === 0 && (
            <p>Create a candidate rejection template in Letters.</p>
          )}
          {history.isPending && <p role="status">Loading correspondence…</p>}
          {history.isSuccess && history.data.total === 0 && (
            <p>No correspondence has been prepared.</p>
          )}
          {history.data?.items.map((row) => (
            <button
              key={row.id}
              type="button"
              className={hrButtonClass}
              disabled={busy}
              onClick={() => {
                setSelected(row.id);
                setReason('');
                decide.reset();
              }}
            >
              Open {row.template_name} · {row.status}
            </button>
          ))}
          {offset + pageSize < (history.data?.total ?? 0) && (
            <button
              type="button"
              className={hrButtonClass}
              onClick={() => setOffset(offset + pageSize)}
            >
              Next correspondence page
            </button>
          )}
          {offset > 0 && (
            <button
              type="button"
              className={hrButtonClass}
              onClick={() => setOffset(offset - pageSize)}
            >
              Previous correspondence page
            </button>
          )}
          {selected && detail.isPending && <p role="status">Loading draft text…</p>}
          {record && (
            <section
              className="space-y-2 rounded border border-theme-border p-2"
              aria-label="Selected correspondence"
            >
              <h5 className="font-semibold">{record.subject}</h5>
              <p>Status {record.status}</p>
              <p className="whitespace-pre-wrap">{record.body}</p>
              {record.rejection_reason && <p>Review reason {record.rejection_reason}</p>}
              {record.can_decide && (
                <>
                  <button
                    type="button"
                    className={hrButtonClass}
                    disabled={busy}
                    onClick={() =>
                      decide.mutate({ decision: 'approved', expected_digest: record.digest })
                    }
                  >
                    Approve candidate correspondence
                  </button>
                  <form
                    onSubmit={(event) => {
                      event.preventDefault();
                      if (!busy && reason.trim())
                        decide.mutate({
                          decision: 'rejected',
                          expected_digest: record.digest,
                          reason: reason.trim()
                        });
                    }}
                  >
                    <label>
                      Correspondence review reason
                      <input
                        className={hrInputClass}
                        required
                        maxLength={2000}
                        disabled={busy}
                        value={reason}
                        onChange={(event) => setReason(event.target.value)}
                      />
                    </label>
                    <button
                      type="submit"
                      className={hrButtonClass}
                      disabled={busy || !reason.trim()}
                    >
                      Reject candidate correspondence
                    </button>
                  </form>
                </>
              )}
            </section>
          )}
          {[templates.error, history.error, detail.error, draft.error, decide.error]
            .filter((error) => error !== null)
            .map((error, index) => (
              <p key={index} role="alert">
                {formatApiError(error, 'Could not update candidate correspondence.')}
              </p>
            ))}
        </>
      )}
    </details>
  );
}

export function HRApplicationRejection({
  application,
  pending,
  change
}: {
  application: ApplicationRecord;
  pending: boolean;
  change: (action: () => Promise<unknown>) => Promise<void>;
}) {
  const [open, setOpen] = useState(false);
  if (application.stage === 'rejected') {
    return (
      <>
        <p>Internal rejection reason {application.rejection_reason}</p>
        <Correspondence id={application.id} />
      </>
    );
  }
  if (
    !['applied', 'screening', 'shortlisted', 'interview', 'evaluation', 'offer'].includes(
      application.stage
    )
  )
    return null;
  if (!open)
    return (
      <button
        type="button"
        className={hrButtonClass}
        disabled={pending}
        onClick={() => setOpen(true)}
      >
        Reject application
      </button>
    );
  return (
    <form
      onSubmit={(event) => {
        event.preventDefault();
        if (pending) return;
        const data = new FormData(event.currentTarget);
        void change(() =>
          updateApplicationStage(application.id, {
            stage: 'rejected',
            rejection_reason: String(data.get('reason')).trim()
          })
        );
      }}
    >
      <label>
        Internal application rejection reason
        <input className={hrInputClass} name="reason" required disabled={pending} />
      </label>
      <button type="submit" className={hrButtonClass} disabled={pending}>
        Confirm application rejection
      </button>
      <button
        type="button"
        className={hrButtonClass}
        disabled={pending}
        onClick={() => setOpen(false)}
      >
        Keep application
      </button>
    </form>
  );
}
