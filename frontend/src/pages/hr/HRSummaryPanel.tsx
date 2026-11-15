import { useInfiniteQuery, useQuery } from '@tanstack/react-query';
import { type FormEvent, useState } from 'react';

import { formatApiError } from '../../api/errors';
import {
  downloadHrSummary,
  getHrSummary,
  listHrReportSites,
  type DepartmentRecord,
  type HrReportFilters,
  type HrReportFormat
} from '../../api/hr';
import { useAuth } from '../../context/useAuth';
import { hrButtonClass, hrInputClass } from './HRAccessForms';

const SITES_PER_PAGE = 50;
const FORMATS = ['xlsx', 'csv', 'pdf'] as const;

export function HRSummaryPanel({ departments }: { departments: DepartmentRecord[] }) {
  const { user } = useAuth();
  const identity = [user?.id, user?.role];
  const [filters, setFilters] = useState<HrReportFilters>({});
  const [filterError, setFilterError] = useState('');
  const [exportError, setExportError] = useState('');
  const [download, setDownload] = useState<HrReportFormat | null>(null);
  const summary = useQuery({
    queryKey: ['hr', 'report-summary', ...identity, filters],
    queryFn: ({ signal }) => getHrSummary(filters, signal)
  });
  const sites = useInfiniteQuery({
    queryKey: ['hr', 'report-sites', ...identity],
    queryFn: ({ pageParam, signal }) => listHrReportSites(pageParam, SITES_PER_PAGE, signal),
    initialPageParam: 0,
    getNextPageParam: (page, _pages, offset) =>
      page.has_more ? offset + SITES_PER_PAGE : undefined
  });

  function applyFilters(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    const fields = new FormData(event.currentTarget);
    const field = (name: string) => String(fields.get(name) ?? '') || undefined;
    const start = field('date_from');
    const end = field('date_to');
    if (Boolean(start) !== Boolean(end) || (start && end && end < start)) {
      setFilterError('Choose an activity start and end date in order, or leave both blank.');
      return;
    }
    setFilterError('');
    setExportError('');
    setFilters({
      project_id: field('project_id'),
      department_id: field('department_id'),
      date_from: start,
      date_to: end
    });
  }

  async function exportReport(format: HrReportFormat) {
    if (download || !summary.data || summary.isFetching) return;
    setDownload(format);
    setExportError('');
    try {
      await downloadHrSummary(format, filters);
    } catch (error) {
      setExportError(formatApiError(error, 'Could not download the HR summary.'));
    } finally {
      setDownload(null);
    }
  }

  const data = summary.data;
  const metrics = [
    ['Total employees', data?.total_employees],
    ['Active workforce', data?.active_employees],
    ['Onboarding backlog', data?.open_onboarding_cases],
    ['Pending access requests', data?.pending_access_requests],
    ['Pending leave approvals', data?.pending_leave_requests],
    ['Credentials due', data?.credentials_due],
    ['Attendance exceptions', data?.attendance_exceptions],
    ['Probation reviews due', data?.probation_reviews_due],
    ['Scheduled training', data?.training_sessions_due],
    ['Separated employees', data?.separated_employees]
  ] as const;

  return (
    <section aria-label="HR summary" className="space-y-4">
      <form
        className="flex flex-wrap items-end gap-3"
        onSubmit={applyFilters}
        onReset={() => {
          setFilters({});
          setFilterError('');
          setExportError('');
        }}
      >
        <label>
          Primary site
          <select name="project_id" defaultValue="" className={hrInputClass}>
            <option value="">All primary sites</option>
            {sites.data?.pages
              .flatMap((page) => page.items)
              .map((site) => (
                <option key={site.id} value={site.id}>
                  {site.name}
                </option>
              ))}
          </select>
        </label>
        {sites.hasNextPage && (
          <button
            type="button"
            className={hrButtonClass}
            disabled={sites.isFetchingNextPage}
            onClick={() => void sites.fetchNextPage()}
          >
            Load more sites
          </button>
        )}
        <label>
          Department
          <select name="department_id" defaultValue="" className={hrInputClass}>
            <option value="">All departments</option>
            {departments.map((department) => (
              <option key={department.id} value={department.id}>
                {department.name}
              </option>
            ))}
          </select>
        </label>
        <label>
          Activity start date <input name="date_from" type="date" className={hrInputClass} />
        </label>
        <label>
          Activity end date <input name="date_to" type="date" className={hrInputClass} />
        </label>
        <button type="submit" className={hrButtonClass} disabled={download !== null}>
          Apply report filters
        </button>
        <button type="reset" className={hrButtonClass} disabled={download !== null}>
          Clear filters
        </button>
      </form>
      {sites.isError && (
        <p role="alert">{formatApiError(sites.error, 'Could not load primary sites.')}</p>
      )}
      {filterError && <p role="alert">{filterError}</p>}
      {summary.isFetching && <p role="status">Loading HR summary…</p>}
      {summary.isError && (
        <div>
          <p role="alert">{formatApiError(summary.error, 'Could not load the HR summary.')}</p>
          <button type="button" className={hrButtonClass} onClick={() => void summary.refetch()}>
            Retry summary
          </button>
        </div>
      )}
      {data && (
        <>
          <div className="space-y-1 text-sm text-theme-text-muted">
            <p>
              Workforce and open queues as of {data.as_of} ({data.timezone}).
            </p>
            <p>
              Attendance {data.attendance_window.date_from} to {data.attendance_window.date_to}. Due
              dates {data.due_window.date_from} to {data.due_window.date_to}.
            </p>
          </div>
          <dl className="grid gap-4 sm:grid-cols-2 lg:grid-cols-4">
            {metrics
              .filter(([, count]) => count != null)
              .map(([label, count]) => (
                <div
                  key={label}
                  className="rounded-lg border border-theme-border bg-theme-card p-4"
                >
                  <dt className="text-sm text-theme-text-muted">{label}</dt>
                  <dd className="mt-1 text-2xl font-semibold text-theme-text-primary">{count}</dd>
                </div>
              ))}
          </dl>
          <div className="flex flex-wrap gap-3">
            {FORMATS.map((format) => (
              <button
                key={format}
                type="button"
                disabled={download !== null || summary.isFetching || summary.isError}
                className={hrButtonClass}
                onClick={() => void exportReport(format)}
              >
                {download === format
                  ? 'Preparing download…'
                  : `Download summary (${format.toUpperCase()})`}
              </button>
            ))}
          </div>
        </>
      )}
      {exportError && <p role="alert">{exportError}</p>}
    </section>
  );
}
