import { apiClient } from './client';
import type { components } from './schema';

export type ImportPreview = components['schemas']['ImportPreviewResponse'];
export type ImportRunResult = components['schemas']['ImportRunResponse'];

export type AsyncImportResult = components['schemas']['ImportQueueResponse'];

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

export async function runImport(template: string, file: File, key: string) {
  const formData = new FormData();
  formData.append('file', file);
  const { data } = await apiClient.post<ImportRunResult>(`/imports/${template}/run`, formData, {
    headers: { 'Content-Type': 'multipart/form-data', 'Idempotency-Key': key }
  });
  return data;
}

export async function runImportAsync(template: string, file: File, key: string) {
  const formData = new FormData();
  formData.append('file', file);
  const { data } = await apiClient.post<AsyncImportResult>(
    `/imports/${template}/run-async`,
    formData,
    {
      headers: { 'Content-Type': 'multipart/form-data', 'Idempotency-Key': key }
    }
  );
  return data;
}

export async function getImportBatchStatus(batchId: string) {
  const { data } = await apiClient.get<ImportRunResult>(`/imports/batches/${batchId}`);
  return data;
}

export async function listImportBatches() {
  const { data } = await apiClient.get<{ items: ImportRunResult[]; total: number }>(
    '/imports/batches'
  );
  return data;
}
