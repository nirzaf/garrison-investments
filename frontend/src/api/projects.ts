import { apiClient } from './client';
import type { components } from './schema';

export type BoqItemPayload = components['schemas']['BoqItemCreateRequest'];

type ProjectCreateSchema = components['schemas']['ProjectCreateRequest'];

export type ProjectPayload = ProjectCreateSchema & {
  location?: string;
  client_name?: string;
  contract_number?: string;
  milestones: NonNullable<ProjectCreateSchema['milestones']>;
  boq_items: NonNullable<ProjectCreateSchema['boq_items']>;
};

export type ProjectRecord = components['schemas']['ProjectResponse'];

export type ProjectListResponse = components['schemas']['ProjectListResponse'];
export type ProjectTimelineResponse = components['schemas']['ProjectTimelineResponse'];
export type ProjectTaskPayload = components['schemas']['ProjectTaskCreateRequest'];
export type ProjectTaskRecord = components['schemas']['ProjectTaskResponse'];

export async function listProjects(params: {
  status?: string;
  search?: string;
}): Promise<ProjectListResponse> {
  const response = await apiClient.get<ProjectListResponse>('/projects', { params });
  return response.data;
}

export async function createProject(payload: ProjectPayload): Promise<ProjectRecord> {
  const response = await apiClient.post<ProjectRecord>('/projects', payload);
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
