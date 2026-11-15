import axios from 'axios';
import { FormEvent, useCallback, useEffect, useState } from 'react';

import {
  acknowledgeMyPolicy,
  cancelMyLeaveRequest,
  downloadMyHrDocument,
  getMyHrProfile,
  getMyLeaveBalances,
  listMyAttendance,
  listMyHrDocuments,
  listMyLeaveRequests,
  listMyLeaveTypes,
  listMyPolicies,
  listMyServiceRequests,
  requestMyAttendanceCorrection,
  submitMyLeaveRequest,
  submitMyServiceRequest,
  updateMyHrProfile,
  type AttendanceEntryRecord,
  type EmployeeSelfRecord,
  type HrDocumentRecord,
  type HrServiceRequestRecord,
  type LeaveBalanceItem,
  type LeaveRequestRecord,
  type LeaveTypeRecord,
  type PolicyDocumentRecord
} from '../../api/hr';
import { formatApiError } from '../../api/errors';
import { StatusBadge } from '../../components/shared/StatusBadge';
import { HRMeWorkflowPanel } from './HRMeWorkflowPanel';

export function HRMePage() {
  const [profile, setProfile] = useState<EmployeeSelfRecord | null>(null);
  const [notLinked, setNotLinked] = useState(false);
  const [balances, setBalances] = useState<LeaveBalanceItem[]>([]);
  const [leaveTypes, setLeaveTypes] = useState<LeaveTypeRecord[]>([]);
  const [leaveRequests, setLeaveRequests] = useState<LeaveRequestRecord[]>([]);
  const [attendance, setAttendance] = useState<AttendanceEntryRecord[]>([]);
  const [documents, setDocuments] = useState<HrDocumentRecord[]>([]);
  const [policies, setPolicies] = useState<PolicyDocumentRecord[]>([]);
  const [serviceRequests, setServiceRequests] = useState<HrServiceRequestRecord[]>([]);
  const [loading, setLoading] = useState(true);
  const [notice, setNotice] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);

  const [personalPhone, setPersonalPhone] = useState('');
  const [personalEmail, setPersonalEmail] = useState('');
  const [residentialAddress, setResidentialAddress] = useState('');
  const [emergencyName, setEmergencyName] = useState('');
  const [emergencyPhone, setEmergencyPhone] = useState('');

  const [leaveTypeId, setLeaveTypeId] = useState('');
  const [leaveStart, setLeaveStart] = useState('');
  const [leaveEnd, setLeaveEnd] = useState('');
  const [leaveDays, setLeaveDays] = useState('1');
  const [leaveReason, setLeaveReason] = useState('');
  const [halfDayPeriod, setHalfDayPeriod] = useState<'' | 'morning' | 'afternoon'>('');
  const [leaveAttachment, setLeaveAttachment] = useState('');
  const [leavePending, setLeavePending] = useState(false);

  const [reqType, setReqType] = useState<
    'employment_letter' | 'address_change' | 'general_inquiry'
  >('employment_letter');
  const [reqSubject, setReqSubject] = useState('');
  const [reqDesc, setReqDesc] = useState('');

  const loadAll = useCallback(async () => {
    setLoading(true);
    setError(null);
    setNotLinked(false);
    try {
      const me = await getMyHrProfile();
      setProfile(me);
      setPersonalPhone(me.personal_phone ?? '');
      setPersonalEmail(me.personal_email ?? '');
      setResidentialAddress(me.residential_address ?? '');
      setEmergencyName(me.emergency_contact_name ?? '');
      setEmergencyPhone(me.emergency_contact_phone ?? '');

      const [bal, types, reqs, att, docs, pols, sreqs] = await Promise.all([
        getMyLeaveBalances(),
        listMyLeaveTypes(),
        listMyLeaveRequests(),
        listMyAttendance(),
        listMyHrDocuments(),
        listMyPolicies(),
        listMyServiceRequests()
      ]);
      setBalances(bal.items);
      setLeaveTypes(types.items);
      setLeaveTypeId((selected) => selected || types.items[0]?.id || '');
      setLeaveRequests(reqs.items);
      setAttendance(att.items);
      setDocuments(docs.items);
      setPolicies(pols.items);
      setServiceRequests(sreqs.items);
    } catch (err) {
      if (axios.isAxiosError(err) && err.response?.status === 404) {
        setNotLinked(true);
      } else {
        setError(formatApiError(err, 'Unable to load HR self-service records.'));
      }
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    void loadAll();
  }, [loadAll]);

  async function handleSaveContact(e: FormEvent) {
    e.preventDefault();
    setError(null);
    setNotice(null);
    try {
      const updated = await updateMyHrProfile({
        personal_phone: personalPhone || null,
        personal_email: personalEmail || null,
        residential_address: residentialAddress || null,
        emergency_contact_name: emergencyName || null,
        emergency_contact_phone: emergencyPhone || null
      });
      setProfile(updated);
      setNotice('Personal HR contact details updated.');
    } catch (err) {
      setError(formatApiError(err, 'Unable to update personal details.'));
    }
  }

  async function handleSubmitLeave(e: FormEvent) {
    e.preventDefault();
    if (leavePending) return;
    setLeavePending(true);
    setError(null);
    setNotice(null);
    try {
      await submitMyLeaveRequest({
        leave_type_id: leaveTypeId,
        start_date: leaveStart,
        end_date: leaveEnd,
        days_requested: leaveDays,
        is_half_day: Boolean(halfDayPeriod),
        half_day_period: halfDayPeriod || null,
        attachment_document_id: leaveAttachment || null,
        reason: leaveReason || null,
        submit_immediately: true
      });
      setLeaveReason('');
      setLeaveAttachment('');
      setHalfDayPeriod('');
      setNotice('Leave request submitted.');
      await loadAll();
    } catch (err) {
      setError(formatApiError(err, 'Unable to submit leave request.'));
    } finally {
      setLeavePending(false);
    }
  }

  async function cancelLeave(id: string) {
    if (leavePending) return;
    setLeavePending(true);
    setError(null);
    try {
      const updated = await cancelMyLeaveRequest(id);
      setLeaveRequests((requests) =>
        requests.map((request) => (request.id === id ? updated : request))
      );
      setNotice('Leave request cancelled.');
    } catch (failure) {
      setError(formatApiError(failure, 'Unable to cancel leave.'));
    } finally {
      setLeavePending(false);
    }
  }

  async function handleDownloadDoc(documentId: string) {
    setError(null);
    try {
      const res = await downloadMyHrDocument(documentId);
      window.open(res.download_url, '_blank', 'noopener,noreferrer');
    } catch (err) {
      setError(formatApiError(err, 'Unable to prepare HR document download.'));
    }
  }

  async function handleAcknowledge(policyId: string) {
    setError(null);
    setNotice(null);
    try {
      await acknowledgeMyPolicy(policyId);
      setNotice('Policy acknowledgement recorded.');
    } catch (err) {
      setError(formatApiError(err, 'Unable to acknowledge policy.'));
    }
  }

  async function handleSubmitServiceReq(e: FormEvent) {
    e.preventDefault();
    setError(null);
    setNotice(null);
    try {
      await submitMyServiceRequest({
        request_type: reqType,
        subject: reqSubject,
        description: reqDesc || null
      });
      setReqSubject('');
      setReqDesc('');
      setNotice('HR service request submitted.');
      await loadAll();
    } catch (err) {
      setError(formatApiError(err, 'Unable to submit HR service request.'));
    }
  }

  if (loading) {
    return <p className="text-sm text-theme-text-muted">Loading HR self-service profile…</p>;
  }

  if (!profile && error && !notLinked) {
    return (
      <div role="alert" className="space-y-2">
        <p>{error}</p>
        <button type="button" onClick={() => void loadAll()}>
          Retry
        </button>
      </div>
    );
  }

  if (notLinked || !profile) {
    return (
      <div className="rounded-lg border border-theme-border bg-theme-card p-6">
        <h2 className="text-xl font-semibold text-theme-text-primary">My HR Self-Service</h2>
        <p className="mt-2 text-sm text-theme-text-secondary">
          Your portal user account is not linked to an active HR employee record yet. Please ask HR
          or an Administrator to complete your HR link request.
        </p>
      </div>
    );
  }

  return (
    <div className="space-y-6">
      <div>
        <p className="text-sm font-medium text-brand-600">Employee Self-Service</p>
        <h2 className="text-2xl font-semibold text-theme-text-primary">My HR Profile</h2>
        <p className="text-sm text-theme-text-muted">
          Employee Code: <strong>{profile.employee.employee_code}</strong> · Status:{' '}
          <StatusBadge tone="info">{profile.employee.employment_status}</StatusBadge>
        </p>
      </div>

      {notice ? (
        <div className="rounded-md border border-[var(--status-success-border)] bg-[var(--status-success-bg)] px-4 py-2 text-sm text-[var(--status-success-text)]">
          {notice}
        </div>
      ) : null}
      {error ? (
        <div className="rounded-md border border-[var(--status-error-border)] bg-[var(--status-error-bg)] px-4 py-2 text-sm text-[var(--status-error-text)]">
          {error}
        </div>
      ) : null}

      <section className="rounded-lg border border-theme-border bg-theme-card p-5 shadow-xs">
        <h3 className="text-base font-semibold text-theme-text-primary">
          Personal Contact & Emergency Details
        </h3>
        <form
          className="mt-4 grid gap-4 md:grid-cols-2"
          onSubmit={(e) => void handleSaveContact(e)}
        >
          <label className="text-sm">
            <span className="block font-medium text-theme-text-secondary">Personal Phone</span>
            <input
              className="mt-1 w-full rounded-md border border-theme-border bg-theme-input px-3 py-2 text-sm"
              onChange={(e) => setPersonalPhone(e.target.value)}
              value={personalPhone}
            />
          </label>
          <label className="text-sm">
            <span className="block font-medium text-theme-text-secondary">Personal Email</span>
            <input
              className="mt-1 w-full rounded-md border border-theme-border bg-theme-input px-3 py-2 text-sm"
              onChange={(e) => setPersonalEmail(e.target.value)}
              type="email"
              value={personalEmail}
            />
          </label>
          <label className="text-sm md:col-span-2">
            <span className="block font-medium text-theme-text-secondary">Residential Address</span>
            <input
              className="mt-1 w-full rounded-md border border-theme-border bg-theme-input px-3 py-2 text-sm"
              onChange={(e) => setResidentialAddress(e.target.value)}
              value={residentialAddress}
            />
          </label>
          <label className="text-sm">
            <span className="block font-medium text-theme-text-secondary">
              Emergency Contact Name
            </span>
            <input
              className="mt-1 w-full rounded-md border border-theme-border bg-theme-input px-3 py-2 text-sm"
              onChange={(e) => setEmergencyName(e.target.value)}
              value={emergencyName}
            />
          </label>
          <label className="text-sm">
            <span className="block font-medium text-theme-text-secondary">
              Emergency Contact Phone
            </span>
            <input
              className="mt-1 w-full rounded-md border border-theme-border bg-theme-input px-3 py-2 text-sm"
              onChange={(e) => setEmergencyPhone(e.target.value)}
              value={emergencyPhone}
            />
          </label>
          <div className="md:col-span-2 flex flex-wrap items-center justify-between gap-2 text-xs text-theme-text-muted">
            <span>
              Bank: {profile.bank_name || 'N/A'} ({profile.bank_account_masked || 'Masked'}) · EPF:{' '}
              {profile.epf_number_masked || 'N/A'}
            </span>
            <button
              className="rounded-md bg-brand-600 px-4 py-2 text-sm font-semibold text-white hover:bg-brand-700"
              type="submit"
            >
              Save contact details
            </button>
          </div>
        </form>
      </section>

      <HRMeWorkflowPanel />

      <section className="grid gap-6 lg:grid-cols-2">
        <div className="rounded-lg border border-theme-border bg-theme-card p-5 shadow-xs">
          <h3 className="text-base font-semibold text-theme-text-primary">My Leave Balances</h3>
          <div className="mt-3 space-y-2 text-sm">
            {balances.length === 0 ? (
              <p className="text-theme-text-muted">No leave balances posted yet.</p>
            ) : (
              balances.map((b) => (
                <div
                  className="flex items-center justify-between rounded-md border border-theme-border px-3 py-2"
                  key={`${b.leave_type_id}-${b.leave_year}`}
                >
                  <span>
                    {b.leave_type_name} ({b.leave_year})
                  </span>
                  <strong>{b.balance_days} days</strong>
                </div>
              ))
            )}
          </div>

          <form
            className="mt-5 space-y-3 border-t border-theme-border pt-4"
            onSubmit={(e) => void handleSubmitLeave(e)}
          >
            <h4 className="text-sm font-semibold text-theme-text-primary">Request Leave</h4>
            <select
              className="w-full rounded-md border border-theme-border bg-theme-input px-3 py-2 text-sm"
              onChange={(e) => setLeaveTypeId(e.target.value)}
              required
              aria-label="Leave type"
              value={leaveTypeId}
            >
              <option value="">Select leave type</option>
              {leaveTypes.map((lt) => (
                <option key={lt.id} value={lt.id}>
                  {lt.name} ({lt.code})
                </option>
              ))}
            </select>
            <div className="grid grid-cols-3 gap-2">
              <input
                className="rounded-md border border-theme-border bg-theme-input px-2 py-1.5 text-sm"
                onChange={(e) => setLeaveStart(e.target.value)}
                required
                type="date"
                aria-label="Leave starts"
                value={leaveStart}
              />
              <input
                className="rounded-md border border-theme-border bg-theme-input px-2 py-1.5 text-sm"
                onChange={(e) => setLeaveEnd(e.target.value)}
                required
                type="date"
                aria-label="Leave ends"
                value={leaveEnd}
              />
              <input
                className="rounded-md border border-theme-border bg-theme-input px-2 py-1.5 text-sm"
                min="0.5"
                onChange={(e) => setLeaveDays(e.target.value)}
                placeholder="Days"
                required
                step="0.5"
                type="number"
                aria-label="Leave days"
                value={leaveDays}
              />
            </div>
            <label className="block text-sm">
              Half-day period
              <select
                className="ml-2 rounded border border-theme-border bg-theme-input"
                value={halfDayPeriod}
                onChange={(event) => setHalfDayPeriod(event.target.value as typeof halfDayPeriod)}
              >
                <option value="">None</option>
                <option value="morning">Morning</option>
                <option value="afternoon">Afternoon</option>
              </select>
            </label>
            {leaveTypes.find((type) => type.id === leaveTypeId)?.requires_attachment && (
              <label className="block text-sm">
                Supporting document
                <select
                  className="ml-2 rounded border border-theme-border bg-theme-input"
                  value={leaveAttachment}
                  onChange={(event) => setLeaveAttachment(event.target.value)}
                  required
                >
                  <option value="">Choose a shared document</option>
                  {documents.map((document) => (
                    <option key={document.id} value={document.id}>
                      {document.title}
                    </option>
                  ))}
                </select>
              </label>
            )}
            <input
              className="w-full rounded-md border border-theme-border bg-theme-input px-3 py-2 text-sm"
              onChange={(e) => setLeaveReason(e.target.value)}
              placeholder="Reason (optional)"
              value={leaveReason}
            />
            <button
              className="rounded-md bg-brand-600 px-3 py-2 text-sm font-semibold text-white hover:bg-brand-700"
              disabled={!leaveTypeId || leavePending}
              type="submit"
            >
              Submit leave request
            </button>
          </form>

          <div className="mt-4 space-y-2">
            {leaveRequests.slice(0, 5).map((r) => (
              <div
                className="flex items-center justify-between text-xs text-theme-text-secondary"
                key={r.id}
              >
                <span>
                  {r.start_date} to {r.end_date} ({r.days_requested}d)
                </span>
                <StatusBadge tone={r.status === 'approved' ? 'success' : 'neutral'}>
                  {r.status}
                </StatusBadge>
                {['draft', 'submitted'].includes(r.status) && (
                  <button
                    type="button"
                    className="font-semibold text-brand-600"
                    disabled={leavePending}
                    onClick={() => void cancelLeave(r.id)}
                  >
                    Cancel leave
                  </button>
                )}
              </div>
            ))}
          </div>
        </div>

        <div className="rounded-lg border border-theme-border bg-theme-card p-5 shadow-xs space-y-5">
          <div>
            <h3 className="text-base font-semibold text-theme-text-primary">My HR Documents</h3>
            <div className="mt-2 space-y-2 text-sm">
              {documents.length === 0 ? (
                <p className="text-theme-text-muted">No shared HR documents.</p>
              ) : (
                documents.map((doc) => (
                  <div
                    className="flex items-center justify-between rounded border border-theme-border px-3 py-2"
                    key={doc.id}
                  >
                    <span>
                      {doc.title} ({doc.document_type})
                    </span>
                    <button
                      className="text-xs font-semibold text-brand-600 hover:underline"
                      onClick={() => void handleDownloadDoc(doc.id)}
                      type="button"
                    >
                      Download
                    </button>
                  </div>
                ))
              )}
            </div>
          </div>

          <div>
            <h3 className="text-base font-semibold text-theme-text-primary">Published Policies</h3>
            <div className="mt-2 space-y-2 text-sm">
              {policies.map((pol) => (
                <div
                  className="flex items-center justify-between rounded border border-theme-border px-3 py-2"
                  key={pol.id}
                >
                  <div>
                    <p className="font-medium text-theme-text-primary">
                      {pol.title} v{pol.version}
                    </p>
                    <p className="text-xs text-theme-text-muted">{pol.content_summary}</p>
                  </div>
                  <button
                    className="rounded border border-brand-600 px-2.5 py-1 text-xs font-semibold text-brand-600 hover:bg-brand-50"
                    onClick={() => void handleAcknowledge(pol.id)}
                    type="button"
                  >
                    Acknowledge
                  </button>
                </div>
              ))}
            </div>
          </div>

          <div>
            <h3 className="text-base font-semibold text-theme-text-primary">Recent Attendance</h3>
            <details className="mt-2 text-sm">
              <summary>Request an attendance correction</summary>
              <form
                className="mt-2 grid gap-2"
                onSubmit={(event) => {
                  event.preventDefault();
                  const form = event.currentTarget;
                  const data = new FormData(form);
                  setError(null);
                  void requestMyAttendanceCorrection({
                    work_date: String(data.get('day')),
                    requested_status: String(data.get('status')) as Parameters<
                      typeof requestMyAttendanceCorrection
                    >[0]['requested_status'],
                    requested_worked_hours: String(data.get('hours')),
                    reason: String(data.get('reason'))
                  })
                    .then(() => {
                      form.reset();
                      setNotice('Attendance correction requested.');
                    })
                    .catch((failure) =>
                      setError(formatApiError(failure, 'Could not submit correction.'))
                    );
                }}
              >
                <label>
                  Work date <input name="day" type="date" required />
                </label>
                <label>
                  Corrected status{' '}
                  <select name="status">
                    <option value="present">Present</option>
                    <option value="absent">Absent</option>
                    <option value="half_day">Half day</option>
                    <option value="on_leave">Leave</option>
                    <option value="holiday">Holiday</option>
                    <option value="remote">Remote</option>
                    <option value="site_duty">Site duty</option>
                  </select>
                </label>
                <label>
                  Worked hours{' '}
                  <input name="hours" type="number" min="0" max="24" step="0.01" required />
                </label>
                <label>
                  Reason <input name="reason" required minLength={2} maxLength={500} />
                </label>
                <button type="submit" className="rounded bg-brand-600 px-3 py-1 text-white">
                  Submit correction
                </button>
              </form>
            </details>
            <div className="mt-2 space-y-1 text-xs text-theme-text-secondary">
              {attendance.slice(0, 6).map((a) => (
                <div className="flex justify-between" key={a.id}>
                  <span>{a.work_date}</span>
                  <span>
                    {a.attendance_status} ({a.worked_hours}h)
                  </span>
                </div>
              ))}
            </div>
          </div>
        </div>
      </section>

      <section className="grid gap-6 lg:grid-cols-2">
        <div className="rounded-lg border border-theme-border bg-theme-card p-5 shadow-xs">
          <h3 className="text-base font-semibold text-theme-text-primary">HR Service Requests</h3>
          <form className="mt-3 space-y-3" onSubmit={(e) => void handleSubmitServiceReq(e)}>
            <select
              className="w-full rounded-md border border-theme-border bg-theme-input px-3 py-2 text-sm"
              onChange={(e) =>
                setReqType(
                  e.target.value as 'employment_letter' | 'address_change' | 'general_inquiry'
                )
              }
              value={reqType}
            >
              <option value="employment_letter">Employment Letter</option>
              <option value="address_change">Address Change</option>
              <option value="general_inquiry">General HR Inquiry</option>
            </select>
            <input
              className="w-full rounded-md border border-theme-border bg-theme-input px-3 py-2 text-sm"
              onChange={(e) => setReqSubject(e.target.value)}
              placeholder="Subject"
              required
              value={reqSubject}
            />
            <textarea
              className="w-full rounded-md border border-theme-border bg-theme-input px-3 py-2 text-sm"
              onChange={(e) => setReqDesc(e.target.value)}
              placeholder="Details"
              rows={2}
              value={reqDesc}
            />
            <button
              className="rounded-md bg-brand-600 px-3 py-2 text-sm font-semibold text-white hover:bg-brand-700"
              type="submit"
            >
              Submit request
            </button>
          </form>
          <div className="mt-3 space-y-1 text-xs">
            {serviceRequests.slice(0, 5).map((sr) => (
              <div className="flex justify-between" key={sr.id}>
                <span>
                  {sr.request_code}: {sr.subject}
                </span>
                <StatusBadge tone="neutral">{sr.status}</StatusBadge>
              </div>
            ))}
          </div>
        </div>
      </section>
    </div>
  );
}
