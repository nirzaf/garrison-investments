import { persistOwnedDraft } from './report-draft-sync.js';
import {
  classifyQueuedReportFile,
  commitUploadReceipt,
  uploadFailure,
  uploadRetry
} from './report-file-sync.js';

// The standalone drain uses the same owner, generation and claim checks as offlineQueue.ts.
const CACHE_NAME = 'garrisons-app-shell-v4';
const LEGACY_CACHES = new Set([
  'garrisons-app-shell-v1',
  'garrisons-app-shell-v2',
  'garrisons-app-shell-v3'
]);
const DB_NAME = 'garrisons-offline';
const DB_VERSION = 3;
const REPORT_DRAFTS = 'ownedReportDrafts';
const PHOTO_QUEUE = 'ownedPhotoQueue';
const SUPERVISOR_DRAFTS = 'ownedSupervisorDrafts';
const SESSION_STORE = 'offlineSessions';
const OWNER_INDEX = 'byOwner';
const API_BASE = '/api/v1';
const NAMESPACE = JSON.stringify([
  self.location.origin,
  new URL(API_BASE, self.location.origin).href
]);
const TOKEN_REFRESH_LOCK = 'garrison-token-refresh';
const SESSION_EVENT = 'garrisons-offline-session';
const STALE_CLAIM_MS = 5 * 60_000;
const APP_SHELL = [
  '/',
  '/manifest.json',
  '/report-draft-sync.js',
  '/report-file-sync.js',
  '/brand/apple-touch-icon.png',
  '/brand/icon-192.png',
  '/brand/icon-512.png',
  '/brand/logo-full.jpg',
  '/brand/logo-mark.png'
];

self.addEventListener('install', (event) => {
  event.waitUntil(
    (async () => {
      const cache = await caches.open(CACHE_NAME);
      await cache.addAll(
        APP_SHELL.map((path) => new Request(path, { credentials: 'omit', cache: 'reload' }))
      );
      await self.skipWaiting();
    })()
  );
});

self.addEventListener('activate', (event) => {
  event.waitUntil(
    (async () => {
      const keys = await caches.keys();
      await Promise.all(
        keys.filter((key) => LEGACY_CACHES.has(key)).map((key) => caches.delete(key))
      );
      try {
        // Close the v1 write path before accepting sync. Ownerless rows remain quarantined.
        const db = await openOfflineDb();
        db.close();
      } catch {
        // If an older tab blocks the upgrade, all new offline transactions fail closed.
      }
      await self.clients.claim();
    })()
  );
});

self.addEventListener('fetch', (event) => {
  const request = event.request;
  const url = new URL(request.url);
  if (
    request.method !== 'GET' ||
    url.origin !== self.location.origin ||
    request.headers.has('Authorization') ||
    url.pathname.startsWith('/api/') ||
    url.pathname.startsWith('/portal-files/')
  )
    return;

  if (request.mode === 'navigate') {
    event.respondWith(fetch(request).catch(async () => (await caches.open(CACHE_NAME)).match('/')));
    return;
  }

  if (
    !url.search &&
    url.pathname.startsWith('/assets/') &&
    (request.destination === 'script' || request.destination === 'style')
  ) {
    event.respondWith(
      (async () => {
        const cache = await caches.open(CACHE_NAME);
        const cached = await cache.match(request);
        if (cached) return cached;
        const response = await fetch(new Request(request, { credentials: 'omit' }));
        if (
          response.ok &&
          !response.redirected &&
          !/\b(private|no-store)\b/i.test(response.headers.get('cache-control') ?? '')
        ) {
          await cache.put(request, response.clone());
        }
        return response;
      })()
    );
    return;
  }

  if (!url.search && APP_SHELL.includes(url.pathname)) {
    event.respondWith(
      (async () => {
        const cache = await caches.open(CACHE_NAME);
        return (await cache.match(request)) ?? fetch(request);
      })()
    );
  }
});

