// The standalone drain uses the same owner, generation and claim checks as offlineQueue.ts.
const CACHE_NAME = 'garrisons-app-shell-v3';
const LEGACY_CACHES = new Set(['garrisons-app-shell-v1', 'garrisons-app-shell-v2']);
const DB_NAME = 'garrisons-offline';
const DB_VERSION = 2;
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
    request.onupgradeneeded = () => {
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

function withOwnedQueue(scope, mode, operation) {
  return transaction([SESSION_STORE, PHOTO_QUEUE], mode, (tx, result) => {
    const request = tx.objectStore(SESSION_STORE).get(scope.namespace);
    request.onsuccess = () => {
      if (sameScope(request.result, scope)) operation(tx.objectStore(PHOTO_QUEUE), result);
    };
  });
}

function claimQueuedPhoto(scope, id) {
  return withOwnedQueue(scope, 'readwrite', (queue, result) => {
    const request = queue.get(id);
    request.onsuccess = () => {
      const item = request.result;
      if (
        !item ||
        item.ownerUserId !== scope.ownerUserId ||
        item.namespace !== scope.namespace ||
        item.status === 'synced' ||
        item.status === 'server_newer'
      )
        return;
      if (
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

function planSyncBatches(items) {
  const batches = new Map();
  for (const item of items) {
    if (item.status === 'synced' || item.status === 'server_newer') continue;
    const key = JSON.stringify([
      item.namespace,
      item.ownerUserId,
      item.localDraftId,
      item.entityId
    ]);
    let batch = batches.get(key);
    if (!batch) {
      batch = { entityId: item.entityId, items: [] };
      batches.set(key, batch);
    }
    batch.items.push(item);
  }
  return [...batches.values()];
}

function updateClaims(scope, claims, patch) {
  return withOwnedQueue(scope, 'readwrite', (queue) => {
    for (const claim of claims) {
      const request = queue.get(claim.id);
      request.onsuccess = () => {
        const item = request.result;
        if (
          item?.claimId !== claim.claimId ||
          item?.ownerUserId !== scope.ownerUserId ||
          item.namespace !== scope.namespace
        )
          return;
        if (patch) queue.put({ ...item, ...patch });
        else queue.delete(claim.id);
      };
    }
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

async function createReportFromQueue(payload, idempotencyKey, accessToken, signal) {
  const response = await signedRequest('/reports', accessToken, signal, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json', 'Idempotency-Key': idempotencyKey },
    body: JSON.stringify(payload)
  });
  if (!response.ok) throw new Error('Unable to create queued daily report');
  return await response.json();
}

async function uploadQueuedFile(item, entityId, accessToken, signal) {
  const formData = new FormData();
  formData.append('entity_type', item.entityType);
  formData.append('entity_id', entityId);
  formData.append('kind', item.kind);
  formData.append('files', item.file);
  const response = await signedRequest('/photos/upload', accessToken, signal, {
    method: 'POST',
    headers: { 'Idempotency-Key': item.id },
    body: formData
  });
  if (!response.ok) throw new Error('Unable to upload queued file');
}

async function drainPhotoQueue(scope, signal) {
  const queued = await withOwnedQueue(scope, 'readonly', (queue, result) => {
    const request = queue.index(OWNER_INDEX).getAll([scope.namespace, scope.ownerUserId]);
    request.onsuccess = () => result(request.result);
  });
  const batches = planSyncBatches(queued ?? []);
  if (!batches.length) return;

  const accessToken = await refreshAccessToken(scope, signal);
  if (!accessToken) return;
  let conflicts = 0;

  for (const batch of batches) {
    if (!(await isVerifiedOwner(scope, accessToken, signal))) return;
    const claimed = [];
    for (const item of batch.items) {
      const entry = await claimQueuedPhoto(scope, item.id);
      if (entry) claimed.push(entry);
    }
    if (!claimed.length) continue;

    let entityId = batch.entityId;
    try {
      if (entityId.startsWith('local-')) {
        const draftPayload = claimed.find((item) => item.draftPayload)?.draftPayload;
        if (!draftPayload) throw new Error('Missing offline draft payload');
        if (signal.aborted || !sameScope(await readSession(), scope)) return;
        const report = await createReportFromQueue(draftPayload, entityId, accessToken, signal);
        entityId = report.id;
        await updateClaims(scope, claimed, { entityId });
        if (report.status !== 'draft') {
          conflicts += claimed.length;
          await updateClaims(scope, claimed, { status: 'server_newer' });
          continue;
        }
      }

      for (const item of claimed) {
        if (signal.aborted || !sameScope(await readSession(), scope)) return;
        try {
          await uploadQueuedFile(item, entityId, accessToken, signal);
          await updateClaims(scope, [item]);
        } catch {
          await updateClaims(scope, [item], { entityId, status: 'failed' });
        }
      }
    } catch {
      await updateClaims(scope, claimed, { entityId, status: 'failed' });
    }
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
