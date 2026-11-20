import { useQuery } from '@tanstack/react-query';
import axios from 'axios';
import { FormEvent, useCallback, useEffect, useState } from 'react';

import {
  cancelMyLeaveRequest,
  downloadMyHrDocument,
  getMyHrProfile,
  getMyLeaveBalances,
  getMyLeaveUnits,
  hrServiceRequestTypes,
  listMyAttendance,
  listMyHrDocuments,
  listMyLeaveRequests,
  listMyLeaveTypes,
  listMyServiceRequests,
  requestMyAttendanceCorrection,
  reopenMyServiceRequest,
  resubmitMyLeaveRequest,
  submitMyLeaveRequest,
  submitMyServiceRequest,
  updateMyHrProfile,
  type AttendanceEntryRecord,
  type EmployeeSelfRecord,
  type HrDocumentRecord,
  type HrServiceRequestRecord,
  type HrServiceRequestType,
  type LeaveBalanceItem,
  type LeaveRequestRecord,
  type LeaveTypeRecord
} from '../../api/hr';
import { formatApiError } from '../../api/errors';
import { StatusBadge } from '../../components/shared/StatusBadge';
import { HRResponseLetter } from './HRResponseLetter';
import { HRLetterRecords } from './HRLetterRecords';
import { HRPayslips } from './HRPayslips';
import { HRMeWorkflowPanel } from './HRMeWorkflowPanel';
import { HRMyTraining } from './HRMyTraining';
import { HRPerformanceReviews } from './HRPerformanceReviews';
import { HRMyPolicies } from './HRMyPolicies';

type SelfRecordResource =
  | 'balances'
  | 'leaveTypes'
  | 'leaveRequests'
  | 'attendance'
  | 'documents'
  | 'serviceRequests';

const selfRecordLabels: Record<SelfRecordResource, string> = {
  balances: 'Leave balances',
  leaveTypes: 'Leave types',
  leaveRequests: 'Leave requests',
  attendance: 'Attendance',
  documents: 'Shared documents',
  serviceRequests: 'HR service requests'
};

