import { apiClient, EXPORT_TIMEOUT_MS } from './client';
import type { components } from './schema';

export type AnalyticsSummary = components['schemas']['AnalyticsSummaryResponse'];

export type AnalyticsFilters = {
  project_id?: string;
  date_from?: string;
  date_to?: string;
  location?: string;
  department?: string;
};

export async function getAnalyticsSummary(filters: AnalyticsFilters = {}) {
  const { data } = await apiClient.get<AnalyticsSummary>('/analytics/summary', {
    params: filters
  });
  return data;
}

export async function downloadExport(
  path: 'project-progress' | 'material-usage' | 'management-summary',
  filters: AnalyticsFilters = {}
) {
  const { data } = await apiClient.get<Blob>(`/export/${path}`, {
    params: filters,
    responseType: 'blob',
    timeout: EXPORT_TIMEOUT_MS
  });
  const url = URL.createObjectURL(data);
  const link = document.createElement('a');
  link.href = url;
  link.download = path === 'management-summary' ? `${path}.pdf` : `${path}.xlsx`;
  link.click();
  URL.revokeObjectURL(url);
}
