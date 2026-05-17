import { apiClient } from './client';
import type { components } from './schema';

export type AuditLogRecord = components['schemas']['AuditLogResponse'];

export type AuditLogListResponse = components['schemas']['AuditLogListResponse'];

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
