import { useQuery } from '@tanstack/react-query';
import { useEffect, useRef, useState } from 'react';

import { formatApiError } from '../../api/errors';
import {
  downloadFrozenPayrollInput,
  downloadPayrollInputs,
  previewPayrollInputs,
  type PayrollInputPreviews,
  type PayrollInputSource,
  type PayrollSnapshot,
  type PayrollSourceEvidence
} from '../../api/hr';
import { hrButtonClass } from './HRAccessForms';

type Props = {
  actorId: string;
  periodId: string;
  employeeIds: string[];
  disabled: boolean;
  evidence?: PayrollSourceEvidence;
  onEvidenceChange: (evidence?: PayrollSourceEvidence) => void;
};
type Preview = PayrollInputPreviews[PayrollInputSource];

export function HRPayrollInputs({
  actorId, periodId, employeeIds, disabled, evidence, onEvidenceChange
}: Props) {
  const [open, setOpen] = useState(false);
  const [pending, setPending] = useState<PayrollInputSource>();
  const [error, setError] = useState('');
  const download = useRef<AbortController | null>(null);
  useEffect(() => () => download.current?.abort(), []);

  const queryKey = ['hr', 'payroll-source-preview', actorId, periodId, employeeIds];
  const time = useQuery({
    queryKey: [...queryKey, 'time'],
    queryFn: ({ signal }) => previewPayrollInputs('time', periodId, employeeIds, signal),
    enabled: open,
    staleTime: Infinity,
    gcTime: 0,
    retry: false
  });
  const leave = useQuery({
    queryKey: [...queryKey, 'leave'],
    queryFn: ({ signal }) => previewPayrollInputs('leave', periodId, employeeIds, signal),
    enabled: open,
    staleTime: Infinity,
    gcTime: 0,
    retry: false
  });
  const fetching = time.isFetching || leave.isFetching;
  const timeDigest = time.isSuccess ? time.data.csv_sha256 : undefined;
  const leaveDigest = leave.isSuccess ? leave.data.csv_sha256 : undefined;

  async function saveCsv(source: PayrollInputSource, digest: string) {
    if (download.current) return;
    const controller = new AbortController();
    download.current = controller;
    setPending(source);
    setError('');
    try {
      const file = await downloadPayrollInputs(source, periodId, employeeIds, digest, controller.signal);
      if (controller.signal.aborted) return;
      saveCsvFile(file, `payroll-${source}-${periodId}.csv`);
    } catch (failure) {
      if (!controller.signal.aborted) {
        setError(formatApiError(failure, 'Unable to verify this file. Refresh the source review before retrying.'));
      }
    } finally {
      download.current = null;
      if (!controller.signal.aborted) setPending(undefined);
    }
  }

  return (
    <section aria-label="Time and leave source review" className="space-y-3 border-t border-theme-border pt-3">
      <button className={hrButtonClass} type="button" disabled={disabled || fetching || Boolean(pending)}
        onClick={() => {
          setError('');
          onEvidenceChange();
          if (open) void Promise.all([time.refetch(), leave.refetch()]);
          else setOpen(true);
        }}>
        {open ? 'Refresh source review' : 'Review time and leave inputs'}
      </button>
      {open && (
        <>
          <p className="text-sm text-theme-text-muted">Source review uses the selected roster. Payroll amounts follow the approved policy and reviewed adjustments.</p>
          {([
            { source: 'time', title: 'Time inputs', query: time },
            { source: 'leave', title: 'Leave inputs', query: leave }
          ] as const).map(({ source, title, query }) => (
            <article key={source} aria-label={title} className="space-y-2">
              <h5 className="font-semibold">{title}</h5>
              {query.isFetching && <p role="status">Reviewing {source} inputs…</p>}
              {query.isError && <p role="alert">{formatApiError(query.error, `Unable to review ${source} inputs.`)}</p>}
              {query.isSuccess && !query.isFetching && (
                <PayrollInputResult data={query.data} title={source}
                  disabled={disabled || Boolean(pending)} onDownload={(digest) => void saveCsv(source, digest)} />
              )}
            </article>
          ))}
          {!fetching && timeDigest && leaveDigest && (
            <label className="flex items-center gap-2">
              <input type="checkbox" checked={Boolean(evidence)} disabled={disabled}
                onChange={(event) => onEvidenceChange(event.target.checked ? {
                  time_sha256: timeDigest, leave_sha256: leaveDigest
                } : undefined)} />
              Attach reviewed time and leave evidence to the snapshot
            </label>
          )}
          {pending && <p role="status">Verifying {pending} CSV…</p>}
          {error && <p role="alert">{error}</p>}
        </>
      )}
    </section>
  );
}

