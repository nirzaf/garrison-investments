import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import { useState } from 'react';

import { formatApiError } from '../../api/errors';
import {
  decideHrDocumentVersion,
  getHrDocumentDownloadUrl,
  listCandidates,
  listHrDocuments,
  uploadHrDocument,
  uploadHrDocumentVersion,
  type CandidateRecord
} from '../../api/hr';
import { hrButtonClass, hrInputClass } from './HRAccessForms';

export function HRCandidateCVs({
  candidates,
  reviewerId,
  offerFiles = false
}: {
  candidates: CandidateRecord[];
  reviewerId: string | undefined;
  offerFiles?: boolean;
}) {
  const client = useQueryClient();
  const label = offerFiles ? 'offer file' : 'CV';
  const documentType = offerFiles ? 'candidate_offer' : 'candidate_cv';
  const [candidateId, setCandidateId] = useState('');
  const [search, setSearch] = useState('');
  const matches = useQuery({
    queryKey: ['hr', 'cv-candidates', search],
    queryFn: () => listCandidates(search),
    enabled: Boolean(search)
  });
  const options = search ? (matches.data?.items ?? []) : candidates;
  const candidate = options.find((item) => item.id === candidateId);
  const cvKey = ['hr', documentType, candidateId];
  const documents = useQuery({
    queryKey: cvKey,
    queryFn: () => listHrDocuments({ candidate_id: candidateId, document_type: documentType }),
    enabled: Boolean(candidate)
  });
  const cv = documents.data?.items[0];
  const latest = cv?.versions?.[0];
  const pending = latest?.status === 'pending';
  const canReview = Boolean(reviewerId && latest && latest.uploaded_by_id !== reviewerId);
  const change = useMutation({
    mutationFn: async (command: () => Promise<unknown>) => command(),
    onSuccess: async () => {
      await Promise.all([
        client.invalidateQueries({ queryKey: cvKey }),
        client.invalidateQueries({ queryKey: ['hr', 'hiring'] })
      ]);
    }
  });

  return (
    <section className="space-y-3 rounded border border-theme-border p-3">
      <h4 className="font-medium">{offerFiles ? 'Candidate offer files' : 'Candidate CVs'}</h4>
      <form
        className="flex flex-wrap items-end gap-2"
        onSubmit={(event) => {
          event.preventDefault();
          const value = String(new FormData(event.currentTarget).get('query')).trim();
          if (value === search) return;
          setSearch(value);
          setCandidateId('');
          change.reset();
        }}
      >
        <label>
          {offerFiles ? 'Search candidates for offer files' : 'Search candidates'}
          <input name="query" className={hrInputClass} />
        </label>
        <button type="submit" className={hrButtonClass} disabled={change.isPending}>
          {offerFiles ? 'Find candidates for offer files' : 'Find candidates'}
        </button>
      </form>
      <label className="block">
        {offerFiles ? 'Offer file candidate' : 'CV candidate'}
        <select
          className={hrInputClass}
          value={candidateId}
          disabled={change.isPending}
          onChange={(event) => {
            setCandidateId(event.target.value);
            change.reset();
          }}
        >
          <option value="">Choose a candidate</option>
          {options.map((item) => (
            <option key={item.id} value={item.id}>
              {item.candidate_code} · {item.full_name}
            </option>
          ))}
        </select>
      </label>
      {(matches.isLoading || documents.isLoading) && (
        <p role="status">Loading candidate records…</p>
      )}
      {matches.isSuccess && search && !options.length && <p>No matching candidates.</p>}
      {matches.isError && (
        <p role="alert">
          {formatApiError(matches.error, 'Could not search candidates.')}{' '}
          <button type="button" className="underline" onClick={() => void matches.refetch()}>
            Retry
          </button>
        </p>
      )}
      {documents.isError && (
        <p role="alert">
          {formatApiError(documents.error, `Could not load the ${label}.`)}{' '}
          <button type="button" className="underline" onClick={() => void documents.refetch()}>
            Retry
          </button>
        </p>
      )}
      {change.isError && (
        <p role="alert">{formatApiError(change.error, `Could not update the ${label}.`)}</p>
      )}
      {candidate && documents.isSuccess && !pending && (
        <form
          className="flex flex-wrap items-end gap-2"
          key={candidate.id}
          onSubmit={(event) => {
            event.preventDefault();
            const form = event.currentTarget;
            const file = new FormData(form).get('file');
            if (!(file instanceof File) || !file.size || change.isPending) return;
            change.mutate(
              () =>
                cv
                  ? uploadHrDocumentVersion(cv.id, file)
                  : uploadHrDocument({
                      file,
                      title: `${offerFiles ? 'Offer file' : 'CV'} · ${candidate.candidate_code}`,
                      document_type: documentType,
                      category: 'confidential',
                      candidate_id: candidate.id
                    }),
              { onSuccess: () => form.reset() }
            );
          }}
        >
          <label>
            {offerFiles
              ? 'Offer file (PDF, up to 60 MiB)'
              : 'CV file (PDF, DOCX, PNG or JPEG, up to 60 MiB)'}
            <input
              name="file"
              className={hrInputClass}
              type="file"
              accept={offerFiles ? '.pdf' : '.pdf,.docx,.png,.jpg,.jpeg'}
              required
            />
          </label>
          <button type="submit" className={hrButtonClass} disabled={change.isPending}>
            {cv ? `Upload replacement ${label}` : `Upload ${label}`}
          </button>
        </form>
      )}
      {cv && (
        <ul className="space-y-1">
          {cv.versions?.map((version) => (
            <li key={version.id} className="flex flex-wrap items-center gap-2">
              <span>
                {version.file_name} · version {version.version_number} · {version.status}
              </span>
              {(['active', 'superseded'].includes(version.status) ||
                (version.status === 'pending' && canReview)) && (
                <button
                  type="button"
                  className="text-brand-600 underline"
                  disabled={change.isPending}
                  onClick={() =>
                    change.mutate(async () => {
                      const link = await getHrDocumentDownloadUrl(cv.id, version.version_number);
                      window.location.assign(link.download_url);
                    })
                  }
                >
                  {version.status === 'pending' ? 'Download for review' : `Download ${label}`}
                </button>
              )}
            </li>
          ))}
        </ul>
      )}
      {cv && latest && pending && canReview && (
        <form
          className="flex flex-wrap items-end gap-2"
          key={latest.id}
          onSubmit={(event) => {
            event.preventDefault();
            const submitter = (event.nativeEvent as SubmitEvent).submitter;
            if (!(submitter instanceof HTMLButtonElement) || change.isPending) return;
            const notes = String(new FormData(event.currentTarget).get('notes')).trim();
            change.mutate(() =>
              decideHrDocumentVersion(cv.id, latest.version_number, {
                decision: submitter.value === 'reject' ? 'reject' : 'approve',
                notes: notes || null
              })
            );
          }}
        >
          <label>
            {label} review reason (required to reject)
            <input className={hrInputClass} name="notes" maxLength={500} />
          </label>
          <button
            className={hrButtonClass}
            disabled={change.isPending}
            type="submit"
            value="approve"
          >
            Approve {label}
          </button>
          <button
            className={hrButtonClass}
            disabled={change.isPending}
            type="submit"
            value="reject"
          >
            Reject {label}
          </button>
        </form>
      )}
      {pending && !canReview && <p>Waiting for a different HR Manager to review this {label}.</p>}
    </section>
  );
}
