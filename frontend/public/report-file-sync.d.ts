export type QueuedFileKind = 'photo' | 'attachment';
export type UploadIntent = {
  reportId: string;
  expectedRevision: number;
  kind: QueuedFileKind;
};
export type UploadFailure =
  { state: 'blocked'; reason: string; conflict?: boolean } | { state: 'suspended' | 'retry' };

export function classifyQueuedReportFile(file: File, kind: QueuedFileKind): Promise<QueuedFileKind>;
export function uploadFailure(status?: number, code?: string, cancelled?: boolean): UploadFailure;
export function uploadRetry(
  attempts: number,
  force: boolean,
  now?: number
): { attempts: number; retryAfter: number };
export function sameUploadIntent(left: UploadIntent | undefined, right: UploadIntent): boolean;
export function commitUploadReceipt(
  tx: IDBTransaction,
  queueStore: string,
  draftStore: string,
  file: {
    id: string;
    claimId?: string;
    namespace: string;
    ownerUserId: string;
    localDraftId: string;
  },
  intent: UploadIntent,
  revision: number | undefined,
  result: (value: boolean) => void
): void;
