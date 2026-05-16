import { apiClient } from './client';

export type DocumentVersionRecord = {
  id: string;
  document_id: string;
  version: number;
  status: string;
  original_name: string;
  mime_type: string;
  size_bytes: number;
  approved_at: string | null;
  approval_comments: string | null;
};

export type DocumentRecord = {
  id: string;
  title: string;
  document_type: string;
  project_id: string | null;
  status: string;
  active_version: number | null;
  expiry_date: string | null;
  versions: DocumentVersionRecord[];
};

export type DocumentListResponse = {
  items: DocumentRecord[];
  total: number;
};

export async function listDocuments(params: {
  project_id?: string;
  document_type?: string;
  search?: string;
}): Promise<DocumentListResponse> {
  const response = await apiClient.get<DocumentListResponse>('/documents', { params });
  return response.data;
}

export async function uploadDocument(params: {
  title: string;
  documentType: string;
  projectId?: string;
  expiryDate?: string;
  file: File;
}): Promise<DocumentRecord> {
  const formData = new FormData();
  formData.append('title', params.title);
  formData.append('document_type', params.documentType);
  if (params.projectId) formData.append('project_id', params.projectId);
  if (params.expiryDate) formData.append('expiry_date', params.expiryDate);
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

export async function getDocumentDownloadUrl(
  documentId: string,
  versionId?: string
): Promise<{ url: string; superseded_warning: boolean }> {
  const response = await apiClient.get<{ url: string; superseded_warning: boolean }>(
    `/documents/${documentId}/download`,
    { params: { version_id: versionId } }
  );
  return response.data;
}
