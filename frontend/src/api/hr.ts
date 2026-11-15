import { apiClient, EXPORT_TIMEOUT_MS } from './client';
import type { components } from './schema';

export type HrSchemas = components['schemas'];

export type DepartmentRecord = HrSchemas['DepartmentResponse'];
export type PositionRecord = HrSchemas['PositionResponse'];
export type OrgChartResponse = HrSchemas['OrgChartResponse'];
export type OrgChartNode = HrSchemas['OrgChartNode'];
export type EmployeeDirectoryRecord = HrSchemas['EmployeeDirectoryResponse'];
export type EmployeeDetailRecord = HrSchemas['EmployeeDetailResponse'];
export type EmployeeSensitiveRecord = HrSchemas['EmployeeSensitiveResponse'];
export type EmployeeSelfRecord = HrSchemas['EmployeeSelfResponse'];
export type EmploymentHistoryRecord = HrSchemas['EmploymentHistoryResponse'];
export type AccessRequestRecord = HrSchemas['AccessRequestResponse'];
export type WorkbookPreviewResponse = HrSchemas['WorkbookPreviewResponse'];
export type WorkbookApplyResponse = HrSchemas['WorkbookApplyResponse'];
export type RequisitionRecord = HrSchemas['RequisitionResponse'];
export type CandidateRecord = HrSchemas['CandidateResponse'];
export type ApplicationRecord = HrSchemas['ApplicationResponse'];
export type OfferRecord = HrSchemas['OfferResponse'];
export type OnboardingCaseRecord = HrSchemas['OnboardingCaseResponse'];
export type HrDocumentRecord = HrSchemas['HrDocumentResponse'];
export type HrDocumentDownloadRecord = HrSchemas['HrDocumentDownloadResponse'];
export type ExpiringComplianceResponse = HrSchemas['ExpiringComplianceResponse'];
export type WorkCalendarRecord = HrSchemas['WorkCalendarResponse'];
export type HolidayRecord = HrSchemas['HolidayResponse'];
export type ShiftAssignmentRecord = HrSchemas['ShiftAssignmentResponse'];
export type AttendanceEntryRecord = HrSchemas['AttendanceEntryResponse'];
export type AttendanceCorrectionRecord = HrSchemas['AttendanceCorrectionResponse'];
export type TimesheetRecord = HrSchemas['TimesheetResponse'];
export type OvertimeRequestRecord = HrSchemas['OvertimeRequestResponse'];
export type LeaveTypeRecord = HrSchemas['LeaveTypeResponse'];
export type LeavePolicyRecord = HrSchemas['LeavePolicyResponse'];
export type LeaveBalanceItem = HrSchemas['LeaveBalanceItem'];
export type LeaveRequestRecord = HrSchemas['LeaveRequestResponse'];
export type PolicyDocumentRecord = HrSchemas['PolicyDocumentResponse'];
export type LetterTemplateRecord = HrSchemas['LetterTemplateResponse'];
export type LetterRenderRecord = HrSchemas['LetterRenderResponse'];
export type HrServiceRequestRecord = HrSchemas['HrServiceRequestResponse'];
export type OffboardingCaseRecord = HrSchemas['OffboardingCaseResponse'];
export type GoalRecord = HrSchemas['GoalResponse'];
export type ReviewCycleRecord = HrSchemas['ReviewCycleResponse'];
export type ReviewRecord = HrSchemas['ReviewResponse'];
export type TrainingCourseRecord = HrSchemas['TrainingCourseResponse'];
export type TrainingEnrollmentRecord = HrSchemas['TrainingEnrollmentResponse'];
export type CertificationRecord = HrSchemas['CertificationResponse'];
export type BenefitTypeRecord = HrSchemas['BenefitTypeResponse'];
export type EmployeeBenefitRecord = HrSchemas['EmployeeBenefitResponse'];
export type ReimbursementRecord = HrSchemas['ReimbursementResponse'];
export type CompensationTermRecord = HrSchemas['CompensationTermResponse'];
export type PayrollPolicyRecord = HrSchemas['PayrollPolicyResponse'];
export type PayrollPeriodRecord = HrSchemas['PayrollPeriodResponse'];
export type PayrollRunRecord = HrSchemas['PayrollRunResponse'];
export type HrCaseRecord = HrSchemas['HrCaseResponse'];
export type HrSummaryReportResponse = HrSchemas['HrSummaryReportResponse'];
export type HrReportFilters = HrSchemas['HrReportFilters'];
export type HrReportFormat = 'xlsx' | 'csv' | 'pdf';
export type ManagerReviewItem = HrSchemas['ManagerReviewItemResponse'];