function openOfflineDb() {
  return new Promise((resolve, reject) => {
    const request = indexedDB.open(DB_NAME, DB_VERSION);
    request.onupgradeneeded = (event) => {
      if (event.oldVersion >= 2) return;
      const db = request.result;
      db.createObjectStore(REPORT_DRAFTS, {
        keyPath: ['namespace', 'ownerUserId', 'localDraftId']
      }).createIndex(OWNER_INDEX, ['namespace', 'ownerUserId']);
      const queue = db.createObjectStore(PHOTO_QUEUE, { keyPath: 'id' });
      queue.createIndex(OWNER_INDEX, ['namespace', 'ownerUserId']);
      queue.createIndex('byOwnerDraft', ['namespace', 'ownerUserId', 'localDraftId']);
      db.createObjectStore(SUPERVISOR_DRAFTS, {
        keyPath: ['namespace', 'ownerUserId', 'localDraftId']
      });
      db.createObjectStore(SESSION_STORE, { keyPath: 'namespace' });
    };
    let blocked = false;
    request.onblocked = () => {
      blocked = true;
      reject(new Error('Offline storage upgrade is blocked.'));
    };
    request.onsuccess = () => {
      const db = request.result;
      db.onversionchange = () => db.close();
      if (blocked) db.close();
      else resolve(db);
    };
    request.onerror = () => reject(request.error);
  });
}

function sameScope(left, right) {
  return (
    left?.state === 'active' &&
    left.namespace === right.namespace &&
    left.ownerUserId === right.ownerUserId &&
    left.generation === right.generation
  );
}

async function transaction(stores, mode, operation) {
  const db = await openOfflineDb();
  return new Promise((resolve, reject) => {
    const tx = db.transaction(stores, mode);
    let result;
    tx.oncomplete = () => {
      db.close();
      resolve(result);
    };
    tx.onabort = () => {
      db.close();
      reject(tx.error ?? new Error('Offline storage transaction aborted.'));
    };
    operation(tx, (value) => {
      result = value;
    });
  });
}

function readSession() {
  return transaction([SESSION_STORE], 'readonly', (tx, result) => {
    const request = tx.objectStore(SESSION_STORE).get(NAMESPACE);
    request.onsuccess = () => result(request.result);
  });
}

function withOwnedTransaction(scope, stores, mode, operation) {
  return transaction([SESSION_STORE, ...stores], mode, (tx, result) => {
    const request = tx.objectStore(SESSION_STORE).get(scope.namespace);
    request.onsuccess = () => {
      if (sameScope(request.result, scope)) operation(tx, result);
    };
  });
}

function withOwnedStore(scope, store, mode, operation) {
  return withOwnedTransaction(scope, [store], mode, (tx, result) =>
    operation(tx.objectStore(store), result)
  );
}

function withOwnedQueue(scope, mode, operation) {
  return withOwnedStore(scope, PHOTO_QUEUE, mode, operation);
}

function initializeDraft(draft) {
  return {
    ...draft,
    localRevision: draft.localRevision ?? 1,
    lastSyncedLocalRevision: draft.lastSyncedLocalRevision ?? 0,
    syncState: draft.syncState ?? 'local',
    attempts: draft.attempts ?? 0,
    retryAfter: draft.retryAfter ?? 0
  };
}

function editReportDraft(scope, localDraftId, edit) {
  return withOwnedStore(scope, REPORT_DRAFTS, 'readwrite', (drafts, result) => {
    const request = drafts.get([scope.namespace, scope.ownerUserId, localDraftId]);
    request.onsuccess = () => {
      const updated = request.result && edit(initializeDraft(request.result));
      if (!updated) return;
      drafts.put(updated);
      result(updated);
    };
  });
}

function readReportDraft(scope, localDraftId) {
  return withOwnedStore(scope, REPORT_DRAFTS, 'readonly', (drafts, result) => {
    const request = drafts.get([scope.namespace, scope.ownerUserId, localDraftId]);
    request.onsuccess = () => {
      if (request.result) result(initializeDraft(request.result));
    };
  });
}

function isBlocked(item) {
  return item.status === 'blocked' || item.status === 'server_newer';
}

async function listQueuedPhotos(scope, localDraftId) {
  return (
    (await withOwnedQueue(scope, 'readonly', (queue, result) => {
      const request = localDraftId
        ? queue.index('byOwnerDraft').getAll([scope.namespace, scope.ownerUserId, localDraftId])
        : queue.index(OWNER_INDEX).getAll([scope.namespace, scope.ownerUserId]);
      request.onsuccess = () => result(request.result);
    })) ?? []
  );
}

