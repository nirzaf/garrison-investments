import { useState } from 'react';
import { useQueryClient } from '@tanstack/react-query';

import { formatApiError } from '../../api/errors';
import { stageAttendanceImport, type HrSchemas } from '../../api/hr';
import { hrButtonClass, hrInputClass } from './HRAccessForms';

const HEADER = 'employee_code,work_date,attendance_status,worked_hours,check_in_at,check_out_at';

export function HRAttendanceImport() {
  const client = useQueryClient();
  const [file, setFile] = useState<File | null>(null);
  const [preview, setPreview] = useState<HrSchemas['AttendanceImportPreviewResponse'] | null>(null);
  const [pending, setPending] = useState(false);
  const [message, setMessage] = useState('');
  const [error, setError] = useState('');
  async function load(apply: boolean) {
    if (!file || pending || (apply && !preview?.digest)) return;
    setPending(true);
    setError('');
    setMessage('');
    try {
      const result = await stageAttendanceImport(
        file,
        apply ? (preview?.digest ?? undefined) : undefined
      );
      if (apply) {
        setPreview(null);
        setMessage(`${result.items.length} attendance entries submitted for review.`);
        await client.invalidateQueries({ queryKey: ['hr', 'time'] });
      } else {
        setPreview(result);
      }
    } catch (failure) {
      setPreview(null);
      setError(formatApiError(failure, 'Could not process attendance CSV.'));
    } finally {
      setPending(false);
    }
  }

  return (
    <details className="space-y-3 rounded border border-theme-border p-3">
      <summary className="cursor-pointer font-semibold">Import attendance CSV</summary>
      <p>
        Use ISO dates and clock timestamps with offsets. For overnight work, use the start date as
        the work date and enter the actual end date in the check-out timestamp. Leave both clock
        columns blank for records without clock times.
      </p>
      <a
        href={`data:text/csv,${encodeURIComponent(`${HEADER}\n`)}`}
        download="attendance-template.csv"
        className="text-brand-600 underline"
      >
        Download CSV header
      </a>
      <div className="flex flex-wrap items-end gap-3">
        <label>
          Attendance CSV{' '}
          <input
            type="file"
            className={hrInputClass}
            accept=".csv,text/csv"
            disabled={pending}
            onChange={(event) => {
              setFile(event.target.files?.[0] ?? null);
              setPreview(null);
              setError('');
              setMessage('');
            }}
          />
        </label>
        <button
          type="button"
          className={hrButtonClass}
          disabled={pending || !file}
          onClick={() => void load(false)}
        >
          Preview attendance
        </button>
        <button
          type="button"
          className={hrButtonClass}
          disabled={pending || !preview?.digest}
          onClick={() => void load(true)}
        >
          Apply attendance import
        </button>
      </div>
      {error && <p role="alert">{error}</p>}
      {message && <p role="status">{message}</p>}
      {preview && (
        <ul className="space-y-1" aria-label="Attendance import preview">
          {preview.items.map((row) => (
            <li key={row.row}>
              Row {row.row} · {row.employee_code ?? 'Missing employee code'} ·{' '}
              {row.work_date ?? 'Unknown date'} ·{' '}
              {row.error ?? `${row.attendance_status} · ${row.worked_hours} h`}
              {!row.error && row.check_in_at && row.check_out_at && (
                <span className="block break-words text-sm text-theme-text-muted">
                  Check-in <time dateTime={row.check_in_at}>{row.check_in_at}</time>
                  {' · '}Check-out <time dateTime={row.check_out_at}>{row.check_out_at}</time>
                </span>
              )}
            </li>
          ))}
        </ul>
      )}
    </details>
  );
}
