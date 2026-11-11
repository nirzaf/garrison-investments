import { useQuery } from '@tanstack/react-query';
import { Camera, Download, Image, RotateCcw, ShieldCheck } from 'lucide-react';
import { useState, type ReactElement } from 'react';

import { getPhotoDownloadUrl, getPhotoThumbnailUrl, listPhotos } from '../../api/photos';
import { EmptyState } from '../../components/shared/EmptyState';
import { StatusBadge } from '../../components/shared/StatusBadge';

const mediaRules = [
  'Maximum 5 photos per daily report',
  '10 MB per photo or attachment',
  'Original, compressed display, and thumbnail variants are stored',
  'JPEG and PNG photos are watermarked with Garrisons Investments',
  'Deletes are soft deletes and remain recoverable by Admin policy'
];

export function PhotosPage() {
  const [kind, setKind] = useState<'photo' | 'attachment' | ''>('photo');
  const photos = useQuery({
    queryKey: ['photos', kind],
    queryFn: () => listPhotos({ kind: kind || undefined, limit: 100 })
  });

  async function openUrl(photoId: string, variant: 'thumbnail' | 'download') {
    const url =
      variant === 'thumbnail'
        ? await getPhotoThumbnailUrl(photoId)
        : await getPhotoDownloadUrl(photoId);
    window.open(url, '_blank', 'noopener,noreferrer');
  }

  return (
    <section className="space-y-6">
      <div className="flex flex-col justify-between gap-3 sm:flex-row sm:items-end">
        <div>
          <p className="text-sm font-medium text-brand-600">Media Evidence</p>
          <h2 className="text-2xl font-semibold text-theme-text-primary">Photos And Attachments</h2>
        </div>
        <div className="inline-flex rounded-md border border-theme-border bg-theme-card p-1">
          {(['photo', 'attachment', ''] as const).map((value) => (
            <button
              className={`rounded px-3 py-1.5 text-sm font-medium ${
                kind === value
                  ? 'bg-brand-600 text-white'
                  : 'text-theme-text-secondary hover:bg-theme-main'
              }`}
              key={value || 'all'}
              onClick={() => setKind(value)}
              type="button"
            >
              {value ? value[0].toUpperCase() + value.slice(1) : 'All'}
            </button>
          ))}
        </div>
      </div>

      <div className="grid gap-4 md:grid-cols-4">
        <MediaRule icon={<Camera className="h-5 w-5" />} label="Capture" value="Camera-ready" />
        <MediaRule icon={<Image className="h-5 w-5" />} label="Variants" value="3 versions" />
        <MediaRule icon={<ShieldCheck className="h-5 w-5" />} label="Watermark" value="Applied" />
        <MediaRule icon={<RotateCcw className="h-5 w-5" />} label="Recovery" value="Soft delete" />
      </div>

      <div className="grid gap-4 lg:grid-cols-[1fr_340px]">
        <div className="rounded-lg border border-theme-border bg-theme-card">
          <div className="border-b border-theme-border px-4 py-3">
            <h3 className="text-base font-semibold text-theme-text-primary">Recent media</h3>
          </div>
          {photos.data?.items.length ? (
            <div className="divide-y divide-theme-border">
              {photos.data.items.map((photo) => (
                <article
                  className="grid gap-3 px-4 py-3 text-sm md:grid-cols-[1fr_auto_auto]"
                  key={photo.id}
                >
                  <div>
                    <p className="font-medium text-theme-text-primary">{photo.original_name}</p>
                    <p className="text-theme-text-muted">
                      {photo.entity_type.replace(/_/g, ' ')} · {photo.kind} ·{' '}
                      {(photo.size_bytes / 1024 / 1024).toFixed(2)} MB
                    </p>
                    {photo.caption ? (
                      <p className="mt-1 text-xs text-theme-text-muted">{photo.caption}</p>
                    ) : null}
                  </div>
                  <StatusBadge tone={photo.processing_status === 'ready' ? 'success' : 'warning'}>
                    {photo.processing_status}
                  </StatusBadge>
                  <div className="flex items-center gap-2">
                    <button
                      className="rounded-md border border-theme-border px-3 py-2 text-xs font-semibold text-theme-text-secondary hover:bg-theme-main"
                      onClick={() => void openUrl(photo.id, 'thumbnail')}
                      type="button"
                    >
                      Preview
                    </button>
                    <button
                      className="inline-flex items-center gap-1 rounded-md bg-brand-600 px-3 py-2 text-xs font-semibold text-white hover:bg-brand-700"
                      onClick={() => void openUrl(photo.id, 'download')}
                      type="button"
                    >
                      <Download className="h-3.5 w-3.5" />
                      Open
                    </button>
                  </div>
                </article>
              ))}
            </div>
          ) : (
            <EmptyState
              description="Uploaded report photos and attachments will appear here."
              title={photos.isLoading ? 'Loading media' : 'No media found'}
            />
          )}
        </div>

        <aside className="rounded-lg border border-theme-border bg-theme-card p-4">
          <h3 className="text-base font-semibold text-theme-text-primary">Media handling rules</h3>
          <ul className="mt-3 space-y-3 text-sm text-theme-text-secondary">
            {mediaRules.map((rule) => (
              <li className="flex gap-2" key={rule}>
                <ShieldCheck className="mt-0.5 h-4 w-4 shrink-0 text-brand-600" />
                <span>{rule}</span>
              </li>
            ))}
          </ul>
        </aside>
      </div>
    </section>
  );
}

function MediaRule({ icon, label, value }: { icon: ReactElement; label: string; value: string }) {
  return (
    <article className="rounded-lg border border-theme-border bg-theme-card p-4">
      <div className="flex items-center gap-2 text-brand-600">{icon}</div>
      <p className="mt-3 text-sm text-theme-text-muted">{label}</p>
      <strong className="text-lg text-theme-text-primary">{value}</strong>
    </article>
  );
}
