import { apiClient } from './client';

export type ReportFileRef = {
  name: string;
  kind: string;
};

export type ReportManpower = {
  trade: string;
  count: number;
  overtime_hours: string;
};

export type ReportEquipment = {
  equipment_name: string;
  quantity: number;
  hours_used: string;
  remarks?: string | null;
};

export type ReportMaterialConsumption = {
  boq_item_id?: string | null;
  material_name: string;
  unit: string;
  quantity: string;
  remarks?: string | null;
};

export type DailyReportPayload = {
  project_id: string;
  report_date: string;
  work_location: string;
  manpower_total: number;
  overtime_hours: string;
  work_completed: string;
  progress_percentage: string;
  safety_incidents: number;
  safety_notes?: string | null;
  wir_status: string;
  inspection_status: string;
  delay_notes?: string | null;
  next_day_plan: string;
  supervisor_update_ids: string[];
  photo_refs: ReportFileRef[];
  attachment_refs: ReportFileRef[];
  manpower_entries: ReportManpower[];
  equipment_entries: ReportEquipment[];
  material_consumption: ReportMaterialConsumption[];
  extra_fields: Record<string, unknown>;
};

export type DailyReportRecord = DailyReportPayload & {
  id: string;
  engineer_id: string;
  report_number: string | null;
  status: string;
  submitted_at: string | null;
  approved_by: string | null;
  approved_at: string | null;
  rejection_comments: string | null;
  approval_history: Array<{
    id: string;
    actor_id: string | null;
    decision: string;
    previous_status: string;
    comments: string | null;
    decided_at: string;
  }>;
};

export type DailyReportListResponse = {
  items: DailyReportRecord[];
  total: number;
};

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
  comments?: string
): Promise<DailyReportRecord> {
  const response = await apiClient.post<DailyReportRecord>(`/reports/${reportId}/approve`, {
    comments
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

export async function downloadReportPdf(reportId: string): Promise<Blob> {
  const response = await apiClient.get<Blob>(`/reports/${reportId}/pdf`, {
    responseType: 'blob'
  });
  return response.data;
}
