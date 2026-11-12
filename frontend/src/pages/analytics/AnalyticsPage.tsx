import { keepPreviousData, useQuery } from '@tanstack/react-query';
import { Download } from 'lucide-react';
import { useRef, useState, type FormEvent } from 'react';
import { Bar, BarChart, CartesianGrid, ResponsiveContainer, Tooltip, XAxis, YAxis } from 'recharts';

import {
  downloadExport,
  getAnalyticsSummary,
  type AnalyticsExport,
  type AnalyticsFilters
} from '../../api/analytics';
import { formatApiError } from '../../api/errors';
import { listProjects } from '../../api/projects';
import { EmptyState } from '../../components/shared/EmptyState';
import { useDebouncedSearch } from '../../useDebouncedSearch';

const exportOptions: [AnalyticsExport, string][] = [
  ['project-progress', 'Project XLSX'],
  ['material-usage', 'Material XLSX'],
  ['management-summary', 'Summary PDF']
];

const filterFields = [
  ['date_from', 'Activity from', 'date'],
  ['date_to', 'Activity through', 'date'],
  ['location', 'Project-panel location', 'text'],
  ['department', 'Project scope or material category', 'text']
] as const;

export function AnalyticsPage() {
  const [draft, setDraft] = useState<AnalyticsFilters>({});
  const [filters, setFilters] = useState<AnalyticsFilters>({});
  const [projectSearch, setProjectSearch] = useState('');
  const [selectedProjectName, setSelectedProjectName] = useState('');
  const [dateError, setDateError] = useState<string | null>(null);
  const [exportError, setExportError] = useState<string | null>(null);
  const exporting = useRef(new Set<AnalyticsExport>());
  const [pending, setPending] = useState<AnalyticsExport[]>([]);
  const search = useDebouncedSearch(projectSearch);
  const projects = useQuery({
    queryKey: ['analytics-projects', search],
    queryFn: () => listProjects({ search: search || undefined })
  });
  const summary = useQuery({
    queryKey: ['analytics-summary', filters],
    queryFn: () => getAnalyticsSummary(filters),
    placeholderData: keepPreviousData
  });

  function applyFilters(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (draft.date_from && draft.date_to && draft.date_from > draft.date_to) {
      setDateError('Choose an end date on or after the start date.');
      return;
    }
    setDateError(null);
    setFilters({
      project_id: draft.project_id || undefined,
      date_from: draft.date_from || undefined,
      date_to: draft.date_to || undefined,
      location: draft.location?.trim() || undefined,
      department: draft.department?.trim() || undefined
    });
  }

  async function exportData(path: AnalyticsExport) {
    if (exporting.current.has(path)) return;
    exporting.current.add(path);
    setPending([...exporting.current]);
    setExportError(null);
    try {
      await downloadExport(path, filters);
    } catch (cause) {
      setExportError(formatApiError(cause, 'Unable to download the export.'));
    } finally {
      exporting.current.delete(path);
      setPending([...exporting.current]);
    }
  }

  const progressData =
    summary.data?.projects.map((project) => ({
      name: project.project_name,
      Progress: Number(project.progress_percentage),
      Reports: project.report_count
    })) ?? [];

  const materialData =
    summary.data?.material_usage.map((item) => ({
      name: item.item_name,
      Issued: Number(item.issued_quantity),
      Consumed: Number(item.consumed_quantity)
    })) ?? [];

  return (
    <section className="space-y-6">
      <div className="flex flex-col justify-between gap-3 sm:flex-row sm:items-end">
        <div>
          <p className="text-sm font-medium text-brand-600">Management</p>
          <h2 className="text-2xl font-semibold text-theme-text-primary">Analytics And Exports</h2>
        </div>
        <div className="flex flex-wrap gap-2">
          {exportOptions.map(([path, label]) => (
            <button
              className="inline-flex items-center gap-2 rounded-md border border-theme-border px-3 py-2 text-sm font-semibold text-theme-text-secondary disabled:opacity-50"
              disabled={pending.includes(path) || summary.isPlaceholderData}
              key={path}
              onClick={() => void exportData(path)}
              type="button"
            >
              <Download className="h-4 w-4" />
              {pending.includes(path) ? 'Downloading…' : label}
            </button>
          ))}
        </div>
      </div>

      <form
        className="space-y-3 rounded-lg border border-theme-border bg-theme-card p-4"
        onSubmit={applyFilters}
      >
        <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-3">
          <label className="text-sm">
            Search projects
            <input
              className="form-field"
              value={projectSearch}
              onChange={(event) => setProjectSearch(event.target.value)}
            />
          </label>
          <label className="text-sm">
            Project
            <select
              className="form-field"
              value={draft.project_id ?? ''}
              onChange={(event) => {
                const project = projects.data?.items.find((item) => item.id === event.target.value);
                setSelectedProjectName(project?.name ?? '');
                setDraft({ ...draft, project_id: event.target.value });
              }}
            >
              <option value="">All accessible projects</option>
              {draft.project_id &&
                !projects.data?.items.some((item) => item.id === draft.project_id) && (
                  <option value={draft.project_id}>{selectedProjectName}</option>
                )}
              {projects.data?.items.map((item) => (
                <option value={item.id} key={item.id}>
                  {item.name}
                </option>
              ))}
            </select>
          </label>
          {filterFields.map(([field, label, type]) => (
            <label className="text-sm" key={field}>
              {label}
              <input
                className="form-field"
                type={type}
                maxLength={100}
                value={draft[field] ?? ''}
                onChange={(event) => setDraft({ ...draft, [field]: event.target.value })}
              />
            </label>
          ))}
        </div>
        {projects.isPending && <p role="status">Loading projects…</p>}
        {projects.isError && <p role="alert">Unable to load projects.</p>}
        {dateError && <p role="alert">{dateError}</p>}
        <div className="flex gap-3">
          <button className="form-button" type="submit">
            Apply filters
          </button>
          <button
            className="form-button"
            type="button"
            onClick={() => {
              setDraft({});
              setFilters({});
              setDateError(null);
              setProjectSearch('');
            }}
          >
            Clear
          </button>
        </div>
        <p className="text-sm text-theme-text-muted">
          Activity dates apply to reports and material movements. Progress, invoiced and paid totals
          are cumulative. Project-panel location applies to the project chart and project export.
        </p>
      </form>
      {exportError && (
        <p role="alert" className="alert-error px-3 py-2">
          {exportError}
        </p>
      )}
      {summary.isFetching && summary.data && (
        <p role="status">Refreshing analytics. The previous results are still visible.</p>
      )}
      {summary.isError && (
        <div className="alert-error px-3 py-2" role="alert">
          {formatApiError(summary.error, 'Unable to load analytics.')}
          <button className="ml-3 underline" type="button" onClick={() => void summary.refetch()}>
            Retry
          </button>
        </div>
      )}
      {summary.data ? (
        <div className="grid gap-4 lg:grid-cols-2">
          <div className="rounded-lg border border-theme-border bg-theme-card p-4">
            <h3 className="text-base font-semibold text-theme-text-primary">Project progress</h3>
            {progressData.length > 0 ? (
              <div className="mt-4">
                <ResponsiveContainer height={300} width="100%">
                  <BarChart data={progressData} margin={{ top: 4, right: 4, left: 0, bottom: 4 }}>
                    <CartesianGrid strokeDasharray="3 3" />
                    <XAxis dataKey="name" fontSize={11} tickLine={false} />
                    <YAxis domain={[0, 100]} fontSize={11} tickLine={false} unit="%" />
                    <Tooltip />
                    <Bar dataKey="Progress" fill="#0f766e" radius={[4, 4, 0, 0]} />
                  </BarChart>
                </ResponsiveContainer>
                <div className="mt-2 space-y-2">
                  {summary.data.projects.map((project) => (
                    <p className="text-xs text-theme-text-muted" key={project.project_id}>
                      {project.project_name}: {project.report_count} reports,{' '}
                      {project.invoice_total} invoiced
                    </p>
                  ))}
                </div>
              </div>
            ) : (
              <EmptyState
                title="No project data"
                description="Project progress will appear once reports are submitted."
              />
            )}
          </div>

          <div className="rounded-lg border border-theme-border bg-theme-card p-4">
            <h3 className="text-base font-semibold text-theme-text-primary">Material usage</h3>
            {materialData.length > 0 ? (
              <div className="mt-4">
                <ResponsiveContainer height={300} width="100%">
                  <BarChart data={materialData} margin={{ top: 4, right: 4, left: 0, bottom: 4 }}>
                    <CartesianGrid strokeDasharray="3 3" />
                    <XAxis dataKey="name" fontSize={11} tickLine={false} />
                    <YAxis fontSize={11} tickLine={false} />
                    <Tooltip />
                    <Bar dataKey="Issued" fill="#0f766e" radius={[4, 4, 0, 0]} />
                    <Bar dataKey="Consumed" fill="#f59e0b" radius={[4, 4, 0, 0]} />
                  </BarChart>
                </ResponsiveContainer>
              </div>
            ) : (
              <EmptyState
                title="No material usage"
                description="Inventory movements will appear in this summary."
              />
            )}
          </div>
        </div>
      ) : summary.isPending ? (
        <EmptyState title="Loading analytics" description="Management summaries are loading." />
      ) : null}
    </section>
  );
}
