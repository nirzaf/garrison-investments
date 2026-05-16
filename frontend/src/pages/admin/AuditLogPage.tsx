import { useQuery } from '@tanstack/react-query';
import { Search } from 'lucide-react';
import { useMemo, useState } from 'react';

import { getAuditLogs } from '../../api/audit';
import { EmptyState } from '../../components/shared/EmptyState';
import { StatusBadge } from '../../components/shared/StatusBadge';

const actionOptions = [
  '',
  'auth.login_success',
  'auth.login_failed',
  'auth.logout',
  'reports.approved',
  'reports.rejected',
  'report_exports.downloaded',
  'documents.downloaded',
  'photos.original.downloaded'
];

const entityOptions = ['', 'users', 'projects', 'daily_reports', 'documents', 'photos'];

function readableAction(action: string) {
  return action.split('_').join(' ').split('.').join(' / ');
}

export function AuditLogPage() {
  const [search, setSearch] = useState('');
  const [action, setAction] = useState('');
  const [entityType, setEntityType] = useState('');

  const filters = useMemo(
    () => ({
      search: search || undefined,
      action: action || undefined,
      entity_type: entityType || undefined,
      limit: 100
    }),
    [action, entityType, search]
  );

  const { data, isLoading, isError } = useQuery({
    queryKey: ['audit-logs', filters],
    queryFn: () => getAuditLogs(filters)
  });

  return (
    <section className="space-y-5">
      <div className="flex flex-col gap-3 sm:flex-row sm:items-end sm:justify-between">
        <div>
          <h2 className="text-xl font-semibold text-slate-950">Audit Logs</h2>
          <p className="text-sm text-slate-600">
            Admin-only trace of access, approvals, downloads, and security events.
          </p>
        </div>
      </div>

      <div className="grid gap-3 rounded-lg border border-slate-200 bg-white p-4 md:grid-cols-[1fr_220px_220px]">
        <label className="space-y-1 text-sm font-medium text-slate-700">
          Search
          <div className="flex items-center gap-2 rounded-md border border-slate-300 px-3">
            <Search className="h-4 w-4 text-slate-400" />
            <input
              className="min-h-10 flex-1 border-0 bg-transparent text-sm outline-none"
              onChange={(event) => setSearch(event.target.value)}
              placeholder="Action, entity, comment"
              value={search}
            />
          </div>
        </label>
        <label className="space-y-1 text-sm font-medium text-slate-700">
          Action
          <select
            className="min-h-10 w-full rounded-md border border-slate-300 px-3 text-sm"
            onChange={(event) => setAction(event.target.value)}
            value={action}
          >
            {actionOptions.map((option) => (
              <option key={option} value={option}>
                {option ? readableAction(option) : 'All actions'}
              </option>
            ))}
          </select>
        </label>
        <label className="space-y-1 text-sm font-medium text-slate-700">
          Entity
          <select
            className="min-h-10 w-full rounded-md border border-slate-300 px-3 text-sm"
            onChange={(event) => setEntityType(event.target.value)}
            value={entityType}
          >
            {entityOptions.map((option) => (
              <option key={option} value={option}>
                {option ? option.split('_').join(' ') : 'All entities'}
              </option>
            ))}
          </select>
        </label>
      </div>

      <div className="overflow-hidden rounded-lg border border-slate-200 bg-white">
        {isLoading ? (
          <p className="p-4 text-sm text-slate-600">Loading audit logs</p>
        ) : isError ? (
          <p className="p-4 text-sm text-red-700">Unable to load audit logs.</p>
        ) : data && data.items.length > 0 ? (
          <div className="overflow-x-auto">
            <table className="min-w-full divide-y divide-slate-200 text-sm">
              <thead className="bg-slate-50 text-left text-xs uppercase tracking-wide text-slate-500">
                <tr>
                  <th className="px-4 py-3">Time</th>
                  <th className="px-4 py-3">Action</th>
                  <th className="px-4 py-3">Entity</th>
                  <th className="px-4 py-3">Actor</th>
                  <th className="px-4 py-3">Context</th>
                </tr>
              </thead>
              <tbody className="divide-y divide-slate-100">
                {data.items.map((log) => (
                  <tr key={log.id}>
                    <td className="whitespace-nowrap px-4 py-3 text-slate-600">
                      {new Date(log.created_at).toLocaleString()}
                    </td>
                    <td className="px-4 py-3">
                      <StatusBadge tone="info">{readableAction(log.action)}</StatusBadge>
                    </td>
                    <td className="px-4 py-3 text-slate-700">
                      <p>{log.entity_type ?? '-'}</p>
                      <p className="max-w-48 truncate text-xs text-slate-500">
                        {log.entity_id ?? ''}
                      </p>
                    </td>
                    <td className="max-w-48 truncate px-4 py-3 text-slate-600">
                      {log.user_id ?? 'System'}
                    </td>
                    <td className="px-4 py-3 text-slate-600">
                      <p>{log.comments ?? '-'}</p>
                      <p className="max-w-md truncate text-xs text-slate-500">
                        {log.ip_address ?? ''} {log.user_agent ? `· ${log.user_agent}` : ''}
                      </p>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        ) : (
          <EmptyState title="No audit logs found" description="Adjust the filters and try again." />
        )}
      </div>
    </section>
  );
}
