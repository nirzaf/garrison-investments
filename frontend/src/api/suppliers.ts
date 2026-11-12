import { apiClient } from './client';
import type { SupplierListResponse, SupplierRecord } from './inventory';
import type { components } from './schema';

export type SupplierUpdatePayload = components['schemas']['SupplierUpdateRequest'];

export async function listSupplierRegister(params: {
  active?: boolean;
  compliance_status?: string;
  search?: string;
  limit: number;
  offset: number;
}) {
  const { data } = await apiClient.get<SupplierListResponse>('/suppliers', { params });
  return data;
}

export async function updateSupplier(supplierId: string, payload: SupplierUpdatePayload) {
  const { data } = await apiClient.patch<SupplierRecord>(`/suppliers/${supplierId}`, payload);
  return data;
}

export async function deactivateSupplier(supplierId: string, revision: number) {
  const { data } = await apiClient.delete<SupplierRecord>(`/suppliers/${supplierId}`, {
    params: { expected_revision: revision }
  });
  return data;
}
