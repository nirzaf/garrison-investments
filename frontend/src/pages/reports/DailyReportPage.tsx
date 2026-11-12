import { AlertTriangle, Check, Plus, Save, Send, Trash2 } from 'lucide-react';
import { FormEvent, useCallback, useEffect, useMemo, useRef, useState } from 'react';
import { useSearchParams } from 'react-router-dom';

import { getBrowserSession } from '../../api/browserSession';
import { sameScope, type OfflineScope } from '../../api/offlineDb';
import { formatApiError } from '../../api/errors';
import { MAX_REPORT_PHOTOS, PDF_IMAGE_ACCEPT, REPORT_PHOTO_ACCEPT } from '../../api/fileValidation';
import {
  clearReportDraft,
  flushPhotoQueue,
  getReportDraft,
  isReportSyncActive,
  queueFiles,
  queuedPhotoCount,
  queuedDraftPhotoCount,
  acknowledgeReportEvidenceRevision,
  registerBackgroundSync,
  saveReportDraft,
  type LocalReportDraft
} from '../../api/offlineQueue';
import {
  listPhotos,
  prepareMediaFiles,
  uploadMediaFiles,
  type MediaUploadIntent,
  type PhotoRecord
} from '../../api/photos';
import { listProjects, type ProjectRecord } from '../../api/projects';
import {
  getDailyReport,
  downloadReportPdf,
  listDailyReports,
  submitDailyReport,
  type DailyReportPayload,
  type DailyReportRecord
} from '../../api/reports';
import {
  listReportSupervisorUpdates,
  listSupervisorUpdates,
  type SupervisorUpdateRecord
} from '../../api/supervisorUpdates';
import { businessDate } from '../../businessDate';
import { EmptyState } from '../../components/shared/EmptyState';
import { StatusBadge } from '../../components/shared/StatusBadge';
import { useAuth } from '../../context/useAuth';

