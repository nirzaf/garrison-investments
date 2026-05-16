import { apiClient } from './client';

export type AuditLogRecord = {
  id: string;
  user_id: string | null;
  action: string;
  entity_type: string | null;
  entity_id: string | null;
  ip_address: string | null;
  user_agent: string | null;
  comments: string | null;
  old_values: Record<string, unknown> | null;
  new_values: Record<string, unknown> | null;
  created_at: string;
};

export type AuditLogListResponse = {
  items: AuditLogRecord[];
  total: number;
};

export type AuditLogFilters = {
  action?: string;
  entity_type?: string;
  user_id?: string;
  search?: string;
  limit?: number;
  offset?: number;
};

export async function getAuditLogs(filters: AuditLogFilters = {}) {
  const { data } = await apiClient.get<AuditLogListResponse>('/audit-logs', {
    params: filters
  });
  return data;
}
