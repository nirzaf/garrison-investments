import { useQuery } from '@tanstack/react-query';
import { useState } from 'react';

import { formatApiError } from '../../api/errors';
import { getHrApplication, listHrDocuments } from '../../api/hr';
import { hrInputClass } from './HRAccessForms';

export function HROfferDocumentPicker({
  applicationId,
  priorVersion,
  loadOnMount = true
}: {
  applicationId: string;
  priorVersion?: string | null;
  loadOnMount?: boolean;
}) {
  const [open, setOpen] = useState(loadOnMount);
  const application = useQuery({
    queryKey: ['hr', 'offer-application', applicationId],
    queryFn: () => getHrApplication(applicationId),
    enabled: open
  });
  const candidateId = application.data?.candidate_id ?? '';
  const files = useQuery({
    queryKey: ['hr', 'candidate_offer', candidateId],
    queryFn: () => listHrDocuments({ candidate_id: candidateId, document_type: 'candidate_offer' }),
    enabled: open && Boolean(candidateId),
    staleTime: 0
  });
  const options =
    files.data?.items.flatMap((doc) =>
      (doc.versions ?? []).filter(
        (version) => version.status === 'active' && version.id !== priorVersion
      )
    ) ?? [];

  return (
    <div>
      {!open && (
        <button type="button" onClick={() => setOpen(true)} className="text-brand-600 underline">
          {priorVersion ? 'Find a replacement offer file' : 'Find an approved offer file'}
        </button>
      )}
      <label className={open ? 'block' : 'sr-only'}>
        Approved offer PDF
        {open && (
          <select
            name="document_version_id"
            className={hrInputClass}
            required={Boolean(priorVersion)}
          >
            <option value="">
              {priorVersion ? 'Select a different approved PDF' : 'No file attached'}
            </option>
            {options.map((version) => (
              <option key={version.id} value={version.id}>
                {version.file_name} · v{version.version_number}
              </option>
            ))}
          </select>
        )}
      </label>
      {open && (application.isFetching || files.isFetching) && (
        <p role="status">Loading offer files…</p>
      )}
      {open && (application.isError || files.isError) && (
        <p role="alert">
          {formatApiError(application.error ?? files.error, 'Could not load approved offer files.')}
        </p>
      )}
      {open && files.isSuccess && options.length === 0 && <p>No eligible approved offer PDFs.</p>}
    </div>
  );
}
