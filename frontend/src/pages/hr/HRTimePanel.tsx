import { useQuery, useQueryClient } from '@tanstack/react-query';
import { type FormEvent, useState } from 'react';

import { formatApiError } from '../../api/errors';
import {
  createAttendance,
  createAttendanceCorrection,
  createOvertimeRequest,
  createTimesheet,
  decideAttendance,
  decideAttendanceCorrection,
  decideOvertimeRequest,
  decideTimesheet,
  listAttendance,
  listAttendanceCorrections,
  listOvertimeRequests,
  listTimesheets,
  type EmployeeDirectoryRecord
} from '../../api/hr';
import { hrButtonClass, hrInputClass } from './HRAccessForms';
import { HRWorkCalendar } from './HRWorkCalendar';
import { HRAttendanceImport } from './HRAttendanceImport';
import { HRRoster } from './HRRoster';

type TimeForm = 'attendance' | 'correction' | 'timesheet' | 'overtime';

export function HRTimePanel({
  employees,
  canReview
}: {
  employees: EmployeeDirectoryRecord[];
  canReview: boolean;
}) {
  const client = useQueryClient();
  const [kind, setKind] = useState<TimeForm>('attendance');
  const [error, setError] = useState('');
  const [pending, setPending] = useState(false);
  const ledger = useQuery({
    queryKey: ['hr', 'time'],
    queryFn: async () => {
      const [attendance, corrections, timesheets, overtime] = await Promise.all([
        listAttendance(),
        listAttendanceCorrections(),
        listTimesheets(),
        listOvertimeRequests()
      ]);
      return { attendance, corrections, timesheets, overtime };
    }
  });

  async function change(action: () => Promise<unknown>) {
    if (pending) return;
    setPending(true);
    setError('');
    try {
      await action();
      await client.invalidateQueries({ queryKey: ['hr', 'time'] });
    } catch (failure) {
      setError(formatApiError(failure, 'Could not update time records.'));
    } finally {
      setPending(false);
    }
  }

  function record(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    const form = event.currentTarget;
    const values = new FormData(form);
    const value = (name: string) => String(values.get(name) ?? '');
    const employee_id = value('employee');
    const work_date = value('date');
    const hours = value('hours');
    const attendance_status = value('status') as Parameters<
      typeof createAttendance
    >[0]['attendance_status'];
    const reason = value('reason');
    void change(async () => {
      if (kind === 'attendance')
        await createAttendance({
          employee_id,
          work_date,
          worked_hours: hours,
          attendance_status,
          source: 'manual'
        });
      if (kind === 'correction')
        await createAttendanceCorrection({
          employee_id,
          work_date,
          requested_worked_hours: hours,
          requested_status: attendance_status,
          reason
        });
      if (kind === 'timesheet')
        await createTimesheet({
          employee_id,
          period_start: work_date,
          period_end: value('end'),
          regular_hours: hours,
          overtime_hours: value('overtime') || '0',
          submit: true
        });
      if (kind === 'overtime')
        await createOvertimeRequest({ employee_id, work_date, requested_hours: hours, reason });
      form.reset();
    });
  }

  function name(id: string) {
    return employees.find((employee) => employee.id === id)?.full_name ?? id;
  }

  return (
    <section className="space-y-4 rounded-lg border border-theme-border bg-theme-card p-5">
      <h3 className="font-semibold">Attendance and time</h3>
      <HRWorkCalendar employees={employees} canReview={canReview} />
      <HRRoster />
      <HRAttendanceImport />
      {ledger.isPending && <p role="status">Loading time records…</p>}
      {ledger.isError && (
        <p role="alert">{formatApiError(ledger.error, 'Could not load time records.')}</p>
      )}
      {error && (
        <p role="alert" className="text-red-700">
          {error}
        </p>
      )}
      <form className="grid gap-3 sm:grid-cols-2 lg:grid-cols-3" onSubmit={record}>
        <label>
          Record type{' '}
          <select
            value={kind}
            className={hrInputClass}
            onChange={(event) => setKind(event.target.value as TimeForm)}
          >
            <option value="attendance">Attendance</option>
            <option value="correction">Attendance correction</option>
            <option value="timesheet">Timesheet</option>
            <option value="overtime">Overtime request</option>
          </select>
        </label>
        <label>
          Employee{' '}
          <input name="employee" list="hr-time-employees" className={hrInputClass} required />
        </label>
        <datalist id="hr-time-employees">
          {employees.map((employee) => (
            <option key={employee.id} value={employee.id}>
              {employee.full_name}
            </option>
          ))}
        </datalist>
        <label>
          {kind === 'timesheet' ? 'Period start' : 'Work date'}{' '}
          <input name="date" type="date" className={hrInputClass} required />
        </label>
        <label>
          {kind === 'timesheet' ? 'Regular hours' : 'Hours'}{' '}
          <input name="hours" type="number" min="0" step="0.01" className={hrInputClass} required />
        </label>
        {(kind === 'attendance' || kind === 'correction') && (
          <label>
            Attendance status{' '}
            <select name="status" className={hrInputClass}>
              <option value="present">Present</option>
              <option value="absent">Absent</option>
              <option value="half_day">Half day</option>
              <option value="on_leave">Leave</option>
              <option value="holiday">Holiday</option>
              <option value="remote">Remote</option>
              <option value="site_duty">Site duty</option>
            </select>
          </label>
        )}
        {kind === 'timesheet' && (
          <>
            <label>
              Period end <input name="end" type="date" className={hrInputClass} required />
            </label>
            <label>
              Overtime hours{' '}
              <input name="overtime" type="number" min="0" step="0.01" className={hrInputClass} />
            </label>
          </>
        )}
        {(kind === 'correction' || kind === 'overtime') && (
          <label>
            Reason <input name="reason" className={hrInputClass} required />
          </label>
        )}
        <div className="self-end">
          <button type="submit" className={hrButtonClass} disabled={pending}>
            Save time record
          </button>
        </div>
      </form>
      {ledger.data?.attendance.items.length === 0 && (
        <p className="text-theme-text-muted">No attendance recorded.</p>
      )}
      {ledger.data?.attendance.items.map((entry) => (
        <div key={entry.id} className="space-y-1 border-b border-theme-border pb-2">
          <p>
            {name(entry.employee_id)} · {entry.work_date} · {entry.attendance_status} ·{' '}
            {entry.worked_hours} h ·{' '}
            {entry.scheduled_workday === null
              ? 'Schedule unavailable'
              : entry.scheduled_workday
                ? 'Scheduled workday'
                : 'Scheduled non-working day'}
            {' · '}
            {entry.status}
            {entry.manager_recommendation &&
              ` · Manager recommendation: ${entry.manager_recommendation}`}
          </p>
          {entry.review_note && <p>{entry.review_note}</p>}
          {canReview && entry.status === 'submitted' && entry.source !== 'site' && (
            <div className="flex flex-wrap items-end gap-2">
              <button
                className={hrButtonClass}
                disabled={pending}
                type="button"
                onClick={() =>
                  void change(() =>
                    decideAttendance(entry.id, {
                      decision: 'approved',
                      expected_revision: entry.record_revision
                    })
                  )
                }
              >
                Approve attendance
              </button>
              <form
                className="flex flex-wrap items-end gap-2"
                onSubmit={(event) => {
                  event.preventDefault();
                  const note = String(new FormData(event.currentTarget).get('note') ?? '');
                  void change(() =>
                    decideAttendance(entry.id, {
                      decision: 'returned',
                      note,
                      expected_revision: entry.record_revision
                    })
                  );
                }}
              >
                <label>
                  Attendance return reason{' '}
                  <input name="note" className={hrInputClass} required maxLength={500} />
                </label>
                <button className={hrButtonClass} disabled={pending} type="submit">
                  Return attendance
                </button>
              </form>
            </div>
          )}
        </div>
      ))}
      <div className="grid gap-4 lg:grid-cols-3">
        <div>
          <h4 className="font-semibold">Attendance corrections</h4>
          {ledger.data?.corrections.items.map((row) => (
            <div className="border-b border-theme-border py-2" key={row.id}>
              <p>
                {name(row.employee_id)} · {row.work_date} · {row.status}
              </p>
              {canReview && row.status === 'submitted' && (
                <button
                  className={hrButtonClass}
                  disabled={pending}
                  type="button"
                  onClick={() =>
                    void change(() => decideAttendanceCorrection(row.id, { decision: 'approved' }))
                  }
                >
                  Approve correction
                </button>
              )}
              {canReview && row.status === 'submitted' && (
                <form
                  className="mt-2 flex flex-wrap items-end gap-2"
                  onSubmit={(event) => {
                    event.preventDefault();
                    const notes = String(new FormData(event.currentTarget).get('note') ?? '');
                    void change(() =>
                      decideAttendanceCorrection(row.id, { decision: 'rejected', notes })
                    );
                  }}
                >
                  <label>
                    Correction rejection reason{' '}
                    <input name="note" className={hrInputClass} required />
                  </label>
                  <button type="submit" disabled={pending} className={hrButtonClass}>
                    Reject correction
                  </button>
                </form>
              )}
            </div>
          ))}
        </div>
        <div>
          <h4 className="font-semibold">Timesheets</h4>
          {ledger.data?.timesheets.items.map((row) => (
            <div className="border-b border-theme-border py-2" key={row.id}>
              <p>
                {name(row.employee_id)} · {row.period_start} to {row.period_end} · {row.status}
                {row.manager_recommendation &&
                  ` · Manager recommendation: ${row.manager_recommendation}`}
              </p>
              {canReview && ['submitted', 'approved'].includes(row.status) && (
                <button
                  className={hrButtonClass}
                  disabled={pending}
                  type="button"
                  onClick={() =>
                    void change(() =>
                      decideTimesheet(row.id, {
                        decision: row.status === 'submitted' ? 'approved' : 'locked',
                        expected_revision: row.record_revision
                      })
                    )
                  }
                >
                  {row.status === 'submitted' ? 'Approve timesheet' : 'Lock timesheet'}
                </button>
              )}
              {canReview && row.status === 'submitted' && (
                <form
                  className="mt-2 flex flex-wrap items-end gap-2"
                  onSubmit={(event) => {
                    event.preventDefault();
                    const notes = String(new FormData(event.currentTarget).get('reason') ?? '');
                    void change(() =>
                      decideTimesheet(row.id, {
                        decision: 'rejected',
                        notes,
                        expected_revision: row.record_revision
                      })
                    );
                  }}
                >
                  <label>
                    Timesheet rejection reason{' '}
                    <input name="reason" className={hrInputClass} required />
                  </label>
                  <button type="submit" disabled={pending} className={hrButtonClass}>
                    Reject timesheet
                  </button>
                </form>
              )}
            </div>
          ))}
        </div>
        <div>
          <h4 className="font-semibold">Overtime</h4>
          {ledger.data?.overtime.items.map((row) => (
            <div className="border-b border-theme-border py-2" key={row.id}>
              <p>
                {name(row.employee_id)} · {row.work_date} · {row.requested_hours} h · {row.status}
                {row.manager_recommendation &&
                  ` · Manager recommendation: ${row.manager_recommendation}`}
              </p>
              {canReview && row.status === 'submitted' && (
                <button
                  className={hrButtonClass}
                  disabled={pending}
                  type="button"
                  onClick={() =>
                    void change(() =>
                      decideOvertimeRequest(row.id, {
                        decision: 'approved',
                        expected_revision: row.record_revision
                      })
                    )
                  }
                >
                  Approve overtime
                </button>
              )}
              {canReview && row.status === 'submitted' && (
                <form
                  className="mt-2 flex flex-wrap items-end gap-2"
                  onSubmit={(event) => {
                    event.preventDefault();
                    const notes = String(new FormData(event.currentTarget).get('reason') ?? '');
                    void change(() =>
                      decideOvertimeRequest(row.id, {
                        decision: 'rejected',
                        notes,
                        expected_revision: row.record_revision
                      })
                    );
                  }}
                >
                  <label>
                    Overtime rejection reason{' '}
                    <input name="reason" className={hrInputClass} required />
                  </label>
                  <button type="submit" disabled={pending} className={hrButtonClass}>
                    Reject overtime
                  </button>
                </form>
              )}
            </div>
          ))}
        </div>
      </div>
    </section>
  );
}
