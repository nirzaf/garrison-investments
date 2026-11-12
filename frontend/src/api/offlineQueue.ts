// Authoritative offline photo-queue drain.
//
// `public/sw.js` keeps a standalone fallback for the no-window-client case and delegates
// here whenever a window is open. Any change to the batching, claim, or idempotency rules
// must be mirrored there — `planSyncBatches` is the shared, unit-tested seam.
import axios from 'axios';
import type { DraftSyncState, SyncDraft } from '../../public/report-draft-sync.js';
import type { UploadIntent } from '../../public/report-file-sync.js';
import { getReportDraftSync, getReportFileSync } from './reportDraftSync';
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
  withOwnedOfflineTransaction,
  type OfflineScope
} from './offlineDb';
import { uploadEntityFilesWithRevision } from './photos';
import { createDailyReport, updateDailyReport, type DailyReportPayload } from './reports';

/** A claim older than this is assumed dead (tab closed mid-upload) and may be reclaimed. */
const STALE_CLAIM_MS = 5 * 60_000;

export type QueuedPhoto = {
  id: string;
  namespace: string;
  ownerUserId: string;
  localDraftId: string;
  entityType: string;
  entityId: string;
  kind: 'photo' | 'attachment';
  file: File;
  createdAt: string;
  claimedAt: string;
  claimId?: string;
  claimGeneration?: string;
  status: 'queued' | 'syncing' | 'failed' | 'blocked' | 'suspended' | 'synced' | 'server_newer';
  intent?: UploadIntent;
  reason?: string;
  attempts?: number;
  retryAfter?: number;
};

export type SyncBatch = { localDraftId: string; items: QueuedPhoto[] };

export function planSyncBatches(items: QueuedPhoto[]): SyncBatch[] {
  const batches = new Map<string, SyncBatch>();
  for (const item of items) {
    if (isBlocked(item) || item.status === 'synced') continue;
    const key = JSON.stringify([item.namespace, item.ownerUserId, item.localDraftId]);
    let batch = batches.get(key);
    if (!batch) {
      batch = { localDraftId: item.localDraftId, items: [] };
      batches.set(key, batch);
    }
    batch.items.push(item);
  }
  return [...batches.values()];
}

