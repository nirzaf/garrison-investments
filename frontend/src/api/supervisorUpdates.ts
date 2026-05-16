import { apiClient } from './client';

export type AttachmentRef = {
  name: string;
  kind: string;
};

export type SupervisorUpdatePayload = {
  project_id: string;
  update_date: string;
  day_type: string;
  work_location: string;
  attendance_count: number;
  overtime_hours: string;
  progress_notes: string;
  delay_notes?: string | null;
  required_notes: string;
  attachment_refs: AttachmentRef[];
};

export type SupervisorUpdateRecord = SupervisorUpdatePayload & {
  id: string;
  supervisor_id: string;
  status: string;
  submitted_at: string | null;
  verified_by: string | null;
  verified_at: string | null;
  verification_notes: string | null;
};

export type SupervisorUpdateListResponse = {
  items: SupervisorUpdateRecord[];
  total: number;
};

export async function listSupervisorUpdates(params: {
  project_id?: string;
  status?: string;
}): Promise<SupervisorUpdateListResponse> {
  const response = await apiClient.get<SupervisorUpdateListResponse>('/supervisor-updates', {
    params
  });
  return response.data;
}

export async function createSupervisorUpdate(
  payload: SupervisorUpdatePayload
): Promise<SupervisorUpdateRecord> {
  const response = await apiClient.post<SupervisorUpdateRecord>('/supervisor-updates', payload);
  return response.data;
}

export async function submitSupervisorUpdate(updateId: string): Promise<SupervisorUpdateRecord> {
  const response = await apiClient.post<SupervisorUpdateRecord>(
    `/supervisor-updates/${updateId}/submit`
  );
  return response.data;
}
