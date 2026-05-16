import { useQuery } from '@tanstack/react-query';
import { Download } from 'lucide-react';

import { downloadExport, getAnalyticsSummary } from '../../api/analytics';
import { EmptyState } from '../../components/shared/EmptyState';

export function AnalyticsPage() {
  const summary = useQuery({ queryKey: ['analytics-summary'], queryFn: getAnalyticsSummary });
  const maxProgress = Math.max(
    1,
    ...(summary.data?.projects.map((project) => Number(project.progress_percentage)) ?? [1])
  );

  return (
    <section className="space-y-6">
      <div className="flex flex-col justify-between gap-3 sm:flex-row sm:items-end">
        <div>
          <p className="text-sm font-medium text-brand-700">Management</p>
          <h2 className="text-2xl font-semibold text-slate-950">Analytics And Exports</h2>
        </div>
        <div className="flex gap-2">
          <button
            className="inline-flex items-center gap-2 rounded-md border border-slate-300 px-3 py-2 text-sm font-semibold text-slate-700"
            onClick={() => void downloadExport('project-progress')}
            type="button"
          >
            <Download className="h-4 w-4" />
            Project XLSX
          </button>
          <button
            className="inline-flex items-center gap-2 rounded-md border border-slate-300 px-3 py-2 text-sm font-semibold text-slate-700"
            onClick={() => void downloadExport('material-usage')}
            type="button"
          >
            <Download className="h-4 w-4" />
            Material XLSX
          </button>
        </div>
      </div>

      {summary.data ? (
        <div className="grid gap-4 lg:grid-cols-2">
          <div className="rounded-lg border border-slate-200 bg-white p-4">
            <h3 className="text-base font-semibold text-slate-950">Project progress</h3>
            <div className="mt-4 space-y-3">
              {summary.data.projects.map((project) => (
                <div key={project.project_id}>
                  <div className="mb-1 flex justify-between text-sm">
                    <span className="font-medium text-slate-700">{project.project_name}</span>
                    <span className="text-slate-500">{project.progress_percentage}%</span>
                  </div>
                  <div className="h-2 rounded bg-slate-100">
                    <div
                      className="h-2 rounded bg-brand-700"
                      style={{
                        width: `${(Number(project.progress_percentage) / maxProgress) * 100}%`
                      }}
                    />
                  </div>
                  <p className="mt-1 text-xs text-slate-500">
                    {project.report_count} reports, {project.invoice_total} invoiced
                  </p>
                </div>
              ))}
            </div>
          </div>

          <div className="rounded-lg border border-slate-200 bg-white p-4">
            <h3 className="text-base font-semibold text-slate-950">Material usage</h3>
            {summary.data.material_usage.length > 0 ? (
              <div className="mt-4 divide-y divide-slate-100">
                {summary.data.material_usage.map((item) => (
                  <div className="flex justify-between py-3 text-sm" key={item.item_id}>
                    <span className="font-medium text-slate-700">{item.item_name}</span>
                    <span className="text-slate-500">
                      {item.issued_quantity} issued / {item.consumed_quantity} consumed
                    </span>
                  </div>
                ))}
              </div>
            ) : (
              <EmptyState
                title="No material usage"
                description="Inventory movements will appear in this summary."
              />
            )}
          </div>
        </div>
      ) : (
        <EmptyState title="Loading analytics" description="Management summaries are loading." />
      )}
    </section>
  );
}
