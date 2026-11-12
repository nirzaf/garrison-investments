import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import { Download, RotateCcw, Trash2 } from 'lucide-react';
import { useState, type FormEvent } from 'react';

import { formatApiError } from '../../api/errors';
import {
  deletePhoto,
  getPhotoDownloadUrl,
  getPhotoThumbnailUrl,
  listPhotos,
  recoverPhoto,
  type PhotoRecord
} from '../../api/photos';
import { EmptyState } from '../../components/shared/EmptyState';
import { useAuth } from '../../context/useAuth';

const pageSize = 25;

export function PhotosPage() {
  const { user } = useAuth();
  const queryClient = useQueryClient();
  const isAdmin = user?.role === 'admin';
  const [kind, setKind] = useState<'photo' | 'attachment' | ''>('photo');
  const [deleted, setDeleted] = useState(false);
  const [page, setPage] = useState(0);
  const [error, setError] = useState('');
  const [notice, setNotice] = useState('');
  const [pendingDecision, setPendingDecision] = useState<{photo: PhotoRecord; action: 'remove' | 'recover'} | null>(null);
  const [reason, setReason] = useState('');
  const [pendingLink, setPendingLink] = useState<string | null>(null);
  const showDeleted = isAdmin && deleted;
  const photos = useQuery({
    queryKey: ['photos', kind, showDeleted, page],
    queryFn: ({ signal }) => listPhotos({
      kind: kind || undefined, deleted: showDeleted, limit: pageSize, offset: page * pageSize
    }, signal)
  });
  const pageCount = Math.max(1, Math.ceil((photos.data?.total ?? 0) / pageSize));

  const updateMedia = useMutation({
    mutationFn: async ({ photo, action, reason }: {
      photo: PhotoRecord; action: 'remove' | 'recover'; reason?: string;
    }) => {
      if (action === 'remove') await deletePhoto(photo.id, reason);
      else await recoverPhoto(photo.id, reason);
    },
    onMutate: () => {
      setError('');
      setNotice('');
    },
    onSuccess: async (_, { photo, action }) => {
      setPendingDecision(null);
      setReason('');
      if (page > 0 && photos.data?.items.length === 1) setPage(page - 1);
      setNotice(`${photo.original_name} ${action === 'remove' ? 'removed' : 'recovered'}.`);
      await queryClient.invalidateQueries({ queryKey: ['photos'] });
    },
    onError: (failure) => setError(formatApiError(failure, 'Unable to update the media record.'))
  });

  async function openUrl(photoId: string, variant: 'thumbnail' | 'download') {
    setError('');
    setPendingLink(photoId);
    try {
      const url = variant === 'thumbnail'
        ? await getPhotoThumbnailUrl(photoId)
        : await getPhotoDownloadUrl(photoId);
      window.open(url, '_blank', 'noopener,noreferrer');
    } catch (failure) {
      setError(formatApiError(failure, 'Unable to open this file.'));
    } finally {
      setPendingLink(null);
    }
  }

  function confirmDecision(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (pendingDecision && !updateMedia.isPending) {
      updateMedia.mutate({ ...pendingDecision, reason });
    }
  }

  return (
    <section className="space-y-5">
      <h2 className="text-2xl font-semibold text-theme-text-primary">Photos and attachments</h2>
      <p className="text-sm text-theme-text-secondary">
        Report and site update files have a 10 MiB limit. Each draft can hold up to five photos.
        JPEG and PNG photos have generated previews. HEIC originals are available for download.
      </p>
      <div className="flex flex-wrap gap-3">
        <select
          aria-label="Media type"
          className="form-field"
          onChange={(event) => {
            const value = event.target.value;
            setKind(value === 'photo' || value === 'attachment' ? value : '');
            setPage(0);
          }}
          value={kind}
        >
          <option value="">All files</option>
          <option value="photo">Photos</option>
          <option value="attachment">Attachments</option>
        </select>
        {isAdmin ? (
          <label className="flex items-center gap-2 text-sm">
            <input
              checked={showDeleted}
              onChange={(event) => {
                setDeleted(event.target.checked);
                setPage(0);
                setError('');
                setNotice('');
              }}
              type="checkbox"
            />
            Show deleted files
          </label>
        ) : null}
      </div>

      {error && !pendingDecision ? <p className="alert-error p-3" role="alert">{error}</p> : null}
      {notice ? <p className="alert-success p-3" role="status">{notice}</p> : null}
      {photos.isError ? (
        <div className="alert-error p-3" role="alert">
          {formatApiError(photos.error, 'Unable to load media.')}
          <button className="ml-3 underline" onClick={() => void photos.refetch()} type="button">Retry</button>
        </div>
      ) : null}
      {photos.isPending ? <EmptyState title="Loading media" description="Fetching files." /> : null}
      {photos.data?.items.length === 0 && !photos.isError ? (
        <EmptyState title={showDeleted ? 'No deleted files' : 'No media found'} description="Files that match this view will appear here." />
      ) : null}
      {photos.data?.items.length ? (
        <div className="divide-y divide-theme-border rounded-lg border border-theme-border bg-theme-card">
          {photos.data.items.map((photo) => {
            const recoverableUntil = photo.recoverable_until ? new Date(photo.recoverable_until) : null;
            const inWindow = recoverableUntil && recoverableUntil.getTime() >= Date.now();
            const owner = photo.entity_type.replace(/_/g, ' ');
            return (
              <article className="flex flex-wrap items-start justify-between gap-3 px-4 py-3 text-sm" key={photo.id}>
                <div>
                  <p className="font-medium text-theme-text-primary">{photo.original_name}</p>
                  <p className="text-theme-text-muted">
                    {owner} · {photo.kind} · {(photo.size_bytes / 1024 / 1024).toFixed(2)} MiB
                  </p>
                  {photo.mime_type === 'image/heic' ? <p className="text-theme-text-muted">Original only</p> : null}
                  {photo.caption ? <p className="mt-1 text-theme-text-muted">{photo.caption}</p> : null}
                  {showDeleted ? (
                    <p className="mt-1 text-theme-text-muted">
                      Record {photo.entity_id}
                      {photo.deleted_at ? ` · Removed ${new Date(photo.deleted_at).toLocaleString()}` : ''}
                      {recoverableUntil ? ` · Recovery deadline ${recoverableUntil.toLocaleString()}` : ''}
                    </p>
                  ) : null}
                </div>
                <div className="flex flex-wrap gap-2">
                  {showDeleted ? (
                    <button
                      className="form-field inline-flex items-center gap-2 disabled:opacity-50"
                      disabled={updateMedia.isPending || !inWindow}
                      onClick={() => {
                        setError('');
                        setReason('');
                        setPendingDecision({ photo, action: 'recover' });
                      }}
                      type="button"
                    >
                      <RotateCcw className="h-4 w-4" />
                      {inWindow ? 'Recover' : 'Recovery window expired'}
                    </button>
                  ) : (
                    <>
                      {photo.thumbnail_path ? (
                        <button
                          className="form-field"
                          disabled={pendingLink !== null}
                          onClick={() => void openUrl(photo.id, 'thumbnail')}
                          type="button"
                        >Preview</button>
                      ) : null}
                      <button
                        className="form-field inline-flex items-center gap-2"
                        disabled={pendingLink !== null}
                        onClick={() => void openUrl(photo.id, 'download')}
                        type="button"
                      >
                        <Download className="h-4 w-4" />
                        {photo.mime_type === 'image/heic' ? 'Download original' : 'Open file'}
                      </button>
                      {photo.can_delete ? (
                        <button
                          className="form-field inline-flex items-center gap-2"
                          disabled={updateMedia.isPending}
                          onClick={() => {
                            setError('');
                            setPendingDecision({ photo, action: 'remove' });
                            setReason('');
                          }}
                          type="button"
                        >
                          <Trash2 className="h-4 w-4" /> Remove
                        </button>
                      ) : null}
                    </>
                  )}
                </div>
              </article>
            );
          })}
        </div>
      ) : null}
      {pageCount > 1 || page > 0 ? (
        <nav aria-label="Media pages" className="flex items-center gap-3">
          <button className="form-field" disabled={page === 0 || photos.isPending} onClick={() => setPage(page - 1)} type="button">Previous</button>
          <span aria-live="polite">Page {page + 1} of {pageCount}</span>
          <button className="form-field" disabled={page + 1 >= pageCount || photos.isPending} onClick={() => setPage(page + 1)} type="button">Next</button>
        </nav>
      ) : null}

      {pendingDecision ? (
        <div aria-labelledby="remove-file-title" aria-modal="true" className="fixed inset-0 z-50 grid place-items-center bg-black/60 p-4" role="dialog">
          <form className="w-full max-w-md space-y-4 rounded-lg bg-theme-card p-5" onSubmit={confirmDecision}>
            <h3 className="font-semibold" id="remove-file-title">{pendingDecision.action === 'remove' ? 'Remove' : 'Recover'} {pendingDecision.photo.original_name}?</h3>
            <p className="text-sm text-theme-text-secondary">
              {pendingDecision.photo.entity_type.replace(/_/g, ' ')} record {pendingDecision.photo.entity_id}.
              {pendingDecision.action === 'remove'
                ? ' Admin can recover the file within 30 days if the stored objects are available.'
                : ' Recovery returns the file to its original record if the record has room.'}
            </p>
            {isAdmin ? (
              <label className="block text-sm">
                Reason · required for submitted evidence
                <textarea className="form-field block w-full" disabled={updateMedia.isPending} maxLength={500} onChange={(event) => setReason(event.target.value)} value={reason} />
              </label>
            ) : null}
            {error ? <p className="alert-error p-2" role="alert">{error}</p> : null}
            <div className="flex gap-2">
              <button className="form-field" disabled={updateMedia.isPending} onClick={() => { setPendingDecision(null); setError(''); }} type="button">Cancel</button>
              <button className="form-field" disabled={updateMedia.isPending} type="submit">
                {pendingDecision.action === 'remove' ? 'Remove file' : 'Recover file'}
              </button>
            </div>
          </form>
        </div>
      ) : null}
    </section>
  );
}
