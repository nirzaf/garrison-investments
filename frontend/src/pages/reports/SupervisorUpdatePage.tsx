import { zodResolver } from '@hookform/resolvers/zod';
import { AlertTriangle, Check, ClipboardList, Save, Send, Upload } from 'lucide-react';
import { useCallback, useEffect, useMemo, useState } from 'react';
import type { ReactNode } from 'react';
import { useForm } from 'react-hook-form';
import { z } from 'zod';

import { listProjects, type ProjectRecord } from '../../api/projects';
import {
  createSupervisorUpdate,
  listSupervisorUpdates,
  submitSupervisorUpdate,
  type SupervisorUpdateRecord
} from '../../api/supervisorUpdates';
import { EmptyState } from '../../components/shared/EmptyState';
import { StatusBadge } from '../../components/shared/StatusBadge';

const draftKey = 'garrisons.supervisor-update-draft';

const updateSchema = z.object({
  project_id: z.string().min(1, 'Select a project.'),
  update_date: z.string().min(1, 'Select a date.'),
  day_type: z.enum(['weekday', 'friday', 'public_holiday']),
  work_location: z.string().min(1, 'Enter the work location.').max(255),
  attendance_count: z.coerce.number().int().min(0, 'Attendance cannot be negative.'),
  overtime_hours: z.coerce.number().min(0, 'Overtime cannot be negative.'),
  progress_notes: z.string().min(1, 'Enter progress notes.'),
  delay_notes: z.string().optional(),
  required_notes: z.string().min(1, 'Enter required notes.'),
  attachment_names: z.string().optional()
});

type UpdateFormInput = z.input<typeof updateSchema>;
type UpdateFormValues = z.output<typeof updateSchema>;

const today = new Date().toISOString().slice(0, 10);

const defaultValues: UpdateFormValues = {
  project_id: '',
  update_date: today,
  day_type: 'weekday',
  work_location: '',
  attendance_count: 0,
  overtime_hours: 0,
  progress_notes: '',
  delay_notes: '',
  required_notes: '',
  attachment_names: ''
};

function parseAttachmentNames(value?: string) {
  return (value ?? '')
    .split('\n')
    .map((name) => name.trim())
    .filter(Boolean)
    .map((name) => ({ name, kind: name.match(/\.(jpg|jpeg|png|webp)$/i) ? 'photo' : 'file' }));
}

function formatApiError(error: unknown) {
  if (typeof error === 'object' && error !== null && 'response' in error) {
    const response = (error as { response?: { data?: { detail?: string } } }).response;
    if (response?.data?.detail) {
      return response.data.detail.replace(/_/g, ' ').toLowerCase();
    }
  }
  return 'Unable to save the site update.';
}

