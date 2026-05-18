import { AlertTriangle, Check, Plus, Save, Send, Trash2 } from 'lucide-react';
import { FormEvent, useCallback, useEffect, useMemo, useRef, useState } from 'react';

import {
  clearReportDraft,
  flushPhotoQueue,
  getReportDraft,
  queueFiles,
  queuedPhotoCount,
  registerBackgroundSync,
  saveReportDraft
} from '../../api/offlineQueue';
import { uploadEntityFiles, type PhotoRecord } from '../../api/photos';
import { listProjects, type ProjectRecord } from '../../api/projects';
import {
  createDailyReport,
  downloadReportPdf,
  listDailyReports,
  submitDailyReport,
  updateDailyReport,
  type DailyReportPayload,
  type DailyReportRecord,
  type ReportManpower
} from '../../api/reports';
import { listSupervisorUpdates, type SupervisorUpdateRecord } from '../../api/supervisorUpdates';
import { EmptyState } from '../../components/shared/EmptyState';
import { StatusBadge } from '../../components/shared/StatusBadge';
import { useAuth } from '../../context/useAuth';

const today = new Date().toISOString().slice(0, 10);

const emptyPayload: DailyReportPayload = {
  project_id: '',
  report_date: today,
  work_location: '',
  manpower_total: 0,
  overtime_hours: '0',
  work_completed: '',
  progress_percentage: '0',
  safety_incidents: 0,
  safety_notes: '',
  wir_status: 'pending',
  inspection_status: 'pending',
  delay_notes: '',
  next_day_plan: '',
  supervisor_update_ids: [],
  photo_refs: [],
  attachment_refs: [],
  manpower_entries: [{ trade: '', count: 0, overtime_hours: '0' }],
  equipment_entries: [],
  material_consumption: [],
  extra_fields: {
    day_type: 'weekday',
    weather_condition: '',
    site_visitors: '',
    subcontractors: '',
    wir_number: ''
  }
};

type ReportExtraField =
  | 'day_type'
  | 'weather_condition'
  | 'site_visitors'
  | 'subcontractors'
  | 'wir_number';

function extraValue(form: DailyReportPayload, key: ReportExtraField) {
  const value = form.extra_fields?.[key];
  return typeof value === 'string' ? value : '';
}

function parseRefs(value: string, kind: string) {
  return value
    .split('\n')
    .map((name) => name.trim())
    .filter(Boolean)
    .map((name) => ({ name, kind }));
}

function formatApiError(error: unknown) {
  if (typeof error === 'object' && error !== null && 'response' in error) {
    const response = (error as { response?: { data?: { detail?: string } } }).response;
    if (response?.data?.detail) {
      return response.data.detail.replace(/_/g, ' ').toLowerCase();
    }
  }
  return 'Unable to save the daily report.';
}

function formHasDraftContent(payload: DailyReportPayload) {
  return Boolean(
    payload.project_id ||
      payload.work_location.trim() ||
      payload.work_completed.trim() ||
      payload.delay_notes?.trim() ||
      payload.next_day_plan.trim() ||
      payload.safety_notes?.trim() ||
      payload.report_date !== today ||
      payload.progress_percentage !== emptyPayload.progress_percentage ||
      payload.safety_incidents !== emptyPayload.safety_incidents ||
      payload.supervisor_update_ids.length > 0 ||
      payload.photo_refs.length > 0 ||
      payload.attachment_refs.length > 0 ||
      payload.equipment_entries.length > 0 ||
      payload.material_consumption.length > 0 ||
      payload.manpower_entries.some(
        (entry) =>
          entry.trade.trim() ||
          Number(entry.count || 0) > 0 ||
          Number(entry.overtime_hours || 0) > 0
      ) ||
      Object.entries(payload.extra_fields ?? {}).some(([key, value]) => {
        if (key === 'day_type') return value !== emptyPayload.extra_fields?.day_type;
        return typeof value === 'string' ? value.trim() : Boolean(value);
      })
  );
}

