import { apiClient } from './client';

export type ImportPreview = {
  template_type: string;
  row_count: number;
  valid: boolean;
  errors: Array<{ row: number; field: string; message: string }>;
};

export type ImportRunResult = {
  batch_id: string;
  template_type: string;
  status: string;
  row_count: number;
  error_count: number;
  summary: Record<string, unknown>;
};

export const importTemplates = [
  'users',
  'projects',
  'suppliers',
  'materials',
  'documents',
  'boq',
  'opening_stock'
];

export async function downloadTemplate(template: string) {
  const { data } = await apiClient.get<Blob>(`/imports/templates/${template}`, {
    responseType: 'blob'
  });
  return data;
}

export async function previewImport(template: string, file: File) {
  const formData = new FormData();
  formData.append('file', file);
  const { data } = await apiClient.post<ImportPreview>(`/imports/${template}/preview`, formData, {
    headers: { 'Content-Type': 'multipart/form-data' }
  });
  return data;
}

export async function runImport(template: string, file: File) {
  const formData = new FormData();
  formData.append('file', file);
  const { data } = await apiClient.post<ImportRunResult>(`/imports/${template}/run`, formData, {
    headers: { 'Content-Type': 'multipart/form-data' }
  });
  return data;
}
