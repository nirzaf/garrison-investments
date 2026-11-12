// Authoritative offline photo-queue drain.
//
// `public/sw.js` keeps a standalone fallback for the no-window-client case and delegates
// here whenever a window is open. Any change to the batching, claim, or idempotency rules
// must be mirrored there — `planSyncBatches` is the shared, unit-tested seam.
import { uploadEntityFiles } from './photos';
import { createDailyReport, type DailyReportPayload } from './reports';

const DB_NAME = 'garrisons-offline';
const DB_VERSION = 1;
const REPORT_DRAFTS = 'reportDrafts';
const PHOTO_QUEUE = 'photoQueue';
/** A claim older than this is assumed dead (tab closed mid-upload) and may be reclaimed. */
const STALE_CLAIM_MS = 5 * 60_000;

export type QueuedPhoto = {
  id: string;
  entityType: string;
  entityId: string;
  draftPayload?: DailyReportPayload;
  kind: 'photo' | 'attachment';
  file: File;
  createdAt: string;
  claimedAt: string;
  status: 'queued' | 'syncing' | 'failed' | 'synced' | 'server_newer';
};

/** One report-create (at most) plus the uploads that belong to the same entity. */
export type SyncBatch = {
  entityId: string;
  needsReportCreate: boolean;
  draftPayload?: DailyReportPayload;
  items: QueuedPhoto[];
};

/**
 * Pure grouping seam for the offline drain — kept free of IndexedDB and network calls so
 * the "3 photos + 1 local id => 1 create + 3 uploads" invariant is unit-testable.
 *
 * Mirrored by `public/sw.js` (planSyncBatches); keep the two in step.
 */
export function planSyncBatches(items: QueuedPhoto[]): SyncBatch[] {
  const batches = new Map<string, SyncBatch>();
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
    batch.draftPayload ??= item.draftPayload;
    batch.items.push(item);
  }
  return [...batches.values()];
}

/**
 * Pure retry record for a failed upload. Keeping the resolved server id is what stops a
 * retry from re-creating the report: the next `planSyncBatches` sees a non-`local-` id and
 * therefore plans uploads only.
 */
export function retryPatch(item: QueuedPhoto, resolvedEntityId: string): QueuedPhoto {
  return { ...item, entityId: resolvedEntityId, status: 'failed' };
}

let flushPromise: Promise<void> | null = null;

