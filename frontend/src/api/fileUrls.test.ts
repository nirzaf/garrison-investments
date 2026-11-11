import { afterEach, describe, expect, it, vi } from 'vitest';

import { normalizeProtectedFileUrl } from './fileUrls';

describe('normalizeProtectedFileUrl', () => {
  afterEach(() => {
    vi.unstubAllGlobals();
  });

  it('rewrites internal MinIO hostnames to the current browser host', () => {
    vi.stubGlobal('window', { location: { hostname: 'localhost' } });

    const normalized = normalizeProtectedFileUrl('http://minio:9000/bucket/photo.jpg?token=abc');

    expect(normalized).toBe('http://localhost:9000/bucket/photo.jpg?token=abc');
  });

  it('adds the public MinIO port when internal URL omits a port', () => {
    vi.stubGlobal('window', { location: { hostname: 'localhost' } });

    const normalized = normalizeProtectedFileUrl('http://minio/bucket/document.pdf');

    expect(normalized).toBe('http://localhost:9000/bucket/document.pdf');
  });

  it('leaves external presigned URLs unchanged', () => {
    const url = 'https://files.example.com/bucket/photo.jpg?token=abc';

    expect(normalizeProtectedFileUrl(url)).toBe(url);
  });

  it('does not rewrite internal signed URLs outside local development', () => {
    vi.stubGlobal('window', { location: { hostname: 'garrisonstg.seasonenterprise.com' } });
    const url = 'http://localhost:9000/bucket/photo.jpg?token=abc';

    expect(normalizeProtectedFileUrl(url)).toBe(url);
  });

  it('leaves malformed URLs unchanged so callers can surface the original error', () => {
    const url = 'not a url';

    expect(normalizeProtectedFileUrl(url)).toBe(url);
  });
});
