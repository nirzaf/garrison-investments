import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import { useState } from 'react';

import { formatApiError } from '../../api/errors';
import { listHrAssignmentProjects, listMyHrAssignments, requestHrAssignment } from '../../api/hr';
import { hrButtonClass, hrInputClass } from './HRAccessForms';

const pageSize = 25;

export function HRProjectAssignments({ employeeId }: { employeeId?: string }) {
  const client = useQueryClient();
  const [search, setSearch] = useState('');
  const [selected, setSelected] = useState('');
  const [selectedLabel, setSelectedLabel] = useState('');
  const [action, setAction] = useState<'assign' | 'revoke'>('assign');
  const [offset, setOffset] = useState(0);
  const [projectOffset, setProjectOffset] = useState(0);
  const projects = useQuery({
    queryKey: ['hr', 'project-assignment-options', employeeId, search, projectOffset],
    queryFn: () => listHrAssignmentProjects(search, pageSize, projectOffset),
    enabled: Boolean(employeeId)
  });
  const requests = useQuery({
    queryKey: ['hr', 'assignment-requests', offset],
    queryFn: () => listMyHrAssignments(offset)
  });
  const send = useMutation({
    mutationFn: ([id, payload]: Parameters<typeof requestHrAssignment>) =>
      requestHrAssignment(id, payload),
    onSuccess: async () => {
      setOffset(0);
      await client.invalidateQueries({ queryKey: ['hr', 'assignment-requests'] });
    }
  });

  return (
    <section className="space-y-3 rounded border border-theme-border p-3">
      <h4 className="font-semibold">Project assignment requests</h4>
      {employeeId && (
        <>
          <form
            className="flex flex-wrap items-end gap-2"
            onSubmit={(event) => {
              event.preventDefault();
              setProjectOffset(0);
              setSearch(String(new FormData(event.currentTarget).get('projectSearch')).trim());
            }}
          >
            <label>
              Find project by name or code
              <input name="projectSearch" className={hrInputClass} maxLength={100} />
            </label>
            <button className={hrButtonClass} type="submit" disabled={send.isPending}>
              Find project
            </button>
          </form>
          <form
            className="grid gap-2 sm:grid-cols-2"
            onSubmit={(event) => {
              event.preventDefault();
              if (!selected || send.isPending) return;
              const form = event.currentTarget;
              const fields = new FormData(form);
              send.mutate(
                [
                  employeeId,
                  {
                    project_id: selected,
                    action,
                    role_in_project:
                      action === 'assign' ? String(fields.get('projectRole')).trim() || null : null,
                    reason: String(fields.get('reason')).trim()
                  }
                ],
                {
                  onSuccess: () => {
                    form.reset();
                    setSelected('');
                  }
                }
              );
            }}
          >
            <label>
              Assignment project
              <select
                className={hrInputClass}
                value={selected}
                disabled={!employeeId || projects.isFetching}
                aria-label="Assignment project"
                onChange={(event) => {
                  const option = projects.data?.items.find((item) => item.id === event.target.value);
                  setSelected(option?.id ?? '');
                  setSelectedLabel(option ? `${option.code} · ${option.name}` : '');
                }}
                required
              >
                <option value="">
                  {projects.isFetching ? 'Loading projects…' : 'Choose a project'}
                </option>
                {selected && !projects.data?.items.some((item) => item.id === selected) && (
                  <option value={selected}>{selectedLabel}</option>
                )}
                {projects.data?.items.map((item) => (
                  <option key={item.id} value={item.id}>
                    {item.code} · {item.name}
                  </option>
                ))}
              </select>
            </label>
            <label>
              Assignment change
              <select
                className={hrInputClass}
                value={action}
                onChange={(event) =>
                  setAction(event.target.value === 'revoke' ? 'revoke' : 'assign')
                }
              >
                <option value="assign">Add to project team</option>
                <option value="revoke">Remove from project team</option>
              </select>
            </label>
            {action === 'assign' && (
              <label>
                Project role label (optional)
                <input name="projectRole" className={hrInputClass} maxLength={50} />
              </label>
            )}
            <label>
              Assignment reason
              <input name="reason" className={hrInputClass} maxLength={500} required />
            </label>
            <button className={hrButtonClass} type="submit" disabled={!selected || send.isPending}>
              Send assignment request
            </button>
          </form>
        </>
      )}
      {!employeeId && <p>Select an employee with a linked portal account to request a change.</p>}
      {projects.isLoading && <p role="status">Finding projects…</p>}
      {projects.isSuccess && !projects.data.items.length && (
        <p>No editable projects are available for this search.</p>
      )}
      {projects.isError && (
        <p role="alert">
          {formatApiError(projects.error, 'Could not find projects.')}{' '}
          <button className="underline" type="button" onClick={() => void projects.refetch()}>
            Retry
          </button>
        </p>
      )}
      {projects.data && projects.data.total > pageSize && employeeId && (
        <nav className="flex gap-2 text-sm" aria-label="Assignment project option pages">
          <button
            className="underline"
            type="button"
            disabled={projectOffset === 0 || projects.isFetching}
            onClick={() => setProjectOffset((value) => Math.max(0, value - pageSize))}
          >
            Previous projects
          </button>
          <button
            className="underline"
            type="button"
            disabled={projectOffset + pageSize >= projects.data.total || projects.isFetching}
            onClick={() => setProjectOffset((value) => value + pageSize)}
          >
            More projects
          </button>
        </nav>
      )}
      {send.isSuccess && <p role="status">Request sent for project review.</p>}
      {send.isError && (
        <p role="alert">{formatApiError(send.error, 'Could not send the request.')}</p>
      )}
      <h5 className="font-medium">My requests</h5>
      {requests.isLoading && <p role="status">Loading requests…</p>}
      {requests.isSuccess && !requests.data.items.length && <p>No requests on this page.</p>}
      {requests.isError && (
        <p role="alert">
          {formatApiError(requests.error, 'Could not load requests.')}{' '}
          <button className="underline" type="button" onClick={() => void requests.refetch()}>
            Retry
          </button>
        </p>
      )}
      <ul className="space-y-2">
        {requests.data?.items.map((item) => (
          <li key={item.id}>
            <p>
              {item.employee_name} · {item.project_code} ·{' '}
              {item.action === 'assign' ? 'Add' : 'Remove'} · {item.status}
            </p>
            {item.decision_note && <p>{item.decision_note}</p>}
          </li>
        ))}
      </ul>
      <div className="flex gap-2">
        <button
          className={hrButtonClass}
          type="button"
          disabled={offset === 0}
          onClick={() => setOffset(offset - pageSize)}
        >
          Previous requests
        </button>
        <button
          className={hrButtonClass}
          type="button"
          disabled={offset + pageSize >= (requests.data?.total ?? 0)}
          onClick={() => setOffset(offset + pageSize)}
        >
          Next requests
        </button>
      </div>
    </section>
  );
}
