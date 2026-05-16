import { apiClient } from './client';

export type BoqItemPayload = {
  item_code: string;
  description: string;
  discipline?: string;
  phase?: string;
  milestone_name?: string;
  unit: string;
  planned_quantity: string;
  unit_rate: string;
};

export type ProjectPayload = {
  name: string;
  scope_of_work: string;
  target_end_date: string;
  location?: string;
  client_name?: string;
  contract_number?: string;
  milestones: Array<{
    name: string;
    discipline?: string;
    planned_start_date?: string;
    planned_end_date?: string;
    sort_order: number;
  }>;
  boq_items: BoqItemPayload[];
};

export type ProjectRecord = {
  id: string;
  name: string;
  code: string;
  location: string | null;
  scope_of_work: string;
  status: string;
  target_end_date: string;
  client_name: string | null;
  progress_percentage: string;
};

export type ProjectListResponse = {
  items: ProjectRecord[];
  total: number;
};

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