function openDb(): Promise<IDBDatabase> {
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

async function store<T>(
  name: string,
  mode: IDBTransactionMode,
  run: (store: IDBObjectStore) => IDBRequest<T>
) {
  const db = await openDb();
  return new Promise<T>((resolve, reject) => {
    const tx = db.transaction(name, mode);
    const request = run(tx.objectStore(name));
    request.onsuccess = () => resolve(request.result);
    request.onerror = () => reject(request.error);
    tx.oncomplete = () => db.close();
    tx.onerror = () => {
      db.close();
      reject(tx.error);
    };
  });
}

type SavedReportReference = { id: string; engineerId: string };

export async function saveReportDraft(
  payload: DailyReportPayload,
  draftKey: string | null,
  serverReport?: SavedReportReference
) {
  await store(REPORT_DRAFTS, 'readwrite', (drafts) =>
    drafts.put(
      { payload, draftKey, serverReport, savedAt: new Date().toISOString(), syncStatus: 'local' },
      'daily-report'
    )
  );
}

export async function getReportDraft(): Promise<{
  payload: DailyReportPayload;
  draftKey?: string | null;
  serverReport?: SavedReportReference;
  savedAt: string;
  syncStatus: string;
} | null> {
  return await store(REPORT_DRAFTS, 'readonly', (drafts) => drafts.get('daily-report'));
}

export async function clearReportDraft() {
  await store(REPORT_DRAFTS, 'readwrite', (drafts) => drafts.delete('daily-report'));
}

export async function queueFiles(args: {
  entityType: string;
  entityId: string;
  draftPayload?: DailyReportPayload;
  kind: 'photo' | 'attachment';
  files: FileList;
}) {
  await Promise.all(
    Array.from(args.files).map((file) =>
      store(PHOTO_QUEUE, 'readwrite', (queue) =>
        queue.put({
          id: crypto.randomUUID(),
          entityType: args.entityType,
          entityId: args.entityId,
          draftPayload: args.draftPayload,
          kind: args.kind,
          file,
          createdAt: new Date().toISOString(),
          claimedAt: '',
          status: 'queued'
        } satisfies QueuedPhoto)
      )
    )
  );
}

export async function queuedPhotoCount(): Promise<number> {
  return await store(PHOTO_QUEUE, 'readonly', (queue) => queue.count());
}

export async function registerBackgroundSync() {
  if (!('serviceWorker' in navigator) || !('SyncManager' in window)) return;
  try {
    const reg = await navigator.serviceWorker.ready;
    await reg.sync.register('flush-photo-queue');
  } catch {
    // Background Sync unsupported (Safari, Firefox) — foreground retry will handle it
  }
}

export function listenForSyncMessages() {
  if (!('serviceWorker' in navigator)) return () => {};

  const handler = (event: MessageEvent) => {
    if (event.data?.type === 'SYNC_FLUSH_PHOTOS') {
      void flushPhotoQueue();
    } else if (event.data?.type === 'SYNC_PHOTOS_DONE') {
      window.dispatchEvent(
        new CustomEvent('photo-queue-sync-complete', {
          detail: { conflicts: Number(event.data.conflicts ?? 0) }
        })
      );
    }
  };
  navigator.serviceWorker.addEventListener('message', handler);
  return () => navigator.serviceWorker.removeEventListener('message', handler);
}

export async function flushPhotoQueue() {
  flushPromise ??= drainPhotoQueue().finally(() => {
    flushPromise = null;
  });
  return flushPromise;
}

async function claimQueuedPhoto(id: string): Promise<QueuedPhoto | null> {
  const db = await openDb();
  return new Promise((resolve, reject) => {
    const tx = db.transaction(PHOTO_QUEUE, 'readwrite');
    const queue = tx.objectStore(PHOTO_QUEUE);
    const getRequest = queue.get(id);
    let claimed: QueuedPhoto | null = null;

    getRequest.onsuccess = () => {
      const item = getRequest.result as QueuedPhoto | undefined;
      if (!item) {
        resolve(null);
        return;
      }
      if (item.status === 'syncing') {
        // M2: a claim left behind by a closed tab must not wedge the queue forever.
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

/** Patch many queue rows inside ONE readwrite transaction (atomic sibling updates). */
async function patchQueuedPhotos(ids: string[], patch: Partial<QueuedPhoto>): Promise<void> {
  if (!ids.length) return;
  const db = await openDb();
  return new Promise((resolve, reject) => {
    const tx = db.transaction(PHOTO_QUEUE, 'readwrite');
    const queue = tx.objectStore(PHOTO_QUEUE);
    for (const id of ids) {
      const getRequest = queue.get(id);
      getRequest.onsuccess = () => {
        const item = getRequest.result as QueuedPhoto | undefined;
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

async function drainPhotoQueue() {
  const queued = await store<QueuedPhoto[]>(PHOTO_QUEUE, 'readonly', (queue) => queue.getAll());
  let conflicts = 0;

  for (const batch of planSyncBatches(queued)) {
    const claimed: QueuedPhoto[] = [];
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
        // C1: exactly one create per local batch, keyed by the local id so a replay is a no-op.
        const report = await createDailyReport(draftPayload, batch.entityId);
        entityId = report.id;
        // Persist the server id onto EVERY sibling before any upload starts, so a crash
        // mid-batch can never re-create the report on the next drain.
        await patchQueuedPhotos(ids, { entityId });
        if (report.status !== 'draft') {
          // M2: the server already moved this report on — stop retrying the leftovers.
          conflicts += claimed.length;
          await patchQueuedPhotos(ids, { status: 'server_newer' });
          continue;
        }
      }

      for (const item of claimed) {
        try {
          const dataTransfer = new DataTransfer();
          dataTransfer.items.add(item.file);
          await uploadEntityFiles({
            entityType: item.entityType,
            entityId,
            kind: item.kind,
            files: dataTransfer.files,
            idempotencyKey: item.id
          });
          await store(PHOTO_QUEUE, 'readwrite', (queue) => queue.delete(item.id));
        } catch {
          await store(PHOTO_QUEUE, 'readwrite', (queue) => queue.put(retryPatch(item, entityId)));
        }
      }
    } catch {
      // Keep the resolved server id (when we have one) so a retry never re-creates the report.
      await patchQueuedPhotos(ids, { entityId, status: 'failed' });
    }
  }

  window.dispatchEvent(new CustomEvent('photo-queue-sync-complete', { detail: { conflicts } }));
}
