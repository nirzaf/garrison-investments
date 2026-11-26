import { apiClient } from './client';
import type { components } from './schema';

export type DashboardSummary = components['schemas']['DashboardSummaryResponse'];
export type BirthdayPage = components['schemas']['BirthdayPageResponse'];
export type AnniversaryPage = components['schemas']['AnniversaryPageResponse'];

export async function getDashboardSummary(): Promise<DashboardSummary> {
  const response = await apiClient.get<DashboardSummary>('/dashboard/summary');
  return response.data;
}

export async function getUpcomingBirthdays(offset = 0, limit = 25): Promise<BirthdayPage> {
  const response = await apiClient.get<BirthdayPage>('/dashboard/birthdays', {
    params: { offset, limit }
  });
  return response.data;
}

export async function getUpcomingAnniversaries(offset = 0, limit = 25): Promise<AnniversaryPage> {
  const response = await apiClient.get<AnniversaryPage>('/dashboard/anniversaries', {
    params: { offset, limit }
  });
  return response.data;
}
