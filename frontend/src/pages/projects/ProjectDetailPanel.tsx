import { useQuery, useQueryClient } from '@tanstack/react-query';
import { useRef, useState, type FormEvent } from 'react';

import { formatApiError } from '../../api/errors';
import {
  assignProjectMember,
  getProject,
  listProjectMembers,
  updateProject,
  type ProjectDetail,
  type ProjectUpdatePayload
} from '../../api/projects';
import { useAuth } from '../../context/useAuth';
import {
  ProjectInput,
  ProjectSelect,
  ProjectTextArea,
  projectActionClass,
  projectSubmitClass
} from './ProjectFields';
import { ProjectTimeline } from './ProjectTimeline';
import { ProjectUserPicker } from './ProjectUserPicker';

const tabs = ['Overview', 'Team', 'Timeline'] as const;

export function ProjectDetailPanel({
  projectId,
  canManage,
  onClose
}: {
  projectId: string;
  canManage: boolean;
  onClose: () => void;
}) {
  const { user } = useAuth();
  const canViewFinancial = user?.permissions?.includes('financial:view') ?? false;
  const [tab, setTab] = useState<(typeof tabs)[number]>('Overview');
  const detail = useQuery({
    queryKey: ['project-detail', projectId],
    queryFn: () => getProject(projectId)
  });
  const project = detail.data;
  const canEdit = canManage && Boolean(project && !project.is_read_only);

  return (
    <section
      className="space-y-4 rounded-lg border border-theme-border bg-theme-card p-4"
      aria-label="Project details"
    >
      <div className="flex flex-wrap items-start justify-between gap-3">
        <div>
          <h3 className="text-lg font-semibold">{project?.name ?? 'Project details'}</h3>
          {project && <p className="text-sm text-theme-text-secondary">{project.code}</p>}
        </div>
        <button className={projectActionClass} type="button" onClick={onClose}>
          Close details
        </button>
      </div>
      {detail.isPending && <p role="status">Loading project details…</p>}
      {detail.isError && (
        <div role="alert">
          <p>{formatApiError(detail.error, 'Unable to load this project.')}</p>
          <button
            type="button"
            className={projectActionClass}
            onClick={() => void detail.refetch()}
          >
            Retry details
          </button>
        </div>
      )}
      {project && (
        <>
          {detail.isFetching && (
            <p role="status" className="text-sm">
              Refreshing project details…
            </p>
          )}
          {detail.isError && <p className="text-sm">Showing the last loaded details.</p>}
          {project.is_read_only && (
            <p className="text-sm text-theme-text-secondary">
              Completed and cancelled projects are read-only.
            </p>
          )}
          <nav className="flex flex-wrap gap-2" aria-label="Project detail views">
            {tabs.map((name) => (
              <button
                key={name}
                aria-pressed={name === tab}
                type="button"
                className={`${projectActionClass} ${name === tab ? 'border-brand-600 text-brand-600' : ''}`}
                onClick={() => setTab(name)}
              >
                {name}
              </button>
            ))}
          </nav>
          <div hidden={tab !== 'Overview'}>
            <ProjectOverview
              project={project}
              canEdit={canEdit}
              canViewFinancial={canViewFinancial}
              refresh={() => void detail.refetch()}
            />
          </div>
          <div hidden={tab !== 'Team'}>
            <ProjectTeam project={project} canEdit={canEdit} active={tab === 'Team'} />
          </div>
          <ProjectTimeline project={project} canEdit={canEdit} active={tab === 'Timeline'} />
        </>
      )}
    </section>
  );
}

