import { apiClient } from './client';

export type DashboardSummary = {
  active_projects: number;
  pending_reports: number;
  approved_reports: number;
  pending_documents: number;
  unread_notifications: number;
  recent_activity: string[];
};

export async function getDashboardSummary(): Promise<DashboardSummary> {
  const response = await apiClient.get<DashboardSummary>('/dashboard/summary');
  return response.data;
}
