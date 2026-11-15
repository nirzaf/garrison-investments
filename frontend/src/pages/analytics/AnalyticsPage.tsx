import { useQuery } from '@tanstack/react-query';
import { isAxiosError } from 'axios';
import { Download } from 'lucide-react';
import { lazy, Suspense, useRef, useState, type FormEvent } from 'react';

import {
  downloadExport,
  getAnalyticsSummary,
  type AnalyticsExport,
  type AnalyticsFilters,
  type AnalyticsSummary
} from '../../api/analytics';
import { labelledAmount, useBusinessPolicy } from '../../api/businessPolicy';
import { formatApiError } from '../../api/errors';
import { listProjects } from '../../api/projects';
import { EmptyState } from '../../components/shared/EmptyState';
import { ErrorBoundary } from '../../components/shared/ErrorBoundary';
import { useAuth } from '../../context/useAuth';
import { useDebouncedSearch } from '../../useDebouncedSearch';

const ProjectProgressChart = lazy(() =>
  import('./AnalyticsCharts').then(({ ProjectProgressChart }) => ({ default: ProjectProgressChart }))
);
const MaterialUsageChart = lazy(() =>
  import('./AnalyticsCharts').then(({ MaterialUsageChart }) => ({ default: MaterialUsageChart }))
);
const chartLoading = <p className="min-h-[300px]" role="status">Loading chart…</p>;

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
  const { user } = useAuth();
  const policy = useBusinessPolicy();
  const [lastSuccessful, setLastSuccessful] = useState<{
    ownerId: string | undefined;
    data: AnalyticsSummary;
    filters: AnalyticsFilters;
    projectName: string;
  } | null>(null);
  const [draft, setDraft] = useState<AnalyticsFilters>({});
  const [filters, setFilters] = useState<AnalyticsFilters>({});
  const [projectSearch, setProjectSearch] = useState('');
  const [selectedProjectName, setSelectedProjectName] = useState('');
  const [appliedProjectName, setAppliedProjectName] = useState('');
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
    queryFn: () => getAnalyticsSummary(filters)
  });

  const failureStatus = isAxiosError(summary.error) ? summary.error.response?.status : undefined;
  const accessDenied = failureStatus === 401 || failureStatus === 403;
  const previous = lastSuccessful?.ownerId === user?.id ? lastSuccessful : null;
  if ((accessDenied || !previous) && lastSuccessful) {
    setLastSuccessful(null);
  } else if (
    summary.isSuccess &&
    (previous?.data !== summary.data || previous.filters !== filters)
  ) {
    setLastSuccessful({
      ownerId: user?.id,
      data: summary.data,
      filters,
      projectName: appliedProjectName
    });
  }
  const displayed = accessDenied ? undefined : (summary.data ?? previous?.data);
  const showingPrevious = displayed !== undefined && (summary.isPending || summary.isError);

  function applyFilters(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (draft.date_from && draft.date_to && draft.date_from > draft.date_to) {
      setDateError('Choose an end date on or after the start date.');
      return;
    }
    setDateError(null);
    setAppliedProjectName(draft.project_id ? selectedProjectName : '');
    setFilters({
      project_id: draft.project_id || undefined,
      date_from: draft.date_from || undefined,
      date_to: draft.date_to || undefined,
      location: draft.location?.trim() || undefined,
      department: draft.department?.trim() || undefined
    });
  }

  async function exportData(path: AnalyticsExport) {
    if (!summary.isSuccess || exporting.current.has(path)) return;
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
    displayed?.projects.map((project) => ({
      name: project.project_name,
      Progress: Number(project.progress_percentage)
    })) ?? [];

  const materialData =
    displayed?.material_usage.map((item) => ({
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
              disabled={pending.includes(path) || !summary.isSuccess}
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
              setAppliedProjectName('');
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
      {showingPrevious && previous && (
        <p role="status">
          {summary.isFetching ? 'Refreshing analytics. ' : ''}
          Showing the last successful results for{' '}
          {[
            previous.projectName || 'all accessible projects',
            previous.filters.date_from && `from ${previous.filters.date_from}`,
            previous.filters.date_to && `through ${previous.filters.date_to}`,
            previous.filters.location && `location ${previous.filters.location}`,
            previous.filters.department && `scope or category ${previous.filters.department}`
          ]
            .filter(Boolean)
            .join(' · ')}
          .
        </p>
      )}
      {summary.isFetching && !showingPrevious && summary.data && (
        <p role="status">Refreshing analytics.</p>
      )}
      {summary.isError && (
        <div className="alert-error px-3 py-2" role="alert">
          {formatApiError(summary.error, 'Unable to load analytics.')}
          <button className="ml-3 underline" type="button" onClick={() => void summary.refetch()}>
            Retry
          </button>
        </div>
      )}
      {displayed ? (
        <div className="grid gap-4 lg:grid-cols-2">
          <div className="rounded-lg border border-theme-border bg-theme-card p-4">
            <h3 className="text-base font-semibold text-theme-text-primary">Project progress</h3>
            {progressData.length > 0 ? (
              <div className="mt-4">
                <ErrorBoundary>
                  <Suspense fallback={chartLoading}>
                    <ProjectProgressChart data={progressData} />
                  </Suspense>
                </ErrorBoundary>
                <div className="mt-2 space-y-2">
                  {displayed.projects.map((project) => (
                    <p className="text-xs text-theme-text-muted" key={project.project_id}>
                      {project.project_name}: {project.report_count} reports,{' '}
                      {project.invoice_total == null
                        ? 'invoice total unavailable'
                        : `${labelledAmount(project.invoice_total, policy.data?.business_currency)} invoiced`}
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
                <ErrorBoundary>
                  <Suspense fallback={chartLoading}>
                    <MaterialUsageChart data={materialData} />
                  </Suspense>
                </ErrorBoundary>
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