function claimQueuedPhoto(scope, id, hasLock) {
  return withOwnedQueue(scope, 'readwrite', (queue, result) => {
    const request = queue.get(id);
    request.onsuccess = () => {
      const item = request.result;
      if (
        !item ||
        item.ownerUserId !== scope.ownerUserId ||
        item.namespace !== scope.namespace ||
        isBlocked(item) ||
        item.status === 'synced' ||
        (item.status === 'suspended' && item.claimGeneration === scope.generation) ||
        (item.retryAfter ?? 0) > Date.now()
      )
        return;
      if (
        !hasLock &&
        item.status === 'syncing' &&
        item.claimGeneration === scope.generation &&
        Date.now() - Date.parse(item.claimedAt) < STALE_CLAIM_MS
      )
        return;
      const claimed = {
        ...item,
        status: 'syncing',
        claimedAt: new Date().toISOString(),
        claimId: crypto.randomUUID(),
        claimGeneration: scope.generation
      };
      queue.put(claimed);
      result(claimed);
    };
  });
}

function patchClaim(scope, claim, patch) {
  return withOwnedQueue(scope, 'readwrite', (queue, result) => {
    const request = queue.get(claim.id);
    request.onsuccess = () => {
      const current = request.result;
      if (
        current?.claimId !== claim.claimId ||
        current?.ownerUserId !== scope.ownerUserId ||
        current.namespace !== scope.namespace
      )
        return;
      const updated = { ...current, ...patch, intent: current.intent ?? patch.intent };
      queue.put(updated);
      result(updated);
    };
  });
}

async function refreshAccessToken(scope, signal) {
  const perform = async () => {
    if (signal.aborted || !sameScope(await readSession(), scope)) return;
    const response = await fetch(`${API_BASE}/auth/refresh`, {
      method: 'POST',
      credentials: 'include',
      cache: 'no-store',
      signal
    });
    if (!response.ok) return;
    const session = await response.json();
    if (session.user?.id === scope.ownerUserId && sameScope(await readSession(), scope)) {
      return session.access_token;
    }
  };
  const locks = self.navigator?.locks;
  return locks ? locks.request(TOKEN_REFRESH_LOCK, perform) : perform();
}

function signedRequest(path, accessToken, signal, options = {}) {
  return fetch(`${API_BASE}${path}`, {
    ...options,
    credentials: 'omit',
    cache: 'no-store',
    signal,
    headers: { ...options.headers, Authorization: `Bearer ${accessToken}` }
  });
}

async function isVerifiedOwner(scope, accessToken, signal) {
  if (signal.aborted || !sameScope(await readSession(), scope)) return false;
  const response = await signedRequest('/auth/me', accessToken, signal);
  return (
    response.ok &&
    (await response.json()).id === scope.ownerUserId &&
    sameScope(await readSession(), scope)
  );
}

async function writeReport(path, payload, accessToken, signal, options) {
  const response = await signedRequest(path, accessToken, signal, {
    method: options.method,
    headers: { 'Content-Type': 'application/json', ...options.headers },
    body: JSON.stringify(payload)
  });
  if (!response.ok)
    throw Object.assign(new Error('Unable to synchronize the report draft.'), {
      status: response.status
    });
  return await response.json();
}

async function persistReportDraft(scope, localDraftId, accessToken, signal, hasLock) {
  const claim = {
    id: crypto.randomUUID(),
    generation: scope.generation,
    expiresAt: Date.now() + STALE_CLAIM_MS
  };
  const snapshot = await editReportDraft(scope, localDraftId, (draft) => {
    if (
      draft.syncState === 'conflict' ||
      draft.syncState === 'blocked' ||
      draft.retryAfter > Date.now()
    )
      return;
    if (
      !hasLock &&
      draft.claim?.generation === scope.generation &&
      draft.claim.expiresAt > Date.now()
    )
      return;
    return { ...draft, claim };
  });
  if (!snapshot) return;

  const patch = (change) =>
    editReportDraft(scope, localDraftId, (draft) =>
      draft.claim?.id === claim.id ? change(draft) : undefined
    );
  let outcome = 'local';
  try {
    if (!(await isVerifiedOwner(scope, accessToken, signal))) return;
    let pending = snapshot;
    for (let attempt = 0; pending && attempt < 3; attempt += 1) {
      outcome = await persistOwnedDraft(pending, {
        update: (id, payload, revision) =>
          writeReport(
            `/reports/${id}`,
            { ...payload, expected_revision: revision },
            accessToken,
            signal,
            { method: 'PUT' }
          ),
        create: (payload, key) =>
          writeReport('/reports', payload, accessToken, signal, {
            method: 'POST',
            headers: { 'Idempotency-Key': key }
          }),
        rememberCreate: async (pendingCreate) =>
          Boolean(await patch((draft) => ({ ...draft, pendingCreate }))),
        acknowledge: async (revision, report) => {
          await patch((draft) => ({
            ...draft,
            serverReport: { id: report.id, engineerId: report.engineer_id },
            baseServerRevision: report.revision,
            lastSyncedLocalRevision: revision,
            pendingCreate: undefined
          }));
        },
        status: (error) => error?.status,
        cancelled: (error) => error?.name === 'AbortError'
      });
      if (outcome !== 'saved' || signal.aborted || !sameScope(await readSession(), scope)) break;
      pending = await readReportDraft(scope, localDraftId);
      if (!pending || pending.lastSyncedLocalRevision >= pending.localRevision) break;
      outcome = 'local';
    }
  } finally {
    await patch((draft) => {
      const attempts = outcome === 'retry' ? draft.attempts + 1 : 0;
      const retryAfter = attempts > 0 ? Date.now() + 1000 * 2 ** Math.min(attempts, 5) : 0;
      return {
        ...draft,
        syncState: outcome,
        attempts,
        retryAfter: attempts >= 4 ? Number.MAX_SAFE_INTEGER : retryAfter,
        claim: undefined
      };
    });
  }
}

