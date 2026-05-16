import { apiClient } from './client';

export type StorageLocationRecord = {
  id: string;
  name: string;
  code: string;
  location_type: string;
  project_id: string | null;
  address: string | null;
  is_active: boolean;
};

export type InventoryItemRecord = {
  id: string;
  name: string;
  item_code: string | null;
  category: string;
  item_type: string;
  unit: string;
  minimum_stock: string;
  reorder_level: string;
  unit_cost: string | null;
  supplier_id: string | null;
  is_active: boolean;
};

export type StockRecord = {
  id: string;
  item_id: string;
  location_id: string;
  location_name: string;
  on_hand_qty: string;
  reserved_qty: string;
  available_qty: string;
};

export type AssetRecord = {
  id: string;
  item_id: string;
  asset_tag: string;
  current_location_id: string;
  condition: string;
  status: string;
};

export type MovementRecord = {
  id: string;
  item_id: string;
  asset_id: string | null;
  movement_type: string;
  quantity: string;
  from_location_id: string | null;
  to_location_id: string | null;
  project_id: string | null;
  reference_type: string | null;
  reference_id: string | null;
  handled_by: string | null;
  notes: string | null;
  created_at: string;
};

export type MaterialRequestRecord = {
  id: string;
  request_number: string;
  project_id: string;
  requester_id: string | null;
  from_location_id: string | null;
  status: string;
  total_estimated_cost: string;
  notes: string | null;
  lines: Array<{
    id: string;
    item_id: string;
    quantity: string;
    reserved_quantity: string;
    issued_quantity: string;
    unit_cost: string | null;
  }>;
};

export type SupplierRecord = {
  id: string;
  name: string;
  category: string;
  rating: string;
  payment_terms: string;
  contact_person: string;
  phone: string;
  email: string;
  address: string;
  tax_registration_number: string;
  tds_certificate_number: string | null;
  tds_expiry_date: string | null;
  tds_document_key: string | null;
  compliance_status: string;
  is_active: boolean;
};

export async function listSuppliers() {
  const { data } = await apiClient.get<{ items: SupplierRecord[]; total: number }>('/suppliers', {
    params: { active: true }
  });
  return data.items;
}

export async function createSupplier(payload: {
  name: string;
  category: string;
  rating: string;
  payment_terms: string;
  contact_person: string;
  phone: string;
  email: string;
  address: string;
  tax_registration_number: string;
  tds_certificate_number?: string;
  tds_expiry_date?: string;
  compliance_status: string;
}) {
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
  const { data } = await apiClient.get<{ url: string; expires_in_seconds: number }>(
    `/suppliers/${supplierId}/tds-document`
  );
  return data;
}

export async function listLocations() {
  const { data } = await apiClient.get<StorageLocationRecord[]>('/inventory/locations');
  return data;
}

export async function createLocation(payload: {
  name: string;
  code: string;
  location_type: string;
  project_id?: string;
  address?: string;
}) {
  const { data } = await apiClient.post<StorageLocationRecord>('/inventory/locations', payload);
  return data;
}

export async function listInventoryItems(search?: string) {
  const { data } = await apiClient.get<InventoryItemRecord[]>('/inventory/items', {
    params: { search }
  });
  return data;
}

export async function createInventoryItem(payload: {
  name: string;
  item_code?: string;
  category: string;
  item_type: string;
  unit: string;
  minimum_stock: string;
  reorder_level: string;
  unit_cost?: string;
  supplier_id: string;
}) {
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

export async function createAsset(payload: {
  item_id: string;
  asset_tag: string;
  current_location_id: string;
  condition: string;
}) {
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

export async function createMovement(payload: {
  item_id: string;
  asset_id?: string;
  movement_type: string;
  quantity: string;
  from_location_id?: string;
  to_location_id?: string;
  project_id?: string;
  notes?: string;
}) {
  const { data } = await apiClient.post<MovementRecord>('/inventory/movements', payload);
  return data;
}

export async function listMaterialRequests() {
  const { data } = await apiClient.get<MaterialRequestRecord[]>('/inventory/requests');
  return data;
}

export async function createMaterialRequest(payload: {
  project_id: string;
  from_location_id: string;
  notes?: string;
  lines: Array<{ item_id: string; quantity: string }>;
}) {
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
