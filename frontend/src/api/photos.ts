import { apiClient, sessionRequestConfig } from './client';
import { formatApiError } from './errors';
import { classifyReportFile, type ReportFileKind } from './fileValidation';
import type { OfflineScope } from './offlineDb';
import { normalizeProtectedFileUrl } from './fileUrls';
import type { components } from './schema';

export type PhotoRecord = components['schemas']['PhotoResponse'];
export type PhotoListResponse = components['schemas']['PhotoListResponse'];
export type ProtectedFileUrl = components['schemas']['ProtectedFileUrlResponse'];

export type MediaUploadIntent = {
  file: File;
  kind: ReportFileKind;
  key: string;
  expectedReportRevision?: number;
};

export async function prepareMediaFiles(
  files: FileList | File[],
  kind: ReportFileKind,
  remainingSlots: number
) {
  const items: MediaUploadIntent[] = [];
  const errors: string[] = [];
  for (const file of Array.from(files)) {
    try {
      const normalizedKind = await classifyReportFile(file, kind);
      if (normalizedKind === 'photo' && remainingSlots <= 0) {
        throw new Error('This draft already has all five photo slots in use.');
      }
      items.push({ file, kind: normalizedKind, key: crypto.randomUUID() });
      if (normalizedKind === 'photo') remainingSlots -= 1;
    } catch (error) {
      errors.push(`${file.name} — ${error instanceof Error ? error.message : 'Invalid file.'}`);
    }
  }
  return { items, errors };
}

export async function uploadMediaFiles(
  entityType: string,
  entityId: string,
  items: MediaUploadIntent[],
  scope?: OfflineScope,
  reportRevision?: number
) {
  const uploaded: PhotoRecord[] = [];
  const failed: MediaUploadIntent[] = [];
  const errors: string[] = [];
  for (const item of items) {
    const intent = {
      ...item,
      expectedReportRevision: item.expectedReportRevision ?? reportRevision
    };
    try {
      const result = await uploadEntityFilesWithRevision({
        entityType,
        entityId,
        kind: intent.kind,
        files: [intent.file],
        idempotencyKey: intent.key,
        scope,
        expectedReportRevision: intent.expectedReportRevision
      });
      uploaded.push(...result.files);
      if (reportRevision !== undefined && result.reportRevision === reportRevision + 1) {
        reportRevision = result.reportRevision;
      }
    } catch (error) {
      failed.push(intent);
      errors.push(`${item.file.name} — ${formatApiError(error, 'Unable to upload file.')}`);
    }
  }
  return { uploaded, failed, errors, reportRevision };
}

type UploadEntityFiles = {
  entityType: string;
  entityId: string;
  kind: 'photo' | 'attachment';
  files: FileList | File[];
  idempotencyKey?: string;
  scope?: OfflineScope;
  expectedReportRevision?: number;
};

export async function uploadEntityFiles(params: UploadEntityFiles): Promise<PhotoRecord[]> {
  return (await uploadEntityFilesWithRevision(params)).files;
}

export async function uploadEntityFilesWithRevision(
  params: UploadEntityFiles
): Promise<{ files: PhotoRecord[]; reportRevision?: number }> {
  const formData = new FormData();
  formData.append('entity_type', params.entityType);
  formData.append('entity_id', params.entityId);
  formData.append('kind', params.kind);
  if (params.expectedReportRevision !== undefined) {
    formData.append('expected_report_revision', String(params.expectedReportRevision));
  }
  Array.from(params.files).forEach((file) => formData.append('files', file));
  const response = await apiClient.post<PhotoRecord[]>('/photos/upload', formData, {
    ...sessionRequestConfig(params.scope),
    headers: {
      'Content-Type': 'multipart/form-data',
      ...(params.idempotencyKey ? { 'Idempotency-Key': params.idempotencyKey } : {})
    }
  });
  const revision = Number(response.headers['x-report-revision']);
  return {
    files: response.data,
    reportRevision: Number.isSafeInteger(revision) && revision > 0 ? revision : undefined
  };
}

export async function listPhotos(
  params?: {
    entityType?: string;
    entityId?: string;
    kind?: 'photo' | 'attachment';
    limit?: number;
    offset?: number;
    deleted?: boolean;
  },
  signal?: AbortSignal
): Promise<PhotoListResponse> {
  const response = await apiClient.get<PhotoListResponse>('/photos', {
    signal,
    params: {
      entity_type: params?.entityType,
      entity_id: params?.entityId,
      kind: params?.kind,
      limit: params?.limit,
      offset: params?.offset,
      deleted: params?.deleted
    }
  });
  return response.data;
}

export async function deletePhoto(photoId: string, reason?: string): Promise<void> {
  await apiClient.delete(`/photos/${photoId}`, { data: { reason } });
}

export async function recoverPhoto(photoId: string, reason?: string): Promise<PhotoRecord> {
  const response = await apiClient.post<PhotoRecord>(`/photos/${photoId}/recover`, { reason });
  return response.data;
}

export async function getPhotoDownloadUrl(photoId: string): Promise<string> {
  const response = await apiClient.get<ProtectedFileUrl>(`/photos/${photoId}/download`);
  return normalizeProtectedFileUrl(response.data.url);
}

export async function getPhotoThumbnailUrl(photoId: string): Promise<string> {
  const response = await apiClient.get<ProtectedFileUrl>(`/photos/${photoId}/thumbnail`);
  return normalizeProtectedFileUrl(response.data.url);
}