export function HRMePage() {
  const [profile, setProfile] = useState<EmployeeSelfRecord | null>(null);
  const [notLinked, setNotLinked] = useState(false);
  const [balances, setBalances] = useState<LeaveBalanceItem[]>([]);
  const [leaveTypes, setLeaveTypes] = useState<LeaveTypeRecord[]>([]);
  const [leaveRequests, setLeaveRequests] = useState<LeaveRequestRecord[]>([]);
  const [attendance, setAttendance] = useState<AttendanceEntryRecord[]>([]);
  const [documents, setDocuments] = useState<HrDocumentRecord[]>([]);
  const [serviceRequests, setServiceRequests] = useState<HrServiceRequestRecord[]>([]);
  const [reopeningRequest, setReopeningRequest] = useState<string | null>(null);
  const [loading, setLoading] = useState(true);
  const [recordLoading, setRecordLoading] = useState<
    Partial<Record<SelfRecordResource, boolean>>
  >({});
  const [recordErrors, setRecordErrors] = useState<Partial<Record<SelfRecordResource, string>>>({});
  const [notice, setNotice] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);

  const [personalPhone, setPersonalPhone] = useState('');
  const [contactPending, setContactPending] = useState(false);
  const [contactConflict, setContactConflict] = useState(false);
  const [personalEmail, setPersonalEmail] = useState('');
  const [residentialAddress, setResidentialAddress] = useState('');
  const [emergencyName, setEmergencyName] = useState('');
  const [emergencyPhone, setEmergencyPhone] = useState('');

  const [leaveTypeId, setLeaveTypeId] = useState('');
  const [leaveStart, setLeaveStart] = useState('');
  const [leaveEnd, setLeaveEnd] = useState('');
  const [leaveReason, setLeaveReason] = useState('');
  const [halfDayPeriod, setHalfDayPeriod] = useState<'' | 'morning' | 'afternoon'>('');
  const [leaveAttachment, setLeaveAttachment] = useState('');
  const [leavePending, setLeavePending] = useState(false);
  const [editingLeave, setEditingLeave] = useState<LeaveRequestRecord | null>(null);
  const [visibleLeaveCount, setVisibleLeaveCount] = useState(5);
  const leaveDates = {
    leave_type_id: leaveTypeId,
    start_date: leaveStart,
    end_date: leaveEnd,
    is_half_day: Boolean(halfDayPeriod),
    half_day_period: halfDayPeriod || null
  };
  const leaveUnits = useQuery({
    queryKey: ['hr', 'self', profile?.employee.id, 'leave-units', leaveDates],
    queryFn: () => getMyLeaveUnits(leaveDates),
    enabled: Boolean(profile?.employee.id && leaveTypeId && leaveStart && leaveEnd),
    retry: false
  });

  const [reqType, setReqType] = useState<HrServiceRequestType>('employment_letter');
  const [reqSubject, setReqSubject] = useState('');
  const [reqDesc, setReqDesc] = useState('');

  const acceptContactSnapshot = useCallback((snapshot: EmployeeSelfRecord) => {
    setProfile(snapshot);
    setContactConflict(false);
    setPersonalPhone(snapshot.personal_phone ?? '');
    setPersonalEmail(snapshot.personal_email ?? '');
    setResidentialAddress(snapshot.residential_address ?? '');
    setEmergencyName(snapshot.emergency_contact_name ?? '');
    setEmergencyPhone(snapshot.emergency_contact_phone ?? '');
  }, []);

  const loadRecord = useCallback(async <T,>(
    resource: SelfRecordResource,
    request: () => Promise<T>,
    accept: (result: T) => void
  ) => {
    setRecordLoading((current) => ({ ...current, [resource]: true }));
    setRecordErrors((current) => ({ ...current, [resource]: undefined }));
    try {
      accept(await request());
    } catch (err) {
      setRecordErrors((current) => ({
        ...current,
        [resource]: formatApiError(
          err,
          `Unable to load ${selfRecordLabels[resource].toLowerCase()}.`
        )
      }));
    } finally {
      setRecordLoading((current) => ({ ...current, [resource]: false }));
    }
  }, []);

  const retryRecord = useCallback(
    (resource: SelfRecordResource) => {
      switch (resource) {
        case 'balances':
          return loadRecord('balances', getMyLeaveBalances, (result) => setBalances(result.items));
        case 'leaveTypes':
          return loadRecord('leaveTypes', listMyLeaveTypes, (result) => {
            setLeaveTypes(result.items);
            setLeaveTypeId((selected) => selected || result.items[0]?.id || '');
          });
        case 'leaveRequests':
          return loadRecord('leaveRequests', listMyLeaveRequests, (result) =>
            setLeaveRequests(result.items)
          );
        case 'attendance':
          return loadRecord('attendance', listMyAttendance, (result) =>
            setAttendance(result.items)
          );
        case 'documents':
          return loadRecord('documents', listMyHrDocuments, (result) =>
            setDocuments(result.items)
          );
        case 'serviceRequests':
          return loadRecord('serviceRequests', listMyServiceRequests, (result) =>
            setServiceRequests(result.items)
          );
      }
    },
    [loadRecord]
  );

  const loadAll = useCallback(async () => {
    setLoading(true);
    setError(null);
    setNotLinked(false);
    try {
      acceptContactSnapshot(await getMyHrProfile());
    } catch (err) {
      if (axios.isAxiosError(err) && err.response?.status === 404) {
        setNotLinked(true);
      } else {
        setError(formatApiError(err, 'Unable to load HR self-service records.'));
      }
      return;
    } finally {
      setLoading(false);
    }

    await Promise.all([
      loadRecord('balances', getMyLeaveBalances, (result) => setBalances(result.items)),
      loadRecord('leaveTypes', listMyLeaveTypes, (result) => {
        setLeaveTypes(result.items);
        setLeaveTypeId((selected) => selected || result.items[0]?.id || '');
      }),
      loadRecord('leaveRequests', listMyLeaveRequests, (result) => setLeaveRequests(result.items)),
      loadRecord('attendance', listMyAttendance, (result) => setAttendance(result.items)),
      loadRecord('documents', listMyHrDocuments, (result) => setDocuments(result.items)),
      loadRecord('serviceRequests', listMyServiceRequests, (result) =>
        setServiceRequests(result.items)
      )
    ]);
  }, [acceptContactSnapshot, loadRecord]);

  useEffect(() => {
    void loadAll();
  }, [loadAll]);

  async function handleSaveContact(e: FormEvent) {
    e.preventDefault();
    if (!profile || contactPending || contactConflict) return;
    setContactPending(true);
    setError(null);
    setNotice(null);
    try {
      const updated = await updateMyHrProfile({
        expected_revision: profile.employee.record_revision,
        personal_phone: personalPhone || null,
        personal_email: personalEmail || null,
        residential_address: residentialAddress || null,
        emergency_contact_name: emergencyName || null,
        emergency_contact_phone: emergencyPhone || null
      });
      acceptContactSnapshot(updated);
      setNotice('Personal HR contact details updated.');
    } catch (err) {
      if (axios.isAxiosError(err) && err.response?.status === 409) setContactConflict(true);
      setError(formatApiError(err, 'Unable to update personal details.'));
    } finally {
      setContactPending(false);
    }
  }

  async function handleSubmitLeave(e: FormEvent) {
    e.preventDefault();
    if (leavePending || leaveUnits.isFetching || !leaveUnits.data || leaveUnits.isError) return;
    setLeavePending(true);
    setError(null);
    setNotice(null);
    try {
      const fields = {
        ...leaveDates,
        days_requested: leaveUnits.data.days_requested,
        attachment_document_id: leaveAttachment || null,
        reason: leaveReason || null
      };
      const saved = editingLeave
        ? await resubmitMyLeaveRequest(editingLeave.id, {
            ...fields,
            expected_revision: editingLeave.record_revision
          })
        : await submitMyLeaveRequest({ ...fields, submit_immediately: true });
      setLeaveRequests((requests) =>
        editingLeave
          ? requests.map((request) => (request.id === saved.id ? saved : request))
          : [saved, ...requests]
      );
      resetLeaveForm();
      setNotice(editingLeave ? 'Leave request resubmitted.' : 'Leave request submitted.');
    } catch (err) {
      setError(formatApiError(err, 'Unable to submit leave request.'));
      if (axios.isAxiosError(err) && err.response?.data?.error_code === 'LEAVE_UNITS_MISMATCH') {
        void leaveUnits.refetch();
      }
    } finally {
      setLeavePending(false);
    }
  }

  function resetLeaveForm() {
    setEditingLeave(null);
    setLeaveTypeId(leaveTypes[0]?.id ?? '');
    setLeaveStart('');
    setLeaveEnd('');
    setLeaveReason('');
    setLeaveAttachment('');
    setHalfDayPeriod('');
  }

  function editLeave(request: LeaveRequestRecord) {
    setEditingLeave(request);
    setLeaveTypeId(
      leaveTypes.some((type) => type.id === request.leave_type_id) ? request.leave_type_id : ''
    );
    setLeaveStart(request.start_date);
    setLeaveEnd(request.end_date);
    setLeaveReason(request.reason ?? '');
    setLeaveAttachment(request.attachment_document_id ?? '');
    setHalfDayPeriod(
      request.half_day_period === 'morning' || request.half_day_period === 'afternoon'
        ? request.half_day_period
        : ''
    );
    setError(null);
    setNotice(null);
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

  async function reopenRequest(request: HrServiceRequestRecord) {
    if (reopeningRequest) return;
    setReopeningRequest(request.id);
    setError(null);
    setNotice(null);
    try {
      const result = await reopenMyServiceRequest(request.id, request.updated_at);
      setServiceRequests((items) => items.map((item) => (item.id === result.id ? result : item)));
      setNotice('HR service request reopened.');
    } catch (err) {
      setError(formatApiError(err, 'Unable to reopen HR service request.'));
    } finally {
      setReopeningRequest(null);
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
        <div
          role="alert"
          className="rounded-md border border-[var(--status-error-border)] bg-[var(--status-error-bg)] px-4 py-2 text-sm text-[var(--status-error-text)]"
        >
          {error}
        </div>
      ) : null}
      {Object.values(recordLoading).some(Boolean) && (
        <p role="status" className="text-sm text-theme-text-muted">
          Loading HR records…
        </p>
      )}
      {Object.entries(recordErrors).map(([resource, message]) =>
        message ? (
          <div
            key={resource}
            role="alert"
            className="flex flex-wrap items-center gap-2 rounded-md border border-[var(--status-error-border)] bg-[var(--status-error-bg)] px-4 py-2 text-sm text-[var(--status-error-text)]"
          >
            <span>
              {selfRecordLabels[resource as SelfRecordResource]}: {message}
            </span>
            <button
              className="font-semibold underline"
              type="button"
              onClick={() => void retryRecord(resource as SelfRecordResource)}
            >
              Retry {selfRecordLabels[resource as SelfRecordResource]}
            </button>
          </div>
        ) : null
      )}

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
              disabled={contactPending}
            />
          </label>
          <label className="text-sm">
            <span className="block font-medium text-theme-text-secondary">Personal Email</span>
            <input
              className="mt-1 w-full rounded-md border border-theme-border bg-theme-input px-3 py-2 text-sm"
              onChange={(e) => setPersonalEmail(e.target.value)}
              type="email"
              value={personalEmail}
              disabled={contactPending}
            />
          </label>
          <label className="text-sm md:col-span-2">
            <span className="block font-medium text-theme-text-secondary">Residential Address</span>
            <input
              className="mt-1 w-full rounded-md border border-theme-border bg-theme-input px-3 py-2 text-sm"
              onChange={(e) => setResidentialAddress(e.target.value)}
              value={residentialAddress}
              disabled={contactPending}
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
              disabled={contactPending}
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
              disabled={contactPending}
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
              disabled={contactPending || contactConflict}
            >
              {contactPending ? 'Saving contact details…' : 'Save contact details'}
            </button>
            {contactConflict && (
              <button
                className="rounded-md border border-theme-border px-4 py-2 text-sm font-semibold"
                type="button"
                onClick={() => void loadAll()}
              >
                Discard edits and reload contact details
              </button>
            )}
          </div>
        </form>
      </section>

      <HRMeWorkflowPanel />
      <HRMyTraining />
      <HRPerformanceReviews />

      <section className="grid gap-6 lg:grid-cols-2">
        <div className="rounded-lg border border-theme-border bg-theme-card p-5 shadow-xs">
          <h3 className="text-base font-semibold text-theme-text-primary">My Leave Balances</h3>
          <div className="mt-3 space-y-2 text-sm">
            {recordLoading.balances ? (
              <p role="status" className="text-theme-text-muted">Loading leave balances…</p>
            ) : recordErrors.balances ? null : balances.length === 0 ? (
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
            <h4 className="text-sm font-semibold text-theme-text-primary">
              {editingLeave ? 'Correct leave request' : 'Request Leave'}
            </h4>
            <select
              className="w-full rounded-md border border-theme-border bg-theme-input px-3 py-2 text-sm"
              onChange={(e) => setLeaveTypeId(e.target.value)}
              required
              disabled={recordLoading.leaveTypes || leaveTypes.length === 0}
              aria-label="Leave type"
              value={leaveTypeId}
            >
              <option value="">
                {recordLoading.leaveTypes
                  ? 'Loading leave types…'
                  : recordErrors.leaveTypes
                    ? 'Leave types unavailable'
                    : leaveTypes.length === 0
                      ? 'No leave types available'
                      : 'Select leave type'}
              </option>
              {leaveTypes.map((lt) => (
                <option key={lt.id} value={lt.id}>
                  {lt.name} ({lt.code})
                </option>
              ))}
            </select>
            <div className="grid grid-cols-2 gap-2">
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
            {leaveUnits.isFetching && <p role="status">Calculating scheduled leave days…</p>}
            {leaveUnits.isError && (
              <p role="alert">
                {formatApiError(leaveUnits.error, 'Unable to calculate leave days.')}
              </p>
            )}
            {leaveUnits.isSuccess && (
              <p className="text-sm">Scheduled leave days: {leaveUnits.data.days_requested}</p>
            )}
            {(leaveTypes.find((type) => type.id === leaveTypeId)?.requires_attachment ||
              leaveAttachment !== '') && (
              <label className="block text-sm">
                Supporting document
                <select
                  className="ml-2 rounded border border-theme-border bg-theme-input"
                  value={leaveAttachment}
                  onChange={(event) => setLeaveAttachment(event.target.value)}
                  disabled={recordLoading.documents || documents.length === 0}
                  required={leaveTypes.find((type) => type.id === leaveTypeId)?.requires_attachment}
                >
                  <option value="">
                    {recordLoading.documents
                      ? 'Loading shared documents…'
                      : recordErrors.documents
                        ? 'Shared documents unavailable'
                        : 'Choose a shared document'}
                  </option>
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
              disabled={!leaveUnits.isSuccess || leaveUnits.isFetching || leavePending}
              type="submit"
            >
              {editingLeave ? 'Resubmit leave request' : 'Submit leave request'}
            </button>
            {editingLeave && (
              <button
                type="button"
                className="ml-3 text-sm"
                onClick={resetLeaveForm}
                disabled={leavePending}
              >
                Cancel editing
              </button>
            )}
          </form>

          <div className="mt-4 space-y-2">
            {leaveRequests.slice(0, visibleLeaveCount).map((r) => (
              <div
                className="flex items-center justify-between text-xs text-theme-text-secondary"
                key={r.id}
              >
                <span>
                  {r.start_date} to {r.end_date} ({r.days_requested}d)
                  {(r.status === 'rejected' || r.status === 'cancelled') && r.decision_notes && (
                    <span className="block">{r.decision_notes}</span>
                  )}
                </span>
                <StatusBadge tone={r.status === 'approved' ? 'success' : 'neutral'}>
                  {r.status}
                </StatusBadge>
                {r.requested_by_id === profile.employee.user_id &&
                  ['draft', 'rejected'].includes(r.status) && (
                    <button
                      type="button"
                      className="font-semibold text-brand-600"
                      disabled={leavePending}
                      onClick={() => editLeave(r)}
                    >
                      Edit leave request
                    </button>
                  )}
                {r.requested_by_id === profile.employee.user_id &&
                  ['draft', 'submitted'].includes(r.status) && (
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
            {leaveRequests.length > visibleLeaveCount && (
              <button
                type="button"
                className="text-sm text-brand-600"
                onClick={() => setVisibleLeaveCount((count) => count + 5)}
              >
                Show more leave requests
              </button>
            )}
          </div>
        </div>

        <div className="rounded-lg border border-theme-border bg-theme-card p-5 shadow-xs space-y-5">
          <HRLetterRecords />
          <HRPayslips />
          <div>
            <h3 className="text-base font-semibold text-theme-text-primary">My HR Documents</h3>
            <div className="mt-2 space-y-2 text-sm">
              {recordLoading.documents ? (
                <p role="status" className="text-theme-text-muted">Loading shared HR documents…</p>
              ) : recordErrors.documents ? null : documents.length === 0 ? (
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

          <HRMyPolicies />

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
              {recordLoading.attendance && <p role="status">Loading attendance…</p>}
              {!recordLoading.attendance && !recordErrors.attendance && attendance.length === 0 && (
                <p>No recent attendance records.</p>
              )}
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
              aria-label="Request type"
              className="w-full rounded-md border border-theme-border bg-theme-input px-3 py-2 text-sm"
              onChange={(e) => setReqType(e.target.value as HrServiceRequestType)}
              value={reqType}
            >
              {Object.entries(hrServiceRequestTypes).map(([value, label]) => (
                <option key={value} value={value}>{label}</option>
              ))}
            </select>
            <input
              className="w-full rounded-md border border-theme-border bg-theme-input px-3 py-2 text-sm"
              onChange={(e) => setReqSubject(e.target.value)}
              placeholder="Subject"
              minLength={2}
              maxLength={200}
              required
              value={reqSubject}
            />
            <textarea
              className="w-full rounded-md border border-theme-border bg-theme-input px-3 py-2 text-sm"
              onChange={(e) => setReqDesc(e.target.value)}
              placeholder="Details"
              maxLength={2000}
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
            {recordLoading.serviceRequests && <p role="status">Loading service requests…</p>}
            {!recordLoading.serviceRequests &&
              !recordErrors.serviceRequests &&
              serviceRequests.length === 0 && <p>No HR service requests yet.</p>}
            {serviceRequests.map((sr) => (
              <div className="flex flex-wrap items-center gap-2" key={sr.id}>
                <span>
                  {sr.request_code}: {sr.subject}
                </span>
                <StatusBadge tone="neutral">{sr.status}</StatusBadge>
                {documents
                  .filter((document) => document.id === sr.generated_document_id)
                  .map((document) => (
                    <button
                      className="rounded border border-theme-border px-2 py-1"
                      key={document.id}
                      onClick={() => void handleDownloadDoc(document.id)}
                      type="button"
                    >
                      Download response document
                    </button>
                  ))}
                {sr.generated_letter_id && (
                  <HRResponseLetter
                    key={sr.generated_letter_id}
                    letterId={sr.generated_letter_id}
                  />
                )}
                {sr.resolution_notes && (
                  <p className="basis-full whitespace-pre-wrap">{sr.resolution_notes}</p>
                )}
                {['completed', 'rejected'].includes(sr.status) && (
                  <button
                    className="rounded border border-theme-border px-2 py-1"
                    disabled={reopeningRequest !== null}
                    onClick={() => void reopenRequest(sr)}
                    aria-label={`Reopen request ${sr.request_code}`}
                    type="button"
                  >
                    {reopeningRequest === sr.id ? 'Reopening…' : 'Reopen request'}
                  </button>
                )}
              </div>
            ))}
          </div>
        </div>
      </section>
    </div>
  );
}
