import { apiClient } from './client';
import type { components } from './schema';

export type UserRecord = components['schemas']['UserResponse'];

export type UserListResponse = components['schemas']['UserListResponse'];

export type CreateUserPayload = components['schemas']['UserCreateRequest'];
export type UserRoleOption = components['schemas']['UserRoleResponse'];

export async function listUserRoles(): Promise<UserRoleOption[]> {
  const response = await apiClient.get<components['schemas']['UserRoleListResponse']>('/users/roles');
  return response.data.items;
}

export async function listUsers(params: {
  active?: boolean;
  role?: string;
  search?: string;
  limit?: number;
  offset?: number;
}): Promise<UserListResponse> {
  const response = await apiClient.get<UserListResponse>('/users', { params });
  return response.data;
}

export async function createUser(payload: CreateUserPayload): Promise<UserRecord> {
  const response = await apiClient.post<UserRecord>('/users', payload);
  return response.data;
}

export async function updateUserRole(
  userId: string,
  role: string,
  expected_updated_at: string
): Promise<UserRecord> {
  const payload: components['schemas']['UserUpdateRequest'] = { role, expected_updated_at };
  const response = await apiClient.patch<UserRecord>(`/users/${userId}`, payload);
  return response.data;
}

export async function deactivateUser(
  userId: string,
  expected_updated_at: string
): Promise<UserRecord> {
  const response = await apiClient.delete<UserRecord>(`/users/${userId}`, {
    params: { expected_updated_at }
  });
  return response.data;
}

export async function adminResetPassword(
  userId: string,
  newPassword: string,
  expected_updated_at: string
): Promise<UserRecord> {
  const payload: components['schemas']['AdminPasswordResetRequest'] = {
    new_password: newPassword,
    expected_updated_at
  };
  const response = await apiClient.post<UserRecord>(`/users/${userId}/reset-password`, payload);
  return response.data;
}
