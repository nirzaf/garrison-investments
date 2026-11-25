import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import { Download, Trash2 } from 'lucide-react';
import { useState, type FormEvent } from 'react';

import { formatApiError } from '../../api/errors';
import {
  classifyPhoto,
  deletePhoto,
  getPhotoDownloadUrl,
  getPhotoThumbnailUrl,
  listPhotos,
  type PhotoRecord
} from '../../api/photos';
import { EmptyState } from '../../components/shared/EmptyState';
import { useAuth } from '../../context/useAuth';

const pageSize = 25;

export function PhotosPage() {
  const { user } = useAuth();
  const queryClient = useQueryClient();
  const [kind, setKind] = useState<'photo' | 'attachment' | ''>('photo');
  const [page, setPage] = useState(0);
  const [error, setError] = useState('');
  const [notice, setNotice] = useState('');
  const [pendingDecision, setPendingDecision] = useState<PhotoRecord | null>(null);
  const [pendingLink, setPendingLink] = useState<string | null>(null);
  const [classificationTarget, setClassificationTarget] = useState<PhotoRecord | null>(null);
  const [classification, setClassification] = useState<'operational' | 'financial'>('operational');
  const [classificationReason, setClassificationReason] = useState('');
  const [classificationPending, setClassificationPending] = useState(false);
  const canReviewClassification = user?.permissions?.includes('documents:manage') ?? false;
  const canViewFinancial = user?.permissions?.includes('financial:view') ?? false;
  const photos = useQuery({
    queryKey: ['photos', kind, page],
    queryFn: ({ signal }) => listPhotos({
      kind: kind || undefined, limit: pageSize, offset: page * pageSize
    }, signal)
  });
  const pageCount = Math.max(1, Math.ceil((photos.data?.total ?? 0) / pageSize));

  const updateMedia = useMutation({
    mutationFn: (photo: PhotoRecord) => deletePhoto(photo.id),
    onMutate: () => {
      setError('');
      setNotice('');
    },
    onSuccess: async (_, photo) => {
      setPendingDecision(null);
      if (page > 0 && photos.data?.items.length === 1) setPage(page - 1);
      setNotice(`${photo.original_name} removed.`);
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
      updateMedia.mutate(pendingDecision);
    }
  }

  async function reviewClassification(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (!classificationTarget || classificationPending) return;
    setClassificationPending(true);
    setError('');
    setNotice('');
    try {
      await classifyPhoto(classificationTarget.id, classification, classificationReason);
      setClassificationTarget(null);
      setClassificationReason('');
      setNotice('Evidence classification reviewed.');
      await queryClient.invalidateQueries({ queryKey: ['photos'] });
    } catch (failure) {
      setError(formatApiError(failure, 'Unable to review evidence classification.'));
    } finally {
      setClassificationPending(false);
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
        <EmptyState title="No media found" description="Files that match this view will appear here." />
      ) : null}
      {photos.data?.items.length ? (
        <div className="divide-y divide-theme-border rounded-lg border border-theme-border bg-theme-card">
          {photos.data.items.map((photo) => {
            const owner = photo.entity_type.replace(/_/g, ' ');
            return (
              <article className="flex flex-wrap items-start justify-between gap-3 px-4 py-3 text-sm" key={photo.id}>
                <div>
                  <p className="font-medium text-theme-text-primary">{photo.original_name}</p>
                  <p className="text-theme-text-muted">
                    {owner} · {photo.kind} · {(photo.size_bytes / 1024 / 1024).toFixed(2)} MiB
                  </p>
                  <p className="text-theme-text-muted">
                    {photo.classification === 'unclassified' ? 'Unclassified · restricted' : `${photo.classification} evidence`}
                  </p>
                  {photo.mime_type === 'image/heic' ? <p className="text-theme-text-muted">Original only</p> : null}
                  {photo.caption ? <p className="mt-1 text-theme-text-muted">{photo.caption}</p> : null}
                </div>
                <div className="flex flex-wrap gap-2">
                  {canReviewClassification && photo.classification === 'unclassified' && photo.uploaded_by !== user?.id ? (
                    <button
                      className="form-field"
                      disabled={classificationPending}
                      onClick={() => {
                        setClassificationTarget(photo);
                        setClassification('operational');
                        setClassificationReason('');
                        setError('');
                      }}
                      type="button"
                    >Review classification</button>
                  ) : null}
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
                            setPendingDecision(photo);
                          }}
                          type="button"
                        >
                          <Trash2 className="h-4 w-4" /> Remove
                        </button>
                      ) : null}
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
            <h3 className="font-semibold" id="remove-file-title">Remove {pendingDecision.original_name}?</h3>
            <p className="text-sm text-theme-text-secondary">
              This removes the file from its editable draft record. Submitted or finalized evidence cannot be removed through this page.
            </p>
            <p className="text-sm text-theme-text-secondary">
              Owning record: {pendingDecision.entity_type.replace(/_/g, ' ')} {pendingDecision.entity_id}
            </p>
            {error ? <p className="alert-error p-2" role="alert">{error}</p> : null}
            <div className="flex gap-2">
              <button className="form-field" disabled={updateMedia.isPending} onClick={() => { setPendingDecision(null); setError(''); }} type="button">Cancel</button>
              <button className="form-field" disabled={updateMedia.isPending} type="submit">
                Remove file
              </button>
            </div>
          </form>
        </div>
      ) : null}
      {classificationTarget ? (
        <div aria-labelledby="photo-classification-title" aria-modal="true" className="fixed inset-0 z-50 grid place-items-center bg-black/60 p-4" role="dialog">
          <form className="w-full max-w-lg space-y-4 rounded-lg bg-theme-card p-5" onSubmit={reviewClassification}>
            <h3 className="font-semibold" id="photo-classification-title">Review {classificationTarget.original_name}</h3>
            <p className="text-sm text-theme-text-secondary">The original, metadata and previews remain restricted until classification is reviewed.</p>
            <label className="block space-y-1 text-sm">
              <span>Classification</span>
              <select className="form-field w-full" disabled={classificationPending} onChange={(event) => setClassification(event.target.value as 'operational' | 'financial')} value={classification}>
                <option value="operational">Operational evidence</option>
                {canViewFinancial ? <option value="financial">Financial evidence</option> : null}
              </select>
            </label>
            <label className="block space-y-1 text-sm">
              <span>Review reason</span>
              <textarea className="form-field min-h-24 w-full" disabled={classificationPending} maxLength={500} minLength={3} onChange={(event) => setClassificationReason(event.target.value)} required value={classificationReason} />
            </label>
            {error ? <p className="alert-error p-2" role="alert">{error}</p> : null}
            <div className="flex justify-end gap-2">
              <button className="form-field" disabled={classificationPending} onClick={() => setClassificationTarget(null)} type="button">Cancel</button>
              <button className="form-field" disabled={classificationPending || classificationReason.trim().length < 3} type="submit">Save review</button>
            </div>
          </form>
        </div>
      ) : null}
    </section>
  );
}
