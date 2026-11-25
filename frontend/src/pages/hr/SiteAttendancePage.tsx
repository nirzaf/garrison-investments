import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import { useState } from 'react';
import { Link, useSearchParams } from 'react-router-dom';

import { formatApiError } from '../../api/errors';
import { listHrAssignmentProjects } from '../../api/hr';
import { listReportProjectOptions } from '../../api/projects';
import {
  getSiteAttendanceCompleteness,
  listSiteAttendance,
  listSiteAttendanceHistory,
  listSiteAttendanceProjectOptions,
  listSiteAttendanceWorkers,
  reviewSiteAttendance,
  writeSiteAttendance,
  type SiteAttendanceDraft,
  type SiteAttendanceRecord,
  type SiteAttendanceWorker
} from '../../api/siteAttendance';
import { businessDate } from '../../businessDate';
import { useAuth } from '../../context/useAuth';
import { useDebouncedSearch } from '../../useDebouncedSearch';

const pageSize = 30;
const isSupervisor = (role?: string) => role === 'site_supervisor' || role === 'senior_site_supervisor';

export function SiteAttendancePage() {
  const { user } = useAuth();
  const [params] = useSearchParams();
  const focusedEntry = params.get('attendanceId') ?? undefined;
  const [workDate, setWorkDate] = useState(businessDate);
  const [project, setProject] = useState<{ id: string; name: string }>();
  const [projectSearch, setProjectSearch] = useState('');
  const [offset, setOffset] = useState(0);
  const [correction, setCorrection] = useState<SiteAttendanceRecord>();
  const [historical, setHistorical] = useState(false);
  const queryClient = useQueryClient();
  const term = useDebouncedSearch(projectSearch);
  const projectChoices = useQuery({
    queryKey: ['site-attendance-projects', user?.id, term, historical],
    queryFn: async () => {
      if (historical) {
        return listSiteAttendanceProjectOptions({
          historical: true, search: term || undefined, limit: pageSize, offset: 0
        });
      }
      return user?.role === 'hr_manager'
        ? listHrAssignmentProjects(term, pageSize)
        : listReportProjectOptions({ search: term || undefined, limit: pageSize });
    },
    enabled: Boolean(user && !focusedEntry)
  });
  const entries = useQuery({
    queryKey: ['site-attendance', project?.id, workDate, focusedEntry, offset],
    queryFn: () => listSiteAttendance({
      project_id: project?.id,
      work_date: focusedEntry ? undefined : workDate,
      entry_id: focusedEntry,
      limit: pageSize,
      offset
    }),
    enabled: Boolean(workDate || focusedEntry)
  });
  const [missingOffset, setMissingOffset] = useState(0);
  const completeness = useQuery({
    queryKey: ['site-attendance-completeness', project?.id, workDate, missingOffset],
    queryFn: () => getSiteAttendanceCompleteness({
      project_id: project!.id, work_date: workDate, limit: pageSize, offset: missingOffset
    }),
    enabled: Boolean(project && workDate && !focusedEntry)
  });
  const maySubmit = isSupervisor(user?.role) && Boolean(project && workDate && !focusedEntry);

  function refresh() {
    void queryClient.invalidateQueries({ queryKey: ['site-attendance'] });
    void queryClient.invalidateQueries({ queryKey: ['site-attendance-completeness'] });
    void queryClient.invalidateQueries({ queryKey: ['site-attendance-history'] });
  }

  return (
    <section className="space-y-4">
      <h2 className="text-2xl font-semibold">Site attendance</h2>
      {focusedEntry ? (
        <Link to="/hr/site-attendance" className="text-brand-600 underline">All site attendance</Link>
      ) : (
        <div className="grid gap-3 sm:grid-cols-3">
          <label>Attendance date
            <input className="form-field" type="date" value={workDate}
              onChange={(event) => { setWorkDate(event.target.value); setMissingOffset(0); setOffset(0); setCorrection(undefined); setHistorical(false); }} />
          </label>
          <>
            <label>Search projects
              <input className="form-field" value={projectSearch}
                onChange={(event) => setProjectSearch(event.target.value)} />
            </label>
            <label>Attendance project
              <select className="form-field" value={project?.id ?? ''}
                onChange={(event) => {
                  setProject(projectChoices.data?.items.find((row) => row.id === event.target.value));
                  setMissingOffset(0);
                  setOffset(0);
                  setCorrection(undefined);
                  setHistorical(false);
                }}>
                <option value="">All accessible projects</option>
                {project && !projectChoices.data?.items.some((row) => row.id === project.id) && (
                  <option value={project.id}>{project.name}</option>
                )}
                {projectChoices.data?.items.map((row) => <option value={row.id} key={row.id}>{row.name}</option>)}
              </select>
              {projectChoices.isError && <span role="alert">Unable to load projects.</span>}
            </label>
          </>
        </div>
      )}
      {!focusedEntry && isSupervisor(user?.role) && project && <label className="flex items-center gap-2">
        <input type="checkbox" checked={historical} disabled={workDate >= businessDate()}
          onChange={(event) => setHistorical(event.target.checked)} />
        Record historical attendance using dated employment and project-assignment evidence
      </label>}
      {project && !focusedEntry && completeness.isError && <p role="alert">Unable to load attendance completeness.</p>}
      {completeness.data && (
        <section aria-label="Attendance completeness" className="space-y-2">
          <p>Expected: {completeness.data.expected_workers} · Recorded: {completeness.data.recorded_workers}
            {' · '}Missing: {completeness.data.missing_workers} · Confirmed: {completeness.data.confirmed_workers}</p>
          {completeness.data.unresolved_workers > 0 && (
            <p>{completeness.data.unresolved_workers} worker obligation(s) need HR reconciliation.</p>
          )}
          {completeness.data.empty_roster && <p>No eligible workers are rostered for this project and date.</p>}
          {completeness.data.is_complete && <p>Attendance is complete.</p>}
          <ul>{completeness.data.items.map((worker) => (
            <li key={worker.id}>{worker.full_name} · {worker.employee_code}</li>
          ))}</ul>
          {missingOffset > 0 && <button type="button" onClick={() => setMissingOffset(missingOffset - pageSize)}>Previous missing workers</button>}
          {missingOffset + pageSize < completeness.data.missing_workers &&
            <button type="button" onClick={() => setMissingOffset(missingOffset + pageSize)}>Next missing workers</button>}
        </section>
      )}
      {correction ? (
        <AttendanceForm
          key={correction.id}
          projectId={correction.submission.requirements.project_id}
          workDate={correction.submission.requirements.work_date}
          correction={correction}
          historical={Boolean(correction.submission.requirements.historical_reason)}
          onCancel={() => setCorrection(undefined)}
          onSuccess={() => { setCorrection(undefined); refresh(); }}
        />
      ) : maySubmit && project && (
        <AttendanceForm key={`${project.id}:${workDate}`} projectId={project.id}
          workDate={workDate} historical={historical} onSuccess={refresh} />
      )}
      {entries.isPending && <p role="status">Loading attendance…</p>}
      {entries.isError && <p role="alert">{formatApiError(entries.error, 'Unable to load attendance.')}</p>}
      {entries.isSuccess && !focusedEntry && (
        <p>Present submitted: {entries.data.submitted_present} · Present confirmed by HR: {entries.data.confirmed_present}</p>
      )}
      {entries.isSuccess && entries.data.total === 0 && <p>No visible site attendance.</p>}
      {entries.data?.items.map((record) => (
        <SiteAttendanceDetails key={record.id} record={record} userId={user?.id} role={user?.role}
          onCorrection={() => setCorrection(record)} refresh={refresh} />
      ))}
      {!focusedEntry && (entries.data?.total ?? 0) > pageSize && (
        <div className="flex gap-3">
          <button className="form-button" type="button" disabled={!offset}
            onClick={() => setOffset(offset - pageSize)}>Previous workers</button>
          <button className="form-button" type="button" disabled={offset + pageSize >= (entries.data?.total ?? 0)}
            onClick={() => setOffset(offset + pageSize)}>Next workers</button>
        </div>
      )}
    </section>
  );
}

