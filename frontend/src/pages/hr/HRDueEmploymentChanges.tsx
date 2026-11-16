import { useQuery } from '@tanstack/react-query';
import { useState } from 'react';

import { formatApiError } from '../../api/errors';
import { dueEmploymentChangesKey, listDueEmploymentChanges } from '../../api/hr';
import { hrButtonClass } from './HRAccessForms';

const pageSize = 20;

export function HRDueEmploymentChanges({
  actorId, inspectEmployee
}: {
  actorId: string;
  inspectEmployee: (employeeId: string) => Promise<void>;
}) {
  const [open, setOpen] = useState(false);
  const [offset, setOffset] = useState(0);
  const due = useQuery({
    queryKey: [...dueEmploymentChangesKey, actorId, offset],
    queryFn: ({ signal }) => listDueEmploymentChanges(offset, pageSize, signal),
    enabled: open,
    gcTime: 0,
    retry: false
  });

  return (
    <details className="space-y-3 rounded border border-theme-border bg-theme-card p-4"
      onToggle={(event) => setOpen(event.currentTarget.open)}>
      <summary className="cursor-pointer font-semibold">Due employment changes</summary>
      {open && due.isPending && <p role="status">Loading due employment changes…</p>}
      {open && due.isError && (
        <p role="alert">{formatApiError(due.error, 'Unable to load due changes.')}{' '}
          <button type="button" className={hrButtonClass} onClick={() => void due.refetch()}>Retry</button>
        </p>
      )}
      {open && due.data && (
        <>
          <p>Approved and due as of {due.data.as_of}. Review the change in the employee record.</p>
          {due.data.total === 0 && <p>No approved employment changes are due.</p>}
          {due.data.items.length > 0 && (
            <ul aria-label="Approved changes due" className="space-y-2">
              {due.data.items.map((change) => (
                <li key={change.id} className="flex flex-wrap items-center justify-between gap-2">
                  <span>{change.employee_code} · {change.change_type.replace(/_/g, ' ')} · {change.effective_date}
                    {!change.revision_matches && ' · Employee record changed'}
                  </span>
                  <button type="button" className={hrButtonClass}
                    onClick={() => void inspectEmployee(change.employee_id)}>Inspect employee</button>
                </li>
              ))}
            </ul>
          )}
          {(offset > 0 || due.data.total > pageSize) && (
            <div className="flex gap-2">
              <button type="button" className={hrButtonClass} disabled={offset === 0}
                onClick={() => setOffset((value) => Math.max(0, value - pageSize))}>Previous changes</button>
              <button type="button" className={hrButtonClass} disabled={offset + pageSize >= due.data.total}
                onClick={() => setOffset((value) => value + pageSize)}>Next changes</button>
            </div>
          )}
        </>
      )}
    </details>
  );
}
