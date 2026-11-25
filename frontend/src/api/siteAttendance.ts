import { apiClient } from './client';
import type { components } from './schema';

export type SiteAttendanceRecord = components['schemas']['SiteAttendanceResponse'];
export type SiteAttendanceDraft = components['schemas']['SiteAttendanceCreateRequest'];
export type SiteAttendanceWorker = components['schemas']['SiteAttendanceWorker'];

export async function getSiteAttendanceCompleteness(params: {
  project_id: string; work_date: string; limit: number; offset: number;
}) {
  const { data } = await apiClient.get<components['schemas']['SiteAttendanceCompleteness']>(
    '/hr/site-attendance/completeness', { params }
  );
  return data;
}

export async function listSiteAttendance(params: {
  project_id?: string;
  work_date?: string;
  entry_id?: string;
  limit: number;
  offset: number;
}) {
  const { data } = await apiClient.get<components['schemas']['SiteAttendancePageResponse']>(
    '/hr/site-attendance', { params }
  );
  return data;
}

export async function listSiteAttendanceWorkers(params: {
  project_id: string;
  work_date: string;
  historical?: boolean;
  search?: string;
  limit: number;
  offset: number;
}) {
  const { data } = await apiClient.get<components['schemas']['SiteAttendanceWorkerPage']>(
    '/hr/site-attendance/workers', { params }
  );
  return data;
}

export async function writeSiteAttendance(
  draft: SiteAttendanceDraft, correction?: SiteAttendanceRecord, correctionReason?: string
) {
  const path = correction ? `/hr/site-attendance/${correction.id}/correction` : '/hr/site-attendance';
  const { data } = await apiClient.post<SiteAttendanceRecord>(path, {
    ...draft,
    ...(correction ? {
      expected_revision: correction.record_revision,
      correction_reason: correctionReason
    } : {})
  });
  return data;
}

export async function reviewSiteAttendance(
  record: SiteAttendanceRecord,
  stage: 'engineer' | 'hr',
  decision: 'approved' | 'returned' | 'rejected',
  comments: string
) {
  const { data } = await apiClient.post<SiteAttendanceRecord>(
    `/hr/site-attendance/${record.id}/decision`, {
      expected_revision: record.record_revision, stage, decision, comments
    }
  );
  return data;
}

export async function listSiteAttendanceHistory(entryId: string) {
  const { data } = await apiClient.get<components['schemas']['SiteAttendanceSubmissionResponse'][]>(
    `/hr/site-attendance/${entryId}/history`
  );
  return data;
}

export const siteAttendanceRoles = new Set([
  'site_supervisor', 'senior_site_supervisor', 'mep_project_manager',
  'group_project_manager', 'managing_director', 'operations_director', 'hr_manager'
]);
