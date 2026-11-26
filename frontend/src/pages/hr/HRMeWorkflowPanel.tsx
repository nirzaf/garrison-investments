import { useQuery, useQueryClient } from '@tanstack/react-query';
import { type FormEvent, useState } from 'react';

import { formatApiError } from '../../api/errors';
import {
  getMyHrWorkflowOptions,
  getMyTimeRecords,
  listMyLeaveReviews,
  listMyManagerReviews,
  decideMyLeaveReview,
  recommendMyDirectReport,
  resubmitMyTimesheet,
  submitMyOvertime,
  submitMyTimesheet,
  type ManagerReviewItem,
  type SupervisorLeaveReviewRecord,
  type TimesheetRecord
} from '../../api/hr';
import { useAuth } from '../../context/useAuth';
import { hrButtonClass, hrInputClass } from './HRAccessForms';

const PAGE_SIZE = 25;

export function HRMeWorkflowPanel() {
  const { user } = useAuth();
  const userId = user?.id ?? '';
  const options = useQuery({
    queryKey: ['hr', 'me', userId, 'workflow-options'],
    queryFn: ({ signal }) => getMyHrWorkflowOptions(signal),
    enabled: Boolean(userId)
  });
  return (
    <>
      {options.isError && (
        <p role="alert">{formatApiError(options.error, 'Could not load HR workflow options.')}</p>
      )}
      {options.data && !options.data.hr_leave_approver_configured && (
        <p role="status" className="rounded border border-amber-400 p-3 text-sm">
          HR fallback leave approval is not currently staffed. Direct supervisor decisions remain
          available when an eligible supervisor is assigned; contact HR to correct the fallback
          setup before relying on HR approval.
        </p>
      )}
      {options.data?.can_recommend && <ManagerReviewQueue userId={userId} />}
      {options.data?.can_decide_leave && <SupervisorLeaveQueue userId={userId} />}
      {options.data?.self_time_submission_enabled && <SelfTimeRequests userId={userId} />}
    </>
  );
}

function SupervisorLeaveQueue({ userId }: { userId: string }) {
  const client = useQueryClient();
  const [offset, setOffset] = useState(0);
  const [pending, setPending] = useState(false);
  const [error, setError] = useState('');
  const [notice, setNotice] = useState('');
  const [notes, setNotes] = useState<Record<string, string>>({});
  const queueKey = ['hr', 'me', userId, 'leave-reviews'];
  const queue = useQuery({
    queryKey: [...queueKey, offset],
    queryFn: ({ signal }) => listMyLeaveReviews(offset, PAGE_SIZE, signal)
  });

  async function decide(item: SupervisorLeaveReviewRecord, decision: 'approved' | 'rejected') {
    if (pending) return;
    const note = (notes[item.id] ?? '').trim();
    if (decision === 'rejected' && !note) {
      setError('Enter a reason before rejecting a leave request.');
      return;
    }
    setPending(true);
    setError('');
    setNotice('');
    try {
      await decideMyLeaveReview(item, decision, note || undefined);
      setNotice(decision === 'approved' ? 'Leave request approved.' : 'Leave request rejected.');
      setNotes((current) => ({ ...current, [item.id]: '' }));
    } catch (failure) {
      setError(formatApiError(failure, 'Could not decide the leave request.'));
    } finally {
      await client.invalidateQueries({ queryKey: queueKey });
      setPending(false);
    }
  }

  return (
    <section className="space-y-3 rounded-lg border border-theme-border bg-theme-card p-5">
      <h3 className="font-semibold">Direct-report leave approvals</h3>
      <p className="text-sm text-theme-text-muted">
        Your decision is final. HR can view requests and can take over only through a recorded
        fallback route.
      </p>
      {queue.isFetching && <p role="status">Loading leave approvals…</p>}
      {queue.isError && (
        <p role="alert">
          {formatApiError(queue.error, 'Could not load direct-report leave approvals.')}{' '}
          <button type="button" onClick={() => void queue.refetch()}>Retry</button>
        </p>
      )}
      {error && <p role="alert">{error}</p>}
      {notice && <p role="status">{notice}</p>}
      {queue.data?.items.length === 0 && <p>No leave requests need your decision.</p>}
      <ul className="space-y-3">
        {queue.data?.items.map((item) => (
          <li key={item.id} className="space-y-2 border-b border-theme-border pb-3">
            <p>
              {item.employee_name} · {item.start_date}
              {item.end_date !== item.start_date ? ` to ${item.end_date}` : ''} ·{' '}
              {item.chargeable_units} days
            </p>
            <label className="block text-sm">
              Decision note (required for rejection)
              <input
                className={hrInputClass}
                maxLength={500}
                value={notes[item.id] ?? ''}
                onChange={(event) =>
                  setNotes((current) => ({ ...current, [item.id]: event.target.value }))
                }
              />
            </label>
            <div className="flex gap-2">
              <button
                type="button"
                className={hrButtonClass}
                disabled={pending || item.status !== 'submitted'}
                onClick={() => void decide(item, 'approved')}
              >
                Approve
              </button>
              <button
                type="button"
                className={hrButtonClass}
                disabled={pending || item.status !== 'submitted' || !notes[item.id]?.trim()}
                onClick={() => void decide(item, 'rejected')}
              >
                Reject
              </button>
            </div>
          </li>
        ))}
      </ul>
      {(offset > 0 || (queue.data?.total ?? 0) > PAGE_SIZE) && (
        <div className="flex gap-2">
          <button
            type="button"
            className={hrButtonClass}
            disabled={pending || offset === 0}
            onClick={() => setOffset(offset - PAGE_SIZE)}
          >
            Previous requests
          </button>
          <button
            type="button"
            className={hrButtonClass}
            disabled={pending || offset + PAGE_SIZE >= (queue.data?.total ?? 0)}
            onClick={() => setOffset(offset + PAGE_SIZE)}
          >
            Next requests
          </button>
        </div>
      )}
    </section>
  );
}