export function SupervisorUpdatePage() {
  const [projects, setProjects] = useState<ProjectRecord[]>([]);
  const [updates, setUpdates] = useState<SupervisorUpdateRecord[]>([]);
  const [notice, setNotice] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [savedDraftId, setSavedDraftId] = useState<string | null>(null);
  const [isLoading, setIsLoading] = useState(true);
  const [isSaving, setIsSaving] = useState(false);

  const storedDraft = useMemo(() => {
    try {
      const raw = window.localStorage.getItem(draftKey);
      return raw ? { ...defaultValues, ...JSON.parse(raw) } : defaultValues;
    } catch {
      return defaultValues;
    }
  }, []);

  const {
    formState: { errors },
    handleSubmit,
    register,
    reset,
    watch
  } = useForm<UpdateFormInput, unknown, UpdateFormValues>({
    defaultValues: storedDraft,
    resolver: zodResolver(updateSchema)
  });

  const selectedProjectId = watch('project_id');

  const loadUpdates = useCallback(
    async (projectId?: string) => {
      const response = await listSupervisorUpdates({
        project_id: projectId || undefined,
        status: undefined
      });
      setUpdates(response.items);
    },
    [setUpdates]
  );

  useEffect(() => {
    let active = true;
    Promise.all([listProjects({ status: 'active' }), listSupervisorUpdates({})])
      .then(([projectResponse, updateResponse]) => {
        if (!active) return;
        setProjects(projectResponse.items);
        setUpdates(updateResponse.items);
      })
      .catch(() => {
        if (active) {
          setError('Unable to load active projects.');
        }
      })
      .finally(() => {
        if (active) {
          setIsLoading(false);
        }
      });
    return () => {
      active = false;
    };
  }, []);

  useEffect(() => {
    const subscription = watch((value) => {
      window.localStorage.setItem(draftKey, JSON.stringify(value));
    });
    return () => subscription.unsubscribe();
  }, [watch]);

  useEffect(() => {
    void loadUpdates(selectedProjectId);
  }, [loadUpdates, selectedProjectId]);

  function buildPayload(values: UpdateFormValues) {
    return {
      project_id: values.project_id,
      update_date: values.update_date,
      day_type: values.day_type,
      work_location: values.work_location,
      attendance_count: values.attendance_count,
      overtime_hours: values.overtime_hours.toString(),
      progress_notes: values.progress_notes,
      delay_notes: values.delay_notes || null,
      required_notes: values.required_notes,
      attachment_refs: parseAttachmentNames(values.attachment_names)
    };
  }

  async function saveDraft(values: UpdateFormValues) {
    setError(null);
    setNotice(null);
    if (savedDraftId) {
      setNotice('Draft already saved. Submit it when the site update is ready.');
      return savedDraftId;
    }

    setIsSaving(true);
    try {
      const update = await createSupervisorUpdate(buildPayload(values));
      setSavedDraftId(update.id);
      setNotice('Draft saved.');
      await loadUpdates(values.project_id);
      return update.id;
    } catch (saveError) {
      setError(formatApiError(saveError));
      return null;
    } finally {
      setIsSaving(false);
    }
  }

  async function submitUpdate(values: UpdateFormValues) {
    setError(null);
    setNotice(null);
    setIsSaving(true);
    try {
      const updateId = savedDraftId ?? (await createSupervisorUpdate(buildPayload(values))).id;
      await submitSupervisorUpdate(updateId);
      setSavedDraftId(null);
      reset(defaultValues);
      window.localStorage.removeItem(draftKey);
      setNotice('Site update submitted.');
      await loadUpdates(values.project_id);
    } catch (submitError) {
      setError(formatApiError(submitError));
    } finally {
      setIsSaving(false);
    }
  }

  return (
    <div className="grid gap-6 xl:grid-cols-[minmax(0,1fr)_380px]">
      <section className="space-y-4">
        <div>
          <p className="text-sm font-medium text-brand-700">Reports</p>
          <h2 className="text-2xl font-semibold text-slate-950">Supervisor Site Update</h2>
        </div>

        {notice ? (
          <div className="flex items-center gap-2 rounded-md bg-emerald-50 px-3 py-2 text-sm text-emerald-800">
            <Check className="h-4 w-4" />
            <span>{notice}</span>
          </div>
        ) : null}
        {error ? (
          <div className="flex items-center gap-2 rounded-md bg-red-50 px-3 py-2 text-sm text-red-700">
            <AlertTriangle className="h-4 w-4" />
            <span>{error}</span>
          </div>
        ) : null}

        <form
          className="rounded-lg border border-slate-200 bg-white p-4 shadow-sm"
          onSubmit={handleSubmit(submitUpdate)}
        >
          <div className="grid gap-4 md:grid-cols-2">
            <Field label="Project" error={errors.project_id?.message}>
              <select className="form-field" disabled={isLoading} {...register('project_id')}>
                <option value="">Select project</option>
                {projects.map((project) => (
                  <option key={project.id} value={project.id}>
                    {project.code} - {project.name}
                  </option>
                ))}
              </select>
            </Field>

            <Field label="Update date" error={errors.update_date?.message}>
              <input className="form-field" type="date" {...register('update_date')} />
            </Field>

            <Field label="Day type" error={errors.day_type?.message}>
              <select className="form-field" {...register('day_type')}>
                <option value="weekday">Weekday</option>
                <option value="friday">Friday</option>
                <option value="public_holiday">Public holiday</option>
              </select>
            </Field>

            <Field label="Work location" error={errors.work_location?.message}>
              <input
                className="form-field"
                placeholder="Tower A, level 3"
                {...register('work_location')}
              />
            </Field>

            <Field label="Attendance" error={errors.attendance_count?.message}>
              <input
                className="form-field"
                min="0"
                type="number"
                {...register('attendance_count')}
              />
            </Field>

            <Field label="Overtime hours" error={errors.overtime_hours?.message}>
              <input
                className="form-field"
                min="0"
                step="0.25"
                type="number"
                {...register('overtime_hours')}
              />
            </Field>
          </div>

          <div className="mt-4 grid gap-4">
            <Field label="Progress notes" error={errors.progress_notes?.message}>
              <textarea className="form-field min-h-28" {...register('progress_notes')} />
            </Field>

            <Field label="Delay notes" error={errors.delay_notes?.message}>
              <textarea className="form-field min-h-24" {...register('delay_notes')} />
            </Field>

            <Field label="Required notes" error={errors.required_notes?.message}>
              <textarea className="form-field min-h-24" {...register('required_notes')} />
            </Field>

            <Field label="Photos and support file names" error={errors.attachment_names?.message}>
              <div className="relative">
                <Upload className="pointer-events-none absolute left-3 top-3 h-4 w-4 text-slate-400" />
                <textarea
                  className="form-field min-h-20 pl-10"
                  placeholder="zone-a.jpg&#10;attendance-sheet.pdf"
                  {...register('attachment_names')}
                />
              </div>
            </Field>
          </div>

          <div className="mt-5 flex flex-col-reverse gap-3 sm:flex-row sm:justify-end">
            <button
              className="inline-flex min-h-11 items-center justify-center gap-2 rounded-md border border-slate-300 px-4 py-2 text-sm font-semibold text-slate-700 hover:bg-slate-50 disabled:opacity-60"
              disabled={isSaving}
              onClick={handleSubmit(saveDraft)}
              type="button"
            >
              <Save className="h-4 w-4" />
              Save draft
            </button>
            <button
              className="inline-flex min-h-11 items-center justify-center gap-2 rounded-md bg-brand-700 px-4 py-2 text-sm font-semibold text-white hover:bg-brand-800 disabled:opacity-60"
              disabled={isSaving}
              type="submit"
            >
              <Send className="h-4 w-4" />
              Submit update
            </button>
          </div>
        </form>
      </section>

      <aside className="space-y-4">
        <div>
          <p className="text-sm font-medium text-brand-700">Current Records</p>
          <h3 className="text-xl font-semibold text-slate-950">Recent Site Updates</h3>
        </div>
        {updates.length === 0 ? (
          <EmptyState
            description="Submitted and draft site updates for the selected project will appear here."
            title="No updates found"
          />
        ) : (
          <div className="space-y-3">
            {updates.map((update) => (
              <article
                className="rounded-lg border border-slate-200 bg-white p-4 shadow-sm"
                key={update.id}
              >
                <div className="flex items-start justify-between gap-3">
                  <div>
                    <p className="text-sm font-semibold text-slate-950">{update.update_date}</p>
                    <p className="text-xs text-slate-500">{update.work_location}</p>
                  </div>
                  <StatusBadge tone={update.status === 'submitted' ? 'success' : 'warning'}>
                    {update.status}
                  </StatusBadge>
                </div>
                <div className="mt-3 flex items-center gap-2 text-xs text-slate-500">
                  <ClipboardList className="h-4 w-4" />
                  <span>{update.attendance_count} attendance</span>
                  <span>{update.overtime_hours} overtime</span>
                </div>
                <p className="mt-3 line-clamp-3 text-sm text-slate-700">{update.progress_notes}</p>
              </article>
            ))}
          </div>
        )}
      </aside>
    </div>
  );
}

function Field({ children, error, label }: { children: ReactNode; error?: string; label: string }) {
  return (
    <label className="block">
      <span className="mb-1 block text-sm font-medium text-slate-700">{label}</span>
      {children}
      {error ? <span className="mt-1 block text-xs text-red-700">{error}</span> : null}
    </label>
  );
}
