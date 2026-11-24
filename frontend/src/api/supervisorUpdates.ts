import { apiClient, sessionRequestConfig } from './client';
import type { OfflineScope } from './offlineDb';
import type { components } from './schema';

export type AttachmentRef = components['schemas']['AttachmentRef'];

export type SupervisorUpdatePayload = components['schemas']['SupervisorUpdateCreateRequest-Input'];

export type SupervisorUpdateRecord = components['schemas']['SupervisorUpdateResponse'];

export type SupervisorUpdateListResponse = components['schemas']['SupervisorUpdateListResponse'];

export async function listSupervisorUpdates(params: {
  project_id?: string;
  status?: string;
  limit?: number;
  offset?: number;
  review_only?: boolean;
  update_id?: string;
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

export async function correctVerifiedSupervisorUpdate(
  record: SupervisorUpdateRecord,
  reason: string,
  scope?: OfflineScope
): Promise<SupervisorUpdateRecord> {
  const { data } = await apiClient.post<SupervisorUpdateRecord>(
    `/supervisor-updates/${record.id}/correction`,
    { ...record, reason, expected_revision: record.revision },
    sessionRequestConfig(scope)
  );
  return data;
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
  expectedRevision: number,
  scope?: OfflineScope
): Promise<SupervisorUpdateRecord> {
  const response = await apiClient.post<SupervisorUpdateRecord>(
    `/supervisor-updates/${updateId}/submit`,
    { expected_revision: expectedRevision },
    sessionRequestConfig(scope)
  );
  return response.data;
}

export async function reviewSupervisorUpdate(
  updateId: string,
  decision: components['schemas']['SupervisorUpdateDecisionRequest']
) {
  const { data } = await apiClient.post<SupervisorUpdateRecord>(
    `/supervisor-updates/${updateId}/review`, decision
  );
  return data;
}

export async function listSupervisorSubmissionHistory(updateId: string) {
  const { data } = await apiClient.get<components['schemas']['SupervisorUpdateSubmissionResponse'][]>(
    `/supervisor-updates/${updateId}/submissions`
  );
  return data;
}
