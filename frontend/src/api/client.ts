import axios, {
  CanceledError,
  type AxiosRequestConfig,
  type InternalAxiosRequestConfig
} from 'axios';
import axiosRetry from 'axios-retry';
import {
  API_BASE,
  getBrowserSession,
  isActiveOfflineScope,
  suspendBrowserSession,
  withSessionLock
} from './browserSession';
import { sameScope, type OfflineScope } from './offlineDb';
import type { components } from './schema';

type RefreshResponse = components['schemas']['RefreshResponse'];
type BrowserRequest = InternalAxiosRequestConfig & {
  _sessionScope?: OfflineScope;
  _retried?: boolean;
};

export function sessionRequestConfig(scope?: OfflineScope): AxiosRequestConfig {
  return { _sessionScope: scope } as AxiosRequestConfig;
}

const SAFE_RETRY_METHODS = new Set(['get', 'head', 'options']);
const NO_SESSION_REFRESH_PATHS = [
  '/auth/login',
  '/auth/verify-otp',
  '/auth/refresh',
  '/auth/logout',
  '/auth/password-reset/request',
  '/auth/password-reset/confirm'
];
export const EXPORT_TIMEOUT_MS = 180_000;

function isSessionRequest(config: BrowserRequest): boolean {
  return NO_SESSION_REFRESH_PATHS.some((path) => config.url?.endsWith(path));
}

export const apiClient = axios.create({
  baseURL: API_BASE,
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
    if (!SAFE_RETRY_METHODS.has(method) || axios.isCancel(error)) return false;
    return (
      axiosRetry.isRetryableError(error) ||
      axiosRetry.isNetworkError(error) ||
      error.code === 'ECONNABORTED'
    );
  }
});

apiClient.interceptors.request.use(
  (config: BrowserRequest) => {
    if (isSessionRequest(config)) return config;
    const session = getBrowserSession();
    if (config._sessionScope && (!session || !sameScope(session.scope, config._sessionScope))) {
      throw new CanceledError('The portal session changed.');
    }
    if (session) {
      config._sessionScope = session.scope;
      config.signal = session.controller.signal;
      config.headers.Authorization = `Bearer ${session.accessToken}`;
    }
    return config;
  },
  (error: unknown) => {
    throw error;
  },
  { synchronous: true }
);

let pendingRefresh: { scope: OfflineScope; result: Promise<void> } | null = null;

apiClient.interceptors.response.use(
  (response) => {
    const scope = (response.config as BrowserRequest)._sessionScope;
    if (scope && !sameScope(getBrowserSession()?.scope, scope)) {
      throw new CanceledError('The portal session changed.');
    }
    return response;
  },
  async (error) => {
    const config = error.config as BrowserRequest | undefined;
    const current = getBrowserSession();
    if (
      !config?._sessionScope ||
      !current ||
      !sameScope(current.scope, config._sessionScope) ||
      error.response?.status !== 401 ||
      config._retried ||
      isSessionRequest(config)
    ) {
      throw error;
    }
    config._retried = true;

    if (!pendingRefresh || !sameScope(pendingRefresh.scope, current.scope)) {
      const result = withSessionLock(async () => {
        if (
          current.controller.signal.aborted ||
          getBrowserSession() !== current ||
          !(await isActiveOfflineScope(current.scope))
        ) {
          throw new CanceledError('The portal session changed.');
        }
        let refreshed: RefreshResponse;
        try {
          refreshed = (await apiClient.post<RefreshResponse>('/auth/refresh')).data;
        } catch (refreshError) {
          const status = axios.isAxiosError(refreshError)
            ? refreshError.response?.status
            : undefined;
          if (!current.controller.signal.aborted && (status === 401 || status === 403)) {
            await suspendBrowserSession(current);
          }
          throw refreshError;
        }
        if (!current.controller.signal.aborted && refreshed.user.id !== current.scope.ownerUserId) {
          await suspendBrowserSession(current);
          throw new CanceledError('The portal session changed.');
        }
        if (
          current.controller.signal.aborted ||
          getBrowserSession() !== current ||
          !(await isActiveOfflineScope(current.scope))
        ) {
          throw new CanceledError('The portal session changed.');
        }
        current.accessToken = refreshed.access_token;
      });
      pendingRefresh = { scope: current.scope, result };
      void result
        .finally(() => {
          if (pendingRefresh?.result === result) pendingRefresh = null;
        })
        .catch(() => {});
    }
    await pendingRefresh.result;
    return apiClient(config);
  }
);
