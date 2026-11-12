// Authoritative offline photo-queue drain.
//
// `public/sw.js` keeps a standalone fallback for the no-window-client case and delegates
// here whenever a window is open. Any change to the batching, claim, or idempotency rules
// must be mirrored there — `planSyncBatches` is the shared, unit-tested seam.
import axios from 'axios';
import type { DraftSyncState, SyncDraft } from '../../public/report-draft-sync.js';
import { getReportDraftSync } from './reportDraftSync';
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
import { uploadEntityFilesWithRevision } from './photos';
import {
  createDailyReport,
  getDailyReport,
  updateDailyReport,
  type DailyReportPayload
} from './reports';

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

type SavedReportReference = { id: string; engineerId: string; revision?: number };

export type LocalReportDraft = SyncDraft & {
  namespace: string;
  ownerUserId: string;
  savedAt: string;
  syncState: DraftSyncState;
  attempts: number;
  retryAfter: number;
  claim?: { id: string; generation: string; expiresAt: number };
};

function initializeDraft(draft: LocalReportDraft): LocalReportDraft {
  return {
    ...draft,
    localRevision: draft.localRevision ?? 1,
    lastSyncedLocalRevision: draft.lastSyncedLocalRevision ?? 0,
    syncState: draft.syncState ?? 'local',
    attempts: draft.attempts ?? 0,
    retryAfter: draft.retryAfter ?? 0
  };
}

async function editReportDraft(
  scope: OfflineScope,
  localDraftId: string,
  edit: (previous: LocalReportDraft | undefined) => LocalReportDraft | undefined
): Promise<LocalReportDraft | undefined> {
  return withOwnedOfflineData<LocalReportDraft>(
    scope,
    REPORT_DRAFTS,
    'readwrite',
    (drafts, result) => {
      const request = drafts.get([...ownerKey(scope), localDraftId]);
      request.onsuccess = () => {
        const previous = request.result
          ? initializeDraft(request.result as LocalReportDraft)
          : undefined;
        const updated = edit(previous);
        if (updated) {
          drafts.put(updated);
          result(updated);
        }
      };
    }
  );
}

export async function saveReportDraft(
  scope: OfflineScope,
  payload: DailyReportPayload,
  localDraftId: string,
  serverReport?: SavedReportReference,
  serverSnapshot = false
): Promise<boolean> {
  const saved = await editReportDraft(scope, localDraftId, (previous) => {
    if (
      previous &&
      !serverSnapshot &&
      JSON.stringify(previous.payload) === JSON.stringify(payload)
    ) {
      return previous;
    }
    const localRevision = (previous?.localRevision ?? 0) + 1;
    return {
      ...previous,
      namespace: scope.namespace,
      ownerUserId: scope.ownerUserId,
      localDraftId,
      payload,
      serverReport: serverSnapshot ? serverReport : (previous?.serverReport ?? serverReport),
      baseServerRevision: serverSnapshot
        ? serverReport?.revision
        : (previous?.baseServerRevision ?? serverReport?.revision),
      savedAt: new Date().toISOString(),
      localRevision,
      lastSyncedLocalRevision: serverSnapshot
        ? localRevision
        : (previous?.lastSyncedLocalRevision ?? 0),
      syncState: serverSnapshot
        ? 'saved'
        : previous?.syncState === 'conflict'
          ? 'conflict'
          : 'local',
      attempts: 0,
      retryAfter: 0,
      pendingCreate: serverSnapshot ? undefined : previous?.pendingCreate
    };
  });
  return saved !== undefined;
}

function listReportDrafts(scope: OfflineScope): Promise<LocalReportDraft[] | undefined> {
  return withOwnedOfflineData<LocalReportDraft[]>(
    scope,
    REPORT_DRAFTS,
    'readonly',
    (drafts, result) => {
      const request = drafts.index(OWNER_INDEX).getAll(ownerKey(scope));
      request.onsuccess = () => result((request.result as LocalReportDraft[]).map(initializeDraft));
    }
  );
}

