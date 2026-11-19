import { useRef, useState, type FormEvent } from 'react';

import { formatApiError } from '../../api/errors';
import {
  plannedBoqTotal,
  projectSetupIssues,
  type BoqDraft,
  type MilestoneDraft,
  type ProjectSetupDraft
} from '../../api/projectSetup';
import { createProject, type ProjectRecord } from '../../api/projects';
import {
  ProjectInput,
  ProjectSelect,
  ProjectTextArea,
  projectActionClass,
  projectSubmitClass
} from './ProjectFields';

function newMilestone(sortOrder: number): MilestoneDraft {
  return { rowId: crypto.randomUUID(), name: '', discipline: '', sort_order: sortOrder };
}

function newBoqItem(itemCode: string, milestoneId = ''): BoqDraft {
  return {
    rowId: crypto.randomUUID(),
    milestoneId,
    item_code: itemCode,
    description: '',
    discipline: '',
    phase: '',
    unit: 'lot',
    planned_quantity: '1',
    unit_rate: '0'
  };
}

function initialDraft(): ProjectSetupDraft {
  const milestone = { ...newMilestone(1), name: 'Mobilization', discipline: 'civil' };
  return {
    name: '',
    scope_of_work: '',
    target_end_date: '',
    status: 'planning',
    milestones: [milestone],
    boq_items: [newBoqItem('BOQ-001', milestone.rowId)]
  };
}