function ManagerReviewQueue({ userId }: { userId: string }) {
  const client = useQueryClient();
  const [offset, setOffset] = useState(0);
  const [pending, setPending] = useState(false);
  const [error, setError] = useState('');
  const [notice, setNotice] = useState('');
  const queueKey = ['hr', 'me', userId, 'manager-reviews'];
  const queue = useQuery({
    queryKey: [...queueKey, offset],
    queryFn: ({ signal }) => listMyManagerReviews(offset, PAGE_SIZE, signal)
  });

  async function recommend(item: ManagerReviewItem, recommendation: 'support' | 'flag') {
    if (pending) return;
    setPending(true);
    setError('');
    setNotice('');
    try {
      await recommendMyDirectReport(item, recommendation);
      setNotice('Recommendation recorded. HR will make the final decision.');
    } catch (error) {
      setError(formatApiError(error, 'Could not record the recommendation.'));
    } finally {
      await client.invalidateQueries({ queryKey: queueKey });
      setPending(false);
    }
  }

  return (
    <section className="space-y-3 rounded-lg border border-theme-border bg-theme-card p-5">
      <h3 className="font-semibold">Line-manager reviews</h3>
      {queue.isFetching && <p role="status">Loading reviews…</p>}
      {queue.isError && (
        <p role="alert">{formatApiError(queue.error, 'Could not load line-manager reviews.')}</p>
      )}
      {error && <p role="alert">{error}</p>}
      {notice && <p role="status">{notice}</p>}
      {queue.data?.items.length === 0 && <p>No pending reviews on this page.</p>}
      <ul className="space-y-2">
        {queue.data?.items.map((item) => (
          <li
            key={`${item.kind}-${item.id}`}
            className="flex flex-wrap items-center justify-between gap-3 border-b border-theme-border pb-2"
          >
            <p>
              {item.employee_name} · {item.kind} · {item.start_date}
              {item.end_date !== item.start_date ? ` to ${item.end_date}` : ''} ·{' '}
              {item.requested_amount} {item.kind === 'leave' ? 'days' : 'hours'}
            </p>
            <div className="flex gap-2">
              <button
                type="button"
                disabled={pending}
                className={hrButtonClass}
                onClick={() => void recommend(item, 'support')}
              >
                Recommend
              </button>
              <button
                type="button"
                disabled={pending}
                className={hrButtonClass}
                onClick={() => void recommend(item, 'flag')}
              >
                Flag for HR
              </button>
            </div>
          </li>
        ))}
      </ul>
      {(offset > 0 || queue.data?.has_more) && (
        <div className="flex gap-2">
          <button
            type="button"
            className={hrButtonClass}
            disabled={pending || offset === 0}
            onClick={() => setOffset(offset - PAGE_SIZE)}
          >
            Previous reviews
          </button>
          <button
            type="button"
            className={hrButtonClass}
            disabled={pending || !queue.data?.has_more}
            onClick={() => setOffset(offset + PAGE_SIZE)}
          >
            Next reviews
          </button>
        </div>
      )}
    </section>
  );
}

