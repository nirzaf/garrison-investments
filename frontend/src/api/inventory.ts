import { apiClient } from './client';
import type { components } from './schema';

export type StorageLocationRecord = components['schemas']['LocationResponse'];
export type LocationCreatePayload = components['schemas']['LocationCreateRequest'];

export type InventoryItemRecord = components['schemas']['InventoryItemResponse'];
export type InventoryItemCreatePayload = components['schemas']['InventoryItemCreateRequest'];

export type StockRecord = components['schemas']['StockResponse'];

export type AssetRecord = components['schemas']['AssetResponse'];
export type AssetCreatePayload = components['schemas']['AssetCreateRequest'];

export type MovementRecord = components['schemas']['MovementResponse'];
export type MovementCreatePayload = components['schemas']['MovementCreateRequest'];

export type MaterialRequestRecord = components['schemas']['MaterialRequestResponse'];
export type MaterialRequestCreatePayload = components['schemas']['MaterialRequestCreateRequest'];

export type SupplierRecord = components['schemas']['SupplierResponse'];
export type SupplierListResponse = components['schemas']['SupplierListResponse'];
export type SupplierCreatePayload = components['schemas']['SupplierCreateRequest'];
export type SupplierDocumentUrl = components['schemas']['SupplierDocumentUrlResponse'];

export async function listSuppliers() {
  const { data } = await apiClient.get<SupplierListResponse>('/suppliers', {
    params: { active: true }
  });
  return data.items;
}

export async function createSupplier(payload: SupplierCreatePayload) {
  const { data } = await apiClient.post<SupplierRecord>('/suppliers', payload);
  return data;
}

export async function uploadSupplierTdsDocument(supplierId: string, file: File) {
  const formData = new FormData();
  formData.append('file', file);
  const { data } = await apiClient.post<SupplierRecord>(
    `/suppliers/${supplierId}/tds-document`,
    formData,
    { headers: { 'Content-Type': 'multipart/form-data' } }
  );
  return data;
}

export async function getSupplierTdsDocumentUrl(supplierId: string) {
  const { data } = await apiClient.get<SupplierDocumentUrl>(
    `/suppliers/${supplierId}/tds-document`
  );
  return data;
}

export async function listLocations() {
  const { data } = await apiClient.get<StorageLocationRecord[]>('/inventory/locations');
  return data;
}

export async function createLocation(payload: LocationCreatePayload) {
  const { data } = await apiClient.post<StorageLocationRecord>('/inventory/locations', payload);
  return data;
}

export async function listInventoryItems(search?: string) {
  const { data } = await apiClient.get<InventoryItemRecord[]>('/inventory/items', {
    params: { search }
  });
  return data;
}

export async function createInventoryItem(payload: InventoryItemCreatePayload) {
  const { data } = await apiClient.post<InventoryItemRecord>('/inventory/items', payload);
  return data;
}

export async function listItemStock(itemId: string) {
  const { data } = await apiClient.get<StockRecord[]>(`/inventory/items/${itemId}/stock`);
  return data;
}

export async function receiveStock(payload: {
  item_id: string;
  to_location_id: string;
  quantity: string;
  notes?: string;
}) {
  const { data } = await apiClient.post('/inventory/movements', {
    ...payload,
    movement_type: 'receive'
  });
  return data;
}

export async function listLowStock() {
  const { data } = await apiClient.get<StockRecord[]>('/inventory/low-stock');
  return data;
}

export async function listAssets() {
  const { data } = await apiClient.get<AssetRecord[]>('/inventory/assets');
  return data;
}

export async function createAsset(payload: AssetCreatePayload) {
  const { data } = await apiClient.post<AssetRecord>('/inventory/assets', payload);
  return data;
}

export async function listMovements(params?: {
  item_id?: string;
  location_id?: string;
  project_id?: string;
}) {
  const { data } = await apiClient.get<MovementRecord[]>('/inventory/movements', { params });
  return data;
}

export async function createMovement(payload: MovementCreatePayload) {
  const { data } = await apiClient.post<MovementRecord>('/inventory/movements', payload);
  return data;
}

export async function listMaterialRequests() {
  const { data } = await apiClient.get<MaterialRequestRecord[]>('/inventory/requests');
  return data;
}

export async function createMaterialRequest(payload: MaterialRequestCreatePayload) {
  const { data } = await apiClient.post<MaterialRequestRecord>('/inventory/requests', payload);
  return data;
}

export async function reserveMaterialRequest(requestId: string) {
  const { data } = await apiClient.post<MaterialRequestRecord>(
    `/inventory/requests/${requestId}/reserve`
  );
  return data;
}

export async function issueMaterialRequest(requestId: string) {
  const { data } = await apiClient.post<MaterialRequestRecord>(
    `/inventory/requests/${requestId}/issue`
  );
  return data;
}

export async function cancelMaterialRequest(requestId: string) {
  const { data } = await apiClient.post<MaterialRequestRecord>(
    `/inventory/requests/${requestId}/cancel`
  );
  return data;
}
