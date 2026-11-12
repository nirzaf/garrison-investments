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

export type AnalyticsExport = 'project-progress' | 'material-usage' | 'management-summary';

export async function getAnalyticsSummary(filters: AnalyticsFilters = {}) {
  const { data } = await apiClient.get<AnalyticsSummary>('/analytics/summary', {
    params: filters
  });
  return data;
}

export async function downloadExport(path: AnalyticsExport, filters: AnalyticsFilters = {}) {
  const params = { ...filters };
  if (path === 'material-usage') delete params.location;
  const { data } = await apiClient.get<Blob>(`/export/${path}`, {
    params,
    responseType: 'blob',
    timeout: EXPORT_TIMEOUT_MS
  });
  const signature = await data.slice(0, 5).text();
  const pdf = path === 'management-summary';
  if (pdf ? !signature.startsWith('%PDF-') : !signature.startsWith('PK\u0003\u0004')) {
    throw new Error('The server returned an invalid export file.');
  }
  const url = URL.createObjectURL(data);
  const link = document.createElement('a');
  link.href = url;
  link.download = `${path}.${pdf ? 'pdf' : 'xlsx'}`;
  try {
    link.click();
  } finally {
    window.setTimeout(() => URL.revokeObjectURL(url), 1000);
  }
}
