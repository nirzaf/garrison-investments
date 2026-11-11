import { AxiosError, type AxiosResponse, type InternalAxiosRequestConfig } from 'axios';
import { afterEach, describe, expect, it, vi } from 'vitest';

import { apiClient, setAccessToken } from './client';

const originalAdapter = apiClient.defaults.adapter;

function response(
  config: InternalAxiosRequestConfig,
  status: number,
  data: unknown
): AxiosResponse {
  return { config, status, statusText: String(status), headers: {}, data };
}

function unauthorized(config: InternalAxiosRequestConfig, errorCode: string): never {
  throw new AxiosError(
    'Unauthorized',
    AxiosError.ERR_BAD_REQUEST,
    config,
    undefined,
    response(config, 401, { error_code: errorCode })
  );
}

afterEach(() => {
  apiClient.defaults.adapter = originalAdapter;
  setAccessToken(null);
});

describe('API client authentication and retries', () => {
  it.each([
    ['/auth/login', 'LOGIN_FAILED'],
    ['/auth/verify-otp', 'OTP_FAILED'],
    ['/auth/password-reset/confirm', 'PASSWORD_RESET_FAILED']
  ])('preserves the %s error without refreshing the session', async (path, code) => {
    const adapter = vi.fn(async (config: InternalAxiosRequestConfig) =>
      unauthorized(config, config.url === path ? code : 'REFRESH_FAILED')
    );
    apiClient.defaults.adapter = adapter;

    await expect(apiClient.post(path)).rejects.toMatchObject({
      response: { status: 401, data: { error_code: code } }
    });
    expect(adapter.mock.calls.map(([config]) => config.url)).toEqual([path]);
  });

  it('refreshes once for simultaneous expired protected requests and retries with the new token', async () => {
    setAccessToken('expired');
    const adapter = vi.fn(async (config: InternalAxiosRequestConfig) => {
      if (config.url === '/auth/refresh') {
        return response(config, 200, { access_token: 'renewed' });
      }
      if (config.headers.Authorization !== 'Bearer renewed') unauthorized(config, 'EXPIRED');
      return response(config, 200, config.url);
    });
    apiClient.defaults.adapter = adapter;

    const results = await Promise.all([apiClient.get('/reports'), apiClient.get('/projects')]);
    expect(results.map(({ data }) => data)).toEqual(['/reports', '/projects']);
    const paths = adapter.mock.calls.map(([config]) => config.url);
    expect(paths.filter((path) => path === '/auth/refresh')).toHaveLength(1);
    expect(paths.filter((path) => path === '/reports')).toHaveLength(2);
    expect(paths.filter((path) => path === '/projects')).toHaveLength(2);
  });

  it('does not retry a payment write when the server response is lost', async () => {
    const adapter = vi.fn(async (config: InternalAxiosRequestConfig) => {
      throw new AxiosError('Connection lost', AxiosError.ERR_NETWORK, config);
    });
    apiClient.defaults.adapter = adapter;

    await expect(apiClient.post('/finance/invoices/test/payments')).rejects.toMatchObject({
      code: AxiosError.ERR_NETWORK
    });
    expect(adapter).toHaveBeenCalledTimes(1);
  });
});
