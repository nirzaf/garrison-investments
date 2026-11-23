import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import { useState } from 'react';
import { Link, useSearchParams } from 'react-router-dom';

import { formatApiError } from '../../api/errors';
import { listReportProjectOptions } from '../../api/projects';
import {
  listSupervisorUpdates,
  reviewSupervisorUpdate,
  type SupervisorUpdateRecord
} from '../../api/supervisorUpdates';
import { useAuth } from '../../context/useAuth';
import { useDebouncedSearch } from '../../useDebouncedSearch';
import { SupervisorUpdateDetails } from './SupervisorEvidence';

const pageSize = 20;

export function SupervisorReviewPage() {
  const { user } = useAuth();
  const [params] = useSearchParams();
  const updateId = params.get('updateId') ?? undefined;
  const [project, setProject] = useState<{ id: string; name: string }>();
  const [search, setSearch] = useState('');
  const projectId = project?.id ?? '';
  const term = useDebouncedSearch(search);
  const [status, setStatus] = useState('');
  const [offset, setOffset] = useState(0);
  const projects = useQuery({
    queryKey: ['supervisor-review-projects', term],
    queryFn: () => listReportProjectOptions({ search: term || undefined, limit: 30 })
  });
  const options = projects.data?.items ?? [];
  const selectedOutsideResults = project && !options.some((option) => option.id === project.id);
  const updates = useQuery({
    queryKey: ['supervisor-review', projectId, status, offset, updateId],
    queryFn: () =>
      listSupervisorUpdates({
        project_id: projectId || undefined,
        status: status || undefined,
        limit: pageSize,
        offset,
        review_only: user?.role === 'quantity_surveyor',
        update_id: updateId
      }),
  });

  return (
    <section className="space-y-4">
      <h2 className="text-2xl font-semibold text-theme-text-primary">Supervisor site updates</h2>
      {updateId && <Link className="text-brand-600 underline" to="/reports/supervisor-update">All updates</Link>}
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
              All accessible projects
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
            <option value="pending_qs">Pending QS verification</option>
            <option value="pending_engineer">Pending Site Engineer confirmation</option>
            <option value="verified">Confirmed</option>
            <option value="returned">Returned for correction</option>
            <option value="submitted">Legacy submission awaiting correction</option>
          </select>
        </label>
      </div>
      {projects.isPending && <p role="status">Loading projects…</p>}
      {projects.isSuccess && !options.length && <p>No matching projects.</p>}
      {projects.isError && <p role="alert">Unable to load projects.</p>}
      {updates.isPending && <p role="status">Loading site updates…</p>}
      {updates.isError && (
        <p role="alert">{formatApiError(updates.error, 'Unable to load site updates.')}</p>
      )}
      {updates.data?.total === 0 && <p>No matching updates.</p>}
      {updates.data?.items.map((update) => (
        <SupervisorUpdateDetails key={update.id} update={update}>
          {update.pending_reviewer_id === user?.id && update.submission_revision != null && (
            <ProgressReviewActions update={update} />
          )}
        </SupervisorUpdateDetails>
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
    </section>
  );
}

function ProgressReviewActions({ update }: { update: SupervisorUpdateRecord }) {
  const [comments, setComments] = useState('');
  const queryClient = useQueryClient();
  const stage = update.status === 'pending_qs' ? 'qs' : 'engineer';
  function refresh() {
    void queryClient.invalidateQueries({ queryKey: ['supervisor-review'] });
    void queryClient.invalidateQueries({ queryKey: ['site-progress-submissions', update.id] });
  }
  const decision = useMutation({
    mutationFn: (value: 'approved' | 'returned' | 'rejected') =>
      reviewSupervisorUpdate(update.id, {
        expected_submission_revision: update.submission_revision!,
        stage,
        decision: value,
        comments
      }),
    onSuccess: refresh
  });
  return (
    <div className="space-y-2 border-t border-theme-border pt-3">
      <label className="block">
        {stage === 'qs' ? 'QS verification comments' : 'Site Engineer confirmation comments'}
        <textarea className="form-field" maxLength={2000} value={comments}
          onChange={(event) => setComments(event.target.value)} />
      </label>
      <div className="flex flex-wrap gap-2">
        {([
          ['approved', stage === 'qs' ? 'Verify quantities and area' : 'Confirm technical progress'],
          ['returned', 'Return for correction'],
          ['rejected', 'Reject submitted progress']
        ] as const).map(([value, label]) => (
          <button key={value} type="button" className="form-button"
            disabled={decision.isPending || (value !== 'approved' && !comments.trim())}
            onClick={() => decision.mutate(value)}>{label}</button>
        ))}
      </div>
      {decision.isError && (
        <div role="alert">
          {formatApiError(decision.error, 'Unable to record the decision.')}
          <button type="button" className="ml-2 underline" onClick={refresh}>Reload update</button>
        </div>
      )}
    </div>
  );
}
