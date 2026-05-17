import { useCallback, useEffect, useMemo, useState, type ReactNode } from 'react';

import {
  changePassword as changePasswordRequest,
  login as loginRequest,
  logout as logoutRequest,
  refreshSession,
  verifyOtp as verifyOtpRequest,
  type AuthUser
} from '../api/auth';
import { setAccessToken } from '../api/client';
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

  useEffect(() => {
    let active = true;
    refreshSessionWithRetry()
      .then((session) => {
        if (!active) return;
        setAccessToken(session.access_token);
        setUser(session.user);
      })
      .catch(() => {
        if (!active) return;
        setAccessToken(null);
        setUser(null);
      })
      .finally(() => {
        if (active) {
          setIsLoading(false);
        }
      });
    return () => {
      active = false;
    };
  }, []);

  const login = useCallback(async (email: string, password: string): Promise<LoginResult> => {
    const challenge = await loginRequest(email, password);
    return {
      challengeId: challenge.challenge_id,
      expiresAt: challenge.expires_at,
      devOtp: challenge.dev_otp
    };
  }, []);

  const verifyOtp = useCallback(async (challengeId: string, otp: string): Promise<void> => {
    const session = await verifyOtpRequest(challengeId, otp);
    setAccessToken(session.access_token);
    setUser(session.user);
  }, []);

  const changePassword = useCallback(
    async (currentPassword: string, newPassword: string): Promise<void> => {
      await changePasswordRequest(currentPassword, newPassword);
      setUser((current) => (current ? { ...current, must_change_password: false } : current));
    },
    []
  );

  const logout = useCallback(async (): Promise<void> => {
    await logoutRequest();
    setAccessToken(null);
    setUser(null);
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

  return <AuthContext.Provider value={value}>{children}</AuthContext.Provider>;
}