function ProjectOverview({
  project,
  canEdit,
  canViewFinancial,
  refresh
}: {
  project: ProjectDetail;
  canEdit: boolean;
  canViewFinancial: boolean;
  refresh: () => void;
}) {
  const [editing, setEditing] = useState(false);
  const milestoneNames = new Map(project.milestones.map((item) => [item.id, item.name]));
  const details = [
    ['Client', project.client_name],
    ['Contract', project.contract_number],
    ['Location', project.location],
    ['Start date', project.start_date],
    ['Target end date', project.target_end_date],
    ['Actual end date', project.actual_end_date],
    ...(canViewFinancial ? [['Budget', project.budget_amount] as const] : []),
    ['Status', project.status.replace(/_/g, ' ')],
    ['Progress', `${project.progress_percentage}%`]
  ];
  return (
    <div className="space-y-4">
      <div className="flex flex-wrap items-center justify-between gap-2">
        <h4 className="font-semibold">Saved project details</h4>
        {canEdit && !editing && (
          <button className={projectActionClass} type="button" onClick={() => setEditing(true)}>
            Edit project
          </button>
        )}
      </div>
      <dl className="grid gap-3 text-sm sm:grid-cols-3">
        {details.map(([label, value]) => (
          <div key={label}>
            <dt className="font-medium">{label}</dt>
            <dd>{value || '—'}</dd>
          </div>
        ))}
        <div className="sm:col-span-3">
          <dt className="font-medium">Scope of work</dt>
          <dd>{project.scope_of_work}</dd>
        </div>
        {project.description && (
          <div className="sm:col-span-3">
            <dt className="font-medium">Description</dt>
            <dd>{project.description}</dd>
          </div>
        )}
      </dl>
      {editing && (
        <ProjectEditor
          project={project}
          canSave={canEdit}
          canEditFinancial={canViewFinancial}
          onClose={() => setEditing(false)}
          refresh={refresh}
        />
      )}
      <div>
        <h4 className="font-semibold">Milestones</h4>
        {project.milestones.length ? (
          <ul className="mt-1 space-y-1 text-sm">
            {project.milestones.map((item) => (
              <li key={item.id}>
                {item.name} · {item.planned_start_date || 'No planned start'} to{' '}
                {item.planned_end_date || 'no planned end'}
              </li>
            ))}
          </ul>
        ) : (
          <p className="text-sm">No milestones.</p>
        )}
      </div>
      <div className="overflow-x-auto">
        <table className="min-w-full text-left text-sm">
          <caption className="mb-2 text-left font-semibold">Bill of quantities</caption>
          <thead className="bg-theme-main">
            <tr>
              {[
                'Code',
                'Description',
                'Milestone',
                'Quantity',
                ...(canViewFinancial ? ['Rate', 'Planned amount'] : [])
              ].map(
                (label) => (
                  <th key={label} scope="col" className="p-2">
                    {label}
                  </th>
                )
              )}
            </tr>
          </thead>
          <tbody className="divide-y divide-theme-border">
            {project.boq_items.map((item) => (
              <tr key={item.id}>
                <td className="p-2">{item.item_code}</td>
                <td className="p-2">{item.description}</td>
                <td className="p-2">{milestoneNames.get(item.milestone_id ?? '') ?? '—'}</td>
                <td className="p-2">
                  {item.planned_quantity} {item.unit}
                </td>
                {canViewFinancial && (
                  <>
                    <td className="p-2">{item.unit_rate ?? '—'}</td>
                    <td className="p-2">{item.planned_amount ?? '—'}</td>
                  </>
                )}
              </tr>
            ))}
          </tbody>
        </table>
        {!project.boq_items.length && <p className="p-2 text-sm">No BOQ items.</p>}
      </div>
    </div>
  );
}

