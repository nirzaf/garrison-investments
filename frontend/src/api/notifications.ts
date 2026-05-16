import { apiClient } from './client';

export type NotificationRecord = {
  id: string;
  title: string;
  body: string;
  notification_type: string;
  reference_type: string | null;
  reference_id: string | null;
  is_read: boolean;
  created_at: string;
};

export async function listNotifications(): Promise<{
  items: NotificationRecord[];
  total: number;
}> {
  const response = await apiClient.get<{ items: NotificationRecord[]; total: number }>(
    '/notifications'
  );
  return response.data;
}

export async function getUnreadCount(): Promise<number> {
  const response = await apiClient.get<{ unread_count: number }>('/notifications/unread-count');
  return response.data.unread_count;
}

export async function markNotificationRead(id: string): Promise<NotificationRecord> {
  const response = await apiClient.patch<NotificationRecord>(`/notifications/${id}/read`);
  return response.data;
}

export async function markAllNotificationsRead(): Promise<void> {
  await apiClient.post('/notifications/mark-all-read');
}