const emptyPayload: DailyReportPayload = {
  project_id: '',
  report_date: '',
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

function createEmptyPayload(): DailyReportPayload {
  return { ...emptyPayload, report_date: businessDate() };
}

type ReportExtraField =
  'day_type' | 'weather_condition' | 'site_visitors' | 'subcontractors' | 'wir_number';

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

function restoreRefs(refs: DailyReportRecord['photo_refs'], defaultKind: string) {
  return refs.flatMap(({ name, kind }) =>
    typeof name === 'string' ? [{ name, kind: typeof kind === 'string' ? kind : defaultKind }] : []
  );
}

function reportForm(report: DailyReportRecord): DailyReportPayload {
  return {
    project_id: report.project_id,
    report_date: report.report_date,
    work_location: report.work_location,
    manpower_total: report.manpower_total,
    overtime_hours: report.overtime_hours,
    work_completed: report.work_completed,
    progress_percentage: report.progress_percentage,
    safety_incidents: report.safety_incidents,
    safety_notes: report.safety_notes,
    wir_status: report.wir_status,
    inspection_status: report.inspection_status,
    delay_notes: report.delay_notes,
    next_day_plan: report.next_day_plan,
    supervisor_update_ids: report.supervisor_update_ids,
    photo_refs: restoreRefs(report.photo_refs, 'photo'),
    attachment_refs: restoreRefs(report.attachment_refs, 'file'),
    manpower_entries: report.manpower_entries.map(({ trade, count, overtime_hours }) => ({
      trade,
      count,
      overtime_hours
    })),
    equipment_entries: report.equipment_entries.map(
      ({ equipment_name, quantity, hours_used, remarks }) => ({
        equipment_name,
        quantity,
        hours_used,
        remarks
      })
    ),
    material_consumption: report.material_consumption.map(
      ({ boq_item_id, material_name, quantity, unit, remarks }) => ({
        boq_item_id,
        material_name,
        quantity,
        unit,
        remarks
      })
    ),
    extra_fields: { ...emptyPayload.extra_fields, ...report.extra_fields }
  };
}

function withManpowerTotals(form: DailyReportPayload): DailyReportPayload {
  const totals = form.manpower_entries.reduce(
    (total, entry) => ({
      count: total.count + Number(entry.count || 0),
      hours: total.hours + Number(entry.overtime_hours || 0)
    }),
    { count: 0, hours: 0 }
  );
  return { ...form, manpower_total: totals.count, overtime_hours: String(totals.hours) };
}

function formHasDraftContent(payload: DailyReportPayload) {
  return Boolean(
    payload.project_id ||
    payload.work_location.trim() ||
    payload.work_completed.trim() ||
    payload.delay_notes?.trim() ||
    payload.next_day_plan.trim() ||
    payload.safety_notes?.trim() ||
    payload.report_date !== businessDate() ||
    payload.progress_percentage !== emptyPayload.progress_percentage ||
    payload.safety_incidents !== emptyPayload.safety_incidents ||
    payload.supervisor_update_ids.length > 0 ||
    payload.photo_refs.length > 0 ||
    payload.attachment_refs.length > 0 ||
    payload.equipment_entries.length > 0 ||
    payload.material_consumption.length > 0 ||
    payload.manpower_entries.some(
      (entry) =>
        entry.trade.trim() || Number(entry.count || 0) > 0 || Number(entry.overtime_hours || 0) > 0
    ) ||
    Object.entries(payload.extra_fields ?? {}).some(([key, value]) => {
      if (key === 'day_type') return value !== emptyPayload.extra_fields?.day_type;
      return typeof value === 'string' ? value.trim() : Boolean(value);
    })
  );
}

const t = (str: string) => str;

export function DailyReportPage() {
  const { user } = useAuth();
  const currentUserId = user?.id;
  const browserScope = getBrowserSession()?.scope;
  const scope = browserScope?.ownerUserId === currentUserId ? browserScope : undefined;
  const [searchParams] = useSearchParams();
  const focusedReportId = searchParams.get('reportId');
  const [projects, setProjects] = useState<ProjectRecord[]>([]);
  const [supervisorUpdates, setSupervisorUpdates] = useState<SupervisorUpdateRecord[]>([]);
  const [reports, setReports] = useState<DailyReportRecord[]>([]);
  const [form, setForm] = useState(createEmptyPayload);
  const [photoNames, setPhotoNames] = useState('');
  const [attachmentNames, setAttachmentNames] = useState('');
  const [uploadedFiles, setUploadedFiles] = useState<PhotoRecord[]>([]);
  const [failedUpload, setFailedUpload] = useState<{
    entityId: string;
    items: MediaUploadIntent[];
  } | null>(null);
  const [queuedDraftPhotos, setQueuedDraftPhotos] = useState(0);
  const [uploadPending, setUploadPending] = useState(false);
  const uploadInProgress = useRef(false);
  const [errors, setErrors] = useState<Record<string, string>>({});
  const [notice, setNotice] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [savedReportId, setSavedReportId] = useState<string | null>(null);
  const [isSaving, setIsSaving] = useState(false);
  const [draftStatus, setDraftStatus] = useState<
    LocalReportDraft['syncState'] | 'idle' | 'syncing'
  >('idle');
  const [queuedUploads, setQueuedUploads] = useState(0);
  const [syncConflicts, setSyncConflicts] = useState(0);
  const [draftHydrated, setDraftHydrated] = useState(false);
  const [isOnline, setIsOnline] = useState(() => navigator.onLine);
  const reportRefs = useRef<Record<string, HTMLElement | null>>({});
  const persistedDraftSnapshot = useRef(JSON.stringify(form));
  const serverSavedSnapshot = useRef(JSON.stringify(form));
  const draftKey = useRef<string | null>(null);
  const baseRevision = useRef<number | undefined>(undefined);

  const getDraftKey = useCallback(() => {
    draftKey.current ??= `local-${crypto.randomUUID()}`;
    return draftKey.current;
  }, []);

  const selectedProject = useMemo(
    () => projects.find((project) => project.id === form.project_id),
    [form.project_id, projects]
  );
  const canSubmitReports = user?.permissions?.includes('reports:submit') ?? false;
  const saveLocalDraft = useCallback(
    (payload: DailyReportPayload) =>
      scope
        ? saveReportDraft(
            scope,
            payload,
            getDraftKey(),
            savedReportId
              ? { id: savedReportId, engineerId: scope.ownerUserId, revision: baseRevision.current }
              : undefined
          )
        : Promise.resolve(false),
    [getDraftKey, savedReportId, scope]
  );

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
    if (!scope) return;
    let mounted = true;
    const active = () => mounted && sameScope(getBrowserSession()?.scope, scope);
    void getReportDraft(scope)
      .then((draft) => {
        if (!active()) return;
        if (
          draft?.payload &&
          (!draft.serverReport || draft.serverReport.engineerId === scope.ownerUserId) &&
          formHasDraftContent(draft.payload)
        ) {
          draftKey.current = draft.localDraftId;
          setSavedReportId(draft.serverReport?.id ?? null);
          baseRevision.current = draft.baseServerRevision;
          setForm(draft.payload);
          setPhotoNames(draft.payload.photo_refs.map(({ name }) => name).join('\n'));
          setAttachmentNames(draft.payload.attachment_refs.map(({ name }) => name).join('\n'));
          persistedDraftSnapshot.current = JSON.stringify(draft.payload);
          setDraftStatus(draft.syncState);
        }
        setDraftHydrated(true);
      })
      .catch(() => {
        if (active())
          setError('Unable to open offline drafts. Close older portal tabs and try again.');
      });
    void queuedPhotoCount(scope)
      .then((count) => {
        if (active()) setQueuedUploads(count);
      })
      .catch(() => {});
    return () => {
      mounted = false;
    };
  }, [scope]);

  useEffect(() => {
    if (!draftHydrated || !scope) return;
    const snapshot = JSON.stringify(form);
    if (snapshot === persistedDraftSnapshot.current || snapshot === serverSavedSnapshot.current) {
      return;
    }
    const active = () => sameScope(getBrowserSession()?.scope, scope);
    const onError = () => {
      if (active()) setError('Unable to save the local draft.');
    };
    if (!formHasDraftContent(form)) {
      const localDraftId = draftKey.current;
      if (!localDraftId) return;
      const timer = window.setTimeout(() => {
        void clearReportDraft(scope, localDraftId)
          .then(() => {
            if (!active()) return;
            persistedDraftSnapshot.current = snapshot;
            setDraftStatus('idle');
          })
          .catch(onError);
      }, 800);
      return () => window.clearTimeout(timer);
    }
    const continueSync = isReportSyncActive(scope);
    const save = () => {
      void saveLocalDraft(form)
        .then((saved) => {
          if (!saved || !active()) return;
          persistedDraftSnapshot.current = snapshot;
          setDraftStatus((current) => (current === 'conflict' ? current : 'local'));
          if (continueSync && navigator.onLine) void flushPhotoQueue(true).catch(() => {});
        })
        .catch(onError);
    };
    const timer = window.setTimeout(save, 800);
    const interval = window.setInterval(save, 30_000);
    return () => {
      window.clearTimeout(timer);
      window.clearInterval(interval);
    };
  }, [draftHydrated, form, saveLocalDraft, scope]);

  useEffect(() => {
    if (!scope) return;
    let mounted = true;
    const refreshQueuedCount = () => {
      void Promise.all([
        queuedPhotoCount(scope),
        draftKey.current ? queuedDraftPhotoCount(scope, draftKey.current) : 0
      ])
        .then(([count, photos]) => {
          if (mounted && sameScope(getBrowserSession()?.scope, scope)) {
            setQueuedUploads(count);
            setQueuedDraftPhotos(photos);
          }
        })
        .catch(() => {});
    };
    const refreshDraftState = () => {
      const localDraftId = draftKey.current;
      if (!localDraftId) return;
      void getReportDraft(scope, localDraftId)
        .then((draft) => {
          if (
            !draft ||
            !mounted ||
            !sameScope(getBrowserSession()?.scope, scope) ||
            draftKey.current !== localDraftId
          )
            return;
          setDraftStatus(draft.syncState);
          if (draft.serverReport) {
            setSavedReportId(draft.serverReport.id);
            baseRevision.current = draft.baseServerRevision;
            if (
              draft.syncState === 'saved' &&
              draft.lastSyncedLocalRevision >= draft.localRevision
            ) {
              serverSavedSnapshot.current = JSON.stringify(draft.payload);
            }
          }
        })
        .catch(() => {});
    };
    const syncQueued = () => {
      setIsOnline(true);
      void flushPhotoQueue()
        .then(() => {
          refreshQueuedCount();
          refreshDraftState();
        })
        .catch(() => {});
    };
    const handleSync = (event: Event) => {
      const { scope: source, conflicts } = (
        event as CustomEvent<{
          scope: OfflineScope;
          conflicts: number;
        }>
      ).detail;
      if (!sameScope(source, scope)) return;
      refreshQueuedCount();
      refreshDraftState();
      setSyncConflicts(conflicts);
    };
    const handleOffline = () => setIsOnline(false);
    window.addEventListener('online', syncQueued);
    window.addEventListener('offline', handleOffline);
    window.addEventListener('photo-queue-sync-complete', handleSync);
    if (navigator.onLine) syncQueued();
    return () => {
      mounted = false;
      window.removeEventListener('online', syncQueued);
      window.removeEventListener('offline', handleOffline);
      window.removeEventListener('photo-queue-sync-complete', handleSync);
    };
  }, [scope]);

  useEffect(() => {
    if (!form.project_id) {
      setSupervisorUpdates([]);
      return;
    }
    let active = true;
    void Promise.all([
      listSupervisorUpdates({ project_id: form.project_id, status: 'submitted' }),
      savedReportId ? listReportSupervisorUpdates(savedReportId) : Promise.resolve([]),
      loadReports(form.project_id)
    ])
      .then(([submitted, linked]) => {
        if (!active) return;
        const updates = new Map(submitted.items.map((update) => [update.id, update]));
        for (const update of linked) {
          if (update.project_id === form.project_id) updates.set(update.id, update);
        }
        setSupervisorUpdates([...updates.values()]);
      })
      .catch(() => {
        if (active) setError('Unable to load supervisor updates.');
      });
    return () => {
      active = false;
    };
  }, [form.project_id, loadReports, savedReportId]);

  useEffect(() => {
    if (!focusedReportId) return;
    const element = reportRefs.current[focusedReportId];
    element?.scrollIntoView({ behavior: 'smooth', block: 'center' });
  }, [focusedReportId, reports]);

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

  async function resumeReport(report: DailyReportRecord) {
    const hasLocalEdits =
      formHasDraftContent({ ...form, project_id: '' }) &&
      JSON.stringify(form) !== serverSavedSnapshot.current;
    if (
      hasLocalEdits &&
      !window.confirm('Open the server draft? Other local drafts stay on this device.')
    )
      return;

    const payload = reportForm(report);
    const snapshot = JSON.stringify(payload);
    setError(null);
    setErrors({});
    setIsSaving(true);
    setSavedReportId(report.id);
    draftKey.current = draftKey.current && savedReportId === report.id ? draftKey.current : null;
    baseRevision.current = report.revision;
    setForm(payload);
    setPhotoNames(payload.photo_refs.map(({ name }) => name).join('\n'));
    setAttachmentNames(payload.attachment_refs.map(({ name }) => name).join('\n'));
    setUploadedFiles([]);
    setFailedUpload(null);
    setQueuedDraftPhotos(0);
    serverSavedSnapshot.current = snapshot;
    persistedDraftSnapshot.current = snapshot;
    setDraftStatus('idle');
    setNotice(
      report.rejection_comments
        ? `Review feedback: ${report.rejection_comments}`
        : 'Report reopened.'
    );
    try {
      if (!scope) return;
      await saveReportDraft(
        scope,
        payload,
        getDraftKey(),
        {
          id: report.id,
          engineerId: report.engineer_id,
          revision: report.revision
        },
        true
      );
      const files = await listPhotos({ entityType: 'daily_report', entityId: report.id });
      setUploadedFiles(files.items);
    } catch (loadError) {
      setError(formatApiError(loadError, 'Unable to load the saved report or its attachments.'));
    } finally {
      setIsSaving(false);
    }
  }

  async function saveDraft() {
    if (!scope || !validate()) return null;
    setIsSaving(true);
    setError(null);
    setNotice(null);
    const localDraftId = getDraftKey();
    try {
      const payload = buildPayload();
      const saved = await saveReportDraft(
        scope,
        payload,
        localDraftId,
        savedReportId
          ? { id: savedReportId, engineerId: scope.ownerUserId, revision: baseRevision.current }
          : undefined
      );
      if (!saved) return null;
      if (!navigator.onLine) {
        setDraftStatus('local');
        setNotice('Daily report draft saved on this device.');
        return null;
      }
      setDraftStatus('syncing');
      await flushPhotoQueue(true);
      const result = await getReportDraft(scope, localDraftId);
      if (!result || !sameScope(getBrowserSession()?.scope, scope)) return null;
      setDraftStatus(result.syncState);
      if (result.syncState !== 'saved' || !result.serverReport) {
        setError(
          result.syncState === 'conflict'
            ? 'The server report changed. Your local draft is still available.'
            : 'The draft is saved locally. Resolve the issue or retry synchronization.'
        );
        return null;
      }
      const reportId = result.serverReport.id;
      setSavedReportId(reportId);
      baseRevision.current = result.baseServerRevision;
      serverSavedSnapshot.current = JSON.stringify(payload);
      persistedDraftSnapshot.current = JSON.stringify(payload);
      setNotice('Daily report draft saved.');
      await loadReports(payload.project_id);
      return reportId;
    } catch (saveError) {
      setError(formatApiError(saveError, 'Unable to save the daily report.'));
      return null;
    } finally {
      setIsSaving(false);
    }
  }

  async function reloadServerDraft() {
    if (!scope || !savedReportId) return;
    try {
      const latest = await getDailyReport(savedReportId, scope);
      if (latest.status !== 'draft') {
        setError(
          'The server report is no longer editable. You can keep this draft or copy the text into a new one.'
        );
        return;
      }
      await resumeReport(latest);
    } catch (loadError) {
      setError(formatApiError(loadError, 'Unable to reload the server report.'));
    }
  }

  function copyDraftText() {
    if (
      !window.confirm(
        'Copy the report text into a new draft? Linked evidence will stay with the existing report.'
      )
    )
      return;
    draftKey.current = null;
    baseRevision.current = undefined;
    setSavedReportId(null);
    setUploadedFiles([]);
    setPhotoNames('');
    setAttachmentNames('');
    setError(null);
    setDraftStatus('local');
    setForm({
      ...createEmptyPayload(),
      project_id: form.project_id,
      work_location: form.work_location,
      work_completed: form.work_completed,
      next_day_plan: form.next_day_plan,
      safety_notes: form.safety_notes,
      delay_notes: form.delay_notes
    });
  }

  async function submitReport(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (!scope || !validate()) return;
    if (!navigator.onLine) {
      setError('Reconnect to submit this report. Your draft can be saved locally.');
      return;
    }
    const unchanged = JSON.stringify(buildPayload()) === serverSavedSnapshot.current;
    const reportId = savedReportId && unchanged ? savedReportId : await saveDraft();
    if (!reportId) return;
    setIsSaving(true);
    setError(null);
    setNotice(null);
    try {
      const report = await submitDailyReport(reportId, scope);
      const resetForm = createEmptyPayload();
      setForm(resetForm);
      setPhotoNames('');
      setAttachmentNames('');
      setUploadedFiles([]);
      setFailedUpload(null);
      setQueuedDraftPhotos(0);
      setSavedReportId(null);
      baseRevision.current = undefined;
      if (draftKey.current) await clearReportDraft(scope, draftKey.current);
      draftKey.current = null;
      serverSavedSnapshot.current = JSON.stringify(resetForm);
      persistedDraftSnapshot.current = JSON.stringify(resetForm);
      setDraftStatus('idle');
      setNotice(`Daily report ${report.report_number} submitted.`);
      await loadReports(report.project_id);
    } catch (submitError) {
      setError(formatApiError(submitError, 'Unable to submit the daily report.'));
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

  async function recordUploads(
    entityId: string,
    items: MediaUploadIntent[],
    selectionErrors: string[]
  ) {
    if (!scope || !sameScope(getBrowserSession()?.scope, scope)) return;
    const previousRevision = baseRevision.current;
    const result = await uploadMediaFiles('daily_report', entityId, items, scope, previousRevision);
    if (!sameScope(getBrowserSession()?.scope, scope)) return;
    if (
      previousRevision !== undefined &&
      result.reportRevision !== undefined &&
      result.reportRevision > previousRevision
    ) {
      baseRevision.current = result.reportRevision;
      if (draftKey.current) {
        await acknowledgeReportEvidenceRevision(
          scope,
          draftKey.current,
          entityId,
          previousRevision,
          result.reportRevision
        );
      }
    }
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

  async function uploadFiles(files: FileList | null, kind: 'photo' | 'attachment') {
    if (!scope || !files?.length || uploadInProgress.current) return;
    uploadInProgress.current = true;
    setUploadPending(true);
    setError(null);
    setNotice(null);
    const selection = Array.from(files);
    try {
      const serverPhotos = uploadedFiles.filter((file) => file.kind === 'photo').length;
      const localDraftId = getDraftKey();
      const queued = await queuedDraftPhotoCount(scope, localDraftId);
      const { items, errors } = await prepareMediaFiles(
        selection,
        kind,
        MAX_REPORT_PHOTOS - serverPhotos - queued
      );
      if (errors.length) setError(errors.join(' '));
      if (!items.length) return;
      if (!navigator.onLine) {
        if (!validate()) return;
        const payload = buildPayload();
        const entityId = savedReportId ?? localDraftId;
        if (!(await saveLocalDraft(payload))) return;
        let queuedFilesCount = 0;
        for (const entry of items) {
          const saved = await queueFiles(scope, {
            entityType: 'daily_report',
            entityId,
            localDraftId,
            draftPayload: savedReportId ? undefined : payload,
            kind: entry.kind,
            files: [entry.file]
          });
          if (saved) queuedFilesCount += 1;
        }
        if (!queuedFilesCount || !sameScope(getBrowserSession()?.scope, scope)) return;
        await registerBackgroundSync();
        setQueuedUploads(await queuedPhotoCount(scope));
        setQueuedDraftPhotos(await queuedDraftPhotoCount(scope, localDraftId));
        setDraftStatus('local');
        setNotice(
          `${queuedFilesCount} file${queuedFilesCount === 1 ? '' : 's'} queued for upload.`
        );
        return;
      }
      const reportId = savedReportId ?? (await saveDraft());
      if (reportId) await recordUploads(reportId, items, errors);
    } catch (failure) {
      setError(formatApiError(failure, 'Unable to process the selected files.'));
    } finally {
      uploadInProgress.current = false;
      setUploadPending(false);
    }
  }

  async function retryMediaUploads() {
    if (!failedUpload || uploadInProgress.current) return;
    uploadInProgress.current = true;
    setUploadPending(true);
    setError(null);
    setNotice(null);
    try {
      await recordUploads(failedUpload.entityId, failedUpload.items, []);
    } finally {
      uploadInProgress.current = false;
      setUploadPending(false);
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
                className={`rounded-lg border bg-theme-card p-4 shadow-xs ${
                  report.id === focusedReportId
                    ? 'border-brand-600 ring-2 ring-brand-600/20'
                    : 'border-theme-border'
                }`}
                key={report.id}
                ref={(element) => {
                  reportRefs.current[report.id] = element;
                }}
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
                    <h4 className="text-sm font-semibold text-theme-text-primary">Next-day plan</h4>
                    <p className="mt-1 text-sm text-theme-text-secondary">{report.next_day_plan}</p>
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
        {draftStatus === 'conflict' || syncConflicts > 0 ? (
          <div
            className="alert-warning rounded-md border border-[var(--status-warning-border)] px-3 py-2 text-sm"
            role="alert"
          >
            The server report changed. Your local draft and queued uploads are still saved on this
            device.
            <div className="mt-2 flex flex-wrap gap-2">
              {savedReportId ? (
                <button
                  className="button-secondary"
                  type="button"
                  onClick={() => void reloadServerDraft()}
                >
                  Reload server draft
                </button>
              ) : null}
              <button className="button-secondary" type="button" onClick={copyDraftText}>
                Copy text into new draft
              </button>
            </div>
          </div>
        ) : null}
        {draftStatus === 'syncing' ? <p role="status">Syncing draft…</p> : null}
        {draftStatus === 'saved' ? <p role="status">Draft saved to server.</p> : null}
        {isOnline &&
        (draftStatus === 'local' || draftStatus === 'retry' || draftStatus === 'blocked') ? (
          <div role="status" className="flex flex-wrap items-center gap-2">
            <p>
              {draftStatus === 'blocked'
                ? 'Draft sync needs attention.'
                : 'Draft saved on this device.'}
            </p>
            <button
              className="button-secondary"
              type="button"
              disabled={isSaving}
              onClick={() => void saveDraft()}
            >
              Retry sync
            </button>
          </div>
        ) : null}
        {!isOnline && (draftStatus === 'local' || queuedUploads > 0) ? (
          <div className="alert-warning rounded-md border border-[var(--status-warning-border)] px-3 py-2 text-sm">
            Local draft active
            {queuedUploads > 0
              ? `, ${queuedUploads} upload${queuedUploads > 1 ? 's' : ''} queued`
              : ''}
            . Sync resumes automatically when the connection is available.
          </div>
        ) : null}

        <form className="space-y-4" onSubmit={submitReport}>
          <section className="rounded-lg border border-theme-border bg-theme-card p-4 shadow-xs">
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
                  <option value="weekday">{t('Weekday')}</option>
                  <option value="friday">{t('Friday')}</option>
                  <option value="public_holiday">{t('Public holiday')}</option>
                </select>
              </Field>
              <Field label="Weather" error={errors.weather_condition}>
                <input
                  className="form-field"
                  list="weather-options"
                  onChange={(event) => updateExtraField('weather_condition', event.target.value)}
                  placeholder={t('Sunny, cloudy, rainy, windy')}
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

          <section className="rounded-lg border border-theme-border bg-theme-card p-4 shadow-xs">
            <SectionHeader title="Supervisor Updates" />
            {supervisorUpdates.length === 0 ? (
              <p className="text-sm text-theme-text-muted">
                {t('No submitted supervisor updates found.')}
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
                      disabled={update.status === 'verified'}
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
                      {update.status === 'verified' && (
                        <span className="block text-theme-text-muted">
                          Verified evidence retained on this report
                        </span>
                      )}
                    </span>
                  </label>
                ))}
              </div>
            )}
          </section>

          <section className="rounded-lg border border-theme-border bg-theme-card p-4 shadow-xs">
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

          <section className="rounded-lg border border-theme-border bg-theme-card p-4 shadow-xs">
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

          <section className="rounded-lg border border-theme-border bg-theme-card p-4 shadow-xs">
            <SectionHeader title="Photos And Attachments" />
            <p className="mb-3 text-sm text-theme-text-muted">
              {uploadedFiles.filter((file) => file.kind === 'photo').length} of 5 photos saved
              {queuedDraftPhotos > 0 ? ` · ${queuedDraftPhotos} photos queued for this draft` : ''}.
              JPEG, PNG and HEIC photos or PDF, JPEG and PNG attachments, up to 10 MiB per file.
            </p>
            <div className="grid gap-4 md:grid-cols-2">
              <Field label="Upload photos">
                <input
                  accept={REPORT_PHOTO_ACCEPT}
                  capture="environment"
                  className="form-field"
                  disabled={isSaving || uploadPending}
                  multiple
                  onChange={(event) => {
                    void uploadFiles(event.target.files, 'photo');
                    event.target.value = '';
                  }}
                  type="file"
                />
              </Field>
              <Field label="Upload attachments">
                <input
                  accept={PDF_IMAGE_ACCEPT}
                  className="form-field"
                  disabled={isSaving || uploadPending}
                  multiple
                  onChange={(event) => {
                    void uploadFiles(event.target.files, 'attachment');
                    event.target.value = '';
                  }}
                  type="file"
                />
              </Field>
              <Field label="Photo file names">
                <textarea
                  className="form-field min-h-20"
                  onChange={(event) => {
                    const names = event.target.value;
                    setPhotoNames(names);
                    setForm((current) => ({ ...current, photo_refs: parseRefs(names, 'photo') }));
                  }}
                  placeholder="zone-a.jpg"
                  value={photoNames}
                />
              </Field>
              <Field label="Attachment file names">
                <textarea
                  className="form-field min-h-20"
                  onChange={(event) => {
                    const names = event.target.value;
                    setAttachmentNames(names);
                    setForm((current) => ({
                      ...current,
                      attachment_refs: parseRefs(names, 'file')
                    }));
                  }}
                  placeholder="inspection.pdf"
                  value={attachmentNames}
                />
              </Field>
            </div>
            {failedUpload ? (
              <button
                className="form-field mt-3"
                disabled={uploadPending || !isOnline}
                onClick={() => void retryMediaUploads()}
                type="button"
              >
                Retry {failedUpload.items.length} failed file(s)
              </button>
            ) : null}
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
              disabled={isSaving || uploadPending}
              onClick={() => void saveDraft()}
              type="button"
            >
              <Save className="h-4 w-4" />
              Save draft
            </button>
            <button
              className="inline-flex min-h-11 items-center justify-center gap-2 rounded-md bg-brand-600 px-4 py-2 text-sm font-semibold text-white hover:bg-brand-700 disabled:opacity-60"
              disabled={isSaving || uploadPending}
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
                className={`rounded-lg border bg-theme-card p-4 shadow-xs ${
                  report.id === focusedReportId
                    ? 'border-brand-600 ring-2 ring-brand-600/20'
                    : 'border-theme-border'
                }`}
                key={report.id}
                ref={(element) => {
                  reportRefs.current[report.id] = element;
                }}
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
                {canSubmitReports &&
                report.engineer_id === currentUserId &&
                (report.status === 'draft' || report.status === 'rejected') ? (
                  <button
                    className="mt-3 rounded-md border border-theme-border px-3 py-2 text-sm font-semibold text-theme-text-secondary hover:bg-theme-main disabled:opacity-50"
                    disabled={
                      !draftHydrated || isSaving || uploadPending || savedReportId === report.id
                    }
                    onClick={() => void resumeReport(report)}
                    type="button"
                  >
                    Resume report
                  </button>
                ) : null}
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
    setForm(key === 'manpower_entries' ? withManpowerTotals(nextForm) : nextForm);
  }

  function removeRow<
    K extends keyof Pick<
      DailyReportPayload,
      'manpower_entries' | 'equipment_entries' | 'material_consumption'
    >
  >(key: K, index: number) {
    const rows = form[key].filter((_, rowIndex) => rowIndex !== index);
    const nextForm = { ...form, [key]: rows };
    setForm(key === 'manpower_entries' ? withManpowerTotals(nextForm) : nextForm);
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
    <section className="rounded-lg border border-theme-border bg-theme-card p-4 shadow-xs">
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
