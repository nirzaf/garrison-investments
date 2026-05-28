const INTERNAL_MINIO_HOSTS = new Set(['minio', 'minio:9000', 'localhost:9000']);

export function normalizeProtectedFileUrl(url: string) {
  if (typeof window === 'undefined') return url;

  try {
    const parsed = new URL(url);
    if (!INTERNAL_MINIO_HOSTS.has(parsed.host) && !INTERNAL_MINIO_HOSTS.has(parsed.hostname)) {
      return url;
    }

    parsed.hostname = window.location.hostname || 'localhost';
    if (!parsed.port) parsed.port = '9000';
    return parsed.toString();
  } catch {
    return url;
  }
}
