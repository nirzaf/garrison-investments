import { useQuery, useQueryClient } from '@tanstack/react-query';
import { useRef, useState, type FormEvent } from 'react';

import { formatApiError } from '../../api/errors';
import {
  createProjectTask,
  getProjectTimeline,
  updateProjectTask,
  type ProjectDetail,
  type ProjectTaskPayload,
  type ProjectTaskRecord,
  type ProjectTimelineResponse
} from '../../api/projects';
import {
  ProjectInput,
  ProjectSelect,
  ProjectTextArea,
  projectActionClass,
  projectSubmitClass
} from './ProjectFields';
import { ProjectUserPicker } from './ProjectUserPicker';
import { buildSchedule, dateRange, scheduleTypes } from './projectSchedule';

const scheduleLabels = { baseline: 'Baseline', planned: 'Planned', actual: 'Actual' };
const colors = { baseline: 'bg-slate-500', planned: 'bg-brand-600', actual: 'bg-emerald-600' };

export function ProjectTimeline({
  project,
  canEdit,
  active
}: {
  project: ProjectDetail;
  canEdit: boolean;
  active: boolean;
}) {
  const queryClient = useQueryClient();
  const timeline = useQuery({
    queryKey: ['project-timeline', project.id],
    queryFn: () => getProjectTimeline(project.id),
    enabled: active
  });
  const [editor, setEditor] = useState<ProjectTaskRecord | 'new' | null>(null);

  return (
    <div className="space-y-4" hidden={!active}>
      <div className="flex flex-wrap items-center justify-between gap-2">
        <h4 className="font-semibold">Project timeline</h4>
        {canEdit && timeline.data && !editor && (
          <button className={projectActionClass} type="button" onClick={() => setEditor('new')}>
            New task
          </button>
        )}
      </div>
      {timeline.isPending && <p role="status">Loading timeline…</p>}
      {timeline.isError && (
        <div role="alert">
          <p>{formatApiError(timeline.error, 'Unable to load the project timeline.')}</p>
          <button
            type="button"
            className={projectActionClass}
            onClick={() => void timeline.refetch()}
          >
            Retry timeline
          </button>
        </div>
      )}
      {timeline.data && (
        <>
          {timeline.isFetching && (
            <p role="status" className="text-sm">
              Refreshing timeline…
            </p>
          )}
          {timeline.isError && <p className="text-sm">Showing the last loaded timeline.</p>}
          {editor && (
            <TaskEditor
              key={editor === 'new' ? 'new' : editor.id}
              projectId={project.id}
              timeline={timeline.data}
              task={editor === 'new' ? undefined : editor}
              canSave={canEdit}
              onCancel={() => setEditor(null)}
              onSaved={() => {
                setEditor(null);
                void queryClient.invalidateQueries({ queryKey: ['project-timeline', project.id] });
              }}
              refresh={() => void timeline.refetch()}
            />
          )}
          <ScheduleChart timeline={timeline.data} />
          <TaskTable timeline={timeline.data} canEdit={canEdit && !editor} onEdit={setEditor} />
        </>
      )}
    </div>
  );
}

