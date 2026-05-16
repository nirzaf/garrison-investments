import { useQuery } from '@tanstack/react-query';
import { Download } from 'lucide-react';
import { Bar, BarChart, CartesianGrid, ResponsiveContainer, Tooltip, XAxis, YAxis } from 'recharts';

import { downloadExport, getAnalyticsSummary } from '../../api/analytics';
import { EmptyState } from '../../components/shared/EmptyState';

export function AnalyticsPage() {
  const summary = useQuery({
    queryKey: ['analytics-summary'],
    queryFn: () => getAnalyticsSummary()
  });

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
        <div className="flex gap-2">
          <button
            className="inline-flex items-center gap-2 rounded-md border border-theme-border px-3 py-2 text-sm font-semibold text-theme-text-secondary"
            onClick={() => void downloadExport('project-progress')}
            type="button"
          >
            <Download className="h-4 w-4" />
            Project XLSX
          </button>
          <button
            className="inline-flex items-center gap-2 rounded-md border border-theme-border px-3 py-2 text-sm font-semibold text-theme-text-secondary"
            onClick={() => void downloadExport('material-usage')}
            type="button"
          >
            <Download className="h-4 w-4" />
            Material XLSX
          </button>
          <button
            className="inline-flex items-center gap-2 rounded-md border border-theme-border px-3 py-2 text-sm font-semibold text-theme-text-secondary"
            onClick={() => void downloadExport('management-summary')}
            type="button"
          >
            <Download className="h-4 w-4" />
            Summary PDF
          </button>
        </div>
      </div>

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
                      {project.project_name}: {project.report_count} reports, {project.invoice_total}{' '}
                      invoiced
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
      ) : (
        <EmptyState title="Loading analytics" description="Management summaries are loading." />
      )}
    </section>
  );
}