function AttendanceForm({ projectId, workDate, correction, historical, onCancel, onSuccess }: {
  projectId: string;
  workDate: string;
  correction?: SiteAttendanceRecord;
  historical?: boolean;
  onCancel?: () => void;
  onSuccess: () => void;
}) {
  const [workerSearch, setWorkerSearch] = useState('');
  const [worker, setWorker] = useState<SiteAttendanceWorker>(correction?.worker ?? { id: '', employee_code: '', full_name: '' });
  const saved = correction?.submission.requirements;
  const historicalMode = historical ?? Boolean(saved?.historical_reason);
  const [status, setStatus] = useState<SiteAttendanceDraft['attendance_status']>(saved?.attendance_status ?? 'present');
  const [arrival, setArrival] = useState(toClockInput(saved?.check_in_at));
  const [departure, setDeparture] = useState(toClockInput(saved?.check_out_at));
  const [worked, setWorked] = useState(String(saved?.worked_hours ?? '0'));
  const [overtime, setOvertime] = useState(String(saved?.overtime_hours ?? '0'));
  const [notes, setNotes] = useState(saved?.notes ?? '');
  const [historicalReason, setHistoricalReason] = useState(saved?.historical_reason ?? '');
  const [correctionReason, setCorrectionReason] = useState('');
  const term = useDebouncedSearch(workerSearch);
  const workers = useQuery({
    queryKey: ['site-attendance-workers', projectId, workDate, historicalMode, term],
    queryFn: () => listSiteAttendanceWorkers({ project_id: projectId, work_date: workDate, historical: historicalMode, search: term, limit: pageSize, offset: 0 }),
    enabled: !correction
  });
  const submit = useMutation({
    mutationFn: () => writeSiteAttendance({
      employee_id: worker.id, project_id: projectId, work_date: workDate, attendance_status: status,
      check_in_at: status === 'present' && arrival ? new Date(arrival).toISOString() : null,
      check_out_at: status === 'present' && departure ? new Date(departure).toISOString() : null,
      worked_hours: status === 'present' ? worked : '0',
      overtime_hours: status === 'present' ? overtime : '0',
      notes: notes || null,
      historical_reason: historicalMode ? historicalReason.trim() : null,
      historical_remediation: historicalMode
    }, correction, correctionReason.trim()),
    onSuccess: () => {
      setWorker({ id: '', employee_code: '', full_name: '' });
      setNotes('');
      setArrival('');
      setDeparture('');
      setStatus('present');
      setWorked('0');
      setOvertime('0');
      setHistoricalReason('');
      onSuccess();
    }
  });
  return (
    <form className="rounded-lg border border-theme-border bg-theme-card p-4"
      onSubmit={(event) => { event.preventDefault(); if (!submit.isPending && worker.id) submit.mutate(); }}>
      <fieldset className="grid gap-3 sm:grid-cols-2" disabled={submit.isPending}>
        <legend className="mb-2 font-medium">{correction ? 'Correct site attendance' : 'Record site worker attendance'}</legend>
        {correction ? <p>{worker.full_name} · {workDate}</p> : <>
          <label>Search assigned workers
            <input className="form-field" value={workerSearch} onChange={(event) => setWorkerSearch(event.target.value)} />
          </label>
          <label>Site worker
            <select className="form-field" required value={worker.id}
              onChange={(event) => {
                const match = workers.data?.items.find((row) => row.id === event.target.value);
                setWorker(match ?? { id: '', employee_code: '', full_name: '' });
              }}>
              <option value="">Choose a {historicalMode ? 'historically assigned' : 'rostered'} worker</option>
              {worker.id && !workers.data?.items.some((row) => row.id === worker.id) && (
                <option value={worker.id}>{worker.full_name}</option>
              )}
              {workers.data?.items.map((row) => (
                <option value={row.id} key={row.id}>{row.full_name} · {row.employee_code}</option>
              ))}
            </select>
            {workers.isPending && <span role="status">Loading workers…</span>}
            {workers.isError && <span role="alert">{formatApiError(workers.error, 'Unable to load workers.')}</span>}
            {workers.data?.total === 0 && <span>No assigned workers match.</span>}
          </label>
        </>}
        <label>Attendance status
          <select className="form-field" value={status}
            onChange={(event) => setStatus(event.target.value as typeof status)}>
            <option value="present">Present</option><option value="absent">Absent</option>
            <option value="on_leave">Leave</option><option value="off_day">Off day</option>
          </select>
        </label>
        {status === 'present' && <>
          <label>Arrival time (device time)
            <input className="form-field" type="datetime-local" value={arrival}
              onChange={(event) => setArrival(event.target.value)} />
          </label>
          <label>Departure time (device time)
            <input className="form-field" type="datetime-local" value={departure}
              onChange={(event) => setDeparture(event.target.value)} />
          </label>
          <label>Worked hours
            <input className="form-field" type="number" min="0" max="24" step="0.01" required value={worked}
              onChange={(event) => setWorked(event.target.value)} />
          </label>
          <label>Overtime hours
            <input className="form-field" type="number" min="0" max={worked || '24'} step="0.01" required value={overtime}
              onChange={(event) => setOvertime(event.target.value)} />
          </label>
        </>}
        <label>Attendance exception notes
          <textarea className="form-field" maxLength={2000} value={notes}
            onChange={(event) => setNotes(event.target.value)} />
        </label>
        {historicalMode && <label>Historical attendance reason
          <textarea className="form-field" required minLength={2} maxLength={500}
            value={historicalReason} onChange={(event) => setHistoricalReason(event.target.value)} />
        </label>}
        {correction && <label>Correction reason
          <textarea className="form-field" required minLength={2} maxLength={500}
            value={correctionReason} onChange={(event) => setCorrectionReason(event.target.value)} />
        </label>}
        <div className="flex gap-3">
          <button className="form-button" type="submit"
            disabled={!worker.id || (Boolean(correction) && correctionReason.trim().length < 2) || (historicalMode && historicalReason.trim().length < 2)}>
            {submit.isPending ? 'Submitting…' : correction ? 'Resubmit attendance' : 'Submit site attendance'}
          </button>
          {onCancel && <button type="button" onClick={onCancel}>Cancel</button>}
        </div>
      </fieldset>
      {submit.isError && <p role="alert">{formatApiError(submit.error, 'Unable to submit attendance.')}</p>}
    </form>
  );
}

