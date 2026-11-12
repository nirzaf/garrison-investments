// Shared by the app and worker. Keep accepted bytes and route limits aligned with the API.
const maxFileBytes = 10 * 1024 * 1024;
const blockedExtension = /\.(exe|sh|bat|cmd|js|ps1|php|py)$/i;

export async function classifyQueuedReportFile(file, kind) {
  if (file.size > maxFileBytes) throw new Error('File exceeds the 10 MiB limit.');
  if (blockedExtension.test(file.name)) throw new Error('File type is blocked.');
  const bytes = new Uint8Array(await file.slice(0, 32).arrayBuffer());
  const starts = (signature) => signature.every((byte, index) => bytes[index] === byte);
  if (starts([0x25, 0x50, 0x44, 0x46, 0x2d])) return 'attachment';
  if (starts([0xff, 0xd8, 0xff]) || starts([0x89, 0x50, 0x4e, 0x47, 0x0d, 0x0a, 0x1a, 0x0a])) {
    return kind;
  }
  if (/^ftyp(heic|heix|hevc|mif1)/.test(String.fromCharCode(...bytes.subarray(4, 12)))) {
    if (kind === 'attachment') throw new Error('Select PDF, JPEG, or PNG for attachments.');
    return 'photo';
  }
  throw new Error('Unsupported file type.');
}

export function uploadFailure(status, code, cancelled = false) {
  if (cancelled || status === 401 || status === 403) return { state: 'suspended' };
  if (
    code === 'DAILY_REPORT_REVISION_CONFLICT' ||
    code === 'PHOTO_UPLOAD_LOCKED' ||
    status === 404
  ) {
    return {
      state: 'blocked',
      conflict: true,
      reason: 'The report changed or is no longer editable.'
    };
  }
  if (code === 'REPORT_PHOTO_LIMIT_REACHED') {
    return { state: 'blocked', reason: 'The report already has five active photos.' };
  }
  if (status === 413) return { state: 'blocked', reason: 'File exceeds the upload limit.' };
  if (status !== undefined && status < 500 && status !== 408 && status !== 429) {
    return {
      state: 'blocked',
      reason: 'The server rejected this file. Check its format or report.'
    };
  }
  return { state: 'retry' };
}

export function uploadRetry(attempts, force, now = Date.now()) {
  const nextAttempt = force && attempts >= 4 ? 1 : attempts + 1;
  return {
    attempts: nextAttempt,
    retryAfter: nextAttempt >= 4 ? Number.MAX_SAFE_INTEGER : now + 1000 * 2 ** nextAttempt
  };
}

export function sameUploadIntent(left, right) {
  return (
    left?.reportId === right.reportId &&
    left.expectedRevision === right.expectedRevision &&
    left.kind === right.kind
  );
}

export function commitUploadReceipt(tx, queueStore, draftStore, file, intent, revision, result) {
  if (revision !== intent.expectedRevision + 1) return;
  const queue = tx.objectStore(queueStore);
  const queued = queue.get(file.id);
  queued.onsuccess = () => {
    const current = queued.result;
    if (
      current?.claimId !== file.claimId ||
      current?.namespace !== file.namespace ||
      current?.ownerUserId !== file.ownerUserId ||
      !sameUploadIntent(current.intent, intent)
    )
      return;

    const drafts = tx.objectStore(draftStore);
    const report = drafts.get([file.namespace, file.ownerUserId, file.localDraftId]);
    report.onsuccess = () => {
      const draft = report.result;
      // Advance only this draft's acknowledged base. Preserve newer local edits and any
      // already observed server conflict. A real receipt still resolves the uploaded file.
      if (
        draft?.serverReport?.id === intent.reportId &&
        draft.baseServerRevision === intent.expectedRevision
      ) {
        drafts.put({ ...draft, baseServerRevision: revision });
      }
      queue.delete(file.id);
      result(true);
    };
  };
}
