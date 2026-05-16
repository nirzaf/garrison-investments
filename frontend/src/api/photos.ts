import { apiClient } from './client';

export type PhotoRecord = {
  id: string;
  filename: string;
  original_name: string;
  storage_path: string;
  compressed_path: string | null;
  thumbnail_path: string | null;
  mime_type: string;
  size_bytes: number;
  width: number | null;
  height: number | null;
  entity_type: string;
  entity_id: string;
  kind: string;
  caption: string | null;
  processing_status: string;
};

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
}): Promise<{ items: PhotoRecord[]; total: number }> {
  const response = await apiClient.get<{ items: PhotoRecord[]; total: number }>('/photos', {
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
  const response = await apiClient.get<{ url: string; expires_in_seconds: number }>(
    `/photos/${photoId}/download`
  );
  return response.data.url;
}

export async function getPhotoThumbnailUrl(photoId: string): Promise<string> {
  const response = await apiClient.get<{ url: string; expires_in_seconds: number }>(
    `/photos/${photoId}/thumbnail`
  );
  return response.data.url;
}