// --- Overview & Org ---

export async function getHrSummary(filters: HrReportFilters, signal?: AbortSignal) {
  const { data } = await apiClient.get<HrSummaryReportResponse>('/hr/reports/summary', {
    params: filters,
    signal
  });
  return data;
}

export async function listHrReportSites(offset: number, limit: number, signal?: AbortSignal) {
  const { data } = await apiClient.get<HrSchemas['HrReportSiteListResponse']>('/hr/reports/sites', {
    params: { offset, limit },
    signal
  });
  return data;
}

export async function downloadHrSummary(format: HrReportFormat, filters: HrReportFilters) {
  const { data } = await apiClient.get<Blob>(`/hr/reports/summary.${format}`, {
    params: filters,
    responseType: 'blob',
    timeout: EXPORT_TIMEOUT_MS
  });
  const signatures = { xlsx: 'PK\u0003\u0004', pdf: '%PDF-', csv: 'Metric,Count' };
  const signature = signatures[format];
  if ((await data.slice(0, signature.length).text()) !== signature) {
    throw new Error('The server returned an invalid HR report.');
  }
  const url = URL.createObjectURL(data);
  const link = document.createElement('a');
  link.href = url;
  link.download = `hr-summary.${format}`;
  try {
    link.click();
  } finally {
    window.setTimeout(() => URL.revokeObjectURL(url), 1000);
  }
}

export async function listDepartments() {
  const { data } = await apiClient.get<HrSchemas['DepartmentListResponse']>('/hr/departments');
  return data;
}

export async function createDepartment(payload: HrSchemas['DepartmentCreateRequest']) {
  const { data } = await apiClient.post<DepartmentRecord>('/hr/departments', payload);
  return data;
}

export async function listPositions() {
  const { data } = await apiClient.get<HrSchemas['PositionListResponse']>('/hr/positions');
  return data;
}

export async function createPosition(payload: HrSchemas['PositionCreateRequest']) {
  const { data } = await apiClient.post<PositionRecord>('/hr/positions', payload);
  return data;
}

export async function getOrgChart() {
  const { data } = await apiClient.get<OrgChartResponse>('/hr/org-chart');
  return data;
}

// --- Employees & Private Vault ---

export async function listEmployees(params?: {
  search?: string;
  employment_status?: string;
  department_id?: string;
  limit?: number;
  offset?: number;
}) {
  const { data } = await apiClient.get<HrSchemas['EmployeeDirectoryListResponse']>(
    '/hr/employees',
    { params }
  );
  return data;
}

export async function getEmployee(employeeId: string) {
  const { data } = await apiClient.get<EmployeeDetailRecord>(`/hr/employees/${employeeId}`);
  return data;
}

export async function createEmployee(payload: HrSchemas['EmployeeCreateRequest']) {
  const { data } = await apiClient.post<EmployeeDetailRecord>('/hr/employees', payload);
  return data;
}

export async function updateEmployee(
  employeeId: string,
  payload: HrSchemas['EmployeeUpdateRequest']
) {
  const { data } = await apiClient.patch<EmployeeDetailRecord>(
    `/hr/employees/${employeeId}`,
    payload
  );
  return data;
}

export async function transitionEmployeeStatus(
  employeeId: string,
  payload: HrSchemas['EmployeeStatusTransitionRequest']
) {
  const { data } = await apiClient.post<EmployeeDetailRecord>(
    `/hr/employees/${employeeId}/status`,
    payload
  );
  return data;
}

export async function getEmployeeHistory(employeeId: string) {
  const { data } = await apiClient.get<HrSchemas['EmploymentHistoryListResponse']>(
    `/hr/employees/${employeeId}/history`
  );
  return data;
}

export async function getEmployeePrivate(employeeId: string, revealSensitive = false) {
  const { data } = await apiClient.get<EmployeeSensitiveRecord>(
    `/hr/employees/${employeeId}/private`,
    { params: { reveal_sensitive: revealSensitive } }
  );
  return data;
}