function ScheduleChart({ timeline }: { timeline: ProjectTimelineResponse }) {
  const chart = buildSchedule(timeline.tasks);
  const milestoneNames = new Map(timeline.milestones.map((item) => [item.id, item.name]));
  if (!timeline.tasks.length) return null;
  return (
    <div className="space-y-3">
      {chart.scheduled.length > 0 && (
        <>
          <ul className="flex flex-wrap gap-3 text-sm" aria-label="Schedule legend">
            {scheduleTypes.map((kind) => (
              <li className="flex items-center gap-2" key={kind}>
                <span
                  className={`inline-block h-2.5 w-5 rounded-sm ${colors[kind]}`}
                  aria-hidden="true"
                />
                {scheduleLabels[kind]}
              </li>
            ))}
          </ul>
          <div
            role="region"
            aria-label="Scrollable task Gantt chart"
            tabIndex={0}
            className="overflow-x-auto rounded-md border border-theme-border focus-visible:outline-2 focus-visible:outline-brand-600"
          >
            <div style={{ minWidth: chart.width + 220 }}>
              <div className="grid grid-cols-[220px_1fr] border-b border-theme-border bg-theme-main">
                <div className="p-2 text-sm font-semibold">Task schedule</div>
                <div className="relative my-2 mr-2 h-4 text-xs font-medium">
                  {chart.ticks.map(({ date, position }) => (
                    <time
                      className="absolute whitespace-nowrap"
                      key={date}
                      dateTime={date}
                      style={{
                        left: `${position}%`,
                        transform: position > 80 ? 'translateX(-100%)' : undefined
                      }}
                    >
                      {date}
                    </time>
                  ))}
                </div>
              </div>
              {chart.scheduled.map(({ task, ranges }) => (
                <div
                  className="grid grid-cols-[220px_1fr] border-b border-theme-border last:border-b-0"
                  key={task.id}
                >
                  <div className="space-y-1 p-2 text-sm">
                    <p className="font-semibold">{task.name}</p>
                    <p className="text-xs text-theme-text-secondary">
                      {milestoneNames.get(task.milestone_id ?? '') ?? 'No milestone'} ·{' '}
                      {timeline.owner_names[task.owner_id ?? ''] ?? 'Unassigned'} ·{' '}
                      {task.progress_percentage}%
                    </p>
                  </div>
                  <div className="grid content-center gap-1 py-2 pr-2">
                    {scheduleTypes.map((kind) => {
                      const range = ranges.find((item) => item.kind === kind);
                      return (
                        <div key={kind} className="relative h-3 rounded bg-theme-main">
                          {range && (
                            <span
                              className={`absolute h-3 min-w-px rounded ${colors[kind]}`}
                              style={chart.bars(range)}
                              aria-label={`${scheduleLabels[kind]} ${range.label}`}
                              role="img"
                              title={`${scheduleLabels[kind]} ${range.label}`}
                            />
                          )}
                        </div>
                      );
                    })}
                  </div>
                </div>
              ))}
            </div>
          </div>
        </>
      )}
      {chart.incomplete.length > 0 && (
        <div className="rounded-md border border-theme-border p-3">
          <h5 className="text-sm font-semibold">Incomplete or unscheduled tasks</h5>
          <ul className="mt-1 list-disc space-y-1 pl-4 text-sm">
            {chart.incomplete.map((task) => (
              <li key={task.id}>{task.name}</li>
            ))}
          </ul>
        </div>
      )}
    </div>
  );
}

