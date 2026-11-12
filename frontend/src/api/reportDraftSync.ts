const url = '/report-draft-sync.js';

type DraftSyncModule = typeof import('../../public/report-draft-sync.js');

export function getReportDraftSync(): Promise<DraftSyncModule> {
  return import(/* @vite-ignore */ url) as Promise<DraftSyncModule>;
}