export async function upsertEmployeePrivate(
  employeeId: string,
  payload: HrSchemas['EmployeePrivateUpdateRequest']
) {
  const { data } = await apiClient.put<EmployeeSensitiveRecord>(
    `/hr/employees/${employeeId}/private`,
    payload
  );
  return data;
}

// --- Access Requests & 7-Column Workbook ---

export async function listAccessRequests(requestStatus?: string) {
  const { data } = await apiClient.get<HrSchemas['AccessRequestListResponse']>(
    '/hr/access-requests',
    { params: requestStatus ? { request_status: requestStatus } : undefined }
  );
  return data;
}

export async function createAccessRequest(payload: HrSchemas['AccessRequestCreateRequest']) {
  const { data } = await apiClient.post<AccessRequestRecord>('/hr/access-requests', payload);
  return data;
}

export async function decideAccessRequest(
  requestId: string,
  payload: HrSchemas['AccessRequestDecisionRequest']
) {
  const { data } = await apiClient.post<AccessRequestRecord>(
    `/hr/access-requests/${requestId}/decision`,
    payload
  );
  return data;
}

export async function previewHrWorkbook(
  file: File,
  explicitRoleOverrides?: Record<string, string>
) {
  const formData = new FormData();
  formData.append('file', file);
  if (explicitRoleOverrides && Object.keys(explicitRoleOverrides).length > 0) {
    formData.append('explicit_role_overrides_json', JSON.stringify(explicitRoleOverrides));
  }
  const { data } = await apiClient.post<WorkbookPreviewResponse>(
    '/hr/imports/workbook-preview',
    formData,
    { headers: { 'Content-Type': 'multipart/form-data' } }
  );
  return data;
}

export async function applyHrWorkbook(payload: HrSchemas['WorkbookApplyRequest']) {
  const { data } = await apiClient.post<WorkbookApplyResponse>(
    '/hr/imports/workbook-apply',
    payload
  );
  return data;
}

// --- Recruitment & Onboarding ---

export async function listRequisitions() {
  const { data } = await apiClient.get<HrSchemas['RequisitionListResponse']>('/hr/requisitions');
  return data;
}

export async function createRequisition(payload: HrSchemas['RequisitionCreateRequest']) {
  const { data } = await apiClient.post<RequisitionRecord>('/hr/requisitions', payload);
  return data;
}

export async function decideRequisition(
  requisitionId: string,
  payload: HrSchemas['RequisitionDecisionRequest']
) {
  const { data } = await apiClient.post<RequisitionRecord>(
    `/hr/requisitions/${requisitionId}/decision`,
    payload
  );
  return data;
}

export async function listCandidates() {
  const { data } = await apiClient.get<HrSchemas['CandidateListResponse']>('/hr/candidates');
  return data;
}

export async function createCandidate(payload: HrSchemas['CandidateCreateRequest']) {
  const { data } = await apiClient.post<CandidateRecord>('/hr/candidates', payload);
  return data;
}

export async function listApplications() {
  const { data } = await apiClient.get<HrSchemas['ApplicationListResponse']>('/hr/applications');
  return data;
}

export async function createApplication(payload: HrSchemas['ApplicationCreateRequest']) {
  const { data } = await apiClient.post<ApplicationRecord>('/hr/applications', payload);
  return data;
}

export async function updateApplicationStage(
  applicationId: string,
  payload: HrSchemas['ApplicationStageUpdateRequest']
) {
  const { data } = await apiClient.patch<ApplicationRecord>(
    `/hr/applications/${applicationId}/stage`,
    payload
  );
  return data;
}

export async function listInterviews() {
  const { data } = await apiClient.get<HrSchemas['InterviewListResponse']>('/hr/interviews');
  return data;
}

export async function createInterview(payload: HrSchemas['InterviewCreateRequest']) {
  const { data } = await apiClient.post<HrSchemas['InterviewResponse']>('/hr/interviews', payload);
  return data;
}

export async function updateInterview(id: string, payload: HrSchemas['InterviewUpdateRequest']) {
  const { data } = await apiClient.patch<HrSchemas['InterviewResponse']>(
    `/hr/interviews/${id}`,
    payload
  );
  return data;
}

export async function listOffers() {
  const { data } = await apiClient.get<HrSchemas['OfferListResponse']>('/hr/offers');
  return data;
}

export async function createOffer(payload: HrSchemas['OfferCreateRequest']) {
  const { data } = await apiClient.post<OfferRecord>('/hr/offers', payload);
  return data;
}

