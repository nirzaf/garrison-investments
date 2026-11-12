import { useEffect, useRef, useState } from 'react';
import { flushPhotoQueue, listenForSyncMessages } from '../../api/offlineQueue';

export function OfflineIndicator() {
  const [isConnected, setIsConnected] = useState(() => navigator.onLine);
  const [reason, setReason] = useState<'offline' | 'server'>(() =>
    navigator.onLine ? 'server' : 'offline'
  );
  const failuresRef = useRef(0);
  const connectedRef = useRef(isConnected);
  connectedRef.current = isConnected;

  useEffect(() => {
    const setConnected = (connected: boolean, nextReason?: 'offline' | 'server') => {
      if (connected === connectedRef.current) {
        if (!connected && nextReason) setReason(nextReason);
        return;
      }
      setIsConnected(connected);
      if (!connected) {
        if (nextReason) setReason(nextReason);
        return;
      }
      void flushPhotoQueue().catch(() => {});
    };

    const probeHealth = async () => {
      const controller = new AbortController();
      const timeout = window.setTimeout(() => controller.abort(), 3_000);
      try {
        const response = await fetch('/health', {
          method: 'GET',
          cache: 'no-store',
          signal: controller.signal
        });
        failuresRef.current = 0;
        if (response.ok) {
          setConnected(true);
        } else {
          setConnected(navigator.onLine);
        }
      } catch {
        failuresRef.current += 1;
        if (failuresRef.current >= 2) {
          setConnected(false, navigator.onLine ? 'server' : 'offline');
        }
      } finally {
        window.clearTimeout(timeout);
      }
    };

    const handleOnline = () => {
      failuresRef.current = 0;
      setConnected(true);
      void probeHealth();
    };
    const handleOffline = () => setConnected(false, 'offline');

    window.addEventListener('online', handleOnline);
    window.addEventListener('offline', handleOffline);

    const cleanupSync = listenForSyncMessages();
    if (navigator.onLine) void flushPhotoQueue().catch(() => {});
    void probeHealth();
    const interval = window.setInterval(() => void probeHealth(), 15_000);

    const handleVisibility = () => {
      if (document.visibilityState === 'visible') {
        void probeHealth();
      }
    };
    document.addEventListener('visibilitychange', handleVisibility);

    return () => {
      window.removeEventListener('online', handleOnline);
      window.removeEventListener('offline', handleOffline);
      cleanupSync();
      window.clearInterval(interval);
      document.removeEventListener('visibilitychange', handleVisibility);
    };
  }, []);

  if (isConnected) {
    return null;
  }

  const message =
    reason === 'offline'
      ? 'Connection lost. Some drafts and selected uploads may be saved locally.'
      : 'Server unreachable. Some drafts and selected uploads may be saved locally.';

  return (
    <div className="alert-warning border-b border-[var(--status-warning-border)] px-4 py-2 text-center text-sm font-medium">
      {message}
    </div>
  );
}
