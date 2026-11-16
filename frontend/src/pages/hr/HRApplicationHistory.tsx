import { useQuery } from '@tanstack/react-query';
import { useState } from 'react';

import { formatApiError } from '../../api/errors';
import { listApplicationActivity } from '../../api/hr';
import { hrButtonClass } from './HRAccessForms';

const pageSize = 20;

export function HRApplicationHistory({ applicationId }: { applicationId: string }) {
  const [open, setOpen] = useState(false);
  const [offset, setOffset] = useState(0);
  const history = useQuery({
    queryKey: ['hr', 'hiring', 'application-activity', applicationId, offset],
    queryFn: () => listApplicationActivity(applicationId, offset, pageSize),
    enabled: open
  });

  return (
    <details className="mt-2 space-y-2" onToggle={(event) => setOpen(event.currentTarget.open)}>
      <summary>Application stage history</summary>
      {open && (
        <>
          {history.isPending && <p role="status">Loading stage history…</p>}
          {history.isError && (
            <p role="alert">{formatApiError(history.error, 'Could not load stage history.')}</p>
          )}
          {history.isSuccess && history.data.total === 0 && <p>No recorded stage events.</p>}
          <ol className="space-y-1">
            {history.data?.items.map((row) => (
              <li key={row.id}>
                {row.stage} · {row.actor_name ?? 'Actor unavailable'} ·{' '}
                {new Date(row.created_at).toLocaleString()}
              </li>
            ))}
          </ol>
          {offset > 0 && (
            <button
              type="button"
              className={hrButtonClass}
              disabled={history.isFetching}
              onClick={() => setOffset(offset - pageSize)}
            >
              Previous stage events
            </button>
          )}
          {offset + pageSize < (history.data?.total ?? 0) && (
            <button
              type="button"
              className={hrButtonClass}
              disabled={history.isFetching}
              onClick={() => setOffset(offset + pageSize)}
            >
              Next stage events
            </button>
          )}
        </>
      )}
    </details>
  );
}
