import { useQuery } from '@tanstack/react-query';
import { useState } from 'react';

import { formatApiError } from '../../api/errors';
import { getHrLetter, listHrLetters } from '../../api/hr';

export function HRResponseLetter({
  letterId,
  employeeId,
  label = 'Open response letter'
}: {
  letterId: string;
  employeeId?: string;
  label?: string;
}) {
  const [open, setOpen] = useState(false);
  const detail = useQuery({
    queryKey: ['hr', 'letter-detail', employeeId ?? 'me', letterId],
    queryFn: () => getHrLetter(employeeId, letterId),
    enabled: open,
    gcTime: 0
  });

  return (
    <div className="basis-full space-y-2">
      <button
        type="button"
        className="rounded border border-theme-border px-2 py-1"
        onClick={() => setOpen(!open)}
        aria-expanded={open}
      >
        {open ? 'Close response letter' : label}
      </button>
      {open && (
        <article className="space-y-1 rounded border border-theme-border p-3">
          {detail.isPending && <p role="status">Opening letter…</p>}
          {detail.isError && (
            <p role="alert">
              {formatApiError(detail.error, 'Unable to open this letter.')}{' '}
              <button type="button" onClick={() => void detail.refetch()}>Retry</button>
            </p>
          )}
          {detail.isSuccess && (
            <>
              <h4 className="font-semibold">{detail.data.subject}</h4>
              <p className="whitespace-pre-wrap break-words">{detail.data.body}</p>
            </>
          )}
        </article>
      )}
    </div>
  );
}

const size = 20;

export function HRIssuedLetterPicker({
  employeeId,
  value,
  onChange,
  disabled
}: {
  employeeId: string;
  value: string;
  onChange: (value: string) => void;
  disabled: boolean;
}) {
  const [enabled, setEnabled] = useState(false);
  const [offset, setOffset] = useState(0);
  const letters = useQuery({
    queryKey: ['hr', 'letters', employeeId, 'issued', offset],
    queryFn: () => listHrLetters(employeeId, offset, size, true),
    enabled
  });
  const options = letters.data?.items ?? [];

  function move(next: number) {
    onChange('');
    setOffset(next);
  }

  return (
    <details className="space-y-2" onToggle={(event) => {
      if (event.currentTarget.open) setEnabled(true);
    }}>
      <summary>Attach issued letter</summary>
      {enabled && letters.isPending && <p role="status">Loading issued letters…</p>}
      {letters.isError && (
        <p role="alert">
          {formatApiError(letters.error, 'Unable to list issued letters.')}{' '}
          <button type="button" onClick={() => void letters.refetch()}>Retry</button>
        </p>
      )}
      {letters.isSuccess && !letters.data.total && <p>No issued letters for this employee.</p>}
      {options.length > 0 && (
        <label className="block">
          Issued response letter{' '}
          <select
            value={value}
            disabled={disabled}
            onChange={(event) => onChange(event.target.value)}
            className="rounded border border-theme-border bg-theme-input"
          >
            <option value="">Keep the current response</option>
            {options.map((letter) => (
              <option value={letter.id} key={letter.id}>
                {letter.template_name} · {letter.decided_at?.slice(0, 10)}
              </option>
            ))}
          </select>
        </label>
      )}
      {letters.isSuccess && letters.data.total > size && (
        <div className="flex gap-2">
          <button type="button" disabled={disabled || offset === 0}
            onClick={() => move(offset - size)}>Previous letters</button>
          <button type="button" disabled={disabled || offset + size >= letters.data.total}
            onClick={() => move(offset + size)}>Next letters</button>
        </div>
      )}
      {value && <HRResponseLetter key={value} employeeId={employeeId} letterId={value}
        label="Preview selected response letter" />}
    </details>
  );
}
