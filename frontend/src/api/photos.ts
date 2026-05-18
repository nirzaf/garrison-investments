import { apiClient } from './client';
import { normalizeProtectedFileUrl } from './fileUrls';
import type { components } from './schema';

export type PhotoRecord = components['schemas']['PhotoResponse'];
export type PhotoListResponse = components['schemas']['PhotoListResponse'];
export type ProtectedFileUrl = components['schemas']['ProtectedFileUrlResponse'];

export async function uploadEntityFiles(params: {
  entityType: string;
  entityId: string;
  kind: 'photo' | 'attachment';
  files: FileList | File[];
}): Promise<PhotoRecord[]> {
  const formData = new FormData();
  formData.append('entity_type', params.entityType);
  formData.append('entity_id', params.entityId);
  formData.append('kind', params.kind);
  Array.from(params.files).forEach((file) => formData.append('files', file));
  const response = await apiClient.post<PhotoRecord[]>('/photos/upload', formData, {
    headers: { 'Content-Type': 'multipart/form-data' }
  });
  return response.data;
}

export async function listPhotos(params?: {
  entityType?: string;
  entityId?: string;
  kind?: 'photo' | 'attachment';
  limit?: number;
  offset?: number;
}): Promise<PhotoListResponse> {
  const response = await apiClient.get<PhotoListResponse>('/photos', {
    params: {
      entity_type: params?.entityType,
      entity_id: params?.entityId,
      kind: params?.kind,
      limit: params?.limit,
      offset: params?.offset
    }
  });
  return response.data;
}

export async function getPhotoDownloadUrl(photoId: string): Promise<string> {
  const response = await apiClient.get<ProtectedFileUrl>(
    `/photos/${photoId}/download`
  );
  return normalizeProtectedFileUrl(response.data.url);
}

export async function getPhotoThumbnailUrl(photoId: string): Promise<string> {
  const response = await apiClient.get<ProtectedFileUrl>(
    `/photos/${photoId}/thumbnail`
  );
  return normalizeProtectedFileUrl(response.data.url);
}