export async function decideOffer(offerId: string, payload: HrSchemas['OfferDecisionRequest']) {
  const { data } = await apiClient.post<OfferRecord>(`/hr/offers/${offerId}/decision`, payload);
  return data;
}

export async function convertOffer(offerId: string, payload: HrSchemas['OfferConvertRequest']) {
  const { data } = await apiClient.post<HrSchemas['OnboardingCaseResponse']>(
    `/hr/offers/${offerId}/convert`,
    payload
  );
  return data;
}

export async function listOnboardingCases() {
  const { data } = await apiClient.get<HrSchemas['OnboardingCaseListResponse']>('/hr/onboarding');
  return data;
}

export async function createOnboardingCase(payload: HrSchemas['OnboardingCaseCreateRequest']) {
  const { data } = await apiClient.post<HrSchemas['OnboardingCaseResponse']>(
    '/hr/onboarding',
    payload
  );
  return data;
}

export async function updateOnboardingTask(
  taskId: string,
  payload: HrSchemas['OnboardingTaskUpdateRequest']
) {
  const { data } = await apiClient.patch<HrSchemas['OnboardingCaseResponse']>(
    `/hr/onboarding/tasks/${taskId}`,
    payload
  );
  return data;
}

// --- Documents & Compliance ---

export async function listHrDocuments(params?: { employee_id?: string; category?: string }) {
  const { data } = await apiClient.get<HrSchemas['HrDocumentListResponse']>('/hr/documents', {
    params
  });
  return data;
}

export async function uploadHrDocument(params: {
  file: File;
  title: string;
  document_type: string;
  category: string;
  employee_id?: string;
  expiry_date?: string;
  is_employee_visible?: boolean;
}) {
  const formData = new FormData();
  formData.append('file', params.file);
  formData.append('title', params.title);
  formData.append('document_type', params.document_type);
  formData.append('category', params.category);
  if (params.employee_id) formData.append('employee_id', params.employee_id);
  if (params.expiry_date) formData.append('expiry_date', params.expiry_date);
  formData.append('is_employee_visible', String(params.is_employee_visible ?? false));
  const { data } = await apiClient.post<HrDocumentRecord>('/hr/documents', formData, {
    headers: { 'Content-Type': 'multipart/form-data' }
  });
  return data;
}

export async function uploadHrDocumentVersion(documentId: string, file: File) {
  const formData = new FormData();
  formData.append('file', file);
  const { data } = await apiClient.post<HrDocumentRecord>(
    `/hr/documents/${documentId}/versions`,
    formData,
    { headers: { 'Content-Type': 'multipart/form-data' } }
  );
  return data;
}

export async function decideHrDocumentVersion(
  documentId: string,
  version: number,
  payload: HrSchemas['HrDocumentDecisionRequest']
) {
  const { data } = await apiClient.post<HrDocumentRecord>(
    `/hr/documents/${documentId}/versions/${version}/decision`,
    payload
  );
  return data;
}

export async function getHrDocumentDownloadUrl(documentId: string, version?: number) {
  const { data } = await apiClient.get<HrDocumentDownloadRecord>(
    `/hr/documents/${documentId}/download`,
    { params: { version_number: version } }
  );
  return data;
}

export async function listExpiringCompliance(withinDays = 30) {
  const { data } = await apiClient.get<ExpiringComplianceResponse>('/hr/compliance/expiring', {
    params: { within_days: withinDays }
  });
  return data;
}

export async function listCertifications() {
  const { data } =
    await apiClient.get<HrSchemas['CertificationListResponse']>('/hr/certifications');
  return data;
}

export async function createCertification(payload: HrSchemas['CertificationCreateRequest']) {
  const { data } = await apiClient.post<CertificationRecord>('/hr/certifications', payload);
  return data;
}

// --- Attendance, Timesheets, Overtime ---

export async function listCalendars() {
  const { data } = await apiClient.get<HrSchemas['WorkCalendarListResponse']>('/hr/calendars');
  return data;
}

export async function createCalendar(payload: HrSchemas['WorkCalendarCreateRequest']) {
  const { data } = await apiClient.post<WorkCalendarRecord>('/hr/calendars', payload);
  return data;
}

