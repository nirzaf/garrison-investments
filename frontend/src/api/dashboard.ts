import { apiClient } from './client';
import type { components } from './schema';

export type DashboardSummary = components['schemas']['DashboardSummaryResponse'];

export async function getDashboardSummary(): Promise<DashboardSummary> {
  const response = await apiClient.get<DashboardSummary>('/dashboard/summary');
  return response.data;
}