function SiteAttendanceDetails({ record, userId, role, onCorrection, refresh }: {
  record: SiteAttendanceRecord;
  userId?: string;
  role?: string;
  onCorrection: () => void;
  refresh: () => void;
}) {
  const [open, setOpen] = useState(false);
  const [comments, setComments] = useState('');
  const submission = record.submission;
  const details = submission.requirements;
  const isEngineer = record.stage === 'pending_engineer' && role === 'mep_project_manager' && submission.engineer_id === userId;
  const isHR = record.stage === 'pending_hr' && role === 'hr_manager' && submission.engineer_id !== userId;
  const eligibleCorrection = isSupervisor(role) && submission.submitted_by === userId &&
    ['approved', 'returned', 'rejected'].includes(record.stage);
  const history = useQuery({
    queryKey: ['site-attendance-history', record.id, record.record_revision],
    queryFn: () => listSiteAttendanceHistory(record.id),
    enabled: open
  });
  const review = useMutation({
    mutationFn: (decision: 'approved' | 'returned' | 'rejected') =>
      reviewSiteAttendance(record, isHR ? 'hr' : 'engineer', decision, comments),
    onSuccess: refresh
  });
  return (
    <details className="rounded-md border border-theme-border p-3" onToggle={(event) => setOpen(event.currentTarget.open)}>
      <summary className="cursor-pointer">
        {record.worker.full_name} · {record.worker.employee_code} · {details.work_date} · {record.stage.replace(/_/g, ' ')}
      </summary>
      <div className="mt-3 space-y-2">
        <p>{details.attendance_status.replace(/_/g, ' ')} · {details.worked_hours} worked hours · {details.overtime_hours} overtime</p>
        {details.arrival_assessment ? (
          <ArrivalAssessmentView
            assessment={details.arrival_assessment}
            actualArrival={details.check_in_at}
          />
        ) : (
          <p>
            {details.check_in_at
              ? `Recorded arrival ${new Date(details.check_in_at).toISOString().replace('T', ' ').replace('Z', ' UTC')}`
              : 'Arrival assessment unavailable for this submission.'}
          </p>
        )}
        {details.correction_reason && <p>Correction reason: {details.correction_reason}</p>}
        {details.notes && <p>{details.notes}</p>}
        {history.data?.map((entry) => (
          <p key={entry.submission_revision}>Submission {entry.submission_revision} · Site Engineer: {entry.engineer_decision ?? 'Pending'} · HR: {entry.hr_decision ?? 'Pending'}
            {entry.engineer_comments && ` · ${entry.engineer_comments}`}
            {entry.hr_comments && ` · ${entry.hr_comments}`}
          </p>
        ))}
        {history.isError && <p role="alert">Unable to load earlier attendance submissions.</p>}
        {eligibleCorrection && <button type="button" className="form-button" onClick={onCorrection}>Correct attendance</button>}
        {(isEngineer || isHR) && <>
          <label className="block">Attendance review comments
            <textarea className="form-field" maxLength={2000} value={comments}
              onChange={(event) => setComments(event.target.value)} />
          </label>
          <div className="flex flex-wrap gap-3">
            {([
              ['approved', isHR ? 'Verify attendance for HR' : 'Approve as Site Engineer'],
              ['returned', 'Return attendance for correction'], ['rejected', 'Reject site attendance']
            ] as const).map(([decision, label]) => (
              <button key={decision} type="button" className="form-button"
                disabled={review.isPending || (decision !== 'approved' && !comments.trim())}
                onClick={() => review.mutate(decision)}>{label}</button>
            ))}
          </div>
          {review.isError && <p role="alert">{formatApiError(review.error, 'Unable to review attendance.')}</p>}
        </>}
      </div>
    </details>
  );
}

