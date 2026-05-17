import { apiClient } from './client';
import type { components } from './schema';

export type ApprovalRecord = components['schemas']['ApprovalResponse'];

export type ApprovalListResponse = components['schemas']['ApprovalListResponse'];

export async function listApprovals(
  params: {
    box?: 'inbox' | 'outbox';
    status?: string;
    limit?: number;
    offset?: number;
  } = {}
) {
  const { data } = await apiClient.get<ApprovalListResponse>('/approvals', { params });
  return data;
}

export async function approveGenericApproval(id: string, comments?: string) {
  const { data } = await apiClient.post<ApprovalRecord>(`/approvals/${id}/approve`, {
    comments
  });
  return data;
}

export async function rejectGenericApproval(id: string, comments: string) {
  const { data } = await apiClient.post<ApprovalRecord>(`/approvals/${id}/reject`, {
    comments
  });
  return data;
}

export async function delegateGenericApproval(
  id: string,
  payload: { delegated_to_id: string; reason: string }
) {
  const { data } = await apiClient.post<ApprovalRecord>(`/approvals/${id}/delegate`, payload);
  return data;
}

export async function overrideGenericApproval(
  id: string,
  payload: { decision: 'approved' | 'rejected'; reason: string }
) {
  const { data } = await apiClient.post<ApprovalRecord>(`/approvals/${id}/override`, payload);
  return data;
}
