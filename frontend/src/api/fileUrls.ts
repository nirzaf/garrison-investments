const INTERNAL_MINIO_HOSTS = new Set(['minio', 'minio:9000', 'localhost:9000']);
const LOCAL_BROWSER_HOSTS = new Set(['localhost', '127.0.0.1', '[::1]']);

export function normalizeProtectedFileUrl(url: string) {
  if (typeof window === 'undefined') return url;

  try {
    const parsed = new URL(url);
    if (!INTERNAL_MINIO_HOSTS.has(parsed.host) && !INTERNAL_MINIO_HOSTS.has(parsed.hostname)) {
      return url;
    }
    if (!LOCAL_BROWSER_HOSTS.has(window.location.hostname)) {
      return url;
    }

    parsed.hostname = window.location.hostname || 'localhost';
    if (!parsed.port) parsed.port = '9000';
    return parsed.toString();
  } catch {
    return url;
  }
}