function ArrivalAssessmentView({ assessment, actualArrival }: {
  assessment: NonNullable<SiteAttendanceRecord['submission']['requirements']['arrival_assessment']>;
  actualArrival?: string | null;
}) {
  const actual = actualArrival
    ? assessment.timezone
      ? new Intl.DateTimeFormat(undefined, {
        dateStyle: 'medium', timeStyle: 'short', timeZone: assessment.timezone, timeZoneName: 'short'
      }).format(new Date(actualArrival))
      : new Date(actualArrival).toISOString().replace('T', ' ').replace('Z', ' UTC')
    : null;
  if (assessment.status === 'unresolved') {
    return <p>{actual ? `Recorded arrival ${actual} · ` : ''}Arrival timing unresolved from the saved schedule.</p>;
  }
  if (assessment.status === 'not_applicable') {
    return <p>{actual ? `Recorded arrival ${actual} · ` : ''}Arrival timing is not applicable.</p>;
  }
  const scheduled = assessment.scheduled_start_at && assessment.timezone
    ? new Intl.DateTimeFormat(undefined, {
      dateStyle: 'medium', timeStyle: 'short', timeZone: assessment.timezone, timeZoneName: 'short'
    }).format(new Date(assessment.scheduled_start_at))
    : null;
  if (!scheduled) {
    return <p>{actual ? `Recorded arrival ${actual} · ` : ''}Arrival timing unresolved from the saved schedule.</p>;
  }
  return (
    <p>
      Planned start {scheduled} · Actual arrival {actual ?? 'not recorded'} · {assessment.status === 'on_time'
        ? 'arrived on or before start'
        : `arrived ${assessment.minutes_after_start ?? 0} minute${assessment.minutes_after_start === 1 ? '' : 's'} after start`}
    </p>
  );
}

function toClockInput(value?: string | null) {
  if (!value) return '';
  const instant = new Date(value);
  return new Date(instant.getTime() - instant.getTimezoneOffset() * 60000).toISOString().slice(0, 16);
}
