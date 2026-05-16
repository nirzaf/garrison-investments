import { useQuery } from '@tanstack/react-query';

import { getDashboardSummary } from '../../api/dashboard';
import { EmptyState } from '../../components/shared/EmptyState';

export function DashboardPage() {
  const { data, isLoading } = useQuery({
    queryKey: ['dashboard-summary'],
    queryFn: getDashboardSummary,
    refetchInterval: 180_000,
    retry: 1
  });

  return (
    <section className="space-y-8">
      <div className="max-w-3xl">
        <p className="text-sm font-medium text-brand-700">Operational overview</p>
        <h2 className="mt-2 text-2xl font-semibold tracking-normal text-slate-950 sm:text-3xl">
          Launch Operations
        </h2>
        <p className="mt-3 text-base leading-7 text-slate-600">
          Review pending approvals, recent reports, active projects, and unread workflow alerts.
        </p>
      </div>

      <div className="grid gap-4 md:grid-cols-2 xl:grid-cols-5">
        <StatusPanel
          label="Active projects"
          value={isLoading ? '...' : (data?.active_projects ?? 0)}
        />
        <StatusPanel
          label="Pending reports"
          value={isLoading ? '...' : (data?.pending_reports ?? 0)}
        />
        <StatusPanel
          label="Approved reports"
          value={isLoading ? '...' : (data?.approved_reports ?? 0)}
        />
        <StatusPanel
          label="Pending documents"
          value={isLoading ? '...' : (data?.pending_documents ?? 0)}
        />
        <StatusPanel
          label="Unread alerts"
          value={isLoading ? '...' : (data?.unread_notifications ?? 0)}
        />
      </div>

      {data?.recent_activity.length ? (
        <section className="rounded-lg border border-slate-200 bg-white p-4 shadow-sm">
          <h3 className="text-base font-semibold text-slate-950">Recent Activity</h3>
          <div className="mt-3 divide-y divide-slate-100">
            {data.recent_activity.map((item) => (
              <p className="py-2 text-sm text-slate-600" key={item}>
                {item}
              </p>
            ))}
          </div>
        </section>
      ) : (
        <EmptyState
          description="Operational activity will appear after reports or approvals are created."
          title="No recent activity"
        />
      )}
    </section>
  );
}

function StatusPanel({ label, value }: { label: string; value: number | string }) {
  return (
    <div className="rounded-lg border border-slate-200 bg-white p-4 shadow-sm">
      <p className="text-sm font-medium text-slate-500">{label}</p>
      <p className="mt-2 text-xl font-semibold text-slate-950">{value}</p>
    </div>
  );
}