function TaskTable({
  timeline,
  canEdit,
  onEdit
}: {
  timeline: ProjectTimelineResponse;
  canEdit: boolean;
  onEdit: (task: ProjectTaskRecord) => void;
}) {
  const taskNames = new Map(timeline.tasks.map((task) => [task.id, task.name]));
  const milestoneNames = new Map(
    timeline.milestones.map((milestone) => [milestone.id, milestone.name])
  );
  return (
    <div className="overflow-x-auto">
      <table className="min-w-full text-left text-sm">
        <caption className="mb-2 text-left font-semibold">Project tasks</caption>
        <thead className="bg-theme-main">
          <tr>
            {[
              'Task',
              'Milestone',
              'Owner',
              'Dependency',
              'Baseline',
              'Planned',
              'Actual',
              'Progress',
              'Status',
              ...(canEdit ? ['Action'] : [])
            ].map((name) => (
              <th key={name} scope="col" className="p-2">
                {name}
              </th>
            ))}
          </tr>
        </thead>
        <tbody className="divide-y divide-theme-border">
          {timeline.tasks.map((task) => (
            <tr key={task.id}>
              <th scope="row" className="p-2">
                <span className="font-medium">{task.name}</span>
                {task.delay_reason && <p className="text-xs font-normal">{task.delay_reason}</p>}
              </th>
              <td className="p-2">{milestoneNames.get(task.milestone_id ?? '') ?? '—'}</td>
              <td className="p-2">{timeline.owner_names[task.owner_id ?? ''] ?? '—'}</td>
              <td className="p-2">{taskNames.get(task.dependency_task_id ?? '') ?? '—'}</td>
              <td className="p-2">{dateRange(task.baseline_start_date, task.baseline_end_date)}</td>
              <td className="p-2">{dateRange(task.planned_start_date, task.planned_end_date)}</td>
              <td className="p-2">{dateRange(task.actual_start_date, task.actual_end_date)}</td>
              <td className="p-2">{task.progress_percentage}%</td>
              <td className="p-2 capitalize">{task.status.replace(/_/g, ' ')}</td>
              {canEdit && (
                <td className="p-2">
                  <button
                    type="button"
                    className={projectActionClass}
                    aria-label={`Edit task ${task.name}`}
                    onClick={() => onEdit(task)}
                  >
                    Edit
                  </button>
                </td>
              )}
            </tr>
          ))}
        </tbody>
      </table>
      {!timeline.tasks.length && <p className="p-2 text-sm">No tasks yet.</p>}
    </div>
  );
}