export async function updateCalendar(id: string, payload: HrSchemas['WorkCalendarUpdateRequest']) {
  const { data } = await apiClient.patch<WorkCalendarRecord>(`/hr/calendars/${id}`, payload);
  return data;
}

export async function decideCalendar(
  id: string,
  payload: HrSchemas['WorkCalendarDecisionRequest']
) {
  const { data } = await apiClient.post<WorkCalendarRecord>(
    `/hr/calendars/${id}/decision`,
    payload
  );
  return data;
}

export async function getWorkSchedule(employeeId: string, workDate: string) {
  const { data } = await apiClient.get<HrSchemas['WorkScheduleResponse']>('/hr/schedule', {
    params: { employee_id: employeeId, work_date: workDate }
  });
  return data;
}

export async function listHolidays() {
  const { data } = await apiClient.get<HrSchemas['HolidayListResponse']>('/hr/holidays');
  return data;
}

export async function createHoliday(payload: HrSchemas['HolidayCreateRequest']) {
  const { data } = await apiClient.post<HrSchemas['HolidayResponse']>('/hr/holidays', payload);
  return data;
}

export async function listShifts() {
  const { data } = await apiClient.get<HrSchemas['ShiftAssignmentListResponse']>('/hr/shifts');
  return data;
}

export async function createShift(payload: HrSchemas['ShiftAssignmentCreateRequest']) {
  const { data } = await apiClient.post<HrSchemas['ShiftAssignmentResponse']>(
    '/hr/shifts',
    payload
  );
  return data;
}

export async function listAttendance(params?: { employee_id?: string }) {
  const { data } = await apiClient.get<HrSchemas['AttendanceEntryListResponse']>('/hr/attendance', {
    params
  });
  return data;
}

export async function createAttendance(payload: HrSchemas['AttendanceEntryCreateRequest']) {
  const { data } = await apiClient.post<AttendanceEntryRecord>('/hr/attendance', payload);
  return data;
}

export async function decideAttendance(id: string, payload: HrSchemas['AttendanceReviewRequest']) {
  const { data } = await apiClient.post<AttendanceEntryRecord>(
    `/hr/attendance/${id}/decision`,
    payload
  );
  return data;
}

export async function stageAttendanceImport(file: File, digest?: string) {
  const body = new FormData();
  body.set('file', file);
  if (digest) body.set('expected_digest', digest);
  const { data } = await apiClient.post<HrSchemas['AttendanceImportPreviewResponse']>(
    `/hr/attendance/imports/${digest ? 'apply' : 'preview'}`,
    body,
    { timeout: EXPORT_TIMEOUT_MS, headers: { 'Content-Type': 'multipart/form-data' } }
  );
  return data;
}

export async function createAttendanceCorrection(
  payload: HrSchemas['AttendanceCorrectionCreateRequest']
) {
  const { data } = await apiClient.post<HrSchemas['AttendanceCorrectionResponse']>(
    '/hr/attendance/corrections',
    payload
  );
  return data;
}

export async function createTimesheet(payload: HrSchemas['TimesheetCreateRequest']) {
  const { data } = await apiClient.post<HrSchemas['TimesheetResponse']>('/hr/timesheets', payload);
  return data;
}

export async function createOvertimeRequest(payload: HrSchemas['OvertimeRequestCreateRequest']) {
  const { data } = await apiClient.post<HrSchemas['OvertimeRequestResponse']>(
    '/hr/overtime',
    payload
  );
  return data;
}

export async function decideOvertimeRequest(
  id: string,
  payload: HrSchemas['OvertimeDecisionRequest']
) {
  const { data } = await apiClient.post<HrSchemas['OvertimeRequestResponse']>(
    `/hr/overtime/${id}/decision`,
    payload
  );
  return data;
}

export async function listAttendanceCorrections() {
  const { data } = await apiClient.get<HrSchemas['AttendanceCorrectionListResponse']>(
    '/hr/attendance/corrections'
  );
  return data;
}

export async function decideAttendanceCorrection(
  correctionId: string,
  payload: HrSchemas['AttendanceCorrectionDecisionRequest']
) {
  const { data } = await apiClient.post<AttendanceCorrectionRecord>(
    `/hr/attendance/corrections/${correctionId}/decision`,
    payload
  );
  return data;
}

export async function listTimesheets() {
  const { data } = await apiClient.get<HrSchemas['TimesheetListResponse']>('/hr/timesheets');
  return data;
}

