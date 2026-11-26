import { apiClient } from './client';
import type { components } from './schema';

export type NotificationRecord = components['schemas']['NotificationResponse'];
export type NotificationListResponse = components['schemas']['NotificationListResponse'];
export type UnreadCountResponse = components['schemas']['UnreadCountResponse'];

export async function listNotifications(
  limit = 100,
  offset = 0
): Promise<NotificationListResponse> {
  const response = await apiClient.get<NotificationListResponse>('/notifications', {
    params: { limit, offset }
  });
  return response.data;
}

export async function getUnreadCount(): Promise<number> {
  const response = await apiClient.get<UnreadCountResponse>('/notifications/unread-count');
  return response.data.unread_count;
}

export async function markNotificationRead(id: string): Promise<NotificationRecord> {
  const response = await apiClient.patch<NotificationRecord>(`/notifications/${id}/read`);
  return response.data;
}

export async function markAllNotificationsRead(): Promise<void> {
  await apiClient.post('/notifications/mark-all-read');
}

export async function muteNotification(id: string): Promise<NotificationRecord> {
  const response = await apiClient.patch<NotificationRecord>(`/notifications/${id}/mute`);
  return response.data;
}

export async function unmuteNotification(id: string): Promise<NotificationRecord> {
  const response = await apiClient.patch<NotificationRecord>(`/notifications/${id}/unmute`);
  return response.data;
}
