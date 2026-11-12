import { useQueryClient } from '@tanstack/react-query';
import { useCallback, useEffect, useMemo, useState, type ReactNode } from 'react';

import {
  changePassword as changePasswordRequest,
  login as loginRequest,
  logout as logoutRequest,
  refreshSession,
  verifyOtp as verifyOtpRequest,
  type AuthUser
} from '../api/auth';
import {
  clearBrowserSession,
  getBrowserSession,
  isActiveOfflineScope,
  listenForSessionChanges,
  notifySessionChange,
  OFFLINE_NAMESPACE,
  onBrowserSessionCleared,
  startBrowserSession,
  withSessionLock
} from '../api/browserSession';
import { readOfflineSession, writeOfflineSession, type OfflineSession } from '../api/offlineDb';
import { AuthContext, type AuthContextValue, type LoginResult } from './auth-context';

const refreshRetryDelaysMs = [300, 900];

function delay(ms: number): Promise<void> {
  return new Promise((resolve) => {
    window.setTimeout(resolve, ms);
  });
}

function getResponseStatus(error: unknown): number | undefined {
  if (typeof error !== 'object' || error === null || !('response' in error)) {
    return undefined;
  }
  return (error as { response?: { status?: number } }).response?.status;
}

async function refreshSessionWithRetry() {
  for (let attempt = 0; attempt < 3; attempt += 1) {
    try {
      return await refreshSession();
    } catch (error) {
      const status = getResponseStatus(error);
      const isTerminalAuthFailure = status === 401 || status === 403;
      const isNonRetryableClientFailure = status !== undefined && status < 500;
      const hasAttemptsRemaining = attempt < refreshRetryDelaysMs.length;
      if (isTerminalAuthFailure || isNonRetryableClientFailure || !hasAttemptsRemaining) {
        throw error;
      }
      await delay(refreshRetryDelaysMs[attempt]);
    }
  }
  throw new Error('Session refresh failed');
}

export function AuthProvider({ children }: { children: ReactNode }) {
  const [user, setUser] = useState<AuthUser | null>(null);
  const [isLoading, setIsLoading] = useState(true);
  const queryClient = useQueryClient();

  const resetSessionView = useCallback(() => {
    void queryClient.cancelQueries();
    queryClient.clear();
    setUser(null);
  }, [queryClient]);

  useEffect(() => {
    let active = true;
    const unsubscribe = onBrowserSessionCleared(resetSessionView);
    const stopListening = listenForSessionChanges();
    void withSessionLock(async () => {
      const previous = await readOfflineSession(OFFLINE_NAMESPACE);
      if (!active || previous?.state === 'signed-out') return;
      const restored = await refreshSessionWithRetry();
      if (!active) return;
      const sameOwner = previous?.state === 'active' && previous.ownerUserId === restored.user.id;
      const scope: OfflineSession = sameOwner
        ? previous
        : {
            namespace: OFFLINE_NAMESPACE,
            ownerUserId: restored.user.id,
            generation: crypto.randomUUID(),
            state: 'active'
          };
      if (!sameOwner) {
        const applied = await writeOfflineSession(scope, previous?.generation ?? null);
        if (!applied || !active) return;
        notifySessionChange();
      } else if (!(await isActiveOfflineScope(scope))) {
        return;
      }
      if (!active) return;
      startBrowserSession(scope, restored.access_token);
      setUser(restored.user);
    })
      .catch(() => {
        if (active) clearBrowserSession();
      })
      .finally(() => {
        if (active) setIsLoading(false);
      });

    return () => {
      active = false;
      stopListening();
      unsubscribe();
    };
  }, [resetSessionView]);

  const login = useCallback(async (email: string, password: string): Promise<LoginResult> => {
    const challenge = await loginRequest(email, password);
    return {
      challengeId: challenge.challenge_id,
      expiresAt: challenge.expires_at,
      devOtp: challenge.dev_otp
    };
  }, []);

  const verifyOtp = useCallback(
    async (challengeId: string, otp: string): Promise<void> => {
      await withSessionLock(async () => {
        const verified = await verifyOtpRequest(challengeId, otp);
        const scope: OfflineSession = {
          namespace: OFFLINE_NAMESPACE,
          ownerUserId: verified.user.id,
          generation: crypto.randomUUID(),
          state: 'active'
        };
        await writeOfflineSession(scope);
        clearBrowserSession();
        resetSessionView();
        startBrowserSession(scope, verified.access_token);
        setUser(verified.user);
        notifySessionChange();
      });
    },
    [resetSessionView]
  );

  const changePassword = useCallback(
    async (currentPassword: string, newPassword: string): Promise<void> => {
      await changePasswordRequest(currentPassword, newPassword);
      setUser((current) => (current ? { ...current, must_change_password: false } : current));
    },
    []
  );

  const logout = useCallback(async (): Promise<void> => {
    const departing = getBrowserSession();
    if (
      !departing ||
      !window.confirm(
        'Sign out and clear this account’s local drafts and queued uploads? Unsynced work will be lost.'
      )
    )
      return;

    departing.controller.abort();
    const signedOut: OfflineSession = {
      ...departing.scope,
      generation: crypto.randomUUID(),
      state: 'signed-out'
    };
    const applied = await writeOfflineSession(
      signedOut,
      departing.scope.generation,
      departing.scope
    );
    clearBrowserSession(departing);
    if (!applied) return;
    notifySessionChange();
    await withSessionLock(async () => {
      const current = await readOfflineSession(OFFLINE_NAMESPACE);
      if (current?.generation === signedOut.generation) {
        // Network failure cannot undo local sign-out or permit automatic cookie refresh.
        await logoutRequest().catch(() => {});
      }
    });
  }, []);

  const value = useMemo<AuthContextValue>(
    () => ({
      user,
      isAuthenticated: Boolean(user),
      isLoading,
      login,
      verifyOtp,
      changePassword,
      logout
    }),
    [changePassword, isLoading, login, logout, user, verifyOtp]
  );

  return (
    <AuthContext.Provider key={getBrowserSession()?.scope.generation ?? 'signed-out'} value={value}>
      {children}
    </AuthContext.Provider>
  );
}