export async function decideTimesheet(
  timesheetId: string,
  payload: HrSchemas['TimesheetDecisionRequest']
) {
  const { data } = await apiClient.post<TimesheetRecord>(
    `/hr/timesheets/${timesheetId}/decision`,
    payload
  );
  return data;
}

export async function listOvertimeRequests() {
  const { data } = await apiClient.get<HrSchemas['OvertimeRequestListResponse']>('/hr/overtime');
  return data;
}

// --- Leave Management ---

export async function listLeaveTypes() {
  const { data } = await apiClient.get<HrSchemas['LeaveTypeListResponse']>('/hr/leave/types');
  return data;
}

export async function createLeaveType(payload: HrSchemas['LeaveTypeCreateRequest']) {
  const { data } = await apiClient.post<LeaveTypeRecord>('/hr/leave/types', payload);
  return data;
}

export async function listLeavePolicies() {
  const { data } = await apiClient.get<HrSchemas['LeavePolicyListResponse']>('/hr/leave/policies');
  return data;
}

export async function createLeavePolicy(payload: HrSchemas['LeavePolicyCreateRequest']) {
  const { data } = await apiClient.post<LeavePolicyRecord>('/hr/leave/policies', payload);
  return data;
}

export async function getLeaveBalances(employeeId: string, year?: number) {
  const { data } = await apiClient.get<HrSchemas['LeaveBalanceListResponse']>(
    `/hr/leave/balances/${employeeId}`,
    { params: { leave_year: year } }
  );
  return data;
}

export async function adjustLeaveLedger(payload: HrSchemas['LeaveLedgerAdjustRequest']) {
  const { data } = await apiClient.post<HrSchemas['LeaveLedgerEntryResponse']>(
    '/hr/leave/ledger',
    payload
  );
  return data;
}

export async function listLeaveRequests() {
  const { data } = await apiClient.get<HrSchemas['LeaveRequestListResponse']>('/hr/leave/requests');
  return data;
}

export async function decideLeaveRequest(
  leaveRequestId: string,
  payload: HrSchemas['LeaveRequestDecisionRequest']
) {
  const { data } = await apiClient.post<LeaveRequestRecord>(
    `/hr/leave/requests/${leaveRequestId}/decision`,
    payload
  );
  return data;
}

// --- Policies, Letters, Service Requests, Offboarding ---

export async function listPolicies() {
  const { data } = await apiClient.get<HrSchemas['PolicyDocumentListResponse']>('/hr/policies');
  return data;
}

export async function createPolicy(payload: HrSchemas['PolicyDocumentCreateRequest']) {
  const { data } = await apiClient.post<PolicyDocumentRecord>('/hr/policies', payload);
  return data;
}

export async function listLetterTemplates() {
  const { data } =
    await apiClient.get<HrSchemas['LetterTemplateListResponse']>('/hr/letter-templates');
  return data;
}

export async function createLetterTemplate(payload: HrSchemas['LetterTemplateCreateRequest']) {
  const { data } = await apiClient.post<LetterTemplateRecord>('/hr/letter-templates', payload);
  return data;
}

export async function renderLetter(payload: HrSchemas['LetterGenerateRequest']) {
  const { data } = await apiClient.post<LetterRenderRecord>('/hr/letters/render', payload);
  return data;
}

export async function listServiceRequests() {
  const { data } = await apiClient.get<HrSchemas['HrServiceRequestListResponse']>('/hr/requests');
  return data;
}

export async function resolveServiceRequest(
  reqId: string,
  payload: HrSchemas['HrServiceRequestResolveRequest']
) {
  const { data } = await apiClient.post<HrServiceRequestRecord>(
    `/hr/requests/${reqId}/resolve`,
    payload
  );
  return data;
}

export async function listOffboardingCases() {
  const { data } = await apiClient.get<HrSchemas['OffboardingCaseListResponse']>('/hr/offboarding');
  return data;
}

export async function initiateOffboarding(payload: HrSchemas['OffboardingInitiateRequest']) {
  const { data } = await apiClient.post<OffboardingCaseRecord>('/hr/offboarding', payload);
  return data;
}

export async function updateOffboardingStep(
  stepId: string,
  payload: HrSchemas['OffboardingStepUpdateRequest']
) {
  const { data } = await apiClient.patch<HrSchemas['ClearanceStepResponse']>(
    `/hr/offboarding/steps/${stepId}`,
    payload
  );
  return data;
}