function TaskEditor({
  projectId,
  timeline,
  task,
  canSave,
  onCancel,
  onSaved,
  refresh
}: {
  projectId: string;
  timeline: ProjectTimelineResponse;
  task?: ProjectTaskRecord;
  canSave: boolean;
  onCancel: () => void;
  onSaved: () => void;
  refresh: () => void;
}) {
  const [draft, setDraft] = useState<ProjectTaskPayload>({
    name: task?.name ?? '',
    milestone_id: task?.milestone_id ?? null,
    dependency_task_id: task?.dependency_task_id ?? null,
    owner_id: task?.owner_id ?? null,
    baseline_start_date: task?.baseline_start_date ?? null,
    baseline_end_date: task?.baseline_end_date ?? null,
    planned_start_date: task?.planned_start_date ?? null,
    planned_end_date: task?.planned_end_date ?? null,
    actual_start_date: task?.actual_start_date ?? null,
    actual_end_date: task?.actual_end_date ?? null,
    status: task?.status ?? 'not_started',
    progress_percentage: task?.progress_percentage ?? '0',
    delay_reason: task?.delay_reason ?? null,
    sort_order: task?.sort_order ?? 0
  });
  const [error, setError] = useState('');
  const [pending, setPending] = useState(false);
  const submitting = useRef(false);
  const changed = Boolean(
    task && timeline.tasks.find((item) => item.id === task.id)?.revision !== task.revision
  );

  async function submit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (submitting.current || changed || !canSave) return;
    submitting.current = true;
    setPending(true);
    setError('');
    const payload = {
      ...draft,
      name: draft.name.trim(),
      delay_reason: draft.delay_reason?.trim() || null
    };
    try {
      if (task)
        await updateProjectTask(projectId, task.id, {
          ...payload,
          expected_revision: task.revision
        });
      else await createProjectTask(projectId, payload);
      onSaved();
    } catch (failure) {
      setError(formatApiError(failure, 'Unable to save task.'));
    } finally {
      submitting.current = false;
      setPending(false);
    }
  }

  return (
    <form
      className="space-y-3 rounded-md border border-theme-border p-3"
      onSubmit={(event) => void submit(event)}
    >
      <h5 className="font-semibold">{task ? `Edit ${task.name}` : 'New task'}</h5>
      {error && (
        <p role="alert" className="alert-error rounded-md p-2 text-sm">
          {error}
        </p>
      )}
      {changed && (
        <p role="status" className="text-sm">
          Compare your draft with the saved task below. Discard this draft to edit the latest
          version.
        </p>
      )}
      <fieldset disabled={pending} className="grid gap-3 sm:grid-cols-2 xl:grid-cols-3">
        <ProjectInput
          label="Task name"
          required
          maxLength={180}
          value={draft.name}
          onChange={(e) => setDraft({ ...draft, name: e.target.value })}
        />
        <ProjectSelect
          label="Milestone"
          value={draft.milestone_id ?? ''}
          onChange={(e) => setDraft({ ...draft, milestone_id: e.target.value || null })}
        >
          <option value="">No milestone</option>
          {draft.milestone_id &&
            !timeline.milestones.some((item) => item.id === draft.milestone_id) && (
              <option value={draft.milestone_id}>Unavailable milestone</option>
            )}
          {timeline.milestones.map((item) => (
            <option key={item.id} value={item.id}>
              {item.name}
            </option>
          ))}
        </ProjectSelect>
        <ProjectSelect
          label="Depends on"
          value={draft.dependency_task_id ?? ''}
          onChange={(e) => setDraft({ ...draft, dependency_task_id: e.target.value || null })}
        >
          <option value="">No dependency</option>
          {draft.dependency_task_id &&
            !timeline.tasks.some((item) => item.id === draft.dependency_task_id) && (
              <option value={draft.dependency_task_id}>Unavailable task</option>
            )}
          {timeline.tasks
            .filter((item) => item.id !== task?.id)
            .map((item) => (
              <option key={item.id} value={item.id}>
                {item.name}
              </option>
            ))}
        </ProjectSelect>
        {scheduleTypes.flatMap((kind) =>
          (['start', 'end'] as const).map((end) => {
            const field = `${kind}_${end}_date` as const;
            return (
              <ProjectInput
                key={field}
                label={`${scheduleLabels[kind]} ${end}`}
                type="date"
                value={draft[field] ?? ''}
                onChange={(e) => setDraft({ ...draft, [field]: e.target.value || null })}
              />
            );
          })
        )}
        <ProjectSelect
          label="Task status"
          value={draft.status}
          onChange={(e) => setDraft({ ...draft, status: e.target.value })}
        >
          <option value="not_started">Not started</option>
          <option value="in_progress">In progress</option>
          <option value="blocked">Blocked</option>
          <option value="completed">Completed</option>
          <option value="cancelled">Cancelled</option>
        </ProjectSelect>
        <ProjectInput
          label="Progress %"
          required
          type="number"
          min="0"
          max="100"
          step="0.01"
          value={draft.progress_percentage}
          onChange={(e) => setDraft({ ...draft, progress_percentage: e.target.value })}
        />
        <ProjectInput
          label="Task sort order"
          required
          type="number"
          min="0"
          max="2147483647"
          value={draft.sort_order}
          onChange={(e) => setDraft({ ...draft, sort_order: e.target.valueAsNumber })}
        />
        <ProjectUserPicker
          label="Task owner"
          value={draft.owner_id ?? ''}
          selectedName={timeline.owner_names[task?.owner_id ?? '']}
          onChange={(id) => setDraft({ ...draft, owner_id: id || null })}
        />
        <ProjectTextArea
          label="Delay notes"
          value={draft.delay_reason ?? ''}
          onChange={(e) => setDraft({ ...draft, delay_reason: e.target.value })}
        />
        <div className="flex flex-wrap items-end gap-2 sm:col-span-2 xl:col-span-3">
          <button type="submit" disabled={!canSave || changed} className={projectSubmitClass}>
            {pending ? 'Saving…' : task ? 'Save task' : 'Add task'}
          </button>
          {error && (
            <button type="button" className={projectActionClass} onClick={refresh}>
              Compare saved task
            </button>
          )}
          <button type="button" className={projectActionClass} onClick={onCancel}>
            Discard task edits
          </button>
        </div>
      </fieldset>
    </form>
  );
}
