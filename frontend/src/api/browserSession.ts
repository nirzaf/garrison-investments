import { readOfflineSession, sameScope, writeOfflineSession, type OfflineScope } from './offlineDb';

export const API_BASE = import.meta.env.VITE_API_BASE_URL ?? '/api/v1';
const appOrigin = typeof window === 'undefined' ? 'http://localhost' : window.location.origin;
const apiUrl = new URL(API_BASE, appOrigin);
export const OFFLINE_NAMESPACE = JSON.stringify([appOrigin, apiUrl.href.replace(/\/+$/, '')]);
export const TOKEN_REFRESH_LOCK = 'garrison-token-refresh';
const SESSION_EVENT = 'garrisons-offline-session';
const SESSION_STORAGE_KEY = `${SESSION_EVENT}:${OFFLINE_NAMESPACE}`;

type BrowserSession = {
  scope: OfflineScope;
  accessToken: string;
  controller: AbortController;
};

let session: BrowserSession | null = null;
const listeners = new Set<() => void>();
let localLock: Promise<unknown> = Promise.resolve();

export function getBrowserSession(): BrowserSession | null {
  return session;
}

export function startBrowserSession(scope: OfflineScope, accessToken: string): void {
  if (session && sameScope(session.scope, scope)) {
    session.accessToken = accessToken;
    return;
  }
  session?.controller.abort();
  session = { scope, accessToken, controller: new AbortController() };
}

export function clearBrowserSession(expected?: BrowserSession): void {
  if (!session || (expected && expected !== session)) return;
  session.controller.abort();
  session = null;
  listeners.forEach((listener) => listener());
}

export function onBrowserSessionCleared(listener: () => void): () => void {
  listeners.add(listener);
  return () => {
    listeners.delete(listener);
  };
}

export function notifySessionChange(): void {
  // Storage events cover tabs without BroadcastChannel. The durable fence remains in IndexedDB.
  try {
    localStorage.setItem(SESSION_STORAGE_KEY, crypto.randomUUID());
  } catch {
    // Storage may be blocked. Before touching the queue, each context checks IndexedDB directly.
  }
  if ('BroadcastChannel' in window) {
    const channel = new BroadcastChannel(SESSION_STORAGE_KEY);
    channel.postMessage(SESSION_EVENT);
    channel.close();
  }
  navigator.serviceWorker?.controller?.postMessage({ type: SESSION_EVENT });
}

export function listenForSessionChanges(): () => void {
  const check = () => {
    const current = session;
    if (!current) return;
    void isActiveOfflineScope(current.scope).then((active) => {
      if (!active) clearBrowserSession(current);
    });
  };
  const storage = (event: StorageEvent) => {
    if (event.key === SESSION_STORAGE_KEY) check();
  };
  const workerMessage = (event: MessageEvent) => {
    if (event.data?.type === SESSION_EVENT) check();
  };
  const channel =
    'BroadcastChannel' in window ? new BroadcastChannel(SESSION_STORAGE_KEY) : undefined;
  channel?.addEventListener('message', check);
  window.addEventListener('storage', storage);
  window.addEventListener('focus', check);
  navigator.serviceWorker?.addEventListener('message', workerMessage);
  return () => {
    channel?.close();
    window.removeEventListener('storage', storage);
    window.removeEventListener('focus', check);
    navigator.serviceWorker?.removeEventListener('message', workerMessage);
  };
}

export async function isActiveOfflineScope(scope: OfflineScope): Promise<boolean> {
  try {
    const state = await readOfflineSession(scope.namespace);
    return state?.state === 'active' && sameScope(state, scope);
  } catch {
    return false;
  }
}

export async function suspendBrowserSession(current: BrowserSession): Promise<void> {
  clearBrowserSession(current);
  try {
    const changed = await writeOfflineSession(
      { ...current.scope, state: 'suspended', generation: crypto.randomUUID() },
      current.scope.generation
    );
    if (changed) notifySessionChange();
  } catch {
    // The tab is already invalidated, and the worker must obtain a verified session to write.
  }
}

export async function withSessionLock<T>(action: () => Promise<T>): Promise<T> {
  if (navigator.locks) return await navigator.locks.request(TOKEN_REFRESH_LOCK, action);
  const pending = localLock.then(action);
  localLock = pending.catch(() => {});
  return pending;
}