export async function completeOffboarding(
  caseId: string,
  payload: HrSchemas['OffboardingCompleteRequest']
) {
  const { data } = await apiClient.post<OffboardingCaseRecord>(
    `/hr/offboarding/${caseId}/complete`,
    payload
  );
  return data;
}

// --- P2 Modules & Policy-Gated Payroll ---

export async function listGoals() {
  const { data } = await apiClient.get<HrSchemas['GoalListResponse']>('/hr/goals');
  return data;
}

export async function createGoal(payload: HrSchemas['GoalCreateRequest']) {
  const { data } = await apiClient.post<GoalRecord>('/hr/goals', payload);
  return data;
}

export async function listPayrollPolicies() {
  const { data } =
    await apiClient.get<HrSchemas['PayrollPolicyListResponse']>('/hr/payroll/policies');
  return data;
}

export async function createPayrollPolicy(payload: HrSchemas['PayrollPolicyCreateRequest']) {
  const { data } = await apiClient.post<PayrollPolicyRecord>('/hr/payroll/policies', payload);
  return data;
}

export async function approvePayrollPolicy(policyId: string) {
  const { data } = await apiClient.post<PayrollPolicyRecord>(
    `/hr/payroll/policies/${policyId}/approve`
  );
  return data;
}

export async function listPayrollPeriods() {
  const { data } =
    await apiClient.get<HrSchemas['PayrollPeriodListResponse']>('/hr/payroll/periods');
  return data;
}

export async function createPayrollPeriod(payload: HrSchemas['PayrollPeriodCreateRequest']) {
  const { data } = await apiClient.post<PayrollPeriodRecord>('/hr/payroll/periods', payload);
  return data;
}

export async function listPayrollRuns() {
  const { data } = await apiClient.get<HrSchemas['PayrollRunListResponse']>('/hr/payroll/runs');
  return data;
}

export async function createPayrollRun(payload: HrSchemas['PayrollRunCreateRequest']) {
  const { data } = await apiClient.post<PayrollRunRecord>('/hr/payroll/runs', payload);
  return data;
}

export async function calculatePayrollRun(runId: string) {
  const { data } = await apiClient.post<PayrollRunRecord>(`/hr/payroll/runs/${runId}/calculate`);
  return data;
}

export async function approvePayrollRun(runId: string) {
  const { data } = await apiClient.post<PayrollRunRecord>(`/hr/payroll/runs/${runId}/approve`);
  return data;
}

export async function listHrCases() {
  const { data } = await apiClient.get<HrSchemas['HrCaseListResponse']>('/hr/cases');
  return data;
}

export async function createHrCase(payload: HrSchemas['HrCaseCreateRequest']) {
  const { data } = await apiClient.post<HrCaseRecord>('/hr/cases', payload);
  return data;
}

// --- Self-Service (/hr/me) ---

export async function getMyHrProfile() {
  const { data } = await apiClient.get<EmployeeSelfRecord>('/hr/me');
  return data;
}

export async function updateMyHrProfile(payload: HrSchemas['EmployeeSelfUpdateRequest']) {
  const { data } = await apiClient.patch<EmployeeSelfRecord>('/hr/me', payload);
  return data;
}

export async function listMyLeaveTypes() {
  const { data } = await apiClient.get<HrSchemas['LeaveTypeListResponse']>('/hr/me/leave-types');
  return data;
}

export async function setEmployeeManagerReview(
  id: string,
  payload: HrSchemas['EmployeeManagerReviewRequest']
) {
  const { data } = await apiClient.put<EmployeeDetailRecord>(
    `/hr/employees/${id}/manager-review`,
    payload
  );
  return data;
}

export async function getMyHrWorkflowOptions(signal?: AbortSignal) {
  const { data } = await apiClient.get<HrSchemas['HrWorkflowOptionsResponse']>(
    '/hr/me/workflow-options',
    { signal }
  );
  return data;
}

export async function listMyManagerReviews(offset: number, limit: number, signal?: AbortSignal) {
  const { data } = await apiClient.get<HrSchemas['ManagerReviewListResponse']>(
    '/hr/me/manager-reviews',
    {
      params: { offset, limit },
      signal
    }
  );
  return data;
}