export function ProjectCreateForm({
  onCreated,
  onCancel,
  planningOnly = false
}: {
  onCreated: (project: ProjectRecord) => void;
  onCancel: () => void;
  planningOnly?: boolean;
}) {
  const [draft, setDraft] = useState(initialDraft);
  const [issues, setIssues] = useState<ReturnType<typeof projectSetupIssues>>([]);
  const [error, setError] = useState('');
  const [pending, setPending] = useState(false);
  const submitting = useRef(false);
  const plannedTotal = plannedBoqTotal(draft.boq_items);

  function setField<K extends keyof ProjectSetupDraft>(field: K, value: ProjectSetupDraft[K]) {
    setDraft((current) => ({ ...current, [field]: value }));
    setIssues([]);
    setError('');
  }

  function editMilestone(rowId: string, fields: Partial<MilestoneDraft>) {
    setField(
      'milestones',
      draft.milestones.map((row) => (row.rowId === rowId ? { ...row, ...fields } : row))
    );
  }

  function editBoqItem(rowId: string, fields: Partial<BoqDraft>) {
    setField(
      'boq_items',
      draft.boq_items.map((row) => (row.rowId === rowId ? { ...row, ...fields } : row))
    );
  }

  function removeMilestone(rowId: string) {
    if (draft.boq_items.some((row) => row.milestoneId === rowId)) {
      setError('Clear or change the milestone selection on its BOQ items before removing it.');
      return;
    }
    setField(
      'milestones',
      draft.milestones.filter((row) => row.rowId !== rowId)
    );
  }

  function moveBoqItem(index: number, direction: -1 | 1) {
    const rows = [...draft.boq_items];
    [rows[index], rows[index + direction]] = [rows[index + direction], rows[index]];
    setField('boq_items', rows);
  }

  function rowIssues(path: string, includeChildren = true) {
    return issues
      .filter(({ field }) => field === path || (includeChildren && field.startsWith(`${path}.`)))
      .map(({ field, message }, index) => (
        <p key={`${field}-${index}`} className="text-sm text-red-700 dark:text-red-300">
          {message}
        </p>
      ));
  }

  async function submit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (submitting.current) return;
    submitting.current = true;
    setPending(true);
    setError('');
    setIssues([]);
    try {
      const project = await createProject(planningOnly ? { ...draft, status: 'planning' } : draft);
      setDraft(initialDraft());
      onCreated(project);
    } catch (failure) {
      const fieldIssues = projectSetupIssues(failure);
      setIssues(fieldIssues);
      setError(
        fieldIssues.length
          ? 'Correct the project fields below and try again.'
          : formatApiError(failure, 'Unable to create project.')
      );
    } finally {
      submitting.current = false;
      setPending(false);
    }
  }

  return (
    <form
      onSubmit={(event) => void submit(event)}
      className="rounded-lg border border-theme-border bg-theme-card p-4"
    >
      <h3 className="text-lg font-semibold">New project</h3>
      {error && (
        <p role="alert" className="alert-error mt-3 rounded-md p-3 text-sm">
          {error}
        </p>
      )}
      <fieldset disabled={pending} className="space-y-5 pt-3">
        <div className="grid gap-3 sm:grid-cols-2 xl:grid-cols-4">
          <div>
            <ProjectInput
              label="Project name"
              required
              maxLength={200}
              value={draft.name}
              onChange={(e) => setField('name', e.target.value)}
            />
            {rowIssues('name')}
          </div>
          <ProjectInput
            label="Client"
            maxLength={200}
            value={draft.client_name ?? ''}
            onChange={(e) => setField('client_name', e.target.value)}
          />
          <ProjectInput
            label="Contract number"
            maxLength={50}
            value={draft.contract_number ?? ''}
            onChange={(e) => setField('contract_number', e.target.value)}
          />
          <ProjectInput
            label="Location"
            value={draft.location ?? ''}
            onChange={(e) => setField('location', e.target.value)}
          />
          <ProjectInput
            label="Start date"
            type="date"
            value={draft.start_date ?? ''}
            onChange={(e) => setField('start_date', e.target.value)}
          />
          <div>
            <ProjectInput
              label="Target end date"
              required
              type="date"
              value={draft.target_end_date}
              onChange={(e) => setField('target_end_date', e.target.value)}
            />
            {rowIssues('target_end_date')}
          </div>
          <div>
            <ProjectInput
              label="Budget"
              inputMode="decimal"
              value={draft.budget_amount ?? ''}
              onChange={(e) => setField('budget_amount', e.target.value)}
            />
            {rowIssues('budget_amount')}
          </div>
          <ProjectSelect
            label="Initial status"
            disabled={planningOnly}
            value={draft.status}
            onChange={(e) => setField('status', e.target.value)}
          >
            <option value="planning">Planning</option>
            <option value="active">Active</option>
            <option value="on_hold">On hold</option>
          </ProjectSelect>
          <div className="sm:col-span-2">
            <ProjectTextArea
              label="Scope of work"
              required
              value={draft.scope_of_work}
              onChange={(e) => setField('scope_of_work', e.target.value)}
            />
            {rowIssues('scope_of_work')}
          </div>
          <div className="sm:col-span-2">
            <ProjectTextArea
              label="Description"
              value={draft.description ?? ''}
              onChange={(e) => setField('description', e.target.value)}
            />
          </div>
        </div>
        <div className="space-y-3">
          <div className="flex flex-wrap items-center justify-between gap-2">
            <h4 className="font-semibold">Milestones</h4>
            <button
              className={projectActionClass}
              type="button"
              onClick={() =>
                setField('milestones', [
                  ...draft.milestones,
                  newMilestone(draft.milestones.length + 1)
                ])
              }
            >
              Add milestone
            </button>
          </div>
          {draft.milestones.map((row, index) => (
            <fieldset
              key={row.rowId}
              className="space-y-2 rounded-md border border-theme-border p-3"
            >
              <legend className="px-1 text-sm font-medium">Milestone {index + 1}</legend>
              <div className="grid gap-3 sm:grid-cols-2 xl:grid-cols-5">
                <ProjectInput
                  label="Milestone name"
                  required
                  maxLength={150}
                  value={row.name}
                  onChange={(e) => editMilestone(row.rowId, { name: e.target.value })}
                />
                <ProjectInput
                  label="Discipline"
                  maxLength={50}
                  value={row.discipline ?? ''}
                  onChange={(e) => editMilestone(row.rowId, { discipline: e.target.value })}
                />
                <ProjectInput
                  label="Planned start"
                  type="date"
                  value={row.planned_start_date ?? ''}
                  onChange={(e) => editMilestone(row.rowId, { planned_start_date: e.target.value })}
                />
                <ProjectInput
                  label="Planned end"
                  type="date"
                  value={row.planned_end_date ?? ''}
                  onChange={(e) => editMilestone(row.rowId, { planned_end_date: e.target.value })}
                />
                <ProjectInput
                  label="Sort order"
                  type="number"
                  min="0"
                  max="2147483647"
                  required
                  value={row.sort_order}
                  onChange={(e) => editMilestone(row.rowId, { sort_order: e.target.valueAsNumber })}
                />
              </div>
              {rowIssues(`milestones.${index}`)}
              <button
                className={projectActionClass}
                type="button"
                onClick={() => removeMilestone(row.rowId)}
              >
                Remove milestone
              </button>
            </fieldset>
          ))}
        </div>
        <div className="space-y-3">
          <div className="flex flex-wrap items-center justify-between gap-2">
            <h4 className="font-semibold">Bill of quantities</h4>
            <button
              className={projectActionClass}
              type="button"
              onClick={() => setField('boq_items', [...draft.boq_items, newBoqItem('')])}
            >
              Add BOQ item
            </button>
          </div>
          {draft.boq_items.map((row, index) => (
            <fieldset
              key={row.rowId}
              className="space-y-2 rounded-md border border-theme-border p-3"
            >
              <legend className="px-1 text-sm font-medium">BOQ item {index + 1}</legend>
              <div className="grid gap-3 sm:grid-cols-2 xl:grid-cols-4">
                <ProjectInput
                  label="Item code"
                  required
                  maxLength={50}
                  value={row.item_code}
                  onChange={(e) => editBoqItem(row.rowId, { item_code: e.target.value })}
                />
                <ProjectInput
                  label="BOQ description"
                  required
                  value={row.description}
                  onChange={(e) => editBoqItem(row.rowId, { description: e.target.value })}
                />
                <ProjectInput
                  label="Discipline"
                  maxLength={50}
                  value={row.discipline ?? ''}
                  onChange={(e) => editBoqItem(row.rowId, { discipline: e.target.value })}
                />
                <ProjectInput
                  label="Phase"
                  maxLength={100}
                  value={row.phase ?? ''}
                  onChange={(e) => editBoqItem(row.rowId, { phase: e.target.value })}
                />
                <ProjectSelect
                  label="Linked milestone"
                  value={row.milestoneId}
                  onChange={(e) => editBoqItem(row.rowId, { milestoneId: e.target.value })}
                >
                  <option value="">No milestone</option>
                  {draft.milestones.map((item) => (
                    <option key={item.rowId} value={item.rowId}>
                      {item.name || 'Unnamed milestone'}
                    </option>
                  ))}
                </ProjectSelect>
                <ProjectInput
                  label="Unit"
                  required
                  maxLength={20}
                  value={row.unit}
                  onChange={(e) => editBoqItem(row.rowId, { unit: e.target.value })}
                />
                <ProjectInput
                  label="Planned quantity"
                  required
                  inputMode="decimal"
                  value={row.planned_quantity}
                  onChange={(e) => editBoqItem(row.rowId, { planned_quantity: e.target.value })}
                />
                <ProjectInput
                  label="Unit rate"
                  required
                  inputMode="decimal"
                  value={row.unit_rate}
                  onChange={(e) => editBoqItem(row.rowId, { unit_rate: e.target.value })}
                />
              </div>
              {rowIssues(`boq_items.${index}`)}
              <div className="flex flex-wrap gap-2">
                <button
                  className={projectActionClass}
                  disabled={index === 0}
                  type="button"
                  onClick={() => moveBoqItem(index, -1)}
                >
                  Move up
                </button>
                <button
                  className={projectActionClass}
                  disabled={index === draft.boq_items.length - 1}
                  type="button"
                  onClick={() => moveBoqItem(index, 1)}
                >
                  Move down
                </button>
                <button
                  className={projectActionClass}
                  disabled={draft.boq_items.length === 1}
                  type="button"
                  onClick={() =>
                    setField(
                      'boq_items',
                      draft.boq_items.filter((item) => item.rowId !== row.rowId)
                    )
                  }
                >
                  Remove BOQ item
                </button>
              </div>
            </fieldset>
          ))}
          {rowIssues('boq_items', false)}
          {plannedTotal !== null && (
            <p className="text-sm text-theme-text-secondary">Planned BOQ total {plannedTotal}</p>
          )}
        </div>
        <div className="flex flex-wrap gap-2">
          <button className={projectSubmitClass} type="submit">
            {pending ? 'Creating…' : 'Create project'}
          </button>
          <button className={projectActionClass} type="button" onClick={onCancel}>
            Cancel project setup
          </button>
        </div>
      </fieldset>
    </form>
  );
}
