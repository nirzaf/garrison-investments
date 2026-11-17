import { describe, expect, it } from 'vitest';

import { planSyncBatches, type QueuedPhoto } from './offlineQueue';

function photo(overrides: Partial<QueuedPhoto> = {}): QueuedPhoto {
  return {
    id: crypto.randomUUID(),
    namespace: 'app-and-api-a',
    ownerUserId: 'owner-a',
    localDraftId: 'draft-a',
    entityType: 'daily_report',
    entityId: 'local-abc',
    kind: 'photo',
    file: new File(['bytes'], 'site.jpg', { type: 'image/jpeg' }),
    createdAt: '2026-05-29T08:00:00.000Z',
    claimedAt: '',
    status: 'queued',
    ...overrides
  };
}

describe('planSyncBatches', () => {
  it('groups files by local draft after some have a known server ID', () => {
    const items = [photo(), photo({ entityId: '11111111-1111-1111-1111-111111111111' }), photo()];
    expect(planSyncBatches(items)).toEqual([{ localDraftId: 'draft-a', items }]);
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

  it('preserves the identity of a file whose upload receipt is pending', () => {
    const item = photo({
      status: 'failed',
      intent: { reportId: 'report-1', expectedRevision: 3, kind: 'attachment' }
    });
    expect(planSyncBatches([item])[0].items[0]).toEqual(item);
  });

  it('skips blocked, superseded, and already uploaded files', () => {
    const pending = photo({ status: 'failed' });
    const batches = planSyncBatches([
      photo({ status: 'blocked' }),
      photo({ status: 'server_newer' }),
      photo({ status: 'synced' }),
      pending
    ]);
    expect(batches[0].items).toEqual([pending]);
  });

  it('returns no batches for an empty queue', () => {
    expect(planSyncBatches([])).toEqual([]);
  });
});

const fileRulesUrl = new URL('../../public/report-file-sync.js', import.meta.url).href;
const fileRules = (await import(
  /* @vite-ignore */ fileRulesUrl
)) as typeof import('../../public/report-file-sync.js');

describe('queued report file rules shared with the worker', () => {
  it('accepts JPEG bytes at 10 MiB and rejects one extra byte', async () => {
    const boundary = new Uint8Array(10 * 1024 * 1024);
    boundary.set([0xff, 0xd8, 0xff]);
    await expect(
      fileRules.classifyQueuedReportFile(new File([boundary], 'site.jpg'), 'photo')
    ).resolves.toBe('photo');
    await expect(
      fileRules.classifyQueuedReportFile(new File([boundary, 'x'], 'site.jpg'), 'photo')
    ).rejects.toThrow('10 MiB');
  });

  it('classifies real PDF and HEIC headers and rejects unsupported attachment formats', async () => {
    await expect(
      fileRules.classifyQueuedReportFile(new File(['%PDF-'], 'site.pdf'), 'photo')
    ).resolves.toBe('attachment');
    const heic = new File(['0000ftypheic'], 'site.heic');
    await expect(fileRules.classifyQueuedReportFile(heic, 'photo')).resolves.toBe('photo');
    await expect(fileRules.classifyQueuedReportFile(heic, 'attachment')).rejects.toThrow(
      'attachments'
    );
  });

  it('does not trust a claimed MIME type or allow blocked extensions', async () => {
    await expect(
      fileRules.classifyQueuedReportFile(
        new File(['text'], 'site.jpg', { type: 'image/jpeg' }),
        'photo'
      )
    ).rejects.toThrow('Unsupported file type.');
    await expect(
      fileRules.classifyQueuedReportFile(
        new File([new Uint8Array([0xff, 0xd8, 0xff])], 'site.sh'),
        'photo'
      )
    ).rejects.toThrow('File type is blocked.');
  });

  it('separates permanent quota and revision errors from auth and transport failures', () => {
    expect(fileRules.uploadFailure(409, 'REPORT_PHOTO_LIMIT_REACHED')).toEqual({
      state: 'blocked',
      reason: 'The report already has five active photos.'
    });
    expect(fileRules.uploadFailure(409, 'DAILY_REPORT_REVISION_CONFLICT')).toMatchObject({
      state: 'blocked',
      conflict: true
    });
    expect(fileRules.uploadFailure(403)).toEqual({ state: 'suspended' });
    expect(fileRules.uploadFailure(503)).toEqual({ state: 'retry' });
  });

  it('caps automatic retry attempts and honors a new explicit retry', () => {
    expect(fileRules.uploadRetry(1, false, 1000)).toEqual({ attempts: 2, retryAfter: 5000 });
    expect(fileRules.uploadRetry(3, false, 1000)).toEqual({
      attempts: 4,
      retryAfter: Number.MAX_SAFE_INTEGER
    });
    expect(fileRules.uploadRetry(4, true, 1000)).toEqual({ attempts: 1, retryAfter: 3000 });
  });
});

const draftSyncUrl = new URL('../../public/report-draft-sync.js', import.meta.url).href;
const draftSync = (await import(
  /* @vite-ignore */ draftSyncUrl
)) as typeof import('../../public/report-draft-sync.js');

describe('queued report draft sync invariants shared with the worker', () => {
  const validPayload = {
    project_id: '11111111-1111-1111-1111-111111111111',
    report_date: '2026-11-17',
    work_location: 'Block A',
    work_completed: 'Slab pour',
    next_day_plan: 'Curing',
    progress_percentage: 45,
    inspection_status: 'passed',
    manpower_total: 0,
    overtime_hours: 0,
    safety_incidents: 0,
    wir_status: 'not_required',
    supervisor_update_ids: [],
    photo_refs: [],
    attachment_refs: [],
    extra_fields: {
      weather_condition: 'Clear',
      site_visitors: 'None',
      subcontractors: 'None',
      wir_number: 'WIR-101'
    },
    manpower_entries: [],
    equipment_entries: [],
    material_consumption: []
  };

  it('retains pendingCreate across retries and suspends cleanly on 401 sign-out mid-sync', async () => {
    const remembered: unknown[] = [];
    const createdPayloads: unknown[] = [];
    const outcome = await draftSync.persistOwnedDraft(
      {
        localDraftId: 'draft-1',
        localRevision: 2,
        lastSyncedLocalRevision: 0,
        pendingCreate: { revision: 1, payload: validPayload },
        payload: { ...validPayload, work_completed: 'Local edit 2' }
      },
      {
        rememberCreate: async (pending) => {
          remembered.push(pending);
          return true;
        },
        create: async (payload) => {
          createdPayloads.push(payload);
          throw { status: 401 };
        },
        update: async () => {
          throw new Error('unexpected update');
        },
        acknowledge: async () => {
          throw new Error('unexpected acknowledge');
        },
        status: (error) => (error as { status?: number })?.status,
        cancelled: () => false
      }
    );
    expect(outcome).toBe('suspended');
    expect(remembered).toEqual([{ revision: 1, payload: validPayload }]);
    expect(createdPayloads).toEqual([validPayload]);
  });

  it('preserves local draft as conflict on 409 revision mismatch and retries on 503', async () => {
    const baseDraft = {
      localDraftId: 'draft-2',
      localRevision: 3,
      lastSyncedLocalRevision: 1,
      baseServerRevision: 1,
      serverReport: { id: 'rep-1', engineerId: 'eng-1' },
      payload: validPayload
    };
    const conflictOutcome = await draftSync.persistOwnedDraft(baseDraft, {
      rememberCreate: async () => true,
      create: async () => {
        throw new Error('unexpected create');
      },
      update: async () => {
        throw { status: 409 };
      },
      acknowledge: async () => {},
      status: (error) => (error as { status?: number })?.status,
      cancelled: () => false
    });
    expect(conflictOutcome).toBe('conflict');

    const retryOutcome = await draftSync.persistOwnedDraft(baseDraft, {
      rememberCreate: async () => true,
      create: async () => {
        throw new Error('unexpected create');
      },
      update: async () => {
        throw { status: 503 };
      },
      acknowledge: async () => {},
      status: (error) => (error as { status?: number })?.status,
      cancelled: () => false
    });
    expect(retryOutcome).toBe('retry');
  });
});
