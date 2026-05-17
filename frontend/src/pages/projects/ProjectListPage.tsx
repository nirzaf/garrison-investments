import { FormEvent, useCallback, useEffect, useMemo, useState } from 'react';

import {
  createProject,
  listProjects,
  type ProjectPayload,
  type ProjectRecord
} from '../../api/projects';
import { useAuth } from '../../context/useAuth';

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

export function ProjectListPage() {
  const { user } = useAuth();
  const canManageProjects = user?.permissions?.includes('projects:manage');
  const [projects, setProjects] = useState<ProjectRecord[]>([]);
  const [total, setTotal] = useState(0);
  const [status, setStatus] = useState('');
  const [search, setSearch] = useState('');
  const [form, setForm] = useState<ProjectPayload>(initialProject);
  const [error, setError] = useState<string | null>(null);
  const [isLoading, setIsLoading] = useState(false);

  const filters = useMemo(
    () => ({
      status: status || undefined,
      search: search || undefined
    }),
    [search, status]
  );

  const loadProjects = useCallback(async () => {
    setIsLoading(true);
    setError(null);
    try {
      const response = await listProjects(filters);
      setProjects(response.items);
      setTotal(response.total);
    } catch {
      setError('Unable to load projects.');
    } finally {
      setIsLoading(false);
    }
  }, [filters]);

  useEffect(() => {
    void loadProjects();
  }, [loadProjects]);

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
        <section className="rounded-lg border border-theme-border bg-theme-card p-4 shadow-sm">
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

      <section className="overflow-hidden rounded-lg border border-theme-border bg-theme-card shadow-sm">
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
