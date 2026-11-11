// Offline photo queue.
//
// The authoritative drain lives in `src/api/offlineQueue.ts`. When a window client is
// available the `sync` event below delegates to it (see the handler at the bottom), so
// there is exactly one implementation in the common case. The standalone drain here is
// the no-client fallback and MUST stay behaviourally identical: same batching, same
// single-create-per-local-entity rule, same Idempotency-Key headers, same refresh lock.
const CACHE_NAME = 'garrisons-app-shell-v2';
const DB_NAME = 'garrisons-offline';
const DB_VERSION = 1;
const REPORT_DRAFTS = 'reportDrafts';
const PHOTO_QUEUE = 'photoQueue';
const API_BASE = '/api/v1';
// Keep in step with TOKEN_REFRESH_LOCK in src/api/client.ts.
const TOKEN_REFRESH_LOCK = 'garrison-token-refresh';
const STALE_CLAIM_MS = 5 * 60_000;
const APP_SHELL = [
  '/',
  '/reports/daily',
  '/manifest.json',
  '/brand/apple-touch-icon.png',
  '/brand/icon-192.png',
  '/brand/icon-512.png',
  '/brand/logo-full.jpg',
  '/brand/logo-mark.png'
];

self.addEventListener('install', (event) => {
  event.waitUntil(caches.open(CACHE_NAME).then((cache) => cache.addAll(APP_SHELL)));
  self.skipWaiting();
});

self.addEventListener('activate', (event) => {
  event.waitUntil(
    caches
      .keys()
      .then((keys) =>
        Promise.all(keys.filter((key) => key !== CACHE_NAME).map((key) => caches.delete(key)))
      )
  );
  self.clients.claim();
});

self.addEventListener('fetch', (event) => {
  const request = event.request;
  if (request.method !== 'GET') return;
  if (request.mode === 'navigate') {
    event.respondWith(fetch(request).catch(() => caches.match('/')));
    return;
  }
  if (request.destination === 'script' || request.destination === 'style') {
    event.respondWith(
      caches.open(CACHE_NAME).then((cache) =>
        cache.match(request).then(
          (cached) =>
            cached ||
            fetch(request).then((response) => {
              cache.put(request, response.clone());
              return response;
            })
        )
      )
    );
    return;
  }
  event.respondWith(caches.match(request).then((cached) => cached || fetch(request)));
});

let photoQueueFlush = null;

function openOfflineDb() {
  return new Promise((resolve, reject) => {
    const request = indexedDB.open(DB_NAME, DB_VERSION);
    request.onupgradeneeded = () => {
      const db = request.result;
      if (!db.objectStoreNames.contains(REPORT_DRAFTS)) db.createObjectStore(REPORT_DRAFTS);
      if (!db.objectStoreNames.contains(PHOTO_QUEUE))
        db.createObjectStore(PHOTO_QUEUE, { keyPath: 'id' });
    };
    request.onsuccess = () => resolve(request.result);
    request.onerror = () => reject(request.error);
  });
}

async function withPhotoQueue(mode, run) {
  const db = await openOfflineDb();
  return new Promise((resolve, reject) => {
    const tx = db.transaction(PHOTO_QUEUE, mode);
    const queue = tx.objectStore(PHOTO_QUEUE);
    const request = run(queue);

    if (request) {
      request.onsuccess = () => resolve(request.result);
      request.onerror = () => reject(request.error);
    }

    tx.oncomplete = () => {
      db.close();
      if (!request) resolve(undefined);
    };
    tx.onerror = () => {
      db.close();
      reject(tx.error);
    };
  });
}

async function claimQueuedPhoto(id) {
  const db = await openOfflineDb();
  return new Promise((resolve, reject) => {
    const tx = db.transaction(PHOTO_QUEUE, 'readwrite');
    const queue = tx.objectStore(PHOTO_QUEUE);
    const getRequest = queue.get(id);
    let claimed = null;

    getRequest.onsuccess = () => {
      const item = getRequest.result;
      if (!item) {
        resolve(null);
        return;
      }
      if (item.status === 'syncing') {
        const claimedAt = item.claimedAt ? Date.parse(item.claimedAt) : 0;
        if (Number.isFinite(claimedAt) && Date.now() - claimedAt <= STALE_CLAIM_MS) {
          resolve(null);
          return;
        }
      }
      claimed = { ...item, status: 'syncing', claimedAt: new Date().toISOString() };
      queue.put(claimed);
    };
    getRequest.onerror = () => reject(getRequest.error);
    tx.oncomplete = () => {
      db.close();
      resolve(claimed);
    };
    tx.onerror = () => {
      db.close();
      reject(tx.error);
    };
  });
}

/** Mirror of planSyncBatches in src/api/offlineQueue.ts — keep the two in step. */
function planSyncBatches(items) {
  const batches = new Map();
  for (const item of items) {
    if (item.status === 'synced' || item.status === 'server_newer') continue;
    let batch = batches.get(item.entityId);
    if (!batch) {
      batch = {
        entityId: item.entityId,
        needsReportCreate: item.entityId.startsWith('local-'),
        draftPayload: item.draftPayload,
        items: []
      };
      batches.set(item.entityId, batch);
    }
    batch.draftPayload = batch.draftPayload ?? item.draftPayload;
    batch.items.push(item);
  }
  return [...batches.values()];
}

