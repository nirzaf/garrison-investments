const CACHE_NAME = 'garrisons-app-shell-v2';
const DB_NAME = 'garrisons-offline';
const DB_VERSION = 1;
const REPORT_DRAFTS = 'reportDrafts';
const PHOTO_QUEUE = 'photoQueue';
const API_BASE = '/api/v1';
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
      if (!item || item.status === 'syncing') {
        resolve(null);
        return;
      }
      claimed = { ...item, status: 'syncing' };
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

async function refreshAccessToken() {
  const response = await fetch(`${API_BASE}/auth/refresh`, {
    method: 'POST',
    credentials: 'include'
  });
  if (!response.ok) throw new Error('Unable to refresh offline sync session');
  const session = await response.json();
  return session.access_token;
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
      Authorization: `Bearer ${accessToken}`
    },
    body: formData
  });
  if (!response.ok) throw new Error('Unable to upload queued file');
}

async function notifyClients(type) {
  const clients = await self.clients.matchAll();
  clients.forEach((client) => client.postMessage({ type }));
}

async function drainPhotoQueue() {
  const queued = await withPhotoQueue('readonly', (queue) => queue.getAll());
  if (!queued.length) return;

  const accessToken = await refreshAccessToken();

  for (const item of queued) {
    const claimed = await claimQueuedPhoto(item.id);
    if (!claimed) continue;

    try {
      let entityId = claimed.entityId;
      if (claimed.entityId.startsWith('local-')) {
        if (!claimed.draftPayload) throw new Error('Missing offline draft payload');
        const report = await createReportFromQueue(
          claimed.draftPayload,
          claimed.entityId,
          accessToken
        );
        entityId = report.id;
      }

      await uploadQueuedFile(claimed, entityId, accessToken);
      await withPhotoQueue('readwrite', (queue) => queue.delete(claimed.id));
    } catch {
      await withPhotoQueue('readwrite', (queue) => queue.put({ ...claimed, status: 'failed' }));
    }
  }

  await notifyClients('SYNC_PHOTOS_DONE');
}

function flushPhotoQueueInServiceWorker() {
  photoQueueFlush ??= drainPhotoQueue().finally(() => {
    photoQueueFlush = null;
  });
  return photoQueueFlush;
}

self.addEventListener('sync', (event) => {
  if (event.tag === 'flush-photo-queue') {
    event.waitUntil(flushPhotoQueueInServiceWorker());
  }
});
