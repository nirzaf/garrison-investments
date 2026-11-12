const url = '/report-draft-sync.js';

type DraftSyncModule = typeof import('../../public/report-draft-sync.js');

export function getReportDraftSync(): Promise<DraftSyncModule> {
  return import(/* @vite-ignore */ url) as Promise<DraftSyncModule>;
}

const fileSyncUrl = '/report-file-sync.js';
type ReportFileSyncModule = typeof import('../../public/report-file-sync.js');

export function getReportFileSync(): Promise<ReportFileSyncModule> {
  return import(/* @vite-ignore */ fileSyncUrl) as Promise<ReportFileSyncModule>;
}