function SelfTimeRequests({ userId }: { userId: string }) {
  const client = useQueryClient();
  const [kind, setKind] = useState<'timesheet' | 'overtime'>('timesheet');
  const [editing, setEditing] = useState<TimesheetRecord | null>(null);
  const [pending, setPending] = useState(false);
  const [error, setError] = useState('');
  const [notice, setNotice] = useState('');
  const timeKey = ['hr', 'me', userId, 'time'];
  const records = useQuery({
    queryKey: timeKey,
    queryFn: ({ signal }) => getMyTimeRecords(signal)
  });

  async function submit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (pending) return;
    const form = event.currentTarget;
    const fields = new FormData(form);
    const field = (name: string) => String(fields.get(name) ?? '');
    setPending(true);
    setError('');
    setNotice('');
    try {
      if (kind === 'overtime') {
        await submitMyOvertime({
          work_date: field('start'),
          requested_hours: field('hours'),
          reason: field('notes')
        });
      } else {
        const hours = {
          regular_hours: field('hours'),
          overtime_hours: field('overtime') || '0',
          notes: field('notes') || null
        };
        if (editing) {
          await resubmitMyTimesheet(editing.id, {
            ...hours,
            expected_revision: editing.record_revision
          });
          setEditing(null);
        } else {
          await submitMyTimesheet({
            ...hours,
            period_start: field('start'),
            period_end: field('end')
          });
        }
      }
      setNotice(kind === 'overtime' ? 'Overtime submitted.' : 'Timesheet submitted.');
      form.reset();
      await client.invalidateQueries({ queryKey: timeKey });
    } catch (error) {
      setError(formatApiError(error, 'Could not submit time.'));
    } finally {
      setPending(false);
    }
  }

  return (
    <section className="space-y-3 rounded-lg border border-theme-border bg-theme-card p-5">
      <h3 className="font-semibold">My time requests</h3>
      {records.isLoading && <p role="status">Loading time requests…</p>}
      {records.isError && (
        <p role="alert">{formatApiError(records.error, 'Could not load time requests.')}</p>
      )}
      {error && <p role="alert">{error}</p>}
      {notice && <p role="status">{notice}</p>}
      <form
        key={editing?.id ?? kind}
        className="grid items-end gap-3 sm:grid-cols-2"
        onSubmit={(event) => void submit(event)}
      >
        {editing ? (
          <p>
            Resubmitting {editing.period_start} to {editing.period_end}
          </p>
        ) : (
          <>
            <label>
              Time request type
              <select
                className={hrInputClass}
                value={kind}
                onChange={(event) => setKind(event.target.value as typeof kind)}
              >
                <option value="timesheet">Timesheet</option>
                <option value="overtime">Overtime</option>
              </select>
            </label>
            <label>
              {kind === 'timesheet' ? 'Period starts' : 'Overtime date'}{' '}
              <input name="start" type="date" required className={hrInputClass} />
            </label>
            {kind === 'timesheet' && (
              <label>
                Period ends <input name="end" type="date" required className={hrInputClass} />
              </label>
            )}
          </>
        )}
        <label>
          {kind === 'timesheet' ? 'Regular hours' : 'Requested overtime hours'}{' '}
          <input
            name="hours"
            type="number"
            min={kind === 'timesheet' ? '0' : '0.01'}
            step="0.01"
            required
            className={hrInputClass}
            defaultValue={editing?.regular_hours}
          />
        </label>
        {kind === 'timesheet' && (
          <label>
            Overtime hours{' '}
            <input
              name="overtime"
              type="number"
              min="0"
              step="0.01"
              className={hrInputClass}
              defaultValue={editing?.overtime_hours}
            />
          </label>
        )}
        <label>
          {kind === 'timesheet' ? 'Time notes' : 'Overtime reason'}{' '}
          <input
            name="notes"
            required={kind === 'overtime'}
            maxLength={500}
            className={hrInputClass}
            defaultValue={editing?.notes ?? ''}
          />
        </label>
        <div className="flex gap-2">
          <button type="submit" disabled={pending} className={hrButtonClass}>
            {editing ? 'Resubmit timesheet' : `Submit ${kind}`}
          </button>
          {editing && (
            <button
              type="button"
              disabled={pending}
              className={hrButtonClass}
              onClick={() => setEditing(null)}
            >
              Cancel edit
            </button>
          )}
        </div>
      </form>
      <ul className="space-y-2">
        {records.data?.timesheets.map((record) => (
          <li key={record.id}>
            {record.period_start} to {record.period_end} · {record.regular_hours} regular hours ·{' '}
            {record.status}
            {record.rejection_reason && <p>{record.rejection_reason}</p>}
            {['draft', 'rejected'].includes(record.status) && (
              <button
                type="button"
                className={hrButtonClass}
                disabled={pending}
                onClick={() => {
                  setKind('timesheet');
                  setEditing(record);
                }}
              >
                Edit timesheet
              </button>
            )}
          </li>
        ))}
        {records.data?.overtime.map((record) => (
          <li key={record.id}>
            {record.work_date} · {record.requested_hours} overtime hours · {record.status}
          </li>
        ))}
      </ul>
    </section>
  );
}
