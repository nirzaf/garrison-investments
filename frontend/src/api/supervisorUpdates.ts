import { apiClient } from './client';
import type { components } from './schema';

export type AttachmentRef = components['schemas']['AttachmentRef'];

export type SupervisorUpdatePayload = components['schemas']['SupervisorUpdateCreateRequest'];

export type SupervisorUpdateRecord = components['schemas']['SupervisorUpdateResponse'];

export type SupervisorUpdateListResponse = components['schemas']['SupervisorUpdateListResponse'];

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

export async function updateSupervisorUpdate(
  updateId: string,
  payload: SupervisorUpdatePayload
): Promise<SupervisorUpdateRecord> {
  const response = await apiClient.put<SupervisorUpdateRecord>(
    `/supervisor-updates/${updateId}`,
    payload
  );
  return response.data;
}

export async function submitSupervisorUpdate(updateId: string): Promise<SupervisorUpdateRecord> {
  const response = await apiClient.post<SupervisorUpdateRecord>(
    `/supervisor-updates/${updateId}/submit`
  );
  return response.data;
}