function PayrollInputResult({ data, title, disabled, onDownload }: {
  data: Preview; title: PayrollInputSource; disabled: boolean; onDownload: (digest: string) => void;
}) {
  const digest = data.csv_sha256;
  if (data.issues.length) {
    return (
      <>
        <p>{data.issues.length} source issues. Resolve them before exporting {title} inputs.</p>
        <ul className="space-y-1 break-all text-sm">
          {data.issues.map((item, index) => {
            const record = 'record_id' in item ? item.record_id : 'request_id' in item ? item.request_id : undefined;
            return (
              <li key={`${item.employee_id}:${item.code}:${record ?? index}`}>
                {item.code.replace(/_/g, ' ')} · Employee <code>{item.employee_id}</code>
                {record && <> · Record <code>{record}</code></>}
              </li>
            );
          })}
        </ul>
      </>
    );
  }
  return (
    <>
      {'regular_hours' in data
        ? <p>Regular hours {data.regular_hours} · Overtime hours {data.overtime_hours}</p>
        : <p>Paid leave days {data.paid_days} · Unpaid leave days {data.unpaid_days}</p>}
      {digest && (
        <>
          <p className="break-all text-sm">CSV SHA-256 <code aria-label={`${title} input checksum`}>{digest}</code></p>
          <button className={hrButtonClass} type="button" disabled={disabled} onClick={() => onDownload(digest)}>
            Download verified {title} CSV
          </button>
        </>
      )}
    </>
  );
}


function saveCsvFile(file: Blob, name: string) {
  const url = URL.createObjectURL(file);
  try {
    const link = document.createElement('a');
    link.href = url;
    link.download = name;
    link.click();
  } finally {
    window.setTimeout(() => URL.revokeObjectURL(url), 1000);
  }
}

export function FrozenPayrollInputs({ runId, evidence }: {
  runId: string; evidence: NonNullable<PayrollSnapshot['source_evidence']>;
}) {
  const download = useRef<AbortController | null>(null);
  const [pending, setPending] = useState<PayrollInputSource>();
  const [error, setError] = useState('');
  useEffect(() => () => download.current?.abort(), []);

  async function save(source: PayrollInputSource, digest: string) {
    if (download.current) return;
    const controller = new AbortController();
    download.current = controller;
    setPending(source);
    setError('');
    try {
      const file = await downloadFrozenPayrollInput(runId, source, digest, controller.signal);
      if (!controller.signal.aborted) saveCsvFile(file, `payroll-${source}-${runId}.csv`);
    } catch (failure) {
      if (!controller.signal.aborted) {
        setError(formatApiError(failure, 'Unable to verify the frozen source file.'));
      }
    } finally {
      download.current = null;
      if (!controller.signal.aborted) setPending(undefined);
    }
  }

  return (
    <section aria-label="Frozen time and leave evidence" className="space-y-2">
      <h5 className="font-semibold">Frozen time and leave evidence</h5>
      <p>Regular hours {evidence.regular_hours} · Overtime hours {evidence.overtime_hours}</p>
      <p>Paid leave days {evidence.paid_days} · Unpaid leave days {evidence.unpaid_days}</p>
      {(['time', 'leave'] as const).map((source) => (
        <div key={source} className="space-y-1">
          <p className="break-all text-sm">{source === 'time' ? 'Time' : 'Leave'} SHA-256{' '}
            <code>{evidence[`${source}_sha256`]}</code>
          </p>
          <button className={hrButtonClass} type="button" disabled={Boolean(pending)}
            onClick={() => void save(source, evidence[`${source}_sha256`])}>
            Download frozen {source} CSV
          </button>
        </div>
      ))}
      {pending && <p role="status">Verifying frozen {pending} CSV…</p>}
      {error && <p role="alert">{error}</p>}
    </section>
  );
}
