import { apiClient } from './client';

export type AnalyticsSummary = {
  projects: Array<{
    project_id: string;
    project_name: string;
    progress_percentage: string;
    report_count: number;
    invoice_total: string;
    paid_total: string;
  }>;
  material_usage: Array<{
    item_id: string;
    item_name: string;
    issued_quantity: string;
    consumed_quantity: string;
  }>;
};

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
    responseType: 'blob'
  });
  const url = URL.createObjectURL(data);
  const link = document.createElement('a');
  link.href = url;
  link.download = path === 'management-summary' ? `${path}.pdf` : `${path}.xlsx`;
  link.click();
  URL.revokeObjectURL(url);
}
