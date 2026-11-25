import { apiClient } from './client';
import { normalizeProtectedFileUrl } from './fileUrls';
import type { components } from './schema';

export type DocumentVersionRecord = components['schemas']['DocumentVersionResponse'];

export type DocumentRecord = components['schemas']['DocumentResponse'];
export type DocumentUploadResult =
  | DocumentRecord
  | components['schemas']['EvidenceUploadReceipt'];

export type DocumentListResponse = components['schemas']['DocumentListResponse'];
export type DocumentDownloadUrl = components['schemas']['DocumentDownloadResponse'];

export async function listDocuments(params: {
  project_id?: string;
  document_type?: string;
  search?: string;
  limit?: number;
  offset?: number;
}, signal?: AbortSignal): Promise<DocumentListResponse> {
  const response = await apiClient.get<DocumentListResponse>('/documents', { params, signal });
  return response.data;
}

export async function getDocument(documentId: string, signal?: AbortSignal) {
  const response = await apiClient.get<DocumentRecord>(`/documents/${documentId}`, { signal });
  return response.data;
}

export async function uploadDocument(params: {
  title: string;
  documentType: string;
  projectId?: string;
  expiryDate?: string;
  file: File;
  classification: 'unclassified' | 'operational' | 'financial';
}): Promise<DocumentUploadResult> {
  const formData = new FormData();
  formData.append('title', params.title);
  formData.append('document_type', params.documentType);
  if (params.projectId) formData.append('project_id', params.projectId);
  if (params.expiryDate) formData.append('expiry_date', params.expiryDate);
  formData.append('classification', params.classification);
  formData.append('file', params.file);
  const response = await apiClient.post<DocumentRecord>('/documents', formData, {
    headers: { 'Content-Type': 'multipart/form-data' }
  });
  return response.data;
}

export async function approveDocumentVersion(params: {
  documentId: string;
  versionId: string;
  comments?: string;
}): Promise<DocumentRecord> {
  const response = await apiClient.post<DocumentRecord>(
    `/documents/${params.documentId}/versions/${params.versionId}/approve`,
    { comments: params.comments }
  );
  return response.data;
}

export async function classifyDocument(
  documentId: string,
  classification: 'operational' | 'financial',
  reason: string,
  expectedClassification: 'unclassified' | 'operational' | 'financial',
  expectedUpdatedAt: string
): Promise<DocumentRecord> {
  const response = await apiClient.patch<DocumentRecord>(
    `/documents/${documentId}/classification`,
    {
      classification,
      reason,
      expected_classification: expectedClassification,
      expected_updated_at: expectedUpdatedAt
    }
  );
  return response.data;
}

export async function uploadDocumentVersion(
  documentId: string,
  file: File,
  idempotencyKey: string,
  classification: 'unclassified' | 'operational' | 'financial'
) {
  const formData = new FormData();
  formData.append('file', file);
  formData.append('classification', classification);
  const response = await apiClient.post<DocumentUploadResult>(
    `/documents/${documentId}/versions`,
    formData,
    { headers: { 'Content-Type': 'multipart/form-data', 'Idempotency-Key': idempotencyKey } }
  );
  return response.data;
}

export async function getDocumentVersionDownloadUrl(documentId: string, versionNumber: number) {
  const { data: versions } = await apiClient.get<DocumentVersionRecord[]>(
    `/documents/${documentId}/versions`
  );
  const version = versions.find((entry) => entry.version === versionNumber);
  if (!version) throw new Error('This submitted document version is unavailable.');
  return getDocumentDownloadUrl(documentId, version.id);
}

export async function getDocumentDownloadUrl(
  documentId: string,
  versionId?: string
): Promise<DocumentDownloadUrl> {
  const response = await apiClient.get<DocumentDownloadUrl>(`/documents/${documentId}/download`, {
    params: { version_id: versionId }
  });
  return { ...response.data, url: normalizeProtectedFileUrl(response.data.url) };
}
