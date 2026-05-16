import { apiClient } from './client';

export type UserRecord = {
  id: string;
  email: string;
  full_name: string;
  role: string;
  employee_code: string | null;
  phone: string | null;
  designation: string | null;
  is_active: boolean;
  must_change_password: boolean;
};

export type UserListResponse = {
  items: UserRecord[];
  total: number;
};

export type CreateUserPayload = {
  email: string;
  full_name: string;
  role: string;
  employee_code: string;
  phone: string;
  designation?: string;
  temporary_password: string;
};

export async function listUsers(params: {
  active?: boolean;
  role?: string;
  search?: string;
}): Promise<UserListResponse> {
  const response = await apiClient.get<UserListResponse>('/users', { params });
  return response.data;
}

export async function createUser(payload: CreateUserPayload): Promise<UserRecord> {
  const response = await apiClient.post<UserRecord>('/users', payload);
  return response.data;
}

export async function deactivateUser(userId: string): Promise<UserRecord> {
  const response = await apiClient.delete<UserRecord>(`/users/${userId}`);
  return response.data;
}
