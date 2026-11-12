// Keep the schema in step with the standalone drain in public/sw.js.
export const OFFLINE_DB = 'garrisons-offline';
export const OFFLINE_DB_VERSION = 3;
export const REPORT_DRAFTS = 'ownedReportDrafts';
export const PHOTO_QUEUE = 'ownedPhotoQueue';
export const SUPERVISOR_DRAFTS = 'ownedSupervisorDrafts';
export const SESSION_STORE = 'offlineSessions';
export const OWNER_INDEX = 'byOwner';

export type OfflineScope = {
  namespace: string;
  ownerUserId: string;
  generation: string;
};

export type OfflineSession = OfflineScope & { state: 'active' | 'signed-out' | 'suspended' };

export function ownerKey(scope: OfflineScope): [string, string] {
  return [scope.namespace, scope.ownerUserId];
}

export function sameScope(left: OfflineScope | null | undefined, right: OfflineScope): boolean {
  return (
    left?.namespace === right.namespace &&
    left.ownerUserId === right.ownerUserId &&
    left.generation === right.generation
  );
}

function openDb(): Promise<IDBDatabase> {
  return new Promise((resolve, reject) => {
    const request = indexedDB.open(OFFLINE_DB, OFFLINE_DB_VERSION);
    request.onupgradeneeded = (event) => {
      if (event.oldVersion >= 2) return;
      const db = request.result;
      // The v1 stores, when present, remain quarantined. Their keys do not prove ownership.
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
      reject(new Error('Close older portal tabs to upgrade offline storage.'));
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

async function transaction<T>(
  stores: string[],
  mode: IDBTransactionMode,
  operation: (tx: IDBTransaction, result: (value: T) => void) => void
): Promise<T | undefined> {
  const db = await openDb();
  return new Promise((resolve, reject) => {
    const tx = db.transaction(stores, mode);
    let result: T | undefined;
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

export function readOfflineSession(namespace: string): Promise<OfflineSession | undefined> {
  return transaction<OfflineSession>([SESSION_STORE], 'readonly', (tx, result) => {
    const request = tx.objectStore(SESSION_STORE).get(namespace);
    request.onsuccess = () => result(request.result as OfflineSession);
  });
}

export async function writeOfflineSession(
  session: OfflineSession,
  expectedGeneration?: string | null,
  purgeOwner?: OfflineScope
): Promise<boolean> {
  const stores = [SESSION_STORE];
  if (purgeOwner) stores.push(REPORT_DRAFTS, PHOTO_QUEUE, SUPERVISOR_DRAFTS);
  const applied = await transaction<boolean>(stores, 'readwrite', (tx, result) => {
    const sessions = tx.objectStore(SESSION_STORE);
    const request = sessions.get(session.namespace);
    request.onsuccess = () => {
      const current = request.result as OfflineSession | undefined;
      if (expectedGeneration !== undefined && (current?.generation ?? null) !== expectedGeneration)
        return;
      sessions.put(session);
      if (purgeOwner) {
        const key = ownerKey(purgeOwner);
        tx.objectStore(SUPERVISOR_DRAFTS).delete([...key, 'supervisor-update']);
        for (const name of [REPORT_DRAFTS, PHOTO_QUEUE]) {
          const matches = tx.objectStore(name).index(OWNER_INDEX).openCursor(key);
          matches.onsuccess = () => {
            const cursor = matches.result;
            if (!cursor) return;
            cursor.delete();
            cursor.continue();
          };
        }
      }
      result(true);
    };
  });
  return applied === true;
}

export function withOwnedOfflineData<T>(
  scope: OfflineScope,
  storeName: string,
  mode: IDBTransactionMode,
  operation: (store: IDBObjectStore, result: (value: T) => void) => void
): Promise<T | undefined> {
  return transaction<T>([SESSION_STORE, storeName], mode, (tx, result) => {
    const request = tx.objectStore(SESSION_STORE).get(scope.namespace);
    request.onsuccess = () => {
      const current = request.result as OfflineSession | undefined;
      if (current?.state === 'active' && sameScope(current, scope)) {
        operation(tx.objectStore(storeName), result);
      }
    };
  });
}
