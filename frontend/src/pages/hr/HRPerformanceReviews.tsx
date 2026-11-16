import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import { useRef, useState } from 'react';

import { apiClient } from '../../api/client';
import { formatApiError } from '../../api/errors';
import { listEmployees, type HrSchemas } from '../../api/hr';
import { hrButtonClass, hrInputClass } from './HRAccessForms';

const endpoint = '/hr/performance/reviews';
const pageSize = 20;
const labels = {
  acknowledge_goals: 'Acknowledge goals',
  record_progress: 'Record progress',
  submit_self_review: 'Submit self-review',
  submit_manager_review: 'Submit manager review',
  calibrate: 'Calibrate review',
  acknowledge_final: 'Acknowledge final review',
  add_addendum: 'Add correction',
  reassign_manager: 'Hand off to current manager'
} satisfies Record<HrSchemas['PerformanceReviewActionRequest']['action'], string>;
type Action = keyof typeof labels;
const ratedActions: Action[] = ['submit_self_review', 'submit_manager_review', 'calibrate'];

export function HRPerformanceReviews() {
  const [open, setOpen] = useState(false);
  const [selected, setSelected] = useState('');
  const [offset, setOffset] = useState(0);
  const [action, setAction] = useState<Action | ''>('');
  const intent = useRef<{ key: string; id: string } | undefined>(undefined);
  const client = useQueryClient();
  const queue = useQuery({
    queryKey: ['hr', 'performance', 'queue', offset],
    queryFn: async () =>
      (
        await apiClient.get<HrSchemas['PerformanceReviewQueue']>(endpoint, {
          params: { limit: pageSize, offset }
        })
      ).data,
    enabled: open
  });
  const detail = useQuery({
    queryKey: ['hr', 'performance', 'detail', selected],
    queryFn: async () =>
      (await apiClient.get<HrSchemas['PerformanceReviewDetail']>(`${endpoint}/${selected}`)).data,
    enabled: open && Boolean(selected)
  });
  const save = useMutation({
    mutationFn: (payload: HrSchemas['PerformanceReviewActionRequest']) =>
      apiClient.post(`${endpoint}/${selected}/actions`, payload),
    onSuccess: async () => {
      setAction('');
      intent.current = undefined;
      await client.invalidateQueries({ queryKey: ['hr', 'performance'] });
    }
  });
  const error = save.error ?? detail.error ?? queue.error;
  return (
    <details
      className="space-y-2 rounded border border-theme-border bg-theme-card p-4"
      onToggle={(event) => setOpen(event.currentTarget.open)}
    >
      <summary className="font-semibold">Performance reviews</summary>
      {open && (
        <>
          <button
            className={hrButtonClass}
            type="button"
            onClick={() => {
              void client.invalidateQueries({ queryKey: ['hr', 'performance'] });
            }}
          >
            Refresh reviews
          </button>
          {error && (
            <p role="alert">{formatApiError(error, 'Could not load or update the review.')}</p>
          )}
          {(queue.isPending || (selected && detail.isPending)) && (
            <p role="status">Loading performance reviews…</p>
          )}
          {queue.data?.total === 0 && <p>No accessible reviews.</p>}
          <ul className="space-y-2">
            {queue.data?.items.map((item) => (
              <li key={item.id}>
                <button
                  className={hrButtonClass}
                  type="button"
                  disabled={save.isPending}
                  onClick={() => {
                    setAction('');
                    save.reset();
                    setSelected(item.id);
                  }}
                >
                  {item.employee_name} · {item.cycle_name} · {item.status.replace(/_/g, ' ')}
                </button>
              </li>
            ))}
          </ul>
          {(queue.data?.total ?? 0) > pageSize && (
            <nav className="flex gap-2" aria-label="Review pages">
              <button type="button" disabled={!offset} onClick={() => setOffset(offset - pageSize)}>
                Previous
              </button>
              <button
                type="button"
                disabled={offset + pageSize >= (queue.data?.total ?? 0)}
                onClick={() => setOffset(offset + pageSize)}
              >
                Next
              </button>
            </nav>
          )}
          {detail.data && (
            <section className="space-y-2" aria-label="Selected performance review">
              <h4 className="font-semibold">
                {detail.data.cycle_name} · {detail.data.status.replace(/_/g, ' ')}
              </h4>
              <ul>
                {detail.data.goals.map((goal) => (
                  <li key={goal.id}>
                    {goal.title}
                    {goal.description && ` · ${goal.description}`}
                  </li>
                ))}
              </ul>
              <ol className="space-y-2">
                {detail.data.events.map((event) => (
                  <li key={event.id}>
                    <p>
                      {labels[event.action]} · {event.participant.toUpperCase()}
                    </p>
                    {event.rating && <p>Rating {event.rating}</p>}
                    {event.notes && <p className="whitespace-pre-wrap">{event.notes}</p>}
                  </li>
                ))}
              </ol>
              {detail.data.allowed_actions.length > 0 && (
                <form
                  className="space-y-2"
                  onSubmit={(event) => {
                    event.preventDefault();
                    if (!action || !detail.data || save.isPending) return;
                    const form = event.currentTarget;
                    const data = new FormData(form);
                    const notes = String(data.get('notes') ?? '').trim() || null;
                    const rating = String(data.get('rating') ?? '') || null;
                    const replacement_reviewer_id =
                      action === 'reassign_manager' ? detail.data.replacement_reviewer_id : null;
                    const revision = detail.data.revision;
                    const key = JSON.stringify([
                      selected,
                      revision,
                      action,
                      notes,
                      rating,
                      replacement_reviewer_id
                    ]);
                    if (intent.current?.key !== key)
                      intent.current = { key, id: crypto.randomUUID() };
                    save.mutate(
                      {
                        event_id: intent.current.id,
                        expected_revision: revision,
                        action,
                        notes,
                        rating,
                        replacement_reviewer_id
                      },
                      { onSuccess: () => form.reset() }
                    );
                  }}
                >
                  <label className="block">
                    Review action{' '}
                    <select
                      required
                      value={action}
                      className={hrInputClass}
                      onChange={(event) => setAction(event.target.value as Action | '')}
                    >
                      <option value="">Select action</option>
                      {detail.data.allowed_actions.map((item) => (
                        <option key={item} value={item}>
                          {labels[item]}
                        </option>
                      ))}
                    </select>
                  </label>
                  {action === 'reassign_manager' && (
                    <p>Replacement reviewer {detail.data.replacement_reviewer_name}</p>
                  )}
                  {action &&
                    ratedActions.includes(action) &&
                    detail.data.rating_scale.length > 0 && (
                      <label className="block">
                        Review rating
                        <select
                          name="rating"
                          className={hrInputClass}
                          required
                          key={action}
                          defaultValue=""
                        >
                          <option value="">Select a rating</option>
                          {detail.data.rating_scale.map((rating) => (
                            <option key={rating} value={rating}>
                              {rating}
                            </option>
                          ))}
                        </select>
                      </label>
                    )}
                  <label className="block">
                    Review notes{' '}
                    <textarea
                      className={hrInputClass}
                      name="notes"
                      maxLength={4000}
                      required={Boolean(action && !action.startsWith('acknowledge'))}
                    />
                  </label>
                  <button className={hrButtonClass} type="submit" disabled={save.isPending}>
                    Record review action
                  </button>
                </form>
              )}
            </section>
          )}
        </>
      )}
    </details>
  );
}

