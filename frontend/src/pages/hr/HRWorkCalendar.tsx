import { skipToken, useQuery, useQueryClient } from '@tanstack/react-query';
import { type FormEvent, useState } from 'react';

import { formatApiError } from '../../api/errors';
import {
  createCalendar,
  createHoliday,
  createShift,
  decideCalendar,
  getWorkSchedule,
  listCalendars,
  listHolidays,
  listShifts,
  updateCalendar,
  type EmployeeDirectoryRecord,
  type HrSchemas,
  type WorkCalendarRecord
} from '../../api/hr';
import { useAuth } from '../../context/useAuth';
import { hrButtonClass, hrInputClass } from './HRAccessForms';

const WEEKDAYS = ['MON', 'TUE', 'WED', 'THU', 'FRI', 'SAT', 'SUN'] as const;

export function HRWorkCalendar({
  employees,
  canReview
}: {
  employees: EmployeeDirectoryRecord[];
  canReview: boolean;
}) {
  const client = useQueryClient();
  const { user } = useAuth();
  const [expanded, setExpanded] = useState(false);
  const [formType, setFormType] = useState<'calendar' | 'holiday' | 'shift'>('calendar');
  const [error, setError] = useState('');
  const [pending, setPending] = useState(false);
  const [editing, setEditing] = useState<WorkCalendarRecord | null>(null);
  const [lookup, setLookup] = useState<{ employeeId: string; date: string } | null>(null);
  const schedule = useQuery({
    queryKey: ['hr', 'schedule'],
    enabled: expanded,
    queryFn: async () => {
      const [calendars, holidays, shifts] = await Promise.all([
        listCalendars(),
        listHolidays(),
        listShifts()
      ]);
      return { calendars: calendars.items, holidays: holidays.items, shifts: shifts.items };
    }
  });
  const workday = useQuery({
    queryKey: ['hr', 'schedule', lookup],
    queryFn: lookup ? () => getWorkSchedule(lookup.employeeId, lookup.date) : skipToken
  });

  async function change(action: () => Promise<unknown>, message: string) {
    if (pending) return;
    setPending(true);
    setError('');
    try {
      await action();
      await client.invalidateQueries({ queryKey: ['hr', 'schedule'] });
    } catch (failure) {
      setError(formatApiError(failure, message));
    } finally {
      setPending(false);
    }
  }

  async function save(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    const form = event.currentTarget;
    const fields = new FormData(form);
    const field = (name: string) => String(fields.get(name) ?? '');
    await change(async () => {
      if (formType === 'calendar') {
        const calendar = {
          code: field('code'),
          name: field('name'),
          work_days_json: WEEKDAYS.filter((day) => fields.has(day)),
          standard_start_time: field('start_time'),
          standard_end_time: field('end_time'),
          daily_hours: field('hours'),
          effective_from: field('date'),
          effective_to: field('end_date'),
          timezone: field('timezone'),
          is_default: fields.has('default'),
          project_id: field('project_id').trim() || null
        };
        if (editing) {
          await updateCalendar(editing.id, { ...calendar, expected_revision: editing.revision });
          setEditing(null);
        } else {
          await createCalendar(calendar);
        }
      } else if (formType === 'holiday') {
        await createHoliday({
          calendar_id: field('calendar'),
          name: field('name'),
          holiday_date: field('date'),
          holiday_type: 'company',
          is_paid: fields.has('paid')
        });
      } else {
        await createShift({
          employee_id: field('employee'),
          calendar_id: field('calendar'),
          shift_name: field('name'),
          effective_from: field('date'),
          effective_to: field('end_date') || null,
          start_time: field('start_time'),
          end_time: field('end_time')
        });
      }
      form.reset();
    }, 'Could not save the work schedule.');
  }

  async function decide(
    calendar: WorkCalendarRecord,
    action: HrSchemas['WorkCalendarDecisionRequest']['action'],
    reason?: string
  ) {
    await change(
      () => decideCalendar(calendar.id, { action, expected_revision: calendar.revision, reason }),
      'Could not change the calendar status.'
    );
  }

  return (
    <details
      className="space-y-3 border-t border-theme-border pt-3"
      onToggle={(event) => setExpanded(event.currentTarget.open)}
    >
      <summary className="cursor-pointer font-semibold">
        Work calendars, holidays and shifts
      </summary>
      {schedule.isLoading && <p role="status">Loading schedules…</p>}
      {schedule.isError && (
        <p role="alert">{formatApiError(schedule.error, 'Could not load schedules.')}</p>
      )}
      {error && (
        <p role="alert" className="text-red-700">
          {error}
        </p>
      )}
      <form
        key={editing?.id ?? 'create-schedule'}
        className="grid items-end gap-3 sm:grid-cols-2 lg:grid-cols-3"
        onSubmit={(event) => void save(event)}
      >
        <label>
          Schedule record{' '}
          <select
            value={formType}
            className={hrInputClass}
            onChange={(event) => {
              setEditing(null);
              setFormType(event.target.value as typeof formType);
            }}
          >
            <option value="calendar">Work calendar</option>
            <option value="holiday">Company holiday</option>
            {canReview && <option value="shift">Employee shift</option>}
          </select>
        </label>
        <label>
          Name <input name="name" className={hrInputClass} defaultValue={editing?.name} required />
        </label>
        {formType === 'calendar' ? (
          <>
            <label>
              Calendar code{' '}
              <input name="code" className={hrInputClass} defaultValue={editing?.code} required />
            </label>
            <label>
              Calendar effective from{' '}
              <input
                name="date"
                type="date"
                className={hrInputClass}
                defaultValue={editing?.effective_from ?? ''}
                required
              />
            </label>
            <label>
              Calendar effective through{' '}
              <input
                name="end_date"
                type="date"
                className={hrInputClass}
                defaultValue={editing?.effective_to ?? ''}
                required
              />
            </label>
            <label>
              IANA timezone{' '}
              <input
                name="timezone"
                className={hrInputClass}
                placeholder="Asia/Colombo"
                defaultValue={editing?.timezone ?? ''}
                required
              />
            </label>
            <label>
              Project ID (optional){' '}
              <input
                name="project_id"
                className={hrInputClass}
                defaultValue={editing?.project_id ?? ''}
              />
            </label>
            <label>
              <input name="default" type="checkbox" defaultChecked={editing?.is_default ?? false} />{' '}
              Company default
            </label>
            <fieldset className="flex flex-wrap gap-2">
              <legend>Workdays</legend>
              {WEEKDAYS.map((day) => (
                <label key={day}>
                  <input
                    name={day}
                    type="checkbox"
                    defaultChecked={editing?.work_days_json.includes(day)}
                  />{' '}
                  {day}
                </label>
              ))}
            </fieldset>
            <label>
              Scheduled daily hours{' '}
              <input
                name="hours"
                className={hrInputClass}
                type="number"
                min="0.01"
                max="24"
                step="0.01"
                defaultValue={editing?.daily_hours}
                required
              />
            </label>
          </>
        ) : (
          <>
            <label>
              Calendar{' '}
              <select name="calendar" required defaultValue="" className={hrInputClass}>
                <option value="" disabled>
                  Select calendar
                </option>
                {schedule.data?.calendars
                  .filter((calendar) =>
                    formType === 'holiday'
                      ? calendar.status === 'draft'
                      : calendar.status === 'published'
                  )
                  .map((calendar) => (
                    <option key={calendar.id} value={calendar.id}>
                      {calendar.name}
                    </option>
                  ))}
              </select>
            </label>
            <label>
              {formType === 'holiday' ? 'Holiday date' : 'Effective from'}{' '}
              <input name="date" className={hrInputClass} type="date" required />
            </label>
          </>
        )}
        {formType === 'holiday' && (
          <label>
            <input name="paid" type="checkbox" /> Paid holiday
          </label>
        )}
        {formType === 'shift' && (
          <>
            <label>
              Employee{' '}
              <select name="employee" required defaultValue="" className={hrInputClass}>
                <option value="" disabled>
                  Select employee
                </option>
                {employees.map((employee) => (
                  <option key={employee.id} value={employee.id}>
                    {employee.full_name}
                  </option>
                ))}
              </select>
            </label>
            <label>
              Effective to <input name="end_date" className={hrInputClass} type="date" />
            </label>
          </>
        )}
        {formType !== 'holiday' && (
          <>
            <label>
              Start time{' '}
              <input
                name="start_time"
                className={hrInputClass}
                type="time"
                defaultValue={editing?.standard_start_time}
                required
              />
            </label>
            <label>
              End time{' '}
              <input
                name="end_time"
                className={hrInputClass}
                type="time"
                defaultValue={editing?.standard_end_time}
                required
              />
            </label>
          </>
        )}
        <div>
          <button className={hrButtonClass} disabled={pending} type="submit">
            {editing ? 'Save draft changes' : 'Save schedule'}
          </button>
          {editing && (
            <button type="button" className={hrButtonClass} onClick={() => setEditing(null)}>
              Cancel edit
            </button>
          )}
        </div>
      </form>
      <ul className="space-y-1 text-sm">
        {schedule.data?.calendars.map((calendar) => (
          <li key={calendar.id} className="space-y-1 border-b border-theme-border py-2">
            <div>
              {calendar.name} · {calendar.work_days_json.join(', ')} · {calendar.daily_hours} h
            </div>
            <div>
              {calendar.status}
              {calendar.timezone &&
                ` · ${calendar.effective_from} through ${calendar.effective_to} · ${calendar.timezone}`}
            </div>
            {calendar.status === 'draft' && (
              <div className="flex flex-wrap gap-2">
                <button
                  type="button"
                  disabled={pending}
                  onClick={() => {
                    setFormType('calendar');
                    setEditing(calendar);
                  }}
                >
                  Edit calendar
                </button>
                <button
                  type="button"
                  disabled={pending || !calendar.timezone}
                  onClick={() => void decide(calendar, 'submit')}
                >
                  Submit calendar
                </button>
              </div>
            )}
            {canReview &&
              calendar.status === 'submitted' &&
              calendar.created_by_id !== user?.id &&
              calendar.submitted_by_id !== user?.id && (
                <button
                  type="button"
                  disabled={pending}
                  onClick={() => void decide(calendar, 'approve')}
                >
                  Approve calendar
                </button>
              )}
            {canReview && calendar.status === 'approved' && (
              <button
                type="button"
                disabled={pending}
                onClick={() => void decide(calendar, 'publish')}
              >
                Publish calendar
              </button>
            )}
            {canReview && (calendar.status === 'submitted' || calendar.status === 'approved') && (
              <form
                className="flex flex-wrap items-center gap-2"
                onSubmit={(event) => {
                  event.preventDefault();
                  const reason = String(new FormData(event.currentTarget).get('reason') ?? '');
                  void decide(calendar, 'return_to_draft', reason);
                }}
              >
                <input
                  name="reason"
                  aria-label="Return reason"
                  required
                  minLength={2}
                  maxLength={500}
                  className={hrInputClass}
                />
                <button type="submit" disabled={pending}>
                  Return to draft
                </button>
              </form>
            )}
          </li>
        ))}
        {schedule.data?.holidays.map((holiday) => (
          <li key={holiday.id}>
            {holiday.holiday_date} · {holiday.name}
          </li>
        ))}
        {schedule.data?.shifts.map((shift) => (
          <li key={shift.id}>
            {shift.shift_name} · {shift.effective_from} to {shift.effective_to ?? 'open'}
          </li>
        ))}
      </ul>
      <form
        className="flex flex-wrap items-end gap-3"
        onSubmit={(event) => {
          event.preventDefault();
          const data = new FormData(event.currentTarget);
          setLookup({ employeeId: String(data.get('employee')), date: String(data.get('date')) });
        }}
      >
        <label>
          Schedule for employee
          <select name="employee" required defaultValue="" className={hrInputClass}>
            <option value="" disabled>
              Select employee
            </option>
            {employees.map((employee) => (
              <option key={employee.id} value={employee.id}>
                {employee.full_name}
              </option>
            ))}
          </select>
        </label>
        <label>
          Work date <input name="date" required type="date" className={hrInputClass} />
        </label>
        <button type="submit" className={hrButtonClass}>
          Find work schedule
        </button>
      </form>
      {workday.isLoading && <p role="status">Looking up the work schedule…</p>}
      {workday.isError && (
        <p role="alert">{formatApiError(workday.error, 'Could not load the work schedule.')}</p>
      )}
      {workday.data && (
        <p role="status">
          {workday.data.calendar
            ? `${workday.data.work_date} · ${workday.data.calendar.name} · ${workday.data.calendar.timezone} · ${workday.data.holiday?.name ?? (workday.data.is_workday ? 'Workday' : 'Non-working day')}${workday.data.shift ? ` · ${workday.data.shift.shift_name}` : ''}`
            : `No published schedule covers ${workday.data.work_date}.`}
        </p>
      )}
    </details>
  );
}
