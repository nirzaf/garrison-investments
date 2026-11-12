import { apiClient, sessionRequestConfig } from './client';
import type { OfflineScope } from './offlineDb';
import type { components } from './schema';

export type AttachmentRef = components['schemas']['AttachmentRef'];

export type SupervisorUpdatePayload = components['schemas']['SupervisorUpdateCreateRequest'];

export type SupervisorUpdateRecord = components['schemas']['SupervisorUpdateResponse'];

export type SupervisorUpdateListResponse = components['schemas']['SupervisorUpdateListResponse'];

export async function listSupervisorUpdates(params: {
  project_id?: string;
  status?: string;
  limit?: number;
  offset?: number;
}): Promise<SupervisorUpdateListResponse> {
  const response = await apiClient.get<SupervisorUpdateListResponse>('/supervisor-updates', {
    params
  });
  return response.data;
}

export async function listReportSupervisorUpdates(
  reportId: string
): Promise<SupervisorUpdateRecord[]> {
  const response = await apiClient.get<SupervisorUpdateRecord[]>(
    `/reports/${reportId}/supervisor-updates`
  );
  return response.data;
}

export async function createSupervisorUpdate(
  payload: SupervisorUpdatePayload,
  scope?: OfflineScope
): Promise<SupervisorUpdateRecord> {
  const response = await apiClient.post<SupervisorUpdateRecord>(
    '/supervisor-updates',
    payload,
    sessionRequestConfig(scope)
  );
  return response.data;
}

export async function updateSupervisorUpdate(
  updateId: string,
  payload: SupervisorUpdatePayload,
  scope?: OfflineScope
): Promise<SupervisorUpdateRecord> {
  const response = await apiClient.put<SupervisorUpdateRecord>(
    `/supervisor-updates/${updateId}`,
    payload,
    sessionRequestConfig(scope)
  );
  return response.data;
}

export async function submitSupervisorUpdate(
  updateId: string,
  scope?: OfflineScope
): Promise<SupervisorUpdateRecord> {
  const response = await apiClient.post<SupervisorUpdateRecord>(
    `/supervisor-updates/${updateId}/submit`,
    undefined,
    sessionRequestConfig(scope)
  );
  return response.data;
}