export function HRPerformanceSetup() {
  const [search, setSearch] = useState('');
  const [employee, setEmployee] = useState('');
  const [cycleId, setCycleId] = useState('');
  const client = useQueryClient();
  const cycles = useQuery({
    queryKey: ['hr', 'performance', 'cycles'],
    queryFn: async () =>
      (await apiClient.get<HrSchemas['ReviewCycleListResponse']>('/hr/review-cycles')).data
  });
  const employees = useQuery({
    queryKey: ['hr', 'performance', 'employee-search', search],
    queryFn: () => listEmployees({ search: search.trim(), limit: 20 }),
    enabled: search.trim().length >= 2
  });
  const cycle = cycles.data?.items.find((item) => item.id === cycleId);
  const save = useMutation({
    mutationFn: ({ path, data }: { path: string; data: object }) => apiClient.post(path, data),
    onSuccess: () => client.invalidateQueries({ queryKey: ['hr', 'performance'] })
  });
  const error = save.error ?? cycles.error ?? employees.error;

  return (
    <section className="space-y-3 rounded border border-theme-border bg-theme-card p-4">
      <h3 className="font-semibold">Review setup</h3>
      {error && <p role="alert">{formatApiError(error, 'Could not update review setup.')}</p>}
      <form
        className="flex flex-wrap items-end gap-2"
        onSubmit={(event) => {
          event.preventDefault();
          const form = event.currentTarget;
          const data = new FormData(form);
          const ratingScale = String(data.get('rating_scale') ?? '')
            .split('\n')
            .map((label) => label.trim())
            .filter(Boolean);
          data.delete('rating_scale');
          save.mutate(
            {
              path: '/hr/review-cycles',
              data: { ...Object.fromEntries(data), rating_scale: ratingScale }
            },
            { onSuccess: () => form.reset() }
          );
        }}
      >
        <label>
          Cycle code <input name="code" className={hrInputClass} required maxLength={40} />
        </label>
        <label>
          Cycle name <input name="name" className={hrInputClass} required maxLength={160} />
        </label>
        <label>
          Cycle starts <input type="date" name="start_date" className={hrInputClass} required />
        </label>
        <label>
          Cycle ends <input type="date" name="end_date" className={hrInputClass} required />
        </label>
        <label>
          Rating labels (one per line, optional)
          <textarea className={hrInputClass} name="rating_scale" rows={3} maxLength={732} />
        </label>
        <button className={hrButtonClass} type="submit" disabled={save.isPending}>
          Create review cycle
        </button>
      </form>
      <label>
        Search review employee{' '}
        <input
          className={hrInputClass}
          value={search}
          onChange={(event) => setSearch(event.target.value)}
        />
      </label>
      <label className="block">
        Review employee{' '}
        <select
          className={hrInputClass}
          value={employee}
          onChange={(event) => setEmployee(event.target.value)}
        >
          <option value="">Select employee</option>
          {employees.data?.items.map((item) => (
            <option key={item.id} value={item.id}>
              {item.full_name} · {item.employee_code}
            </option>
          ))}
        </select>
      </label>
      <label className="block">
        Review cycle{' '}
        <select
          className={hrInputClass}
          value={cycleId}
          onChange={(event) => setCycleId(event.target.value)}
        >
          <option value="">Select cycle</option>
          {cycles.data?.items.map((item) => (
            <option key={item.id} value={item.id}>
              {item.name}
            </option>
          ))}
        </select>
      </label>
      {employee && cycle && (
        <>
          <form
            className="flex flex-wrap items-end gap-2"
            onSubmit={(event) => {
              event.preventDefault();
              const form = event.currentTarget;
              const data = new FormData(form);
              save.mutate(
                {
                  path: '/hr/goals',
                  data: {
                    employee_id: employee,
                    cycle_name: cycle.code,
                    title: data.get('title'),
                    description: data.get('description') || null
                  }
                },
                { onSuccess: () => form.reset() }
              );
            }}
          >
            <label>
              Goal title <input name="title" className={hrInputClass} required maxLength={200} />
            </label>
            <label>
              Goal description <input name="description" className={hrInputClass} />
            </label>
            <button className={hrButtonClass} type="submit" disabled={save.isPending}>
              Add goal
            </button>
          </form>
          <button
            className={hrButtonClass}
            type="button"
            disabled={save.isPending}
            onClick={() =>
              save.mutate({
                path: '/hr/reviews',
                data: { employee_id: employee, cycle_id: cycle.id }
              })
            }
          >
            Open draft review
          </button>
        </>
      )}
    </section>
  );
}
