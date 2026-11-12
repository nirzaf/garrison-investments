import { FormEvent, useCallback, useEffect, useMemo, useState } from 'react';

import {
  createProjectTask,
  createProject,
  getProjectTimeline,
  listProjects,
  type ProjectPayload,
  type ProjectRecord,
  type ProjectTaskPayload,
  type ProjectTimelineResponse
} from '../../api/projects';
import { listUsers, type UserRecord } from '../../api/users';
import { useAuth } from '../../context/useAuth';
import { useDebouncedSearch } from '../../useDebouncedSearch';

const initialProject: ProjectPayload = {
  name: '',
  scope_of_work: '',
  target_end_date: '',
  status: 'planning',
  location: '',
  client_name: '',
  contract_number: '',
  milestones: [
    {
      name: 'Mobilization',
      discipline: 'civil',
      planned_start_date: '',
      planned_end_date: '',
      sort_order: 1
    }
  ],
  boq_items: [
    {
      item_code: 'BOQ-001',
      description: '',
      discipline: 'civil',
      phase: 'Mobilization',
      milestone_name: 'Mobilization',
      unit: 'lot',
      planned_quantity: '1',
      unit_rate: '0'
    }
  ]
};

const initialTask: ProjectTaskPayload = {
  name: '',
  milestone_id: null,
  dependency_task_id: null,
  owner_id: null,
  baseline_start_date: null,
  baseline_end_date: null,
  planned_start_date: null,
  planned_end_date: null,
  actual_start_date: null,
  actual_end_date: null,
  status: 'not_started',
  progress_percentage: 0,
  delay_reason: null,
  sort_order: 0
};

