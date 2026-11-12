// Shared by the foreground application and the module service worker.
export function reportPayload(payload) {
  return {
    ...payload,
    manpower_entries: payload.manpower_entries.filter((entry) => entry.trade.trim()),
    equipment_entries: payload.equipment_entries.filter((entry) => entry.equipment_name.trim()),
    material_consumption: payload.material_consumption.filter((entry) => entry.material_name.trim())
  };
}

export function reportDraftErrors(payload) {
  const errors = {};
  if (!payload.project_id) errors.project_id = 'Select a project.';
  if (!payload.report_date) errors.report_date = 'Select a date.';
  if (!payload.work_location.trim()) errors.work_location = 'Enter the work location.';
  if (!payload.work_completed.trim()) errors.work_completed = 'Enter work completed.';
  if (!payload.next_day_plan.trim()) errors.next_day_plan = 'Enter the next-day plan.';
  const required = {
    weather_condition: 'Select or enter the weather condition.',
    site_visitors: 'Enter site visitors or write none.',
    subcontractors: 'Enter subcontractors or write none.',
    wir_number: 'Enter the WIR number or write not required.'
  };
  for (const [field, message] of Object.entries(required)) {
    const value = payload.extra_fields?.[field];
    if (typeof value !== 'string' || !value.trim()) errors[field] = message;
  }
  const progress = Number(payload.progress_percentage);
  if (!Number.isFinite(progress) || progress < 0 || progress > 100) {
    errors.progress_percentage = 'Progress must be between 0 and 100.';
  }
  if (payload.manpower_entries.some((entry) => !entry.trade.trim())) {
    errors.manpower_entries = 'Every manpower row needs a trade.';
  }
  return errors;
}

export async function persistOwnedDraft(draft, adapter) {
  const {
    localRevision,
    lastSyncedLocalRevision,
    baseServerRevision,
    serverReport,
    pendingCreate
  } = draft;
  if (lastSyncedLocalRevision >= localRevision && serverReport) return 'saved';
  if (!pendingCreate && Object.keys(reportDraftErrors(draft.payload)).length) return 'local';
  if (serverReport && baseServerRevision == null) return 'conflict';

  try {
    if (serverReport) {
      const report = await adapter.update(
        serverReport.id,
        reportPayload(draft.payload),
        baseServerRevision
      );
      if (report.revision !== baseServerRevision + 1 || report.status !== 'draft')
        return 'conflict';
      await adapter.acknowledge(localRevision, report);
    } else {
      // Retain the exact first attempted payload across retries and local edits.
      const attempt = pendingCreate ?? {
        revision: localRevision,
        payload: reportPayload(draft.payload)
      };
      if (!(await adapter.rememberCreate(attempt))) return 'suspended';
      const report = await adapter.create(attempt.payload, draft.localDraftId);
      if (report.revision !== 1 || report.status !== 'draft') return 'conflict';
      await adapter.acknowledge(attempt.revision, report);
    }
    return 'saved';
  } catch (error) {
    const status = adapter.status(error);
    if (status === 401 || status === 403 || adapter.cancelled(error)) return 'suspended';
    if (status === 404 || status === 409) return 'conflict';
    if (status !== undefined && status < 500 && status !== 408 && status !== 429) return 'blocked';
    return 'retry';
  }
}
