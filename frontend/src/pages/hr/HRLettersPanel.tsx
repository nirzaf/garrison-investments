import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import { useState, type FormEvent } from 'react';

import { formatApiError } from '../../api/errors';
import {
  createLetterTemplate,
  draftHrLetter,
  listEmployees,
  listLetterTemplates,
  renderLetter,
  type HrSchemas
} from '../../api/hr';
import { hrInputClass } from './HRAccessForms';
import { HRLetterRecords } from './HRLetterRecords';

const templateKey = ['hr', 'letter-templates'] as const;
const employeeFields = new Set(['employee_code', 'full_name', 'join_date', 'employment_status']);
const letterTypes = {
  employment_confirmation: 'Employment confirmation',
  experience_letter: 'Experience letter',
  transfer_letter: 'Transfer letter',
  warning_letter: 'Warning letter',
  salary_confirmation: 'Salary confirmation',
  candidate_rejection: 'Candidate rejection',
  custom: 'Custom'
};
const buttonClass = 'rounded bg-brand-600 px-3 py-1.5 text-white disabled:opacity-50';

export function HRLettersPanel({
  canCreate,
  canRender,
  canIssue
}: {
  canCreate: boolean;
  canRender: boolean;
  canIssue: boolean;
}) {
  const queryClient = useQueryClient();
  const [templateId, setTemplateId] = useState('');
  const [employeeId, setEmployeeId] = useState('');
  const [search, setSearch] = useState('');
  const templates = useQuery({
    queryKey: templateKey,
    queryFn: listLetterTemplates,
    enabled: canRender
  });
  const employees = useQuery({
    queryKey: ['hr', 'letter-employees', search],
    queryFn: () => listEmployees({ search, limit: 25 }),
    enabled: canRender && search.length > 0
  });
  const create = useMutation({ mutationFn: createLetterTemplate });
  const render = useMutation({ mutationFn: renderLetter });
  const draft = useMutation({
    mutationFn: draftHrLetter,
    onSuccess: (_saved, input) =>
      queryClient.invalidateQueries({
        queryKey: ['hr', 'letters', input.employee_id]
      })
  });
  const [selection, setSelection] = useState<
    HrSchemas['LetterGenerateRequest'] & { draft_id: string }
  >();
  const activeTemplates = templates.data?.items.filter((item) => item.is_active) ?? [];
  const template = activeTemplates.find((item) => item.id === templateId);
  const variables = new Set<string>();
  for (const value of [template?.subject_template, template?.body_template]) {
    for (const [, field] of value?.matchAll(/\{\{|\}\}|\{([A-Za-z_]\w*):?\}/g) ?? []) {
      if (field && !employeeFields.has(field)) variables.add(field);
    }
  }
  const canPreview =
    Boolean(template) && Boolean(employees.data?.items.some((item) => item.id === employeeId));

  function handleCreate(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (create.isPending) return;
    const form = event.currentTarget;
    const data = new FormData(form);
    create.mutate(
      {
        code: String(data.get('code')).trim(),
        name: String(data.get('name')).trim(),
        letter_type: data.get('type') as keyof typeof letterTypes,
        subject_template: String(data.get('subject')).trim(),
        body_template: String(data.get('body')).trim(),
        requires_hr_manager: data.has('restricted')
      },
      {
        onSuccess: (saved) => {
          form.reset();
          render.reset();
          if (saved.letter_type !== 'candidate_rejection') setTemplateId(saved.id);
          void queryClient.invalidateQueries({ queryKey: templateKey });
        }
      }
    );
  }

  function handleRender(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (!canPreview || render.isPending || draft.isPending) return;
    const data = new FormData(event.currentTarget);
    draft.reset();
    const input = {
      template_id: templateId,
      employee_id: employeeId,
      extra_vars: Object.fromEntries(
        [...variables].map((field) => [field, String(data.get(field) ?? '')])
      )
    };
    setSelection({ ...input, draft_id: crypto.randomUUID() });
    render.mutate(input);
  }

  return (
    <section className="space-y-4 rounded-lg border border-theme-border bg-theme-card p-5 lg:col-span-2">
      <h3 className="text-base font-semibold">HR letters</h3>
      <div className="grid gap-6 lg:grid-cols-2">
        {canCreate && (
          <form className="space-y-3" onSubmit={handleCreate}>
            <h4 className="font-medium">Create a template</h4>
            <p className="text-sm">
              Use {'{full_name}'}, {'{employee_code}'}, {'{join_date}'} or {'{employment_status}'}{' '}
              to insert employee details from the directory.
            </p>
            <p className="text-sm">
              Candidate rejection templates use {'{candidate_name}'} and {'{position_title}'}.
              Review the rendered correspondence in Recruitment.
            </p>
            <label className="block">
              Template code
              <input className={hrInputClass} name="code" maxLength={40} required />
            </label>
            <label className="block">
              Template name
              <input className={hrInputClass} name="name" minLength={2} maxLength={160} required />
            </label>
            <label className="block">
              Letter type
              <select className={hrInputClass} name="type">
                {Object.entries(letterTypes).map(([key, label]) => (
                  <option value={key} key={key}>
                    {label}
                  </option>
                ))}
              </select>
            </label>
            <label className="block">
              Letter subject template
              <input
                className={hrInputClass}
                name="subject"
                minLength={2}
                maxLength={255}
                required
              />
            </label>
            <label className="block">
              Letter body template
              <textarea className={hrInputClass} name="body" minLength={5} rows={4} required />
            </label>
            <label className="flex items-center gap-2">
              <input type="checkbox" name="restricted" />
              Require sensitive HR permission to render
            </label>
            <button
              className={buttonClass}
              disabled={create.isPending || render.isPending}
              type="submit"
            >
              {create.isPending ? 'Saving…' : 'Save letter template'}
            </button>
            {create.isSuccess && <p role="status">Letter template saved.</p>}
            {create.isError && (
              <p role="alert">
                {formatApiError(create.error, 'Unable to save the letter template.')}
              </p>
            )}
          </form>
        )}
        {canRender && (
          <div className="space-y-3">
            <h4 className="font-medium">Preview an employee letter</h4>
            <form
              className="space-y-2"
              onSubmit={(event) => {
                event.preventDefault();
                const value = String(new FormData(event.currentTarget).get('search')).trim();
                if (value === search) return;
                setEmployeeId('');
                render.reset();
                setSearch(value);
              }}
            >
              <label className="block">
                Find employee by name or code
                <input className={hrInputClass} name="search" required />
              </label>
              <button className={buttonClass} disabled={render.isPending} type="submit">
                Find employee
              </button>
            </form>
            <form className="space-y-3" onSubmit={handleRender}>
              <label className="block">
                Letter template
                <select
                  className={hrInputClass}
                  onChange={(event) => {
                    setTemplateId(event.target.value);
                    render.reset();
                  }}
                  value={templateId}
                  disabled={render.isPending}
                  required
                >
                  <option value="">Select a template</option>
                  {activeTemplates.map((item) => (
                    <option key={item.id} value={item.id}>
                      {item.code} · {item.name}
                    </option>
                  ))}
                </select>
              </label>
              <label className="block">
                Letter employee
                <select
                  className={hrInputClass}
                  onChange={(event) => {
                    setEmployeeId(event.target.value);
                    render.reset();
                  }}
                  value={employeeId}
                  disabled={render.isPending}
                  required
                >
                  <option value="">Select an employee</option>
                  {employees.data?.items.map((item) => (
                    <option key={item.id} value={item.id}>
                      {item.employee_code} · {item.full_name}
                    </option>
                  ))}
                </select>
              </label>
              {templates.isLoading && <p role="status">Loading letter templates…</p>}
              {templates.isSuccess && !activeTemplates.length && <p>No active letter templates.</p>}
              {employees.isLoading && <p role="status">Searching the employee directory…</p>}
              {employees.isSuccess && !employees.data.items.length && <p>No matching employees.</p>}
              {templates.isError && (
                <p role="alert">
                  {formatApiError(templates.error, 'Unable to load letter templates.')}{' '}
                  <button
                    type="button"
                    className="underline"
                    onClick={() => void templates.refetch()}
                  >
                    Retry
                  </button>
                </p>
              )}
              {employees.isError && (
                <p role="alert">
                  {formatApiError(employees.error, 'Unable to find employees.')}{' '}
                  <button
                    type="button"
                    className="underline"
                    onClick={() => void employees.refetch()}
                  >
                    Retry
                  </button>
                </p>
              )}
              {[...variables].map((field) => (
                <label className="block" key={`${templateId}-${field}`}>
                  {field}
                  <input
                    className={hrInputClass}
                    name={field}
                    onChange={() => render.reset()}
                    disabled={render.isPending}
                    required
                  />
                </label>
              ))}
              <button
                className={buttonClass}
                disabled={!canPreview || render.isPending || create.isPending}
                type="submit"
              >
                {render.isPending ? 'Rendering…' : 'Preview letter'}
              </button>
              {render.isError && (
                <p role="alert">{formatApiError(render.error, 'Unable to preview the letter.')}</p>
              )}
            </form>
            {render.data && (
              <div className="space-y-2 rounded border border-theme-border p-3" role="status">
                <p className="font-semibold">{render.data.subject}</p>
                <p className="whitespace-pre-wrap break-words">{render.data.body}</p>
                {canIssue && selection && render.data.digest && (
                  <button
                    className={buttonClass}
                    type="button"
                    disabled={draft.isPending || draft.isSuccess || render.isPending}
                    onClick={() => {
                      const digest = render.data?.digest;
                      if (digest) draft.mutate({ ...selection, expected_digest: digest });
                    }}
                  >
                    Save draft for independent review
                  </button>
                )}
                {draft.isSuccess && <p>Letter draft saved for review.</p>}
                {draft.isError && (
                  <p role="alert">{formatApiError(draft.error, 'Unable to save the draft.')}</p>
                )}
              </div>
            )}
            {canIssue && employeeId && <HRLetterRecords key={employeeId} employeeId={employeeId} />}
          </div>
        )}
      </div>
    </section>
  );
}
