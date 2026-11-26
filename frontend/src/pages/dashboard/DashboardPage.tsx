import { useState } from 'react';
import { useQuery } from '@tanstack/react-query';
import { Link } from 'react-router-dom';

import {
  getDashboardSummary,
  getUpcomingAnniversaries,
  getUpcomingBirthdays
} from '../../api/dashboard';
import { siteAttendanceRoles } from '../../api/siteAttendance';
import { useAuth } from '../../context/useAuth';
import { EmptyState } from '../../components/shared/EmptyState';

export function DashboardPage() {
  const { user } = useAuth();
  const [birthdayOffset, setBirthdayOffset] = useState(0);
  const [anniversaryOffset, setAnniversaryOffset] = useState(0);
  const birthdayQuery = useQuery({
    queryKey: ['dashboard-celebrations', user?.id, 'birthdays', birthdayOffset],
    queryFn: () => getUpcomingBirthdays(birthdayOffset),
    enabled: Boolean(user?.id),
    refetchOnWindowFocus: true,
    refetchInterval: 300_000,
    retry: 1
  });
  const anniversaryQuery = useQuery({
    queryKey: ['dashboard-celebrations', user?.id, 'anniversaries', anniversaryOffset],
    queryFn: () => getUpcomingAnniversaries(anniversaryOffset),
    enabled: Boolean(user?.id),
    refetchOnWindowFocus: true,
    refetchInterval: 300_000,
    retry: 1
  });
  const { data, isLoading } = useQuery({
    queryKey: ['dashboard-summary'],
    queryFn: getDashboardSummary,
    refetchInterval: 180_000,
    retry: 1
  });

  return (
    <section className="space-y-8">
      <div className="max-w-3xl">
        <p className="text-sm font-medium text-brand-600">Operational overview</p>
        <h2 className="mt-2 text-2xl font-semibold tracking-normal text-theme-text-primary sm:text-3xl">
          Launch Operations
        </h2>
        <p className="mt-3 text-base leading-7 text-theme-text-secondary">
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

      {user && siteAttendanceRoles.has(user.role) && (
        <Link className="text-brand-600 underline" to="/hr/site-attendance">Site attendance</Link>
      )}

      {data?.site_operations && (
        <section className="space-y-3">
          <h3 className="font-semibold">Site workflow status</h3>
          <div className="grid gap-4 sm:grid-cols-2 lg:grid-cols-3">
            <StatusPanel label="Confirmed site updates" value={data.site_operations.confirmed_progress} />
            <StatusPanel label="Site updates awaiting review" value={data.site_operations.progress_awaiting_review} />
            <StatusPanel label="Material requests awaiting review" value={data.site_operations.material_requests_awaiting_review} />
            <StatusPanel label="Registrations awaiting engineer review" value={data.site_operations.registrations_awaiting_review} />
            <StatusPanel label="Confirmed inventory registrations" value={data.site_operations.confirmed_registrations} />
            <StatusPanel label="Confirmed site workers present today" value={data.site_operations.confirmed_present_today} />
          </div>
        </section>
      )}

      <div className="grid gap-4 lg:grid-cols-2">
        <CelebrationCard
          title="Upcoming birthdays — 7 days"
          query={birthdayQuery}
          offset={birthdayOffset}
          setOffset={setBirthdayOffset}
          renderItem={(person) => (
            <li className="flex justify-between gap-3 py-2" key={`${person.month}-${person.day}-${person.name}`}>
              <span>{person.name}</span>
              <time dateTime={`--${String(person.month).padStart(2, '0')}-${String(person.day).padStart(2, '0')}`}>
                {formatDayMonth(person.month, person.day)}
              </time>
            </li>
          )}
          items={birthdayQuery.data?.items ?? []}
          total={birthdayQuery.data?.total ?? 0}
        />
        <CelebrationCard
          title="Work anniversaries — 30 days"
          query={anniversaryQuery}
          offset={anniversaryOffset}
          setOffset={setAnniversaryOffset}
          renderItem={(person) => (
            <li className="flex justify-between gap-3 py-2" key={`${person.month}-${person.day}-${person.name}-${person.completed_years}`}>
              <span>{person.name}</span>
              <span>{formatDayMonth(person.month, person.day)} · {person.completed_years} {person.completed_years === 1 ? 'year' : 'years'}</span>
            </li>
          )}
          items={anniversaryQuery.data?.items ?? []}
          total={anniversaryQuery.data?.total ?? 0}
        />
      </div>

      {data?.recent_activity.length ? (
        <section className="rounded-lg border border-theme-border bg-theme-card p-4 shadow-xs">
          <h3 className="text-base font-semibold text-theme-text-primary">Recent Activity</h3>
          <div className="mt-3 divide-y divide-theme-border">
            {data.recent_activity.map((item) => (
              <p className="py-2 text-sm text-theme-text-secondary" key={item}>
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

function formatDayMonth(month: number, day: number): string {
  return new Intl.DateTimeFormat(undefined, {
    day: 'numeric', month: 'short', timeZone: 'UTC'
  }).format(new Date(Date.UTC(2000, month - 1, day, 12)));
}

type CelebrationCardProps<T> = {
  title: string;
  query: { isPending: boolean; isError: boolean; refetch: () => Promise<unknown> };
  offset: number;
  setOffset: (offset: number) => void;
  items: T[];
  total: number;
  renderItem: (item: T) => React.ReactNode;
};

function CelebrationCard<T>({
  title, query, offset, setOffset, items, total, renderItem
}: CelebrationCardProps<T>) {
  const pageSize = 25;
  return (
    <section aria-label={title} className="rounded-lg border border-theme-border bg-theme-card p-4 shadow-xs">
      <h3 className="font-semibold text-theme-text-primary">{title}</h3>
      {query.isPending && <p role="status" className="mt-3 text-sm">Loading…</p>}
      {query.isError && (
        <p role="alert" className="mt-3 text-sm">
          Could not load this list.{' '}
          <button className="text-brand-600 underline" onClick={() => void query.refetch()} type="button">Retry</button>
        </p>
      )}
      {!query.isPending && !query.isError && items.length === 0 && (
        <p className="mt-3 text-sm text-theme-text-secondary">No upcoming dates.</p>
      )}
      {items.length > 0 && <ul className="mt-2 divide-y divide-theme-border">{items.map(renderItem)}</ul>}
      {(offset > 0 || offset + pageSize < total) && (
        <nav aria-label={`${title} pages`} className="mt-3 flex items-center justify-between text-sm">
          <button type="button" className="text-brand-600 underline" disabled={offset === 0}
            onClick={() => setOffset(Math.max(0, offset - pageSize))}>Previous</button>
          <span>{Math.min(offset + 1, total)}–{Math.min(offset + pageSize, total)} of {total}</span>
          <button type="button" className="text-brand-600 underline" disabled={offset + pageSize >= total}
            onClick={() => setOffset(offset + pageSize)}>Next</button>
        </nav>
      )}
    </section>
  );
}

function StatusPanel({ label, value }: { label: string; value: number | string }) {
  return (
    <div className="rounded-lg border border-theme-border bg-theme-card p-4 shadow-xs">
      <p className="text-sm font-medium text-theme-text-muted">{label}</p>
      <p className="mt-2 text-xl font-semibold text-theme-text-primary">{value}</p>
    </div>
  );
}