export function DailyReportPage() {
  const { user } = useAuth();
  const [projects, setProjects] = useState<ProjectRecord[]>([]);
  const [supervisorUpdates, setSupervisorUpdates] = useState<SupervisorUpdateRecord[]>([]);
  const [reports, setReports] = useState<DailyReportRecord[]>([]);
  const [form, setForm] = useState<DailyReportPayload>(emptyPayload);
  const [photoNames, setPhotoNames] = useState('');
  const [attachmentNames, setAttachmentNames] = useState('');
  const [uploadedFiles, setUploadedFiles] = useState<PhotoRecord[]>([]);
  const [errors, setErrors] = useState<Record<string, string>>({});
  const [notice, setNotice] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [savedReportId, setSavedReportId] = useState<string | null>(null);
  const [isSaving, setIsSaving] = useState(false);
  const [draftStatus, setDraftStatus] = useState<'idle' | 'local' | 'server_newer'>('idle');
  const [queuedUploads, setQueuedUploads] = useState(0);
  const [draftHydrated, setDraftHydrated] = useState(false);
  const persistedDraftSnapshot = useRef(JSON.stringify(emptyPayload));
  const serverSavedSnapshot = useRef(JSON.stringify(emptyPayload));

  const selectedProject = useMemo(
    () => projects.find((project) => project.id === form.project_id),
    [form.project_id, projects]
  );
  const canSubmitReports = user?.permissions?.includes('reports:submit') ?? false;

  const loadReports = useCallback(async (projectId?: string) => {
    const response = await listDailyReports({ project_id: projectId || undefined });
    setReports(response.items);
  }, []);

  useEffect(() => {
    Promise.all([listProjects({ status: 'active' }), listDailyReports({})])
      .then(([projectResponse, reportResponse]) => {
        setProjects(projectResponse.items);
        setReports(reportResponse.items);
      })
      .catch(() => setError('Unable to load report data.'));
  }, []);

  useEffect(() => {
    void getReportDraft().then((draft) => {
      if (draft?.payload && formHasDraftContent(draft.payload)) {
        setForm(draft.payload);
        persistedDraftSnapshot.current = JSON.stringify(draft.payload);
        setDraftStatus('local');
      }
      setDraftHydrated(true);
    });
    void queuedPhotoCount().then(setQueuedUploads);
  }, []);

  useEffect(() => {
    if (!draftHydrated) return;
    const snapshot = JSON.stringify(form);
    if (snapshot === persistedDraftSnapshot.current || snapshot === serverSavedSnapshot.current) {
      return;
    }
    if (!formHasDraftContent(form)) {
      const timer = window.setTimeout(() => {
        void clearReportDraft().then(() => {
          persistedDraftSnapshot.current = JSON.stringify(emptyPayload);
          setDraftStatus('idle');
        });
      }, 800);
      return () => window.clearTimeout(timer);
    }
    const timer = window.setTimeout(() => {
      void saveReportDraft(form).then(() => {
        persistedDraftSnapshot.current = snapshot;
        setDraftStatus('local');
      });
    }, 800);
    const interval = window.setInterval(() => {
      void saveReportDraft(form).then(() => {
        persistedDraftSnapshot.current = JSON.stringify(form);
        setDraftStatus('local');
      });
    }, 30_000);
    return () => {
      window.clearTimeout(timer);
      window.clearInterval(interval);
    };
  }, [draftHydrated, form]);

  useEffect(() => {
    const syncQueued = () => {
      void flushPhotoQueue()
        .then(() => queuedPhotoCount())
        .then(setQueuedUploads);
    };
    const refreshQueuedCount = () => {
      void queuedPhotoCount().then(setQueuedUploads);
    };
    window.addEventListener('online', syncQueued);
    window.addEventListener('photo-queue-sync-complete', refreshQueuedCount);
    if (navigator.onLine) syncQueued();
    return () => {
      window.removeEventListener('online', syncQueued);
      window.removeEventListener('photo-queue-sync-complete', refreshQueuedCount);
    };
  }, []);

  useEffect(() => {
    if (!form.project_id) {
      setSupervisorUpdates([]);
      return;
    }
    void Promise.all([
      listSupervisorUpdates({ project_id: form.project_id, status: 'submitted' }),
      loadReports(form.project_id)
    ])
      .then(([updateResponse]) => setSupervisorUpdates(updateResponse.items))
      .catch(() => setError('Unable to load supervisor updates.'));
  }, [form.project_id, loadReports]);

  function validate() {
    const nextErrors: Record<string, string> = {};
    if (!form.project_id) nextErrors.project_id = 'Select a project.';
    if (!form.report_date) nextErrors.report_date = 'Select a date.';
    if (!form.work_location.trim()) nextErrors.work_location = 'Enter the work location.';
    if (!form.work_completed.trim()) nextErrors.work_completed = 'Enter work completed.';
    if (!form.next_day_plan.trim()) nextErrors.next_day_plan = 'Enter the next-day plan.';
    if (!extraValue(form, 'weather_condition').trim()) {
      nextErrors.weather_condition = 'Select or enter the weather condition.';
    }
    if (!extraValue(form, 'site_visitors').trim()) {
      nextErrors.site_visitors = 'Enter site visitors or write none.';
    }
    if (!extraValue(form, 'subcontractors').trim()) {
      nextErrors.subcontractors = 'Enter subcontractors or write none.';
    }
    if (!extraValue(form, 'wir_number').trim()) {
      nextErrors.wir_number = 'Enter the WIR number or write not required.';
    }
    if (Number(form.progress_percentage) < 0 || Number(form.progress_percentage) > 100) {
      nextErrors.progress_percentage = 'Progress must be between 0 and 100.';
    }
    if (form.manpower_entries.some((entry) => !entry.trade.trim())) {
      nextErrors.manpower_entries = 'Every manpower row needs a trade.';
    }
    setErrors(nextErrors);
    return Object.keys(nextErrors).length === 0;
  }

  function buildPayload(): DailyReportPayload {
    return {
      ...form,
      photo_refs: parseRefs(photoNames, 'photo'),
      attachment_refs: parseRefs(attachmentNames, 'file'),
      manpower_entries: form.manpower_entries.filter((entry) => entry.trade.trim()),
      equipment_entries: form.equipment_entries.filter((entry) => entry.equipment_name.trim()),
      material_consumption: form.material_consumption.filter((entry) => entry.material_name.trim())
    };
  }

  function updateExtraField(key: ReportExtraField, value: string) {
    setForm({
      ...form,
      extra_fields: {
        ...form.extra_fields,
        [key]: value
      }
    });
  }

  async function saveDraft() {
    if (!validate()) return null;
    setIsSaving(true);
    setError(null);
    setNotice(null);
    try {
      const payload = buildPayload();
      const report = savedReportId
        ? await updateDailyReport(savedReportId, payload)
        : await createDailyReport(payload);
      setSavedReportId(report.id);
      await clearReportDraft();
      serverSavedSnapshot.current = JSON.stringify(payload);
      persistedDraftSnapshot.current = JSON.stringify(payload);
      setDraftStatus('idle');
      setNotice('Daily report draft saved.');
      await loadReports(payload.project_id);
      return report.id;
    } catch (saveError) {
      setError(formatApiError(saveError));
      return null;
    } finally {
      setIsSaving(false);
    }
  }

  async function submitReport(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    const reportId = savedReportId ?? (await saveDraft());
    if (!reportId) return;
    setIsSaving(true);
    setError(null);
    setNotice(null);
    try {
      const report = await submitDailyReport(reportId);
      setForm(emptyPayload);
      setPhotoNames('');
      setAttachmentNames('');
      setSavedReportId(null);
      await clearReportDraft();
      serverSavedSnapshot.current = JSON.stringify(emptyPayload);
      persistedDraftSnapshot.current = JSON.stringify(emptyPayload);
      setDraftStatus('idle');
      setNotice(`Daily report ${report.report_number} submitted.`);
      await loadReports(report.project_id);
    } catch (submitError) {
      setError(formatApiError(submitError));
    } finally {
      setIsSaving(false);
    }
  }

  async function downloadPdf(report: DailyReportRecord) {
    setError(null);
    try {
      const blob = await downloadReportPdf(report.id);
      const url = window.URL.createObjectURL(blob);
      const link = document.createElement('a');
      link.href = url;
      link.download = `${report.report_number ?? report.id}.pdf`;
      link.click();
      window.URL.revokeObjectURL(url);
    } catch {
      setError('Unable to download the report PDF.');
    }
  }

  async function uploadFiles(files: FileList | null, kind: 'photo' | 'attachment') {
    if (!files?.length) return;
    const fileList = Array.from(files);
    if (kind === 'photo' && fileList.length > 5) {
      setError('Maximum 5 photos allowed per report.');
      return;
    }
    const maxSize = kind === 'photo' ? 10 * 1024 * 1024 : 60 * 1024 * 1024;
    const label = kind === 'photo' ? '10 MB' : '60 MB';
    if (fileList.some((f) => f.size > maxSize)) {
      setError(`File size exceeds the ${label} limit.`);
      return;
    }
    const payload = buildPayload();
    if (!navigator.onLine) {
      if (!validate()) return;
      await saveReportDraft(payload);
      await queueFiles({
        entityType: 'daily_report',
        entityId: savedReportId ?? undefined,
        draftPayload: savedReportId ? undefined : payload,
        kind,
        files
      });
      await registerBackgroundSync();
      const count = await queuedPhotoCount();
      setQueuedUploads(count);
      setDraftStatus('local');
      setNotice(`${files.length} file${files.length > 1 ? 's' : ''} queued for upload.`);
      return;
    }
    const reportId = savedReportId ?? (await saveDraft());
    if (!reportId) return;
    setIsSaving(true);
    setError(null);
    try {
      const uploaded = await uploadEntityFiles({
        entityType: 'daily_report',
        entityId: reportId,
        kind,
        files
      });
      setUploadedFiles([...uploadedFiles, ...uploaded]);
      setNotice(`${uploaded.length} ${kind === 'photo' ? 'photo' : 'attachment'} file saved.`);
    } catch {
      setError('Unable to upload the selected file.');
    } finally {
      setIsSaving(false);
    }
  }

  if (!canSubmitReports) {
    return (
      <section className="space-y-4">
        <div>
          <p className="text-sm font-medium text-brand-600">Reports</p>
          <h2 className="text-2xl font-semibold text-theme-text-primary">Daily Reports</h2>
          <p className="mt-1 text-sm text-theme-text-muted">
            Review submitted and approved site reports across accessible projects.
          </p>
        </div>

        {error ? <Alert tone="error" message={error} /> : null}

        {reports.length === 0 ? (
          <EmptyState
            description="Submitted and draft engineer reports will appear here."
            title="No daily reports found"
          />
        ) : (
          <div className="grid gap-3">
            {reports.map((report) => (
              <article
                className="rounded-lg border border-theme-border bg-theme-card p-4 shadow-sm"
                key={report.id}
              >
                <div className="flex flex-col justify-between gap-3 sm:flex-row sm:items-start">
                  <div>
                    <div className="flex flex-wrap items-center gap-2">
                      <h3 className="text-base font-semibold text-theme-text-primary">
                        {report.report_number ?? 'Draft report'}
                      </h3>
                      <StatusBadge tone={report.status === 'submitted' ? 'info' : 'warning'}>
                        {report.status}
                      </StatusBadge>
                    </div>
                    <p className="mt-1 text-sm text-theme-text-muted">
                      {report.report_date} - {report.work_location}
                    </p>
                  </div>
                  <p className="text-sm font-medium text-theme-text-secondary">
                    {report.progress_percentage}% progress
                  </p>
                </div>

                <div className="mt-4 grid gap-4 lg:grid-cols-2">
                  <div>
                    <h4 className="text-sm font-semibold text-theme-text-primary">
                      Work completed
                    </h4>
                    <p className="mt-1 text-sm text-theme-text-secondary">
                      {report.work_completed}
                    </p>
                  </div>
                  <div>
                    <h4 className="text-sm font-semibold text-theme-text-primary">
                      Next-day plan
                    </h4>
                    <p className="mt-1 text-sm text-theme-text-secondary">
                      {report.next_day_plan}
                    </p>
                  </div>
                  <div>
                    <h4 className="text-sm font-semibold text-theme-text-primary">Safety</h4>
                    <p className="mt-1 text-sm text-theme-text-secondary">
                      {report.safety_incidents} incidents. {report.safety_notes || 'No notes.'}
                    </p>
                  </div>
                  <div>
                    <h4 className="text-sm font-semibold text-theme-text-primary">History</h4>
                    <p className="mt-1 text-sm text-theme-text-secondary">
                      {report.approval_history.length} workflow events recorded.
                    </p>
                  </div>
                </div>

                {report.status === 'approved' ? (
                  <button
                    className="mt-4 rounded-md border border-theme-border px-3 py-2 text-sm font-semibold text-theme-text-secondary hover:bg-theme-main"
                    onClick={() => void downloadPdf(report)}
                    type="button"
                  >
                    Download PDF
                  </button>
                ) : null}
              </article>
            ))}
          </div>
        )}
      </section>
    );
  }

  return (
    <div className="grid gap-6 xl:grid-cols-[minmax(0,1fr)_380px]">
      <section className="space-y-4">
        <div>
          <p className="text-sm font-medium text-brand-600">Reports</p>
          <h2 className="text-2xl font-semibold text-theme-text-primary">Engineer Daily Report</h2>
          {selectedProject ? (
            <p className="mt-1 text-sm text-theme-text-muted">
              {selectedProject.code} - {selectedProject.name}
            </p>
          ) : null}
        </div>

        {notice ? <Alert tone="success" message={notice} /> : null}
        {error ? <Alert tone="error" message={error} /> : null}
        {draftStatus === 'local' || queuedUploads > 0 ? (
          <div className="alert-warning rounded-md border border-[var(--status-warning-border)] px-3 py-2 text-sm">
            Local draft active
            {queuedUploads > 0
              ? `, ${queuedUploads} upload${queuedUploads > 1 ? 's' : ''} queued`
              : ''}
            . Sync resumes automatically when the connection is available.
          </div>
        ) : null}

        <form className="space-y-4" onSubmit={submitReport}>
          <section className="rounded-lg border border-theme-border bg-theme-card p-4 shadow-sm">
            <div className="grid gap-4 md:grid-cols-2">
              <Field label="Project" error={errors.project_id}>
                <select
                  className="form-field"
                  onChange={(event) => setForm({ ...form, project_id: event.target.value })}
                  value={form.project_id}
                >
                  <option value="">Select project</option>
                  {projects.map((project) => (
                    <option key={project.id} value={project.id}>
                      {project.code} - {project.name}
                    </option>
                  ))}
                </select>
              </Field>
              <Field label="Report date" error={errors.report_date}>
                <input
                  className="form-field"
                  onChange={(event) => setForm({ ...form, report_date: event.target.value })}
                  type="date"
                  value={form.report_date}
                />
              </Field>
              <Field label="Work area / location" error={errors.work_location}>
                <input
                  className="form-field"
                  onChange={(event) => setForm({ ...form, work_location: event.target.value })}
                  value={form.work_location}
                />
              </Field>
              <Field label="Progress %" error={errors.progress_percentage}>
                <input
                  className="form-field"
                  max="100"
                  min="0"
                  onChange={(event) =>
                    setForm({ ...form, progress_percentage: event.target.value })
                  }
                  type="number"
                  value={form.progress_percentage}
                />
              </Field>
              <Field label="Day type">
                <select
                  className="form-field"
                  onChange={(event) => updateExtraField('day_type', event.target.value)}
                  value={extraValue(form, 'day_type') || 'weekday'}
                >
                  <option value="weekday">Weekday</option>
                  <option value="friday">Friday</option>
                  <option value="public_holiday">Public holiday</option>
                </select>
              </Field>
              <Field label="Weather" error={errors.weather_condition}>
                <input
                  className="form-field"
                  list="weather-options"
                  onChange={(event) => updateExtraField('weather_condition', event.target.value)}
                  placeholder="Sunny, cloudy, rainy, windy"
                  value={extraValue(form, 'weather_condition')}
                />
                <datalist id="weather-options">
                  <option value="Sunny" />
                  <option value="Cloudy" />
                  <option value="Rainy" />
                  <option value="Windy" />
                  <option value="Dusty" />
                </datalist>
              </Field>
            </div>
          </section>

          <section className="rounded-lg border border-theme-border bg-theme-card p-4 shadow-sm">
            <SectionHeader title="Supervisor Updates" />
            {supervisorUpdates.length === 0 ? (
              <p className="text-sm text-theme-text-muted">
                No submitted supervisor updates found.
              </p>
            ) : (
              <div className="grid gap-2">
                {supervisorUpdates.map((update) => (
                  <label
                    className="flex items-start gap-3 rounded-md border border-theme-border p-3 text-sm"
                    key={update.id}
                  >
                    <input
                      checked={form.supervisor_update_ids.includes(update.id)}
                      className="mt-1"
                      onChange={(event) => {
                        const selected = event.target.checked
                          ? [...form.supervisor_update_ids, update.id]
                          : form.supervisor_update_ids.filter((id) => id !== update.id);
                        setForm({ ...form, supervisor_update_ids: selected });
                      }}
                      type="checkbox"
                    />
                    <span>
                      <span className="block font-medium text-theme-text-primary">
                        {update.update_date} - {update.work_location}
                      </span>
                      <span className="line-clamp-2 text-theme-text-muted">
                        {update.progress_notes}
                      </span>
                    </span>
                  </label>
                ))}
              </div>
            )}
          </section>

          <section className="rounded-lg border border-theme-border bg-theme-card p-4 shadow-sm">
            <SectionHeader title="Work Summary" />
            <div className="grid gap-4">
              <Field label="Work completed" error={errors.work_completed}>
                <textarea
                  className="form-field min-h-28"
                  onChange={(event) => setForm({ ...form, work_completed: event.target.value })}
                  value={form.work_completed}
                />
              </Field>
              <Field label="Delays">
                <textarea
                  className="form-field min-h-20"
                  onChange={(event) => setForm({ ...form, delay_notes: event.target.value })}
                  value={form.delay_notes ?? ''}
                />
              </Field>
              <Field label="Next-day plan" error={errors.next_day_plan}>
                <textarea
                  className="form-field min-h-24"
                  onChange={(event) => setForm({ ...form, next_day_plan: event.target.value })}
                  value={form.next_day_plan}
                />
              </Field>
              <div className="grid gap-4 md:grid-cols-2">
                <Field label="Site visitors" error={errors.site_visitors}>
                  <textarea
                    className="form-field min-h-20"
                    onChange={(event) => updateExtraField('site_visitors', event.target.value)}
                    placeholder="Client engineer, consultant, none"
                    value={extraValue(form, 'site_visitors')}
                  />
                </Field>
                <Field label="Subcontractors" error={errors.subcontractors}>
                  <textarea
                    className="form-field min-h-20"
                    onChange={(event) => updateExtraField('subcontractors', event.target.value)}
                    placeholder="MEP subcontractor, plaster crew, none"
                    value={extraValue(form, 'subcontractors')}
                  />
                </Field>
              </div>
            </div>
          </section>

          <section className="rounded-lg border border-theme-border bg-theme-card p-4 shadow-sm">
            <SectionHeader title="Safety And Inspection" />
            <div className="grid gap-4 md:grid-cols-2">
              <Field label="Safety incidents">
                <input
                  className="form-field"
                  min="0"
                  onChange={(event) =>
                    setForm({ ...form, safety_incidents: Number(event.target.value) })
                  }
                  type="number"
                  value={form.safety_incidents}
                />
              </Field>
              <Field label="WIR status">
                <select
                  className="form-field"
                  onChange={(event) => setForm({ ...form, wir_status: event.target.value })}
                  value={form.wir_status}
                >
                  <option value="pending">Pending</option>
                  <option value="passed">Passed</option>
                  <option value="failed">Failed</option>
                  <option value="not_required">Not required</option>
                </select>
              </Field>
              <Field label="Inspection status">
                <select
                  className="form-field"
                  onChange={(event) => setForm({ ...form, inspection_status: event.target.value })}
                  value={form.inspection_status}
                >
                  <option value="pending">Pending</option>
                  <option value="completed">Completed</option>
                  <option value="failed">Failed</option>
                  <option value="not_required">Not required</option>
                </select>
              </Field>
              <Field label="WIR number" error={errors.wir_number}>
                <input
                  className="form-field"
                  onChange={(event) => updateExtraField('wir_number', event.target.value)}
                  placeholder="GAR-WIR-2026-001 or not required"
                  value={extraValue(form, 'wir_number')}
                />
              </Field>
              <Field label="Safety notes">
                <textarea
                  className="form-field min-h-20"
                  onChange={(event) => setForm({ ...form, safety_notes: event.target.value })}
                  value={form.safety_notes ?? ''}
                />
              </Field>
            </div>
          </section>

          <DynamicRows
            addLabel="Add manpower"
            error={errors.manpower_entries}
            render={(entry, index) => (
              <div className="grid gap-3 md:grid-cols-[1fr_120px_140px_auto]">
                <input
                  className="form-field"
                  onChange={(event) =>
                    updateRow('manpower_entries', index, { ...entry, trade: event.target.value })
                  }
                  placeholder="Trade"
                  value={entry.trade}
                />
                <input
                  className="form-field"
                  min="0"
                  onChange={(event) =>
                    updateRow('manpower_entries', index, {
                      ...entry,
                      count: Number(event.target.value)
                    })
                  }
                  type="number"
                  value={entry.count}
                />
                <input
                  className="form-field"
                  min="0"
                  onChange={(event) =>
                    updateRow('manpower_entries', index, {
                      ...entry,
                      overtime_hours: event.target.value
                    })
                  }
                  type="number"
                  value={entry.overtime_hours}
                />
                <RemoveButton onClick={() => removeRow('manpower_entries', index)} />
              </div>
            )}
            rows={form.manpower_entries}
            title="Manpower"
            onAdd={() =>
              setForm({
                ...form,
                manpower_entries: [
                  ...form.manpower_entries,
                  { trade: '', count: 0, overtime_hours: '0' }
                ]
              })
            }
          />

          <DynamicRows
            addLabel="Add equipment"
            render={(entry, index) => (
              <div className="grid gap-3 md:grid-cols-[1fr_100px_120px_1fr_auto]">
                <input
                  className="form-field"
                  onChange={(event) =>
                    updateRow('equipment_entries', index, {
                      ...entry,
                      equipment_name: event.target.value
                    })
                  }
                  placeholder="Equipment"
                  value={entry.equipment_name}
                />
                <input
                  className="form-field"
                  min="0"
                  onChange={(event) =>
                    updateRow('equipment_entries', index, {
                      ...entry,
                      quantity: Number(event.target.value)
                    })
                  }
                  type="number"
                  value={entry.quantity}
                />
                <input
                  className="form-field"
                  min="0"
                  onChange={(event) =>
                    updateRow('equipment_entries', index, {
                      ...entry,
                      hours_used: event.target.value
                    })
                  }
                  type="number"
                  value={entry.hours_used}
                />
                <input
                  className="form-field"
                  onChange={(event) =>
                    updateRow('equipment_entries', index, {
                      ...entry,
                      remarks: event.target.value
                    })
                  }
                  placeholder="Remarks"
                  value={entry.remarks ?? ''}
                />
                <RemoveButton onClick={() => removeRow('equipment_entries', index)} />
              </div>
            )}
            rows={form.equipment_entries}
            title="Equipment"
            onAdd={() =>
              setForm({
                ...form,
                equipment_entries: [
                  ...form.equipment_entries,
                  { equipment_name: '', quantity: 0, hours_used: '0', remarks: '' }
                ]
              })
            }
          />

          <DynamicRows
            addLabel="Add material"
            render={(entry, index) => (
              <div className="grid gap-3 md:grid-cols-[1fr_90px_120px_1fr_auto]">
                <input
                  className="form-field"
                  onChange={(event) =>
                    updateRow('material_consumption', index, {
                      ...entry,
                      material_name: event.target.value
                    })
                  }
                  placeholder="Material"
                  value={entry.material_name}
                />
                <input
                  className="form-field"
                  onChange={(event) =>
                    updateRow('material_consumption', index, {
                      ...entry,
                      unit: event.target.value
                    })
                  }
                  placeholder="Unit"
                  value={entry.unit}
                />
                <input
                  className="form-field"
                  min="0"
                  onChange={(event) =>
                    updateRow('material_consumption', index, {
                      ...entry,
                      quantity: event.target.value
                    })
                  }
                  type="number"
                  value={entry.quantity}
                />
                <input
                  className="form-field"
                  onChange={(event) =>
                    updateRow('material_consumption', index, {
                      ...entry,
                      remarks: event.target.value
                    })
                  }
                  placeholder="Remarks"
                  value={entry.remarks ?? ''}
                />
                <RemoveButton onClick={() => removeRow('material_consumption', index)} />
              </div>
            )}
            rows={form.material_consumption}
            title="Material Consumption"
            onAdd={() =>
              setForm({
                ...form,
                material_consumption: [
                  ...form.material_consumption,
                  { material_name: '', unit: '', quantity: '0', remarks: '' }
                ]
              })
            }
          />

          <section className="rounded-lg border border-theme-border bg-theme-card p-4 shadow-sm">
            <SectionHeader title="Photos And Attachments" />
            <div className="grid gap-4 md:grid-cols-2">
              <Field label="Upload photos">
                <input
                  accept="image/jpeg,image/png,image/heic"
                  capture="environment"
                  className="form-field"
                  multiple
                  onChange={(event) => void uploadFiles(event.target.files, 'photo')}
                  type="file"
                />
              </Field>
              <Field label="Upload attachments">
                <input
                  accept="application/pdf,image/jpeg,image/png"
                  className="form-field"
                  multiple
                  onChange={(event) => void uploadFiles(event.target.files, 'attachment')}
                  type="file"
                />
              </Field>
              <Field label="Photo file names">
                <textarea
                  className="form-field min-h-20"
                  onChange={(event) => setPhotoNames(event.target.value)}
                  placeholder="zone-a.jpg"
                  value={photoNames}
                />
              </Field>
              <Field label="Attachment file names">
                <textarea
                  className="form-field min-h-20"
                  onChange={(event) => setAttachmentNames(event.target.value)}
                  placeholder="inspection.pdf"
                  value={attachmentNames}
                />
              </Field>
            </div>
            {uploadedFiles.length > 0 ? (
              <div className="mt-4 grid gap-2 text-sm text-theme-text-secondary">
                {uploadedFiles.map((file) => (
                  <div
                    className="flex items-center justify-between rounded-md border border-theme-border px-3 py-2"
                    key={file.id}
                  >
                    <span>{file.original_name}</span>
                    <StatusBadge tone="success">{file.processing_status}</StatusBadge>
                  </div>
                ))}
              </div>
            ) : null}
          </section>

          <div className="flex flex-col-reverse gap-3 sm:flex-row sm:justify-end">
            <button
              className="inline-flex min-h-11 items-center justify-center gap-2 rounded-md border border-theme-border px-4 py-2 text-sm font-semibold text-theme-text-secondary hover:bg-theme-main disabled:opacity-60"
              disabled={isSaving}
              onClick={() => void saveDraft()}
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
              Submit report
            </button>
          </div>
        </form>
      </section>

      <aside className="space-y-4">
        <div>
          <p className="text-sm font-medium text-brand-600">Official Reports</p>
          <h3 className="text-xl font-semibold text-theme-text-primary">Recent Daily Reports</h3>
        </div>
        {reports.length === 0 ? (
          <EmptyState
            description="Draft and submitted engineer reports will appear here."
            title="No daily reports found"
          />
        ) : (
          <div className="space-y-3">
            {reports.map((report) => (
              <article
                className="rounded-lg border border-theme-border bg-theme-card p-4 shadow-sm"
                key={report.id}
              >
                <div className="flex items-start justify-between gap-3">
                  <div>
                    <p className="text-sm font-semibold text-theme-text-primary">
                      {report.report_number ?? 'Draft report'}
                    </p>
                    <p className="text-xs text-theme-text-muted">{report.report_date}</p>
                  </div>
                  <StatusBadge tone={report.status === 'submitted' ? 'info' : 'warning'}>
                    {report.status}
                  </StatusBadge>
                </div>
                <p className="mt-3 text-sm text-theme-text-secondary">{report.work_location}</p>
                <p className="mt-1 text-xs text-theme-text-muted">
                  {report.progress_percentage}% progress
                </p>
                {report.status === 'approved' ? (
                  <button
                    className="mt-3 rounded-md border border-theme-border px-3 py-2 text-sm font-semibold text-theme-text-secondary hover:bg-theme-main"
                    onClick={() => void downloadPdf(report)}
                    type="button"
                  >
                    Download PDF
                  </button>
                ) : null}
              </article>
            ))}
          </div>
        )}
      </aside>
    </div>
  );

  function updateRow<
    K extends keyof Pick<
      DailyReportPayload,
      'manpower_entries' | 'equipment_entries' | 'material_consumption'
    >
  >(key: K, index: number, value: DailyReportPayload[K][number]) {
    const rows = [...form[key]];
    rows[index] = value;
    const nextForm = { ...form, [key]: rows };
    if (key === 'manpower_entries') {
      nextForm.manpower_total = (rows as ReportManpower[]).reduce(
        (total, entry) => total + Number(entry.count || 0),
        0
      );
      nextForm.overtime_hours = (rows as ReportManpower[])
        .reduce((total, entry) => total + Number(entry.overtime_hours || 0), 0)
        .toString();
    }
    setForm(nextForm);
  }

  function removeRow<
    K extends keyof Pick<
      DailyReportPayload,
      'manpower_entries' | 'equipment_entries' | 'material_consumption'
    >
  >(key: K, index: number) {
    const rows = form[key].filter((_, rowIndex) => rowIndex !== index);
    setForm({ ...form, [key]: rows });
  }
}

