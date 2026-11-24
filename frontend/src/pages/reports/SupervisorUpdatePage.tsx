import { zodResolver } from '@hookform/resolvers/zod';
import { AlertTriangle, Check, ClipboardList, Image, Paperclip, Save, Send } from 'lucide-react';
import { useCallback, useEffect, useRef, useState } from 'react';
import type { ReactNode } from 'react';
import { useSearchParams } from 'react-router-dom';
import { useForm } from 'react-hook-form';
import { z } from 'zod';

import { getBrowserSession } from '../../api/browserSession';
import { sameScope, type OfflineScope } from '../../api/offlineDb';
import {
  clearSupervisorDraft,
  getSupervisorDraft,
  saveSupervisorDraft
} from '../../api/offlineQueue';
import { formatApiError } from '../../api/errors';
import { MAX_REPORT_PHOTOS, PDF_IMAGE_ACCEPT, REPORT_PHOTO_ACCEPT } from '../../api/fileValidation';
import {
  deletePhoto,
  getPhotoDownloadUrl,
  getPhotoThumbnailUrl,
  listPhotos,
  prepareMediaFiles,
  uploadMediaFiles,
  type MediaUploadIntent,
  type PhotoRecord
} from '../../api/photos';
import { listReportProjectOptions, type ProjectOption } from '../../api/projects';
import {
  correctVerifiedSupervisorUpdate,
  createSupervisorUpdate,
  listSupervisorUpdates,
  submitSupervisorUpdate,
  updateSupervisorUpdate,
  type SupervisorUpdateRecord
} from '../../api/supervisorUpdates';
import { businessDate } from '../../businessDate';
import { EmptyState } from '../../components/shared/EmptyState';
import { FileDropZone } from '../../components/shared/FileDropZone';
import { StatusBadge } from '../../components/shared/StatusBadge';
import { useAuth } from '../../context/useAuth';
import { SupervisorSubmissionHistory } from './SupervisorEvidence';

const updateSchema = z.object({
  project_id: z.string().min(1, 'Select a project.'),
  update_date: z.string().min(1, 'Select a date.'),
  day_type: z.enum(['weekday', 'friday', 'public_holiday']),
  work_location: z.string().min(1, 'Enter the work location.').max(255),
  attendance_count: z.coerce.number().int().min(0, 'Attendance cannot be negative.'),
  overtime_hours: z.coerce.number().min(0, 'Overtime cannot be negative.'),
  activity_scope: z.string().max(2000).optional(),
  remaining_work: z.string().max(2000).optional(),
  completed_area: z.string().max(255).optional(),
  completed_quantity: z.string().optional(),
  quantity_unit: z.string().max(30).optional(),
  progress_percentage: z.string().optional(),
  progress_notes: z.string().min(1, 'Enter progress notes.'),
  delay_notes: z.string().optional(),
  required_notes: z.string().min(1, 'Enter required notes.'),
  attachment_names: z.string().optional()
});

type UpdateFormInput = z.input<typeof updateSchema>;
type UpdateFormValues = z.output<typeof updateSchema>;

function createDefaultValues(): UpdateFormValues {
  return {
    project_id: '',
    update_date: businessDate(),
    day_type: 'weekday',
    work_location: '',
    attendance_count: 0,
    overtime_hours: 0,
    activity_scope: '',
    remaining_work: '',
    completed_area: '',
    completed_quantity: '',
    quantity_unit: '',
    progress_percentage: '',
    progress_notes: '',
    delay_notes: '',
    required_notes: '',
    attachment_names: ''
  };
}

function parseAttachmentNames(value?: string) {
  return (value ?? '')
    .split('\n')
    .map((name) => name.trim())
    .filter(Boolean)
    .map((name) => ({ name, kind: name.match(/\.(jpg|jpeg|png|webp)$/i) ? 'photo' : 'file' }));
}

