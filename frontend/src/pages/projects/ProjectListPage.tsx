import { keepPreviousData, useQuery, useQueryClient } from '@tanstack/react-query';
import { useState } from 'react';

import { formatApiError } from '../../api/errors';
import { listProjects } from '../../api/projects';
import { useAuth } from '../../context/useAuth';
import { useDebouncedSearch } from '../../useDebouncedSearch';
import { ProjectCreateForm } from './ProjectCreateForm';
import { ProjectDetailPanel } from './ProjectDetailPanel';
import { ProjectInput, ProjectSelect, projectActionClass } from './ProjectFields';

const pageSize = 25;

export function ProjectListPage() {
  const { user } = useAuth();
  const queryClient = useQueryClient();
  const canManage = user?.permissions?.includes('projects:manage') ?? false;
  const canCreate = ['managing_director', 'operations_director'].includes(user?.role ?? '');
  const [status, setStatus] = useState('');
  const [search, setSearch] = useState('');
  const [page, setPage] = useState(0);
  const [creating, setCreating] = useState(false);
  const [projectId, setProjectId] = useState('');
  const debouncedSearch = useDebouncedSearch(search);
  const list = useQuery({
    queryKey: ['projects', 'page', status, debouncedSearch, page],
    queryFn: () =>
      listProjects({
        status: status || undefined,
        search: debouncedSearch || undefined,
        offset: page * pageSize,
        limit: pageSize
      }),
    placeholderData: keepPreviousData
  });

  return (
    <div className="space-y-6">
      <div className="flex flex-wrap items-center justify-between gap-3">
        <h2 className="text-2xl font-semibold text-theme-text-primary">Projects</h2>
        {canCreate && !creating && (
          <button className={projectActionClass} type="button" onClick={() => setCreating(true)}>
            New project
          </button>
        )}
      </div>
      {canCreate && creating && (
        <ProjectCreateForm
          onCancel={() => setCreating(false)}
          onCreated={(project) => {
            setCreating(false);
            setProjectId(project.id);
            void queryClient.invalidateQueries({ queryKey: ['projects'] });
          }}
        />
      )}
      <section className="overflow-hidden rounded-lg border border-theme-border bg-theme-card">
        <div className="grid gap-3 border-b border-theme-border p-4 sm:grid-cols-2">
          <ProjectInput
            label="Search projects"
            type="search"
            maxLength={100}
            value={search}
            onChange={(event) => {
              setSearch(event.target.value);
              setPage(0);
            }}
          />
          <ProjectSelect
            label="Project status"
            value={status}
            onChange={(event) => {
              setStatus(event.target.value);
              setPage(0);
            }}
          >
            <option value="">All statuses</option>
            <option value="planning">Planning</option>
            <option value="active">Active</option>
            <option value="on_hold">On hold</option>
            <option value="completed">Completed</option>
            <option value="cancelled">Cancelled</option>
          </ProjectSelect>
        </div>
        {list.isPending && (
          <p className="p-4" role="status">
            Loading projects…
          </p>
        )}
        {list.isError && (
          <div className="p-4" role="alert">
            <p>{formatApiError(list.error, 'Unable to load projects.')}</p>
            <button
              className={projectActionClass}
              type="button"
              onClick={() => void list.refetch()}
            >
              Retry
            </button>
          </div>
        )}
        {list.data && (
          <>
            {list.isFetching && (
              <p className="p-4 text-sm" role="status">
                Updating project results…
              </p>
            )}
            {list.isError && <p className="px-4 text-sm">Showing the last loaded results.</p>}
            {list.data.items.length ? (
              <div className="overflow-x-auto">
                <table className="min-w-full text-left text-sm">
                  <thead className="bg-theme-main text-theme-text-secondary">
                    <tr>
                      {['Project', 'Client', 'Deadline', 'Progress', 'Status'].map((heading) => (
                        <th scope="col" key={heading} className="p-3">
                          {heading}
                        </th>
                      ))}
                    </tr>
                  </thead>
                  <tbody className="divide-y divide-theme-border">
                    {list.data.items.map((project) => (
                      <tr key={project.id}>
                        <td className="p-3">
                          <button
                            className="text-left font-semibold text-brand-600 hover:underline"
                            type="button"
                            onClick={() => setProjectId(project.id)}
                          >
                            {project.name}
                          </button>
                          <p className="text-xs text-theme-text-secondary">{project.code}</p>
                        </td>
                        <td className="p-3">{project.client_name || '—'}</td>
                        <td className="p-3">{project.target_end_date}</td>
                        <td className="p-3">{project.progress_percentage}%</td>
                        <td className="p-3 capitalize">{project.status.replace(/_/g, ' ')}</td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            ) : (
              <p className="p-4 text-sm">No projects match these filters.</p>
            )}
            <div className="flex flex-wrap items-center justify-between gap-2 border-t border-theme-border p-3 text-sm">
              <span>{list.data.total} projects</span>
              <div className="flex items-center gap-2">
                <button
                  type="button"
                  className={projectActionClass}
                  disabled={page === 0 || list.isFetching}
                  onClick={() => setPage(page - 1)}
                >
                  Previous page
                </button>
                <button
                  type="button"
                  className={projectActionClass}
                  disabled={(page + 1) * pageSize >= list.data.total || list.isFetching}
                  onClick={() => setPage(page + 1)}
                >
                  Next page
                </button>
              </div>
            </div>
          </>
        )}
      </section>
      {projectId && (
        <ProjectDetailPanel
          key={projectId}
          projectId={projectId}
          canManage={canManage}
          onClose={() => setProjectId('')}
        />
      )}
    </div>
  );
}