export function ProjectListPage() {
  const { user } = useAuth();
  const canManageProjects = user?.permissions?.includes('projects:manage');
  const [projects, setProjects] = useState<ProjectRecord[]>([]);
  const [total, setTotal] = useState(0);
  const [status, setStatus] = useState('');
  const [search, setSearch] = useState('');
  const debouncedSearch = useDebouncedSearch(search);
  const [form, setForm] = useState<ProjectPayload>(initialProject);
  const [users, setUsers] = useState<UserRecord[]>([]);
  const [timelineProjectId, setTimelineProjectId] = useState('');
  const [timeline, setTimeline] = useState<ProjectTimelineResponse | null>(null);
  const [taskForm, setTaskForm] = useState<ProjectTaskPayload>(initialTask);
  const [error, setError] = useState<string | null>(null);
  const [isLoading, setIsLoading] = useState(false);

  const filters = useMemo(
    () => ({
      status: status || undefined,
      search: debouncedSearch || undefined
    }),
    [debouncedSearch, status]
  );

  const loadProjects = useCallback(async () => {
    setIsLoading(true);
    setError(null);
    try {
      const response = await listProjects(filters);
      setProjects(response.items);
      setTotal(response.total);
      setTimelineProjectId((current) => current || response.items[0]?.id || '');
    } catch {
      setError('Unable to load projects.');
    } finally {
      setIsLoading(false);
    }
  }, [filters]);

  useEffect(() => {
    void loadProjects();
  }, [loadProjects]);

  useEffect(() => {
    if (!canManageProjects) {
      return;
    }
    listUsers({ active: true })
      .then((response) => setUsers(response.items))
      .catch(() => setUsers([]));
  }, [canManageProjects]);

  useEffect(() => {
    if (!timelineProjectId) {
      setTimeline(null);
      return;
    }
    getProjectTimeline(timelineProjectId)
      .then(setTimeline)
      .catch(() => setTimeline(null));
  }, [timelineProjectId]);

  async function handleCreate(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    setError(null);
    try {
      await createProject(form);
      setForm(initialProject);
      await loadProjects();
    } catch {
      setError('Unable to create project.');
    }
  }

  async function handleCreateTask(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (!timelineProjectId) {
      return;
    }
    setError(null);
    try {
      await createProjectTask(timelineProjectId, normalizeTaskPayload(taskForm));
      setTaskForm(initialTask);
      setTimeline(await getProjectTimeline(timelineProjectId));
    } catch {
      setError('Unable to create project task.');
    }
  }

  const milestone = form.milestones[0];
  const boqItem = form.boq_items[0];

  return (
    <div className="space-y-6">
      <div className="flex flex-col justify-between gap-4 sm:flex-row sm:items-end">
        <div>
          <p className="text-sm font-medium text-brand-600">Projects</p>
          <h2 className="text-2xl font-semibold text-theme-text-primary">Project Setup</h2>
        </div>
        <div className="grid gap-3 sm:grid-cols-2">
          <input
            className="rounded-md border border-theme-border bg-theme-card px-3 py-2 text-sm text-theme-text-primary"
            onChange={(event) => setSearch(event.target.value)}
            placeholder="Search projects"
            value={search}
          />
          <select
            className="rounded-md border border-theme-border bg-theme-card px-3 py-2 text-sm text-theme-text-primary"
            onChange={(event) => setStatus(event.target.value)}
            value={status}
          >
            <option value="">All statuses</option>
            <option value="planning">Planning</option>
            <option value="active">Active</option>
            <option value="on_hold">On hold</option>
            <option value="completed">Completed</option>
            <option value="cancelled">Cancelled</option>
          </select>
        </div>
      </div>

      {error ? <p className="alert-error rounded-md px-3 py-2 text-sm">{error}</p> : null}

      {canManageProjects ? (
        <section className="rounded-lg border border-theme-border bg-theme-card p-4 shadow-xs">
          <form className="grid gap-3 lg:grid-cols-4" onSubmit={handleCreate}>
            <input
              className="rounded-md border border-theme-border bg-theme-card px-3 py-2 text-sm text-theme-text-primary"
              onChange={(event) => setForm({ ...form, name: event.target.value })}
              placeholder="Project name"
              required
              value={form.name}
            />
            <input
              className="rounded-md border border-theme-border bg-theme-card px-3 py-2 text-sm text-theme-text-primary"
              onChange={(event) => setForm({ ...form, client_name: event.target.value })}
              placeholder="Client"
              value={form.client_name ?? ''}
            />
            <input
              className="rounded-md border border-theme-border bg-theme-card px-3 py-2 text-sm text-theme-text-primary"
              onChange={(event) => setForm({ ...form, location: event.target.value })}
              placeholder="Location"
              value={form.location ?? ''}
            />
            <input
              className="rounded-md border border-theme-border bg-theme-card px-3 py-2 text-sm text-theme-text-primary"
              onChange={(event) => setForm({ ...form, target_end_date: event.target.value })}
              required
              type="date"
              value={form.target_end_date}
            />
            <textarea
              className="rounded-md border border-theme-border bg-theme-card px-3 py-2 text-sm text-theme-text-primary lg:col-span-2"
              onChange={(event) => setForm({ ...form, scope_of_work: event.target.value })}
              placeholder="Scope of work"
              required
              value={form.scope_of_work}
            />
            <input
              className="rounded-md border border-theme-border bg-theme-card px-3 py-2 text-sm text-theme-text-primary"
              onChange={(event) =>
                setForm({ ...form, milestones: [{ ...milestone, name: event.target.value }] })
              }
              placeholder="Milestone"
              required
              value={milestone.name}
            />
            <input
              className="rounded-md border border-theme-border bg-theme-card px-3 py-2 text-sm text-theme-text-primary"
              onChange={(event) =>
                setForm({ ...form, boq_items: [{ ...boqItem, description: event.target.value }] })
              }
              placeholder="BOQ description"
              required
              value={boqItem.description}
            />
            <input
              className="rounded-md border border-theme-border bg-theme-card px-3 py-2 text-sm text-theme-text-primary"
              onChange={(event) =>
                setForm({
                  ...form,
                  boq_items: [{ ...boqItem, planned_quantity: event.target.value }]
                })
              }
              placeholder="Quantity"
              required
              type="number"
              value={boqItem.planned_quantity}
            />
            <input
              className="rounded-md border border-theme-border bg-theme-card px-3 py-2 text-sm text-theme-text-primary"
              onChange={(event) =>
                setForm({ ...form, boq_items: [{ ...boqItem, unit_rate: event.target.value }] })
              }
              placeholder="Rate"
              required
              type="number"
              value={boqItem.unit_rate}
            />
            <button
              className="rounded-md bg-brand-600 px-4 py-2 text-sm font-semibold text-white hover:bg-brand-700"
              type="submit"
            >
              Create project
            </button>
          </form>
        </section>
      ) : null}

      {canManageProjects ? (
        <section className="rounded-lg border border-theme-border bg-theme-card p-4 shadow-xs">
          <div className="mb-4 flex flex-col justify-between gap-3 sm:flex-row sm:items-center">
            <div>
              <h3 className="text-base font-semibold text-theme-text-primary">
                Task / Gantt Tracking
              </h3>
              <p className="text-sm text-theme-text-secondary">
                Baselines, dependencies, actuals, owners, and delay notes.
              </p>
            </div>
            <select
              className="rounded-md border border-theme-border bg-theme-card px-3 py-2 text-sm text-theme-text-primary"
              onChange={(event) => setTimelineProjectId(event.target.value)}
              value={timelineProjectId}
            >
              {projects.map((project) => (
                <option key={project.id} value={project.id}>
                  {project.code} - {project.name}
                </option>
              ))}
            </select>
          </div>

          <form className="grid gap-3 lg:grid-cols-4" onSubmit={handleCreateTask}>
            <input
              className="rounded-md border border-theme-border bg-theme-card px-3 py-2 text-sm text-theme-text-primary"
              onChange={(event) => setTaskForm({ ...taskForm, name: event.target.value })}
              placeholder="Task name"
              required
              value={taskForm.name}
            />
            <select
              className="rounded-md border border-theme-border bg-theme-card px-3 py-2 text-sm text-theme-text-primary"
              onChange={(event) => setTaskForm({ ...taskForm, milestone_id: event.target.value })}
              value={taskForm.milestone_id ?? ''}
            >
              <option value="">No milestone</option>
              {timeline?.milestones.map((milestone) => (
                <option key={milestone.id} value={milestone.id}>
                  {milestone.name}
                </option>
              ))}
            </select>
            <select
              className="rounded-md border border-theme-border bg-theme-card px-3 py-2 text-sm text-theme-text-primary"
              onChange={(event) =>
                setTaskForm({ ...taskForm, dependency_task_id: event.target.value })
              }
              value={taskForm.dependency_task_id ?? ''}
            >
              <option value="">No dependency</option>
              {timeline?.tasks.map((task) => (
                <option key={task.id} value={task.id}>
                  {task.name}
                </option>
              ))}
            </select>
            <select
              className="rounded-md border border-theme-border bg-theme-card px-3 py-2 text-sm text-theme-text-primary"
              onChange={(event) => setTaskForm({ ...taskForm, owner_id: event.target.value })}
              value={taskForm.owner_id ?? ''}
            >
              <option value="">Unassigned</option>
              {users.map((owner) => (
                <option key={owner.id} value={owner.id}>
                  {owner.full_name}
                </option>
              ))}
            </select>
            <input
              className="rounded-md border border-theme-border bg-theme-card px-3 py-2 text-sm text-theme-text-primary"
              onChange={(event) =>
                setTaskForm({ ...taskForm, baseline_start_date: event.target.value })
              }
              type="date"
              value={taskForm.baseline_start_date ?? ''}
            />
            <input
              className="rounded-md border border-theme-border bg-theme-card px-3 py-2 text-sm text-theme-text-primary"
              onChange={(event) =>
                setTaskForm({ ...taskForm, baseline_end_date: event.target.value })
              }
              type="date"
              value={taskForm.baseline_end_date ?? ''}
            />
            <input
              className="rounded-md border border-theme-border bg-theme-card px-3 py-2 text-sm text-theme-text-primary"
              onChange={(event) =>
                setTaskForm({ ...taskForm, actual_start_date: event.target.value })
              }
              type="date"
              value={taskForm.actual_start_date ?? ''}
            />
            <input
              className="rounded-md border border-theme-border bg-theme-card px-3 py-2 text-sm text-theme-text-primary"
              onChange={(event) =>
                setTaskForm({ ...taskForm, actual_end_date: event.target.value })
              }
              type="date"
              value={taskForm.actual_end_date ?? ''}
            />
            <select
              className="rounded-md border border-theme-border bg-theme-card px-3 py-2 text-sm text-theme-text-primary"
              onChange={(event) => setTaskForm({ ...taskForm, status: event.target.value })}
              value={taskForm.status}
            >
              <option value="not_started">Not started</option>
              <option value="in_progress">In progress</option>
              <option value="blocked">Blocked</option>
              <option value="completed">Completed</option>
              <option value="cancelled">Cancelled</option>
            </select>
            <input
              className="rounded-md border border-theme-border bg-theme-card px-3 py-2 text-sm text-theme-text-primary"
              max="100"
              min="0"
              onChange={(event) =>
                setTaskForm({ ...taskForm, progress_percentage: Number(event.target.value) })
              }
              placeholder="Progress %"
              type="number"
              value={taskForm.progress_percentage}
            />
            <input
              className="rounded-md border border-theme-border bg-theme-card px-3 py-2 text-sm text-theme-text-primary lg:col-span-2"
              onChange={(event) => setTaskForm({ ...taskForm, delay_reason: event.target.value })}
              placeholder="Delay reason"
              value={taskForm.delay_reason ?? ''}
            />
            <button
              className="rounded-md bg-brand-600 px-4 py-2 text-sm font-semibold text-white hover:bg-brand-700"
              type="submit"
            >
              Add task
            </button>
          </form>

          <div className="mt-4 overflow-x-auto">
            <table className="min-w-full divide-y divide-theme-border text-sm">
              <thead className="bg-theme-main text-left text-xs font-semibold uppercase text-theme-text-muted">
                <tr>
                  <th className="px-4 py-3">Task</th>
                  <th className="px-4 py-3">Owner</th>
                  <th className="px-4 py-3">Dependency</th>
                  <th className="px-4 py-3">Baseline</th>
                  <th className="px-4 py-3">Actual</th>
                  <th className="px-4 py-3">Progress</th>
                  <th className="px-4 py-3">Status</th>
                </tr>
              </thead>
              <tbody className="divide-y divide-theme-border">
                {timeline?.tasks.map((task) => (
                  <tr key={task.id}>
                    <td className="px-4 py-3">
                      <p className="font-medium text-theme-text-primary">{task.name}</p>
                      <p className="text-xs text-theme-text-muted">
                        {task.delay_reason || 'No delay notes'}
                      </p>
                    </td>
                    <td className="px-4 py-3">{ownerName(users, task.owner_id)}</td>
                    <td className="px-4 py-3">
                      {dependencyName(timeline, task.dependency_task_id)}
                    </td>
                    <td className="px-4 py-3">
                      {dateRange(task.baseline_start_date, task.baseline_end_date)}
                    </td>
                    <td className="px-4 py-3">
                      {dateRange(task.actual_start_date, task.actual_end_date)}
                    </td>
                    <td className="px-4 py-3">{task.progress_percentage}%</td>
                    <td className="px-4 py-3">
                      <span className="rounded-full bg-theme-card-elevated px-2 py-1 text-xs font-semibold text-theme-text-secondary">
                        {task.status.replace('_', ' ')}
                      </span>
                    </td>
                  </tr>
                ))}
                {!timeline?.tasks.length ? (
                  <tr>
                    <td className="px-4 py-6 text-center text-theme-text-muted" colSpan={7}>
                      No tasks yet.
                    </td>
                  </tr>
                ) : null}
              </tbody>
            </table>
          </div>
        </section>
      ) : null}

      <section className="overflow-hidden rounded-lg border border-theme-border bg-theme-card shadow-xs">
        <div className="border-b border-theme-border px-4 py-3 text-sm text-theme-text-secondary">
          {isLoading ? 'Loading projects' : `${total} projects`}
        </div>
        <div className="overflow-x-auto">
          <table className="min-w-full divide-y divide-theme-border text-sm">
            <thead className="bg-theme-main text-left text-xs font-semibold uppercase text-theme-text-muted">
              <tr>
                <th className="px-4 py-3">Project</th>
                <th className="px-4 py-3">Client</th>
                <th className="px-4 py-3">Deadline</th>
                <th className="px-4 py-3">Progress</th>
                <th className="px-4 py-3">Status</th>
              </tr>
            </thead>
            <tbody className="divide-y divide-theme-border">
              {projects.map((project) => (
                <tr key={project.id}>
                  <td className="px-4 py-3">
                    <p className="font-medium text-theme-text-primary">{project.name}</p>
                    <p className="text-xs text-theme-text-muted">{project.code}</p>
                  </td>
                  <td className="px-4 py-3">{project.client_name || '-'}</td>
                  <td className="px-4 py-3">{project.target_end_date}</td>
                  <td className="px-4 py-3">{project.progress_percentage}%</td>
                  <td className="px-4 py-3">
                    <span className="rounded-full bg-theme-card-elevated px-2 py-1 text-xs font-semibold text-theme-text-secondary">
                      {project.status.replace('_', ' ')}
                    </span>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </section>
    </div>
  );
}

function normalizeTaskPayload(payload: ProjectTaskPayload): ProjectTaskPayload {
  return {
    ...payload,
    milestone_id: payload.milestone_id || null,
    dependency_task_id: payload.dependency_task_id || null,
    owner_id: payload.owner_id || null,
    baseline_start_date: payload.baseline_start_date || null,
    baseline_end_date: payload.baseline_end_date || null,
    planned_start_date: payload.planned_start_date || null,
    planned_end_date: payload.planned_end_date || null,
    actual_start_date: payload.actual_start_date || null,
    actual_end_date: payload.actual_end_date || null,
    delay_reason: payload.delay_reason || null
  };
}

function ownerName(users: UserRecord[], ownerId: string | null | undefined): string {
  return users.find((user) => user.id === ownerId)?.full_name || '-';
}

function dependencyName(
  timeline: ProjectTimelineResponse,
  dependencyTaskId: string | null | undefined
): string {
  return timeline.tasks.find((task) => task.id === dependencyTaskId)?.name || '-';
}

function dateRange(start: string | null | undefined, end: string | null | undefined): string {
  if (!start && !end) {
    return '-';
  }
  return `${start || '-'} to ${end || '-'}`;
}
