import { describe, expect, it } from 'vitest';

import { planSyncBatches, retryPatch, type QueuedPhoto } from './offlineQueue';
import type { DailyReportPayload } from './reports';

const draftPayload = { project_id: 'project-1' } as unknown as DailyReportPayload;

function photo(overrides: Partial<QueuedPhoto> = {}): QueuedPhoto {
  return {
    id: `item-${Math.random().toString(36).slice(2)}`,
    namespace: 'app-and-api-a',
    ownerUserId: 'owner-a',
    localDraftId: 'draft-a',
    entityType: 'daily_report',
    entityId: 'local-abc',
    draftPayload,
    kind: 'photo',
    file: new File(['bytes'], 'site.jpg', { type: 'image/jpeg' }),
    createdAt: '2026-05-29T08:00:00.000Z',
    claimedAt: '',
    status: 'queued',
    ...overrides
  };
}

describe('planSyncBatches', () => {
  it('plans one report create and three uploads for three photos sharing a local id', () => {
    const items = [photo(), photo(), photo()];

    const batches = planSyncBatches(items);

    expect(batches).toHaveLength(1);
    expect(batches[0].needsReportCreate).toBe(true);
    expect(batches[0].entityId).toBe('local-abc');
    expect(batches[0].items).toHaveLength(3);
    expect(batches[0].draftPayload).toBe(draftPayload);
    // One create + one upload per item, never one create per item.
    expect(batches.filter((batch) => batch.needsReportCreate)).toHaveLength(1);
  });

  it('does not plan a create for an entity that already has a server id', () => {
    const batches = planSyncBatches([
      photo({ entityId: '11111111-1111-1111-1111-111111111111' }),
      photo({ entityId: '11111111-1111-1111-1111-111111111111' })
    ]);

    expect(batches).toHaveLength(1);
    expect(batches[0].needsReportCreate).toBe(false);
    expect(batches[0].items).toHaveLength(2);
  });

  it('keeps separate local batches separate', () => {
    const batches = planSyncBatches([
      photo({ entityId: 'local-a' }),
      photo({ entityId: 'local-b' }),
      photo({ entityId: 'local-a' })
    ]);

    expect(batches).toHaveLength(2);
    expect(batches.map((batch) => batch.entityId).sort()).toEqual(['local-a', 'local-b']);
    expect(batches.every((batch) => batch.needsReportCreate)).toBe(true);
    expect(batches.find((batch) => batch.entityId === 'local-a')?.items).toHaveLength(2);
  });

  it('keeps matching entity IDs separate across owners, API environments, and drafts', () => {
    const batches = planSyncBatches([
      photo(),
      photo({ ownerUserId: 'owner-b' }),
      photo({ namespace: 'app-and-api-b' }),
      photo({ localDraftId: 'draft-b' })
    ]);
    expect(batches).toHaveLength(4);
    expect(batches.every((batch) => batch.items.length === 1)).toBe(true);
  });

  it('takes the draft payload from any sibling that carries one', () => {
    const batches = planSyncBatches([photo({ draftPayload: undefined }), photo({ draftPayload })]);

    expect(batches[0].draftPayload).toBe(draftPayload);
  });

  it('ignores items that are already synced or superseded by the server', () => {
    const batches = planSyncBatches([
      photo({ status: 'synced' }),
      photo({ status: 'server_newer' }),
      photo({ status: 'failed' })
    ]);

    expect(batches).toHaveLength(1);
    expect(batches[0].items).toHaveLength(1);
    expect(batches[0].items[0].status).toBe('failed');
  });

  it('returns no batches for an empty queue', () => {
    expect(planSyncBatches([])).toEqual([]);
  });
});

describe('retryPatch', () => {
  it('keeps the resolved server id so a retry never re-creates the report', () => {
    const item = photo();
    const serverId = '22222222-2222-2222-2222-222222222222';

    const retried = retryPatch(item, serverId);

    expect(retried.entityId).toBe(serverId);
    expect(retried.status).toBe('failed');
    expect(retried.id).toBe(item.id);

    const replanned = planSyncBatches([retried]);
    expect(replanned).toHaveLength(1);
    expect(replanned[0].needsReportCreate).toBe(false);
    expect(replanned[0].entityId).toBe(serverId);
  });

  it('keeps the local id when the create itself failed, so the retry can create it', () => {
    const item = photo();

    const retried = retryPatch(item, item.entityId);

    expect(retried.entityId).toBe('local-abc');
    expect(planSyncBatches([retried])[0].needsReportCreate).toBe(true);
  });

  it('does not mutate the original queue item', () => {
    const item = photo();

    retryPatch(item, 'server-id');

    expect(item.entityId).toBe('local-abc');
    expect(item.status).toBe('queued');
  });
});
