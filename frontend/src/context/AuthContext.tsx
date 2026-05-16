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

export function AuthProvider({ children }: { children: ReactNode }) {
  const [user, setUser] = useState<AuthUser | null>(null);
  const [isLoading, setIsLoading] = useState(true);

  useEffect(() => {
    let active = true;
    refreshSession()
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