function isBlocked(item: QueuedPhoto): boolean {
  return item.status === 'blocked' || item.status === 'server_newer';
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

export async function acknowledgeReportEvidenceRevision(
  scope: OfflineScope,
  localDraftId: string,
  reportId: string,
  previousRevision: number,
  nextRevision: number
): Promise<void> {
  await editReportDraft(scope, localDraftId, (draft) => {
    if (draft?.serverReport?.id !== reportId || draft.baseServerRevision !== previousRevision) {
      return undefined;
    }
    return { ...draft, baseServerRevision: nextRevision };
  });
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

async function listQueuedPhotos(
  scope: OfflineScope,
  localDraftId?: string
): Promise<QueuedPhoto[]> {
  const queued = await withOwnedOfflineData<QueuedPhoto[]>(
    scope,
    PHOTO_QUEUE,
    'readonly',
    (queue, result) => {
      const request = localDraftId
        ? queue.index('byOwnerDraft').getAll([...ownerKey(scope), localDraftId])
        : queue.index(OWNER_INDEX).getAll(ownerKey(scope));
      request.onsuccess = () => result(request.result as QueuedPhoto[]);
    }
  );
  return queued ?? [];
}

export async function queuedPhotoCount(scope: OfflineScope): Promise<number> {
  return (await listQueuedPhotos(scope)).filter(
    (item) => !isBlocked(item) && item.status !== 'synced'
  ).length;
}

export type QueuedUploadIssue = { id: string; name: string; reason: string; canRetry: boolean };

function needsAttention(item: QueuedPhoto): boolean {
  return isBlocked(item) || (item.status === 'failed' && (item.attempts ?? 0) >= 4);
}

export async function getQueuedUploadIssues(scope: OfflineScope): Promise<QueuedUploadIssue[]> {
  return (await listQueuedPhotos(scope)).filter(needsAttention).map((item) => ({
    id: item.id,
    name: item.file.name,
    reason:
      item.reason ??
      (isBlocked(item)
        ? 'The server report changed before this file could be uploaded.'
        : 'Upload confirmation is pending. Retry or remove the local copy.'),
    canRetry: !isBlocked(item)
  }));
}

export async function removeQueuedUploadIssue(scope: OfflineScope, id: string): Promise<void> {
  await withOwnedOfflineData(scope, PHOTO_QUEUE, 'readwrite', (queue) => {
    const request = queue.get(id);
    request.onsuccess = () => {
      const item = request.result as QueuedPhoto | undefined;
      if (
        item?.ownerUserId === scope.ownerUserId &&
        item.namespace === scope.namespace &&
        needsAttention(item)
      )
        queue.delete(id);
    };
  });
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
        result(
          (request.result as QueuedPhoto[]).filter(
            (entry) => entry.kind === 'photo' && !isBlocked(entry) && entry.status !== 'synced'
          ).length
        );
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

function claimQueuedPhoto(
  scope: OfflineScope,
  id: string,
  hasLock: boolean,
  force: boolean
): Promise<QueuedPhoto | undefined> {
  return withOwnedOfflineData<QueuedPhoto>(scope, PHOTO_QUEUE, 'readwrite', (queue, result) => {
    const request = queue.get(id);
    request.onsuccess = () => {
      const item = request.result as QueuedPhoto | undefined;
      if (
        !item ||
        item.ownerUserId !== scope.ownerUserId ||
        item.namespace !== scope.namespace ||
        isBlocked(item) ||
        item.status === 'synced' ||
        (item.status === 'suspended' && item.claimGeneration === scope.generation) ||
        (!force && (item.retryAfter ?? 0) > Date.now())
      )
        return;
      if (
        !hasLock &&
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

type QueuePatch = Partial<
  Pick<QueuedPhoto, 'status' | 'reason' | 'attempts' | 'retryAfter' | 'intent'>
>;

function patchClaim(
  scope: OfflineScope,
  claim: QueuedPhoto,
  patch: QueuePatch
): Promise<QueuedPhoto | undefined> {
  return withOwnedOfflineData<QueuedPhoto>(scope, PHOTO_QUEUE, 'readwrite', (queue, result) => {
    const request = queue.get(claim.id);
    request.onsuccess = () => {
      const current = request.result as QueuedPhoto | undefined;
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

function publishSyncResult(scope: OfflineScope, conflicts: number): void {
  if (!sameScope(getBrowserSession()?.scope, scope)) return;
  window.dispatchEvent(
    new CustomEvent('photo-queue-sync-complete', { detail: { scope, conflicts } })
  );
}

async function canSync(scope: OfflineScope): Promise<boolean> {
  return (await isActiveOfflineScope(scope)) && sameScope(getBrowserSession()?.scope, scope);
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

async function syncQueuedPhoto(
  scope: OfflineScope,
  item: QueuedPhoto,
  draft: LocalReportDraft | undefined,
  hasLock: boolean,
  force: boolean
): Promise<'saved' | 'blocked' | 'conflict' | 'pending' | 'waiting'> {
  if (!(await canSync(scope))) return 'pending';
  const claim = await claimQueuedPhoto(scope, item.id, hasLock, force);
  if (!claim) {
    const retryAfter = item.retryAfter ?? 0;
    if (item.status === 'failed' && (item.attempts ?? 0) < 4 && retryAfter > Date.now()) {
      scheduleRetry(scope, retryAfter);
    }
    return 'pending';
  }
  const rules = await getReportFileSync();
  let kind: QueuedPhoto['kind'];
  try {
    kind = await rules.classifyQueuedReportFile(claim.file, claim.kind);
  } catch (error) {
    await patchClaim(scope, claim, {
      status: 'blocked',
      reason: error instanceof Error ? error.message : 'File could not be read.'
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
    if (!(await patchClaim(scope, claim, { intent })) || !(await canSync(scope))) return 'pending';
    const uploaded = await uploadEntityFilesWithRevision({
      entityType: claim.entityType,
      entityId: intent.reportId,
      kind: intent.kind,
      files: [claim.file],
      idempotencyKey: claim.id,
      expectedReportRevision: intent.expectedRevision,
      scope
    });
    if (uploaded.reportRevision === intent.expectedRevision + 1) {
      const saved = await withOwnedOfflineTransaction<boolean>(
        scope,
        [PHOTO_QUEUE, REPORT_DRAFTS],
        'readwrite',
        (tx, result) =>
          rules.commitUploadReceipt(
            tx,
            PHOTO_QUEUE,
            REPORT_DRAFTS,
            claim,
            intent,
            uploaded.reportRevision,
            result
          )
      );
      return saved ? 'saved' : 'pending';
    }
  } catch (error) {
    const response = axios.isAxiosError<{ error_code?: string }>(error)
      ? error.response
      : undefined;
    const failure = rules.uploadFailure(
      response?.status,
      response?.data?.error_code,
      axios.isCancel(error)
    );
    if (failure.state === 'suspended') {
      await patchClaim(scope, claim, { status: 'suspended' });
      return 'pending';
    }
    if (failure.state === 'blocked') {
      await patchClaim(scope, claim, { status: 'blocked', reason: failure.reason });
      if (failure.conflict) {
        await editReportDraft(scope, claim.localDraftId, (latest) =>
          latest ? { ...latest, syncState: 'conflict' } : undefined
        );
        return 'conflict';
      }
      return 'blocked';
    }
  }

  const retry = rules.uploadRetry(claim.attempts ?? 0, force);
  await patchClaim(scope, claim, { status: 'failed', ...retry });
  if (retry.attempts < 4) scheduleRetry(scope, retry.retryAfter);
  return 'pending';
}

async function syncOwnedDraft(
  scope: OfflineScope,
  localDraftId: string,
  hasLock: boolean,
  force: boolean
): Promise<number> {
  if (!(await canSync(scope))) return 0;
  const actor = await getMe(scope).catch(() => null);
  if (actor?.id !== scope.ownerUserId || !(await canSync(scope))) return 0;
  const queued = (await listQueuedPhotos(scope, localDraftId)).filter(
    (item) => !isBlocked(item) && item.status !== 'synced'
  );

  // Recover an acknowledged upload before comparing or changing the draft's base revision.
  for (const item of queued) {
    if (!item.intent) continue;
    const result = await syncQueuedPhoto(scope, item, undefined, hasLock, force);
    if (result === 'conflict') return 1;
    if (result === 'pending') return 0;
  }

  const original = await getReportDraft(scope, localDraftId);
  if (original && original.lastSyncedLocalRevision < original.localRevision) {
    if (
      !force &&
      original.syncState === 'retry' &&
      original.attempts < 4 &&
      original.retryAfter > Date.now()
    )
      scheduleRetry(scope, original.retryAfter);
    await persistReportDraft(scope, localDraftId, force, hasLock);
  }
  let draft = await getReportDraft(scope, localDraftId);
  for (const item of queued) {
    if (item.intent) continue;
    const result = await syncQueuedPhoto(scope, item, draft, hasLock, force);
    if (result === 'conflict') return 1;
    if (result === 'pending') break;
    draft = await getReportDraft(scope, localDraftId);
  }
  return 0;
}

async function drainPhotoQueue(scope: OfflineScope, force: boolean): Promise<void> {
  const draftIds = new Set([
    ...((await listReportDrafts(scope)) ?? [])
      .filter((draft) => draft.lastSyncedLocalRevision < draft.localRevision)
      .map((draft) => draft.localDraftId),
    ...planSyncBatches(await listQueuedPhotos(scope)).map((batch) => batch.localDraftId)
  ]);
  let conflicts = 0;
  for (const localDraftId of draftIds) {
    if (!(await canSync(scope))) return;
    const lockName = `garrisons-draft-sync:${JSON.stringify([...ownerKey(scope), localDraftId])}`;
    conflicts += navigator.locks
      ? await navigator.locks.request(lockName, () =>
          syncOwnedDraft(scope, localDraftId, true, force)
        )
      : await syncOwnedDraft(scope, localDraftId, false, force);
  }
  if (await canSync(scope)) publishSyncResult(scope, conflicts);
}
