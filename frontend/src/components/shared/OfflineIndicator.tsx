import { useEffect, useState } from 'react';
import { flushPhotoQueue, listenForSyncMessages } from '../../api/offlineQueue';

export function OfflineIndicator() {
  const [isOnline, setIsOnline] = useState(() => navigator.onLine);

  useEffect(() => {
    const handleOnline = () => {
      setIsOnline(true);
      void flushPhotoQueue();
    };
    const handleOffline = () => setIsOnline(false);

    window.addEventListener('online', handleOnline);
    window.addEventListener('offline', handleOffline);

    const cleanupSync = listenForSyncMessages();

    return () => {
      window.removeEventListener('online', handleOnline);
      window.removeEventListener('offline', handleOffline);
      cleanupSync();
    };
  }, []);

  if (isOnline) {
    return null;
  }

  return (
    <div className="alert-warning border-b border-[var(--status-warning-border)] px-4 py-2 text-center text-sm font-medium">
      Connection lost. Report drafts and selected uploads are saving locally.
    </div>
  );
}
