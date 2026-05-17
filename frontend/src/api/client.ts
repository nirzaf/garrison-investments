import axios, { type AxiosRequestConfig } from 'axios';
import axiosRetry from 'axios-retry';

let accessToken: string | null = null;
let refreshPromise: Promise<string> | null = null;

type RetriableRequestConfig = AxiosRequestConfig & {
  _retry?: boolean;
  headers: NonNullable<AxiosRequestConfig['headers']>;
};

export const apiClient = axios.create({
  baseURL: import.meta.env.VITE_API_BASE_URL ?? '/api/v1',
  withCredentials: true,
  timeout: 15_000,
  headers: {
    'Content-Type': 'application/json'
  }
});

axiosRetry(apiClient, {
  retries: 3,
  retryDelay: axiosRetry.exponentialDelay,
  retryCondition: (error) => {
    return axiosRetry.isNetworkOrIdempotentRequestError(error) || error.code === 'ECONNABORTED';
  }
});

apiClient.interceptors.request.use((config) => {
  if (accessToken) {
    config.headers.Authorization = `Bearer ${accessToken}`;
  }
  return config;
});

apiClient.interceptors.response.use(undefined, async (error) => {
  const original = error.config as RetriableRequestConfig | undefined;
  const status = error.response?.status;
  const url = original?.url ?? '';

  if (!original || status !== 401 || original._retry || url.endsWith('/auth/refresh')) {
    return Promise.reject(error);
  }

  original._retry = true;
  original.headers ??= {};
  refreshPromise ??= apiClient
    .post<{ access_token: string }>('/auth/refresh')
    .then((response) => {
      setAccessToken(response.data.access_token);
      return response.data.access_token;
    })
    .finally(() => {
      refreshPromise = null;
    });

  const token = await refreshPromise;
  original.headers.Authorization = `Bearer ${token}`;
  return apiClient(original);
});

export function setAccessToken(token: string | null) {
  accessToken = token;
}
