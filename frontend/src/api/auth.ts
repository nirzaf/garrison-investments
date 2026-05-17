import { apiClient } from './client';
import type { components } from './schema';

export type AuthUser = components['schemas']['AuthUserResponse'];

export type LoginChallenge = components['schemas']['LoginChallengeResponse'];

export type TokenResponse = components['schemas']['TokenResponse'];

export type PasswordResetChallenge = components['schemas']['PasswordResetChallengeResponse'];

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