function buildPayload(values: UpdateFormValues, draft: SupervisorUpdateRecord | null) {
  return {
    project_id: values.project_id,
    update_date: values.update_date,
    day_type: values.day_type,
    work_location: values.work_location,
    attendance_count: values.attendance_count,
    overtime_hours: values.overtime_hours.toString(),
    activity_scope: values.activity_scope || null,
    remaining_work: values.remaining_work || null,
    completed_area: values.completed_area || null,
    completed_quantity: values.completed_quantity || null,
    quantity_unit: values.quantity_unit || null,
    progress_percentage: values.progress_percentage || null,
    expected_revision: draft?.revision,
    progress_notes: values.progress_notes,
    delay_notes: values.delay_notes || null,
    required_notes: values.required_notes,
    attachment_refs: draft
      ? draft.attachment_refs.flatMap(({ name, kind }) =>
          typeof name === 'string'
            ? [{ name, kind: typeof kind === 'string' ? kind : 'photo' }]
            : []
        )
      : parseAttachmentNames(values.attachment_names)
  };
}

function persistDraft(
  values: UpdateFormValues,
  draft: SupervisorUpdateRecord | null,
  scope: OfflineScope
) {
  const payload = buildPayload(values, draft);
  return draft
    ? updateSupervisorUpdate(draft.id, payload, scope)
    : createSupervisorUpdate(payload, scope);
}

