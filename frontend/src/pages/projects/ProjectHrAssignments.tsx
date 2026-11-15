import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import { useState } from 'react';

import { formatApiError } from '../../api/errors';
import { decideProjectHrAssignment, listProjectHrAssignments } from '../../api/projects';
import { projectActionClass } from './ProjectFields';

export function ProjectHrAssignments({
  projectId,
  revision,
  canApprove
}: {
  projectId: string;
  revision: number;
  canApprove: boolean;
}) {
  const client = useQueryClient();
  const [offset, setOffset] = useState(0);
  const requests = useQuery({
    queryKey: ['project-hr-assignment-requests', projectId, offset],
    queryFn: () => listProjectHrAssignments(projectId, offset)
  });
  const decide = useMutation({
    mutationFn: ({
      id,
      decision,
      note
    }: {
      id: string;
      decision: 'approve' | 'reject';
      note: string;
    }) =>
      decideProjectHrAssignment(projectId, id, {
        decision,
        note: note.trim() || null,
        expected_project_revision: revision
      }),
    onSuccess: async () => {
      await Promise.all([
        client.invalidateQueries({ queryKey: ['project-hr-assignment-requests', projectId] }),
        client.invalidateQueries({ queryKey: ['project-members', projectId] }),
        client.invalidateQueries({ queryKey: ['project-detail', projectId] }),
        client.invalidateQueries({ queryKey: ['projects'] })
      ]);
    },
    onError: () => client.invalidateQueries({ queryKey: ['project-detail', projectId] })
  });

  return (
    <section className="space-y-2 rounded border border-theme-border p-3">
      <h5 className="font-semibold">HR assignment requests</h5>
      {requests.isLoading && <p role="status">Loading HR requests…</p>}
      {requests.isSuccess && !requests.data.items.length && <p>No HR requests on this page.</p>}
      {requests.isError && (
        <p role="alert">
          {formatApiError(requests.error, 'Could not load HR requests.')}{' '}
          <button
            className={projectActionClass}
            type="button"
            onClick={() => void requests.refetch()}
          >
            Retry requests
          </button>
        </p>
      )}
      {decide.isError && (
        <p role="alert">{formatApiError(decide.error, 'Could not decide the request.')}</p>
      )}
      {decide.isSuccess && <p role="status">Assignment decision recorded.</p>}
      <ul className="space-y-3">
        {requests.data?.items.map((item) => (
          <li key={item.id} className="space-y-1 border-b border-theme-border pb-2">
            <p>
              <strong>{item.employee_name}</strong> · {item.action === 'assign' ? 'Add' : 'Remove'}{' '}
              · {item.status}
            </p>
            {item.role_in_project && <p>Requested project role label: {item.role_in_project}</p>}
            <p>{item.reason}</p>
            {item.decision_note && <p>{item.decision_note}</p>}
            {item.status === 'pending' && (
              <form
                className="flex flex-wrap items-end gap-2"
                onSubmit={(event) => {
                  event.preventDefault();
                  const submitter = (event.nativeEvent as SubmitEvent).submitter;
                  if (!(submitter instanceof HTMLButtonElement) || decide.isPending) return;
                  const decision = submitter.value === 'reject' ? 'reject' : 'approve';
                  if (decision === 'approve' && !canApprove) return;
                  const note = String(new FormData(event.currentTarget).get('note') ?? '');
                  decide.mutate({ id: item.id, decision, note });
                }}
              >
                <label>
                  Decision note (required to reject)
                  <input
                    className="block rounded border border-theme-border bg-theme-input px-2 py-1"
                    name="note"
                    maxLength={500}
                  />
                </label>
                <button
                  className={projectActionClass}
                  type="submit"
                  value="approve"
                  disabled={decide.isPending || !canApprove}
                >
                  Approve assignment
                </button>
                <button
                  className={projectActionClass}
                  type="submit"
                  value="reject"
                  disabled={decide.isPending}
                >
                  Reject assignment
                </button>
              </form>
            )}
          </li>
        ))}
      </ul>
      <div className="flex gap-2">
        <button
          className={projectActionClass}
          type="button"
          disabled={offset === 0}
          onClick={() => setOffset(offset - 25)}
        >
          Previous HR requests
        </button>
        <button
          className={projectActionClass}
          type="button"
          disabled={offset + 25 >= (requests.data?.total ?? 0)}
          onClick={() => setOffset(offset + 25)}
        >
          Next HR requests
        </button>
      </div>
    </section>
  );
}
