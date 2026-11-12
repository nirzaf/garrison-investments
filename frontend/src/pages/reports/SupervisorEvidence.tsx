import { useQuery } from '@tanstack/react-query';
import { useState } from 'react';

import { formatApiError } from '../../api/errors';
import { getPhotoDownloadUrl, listPhotos } from '../../api/photos';
import {
  listReportSupervisorUpdates,
  type SupervisorUpdateRecord
} from '../../api/supervisorUpdates';

function EvidenceFiles({ updateId }: { updateId: string }) {
  const files = useQuery({
    queryKey: ['supervisor-evidence-files', updateId],
    queryFn: () => listPhotos({ entityType: 'supervisor_update', entityId: updateId })
  });
  const [pending, setPending] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);

  async function openFile(fileId: string) {
    setPending(fileId);
    setError(null);
    try {
      const url = await getPhotoDownloadUrl(fileId);
      window.open(url, '_blank', 'noopener,noreferrer');
    } catch (cause) {
      setError(formatApiError(cause, 'Unable to open this attachment.'));
    } finally {
      setPending(null);
    }
  }

  if (files.isPending) return <p role="status">Loading attachments…</p>;
  if (files.isError) return <p role="alert">Unable to load attachments.</p>;
  if (!files.data.items.length) return <p>No attachments.</p>;
  return (
    <div className="space-y-1">
      {error && <p role="alert">{error}</p>}
      {files.data.items.map((file) => (
        <button
          className="block text-brand-600 underline"
          disabled={pending !== null}
          key={file.id}
          onClick={() => void openFile(file.id)}
          type="button"
        >
          {pending === file.id ? 'Opening…' : file.original_name}
        </button>
      ))}
    </div>
  );
}

export function SupervisorUpdateDetails({ update }: { update: SupervisorUpdateRecord }) {
  const [expanded, setExpanded] = useState(false);
  return (
    <details
      className="rounded-md border border-theme-border p-3 text-sm"
      onToggle={(event) => setExpanded(event.currentTarget.open)}
    >
      <summary className="cursor-pointer font-medium">
        {update.update_date} · {update.work_location} · {update.status}
      </summary>
      <div className="mt-3 space-y-2">
        <p className="whitespace-pre-wrap">{update.progress_notes}</p>
        <p>
          {update.attendance_count} attendance · {update.overtime_hours} overtime hours
        </p>
        {update.delay_notes && <p>Delays — {update.delay_notes}</p>}
        <p>Requirements — {update.required_notes}</p>
        {update.submitted_at && <p>Submitted {new Date(update.submitted_at).toLocaleString()}</p>}
        {update.verified_at && (
          <p>
            Verified {new Date(update.verified_at).toLocaleString()}
            {update.verified_by_name ? ` by ${update.verified_by_name}` : ''}
          </p>
        )}
        {update.verified_report_id && <p>Linked report {update.verified_report_id}</p>}
        {expanded && <EvidenceFiles updateId={update.id} />}
      </div>
    </details>
  );
}

export function ReportSupervisorEvidence({ reportId }: { reportId: string }) {
  const [expanded, setExpanded] = useState(false);
  const evidence = useQuery({
    queryKey: ['report-supervisor-evidence', reportId],
    queryFn: () => listReportSupervisorUpdates(reportId),
    enabled: expanded
  });
  return (
    <details
      className="mt-4 rounded-md border border-theme-border p-3 text-sm"
      onToggle={(event) => setExpanded(event.currentTarget.open)}
    >
      <summary className="cursor-pointer font-medium">Supervisor evidence</summary>
      {expanded && (
        <div className="mt-2 space-y-2">
          {evidence.isPending && <p role="status">Loading supervisor evidence…</p>}
          {evidence.isError && <p role="alert">Unable to load supervisor evidence.</p>}
          {evidence.data?.length === 0 && <p>No linked supervisor updates are available.</p>}
          {evidence.data?.map((update) => (
            <SupervisorUpdateDetails key={update.id} update={update} />
          ))}
        </div>
      )}
    </details>
  );
}