export async function recommendMyDirectReport(
  item: ManagerReviewItem,
  recommendation: HrSchemas['ManagerReviewDecisionRequest']['recommendation']
) {
  const { data } = await apiClient.post<ManagerReviewItem>(
    `/hr/me/manager-reviews/${item.kind}/${item.id}`,
    {
      recommendation,
      expected_revision: item.record_revision
    }
  );
  return data;
}

export async function getMyTimeRecords(signal?: AbortSignal) {
  const [timesheets, overtime] = await Promise.all([
    apiClient.get<HrSchemas['TimesheetListResponse']>('/hr/me/timesheets', { signal }),
    apiClient.get<HrSchemas['OvertimeRequestListResponse']>('/hr/me/overtime', { signal })
  ]);
  return { timesheets: timesheets.data.items, overtime: overtime.data.items };
}

export async function submitMyTimesheet(payload: HrSchemas['TimesheetSelfCreateRequest']) {
  const { data } = await apiClient.post<TimesheetRecord>('/hr/me/timesheets', payload);
  return data;
}

export async function resubmitMyTimesheet(
  id: string,
  payload: HrSchemas['TimesheetSelfResubmitRequest']
) {
  const { data } = await apiClient.put<TimesheetRecord>(
    `/hr/me/timesheets/${id}/submission`,
    payload
  );
  return data;
}

export async function submitMyOvertime(payload: HrSchemas['OvertimeSelfCreateRequest']) {
  const { data } = await apiClient.post<OvertimeRequestRecord>('/hr/me/overtime', payload);
  return data;
}

export async function getMyLeaveBalances() {
  const { data } =
    await apiClient.get<HrSchemas['LeaveBalanceListResponse']>('/hr/me/leave-balances');
  return data;
}

export async function listMyLeaveRequests() {
  const { data } =
    await apiClient.get<HrSchemas['LeaveRequestListResponse']>('/hr/me/leave-requests');
  return data;
}

export async function submitMyLeaveRequest(payload: HrSchemas['LeaveRequestCreateRequest']) {
  const { data } = await apiClient.post<LeaveRequestRecord>('/hr/me/leave-requests', payload);
  return data;
}

export async function cancelMyLeaveRequest(id: string) {
  const { data } = await apiClient.post<LeaveRequestRecord>(`/hr/me/leave-requests/${id}/cancel`);
  return data;
}

export async function listMyAttendance() {
  const { data } =
    await apiClient.get<HrSchemas['AttendanceEntryListResponse']>('/hr/me/attendance');
  return data;
}

export async function requestMyAttendanceCorrection(
  payload: HrSchemas['AttendanceCorrectionSelfRequest']
) {
  const { data } = await apiClient.post<HrSchemas['AttendanceCorrectionResponse']>(
    '/hr/me/attendance/corrections',
    payload
  );
  return data;
}

export async function listMyHrDocuments() {
  const { data } = await apiClient.get<HrSchemas['HrDocumentListResponse']>('/hr/me/documents');
  return data;
}

export async function downloadMyHrDocument(documentId: string) {
  const { data } = await apiClient.get<HrDocumentDownloadRecord>(
    `/hr/me/documents/${documentId}/download`
  );
  return data;
}

export async function listMyPolicies() {
  const { data } = await apiClient.get<HrSchemas['PolicyDocumentListResponse']>('/hr/me/policies');
  return data;
}

export async function acknowledgeMyPolicy(policyId: string, notes?: string) {
  const { data } = await apiClient.post<HrSchemas['PolicyAcknowledgementResponse']>(
    `/hr/me/policies/${policyId}/acknowledge`,
    { notes }
  );
  return data;
}

export async function listMyServiceRequests() {
  const { data } =
    await apiClient.get<HrSchemas['HrServiceRequestListResponse']>('/hr/me/requests');
  return data;
}

export async function submitMyServiceRequest(payload: HrSchemas['HrServiceRequestCreateRequest']) {
  const { data } = await apiClient.post<HrServiceRequestRecord>('/hr/me/requests', payload);
  return data;
}

export async function listMyReimbursements() {
  const { data } =
    await apiClient.get<HrSchemas['ReimbursementListResponse']>('/hr/me/reimbursements');
  return data;
}

export async function submitMyReimbursement(payload: HrSchemas['ReimbursementCreateRequest']) {
  const { data } = await apiClient.post<ReimbursementRecord>('/hr/me/reimbursements', payload);
  return data;
}
