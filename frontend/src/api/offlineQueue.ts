import { uploadEntityFiles } from './photos';
import { createDailyReport, type DailyReportPayload } from './reports';

const DB_NAME = 'garrisons-offline';
const DB_VERSION = 1;
const REPORT_DRAFTS = 'reportDrafts';
const PHOTO_QUEUE = 'photoQueue';

type QueuedPhoto = {
  id: string;
  entityType: string;
  entityId: string;
  draftPayload?: DailyReportPayload;
  kind: 'photo' | 'attachment';
  file: File;
  createdAt: string;
  status: 'queued' | 'syncing' | 'failed' | 'synced' | 'server_newer';
};

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

export async function saveReportDraft(payload: DailyReportPayload) {
  await store(REPORT_DRAFTS, 'readwrite', (drafts) =>
    drafts.put({ payload, savedAt: new Date().toISOString(), syncStatus: 'local' }, 'daily-report')
  );
}

export async function getReportDraft(): Promise<{
  payload: DailyReportPayload;
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
  entityId?: string;
  draftPayload?: DailyReportPayload;
  kind: 'photo' | 'attachment';
  files: FileList;
}) {
  const entityId = args.entityId ?? `local-${crypto.randomUUID()}`;
  await Promise.all(
    Array.from(args.files).map((file) =>
      store(PHOTO_QUEUE, 'readwrite', (queue) =>
        queue.put({
          id: crypto.randomUUID(),
          entityType: args.entityType,
          entityId,
          draftPayload: args.draftPayload,
          kind: args.kind,
          file,
          createdAt: new Date().toISOString(),
          status: 'queued'
        } satisfies QueuedPhoto)
      )
    )
  );
}

export async function queuedPhotoCount(): Promise<number> {
  return await store(PHOTO_QUEUE, 'readonly', (queue) => queue.count());
}

export async function flushPhotoQueue() {
  const queued = await store<QueuedPhoto[]>(PHOTO_QUEUE, 'readonly', (queue) => queue.getAll());
  for (const item of queued) {
    try {
      await store(PHOTO_QUEUE, 'readwrite', (queue) => queue.put({ ...item, status: 'syncing' }));
      let entityId = item.entityId;
      if (item.entityId.startsWith('local-')) {
        if (!item.draftPayload) {
          throw new Error('Missing offline draft payload');
        }
        const report = await createDailyReport(item.draftPayload, item.entityId);
        entityId = report.id;
      }
      const dataTransfer = new DataTransfer();
      dataTransfer.items.add(item.file);
      await uploadEntityFiles({
        entityType: item.entityType,
        entityId,
        kind: item.kind,
        files: dataTransfer.files
      });
      await store(PHOTO_QUEUE, 'readwrite', (queue) => queue.delete(item.id));
    } catch {
      await store(PHOTO_QUEUE, 'readwrite', (queue) => queue.put({ ...item, status: 'failed' }));
    }
  }
}
