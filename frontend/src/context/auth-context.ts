import { createContext } from 'react';

import type { AuthUser } from '../api/auth';
export type { AuthUser } from '../api/auth';

export type LoginChallengeState = {
  challengeId: string;
  expiresAt: string;
  devOtp?: string | null;
};

export type LoginResult = LoginChallengeState;

export type AuthContextValue = {
  user: AuthUser | null;
  isAuthenticated: boolean;
  isLoading: boolean;
  login: (email: string, password: string) => Promise<LoginResult>;
  verifyOtp: (challengeId: string, otp: string) => Promise<void>;
  logout: () => Promise<void>;
};

export const AuthContext = createContext<AuthContextValue | undefined>(undefined);
