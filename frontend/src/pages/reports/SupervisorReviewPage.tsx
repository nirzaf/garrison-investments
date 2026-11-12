import { useQuery } from '@tanstack/react-query';
import { useState } from 'react';

import { formatApiError } from '../../api/errors';
import { listProjects } from '../../api/projects';
import { listSupervisorUpdates } from '../../api/supervisorUpdates';
import { useAuth } from '../../context/useAuth';
import { useDebouncedSearch } from '../../useDebouncedSearch';
import { SupervisorUpdateDetails } from './SupervisorEvidence';

const pageSize = 20;

export function SupervisorReviewPage() {
  const { user } = useAuth();
  const [project, setProject] = useState<{ id: string; name: string }>();
  const [search, setSearch] = useState('');
  const projectId = project?.id ?? '';
  const term = useDebouncedSearch(search);
  const [status, setStatus] = useState('');
  const [offset, setOffset] = useState(0);
  const projects = useQuery({
    queryKey: ['supervisor-review-projects', term],
    queryFn: () => listProjects({ search: term || undefined, limit: 30 })
  });
  const options = projects.data?.items ?? [];
  const selectedOutsideResults = project && !options.some((option) => option.id === project.id);
  const needsProject = user?.role === 'civil_engineer' && !projectId;
  const updates = useQuery({
    queryKey: ['supervisor-review', projectId, status, offset],
    queryFn: () =>
      listSupervisorUpdates({
        project_id: projectId || undefined,
        status: status || undefined,
        limit: pageSize,
        offset
      }),
    enabled: !needsProject
  });

  return (
    <section className="space-y-4">
      <h2 className="text-2xl font-semibold text-theme-text-primary">Supervisor site updates</h2>
      <div className="grid gap-3 sm:grid-cols-2">
        <label className="block text-sm">
          Search projects
          <input
            className="form-field"
            value={search}
            onChange={(event) => setSearch(event.target.value)}
          />
        </label>
        <label className="block text-sm">
          Project
          <select
            className="form-field"
            value={projectId}
            onChange={(event) => {
              setProject(
                options.find((option) => option.id === event.target.value) ??
                  (event.target.value === projectId ? project : undefined)
              );
              setOffset(0);
            }}
          >
            <option value="">
              {user?.role === 'civil_engineer' ? 'Select a project' : 'All accessible projects'}
            </option>
            {selectedOutsideResults && <option value={project.id}>{project.name}</option>}
            {options.map((project) => (
              <option key={project.id} value={project.id}>
                {project.name}
              </option>
            ))}
          </select>
        </label>
        <label className="block text-sm">
          Status
          <select
            className="form-field"
            value={status}
            onChange={(event) => {
              setStatus(event.target.value);
              setOffset(0);
            }}
          >
            <option value="">All visible statuses</option>
            <option value="submitted">Submitted</option>
            <option value="verified">Verified</option>
          </select>
        </label>
      </div>
      {projects.isPending && <p role="status">Loading projects…</p>}
      {projects.isSuccess && !options.length && <p>No matching projects.</p>}
      {projects.isError && <p role="alert">Unable to load projects.</p>}
      {needsProject ? (
        <p>Select a project to see its site updates.</p>
      ) : (
        <>
          {updates.isPending && <p role="status">Loading site updates…</p>}
          {updates.isError && (
            <p role="alert">{formatApiError(updates.error, 'Unable to load site updates.')}</p>
          )}
          {updates.data?.total === 0 && <p>No matching updates.</p>}
          {updates.data?.items.map((update) => (
            <SupervisorUpdateDetails key={update.id} update={update} />
          ))}
          {updates.data && updates.data.total > pageSize && (
            <div className="flex gap-4 text-sm">
              <button
                className="form-button"
                disabled={offset === 0}
                type="button"
                onClick={() => setOffset(offset - pageSize)}
              >
                Previous
              </button>
              <button
                className="form-button"
                disabled={offset + pageSize >= updates.data.total}
                type="button"
                onClick={() => setOffset(offset + pageSize)}
              >
                Next
              </button>
            </div>
          )}
        </>
      )}
    </section>
  );
}