function ProjectEditor({
  project,
  canSave,
  canEditFinancial,
  onClose,
  refresh
}: {
  project: ProjectDetail;
  canSave: boolean;
  canEditFinancial: boolean;
  onClose: () => void;
  refresh: () => void;
}) {
  const queryClient = useQueryClient();
  const [draft, setDraft] = useState({
    expected_revision: project.revision,
    name: project.name,
    client_name: project.client_name ?? '',
    contract_number: project.contract_number ?? '',
    location: project.location ?? '',
    scope_of_work: project.scope_of_work,
    description: project.description ?? '',
    start_date: project.start_date ?? '',
    target_end_date: project.target_end_date,
    actual_end_date: project.actual_end_date ?? '',
    budget_amount: project.budget_amount ?? '',
    status: project.status
  });
  const [error, setError] = useState('');
  const [pending, setPending] = useState(false);
  const locked = useRef(false);

  async function submit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (locked.current || !canSave) return;
    locked.current = true;
    setPending(true);
    setError('');
    const payload: ProjectUpdatePayload = {
      ...draft,
      name: draft.name.trim(),
      scope_of_work: draft.scope_of_work.trim(),
      client_name: draft.client_name.trim() || null,
      contract_number: draft.contract_number.trim() || null,
      location: draft.location.trim() || null,
      description: draft.description.trim() || null,
      start_date: draft.start_date || null,
      actual_end_date: draft.actual_end_date || null,
      ...(canEditFinancial ? { budget_amount: draft.budget_amount.trim() || null } : {})
    };
    try {
      await updateProject(project.id, payload);
      void queryClient.invalidateQueries({ queryKey: ['project-detail', project.id] });
      void queryClient.invalidateQueries({ queryKey: ['project-timeline', project.id] });
      void queryClient.invalidateQueries({ queryKey: ['projects'] });
      void queryClient.invalidateQueries({ queryKey: ['finance', 'budget', project.id] });
      onClose();
    } catch (failure) {
      setError(formatApiError(failure, 'Unable to save project.'));
    } finally {
      locked.current = false;
      setPending(false);
    }
  }

  return (
    <form
      onSubmit={(event) => void submit(event)}
      className="space-y-3 rounded-md border border-theme-border p-3"
    >
      <h5 className="font-semibold">Edit project</h5>
      {error && (
        <p className="alert-error rounded-md p-2 text-sm" role="alert">
          {error}
        </p>
      )}
      {project.revision !== draft.expected_revision && (
        <p role="status" className="text-sm">
          Compare your draft with the saved details above. Discard this draft to edit the latest
          version.
        </p>
      )}
      <fieldset disabled={pending} className="grid gap-3 sm:grid-cols-2 lg:grid-cols-3">
        <ProjectInput
          label="Project name"
          required
          maxLength={200}
          value={draft.name}
          onChange={(e) => setDraft({ ...draft, name: e.target.value })}
        />
        <ProjectInput
          label="Client"
          maxLength={200}
          value={draft.client_name}
          onChange={(e) => setDraft({ ...draft, client_name: e.target.value })}
        />
        <ProjectInput
          label="Contract number"
          maxLength={50}
          value={draft.contract_number}
          onChange={(e) => setDraft({ ...draft, contract_number: e.target.value })}
        />
        <ProjectInput
          label="Location"
          value={draft.location}
          onChange={(e) => setDraft({ ...draft, location: e.target.value })}
        />
        <ProjectInput
          label="Start date"
          type="date"
          value={draft.start_date}
          onChange={(e) => setDraft({ ...draft, start_date: e.target.value })}
        />
        <ProjectInput
          label="Target end date"
          required
          type="date"
          value={draft.target_end_date}
          onChange={(e) => setDraft({ ...draft, target_end_date: e.target.value })}
        />
        <ProjectInput
          label="Actual end date"
          type="date"
          value={draft.actual_end_date}
          onChange={(e) => setDraft({ ...draft, actual_end_date: e.target.value })}
        />
        {canEditFinancial && (
          <ProjectInput
            label="Budget"
            inputMode="decimal"
            value={draft.budget_amount}
            onChange={(e) => setDraft({ ...draft, budget_amount: e.target.value })}
          />
        )}
        <ProjectSelect
          label="Status"
          value={draft.status}
          onChange={(e) => setDraft({ ...draft, status: e.target.value })}
        >
          <option value="planning">Planning</option>
          <option value="active">Active</option>
          <option value="on_hold">On hold</option>
          <option value="completed">Completed</option>
          <option value="cancelled">Cancelled</option>
        </ProjectSelect>
        <ProjectTextArea
          label="Scope of work"
          required
          value={draft.scope_of_work}
          onChange={(e) => setDraft({ ...draft, scope_of_work: e.target.value })}
        />
        <ProjectTextArea
          label="Description"
          value={draft.description}
          onChange={(e) => setDraft({ ...draft, description: e.target.value })}
        />
        <div className="flex flex-wrap items-end gap-2 sm:col-span-2 lg:col-span-3">
          <button
            className={projectSubmitClass}
            disabled={!canSave || draft.expected_revision !== project.revision}
            type="submit"
          >
            {pending ? 'Saving…' : 'Save project'}
          </button>
          {error && (
            <button className={projectActionClass} type="button" onClick={refresh}>
              Compare saved details
            </button>
          )}
          <button className={projectActionClass} type="button" onClick={onClose}>
            Discard edits
          </button>
        </div>
      </fieldset>
    </form>
  );
}

