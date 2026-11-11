import { isAxiosError } from 'axios';

export function formatApiError(error: unknown, fallback: string): string {
  if (!isAxiosError<{ detail?: unknown; error_code?: string; errors?: unknown }>(error)) return fallback;
  const data = error.response?.data;
  const detail = data?.detail;
  const validationIssues = data?.error_code === 'VALIDATION_ERROR' ? data.errors : undefined;

  const entries = Array.isArray(validationIssues)
    ? validationIssues
    : Array.isArray(detail) ? detail : [detail];
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
  return messages.join(' ') || (typeof detail === 'string' ? detail.trim() : '') || fallback;
}