async function uploadQueuedFile(item, intent, accessToken, signal) {
  const formData = new FormData();
  formData.append('entity_type', item.entityType);
  formData.append('entity_id', intent.reportId);
  formData.append('kind', intent.kind);
  formData.append('expected_report_revision', String(intent.expectedRevision));
  formData.append('files', item.file);
  const response = await signedRequest('/photos/upload', accessToken, signal, {
    method: 'POST',
    headers: { 'Idempotency-Key': item.id },
    body: formData
  });
  if (!response.ok) {
    const details = await response.json().catch(() => null);
    throw Object.assign(new Error('Unable to upload queued file.'), {
      status: response.status,
      code: details?.error_code
    });
  }
  const committed = Number(response.headers.get('X-Report-Revision'));
  return Number.isSafeInteger(committed) && committed > 0 ? committed : undefined;
}

async function syncQueuedPhoto(scope, item, draft, hasLock, accessToken, signal) {
  if (signal.aborted || !sameScope(await readSession(), scope)) return 'pending';
  const claim = await claimQueuedPhoto(scope, item.id, hasLock);
  if (!claim) return 'pending';
  let kind;
  try {
    kind = await classifyQueuedReportFile(claim.file, claim.kind);
  } catch (error) {
    await patchClaim(scope, claim, {
      status: 'blocked',
      reason: error?.message ?? 'File could not be read.'
    });
    return 'blocked';
  }

  if (!claim.intent && draft && (draft.syncState !== 'saved' || !draft.serverReport)) {
    await patchClaim(scope, claim, { status: 'queued' });
    return 'waiting';
  }
  const reportId = draft?.serverReport?.id;
  const revision = draft?.baseServerRevision;
  const intent =
    claim.intent ??
    (reportId && revision !== undefined
      ? { reportId, expectedRevision: revision, kind }
      : undefined);
  if (!intent) {
    await patchClaim(scope, claim, {
      status: 'blocked',
      reason: 'This local report is no longer available.'
    });
    return 'blocked';
  }

  try {
    if (
      !(await patchClaim(scope, claim, { intent })) ||
      signal.aborted ||
      !sameScope(await readSession(), scope)
    )
      return 'pending';
    const committed = await uploadQueuedFile(claim, intent, accessToken, signal);
    if (committed === intent.expectedRevision + 1) {
      const saved = await withOwnedTransaction(
        scope,
        [PHOTO_QUEUE, REPORT_DRAFTS],
        'readwrite',
        (tx, result) =>
          commitUploadReceipt(tx, PHOTO_QUEUE, REPORT_DRAFTS, claim, intent, committed, result)
      );
      return saved ? 'saved' : 'pending';
    }
  } catch (error) {
    const failure = uploadFailure(error?.status, error?.code, signal.aborted);
    if (failure.state === 'suspended') {
      await patchClaim(scope, claim, { status: 'suspended' });
      return 'pending';
    }
    if (failure.state === 'blocked') {
      await patchClaim(scope, claim, { status: 'blocked', reason: failure.reason });
      if (failure.conflict) {
        await editReportDraft(scope, claim.localDraftId, (latest) => ({
          ...latest,
          syncState: 'conflict'
        }));
        return 'conflict';
      }
      return 'blocked';
    }
  }
  await patchClaim(scope, claim, { status: 'failed', ...uploadRetry(claim.attempts ?? 0, false) });
  return 'pending';
}

