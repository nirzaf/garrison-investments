import { apiClient } from './client';
import { normalizeProjectCreate, type ProjectSetupDraft } from './projectSetup';
import type { components } from './schema';

export type ProjectRecord = components['schemas']['ProjectResponse'];
export type ProjectDetail = components['schemas']['ProjectDetailResponse'];
export type ProjectUpdatePayload = components['schemas']['ProjectUpdateRequest'];
export type ProjectMember = components['schemas']['ProjectMemberResponse'];
export type ProjectMemberPayload = components['schemas']['ProjectMemberCreateRequest'];
export type ProjectListResponse = components['schemas']['ProjectListResponse'];
export type ProjectOption = components['schemas']['ProjectOption'];
export type ProjectOptionListResponse = components['schemas']['ProjectOptionListResponse'];
export type ProjectTimelineResponse = components['schemas']['ProjectTimelineResponse'];
export type ProjectTaskPayload = components['schemas']['ProjectTaskCreateRequest'];
export type ProjectTaskRecord = components['schemas']['ProjectTaskResponse'];
export type ProjectTaskUpdatePayload = components['schemas']['ProjectTaskUpdateRequest'];
export type ProjectBoqItemPayload = components['schemas']['BoqItemCreateRequest'];
export type ProjectBoqItem = components['schemas']['BoqItemResponse'];

export async function listProjectHrAssignments(projectId: string, offset: number) {
  const { data } = await apiClient.get<components['schemas']['HrProjectAssignmentListResponse']>(
    `/projects/${projectId}/hr-assignment-requests`,
    { params: { offset } }
  );
  return data;
}

export async function decideProjectHrAssignment(
  projectId: string,
  requestId: string,
  payload: components['schemas']['HrProjectAssignmentDecision']
) {
  const { data } = await apiClient.post<components['schemas']['HrProjectAssignmentResponse']>(
    `/projects/${projectId}/hr-assignment-requests/${requestId}/decision`,
    payload
  );
  return data;
}

export async function listProjects(params: {
  status?: string;
  search?: string;
  limit?: number;
  offset?: number;
}): Promise<ProjectListResponse> {
  const response = await apiClient.get<ProjectListResponse>('/projects', { params });
  return response.data;
}

export async function listReportProjectOptions(params: {
  search?: string;
  limit?: number;
  offset?: number;
} = {}): Promise<ProjectOptionListResponse> {
  const response = await apiClient.get<ProjectOptionListResponse>('/reports/project-options', {
    params
  });
  return response.data;
}

export async function listDocumentProjectOptions(params: {
  search?: string;
  limit?: number;
  offset?: number;
} = {}): Promise<ProjectOptionListResponse> {
  const response = await apiClient.get<ProjectOptionListResponse>('/documents/project-options', {
    params
  });
  return response.data;
}

export async function createProject(payload: ProjectSetupDraft): Promise<ProjectRecord> {
  const response = await apiClient.post<ProjectRecord>(
    '/projects',
    normalizeProjectCreate(payload)
  );
  return response.data;
}

export async function createProjectBoqItem(
  projectId: string,
  payload: ProjectBoqItemPayload
): Promise<ProjectBoqItem> {
  const response = await apiClient.post<ProjectBoqItem>(
    `/projects/${projectId}/boq-items`,
    payload
  );
  return response.data;
}

export async function getProject(projectId: string): Promise<ProjectDetail> {
  const response = await apiClient.get<ProjectDetail>(`/projects/${projectId}`);
  return response.data;
}

export async function updateProject(
  projectId: string,
  payload: ProjectUpdatePayload
): Promise<ProjectRecord> {
  const response = await apiClient.patch<ProjectRecord>(`/projects/${projectId}`, payload);
  return response.data;
}

export async function listProjectMembers(projectId: string): Promise<ProjectMember[]> {
  const response = await apiClient.get<ProjectMember[]>(`/projects/${projectId}/members`);
  return response.data;
}

export async function assignProjectMember(
  projectId: string,
  payload: ProjectMemberPayload
): Promise<ProjectMember> {
  const response = await apiClient.post<ProjectMember>(`/projects/${projectId}/members`, payload);
  return response.data;
}

export async function getProjectTimeline(projectId: string): Promise<ProjectTimelineResponse> {
  const response = await apiClient.get<ProjectTimelineResponse>(`/projects/${projectId}/timeline`);
  return response.data;
}

export async function createProjectTask(
  projectId: string,
  payload: ProjectTaskPayload
): Promise<ProjectTaskRecord> {
  const response = await apiClient.post<ProjectTaskRecord>(`/projects/${projectId}/tasks`, payload);
  return response.data;
}

export async function updateProjectTask(
  projectId: string,
  taskId: string,
  payload: ProjectTaskUpdatePayload
): Promise<ProjectTaskRecord> {
  const response = await apiClient.patch<ProjectTaskRecord>(
    `/projects/${projectId}/tasks/${taskId}`,
    payload
  );
  return response.data;
}
