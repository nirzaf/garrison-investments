import { apiClient } from './client';

export type AuthUser = {
  id: string;
  email: string;
  full_name: string;
  role: string;
  is_active: boolean;
  must_change_password: boolean;
  permissions: string[];
};

export type LoginChallenge = {
  challenge_id: string;
  expires_at: string;
  expires_in_seconds: number;
  dev_otp?: string | null;
};

export type TokenResponse = {
  access_token: string;
  token_type: 'bearer';
  expires_in_seconds: number;
  user: AuthUser;
};

export type PasswordResetChallenge = {
  challenge_id?: string | null;
  expires_at?: string | null;
  expires_in_seconds?: number | null;
  dev_otp?: string | null;
  message: string;
};

export async function login(email: string, password: string): Promise<LoginChallenge> {
  const response = await apiClient.post<LoginChallenge>('/auth/login', { email, password });
  return response.data;
}

export async function verifyOtp(challengeId: string, otp: string): Promise<TokenResponse> {
  const response = await apiClient.post<TokenResponse>('/auth/verify-otp', {
    challenge_id: challengeId,
    otp
  });
  return response.data;
}

export async function refreshSession(): Promise<TokenResponse> {
  const response = await apiClient.post<TokenResponse>('/auth/refresh');
  return response.data;
}

export async function logout(): Promise<void> {
  await apiClient.post('/auth/logout');
}

export async function getMe(): Promise<AuthUser> {
  const response = await apiClient.get<AuthUser>('/auth/me');
  return response.data;
}

export async function changePassword(currentPassword: string, newPassword: string): Promise<void> {
  await apiClient.post('/auth/change-password', {
    current_password: currentPassword,
    new_password: newPassword
  });
}

export async function requestPasswordReset(email: string): Promise<PasswordResetChallenge> {
  const response = await apiClient.post<PasswordResetChallenge>('/auth/password-reset/request', {
    email
  });
  return response.data;
}

export async function confirmPasswordReset(
  challengeId: string,
  otp: string,
  newPassword: string
): Promise<void> {
  await apiClient.post('/auth/password-reset/confirm', {
    challenge_id: challengeId,
    otp,
    new_password: newPassword
  });
}