export async function getReportDraft(
  scope: OfflineScope,
  localDraftId?: string
): Promise<LocalReportDraft | undefined> {
  if (!localDraftId) {
    const owned = await listReportDrafts(scope);
    return owned?.sort((left, right) => right.savedAt.localeCompare(left.savedAt))[0];
  }
  return withOwnedOfflineData<LocalReportDraft>(
    scope,
    REPORT_DRAFTS,
    'readonly',
    (drafts, result) => {
      const request = drafts.get([...ownerKey(scope), localDraftId]);
      request.onsuccess = () => {
        if (request.result) result(initializeDraft(request.result as LocalReportDraft));
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
let retryTimer: { scope: OfflineScope; at: number; id: number } | undefined;

export function isReportSyncActive(scope: OfflineScope): boolean {
  return sameScope(currentFlush?.scope, scope);
}

function scheduleRetry(scope: OfflineScope, at: number): void {
  if (retryTimer && sameScope(retryTimer.scope, scope) && retryTimer.at <= at) return;
  if (retryTimer) window.clearTimeout(retryTimer.id);
  const id = window.setTimeout(
    () => {
      retryTimer = undefined;
      if (navigator.onLine && sameScope(getBrowserSession()?.scope, scope)) {
        void flushPhotoQueue().catch(() => {});
      }
    },
    Math.max(at - Date.now(), 0)
  );
  retryTimer = { scope, at, id };
}

export async function flushPhotoQueue(force = false): Promise<void> {
  const scope = getBrowserSession()?.scope;
  if (!scope) return;
  if (currentFlush && sameScope(currentFlush.scope, scope)) {
    if (!force) return currentFlush.result;
    await currentFlush.result;
    if (!sameScope(getBrowserSession()?.scope, scope)) return;
  }

  const result = drainPhotoQueue(scope, force).finally(() => {
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

async function syncReportDraft(scope: OfflineScope, localDraftId: string, force: boolean) {
  const lockName = `garrisons-draft-sync:${JSON.stringify([...ownerKey(scope), localDraftId])}`;
  if (navigator.locks) {
    await navigator.locks.request(lockName, () =>
      persistReportDraft(scope, localDraftId, force, true)
    );
  } else {
    await persistReportDraft(scope, localDraftId, force, false);
  }
}

async function persistReportDraft(
  scope: OfflineScope,
  localDraftId: string,
  force: boolean,
  hasLock: boolean
) {
  const sync = await getReportDraftSync();
  const claim = {
    id: crypto.randomUUID(),
    generation: scope.generation,
    expiresAt: Date.now() + STALE_CLAIM_MS
  };
  const snapshot = await editReportDraft(scope, localDraftId, (draft) => {
    if (
      !draft ||
      draft.syncState === 'conflict' ||
      draft.syncState === 'blocked' ||
      (!force && draft.retryAfter > Date.now())
    )
      return undefined;
    if (
      !hasLock &&
      draft.claim?.generation === scope.generation &&
      draft.claim.expiresAt > Date.now()
    )
      return undefined;
    return { ...draft, claim };
  });
  if (!snapshot) return;

  const patch = (change: (draft: LocalReportDraft) => LocalReportDraft) =>
    editReportDraft(scope, localDraftId, (draft) =>
      draft?.claim?.id === claim.id ? change(draft) : undefined
    );
  let outcome: DraftSyncState = 'local';
  try {
    if (!(await canSync(scope))) return;
    const actor = await getMe(scope).catch(() => null);
    if (actor?.id !== scope.ownerUserId || !(await canSync(scope))) return;
    let pending: LocalReportDraft | undefined = snapshot;
    for (let attempt = 0; pending && attempt < 3; attempt += 1) {
      outcome = await sync.persistOwnedDraft(pending, {
        update: (id, payload, revision) => updateDailyReport(id, payload, revision, scope),
        create: (payload, key) => createDailyReport(payload, key, scope),
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
        status: (error) => (axios.isAxiosError(error) ? error.response?.status : undefined),
        cancelled: axios.isCancel
      });
      if (outcome !== 'saved' || !(await canSync(scope))) break;
      pending = await getReportDraft(scope, localDraftId);
      if (!pending || pending.lastSyncedLocalRevision >= pending.localRevision) break;
      outcome = 'local';
    }
  } finally {
    const final = await patch((draft) => {
      const previousAttempts = force && draft.attempts >= 4 ? 0 : draft.attempts;
      const attempts = outcome === 'retry' ? previousAttempts + 1 : 0;
      const retryAfter = attempts > 0 ? Date.now() + 1000 * 2 ** Math.min(attempts, 5) : 0;
      return {
        ...draft,
        syncState: outcome,
        attempts,
        retryAfter: attempts >= 4 ? Number.MAX_SAFE_INTEGER : retryAfter,
        claim: undefined
      };
    });
    if (final?.syncState === 'retry' && final.attempts < 4) scheduleRetry(scope, final.retryAfter);
  }
}

export async function advanceDraftEvidenceRevision(
  scope: OfflineScope,
  localDraftId: string,
  expected: number,
  committed: number
): Promise<boolean> {
  const updated = await editReportDraft(scope, localDraftId, (draft) => {
    if (!draft || draft.baseServerRevision !== expected) return undefined;
    if (committed !== expected + 1) return { ...draft, syncState: 'conflict' };
    return { ...draft, baseServerRevision: committed };
  });
  return updated?.baseServerRevision === committed;
}

async function drainPhotoQueue(scope: OfflineScope, force: boolean): Promise<void> {
  let conflicts = 0;
  for (const draft of (await listReportDrafts(scope)) ?? []) {
    if (!(await canSync(scope))) return;
    await syncReportDraft(scope, draft.localDraftId, force);
  }
  const queued = await withOwnedOfflineData<QueuedPhoto[]>(
    scope,
    PHOTO_QUEUE,
    'readonly',
    (queue, result) => {
      const request = queue.index(OWNER_INDEX).getAll(ownerKey(scope));
      request.onsuccess = () => result(request.result as QueuedPhoto[]);
    }
  );
  for (const batch of planSyncBatches(queued ?? [])) {
    if (!(await canSync(scope))) return;
    const first = batch.items[0];
    const draft = await getReportDraft(scope, first.localDraftId);
    if (!draft?.serverReport || draft.syncState !== 'saved') continue;
    const entityId = draft.serverReport.id;
    const actor = await getMe(scope).catch(() => null);
    if (actor?.id !== scope.ownerUserId || !(await canSync(scope))) return;
    const current = await getDailyReport(entityId, scope).catch(() => null);
    if (!current) continue;
    if (current.status !== 'draft' || current.revision !== draft.baseServerRevision) {
      await editReportDraft(scope, first.localDraftId, (latest) =>
        latest ? { ...latest, syncState: 'conflict' } : undefined
      );
      conflicts += batch.items.length;
      continue;
    }

    let revision = current.revision;
    for (const item of batch.items) {
      if (!(await canSync(scope))) return;
      const claimed = await claimQueuedPhoto(scope, item.id);
      if (!claimed) continue;
      try {
        const uploaded = await uploadEntityFilesWithRevision({
          entityType: claimed.entityType,
          entityId,
          kind: claimed.kind,
          files: [claimed.file],
          idempotencyKey: claimed.id,
          expectedReportRevision: revision,
          scope
        });
        await updateClaims(scope, [claimed]);
        if (uploaded.reportRevision !== undefined) {
          const advanced = await advanceDraftEvidenceRevision(
            scope,
            first.localDraftId,
            revision,
            uploaded.reportRevision
          );
          if (!advanced) {
            conflicts += 1;
            break;
          }
          revision = uploaded.reportRevision;
        }
      } catch (error) {
        const status = axios.isAxiosError(error) ? error.response?.status : undefined;
        await updateClaims(scope, [claimed], {
          entityId,
          status:
            status && status < 500 && status !== 408 && status !== 429 ? 'server_newer' : 'failed'
        });
        if (status === 401 || status === 403 || axios.isCancel(error)) return;
        if (status === 409) {
          await editReportDraft(scope, first.localDraftId, (latest) =>
            latest ? { ...latest, syncState: 'conflict' } : undefined
          );
          conflicts += 1;
          break;
        }
      }
    }
  }
  if (await canSync(scope)) publishSyncResult(scope, conflicts);
}
