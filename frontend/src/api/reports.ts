import { apiClient } from './client';
import type { components } from './schema';

export type ReportFileRef = components['schemas']['ReportFileRef'];

export type ReportManpower = components['schemas']['ReportManpowerInput'];

export type ReportEquipment = components['schemas']['ReportEquipmentInput'];

export type ReportMaterialConsumption = components['schemas']['ReportMaterialConsumptionInput'];

type DailyReportCreateSchema = components['schemas']['DailyReportCreateRequest'];

export type DailyReportPayload = DailyReportCreateSchema & {
  supervisor_update_ids: string[];
  photo_refs: ReportFileRef[];
  attachment_refs: ReportFileRef[];
  manpower_entries: ReportManpower[];
  equipment_entries: ReportEquipment[];
  material_consumption: ReportMaterialConsumption[];
  extra_fields: Record<string, unknown>;
};

export type DailyReportRecord = components['schemas']['DailyReportResponse'];

export type DailyReportListResponse = components['schemas']['DailyReportListResponse'];

export async function listDailyReports(params: {
  project_id?: string;
  status?: string;
}): Promise<DailyReportListResponse> {
  const response = await apiClient.get<DailyReportListResponse>('/reports', { params });
  return response.data;
}

export async function createDailyReport(
  payload: DailyReportPayload,
  idempotencyKey?: string
): Promise<DailyReportRecord> {
  const response = await apiClient.post<DailyReportRecord>('/reports', payload, {
    headers: idempotencyKey ? { 'Idempotency-Key': idempotencyKey } : undefined
  });
  return response.data;
}

export async function updateDailyReport(
  reportId: string,
  payload: DailyReportPayload
): Promise<DailyReportRecord> {
  const response = await apiClient.put<DailyReportRecord>(`/reports/${reportId}`, payload);
  return response.data;
}

export async function submitDailyReport(reportId: string): Promise<DailyReportRecord> {
  const response = await apiClient.post<DailyReportRecord>(`/reports/${reportId}/submit`);
  return response.data;
}

export async function approveDailyReport(
  reportId: string,
  comments?: string,
  targetCovered = false
): Promise<DailyReportRecord> {
  const response = await apiClient.post<DailyReportRecord>(`/reports/${reportId}/approve`, {
    comments,
    target_covered: targetCovered
  });
  return response.data;
}

export async function rejectDailyReport(
  reportId: string,
  comments: string
): Promise<DailyReportRecord> {
  const response = await apiClient.post<DailyReportRecord>(`/reports/${reportId}/reject`, {
    comments
  });
  return response.data;
}

export async function overrideDailyReport(
  reportId: string,
  payload: { decision: 'approved' | 'rejected'; reason: string; targetCovered?: boolean }
): Promise<DailyReportRecord> {
  const response = await apiClient.post<DailyReportRecord>(`/reports/${reportId}/override`, {
    decision: payload.decision,
    reason: payload.reason,
    target_covered: payload.targetCovered ?? false
  });
  return response.data;
}

export async function downloadReportPdf(reportId: string): Promise<Blob> {
  const response = await apiClient.get<Blob>(`/reports/${reportId}/pdf`, {
    responseType: 'blob'
  });
  return response.data;
}
