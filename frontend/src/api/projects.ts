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