export function SupervisorUpdatePage() {
  const { user } = useAuth();
  const [params] = useSearchParams();
  const focusedUpdateId = params.get('updateId') ?? undefined;
  const browserScope = getBrowserSession()?.scope;
  const scope = browserScope?.ownerUserId === user?.id ? browserScope : undefined;
  const [projects, setProjects] = useState<ProjectOption[]>([]);
  const [updates, setUpdates] = useState<SupervisorUpdateRecord[]>([]);
  const [notice, setNotice] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [savedDraft, setSavedDraft] = useState<SupervisorUpdateRecord | null>(null);
  const [isLoading, setIsLoading] = useState(true);
  const [isSaving, setIsSaving] = useState(false);
  const [lastAutosavedAt, setLastAutosavedAt] = useState<string | null>(null);
  const [uploadedFiles, setUploadedFiles] = useState<PhotoRecord[]>([]);
  const [openingFile, setOpeningFile] = useState(false);
  const [failedUpload, setFailedUpload] = useState<{
    entityId: string;
    items: MediaUploadIntent[];
  } | null>(null);
  const mediaWrite = useRef(false);

  const [draftHydrated, setDraftHydrated] = useState(false);

  const {
    formState: { errors, isDirty },
    getValues,
    handleSubmit,
    register,
    reset,
    watch
  } = useForm<UpdateFormInput, unknown, UpdateFormValues>({
    defaultValues: createDefaultValues(),
    resolver: zodResolver(updateSchema)
  });

  const selectedProjectId = watch('project_id');

  const loadUpdates = useCallback(
    async (projectId?: string) => {
      const response = await listSupervisorUpdates({
        project_id: projectId || undefined,
        update_id: focusedUpdateId
      });
      setUpdates(response.items);
    },
    [focusedUpdateId]
  );

  useEffect(() => {
    let active = true;
    Promise.all([listReportProjectOptions({ limit: 100 }), listSupervisorUpdates({ update_id: focusedUpdateId })])
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
  }, [focusedUpdateId]);

  useEffect(() => {
    if (!scope) return;
    let active = true;
    void getSupervisorDraft<UpdateFormInput>(scope)
      .then((stored) => {
        if (!active || !sameScope(getBrowserSession()?.scope, scope)) return;
        if (stored) reset({ ...createDefaultValues(), ...stored });
        setDraftHydrated(true);
      })
      .catch(() => {
        if (active) setError('Unable to open the local site update draft.');
      });
    return () => {
      active = false;
    };
  }, [reset, scope]);

  useEffect(() => {
    if (!scope || !draftHydrated) return;
    let timer: ReturnType<typeof setTimeout>;
    const subscription = watch((value, { name }) => {
      window.clearTimeout(timer);
      if (!name && !value.project_id) return;
      timer = window.setTimeout(() => {
        void saveSupervisorDraft(scope, value).catch(() => {
          if (sameScope(getBrowserSession()?.scope, scope))
            setError('Unable to save the local site update draft.');
        });
      }, 800);
    });
    return () => {
      subscription.unsubscribe();
      window.clearTimeout(timer);
    };
  }, [draftHydrated, scope, watch]);

  useEffect(() => {
    if (!scope || !draftHydrated) return;
    const interval = window.setInterval(() => {
      if (!sameScope(getBrowserSession()?.scope, scope)) return;
      const parsed = updateSchema.safeParse(getValues());
      if (!parsed.success || isSaving || (savedDraft && !isDirty)) return;
      setIsSaving(true);
      void persistDraft(parsed.data, savedDraft, scope)
        .then((update) => {
          if (!sameScope(getBrowserSession()?.scope, scope)) return;
          setSavedDraft(update);
          setLastAutosavedAt(new Date().toLocaleTimeString());
        })
        .catch(() =>
          saveSupervisorDraft(scope, getValues()).catch(() => {
            if (sameScope(getBrowserSession()?.scope, scope))
              setError('Unable to save the local site update draft.');
          })
        )
        .finally(() => setIsSaving(false));
    }, 30000);
    return () => window.clearInterval(interval);
  }, [draftHydrated, getValues, isDirty, isSaving, savedDraft, scope]);

  useEffect(() => {
    void loadUpdates(selectedProjectId);
  }, [loadUpdates, selectedProjectId]);

  async function resumeDraft(update: SupervisorUpdateRecord) {
    const { day_type } = update;
    if (day_type !== 'weekday' && day_type !== 'friday' && day_type !== 'public_holiday') {
      setError('This draft has an unsupported day type.');
      return;
    }
    setError(null);
    setIsSaving(true);
    setSavedDraft(update);
    setLastAutosavedAt(null);
    setUploadedFiles([]);
    setFailedUpload(null);
    reset({
      project_id: update.project_id,
      update_date: update.update_date,
      day_type,
      work_location: update.work_location,
      attendance_count: update.attendance_count,
      overtime_hours: Number(update.overtime_hours),
      activity_scope: update.activity_scope ?? '',
      remaining_work: update.remaining_work ?? '',
      completed_area: update.completed_area ?? '',
      completed_quantity: update.completed_quantity == null ? '' : String(update.completed_quantity),
      quantity_unit: update.quantity_unit ?? '',
      progress_percentage: update.progress_percentage == null ? '' : String(update.progress_percentage),
      progress_notes: update.progress_notes,
      delay_notes: update.delay_notes ?? '',
      required_notes: update.required_notes,
      attachment_names: ''
    });
    setNotice('Draft reopened.');
    try {
      const files = await listPhotos({ entityType: 'supervisor_update', entityId: update.id });
      setUploadedFiles(files.items);
    } catch (loadError) {
      setError(formatApiError(loadError, 'Unable to load existing attachments.'));
    } finally {
      setIsSaving(false);
    }
  }

  async function recordUploads(
    entityId: string,
    items: MediaUploadIntent[],
    selectionErrors: string[]
  ) {
    if (!scope || !sameScope(getBrowserSession()?.scope, scope)) return;
    const result = await uploadMediaFiles('supervisor_update', entityId, items, scope);
    if (!sameScope(getBrowserSession()?.scope, scope)) return;
    setUploadedFiles((current) => [
      ...current,
      ...result.uploaded.filter((file) => !current.some((existing) => existing.id === file.id))
    ]);
    setFailedUpload((current) => {
      const previous = current?.entityId === entityId ? current.items : [];
      const untouched = previous.filter((item) => !items.some((sent) => sent.key === item.key));
      const next = [...untouched, ...result.failed];
      return next.length ? { entityId, items: next } : null;
    });
    const errors = [...selectionErrors, ...result.errors];
    if (errors.length) setError(errors.join(' '));
    if (result.uploaded.length) {
      setNotice(`${result.uploaded.length} file${result.uploaded.length === 1 ? '' : 's'} saved.`);
    }
  }

  async function updateMedia(action: () => Promise<void>) {
    if (mediaWrite.current) return;
    mediaWrite.current = true;
    setIsSaving(true);
    setError(null);
    setNotice(null);
    try {
      await action();
    } catch (failure) {
      setError(formatApiError(failure, 'Unable to update site evidence.'));
    } finally {
      mediaWrite.current = false;
      setIsSaving(false);
    }
  }

  async function uploadFiles(files: FileList | null, kind: 'photo' | 'attachment') {
    if (!scope || !files?.length) return;
    await updateMedia(async () => {
      const { items, errors } = await prepareMediaFiles(
        files,
        kind,
        MAX_REPORT_PHOTOS - uploadedFiles.filter((file) => file.kind === 'photo').length
      );
      if (errors.length) setError(errors.join(' '));
      if (!items.length) return;
      const update = savedDraft ?? (await persistDraft(watch() as UpdateFormValues, null, scope));
      setSavedDraft(update);
      await recordUploads(update.id, items, errors);
    });
  }

  async function removeFile(file: PhotoRecord) {
    if (!savedDraft || savedDraft.status !== 'draft') return;
    if (!window.confirm(`Remove ${file.original_name} from this site update (${savedDraft.id})?`))
      return;
    await updateMedia(async () => {
      await deletePhoto(file.id);
      setUploadedFiles((current) => current.filter((item) => item.id !== file.id));
      setNotice(`${file.original_name} removed.`);
    });
  }

  async function openFile(file: PhotoRecord, preview: boolean) {
    setOpeningFile(true);
    setError(null);
    try {
      const url = preview ? await getPhotoThumbnailUrl(file.id) : await getPhotoDownloadUrl(file.id);
      window.open(url, '_blank', 'noopener,noreferrer');
    } catch (failure) {
      setError(formatApiError(failure, 'Unable to open this file.'));
    } finally {
      setOpeningFile(false);
    }
  }

  async function saveDraft(values: UpdateFormValues) {
    if (!scope) return null;
    setError(null);
    setNotice(null);
    setIsSaving(true);
    try {
      const update =
        savedDraft?.status === 'draft' && !isDirty ? savedDraft : await persistDraft(values, savedDraft, scope);
      setSavedDraft(update);
      setNotice('Draft saved.');
      await loadUpdates(values.project_id);
      return update.id;
    } catch (saveError) {
      setError(formatApiError(saveError, 'Unable to save the site update.'));
      return null;
    } finally {
      setIsSaving(false);
    }
  }

  async function submitUpdate(values: UpdateFormValues) {
    if (!scope) return;
    setError(null);
    setNotice(null);
    setIsSaving(true);
    try {
      const draft =
        savedDraft?.status === 'draft' && !isDirty ? savedDraft : await persistDraft(values, savedDraft, scope);
      setSavedDraft(draft);
      await submitSupervisorUpdate(draft.id, draft.revision ?? 1, scope);
      setSavedDraft(null);
      setUploadedFiles([]);
      setFailedUpload(null);
      setLastAutosavedAt(null);
      reset(createDefaultValues());
      await clearSupervisorDraft(scope);
      setNotice('Site update submitted.');
      await loadUpdates(values.project_id);
    } catch (submitError) {
      setError(formatApiError(submitError, 'Unable to submit the site update.'));
    } finally {
      setIsSaving(false);
    }
  }

  return (
    <div className="grid gap-6 xl:grid-cols-[minmax(0,1fr)_380px]">
      <section className="space-y-4">
        <div>
          <p className="text-sm font-medium text-brand-600">Reports</p>
          <h2 className="text-2xl font-semibold text-theme-text-primary">Supervisor Site Update</h2>
        </div>

        {notice ? (
          <div className="alert-success flex items-center gap-2 rounded-md px-3 py-2 text-sm">
            <Check className="h-4 w-4" />
            <span>{notice}</span>
          </div>
        ) : null}
        {error ? (
          <div className="alert-error flex items-center gap-2 rounded-md px-3 py-2 text-sm" role="alert">
            <AlertTriangle className="h-4 w-4" />
            <span>{error}</span>
          </div>
        ) : null}
        {lastAutosavedAt ? (
          <div className="alert-info rounded-md px-3 py-2 text-sm">
            Draft autosaved at {lastAutosavedAt}.
          </div>
        ) : null}

        <form
          className="rounded-lg border border-theme-border bg-theme-card p-4 shadow-xs"
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
            <Field label="Activity and work scope" error={errors.activity_scope?.message}>
              <textarea className="form-field" maxLength={2000} {...register('activity_scope')} />
            </Field>
            <Field label="Progress notes" error={errors.progress_notes?.message}>
              <textarea className="form-field min-h-28" {...register('progress_notes')} />
            </Field>

            <Field label="Remaining work" error={errors.remaining_work?.message}>
              <textarea className="form-field" maxLength={2000} {...register('remaining_work')} />
            </Field>
            <div className="grid gap-3 sm:grid-cols-2">
              <Field label="Completed area" error={errors.completed_area?.message}>
                <input className="form-field" maxLength={255} {...register('completed_area')} />
              </Field>
              <Field label="Progress percentage" error={errors.progress_percentage?.message}>
                <input className="form-field" type="number" min="0" max="100" step="0.01"
                  {...register('progress_percentage')} />
              </Field>
              <Field label="Completed quantity" error={errors.completed_quantity?.message}>
                <input className="form-field" type="number" min="0" step="0.001"
                  {...register('completed_quantity')} />
              </Field>
              <Field label="Quantity unit" error={errors.quantity_unit?.message}>
                <input className="form-field" maxLength={30} {...register('quantity_unit')} />
              </Field>
            </div>
            <Field label="Delay notes" error={errors.delay_notes?.message}>
              <textarea className="form-field min-h-24" {...register('delay_notes')} />
            </Field>

            <Field label="Required notes" error={errors.required_notes?.message}>
              <textarea className="form-field min-h-24" {...register('required_notes')} />
            </Field>

            <div className="grid gap-4 md:grid-cols-2">
              <div>
                <div className="mb-2 flex items-center gap-2 text-sm font-medium text-theme-text-secondary">
                  <Image className="h-4 w-4" />
                  <span>Upload photos</span>
                </div>
                <FileDropZone
                  accept={REPORT_PHOTO_ACCEPT}
                  capture="environment"
                  disabled={isSaving}
                  hint={`${uploadedFiles.filter((file) => file.kind === 'photo').length} of 5 photos saved. JPEG, PNG or HEIC, up to 10 MiB each.`}
                  label="Drop photos here or tap to use camera"
                  multiple
                  onFiles={(files) => void uploadFiles(files, 'photo')}
                />
              </div>
              <div>
                <div className="mb-2 flex items-center gap-2 text-sm font-medium text-theme-text-secondary">
                  <Paperclip className="h-4 w-4" />
                  <span>Upload attachments</span>
                </div>
                <FileDropZone
                  accept={PDF_IMAGE_ACCEPT}
                  disabled={isSaving}
                  hint="PDF, JPEG or PNG, up to 10 MiB per file."
                  label="Drop attachments here or tap to browse"
                  multiple
                  onFiles={(files) => void uploadFiles(files, 'attachment')}
                />
              </div>
            </div>
            {failedUpload ? (
              <button
                className="form-field mt-3"
                disabled={isSaving}
                onClick={() => {
                  void updateMedia(() =>
                    recordUploads(failedUpload.entityId, failedUpload.items, [])
                  );
                }}
                type="button"
              >
                Retry {failedUpload.items.length} failed file(s)
              </button>
            ) : null}
            {uploadedFiles.length > 0 ? (
              <ul className="mt-4 grid gap-2 text-sm text-theme-text-secondary">
                {uploadedFiles.map((file) => (
                  <li
                    className="flex flex-wrap items-center justify-between gap-2 rounded-md border border-theme-border px-3 py-2"
                    key={file.id}
                  >
                    <div>
                      <p>{file.original_name}</p>
                      {file.mime_type === 'image/heic' && (
                        <p className="text-theme-text-muted">Original only</p>
                      )}
                    </div>
                    <div className="flex flex-wrap items-center gap-2">
                      <StatusBadge tone="success">{file.processing_status}</StatusBadge>
                      {file.thumbnail_path && (
                        <button
                          className="form-field"
                          disabled={openingFile || isSaving}
                          onClick={() => void openFile(file, true)}
                          type="button"
                        >
                          Preview
                        </button>
                      )}
                      <button
                        className="form-field"
                        disabled={openingFile || isSaving}
                        onClick={() => void openFile(file, false)}
                        type="button"
                      >
                        {file.mime_type === 'image/heic' ? 'Download original' : 'Open file'}
                      </button>
                      {savedDraft?.status === 'draft' ? (
                        <button
                          className="form-field"
                          disabled={isSaving}
                          onClick={() => void removeFile(file)}
                          type="button"
                        >
                          Remove
                        </button>
                      ) : null}
                    </div>
                  </li>
                ))}
              </ul>
            ) : null}
          </div>

          <div className="mt-5 flex flex-col-reverse gap-3 sm:flex-row sm:justify-end">
            <button
              className="inline-flex min-h-11 items-center justify-center gap-2 rounded-md border border-theme-border px-4 py-2 text-sm font-semibold text-theme-text-secondary hover:bg-theme-main disabled:opacity-60"
              disabled={isSaving}
              onClick={handleSubmit(saveDraft)}
              type="button"
            >
              <Save className="h-4 w-4" />
              Save draft
            </button>
            <button
              className="inline-flex min-h-11 items-center justify-center gap-2 rounded-md bg-brand-600 px-4 py-2 text-sm font-semibold text-white hover:bg-brand-700 disabled:opacity-60"
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
          <p className="text-sm font-medium text-brand-600">Current Records</p>
          <h3 className="text-xl font-semibold text-theme-text-primary">Recent Site Updates</h3>
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
                className="rounded-lg border border-theme-border bg-theme-card p-4 shadow-xs"
                key={update.id}
              >
                <div className="flex items-start justify-between gap-3">
                  <div>
                    <p className="text-sm font-semibold text-theme-text-primary">
                      {update.update_date}
                    </p>
                    <p className="text-xs text-theme-text-muted">{update.work_location}</p>
                  </div>
                  <StatusBadge tone={update.status === 'submitted' ? 'success' : 'warning'}>
                    {update.status}
                  </StatusBadge>
                </div>
                <div className="mt-3 flex items-center gap-2 text-xs text-theme-text-muted">
                  <ClipboardList className="h-4 w-4" />
                  <span>{update.attendance_count} attendance</span>
                  <span>{update.overtime_hours} overtime</span>
                </div>
                <p className="mt-3 line-clamp-3 text-sm text-theme-text-secondary">
                  {update.progress_notes}
                </p>
                {update.submission_revision != null && (
                  <UpdateHistory updateId={update.id} />
                )}
                {update.verified_at && (
                  <p className="mt-2 text-xs text-theme-text-muted">
                    Verified {new Date(update.verified_at).toLocaleString()}
                    {update.verified_by_name ? ` by ${update.verified_by_name}` : ''}
                    {update.verified_report_id && (
                      <span className="block">Linked report {update.verified_report_id}</span>
                    )}
                  </p>
                )}
                {update.previous_id && <p className="text-sm">Correction of {update.previous_id}</p>}
                {update.status === 'verified' && update.supervisor_id === user?.id && (
                  <button type="button" disabled={isSaving} className="form-button" onClick={async () => {
                    const reason = window.prompt('Reason for correcting confirmed progress')?.trim();
                    if (!reason) return;
                    setIsSaving(true);
                    try {
                      const corrected = await correctVerifiedSupervisorUpdate(update, reason, scope ?? undefined);
                      await resumeDraft(corrected);
                      await loadUpdates(update.project_id);
                    } catch (cause) {
                      setError(formatApiError(cause, 'Unable to start the correction.'));
                    } finally {
                      setIsSaving(false);
                    }
                  }}>Correct confirmed progress</button>
                )}
                {(['draft', 'returned', 'rejected'].includes(update.status) ||
                  (update.status === 'submitted' && update.submission_revision == null)) &&
                  update.supervisor_id === user?.id ? (
                  <button
                    className="mt-3 text-sm font-medium text-brand-600 hover:text-brand-700 disabled:opacity-50"
                    disabled={isSaving}
                    onClick={() => void resumeDraft(update)}
                    type="button"
                  >
                    {update.status === 'draft' ? 'Resume draft' : 'Correct and resubmit'}
                  </button>
                ) : null}
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
      <span className="mb-1 block text-sm font-medium text-theme-text-secondary">{label}</span>
      {children}
      {error ? (
        <span className="mt-1 block text-xs text-[var(--status-error-text)]">{error}</span>
      ) : null}
    </label>
  );
}

function UpdateHistory({ updateId }: { updateId: string }) {
  const [open, setOpen] = useState(false);
  return (
    <details className="mt-2 text-sm" onToggle={(event) => setOpen(event.currentTarget.open)}>
      <summary className="cursor-pointer">Submission and decision history</summary>
      {open && <SupervisorSubmissionHistory updateId={updateId} />}
    </details>
  );
}
