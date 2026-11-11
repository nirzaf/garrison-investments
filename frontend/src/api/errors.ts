import { isAxiosError } from 'axios';

export function formatApiError(error: unknown, fallback: string): string {
  if (!isAxiosError<{ detail?: unknown }>(error)) return fallback;
  const detail = error.response?.data?.detail;
  if (typeof detail === 'string') return detail.trim() || fallback;

  const entries = Array.isArray(detail) ? detail : [detail];
  const messages = entries.flatMap((entry: unknown) => {
    if (typeof entry !== 'object' || entry === null || !('msg' in entry)) return [];
    if (typeof entry.msg !== 'string' || !entry.msg.trim()) return [];
    const path =
      'loc' in entry && Array.isArray(entry.loc)
        ? entry.loc.filter((part: unknown) => typeof part === 'string' || typeof part === 'number')
        : [];
    const field = path.filter((part) => part !== 'body').join('.');
    return [field ? `${field}: ${entry.msg}` : entry.msg];
  });
  return messages.join(' ') || fallback;
}
