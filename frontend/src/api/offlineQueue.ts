// Authoritative offline photo-queue drain.
//
// `public/sw.js` keeps a standalone fallback for the no-window-client case and delegates
// here whenever a window is open. Any change to the batching, claim, or idempotency rules
// must be mirrored there — `planSyncBatches` is the shared, unit-tested seam.
import { getMe } from './auth';
import { getBrowserSession, isActiveOfflineScope } from './browserSession';
import {
  ownerKey,
  OWNER_INDEX,
  PHOTO_QUEUE,
  REPORT_DRAFTS,
  SUPERVISOR_DRAFTS,
  sameScope,
  withOwnedOfflineData,
  type OfflineScope
} from './offlineDb';
import { uploadEntityFiles } from './photos';
import { createDailyReport, type DailyReportPayload } from './reports';

/** A claim older than this is assumed dead (tab closed mid-upload) and may be reclaimed. */
const STALE_CLAIM_MS = 5 * 60_000;

export type QueuedPhoto = {
  id: string;
  namespace: string;
  ownerUserId: string;
  localDraftId: string;
  entityType: string;
  entityId: string;
  draftPayload?: DailyReportPayload;
  kind: 'photo' | 'attachment';
  file: File;
  createdAt: string;
  claimedAt: string;
  claimId?: string;
  claimGeneration?: string;
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
    const key = JSON.stringify([
      item.namespace,
      item.ownerUserId,
      item.localDraftId,
      item.entityId
    ]);
    let batch = batches.get(key);
    if (!batch) {
      batch = {
        entityId: item.entityId,
        needsReportCreate: item.entityId.startsWith('local-'),
        draftPayload: item.draftPayload,
        items: []
      };
      batches.set(key, batch);
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

type SavedReportReference = { id: string; engineerId: string };

type LocalReportDraft = {
  namespace: string;
  ownerUserId: string;
  localDraftId: string;
  payload: DailyReportPayload;
  serverReport?: SavedReportReference;
  savedAt: string;
};

export async function saveReportDraft(
  scope: OfflineScope,
  payload: DailyReportPayload,
  localDraftId: string,
  serverReport?: SavedReportReference
): Promise<boolean> {
  const saved = await withOwnedOfflineData<boolean>(
    scope,
    REPORT_DRAFTS,
    'readwrite',
    (drafts, result) => {
      drafts.put({
        namespace: scope.namespace,
        ownerUserId: scope.ownerUserId,
        localDraftId,
        payload,
        serverReport,
        savedAt: new Date().toISOString()
      } satisfies LocalReportDraft);
      result(true);
    }
  );
  return saved === true;
}

export async function getReportDraft(scope: OfflineScope): Promise<LocalReportDraft | undefined> {
  return withOwnedOfflineData<LocalReportDraft>(
    scope,
    REPORT_DRAFTS,
    'readonly',
    (drafts, result) => {
      const request = drafts.index(OWNER_INDEX).getAll(ownerKey(scope));
      request.onsuccess = () => {
        const owned = request.result as LocalReportDraft[];
        const latest = owned.sort((left, right) => right.savedAt.localeCompare(left.savedAt))[0];
        if (latest) result(latest);
      };
    }
  );
}

export async function clearReportDraft(scope: OfflineScope, localDraftId: string): Promise<void> {
  await withOwnedOfflineData(scope, REPORT_DRAFTS, 'readwrite', (drafts) => {
    drafts.delete([...ownerKey(scope), localDraftId]);
  });
}

export async function getSupervisorDraft<T>(scope: OfflineScope): Promise<T | undefined> {
  return withOwnedOfflineData<T>(scope, SUPERVISOR_DRAFTS, 'readonly', (drafts, result) => {
    const request = drafts.get([...ownerKey(scope), 'supervisor-update']);
    request.onsuccess = () => {
      const row = request.result as { values: T } | undefined;
      if (row) result(row.values);
    };
  });
}

export async function saveSupervisorDraft<T>(scope: OfflineScope, values: T): Promise<void> {
  await withOwnedOfflineData(scope, SUPERVISOR_DRAFTS, 'readwrite', (drafts) => {
    drafts.put({
      namespace: scope.namespace,
      ownerUserId: scope.ownerUserId,
      localDraftId: 'supervisor-update',
      values
    });
  });
}

export async function clearSupervisorDraft(scope: OfflineScope): Promise<void> {
  await withOwnedOfflineData(scope, SUPERVISOR_DRAFTS, 'readwrite', (drafts) => {
    drafts.delete([...ownerKey(scope), 'supervisor-update']);
  });
}

export async function queueFiles(
  scope: OfflineScope,
  args: {
    entityType: string;
    entityId: string;
    localDraftId: string;
    draftPayload?: DailyReportPayload;
    kind: 'photo' | 'attachment';
    files: FileList | File[];
  }
): Promise<boolean> {
  const queued = await withOwnedOfflineData<boolean>(
    scope,
    PHOTO_QUEUE,
    'readwrite',
    (queue, result) => {
      for (const file of args.files) {
        queue.add({
          id: crypto.randomUUID(),
          namespace: scope.namespace,
          ownerUserId: scope.ownerUserId,
          localDraftId: args.localDraftId,
          entityType: args.entityType,
          entityId: args.entityId,
          draftPayload: args.draftPayload,
          kind: args.kind,
          file,
          createdAt: new Date().toISOString(),
          claimedAt: '',
          status: 'queued'
        } satisfies QueuedPhoto);
      }
      result(true);
    }
  );
  return queued === true;
}

export async function queuedPhotoCount(scope: OfflineScope): Promise<number> {
  const count = await withOwnedOfflineData<number>(
    scope,
    PHOTO_QUEUE,
    'readonly',
    (queue, result) => {
      const request = queue.index(OWNER_INDEX).count(ownerKey(scope));
      request.onsuccess = () => result(request.result);
    }
  );
  return count ?? 0;
}

export async function queuedDraftPhotoCount(
  scope: OfflineScope,
  localDraftId: string
): Promise<number> {
  const count = await withOwnedOfflineData<number>(
    scope,
    PHOTO_QUEUE,
    'readonly',
    (queue, result) => {
      const request = queue.index('byOwnerDraft').getAll([...ownerKey(scope), localDraftId]);
      request.onsuccess = () =>
        result((request.result as QueuedPhoto[]).filter((entry) => entry.kind === 'photo').length);
    }
  );
  return count ?? 0;
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
    const scope = getBrowserSession()?.scope;
    if (!scope || !sameScope(event.data?.scope, scope)) return;
    if (event.data.type === 'SYNC_FLUSH_PHOTOS') {
      void flushPhotoQueue().catch(() => {});
    } else if (event.data.type === 'SYNC_PHOTOS_DONE') {
      publishSyncResult(scope, Number(event.data.conflicts ?? 0));
    }
  };
  navigator.serviceWorker.addEventListener('message', handler);
  return () => navigator.serviceWorker.removeEventListener('message', handler);
}

let currentFlush: { scope: OfflineScope; result: Promise<void> } | undefined;

export async function flushPhotoQueue(): Promise<void> {
  const scope = getBrowserSession()?.scope;
  if (!scope) return;
  if (currentFlush && sameScope(currentFlush.scope, scope)) return currentFlush.result;

  const result = drainPhotoQueue(scope).finally(() => {
    if (currentFlush?.result === result) currentFlush = undefined;
  });
  currentFlush = { scope, result };
  return result;
}

function claimQueuedPhoto(scope: OfflineScope, id: string): Promise<QueuedPhoto | undefined> {
  return withOwnedOfflineData<QueuedPhoto>(scope, PHOTO_QUEUE, 'readwrite', (queue, result) => {
    const request = queue.get(id);
    request.onsuccess = () => {
      const item = request.result as QueuedPhoto | undefined;
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
      const claimed: QueuedPhoto = {
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

async function updateClaims(
  scope: OfflineScope,
  claims: QueuedPhoto[],
  patch?: Partial<Pick<QueuedPhoto, 'entityId' | 'status' | 'claimedAt'>>
): Promise<void> {
  await withOwnedOfflineData(scope, PHOTO_QUEUE, 'readwrite', (queue) => {
    for (const claim of claims) {
      const request = queue.get(claim.id);
      request.onsuccess = () => {
        const item = request.result as QueuedPhoto | undefined;
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

function publishSyncResult(scope: OfflineScope, conflicts: number): void {
  if (!sameScope(getBrowserSession()?.scope, scope)) return;
  window.dispatchEvent(
    new CustomEvent('photo-queue-sync-complete', { detail: { scope, conflicts } })
  );
}

async function canSync(scope: OfflineScope): Promise<boolean> {
  return (await isActiveOfflineScope(scope)) && sameScope(getBrowserSession()?.scope, scope);
}

async function drainPhotoQueue(scope: OfflineScope): Promise<void> {
  const queued = await withOwnedOfflineData<QueuedPhoto[]>(
    scope,
    PHOTO_QUEUE,
    'readonly',
    (queue, result) => {
      const request = queue.index(OWNER_INDEX).getAll(ownerKey(scope));
      request.onsuccess = () => result(request.result as QueuedPhoto[]);
    }
  );
  let conflicts = 0;
  for (const batch of planSyncBatches(queued ?? [])) {
    if (!(await canSync(scope))) return;
    const actor = await getMe(scope).catch(() => null);
    if (actor?.id !== scope.ownerUserId || !(await canSync(scope))) return;
    const claimed: QueuedPhoto[] = [];
    for (const item of batch.items) {
      const entry = await claimQueuedPhoto(scope, item.id);
      if (entry) claimed.push(entry);
    }
    if (!claimed.length) continue;

    let entityId = batch.entityId;
    try {
      if (batch.needsReportCreate) {
        const draftPayload = claimed.find((item) => item.draftPayload)?.draftPayload;
        if (!draftPayload) throw new Error('Missing offline draft payload');
        if (!(await canSync(scope))) return;
        const report = await createDailyReport(draftPayload, batch.entityId, scope);
        entityId = report.id;
        await updateClaims(scope, claimed, { entityId });
        if (report.status !== 'draft') {
          conflicts += claimed.length;
          await updateClaims(scope, claimed, { status: 'server_newer' });
          continue;
        }
      }

      for (const item of claimed) {
        if (!(await canSync(scope))) return;
        try {
          const dataTransfer = new DataTransfer();
          dataTransfer.items.add(item.file);
          await uploadEntityFiles({
            entityType: item.entityType,
            entityId,
            kind: item.kind,
            files: dataTransfer.files,
            idempotencyKey: item.id,
            scope
          });
          await updateClaims(scope, [item]);
        } catch {
          await updateClaims(scope, [item], { entityId, status: 'failed' });
        }
      }
    } catch {
      await updateClaims(scope, claimed, { entityId, status: 'failed' });
    }
  }
  if (await canSync(scope)) publishSyncResult(scope, conflicts);
}