async function syncOwnedDraft(scope, localDraftId, hasLock, accessToken, signal) {
  if (!(await isVerifiedOwner(scope, accessToken, signal))) return 0;
  const queued = (await listQueuedPhotos(scope, localDraftId)).filter(
    (item) => !isBlocked(item) && item.status !== 'synced'
  );
  for (const item of queued) {
    if (!item.intent) continue;
    const result = await syncQueuedPhoto(scope, item, undefined, hasLock, accessToken, signal);
    if (result === 'conflict') return 1;
    if (result === 'pending') return 0;
  }

  const original = await readReportDraft(scope, localDraftId);
  if (original && original.lastSyncedLocalRevision < original.localRevision) {
    await persistReportDraft(scope, localDraftId, accessToken, signal, hasLock);
  }
  let draft = await readReportDraft(scope, localDraftId);
  for (const item of queued) {
    if (item.intent) continue;
    const result = await syncQueuedPhoto(scope, item, draft, hasLock, accessToken, signal);
    if (result === 'conflict') return 1;
    if (result === 'pending') break;
    draft = await readReportDraft(scope, localDraftId);
  }
  return 0;
}

async function drainPhotoQueue(scope, signal) {
  const ownedDrafts = await withOwnedStore(scope, REPORT_DRAFTS, 'readonly', (drafts, result) => {
    const request = drafts.index(OWNER_INDEX).getAll([scope.namespace, scope.ownerUserId]);
    request.onsuccess = () => result(request.result);
  });
  const queued = await listQueuedPhotos(scope);
  const draftIds = new Set([
    ...(ownedDrafts ?? [])
      .filter((draft) => (draft.lastSyncedLocalRevision ?? 0) < (draft.localRevision ?? 1))
      .map((draft) => draft.localDraftId),
    ...queued
      .filter((item) => !isBlocked(item) && item.status !== 'synced')
      .map((item) => item.localDraftId)
  ]);
  if (!draftIds.size) return;
  const accessToken = await refreshAccessToken(scope, signal);
  if (!accessToken) return;

  let conflicts = 0;
  for (const localDraftId of draftIds) {
    if (signal.aborted || !sameScope(await readSession(), scope)) return;
    const lockName = `garrisons-draft-sync:${JSON.stringify([scope.namespace, scope.ownerUserId, localDraftId])}`;
    conflicts += self.navigator?.locks
      ? await self.navigator.locks.request(lockName, () =>
          syncOwnedDraft(scope, localDraftId, true, accessToken, signal)
        )
      : await syncOwnedDraft(scope, localDraftId, false, accessToken, signal);
  }
  if (signal.aborted || !sameScope(await readSession(), scope)) return;
  const clients = await self.clients.matchAll({ type: 'window' });
  clients.forEach((client) => client.postMessage({ type: 'SYNC_PHOTOS_DONE', scope, conflicts }));
}

let currentDrain;

self.addEventListener('message', (event) => {
  if (event.data?.type !== SESSION_EVENT) return;
  const drain = currentDrain;
  event.waitUntil(
    (async () => {
      if (drain && !sameScope(await readSession(), drain.scope)) drain.controller.abort();
      const clients = await self.clients.matchAll({ type: 'window' });
      clients.forEach((client) => client.postMessage({ type: SESSION_EVENT }));
    })()
  );
});

self.addEventListener('sync', (event) => {
  if (event.tag !== 'flush-photo-queue') return;
  event.waitUntil(
    (async () => {
      const scope = await readSession();
      if (scope?.state !== 'active') return;
      const windows = await self.clients.matchAll({ type: 'window' });
      if (windows.length) {
        windows.forEach((client) => client.postMessage({ type: 'SYNC_FLUSH_PHOTOS', scope }));
        return;
      }
      if (currentDrain && sameScope(scope, currentDrain.scope)) return currentDrain.result;
      currentDrain?.controller.abort();
      const controller = new AbortController();
      const result = drainPhotoQueue(scope, controller.signal).finally(() => {
        if (currentDrain?.result === result) currentDrain = undefined;
      });
      currentDrain = { scope, controller, result };
      await result;
    })()
  );
});
