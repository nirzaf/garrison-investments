import { getBrowserSession } from './browserSession';

type BrowserSession = NonNullable<ReturnType<typeof getBrowserSession>>;

const requestIdPattern = /^(?:[a-f0-9]{32}|[a-f0-9]{8}(?:-[a-f0-9]{4}){3}-[a-f0-9]{12})$/;
const recent = new WeakMap<BrowserSession, Map<string, number>>();
const retentionMs = 30 * 60_000;
const maxRequests = 8;

export function rememberFeedbackRequest(session: BrowserSession, requestId: unknown) {
  if (typeof requestId !== 'string' || !requestIdPattern.test(requestId)) return;
  const references = recent.get(session) ?? new Map();
  references.delete(requestId);
  references.set(requestId, Date.now());
  for (const [id, recordedAt] of references) {
    if (Date.now() - recordedAt >= retentionMs || references.size > maxRequests)
      references.delete(id);
  }
  recent.set(session, references);
}

export function recentFeedbackRequests() {
  const session = getBrowserSession();
  if (!session) return [];
  return [...(recent.get(session) ?? [])]
    .filter(([, recordedAt]) => Date.now() - recordedAt < retentionMs)
    .map(([id]) => id)
    .reverse();
}