function ProjectTeam({
  project,
  canEdit,
  active
}: {
  project: ProjectDetail;
  canEdit: boolean;
  active: boolean;
}) {
  const queryClient = useQueryClient();
  const members = useQuery({
    queryKey: ['project-members', project.id],
    queryFn: () => listProjectMembers(project.id),
    enabled: active
  });
  const [selectedUser, setSelectedUser] = useState('');
  const [role, setRole] = useState('');
  const [pending, setPending] = useState(false);
  const [error, setError] = useState('');
  const locked = useRef(false);

  async function assign(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (locked.current || !canEdit || !selectedUser) return;
    locked.current = true;
    setPending(true);
    setError('');
    try {
      await assignProjectMember(project.id, {
        user_id: selectedUser,
        role_in_project: role.trim() || null,
        expected_revision: project.revision
      });
      setSelectedUser('');
      setRole('');
      void queryClient.invalidateQueries({ queryKey: ['project-members', project.id] });
      void queryClient.invalidateQueries({ queryKey: ['project-detail', project.id] });
      void queryClient.invalidateQueries({ queryKey: ['projects'] });
    } catch (failure) {
      setError(formatApiError(failure, 'Unable to assign this member.'));
      void queryClient.invalidateQueries({ queryKey: ['project-detail', project.id] });
    } finally {
      locked.current = false;
      setPending(false);
    }
  }

  return (
    <div className="space-y-3">
      <h4 className="font-semibold">Project team</h4>
      {members.isPending && (
        <p role="status" className="text-sm">
          Loading project team…
        </p>
      )}
      {members.isFetching && members.data && (
        <p role="status" className="text-sm">
          Refreshing project team…
        </p>
      )}
      {members.isError && (
        <div role="alert">
          <p>{formatApiError(members.error, 'Unable to load project team.')}</p>
          <button
            type="button"
            className={projectActionClass}
            onClick={() => void members.refetch()}
          >
            Retry team
          </button>
        </div>
      )}
      {members.data?.length ? (
        <ul className="divide-y divide-theme-border">
          {members.data.map((member) => (
            <li className="py-2 text-sm" key={member.id}>
              <strong>{member.user_name || 'Unavailable user'}</strong>
              {member.role_in_project && ` · ${member.role_in_project}`}
            </li>
          ))}
        </ul>
      ) : (
        members.isSuccess && <p className="text-sm">No assigned team members.</p>
      )}
      {canEdit && active && (
        <form
          onSubmit={(event) => void assign(event)}
          className="rounded-md border border-theme-border p-3"
        >
          <h5 className="mb-2 font-semibold">Assign team member</h5>
          {error && (
            <p role="alert" className="alert-error mb-2 rounded-md p-2 text-sm">
              {error}
            </p>
          )}
          <fieldset disabled={pending} className="grid gap-3 sm:grid-cols-2">
            <ProjectUserPicker
              label="Team member"
              value={selectedUser}
              onChange={setSelectedUser}
              required
            />
            <ProjectInput
              label="Role in project"
              maxLength={50}
              value={role}
              onChange={(e) => setRole(e.target.value)}
            />
            <div>
              <button className={projectSubmitClass} disabled={!selectedUser} type="submit">
                {pending ? 'Assigning…' : 'Assign member'}
              </button>
            </div>
          </fieldset>
        </form>
      )}
    </div>
  );
}
