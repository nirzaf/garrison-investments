import { useQuery } from '@tanstack/react-query';
import { useState } from 'react';

import { formatApiError } from '../../api/errors';
import { getMyPayslip, listMyPayslips } from '../../api/hr';

const pageSize = 20;

export function HRPayslips() {
  const [open, setOpen] = useState(false);
  const [offset, setOffset] = useState(0);
  const [selected, setSelected] = useState('');
  const list = useQuery({
    queryKey: ['hr', 'me', 'payslips', offset],
    queryFn: () => listMyPayslips(pageSize, offset),
    enabled: open
  });
  const detail = useQuery({
    queryKey: ['hr', 'me', 'payslip', selected],
    queryFn: () => getMyPayslip(selected),
    enabled: open && Boolean(selected),
    gcTime: 0
  });

  return (
    <details className="space-y-2 text-sm" onToggle={(event) => {
      const expanded = event.currentTarget.open;
      setOpen(expanded);
      if (!expanded) setSelected('');
    }}>
      <summary className="font-medium">My payslips</summary>
      {open && list.isPending && <p role="status">Loading payslips…</p>}
      {list.isError && (
        <p role="alert">
          {formatApiError(list.error, 'Unable to load your payslips.')}{' '}
          <button type="button" onClick={() => void list.refetch()}>Retry</button>
        </p>
      )}
      {list.data?.total === 0 && <p>No payslips have been published for you.</p>}
      {list.data?.items.map((row) => (
        <p key={row.run_id}>
          <button
            type="button"
            onClick={() => setSelected(row.run_id)}
            className="text-brand-600 underline"
          >
            Open payslip for {row.period_start} to {row.period_end}
          </button>
        </p>
      ))}
      {list.data && list.data.total > pageSize && (
        <div className="flex gap-2">
          <button type="button" disabled={!offset} onClick={() => setOffset(offset - pageSize)}>
            Previous payslips
          </button>
          <button type="button" disabled={offset + pageSize >= list.data.total}
            onClick={() => setOffset(offset + pageSize)}>
            Next payslips
          </button>
        </div>
      )}
      {selected && detail.isPending && <p role="status">Opening payslip…</p>}
      {selected && detail.isError && (
        <p role="alert">
          {formatApiError(detail.error, 'Unable to open this payslip.')}{' '}
          <button type="button" onClick={() => void detail.refetch()}>Retry</button>
        </p>
      )}
      {selected && detail.isSuccess && (
        <article className="space-y-2 rounded border border-theme-border p-3">
          <h4 className="font-medium">
            Payslip for {detail.data.period_start} to {detail.data.period_end}
          </h4>
          <p>Scheduled pay date {detail.data.pay_date}</p>
          <dl className="grid grid-cols-2 gap-2">
            <dt>Gross</dt><dd>{detail.data.currency} {detail.data.gross}</dd>
            <dt>Deductions</dt><dd>{detail.data.currency} {detail.data.deductions}</dd>
            <dt>Net</dt><dd>{detail.data.currency} {detail.data.net}</dd>
          </dl>
          <button type="button" onClick={() => setSelected('')}>Close payslip</button>
        </article>
      )}
    </details>
  );
}
