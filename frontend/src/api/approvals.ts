import { apiClient } from './client';

export type ApprovalRecord = {
  id: string;
  request_type: string;
  request_id: string;
  project_id: string | null;
  submitter_id: string | null;
  approver_id: string | null;
  delegated_to_id: string | null;
  escalation_user_id: string | null;
  status: string;
  step_order: number;
  amount: string | null;
  currency: string | null;
  title: string;
  submitter_comments: string | null;
  decision_comments: string | null;
  delegation_reason: string | null;
  override_reason: string | null;
  submitted_at: string;
  due_at: string;
  reminded_at: string | null;
  escalated_at: string | null;
  decided_at: string | null;
};

export type ApprovalListResponse = {
  items: ApprovalRecord[];
  total: number;
};

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
