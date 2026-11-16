import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import { useState } from 'react';

import { formatApiError } from '../../api/errors';
import { decideHrLetter, getHrLetter, listHrLetters } from '../../api/hr';

const pageSize = 20;

export function HRLetterRecords({ employeeId }: { employeeId?: string }) {
  const scope = employeeId ?? 'me';
  const [offset, setOffset] = useState(0);
  const [selected, setSelected] = useState('');
  const [reason, setReason] = useState('');
  const queries = useQueryClient();
  const list = useQuery({
    queryKey: ['hr', 'letters', scope, offset],
    queryFn: () => listHrLetters(employeeId, offset, pageSize)
  });
  const detailKey = ['hr', 'letter-detail', scope, selected];
  const detail = useQuery({
    queryKey: detailKey,
    queryFn: () => getHrLetter(employeeId, selected),
    enabled: Boolean(selected),
    gcTime: 0
  });
  const decision = useMutation({
    mutationFn: (apply: 'issued' | 'rejected') =>
      decideHrLetter(employeeId ?? '', selected, {
        decision: apply,
        reason: apply === 'rejected' ? reason.trim() : undefined
      }),
    onSuccess: async (row) => {
      queries.setQueryData(detailKey, row);
      setReason('');
      await queries.invalidateQueries({ queryKey: ['hr', 'letters', scope] });
    }
  });

  return (
    <div className="space-y-2 text-sm">
      <h4 className="font-medium">{employeeId ? 'Retained HR letters' : 'My issued HR letters'}</h4>
      {list.isPending && <p role="status">Loading HR letters…</p>}
      {list.isError && (
        <p role="alert">
          {formatApiError(list.error, 'Could not load HR letters.')}{' '}
          <button onClick={() => void list.refetch()} type="button">Retry</button>
        </p>
      )}
      {list.data?.total === 0 && <p>No HR letters are available.</p>}
      {list.data?.items.map((row) => (
        <p key={row.id}>
          <button
            className="text-brand-600 underline"
            disabled={decision.isPending}
            onClick={() => {
              setSelected(row.id);
              setReason('');
              decision.reset();
            }}
            type="button"
          >
            {row.template_name} · {row.status} · {row.created_at.slice(0, 10)}
          </button>
        </p>
      ))}
      {list.data && list.data.total > pageSize && (
        <div className="flex gap-3">
          <button type="button" disabled={offset === 0} onClick={() => setOffset(offset - pageSize)}>
            Previous letters
          </button>
          <button type="button" disabled={offset + pageSize >= list.data.total}
            onClick={() => setOffset(offset + pageSize)}>
            Next letters
          </button>
        </div>
      )}
      {selected && detail.isPending && <p role="status">Opening letter…</p>}
      {detail.isError && (
        <p role="alert">
          {formatApiError(detail.error, 'Could not open the letter.')}{' '}
          <button onClick={() => void detail.refetch()} type="button">Retry</button>
        </p>
      )}
      {detail.data && (
        <article className="space-y-2 rounded border border-theme-border p-3">
          <h5 className="font-semibold">{detail.data.subject}</h5>
          <p className="whitespace-pre-wrap break-words">{detail.data.body}</p>
          {detail.data.decided_at && (
            <p role="status">
              {detail.data.status === 'issued' ? 'Issued' : 'Rejected'}{' '}
              {detail.data.decided_at.slice(0, 10)}
            </p>
          )}
          {detail.data.rejection_reason && <p>Rejection reason: {detail.data.rejection_reason}</p>}
          {employeeId && detail.data.can_decide && (
            <form
              className="space-y-2"
              onSubmit={(event) => {
                event.preventDefault();
                decision.mutate('rejected');
              }}
            >
              <button type="button" disabled={decision.isPending}
                onClick={() => decision.mutate('issued')}>
                Approve and issue letter
              </button>
              <label className="block">
                Letter rejection reason{' '}
                <input value={reason} maxLength={2000} required
                  onChange={(event) => setReason(event.target.value)} />
              </label>
              <button type="submit" disabled={decision.isPending || !reason.trim()}>
                Reject letter
              </button>
            </form>
          )}
          {decision.isError && (
            <p role="alert">{formatApiError(decision.error, 'Could not decide the letter.')}</p>
          )}
        </article>
      )}
    </div>
  );
}