function Alert({ message, tone }: { message: string; tone: 'error' | 'success' }) {
  const Icon = tone === 'success' ? Check : AlertTriangle;
  const cls = tone === 'success' ? 'alert-success' : 'alert-error';
  return (
    <div className={`flex items-center gap-2 rounded-md px-3 py-2 text-sm ${cls}`}>
      <Icon className="h-4 w-4" />
      <span>{message}</span>
    </div>
  );
}

function SectionHeader({ title }: { title: string }) {
  return <h3 className="mb-3 text-base font-semibold text-theme-text-primary">{title}</h3>;
}

function Field({
  children,
  error,
  label
}: {
  children: React.ReactNode;
  error?: string;
  label: string;
}) {
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

function DynamicRows<T>({
  addLabel,
  error,
  onAdd,
  render,
  rows,
  title
}: {
  addLabel: string;
  error?: string;
  onAdd: () => void;
  render: (row: T, index: number) => React.ReactNode;
  rows: T[];
  title: string;
}) {
  return (
    <section className="rounded-lg border border-theme-border bg-theme-card p-4 shadow-sm">
      <div className="mb-3 flex items-center justify-between gap-3">
        <h3 className="text-base font-semibold text-theme-text-primary">{title}</h3>
        <button
          className="inline-flex items-center gap-2 rounded-md border border-theme-border px-3 py-2 text-sm font-semibold text-theme-text-secondary hover:bg-theme-main"
          onClick={onAdd}
          type="button"
        >
          <Plus className="h-4 w-4" />
          {addLabel}
        </button>
      </div>
      {error ? <p className="mb-2 text-xs text-[var(--status-error-text)]">{error}</p> : null}
      <div className="space-y-3">{rows.map((row, index) => render(row, index))}</div>
    </section>
  );
}

function RemoveButton({ onClick }: { onClick: () => void }) {
  return (
    <button
      aria-label="Remove row"
      className="inline-flex min-h-10 items-center justify-center rounded-md border border-theme-border px-3 text-theme-text-secondary hover:bg-theme-main"
      onClick={onClick}
      type="button"
    >
      <Trash2 className="h-4 w-4" />
    </button>
  );
}
