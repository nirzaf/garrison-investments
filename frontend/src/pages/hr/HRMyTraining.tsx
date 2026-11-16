import { useQuery } from '@tanstack/react-query';
import { useState } from 'react';

import { apiClient } from '../../api/client';
import { formatApiError } from '../../api/errors';
import type { HrSchemas } from '../../api/hr';
import { hrButtonClass } from './HRAccessForms';
import { TrainingRequirements } from './HRTrainingRequirements';

const PAGE_SIZE = 20;

export function HRMyTraining() {
  const [open, setOpen] = useState(false);
  const [offset, setOffset] = useState(0);
  const training = useQuery({
    queryKey: ['hr', 'me', 'training', offset],
    queryFn: async ({ signal }) =>
      (
        await apiClient.get<HrSchemas['SelfTrainingListResponse']>('/hr/me/training', {
          params: { offset, limit: PAGE_SIZE },
          signal
        })
      ).data,
    enabled: open
  });
  return (
    <details
      className="space-y-3 rounded-lg border border-theme-border bg-theme-card p-5"
      onToggle={(event) => setOpen(event.currentTarget.open)}
    >
      <summary className="font-semibold">My training</summary>
      {open && <TrainingRequirements />}
      {open && training.isPending && <p role="status">Loading training…</p>}
      {training.isError && (
        <p role="alert">
          {formatApiError(training.error, 'Could not load your training.')}{' '}
          <button type="button" onClick={() => void training.refetch()}>
            Retry
          </button>
        </p>
      )}
      {training.data && (
        <>
          {training.data.total === 0 && <p>No training enrollments.</p>}
          <ul className="space-y-2">
            {training.data.items.map((item) => (
              <li key={item.enrollment_id}>
                <p>
                  {item.course_title} · {item.status.replace(/_/g, ' ')}
                </p>
                {item.scheduled_date && <p>Scheduled {item.scheduled_date}</p>}
                {item.completed_date && (
                  <p>
                    Completed {item.completed_date}
                    {item.verified && ' · Verified'}
                  </p>
                )}
                {item.certificate_expiry && (
                  <p>
                    {item.certificate_expired ? 'Certificate expired' : 'Certificate expires'}{' '}
                    {item.certificate_expiry}
                  </p>
                )}
              </li>
            ))}
          </ul>
          {training.data.total > PAGE_SIZE && (
            <nav aria-label="Training pages" className="flex gap-2">
              <button
                className={hrButtonClass}
                type="button"
                disabled={!offset}
                onClick={() => setOffset(offset - PAGE_SIZE)}
              >
                Previous
              </button>
              <button
                className={hrButtonClass}
                type="button"
                disabled={offset + PAGE_SIZE >= training.data.total}
                onClick={() => setOffset(offset + PAGE_SIZE)}
              >
                Next
              </button>
            </nav>
          )}
        </>
      )}
    </details>
  );
}
