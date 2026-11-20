import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import { useState } from 'react';

import { formatApiError } from '../../api/errors';
import {
  cancelRosterAllocation,
  createRosterAllocation,
  listEmployees,
  listHrAssignmentProjects,
  listRoster
} from '../../api/hr';
import { hrButtonClass, hrInputClass } from './HRAccessForms';

const pageSize = 25;
const rosterKey = ['hr', 'roster'];

function localTime(value: string, timeZone: string) {
  return new Intl.DateTimeFormat(undefined, {
    dateStyle: 'medium',
    timeStyle: 'short',
    timeZone
  }).format(new Date(value));
}

export function HRRoster() {
  const client = useQueryClient();
  const [employeeSearch, setEmployeeSearch] = useState('');
  const [projectSearch, setProjectSearch] = useState('');
  const [employeeId, setEmployeeId] = useState('');
  const [employeeLabel, setEmployeeLabel] = useState('');
  const [projectId, setProjectId] = useState('');
  const [projectLabel, setProjectLabel] = useState('');
  const [employeeOptionOffset, setEmployeeOptionOffset] = useState(0);
  const [projectOptionOffset, setProjectOptionOffset] = useState(0);
  const [workDate, setWorkDate] = useState('');
  const [commandId, setCommandId] = useState(() => crypto.randomUUID());
  const [startDate, setStartDate] = useState('');
  const [endDate, setEndDate] = useState('');
  const [range, setRange] = useState({ from: '', to: '' });
  const [offset, setOffset] = useState(0);
  const [cancellingId, setCancellingId] = useState('');
  const [reason, setReason] = useState('');

  const employees = useQuery({
    queryKey: ['hr', 'roster-employee-options', employeeSearch.trim(), employeeOptionOffset],
    queryFn: () =>
      listEmployees({
        search: employeeSearch.trim() || undefined,
        limit: pageSize,
        offset: employeeOptionOffset
      })
  });
  const projects = useQuery({
    queryKey: ['hr', 'assignment-projects', projectSearch.trim(), projectOptionOffset],
    queryFn: () => listHrAssignmentProjects(projectSearch.trim(), pageSize, projectOptionOffset)
  });
  const roster = useQuery({
    queryKey: [...rosterKey, range, offset],
    queryFn: () =>
      listRoster({ date_from: range.from, date_to: range.to, limit: pageSize, offset }),
    enabled: Boolean(range.from && range.to)
  });
  const add = useMutation({
    mutationFn: createRosterAllocation,
    onSuccess: async (row) => {
      setStartDate(row.work_date);
      setEndDate(row.work_date);
      setRange({ from: row.work_date, to: row.work_date });
      setOffset(0);
      setCommandId(crypto.randomUUID());
      await client.invalidateQueries({ queryKey: rosterKey });
    }
  });
  const cancel = useMutation({
    mutationFn: ({ id, why }: { id: string; why: string }) => cancelRosterAllocation(id, why),
    onSuccess: async () => {
      setCancellingId('');
      setReason('');
      await client.invalidateQueries({ queryKey: rosterKey });
    }
  });
  const pending = add.isPending || cancel.isPending;

  return (
    <section className="space-y-3 rounded border border-theme-border p-3">
      <h4 className="font-semibold">Workforce roster</h4>
      <p className="text-sm">
        Plan a project allocation using the employee’s published work schedule.
      </p>
      <form
        className="space-y-2"
        onSubmit={(event) => {
          event.preventDefault();
          if (!pending && employeeId && projectId && workDate)
            add.mutate({
              id: commandId,
              employee_id: employeeId,
              project_id: projectId,
              work_date: workDate
            });
        }}
      >
        <fieldset disabled={pending} className="grid gap-2 sm:grid-cols-2">
          <label>
            Find roster employee
            <input
              type="search"
              className={hrInputClass}
              value={employeeSearch}
              maxLength={100}
              onChange={(event) => {
                setEmployeeSearch(event.target.value);
                setEmployeeOptionOffset(0);
                setCommandId(crypto.randomUUID());
              }}
            />
          </label>
          <label>
            Roster employee
            <select
              className={hrInputClass}
              required
              disabled={employees.isFetching}
              aria-label="Roster employee"
              value={employeeId}
              onChange={(event) => {
                const option = employees.data?.items.find((row) => row.id === event.target.value);
                setEmployeeId(option?.id ?? '');
                setEmployeeLabel(option ? `${option.full_name} (${option.employee_code})` : '');
                setCommandId(crypto.randomUUID());
              }}
            >
              <option value="">
                {employees.isFetching ? 'Loading employees…' : 'Choose employee'}
              </option>
              {employeeId && !employees.data?.items.some((row) => row.id === employeeId) && (
                <option value={employeeId}>{employeeLabel}</option>
              )}
              {employees.data?.items.map((row) => (
                <option key={row.id} value={row.id}>
                  {row.full_name} ({row.employee_code})
                </option>
              ))}
            </select>
            {employees.isError && (
              <span role="alert" className="mt-1 block text-sm">
                {formatApiError(employees.error, 'Employee search failed.')} {' '}
                <button
                  className="underline"
                  type="button"
                  onClick={() => void employees.refetch()}
                >
                  Retry employee search
                </button>
              </span>
            )}
            {employees.isSuccess && !employees.data.items.length && (
              <span className="mt-1 block text-sm">No matching employees.</span>
            )}
            {(employees.data?.total ?? 0) > pageSize && (
              <nav className="mt-1 flex gap-2 text-sm" aria-label="Roster employee options pages">
                <button
                  type="button"
                  className="underline"
                  disabled={employeeOptionOffset === 0 || employees.isFetching}
                  onClick={() => setEmployeeOptionOffset((value) => Math.max(0, value - pageSize))}
                >
                  Previous employees
                </button>
                <button
                  type="button"
                  className="underline"
                  disabled={
                    employeeOptionOffset + pageSize >= (employees.data?.total ?? 0) ||
                    employees.isFetching
                  }
                  onClick={() => setEmployeeOptionOffset((value) => value + pageSize)}
                >
                  More employees
                </button>
              </nav>
            )}
          </label>
          <label>
            Find roster project
            <input
              type="search"
              className={hrInputClass}
              value={projectSearch}
              maxLength={100}
              onChange={(event) => {
                setProjectSearch(event.target.value);
                setProjectOptionOffset(0);
                setCommandId(crypto.randomUUID());
              }}
            />
          </label>
          <label>
            Roster project
            <select
              className={hrInputClass}
              required
              disabled={projects.isFetching}
              aria-label="Roster project"
              value={projectId}
              onChange={(event) => {
                const option = projects.data?.items.find((row) => row.id === event.target.value);
                setProjectId(option?.id ?? '');
                setProjectLabel(option ? `${option.name} (${option.code})` : '');
                setCommandId(crypto.randomUUID());
              }}
            >
              <option value="">
                {projects.isFetching ? 'Loading projects…' : 'Choose project'}
              </option>
              {projectId && !projects.data?.items.some((row) => row.id === projectId) && (
                <option value={projectId}>{projectLabel}</option>
              )}
              {projects.data?.items.map((row) => (
                <option key={row.id} value={row.id}>
                  {row.name} ({row.code})
                </option>
              ))}
            </select>
            {projects.isError && (
              <span role="alert" className="mt-1 block text-sm">
                {formatApiError(projects.error, 'Project search failed.')} {' '}
                <button
                  className="underline"
                  type="button"
                  onClick={() => void projects.refetch()}
                >
                  Retry project search
                </button>
              </span>
            )}
            {projects.isSuccess && !projects.data.items.length && (
              <span className="mt-1 block text-sm">No matching projects.</span>
            )}
            {(projects.data?.total ?? 0) > pageSize && (
              <nav className="mt-1 flex gap-2 text-sm" aria-label="Roster project options pages">
                <button
                  type="button"
                  className="underline"
                  disabled={projectOptionOffset === 0 || projects.isFetching}
                  onClick={() => setProjectOptionOffset((value) => Math.max(0, value - pageSize))}
                >
                  Previous projects
                </button>
                <button
                  type="button"
                  className="underline"
                  disabled={
                    projectOptionOffset + pageSize >= (projects.data?.total ?? 0) ||
                    projects.isFetching
                  }
                  onClick={() => setProjectOptionOffset((value) => value + pageSize)}
                >
                  More projects
                </button>
              </nav>
            )}
          </label>
          <label>
            Allocation date
            <input
              type="date"
              className={hrInputClass}
              required
              value={workDate}
              onChange={(event) => {
                setWorkDate(event.target.value);
                setCommandId(crypto.randomUUID());
              }}
            />
          </label>
          <div className="self-end">
            <button type="submit" className={hrButtonClass} disabled={!employeeId || !projectId}>
              {add.isPending ? 'Allocating…' : 'Allocate shift'}
            </button>
          </div>
        </fieldset>
        {(employees.isFetching || projects.isFetching) && (
          <p role="status">Loading roster options…</p>
        )}
        {add.isError && (
          <p role="alert">{formatApiError(add.error, 'Could not allocate the shift.')}</p>
        )}
      </form>
      <form
        className="flex flex-wrap items-end gap-2"
        onSubmit={(event) => {
          event.preventDefault();
          setOffset(0);
          setRange({ from: startDate, to: endDate });
        }}
      >
        <label>
          Roster from
          <input
            type="date"
            className={hrInputClass}
            required
            value={startDate}
            onChange={(event) => setStartDate(event.target.value)}
          />
        </label>
        <label>
          Roster to
          <input
            type="date"
            className={hrInputClass}
            required
            min={startDate || undefined}
            value={endDate}
            onChange={(event) => setEndDate(event.target.value)}
          />
        </label>
        <button type="submit" className={hrButtonClass}>
          View roster
        </button>
      </form>
      {!range.from && <p className="text-sm">Select a date range to see allocations.</p>}
      {roster.isLoading && <p role="status">Loading roster…</p>}
      {roster.isError && (
        <p role="alert">{formatApiError(roster.error, 'Could not load the roster.')}</p>
      )}
      {roster.isSuccess && !roster.data.items.length && <p>No allocations in this range.</p>}
      <ul className="space-y-2">
        {roster.data?.items.map((row) => (
          <li key={row.id} className="rounded border border-theme-border p-2">
            <p className="font-medium">
              {row.employee_name} · {row.project_name}
            </p>
            <p className="text-sm">
              {localTime(row.starts_at, row.timezone)} – {localTime(row.ends_at, row.timezone)}
              {' · '}
              {row.timezone}
              {' · '}
              {row.planned_hours} planned hours
            </p>
            {row.cancelled_at ? (
              <p>Cancelled · {row.cancellation_reason}</p>
            ) : cancellingId === row.id ? (
              <form
                onSubmit={(event) => {
                  event.preventDefault();
                  if (!pending && reason.trim()) cancel.mutate({ id: row.id, why: reason.trim() });
                }}
              >
                <label>
                  Roster cancellation reason
                  <input
                    className={hrInputClass}
                    required
                    maxLength={500}
                    value={reason}
                    disabled={pending}
                    onChange={(event) => setReason(event.target.value)}
                  />
                </label>
                <button
                  type="submit"
                  className={hrButtonClass}
                  disabled={pending || !reason.trim()}
                >
                  Confirm roster cancellation
                </button>
                <button
                  type="button"
                  className={hrButtonClass}
                  disabled={pending}
                  onClick={() => {
                    setCancellingId('');
                    setReason('');
                    cancel.reset();
                  }}
                >
                  Keep allocation
                </button>
                {cancel.isError && (
                  <p role="alert">
                    {formatApiError(cancel.error, 'Could not cancel the allocation.')}
                  </p>
                )}
              </form>
            ) : (
              <button
                type="button"
                className={hrButtonClass}
                disabled={pending}
                onClick={() => {
                  setCancellingId(row.id);
                  setReason('');
                  cancel.reset();
                }}
              >
                Cancel allocation
              </button>
            )}
          </li>
        ))}
      </ul>
      {(offset > 0 || offset + pageSize < (roster.data?.total ?? 0)) && (
        <div className="flex gap-2">
          <button
            type="button"
            className={hrButtonClass}
            disabled={offset === 0 || roster.isFetching}
            onClick={() => setOffset(offset - pageSize)}
          >
            Previous roster page
          </button>
          <button
            type="button"
            className={hrButtonClass}
            disabled={roster.isFetching || offset + pageSize >= (roster.data?.total ?? 0)}
            onClick={() => setOffset(offset + pageSize)}
          >
            Next roster page
          </button>
        </div>
      )}
    </section>
  );
}
