import { CheckCheck } from 'lucide-react';
import { useCallback, useEffect, useState } from 'react';

import {
  listNotifications,
  markAllNotificationsRead,
  markNotificationRead,
  type NotificationRecord
} from '../../api/notifications';
import { EmptyState } from '../../components/shared/EmptyState';
import { StatusBadge } from '../../components/shared/StatusBadge';

export function NotificationsPage() {
  const [notifications, setNotifications] = useState<NotificationRecord[]>([]);
  const [error, setError] = useState<string | null>(null);

  const loadNotifications = useCallback(async () => {
    try {
      const response = await listNotifications();
      setNotifications(response.items);
    } catch {
      setError('Unable to load notifications.');
    }
  }, []);

  useEffect(() => {
    void loadNotifications();
  }, [loadNotifications]);

  async function markAllRead() {
    await markAllNotificationsRead();
    await loadNotifications();
  }

  async function markRead(notification: NotificationRecord) {
    if (notification.is_read) return;
    await markNotificationRead(notification.id);
    await loadNotifications();
  }

  return (
    <div className="space-y-6">
      <div className="flex flex-col justify-between gap-3 sm:flex-row sm:items-end">
        <div>
          <p className="text-sm font-medium text-brand-700">Notifications</p>
          <h2 className="text-2xl font-semibold text-slate-950">Notification History</h2>
        </div>
        <button
          className="inline-flex min-h-10 items-center justify-center gap-2 rounded-md border border-slate-300 px-3 py-2 text-sm font-semibold text-slate-700 hover:bg-slate-50"
          onClick={() => void markAllRead()}
          type="button"
        >
          <CheckCheck className="h-4 w-4" />
          Mark all read
        </button>
      </div>

      {error ? (
        <p className="rounded-md bg-red-50 px-3 py-2 text-sm text-red-700">{error}</p>
      ) : null}

      {notifications.length === 0 ? (
        <EmptyState
          description="Workflow alerts, approvals, and reminders will appear here."
          title="No notifications"
        />
      ) : (
        <div className="space-y-3">
          {notifications.map((notification) => (
            <button
              className="w-full rounded-lg border border-slate-200 bg-white p-4 text-left shadow-sm hover:bg-slate-50"
              key={notification.id}
              onClick={() => void markRead(notification)}
              type="button"
            >
              <div className="flex items-start justify-between gap-3">
                <div>
                  <p className="text-sm font-semibold text-slate-950">{notification.title}</p>
                  <p className="mt-1 text-sm text-slate-600">{notification.body}</p>
                  <p className="mt-2 text-xs text-slate-500">
                    {new Date(notification.created_at).toLocaleString()}
                  </p>
                </div>
                <StatusBadge tone={notification.is_read ? 'neutral' : 'info'}>
                  {notification.is_read ? 'read' : 'unread'}
                </StatusBadge>
              </div>
            </button>
          ))}
        </div>
      )}
    </div>
  );
}
