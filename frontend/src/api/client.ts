import axios, { type AxiosRequestConfig } from 'axios';
import axiosRetry from 'axios-retry';

let accessToken: string | null = null;
let refreshPromise: Promise<string> | null = null;
const SAFE_RETRY_METHODS = new Set(['get', 'head', 'options']);
const NO_SESSION_REFRESH_PATHS = [
  '/auth/login',
  '/auth/verify-otp',
  '/auth/refresh',
  '/auth/password-reset/confirm'
];
/** Shared with `public/sw.js` so the app and the service worker cannot refresh at once. */
export const TOKEN_REFRESH_LOCK = 'garrison-token-refresh';
export const EXPORT_TIMEOUT_MS = 180_000;

/**
 * M3: the in-tab singleton below only serialises one tab. Refresh tokens rotate, so two
 * tabs refreshing together can invalidate each other's session. The Web Locks API gives
 * us cross-tab exclusion in secure contexts; elsewhere we fall back to the singleton.
 */
async function withTokenRefreshLock<T>(operation: () => Promise<T>): Promise<T> {
  const locks = typeof navigator === 'undefined' ? undefined : navigator.locks;
  if (!locks) return operation();
  // `await` flattens the LockManager's Promise<Promise<T>> back to T.
  return await locks.request(TOKEN_REFRESH_LOCK, operation);
}

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
    const method = error.config?.method?.toLowerCase() ?? 'get';
    if (!SAFE_RETRY_METHODS.has(method)) {
      return false;
    }
    return (
      axiosRetry.isRetryableError(error) ||
      axiosRetry.isNetworkError(error) ||
      error.code === 'ECONNABORTED'
    );
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

  if (
    !original ||
    status !== 401 ||
    original._retry ||
    NO_SESSION_REFRESH_PATHS.some((path) => url.endsWith(path))
  ) {
    return Promise.reject(error);
  }

  original._retry = true;
  original.headers ??= {};
  refreshPromise ??= withTokenRefreshLock(() =>
    apiClient.post<{ access_token: string }>('/auth/refresh').then((response) => {
      setAccessToken(response.data.access_token);
      return response.data.access_token;
    })
  )
    .catch((error) => {
      setAccessToken(null);
      return Promise.reject(error);
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