/** Patch many queue rows inside ONE readwrite transaction. */
async function patchQueuedPhotos(ids, patch) {
  if (!ids.length) return;
  const db = await openOfflineDb();
  return new Promise((resolve, reject) => {
    const tx = db.transaction(PHOTO_QUEUE, 'readwrite');
    const queue = tx.objectStore(PHOTO_QUEUE);
    for (const id of ids) {
      const getRequest = queue.get(id);
      getRequest.onsuccess = () => {
        const item = getRequest.result;
        if (item) queue.put({ ...item, ...patch });
      };
    }
    tx.oncomplete = () => {
      db.close();
      resolve();
    };
    tx.onerror = () => {
      db.close();
      reject(tx.error);
    };
  });
}

async function refreshAccessToken() {
  const perform = async () => {
    const response = await fetch(`${API_BASE}/auth/refresh`, {
      method: 'POST',
      credentials: 'include'
    });
    if (!response.ok) throw new Error('Unable to refresh offline sync session');
    const session = await response.json();
    return session.access_token;
  };
  // Same lock name as the app so a foreground refresh and a background sync cannot race.
  const locks = self.navigator?.locks;
  return locks ? locks.request(TOKEN_REFRESH_LOCK, perform) : perform();
}

async function createReportFromQueue(payload, idempotencyKey, accessToken) {
  const response = await fetch(`${API_BASE}/reports`, {
    method: 'POST',
    credentials: 'include',
    headers: {
      Authorization: `Bearer ${accessToken}`,
      'Content-Type': 'application/json',
      'Idempotency-Key': idempotencyKey
    },
    body: JSON.stringify(payload)
  });
  if (!response.ok) throw new Error('Unable to create queued daily report');
  return await response.json();
}

async function uploadQueuedFile(item, entityId, accessToken) {
  const formData = new FormData();
  formData.append('entity_type', item.entityType);
  formData.append('entity_id', entityId);
  formData.append('kind', item.kind);
  formData.append('files', item.file);

  const response = await fetch(`${API_BASE}/photos/upload`, {
    method: 'POST',
    credentials: 'include',
    headers: {
      Authorization: `Bearer ${accessToken}`,
      'Idempotency-Key': item.id
    },
    body: formData
  });
  if (!response.ok) throw new Error('Unable to upload queued file');
}

async function notifyClients(type, extra) {
  const clients = await self.clients.matchAll();
  clients.forEach((client) => client.postMessage({ type, ...extra }));
}

async function drainPhotoQueue() {
  const queued = await withPhotoQueue('readonly', (queue) => queue.getAll());
  if (!queued.length) return;

  const accessToken = await refreshAccessToken();
  let conflicts = 0;

  for (const batch of planSyncBatches(queued)) {
    const claimed = [];
    for (const item of batch.items) {
      const entry = await claimQueuedPhoto(item.id);
      if (entry) claimed.push(entry);
    }
    if (!claimed.length) continue;

    const ids = claimed.map((item) => item.id);
    let entityId = batch.entityId;
    try {
      if (batch.needsReportCreate) {
        const draftPayload = claimed.find((item) => item.draftPayload)?.draftPayload;
        if (!draftPayload) throw new Error('Missing offline draft payload');
        const report = await createReportFromQueue(draftPayload, batch.entityId, accessToken);
        entityId = report.id;
        // Persist the server id onto every sibling before uploading anything.
        await patchQueuedPhotos(ids, { entityId });
        if (report.status !== 'draft') {
          conflicts += claimed.length;
          await patchQueuedPhotos(ids, { status: 'server_newer' });
          continue;
        }
      }

      for (const item of claimed) {
        try {
          await uploadQueuedFile(item, entityId, accessToken);
          await withPhotoQueue('readwrite', (queue) => queue.delete(item.id));
        } catch {
          await withPhotoQueue('readwrite', (queue) =>
            queue.put({ ...item, entityId, status: 'failed' })
          );
        }
      }
    } catch {
      await patchQueuedPhotos(ids, { entityId, status: 'failed' });
    }
  }

  await notifyClients('SYNC_PHOTOS_DONE', { conflicts });
}

function flushPhotoQueueInServiceWorker() {
  photoQueueFlush ??= drainPhotoQueue().finally(() => {
    photoQueueFlush = null;
  });
  return photoQueueFlush;
}

self.addEventListener('sync', (event) => {
  if (event.tag !== 'flush-photo-queue') return;
  event.waitUntil(
    (async () => {
      // Prefer the app: it owns the tested drain and its own token-refresh lock.
      const windows = await self.clients.matchAll({ type: 'window' });
      if (windows.length) {
        windows.forEach((client) => client.postMessage({ type: 'SYNC_FLUSH_PHOTOS' }));
        return;
      }
      await flushPhotoQueueInServiceWorker();
    })()
  );
});
