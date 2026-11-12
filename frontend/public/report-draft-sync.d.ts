import type { DailyReportPayload, DailyReportRecord } from '../src/api/reports';

export type CreateAttempt = { revision: number; payload: DailyReportPayload };
export type DraftSyncState = 'local' | 'saved' | 'conflict' | 'blocked' | 'retry' | 'suspended';
export type SyncDraft = {
  localDraftId: string;
  localRevision: number;
  lastSyncedLocalRevision: number;
  baseServerRevision?: number;
  serverReport?: { id: string; engineerId: string };
  pendingCreate?: CreateAttempt;
  payload: DailyReportPayload;
};
export type DraftSyncAdapter = {
  update: (
    reportId: string,
    payload: DailyReportPayload,
    revision: number
  ) => Promise<DailyReportRecord>;
  create: (payload: DailyReportPayload, localDraftId: string) => Promise<DailyReportRecord>;
  rememberCreate: (attempt: CreateAttempt) => Promise<boolean>;
  acknowledge: (sentRevision: number, report: DailyReportRecord) => Promise<void>;
  status: (error: unknown) => number | undefined;
  cancelled: (error: unknown) => boolean;
};

export function reportPayload(payload: DailyReportPayload): DailyReportPayload;
export function reportDraftErrors(payload: DailyReportPayload): Record<string, string>;
export function persistOwnedDraft(
  draft: SyncDraft,
  adapter: DraftSyncAdapter
): Promise<DraftSyncState>;
