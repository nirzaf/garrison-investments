import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import { useState } from 'react';

import { apiClient } from '../../api/client';
import { formatApiError } from '../../api/errors';
import { listHrAssignmentProjects, listPositions, type HrSchemas } from '../../api/hr';
import { hrButtonClass, hrInputClass } from './HRAccessForms';

const rulesPath = '/hr/training/requirements';
const pageSize = 20;
const statusLabels = { met: 'Met', enrolled: 'Enrolled', expired: 'Expired', required: 'Required' };

export function TrainingRequirements({ employeeId }: { employeeId?: string }) {
  const [offset, setOffset] = useState(0);
  const path = employeeId ? `${rulesPath}/employees/${employeeId}` : '/hr/me/training/requirements';
  const requirements = useQuery({
    queryKey: employeeId
      ? ['hr', 'training', 'requirements', employeeId, offset]
      : ['hr', 'me', 'training-requirements', offset],
    queryFn: async ({ signal }) =>
      (
        await apiClient.get<HrSchemas['TrainingRequirementStatusListResponse']>(path, {
          params: { limit: pageSize, offset },
          signal
        })
      ).data
  });
  return (
    <section aria-label="Mandatory training" className="space-y-2">
      <h5 className="font-semibold">Mandatory training</h5>
      {requirements.isPending && <p role="status">Loading requirements…</p>}
      {requirements.isError && (
        <p role="alert">
          {formatApiError(requirements.error, 'Could not load requirements.')}{' '}
          <button type="button" onClick={() => void requirements.refetch()}>
            Retry
          </button>
        </p>
      )}
      {requirements.data?.total === 0 && (
        <p>No mandatory training matches this position or site.</p>
      )}
      <ul>
        {requirements.data?.items.map((item) => (
          <li key={item.course_id}>
            {item.course_title} · {statusLabels[item.status]}
          </li>
        ))}
      </ul>
      {(requirements.data?.total ?? 0) > pageSize && (
        <nav aria-label="Mandatory training pages" className="flex gap-2">
          <button type="button" disabled={!offset} onClick={() => setOffset(offset - pageSize)}>
            Previous
          </button>
          <button
            type="button"
            disabled={offset + pageSize >= (requirements.data?.total ?? 0)}
            onClick={() => setOffset(offset + pageSize)}
          >
            Next
          </button>
        </nav>
      )}
    </section>
  );
}

export function TrainingRuleEditor({
  courses
}: {
  courses: HrSchemas['TrainingCourseResponse'][];
}) {
  const [open, setOpen] = useState(false);
  const [offset, setOffset] = useState(0);
  const [search, setSearch] = useState('');
  const queryClient = useQueryClient();
  const positions = useQuery({
    queryKey: ['hr', 'training', 'positions'],
    queryFn: listPositions,
    enabled: open
  });
  const sites = useQuery({
    queryKey: ['hr', 'training', 'sites', search],
    queryFn: () => listHrAssignmentProjects(search.trim() || undefined),
    enabled: open
  });
  const rules = useQuery({
    queryKey: ['hr', 'training', 'rules', offset],
    enabled: open,
    queryFn: async () =>
      (
        await apiClient.get<HrSchemas['TrainingRequirementListResponse']>(rulesPath, {
          params: { offset, limit: pageSize }
        })
      ).data
  });
  const refresh = () => queryClient.invalidateQueries({ queryKey: ['hr', 'training'] });
  const save = useMutation({
    mutationFn: (payload: HrSchemas['TrainingRequirementCreateRequest']) =>
      apiClient.post(rulesPath, payload),
    onSuccess: refresh
  });
  const remove = useMutation({
    mutationFn: (id: string) => apiClient.delete(`${rulesPath}/${id}`),
    onSuccess: refresh
  });
  const pending = save.isPending || remove.isPending;
  const error = save.error ?? remove.error ?? rules.error ?? positions.error ?? sites.error;
  return (
    <details
      className="space-y-3 rounded border border-theme-border bg-theme-card p-4"
      onToggle={(event) => setOpen(event.currentTarget.open)}
    >
      <summary className="font-semibold">Mandatory training rules</summary>
      {open && (
        <>
          <form
            className="flex flex-wrap items-end gap-2"
            onSubmit={(event) => {
              event.preventDefault();
              const form = event.currentTarget;
              const data = new FormData(form);
              save.mutate(
                {
                  course_id: String(data.get('course')),
                  position_id: String(data.get('position') ?? '') || null,
                  project_id: String(data.get('site') ?? '') || null
                },
                { onSuccess: () => form.reset() }
              );
            }}
          >
            <label>
              Required course{' '}
              <select name="course" className={hrInputClass} required defaultValue="">
                <option value="">Select course</option>
                {courses
                  .filter((course) => course.is_active)
                  .map((course) => (
                    <option key={course.id} value={course.id}>
                      {course.title}
                    </option>
                  ))}
              </select>
            </label>
            <label>
              Required job position{' '}
              <select name="position" className={hrInputClass}>
                <option value="">Any position</option>
                {positions.data?.items
                  .filter((position) => position.is_active)
                  .map((position) => (
                    <option key={position.id} value={position.id}>
                      {position.title}
                    </option>
                  ))}
              </select>
            </label>
            <label>
              Search requirement site{' '}
              <input
                className={hrInputClass}
                value={search}
                onChange={(event) => setSearch(event.target.value)}
              />
            </label>
            <label>
              Required project site{' '}
              <select name="site" className={hrInputClass}>
                <option value="">Any site</option>
                {sites.data?.items.map((site) => (
                  <option key={site.id} value={site.id}>
                    {site.name}
                  </option>
                ))}
              </select>
            </label>
            <button className={hrButtonClass} type="submit" disabled={pending}>
              Save training rule
            </button>
          </form>
          <p>
            Choose a position, a site, or both. A rule with both applies to employees who match
            both.
          </p>
          {error && (
            <p role="alert">
              {formatApiError(error, 'Could not update training rules.')}{' '}
              <button
                type="button"
                onClick={() => {
                  void refresh();
                }}
              >
                Refresh
              </button>
            </p>
          )}
          {rules.isPending && <p role="status">Loading training rules…</p>}
          {rules.data?.total === 0 && <p>No training rules.</p>}
          <ul className="space-y-2">
            {rules.data?.items.map((rule) => (
              <li key={rule.id}>
                {rule.course_title} · {rule.position_title ?? 'Any position'} ·{' '}
                {rule.project_name ?? 'Any site'} · {rule.is_active ? 'Active' : 'Inactive'}{' '}
                {rule.is_active && (
                  <button
                    type="button"
                    className={hrButtonClass}
                    disabled={pending}
                    onClick={() => remove.mutate(rule.id)}
                  >
                    Deactivate rule
                  </button>
                )}
              </li>
            ))}
          </ul>
          {(rules.data?.total ?? 0) > pageSize && (
            <nav aria-label="Training rule pages" className="flex gap-2">
              <button type="button" disabled={!offset} onClick={() => setOffset(offset - pageSize)}>
                Previous
              </button>
              <button
                type="button"
                disabled={offset + pageSize >= (rules.data?.total ?? 0)}
                onClick={() => setOffset(offset + pageSize)}
              >
                Next
              </button>
            </nav>
          )}
        </>
      )}
    </details>
  );
}
