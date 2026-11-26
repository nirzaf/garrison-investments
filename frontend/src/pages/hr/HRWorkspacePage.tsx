import { Link } from 'react-router-dom';
import { useQuery, useQueryClient } from '@tanstack/react-query';
import { ChangeEvent, FormEvent, useCallback, useEffect, useRef, useState } from 'react';

import {
  applyHrWorkbook,
  createDepartment,
  createEmployee,
  createLeaveType,
  adjustLeaveLedger,
  createPosition,
  createRequisition,
  decideLeaveRequest,
  routeLeaveRequestToHrFallback,
  refreshLeaveRequestRoute,
  decideHrDocumentVersion,
  uploadHrDocumentVersion,
  updateEmployee,
  getEmployee,
  getOrgChart,
  getEmployeeHistory,
  getEmployeePrivate,
  getHrDocumentDownloadUrl,
  hrServiceRequestTypes,
  listAccessRequests,
  listDepartments,
  listEmployees,
  listExpiringCompliance,
  listHrDocuments,
  listLeaveRequests,
  listLeaveTypes,
  listOffboardingCases,
  listPolicies,
  listPositions,
  listRequisitions,
  listServiceRequestAssignees,
  listServiceRequests,
  previewHrWorkbook,
  resolveServiceRequest,
  setEmployeeManagerReview,
  transitionEmployeeStatus,
  uploadHrDocument,
  upsertEmployeePrivate,
  type AccessRequestRecord,
  type OrgChartNode,
  type EmploymentHistoryRecord,
  type DepartmentRecord,
  type EmployeeDetailRecord,
  type EmployeeDirectoryRecord,
  type EmployeeSensitiveRecord,
  type ExpiringComplianceResponse,
  type HrDocumentRecord,
  type HrServiceRequestType,
  type HrSchemas,
  type LeaveTypeRecord,
  type OffboardingCaseRecord,
  type PolicyDocumentRecord,
  type PositionRecord,
  type RequisitionRecord,
  type WorkbookApplyResponse,
  type WorkbookPreviewResponse
} from '../../api/hr';
import { formatApiError as errMsg } from '../../api/errors';
import { HRAccessForms, hrInputClass } from './HRAccessForms';
import { HROffboarding } from './HROffboarding';
import { HRTraining } from './HRTraining';
import { HRPerformanceReviews, HRPerformanceSetup } from './HRPerformanceReviews';
import { HRDirectorOffboarding } from './HROffboardingCustody';
import { HRSummaryPanel } from './HRSummaryPanel';
import { HRTimePanel } from './HRTimePanel';
import { HRLeavePolicies } from './HRLeavePolicies';
import { HRLeaveDateEvidence } from './HRLeaveDateEvidence';
import { HRLeaveAccrual } from './HRLeaveAccrual';
import { HRLeaveBaseline } from './HRLeaveBaseline';
import { HRLeaveRollover } from './HRLeaveRollover';
import { HRHiringPanel } from './HRHiringPanel';
import { HREmploymentChanges } from './HREmploymentChanges';
import { HRDueEmploymentChanges } from './HRDueEmploymentChanges';
import { HRLettersPanel } from './HRLettersPanel';
import { HRPolicyPublication } from './HRPolicyPublication';
import { HRIssuedLetterPicker, HRResponseLetter } from './HRResponseLetter';
import { HRServiceRequestAssignment } from './HRServiceRequestAssignment';
import { HRProjectAssignments } from './HRProjectAssignments';
import { HRCompensation } from './HRCompensation';
import { HRAdvances } from './HRAdvances';
import { HRBenefits } from './HRBenefits';
import { HRReimbursements } from './HRReimbursements';
import { HRPayroll } from './HRPayroll';
import { StatusBadge } from '../../components/shared/StatusBadge';
import { useAuth } from '../../context/useAuth';

type HrTab =
  | 'overview'
  | 'directory'
  | 'access'
  | 'recruitment'
  | 'documents'
  | 'attendance'
  | 'leave'
  | 'operations'
  | 'training'
  | 'payroll'
  | 'performance';

const LEAVE_PAGE_SIZE = 25;
const LEAVE_REQUESTS_KEY = ['hr', 'leave-requests'];
const SERVICE_REQUEST_PAGE_SIZE = 25;
const SERVICE_REQUESTS_KEY = ['hr', 'service-requests'];
type CoreResource =
  | 'departments'
  | 'positions'
  | 'employees'
  | 'accessRequests'
  | 'compliance'
  | 'requisitions'
  | 'documents'
  | 'leaveTypes'
  | 'policies'
  | 'offboarding';

const coreResourceLabels: Record<CoreResource, string> = {
  departments: 'Departments',
  positions: 'Positions',
  employees: 'Employee directory',
  accessRequests: 'Access requests',
  compliance: 'Compliance records',
  requisitions: 'Recruitment requisitions',
  documents: 'HR documents',
  leaveTypes: 'Leave types',
  policies: 'HR policies',
  offboarding: 'Offboarding cases'
};

function OrgBranch({ node }: { node: OrgChartNode }) {
  return (
    <li className="space-y-1">
      <p>
        {node.full_name} · {node.position_title ?? 'Unassigned position'} ·{' '}
        {node.department_name ?? 'Unassigned department'}
        {node.work_location && ` · ${node.work_location}`}
        {node.primary_assignment === 'active' && ' · Active primary project membership'}
        {node.primary_assignment === 'inactive' && ' · No active primary project membership'}
      </p>
      {node.direct_reports?.length ? (
        <ul className="ml-4 border-l border-theme-border pl-3">
          {node.direct_reports.map((child) => (
            <OrgBranch node={child} key={child.employee_id} />
          ))}
        </ul>
      ) : null}
    </li>
  );
}

export function HRWorkspacePage() {
  const { user } = useAuth();
  const queryClient = useQueryClient();
  const perms = user?.permissions ?? [];
  const hasPerm = (p: string) => perms.includes(p);

  const [tab, setTab] = useState<HrTab>(hasPerm('hr:employees:read') ? 'overview' : 'access');
  const [notice, setNotice] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [coreLoading, setCoreLoading] = useState<Partial<Record<CoreResource, boolean>>>({});
  const [coreErrors, setCoreErrors] = useState<Partial<Record<CoreResource, string>>>({});

  const [departments, setDepartments] = useState<DepartmentRecord[]>([]);
  const [positions, setPositions] = useState<PositionRecord[]>([]);
  const [employees, setEmployees] = useState<EmployeeDirectoryRecord[]>([]);
  const [selectedEmp, setSelectedEmp] = useState<EmployeeDetailRecord | null>(null);
  const [orgRoots, setOrgRoots] = useState<OrgChartNode[] | null>(null);
  const [employmentHistory, setEmploymentHistory] = useState<EmploymentHistoryRecord[] | null>(
    null
  );
  const [privateVault, setPrivateVault] = useState<EmployeeSensitiveRecord | null>(null);
  const selectedVault = privateVault?.employee_id === selectedEmp?.id ? privateVault : null;
  const [vaultPending, setVaultPending] = useState(false);
  const employeeSelection = useRef(0);

  const [accessRequests, setAccessRequests] = useState<AccessRequestRecord[]>([]);
  const [wbFile, setWbFile] = useState<File | null>(null);
  const [wbOverrides, setWbOverrides] = useState('{}');
  const [wbPreview, setWbPreview] = useState<WorkbookPreviewResponse | null>(null);
  const [wbApplyResult, setWbApplyResult] = useState<WorkbookApplyResponse | null>(null);
  const [wbPending, setWbPending] = useState(false);

  const [requisitions, setRequisitions] = useState<RequisitionRecord[]>([]);
  const [documents, setDocuments] = useState<HrDocumentRecord[]>([]);
  const [compliance, setCompliance] = useState<ExpiringComplianceResponse | null>(null);
  const [leaveTypes, setLeaveTypes] = useState<LeaveTypeRecord[]>([]);
  const [leaveStatus, setLeaveStatus] = useState('');
  const [leaveOffset, setLeaveOffset] = useState(0);
  const leaveQueue = useQuery({
    queryKey: [...LEAVE_REQUESTS_KEY, user?.id, leaveStatus, leaveOffset],
    queryFn: ({ signal }) => listLeaveRequests({
      limit: LEAVE_PAGE_SIZE, offset: leaveOffset, req_status: leaveStatus || undefined
    }, signal),
    enabled: tab === 'leave' && hasPerm('hr:leave:manage'),
    gcTime: 0
  });
  const [policies, setPolicies] = useState<PolicyDocumentRecord[]>([]);
  const [requestStatus, setRequestStatus] = useState('');
  const [requestOffset, setRequestOffset] = useState(0);
  const canLoadServiceRequests = tab === 'operations' && hasPerm('hr:requests:process');
  const requestQueue = useQuery({
    queryKey: [...SERVICE_REQUESTS_KEY, user?.id, requestStatus, requestOffset],
    queryFn: ({ signal }) => listServiceRequests({
      limit: SERVICE_REQUEST_PAGE_SIZE,
      offset: requestOffset,
      req_status: requestStatus || undefined
    }, signal),
    enabled: canLoadServiceRequests,
    gcTime: 0
  });
  const assignees = useQuery({
    queryKey: ['hr', 'service-request-assignees', user?.id],
    queryFn: ({ signal }) => listServiceRequestAssignees(signal),
    enabled: canLoadServiceRequests,
    gcTime: 0
  });
  const requestAssignees = assignees.data ?? [];
  const [requestLetters, setRequestLetters] = useState<Record<string, string>>({});
  const [requestResponses, setRequestResponses] = useState<Record<string, string>>({});
  const [offboarding, setOffboarding] = useState<OffboardingCaseRecord[]>([]);

  // Forms
  const [deptCode, setDeptCode] = useState('');
  const [deptName, setDeptName] = useState('');
  const [posCode, setPosCode] = useState('');
  const [posTitle, setPosTitle] = useState('');
  const [empCode, setEmpCode] = useState('');
  const [empFirst, setEmpFirst] = useState('');
  const [empLast, setEmpLast] = useState('');
  const [empEmail, setEmpEmail] = useState('');
  const [employmentCategory, setEmploymentCategory] =
    useState<Parameters<typeof createEmployee>[0]['employment_category']>('permanent');
  const [empPhone, setEmpPhone] = useState('');
  const [employeeSearch, setEmployeeSearch] = useState('');
  const [employeeOffset, setEmployeeOffset] = useState(0);
  const [employeeTotal, setEmployeeTotal] = useState(0);
  const [pending, setPending] = useState(false);
  const [docDecisionNotes, setDocDecisionNotes] = useState<Record<string, string>>({});
  const [leaveDecisionNotes, setLeaveDecisionNotes] = useState<Record<string, string>>({});

  const [vaultNationalId, setVaultNationalId] = useState('');

  const [reqCode, setReqCode] = useState('');
  const [reqTitle, setReqTitle] = useState('');
  const [reqHeadcount, setReqHeadcount] = useState('1');

  const [docTitle, setDocTitle] = useState('');
  const [uploadCompanyPolicy, setUploadCompanyPolicy] = useState(false);
  const [docCategory, setDocCategory] = useState<
    'ordinary' | 'confidential' | 'medical' | 'compensation' | 'disciplinary'
  >('ordinary');
  const [shareDocument, setShareDocument] = useState(false);
  const [docFile, setDocFile] = useState<File | null>(null);

  const [ltCode, setLtCode] = useState('');
  const [ltName, setLtName] = useState('');

  const loadCore = useCallback(async () => {
    const load = async <T,>(
      resource: CoreResource,
      request: () => Promise<T>,
      accept: (result: T) => void
    ) => {
      setCoreLoading((current) => ({ ...current, [resource]: true }));
      setCoreErrors((current) => ({ ...current, [resource]: undefined }));
      try {
        accept(await request());
      } catch (failure) {
        setCoreErrors((current) => ({
          ...current,
          [resource]: errMsg(
            failure,
            `Unable to load ${coreResourceLabels[resource].toLowerCase()}.`
          )
        }));
      } finally {
        setCoreLoading((current) => ({ ...current, [resource]: false }));
      }
    };

    const requests: Promise<void>[] = [];
    if (hasPerm('hr:employees:read')) {
      requests.push(
        load('departments', listDepartments, (result) => setDepartments(result.items)),
        load('positions', listPositions, (result) => setPositions(result.items)),
        load(
          'employees',
          () => listEmployees({
            search: employeeSearch || undefined,
            offset: employeeOffset,
            limit: 50
          }),
          (result) => {
            setEmployees(result.items);
            setEmployeeTotal(result.total);
          }
        )
      );
    }
    if (hasPerm('hr:employees:read') || hasPerm('users:manage')) {
      requests.push(load('accessRequests', listAccessRequests, (result) => setAccessRequests(result.items)));
    }
    if (hasPerm('hr:compliance:manage')) {
      requests.push(load('compliance', () => listExpiringCompliance(60), setCompliance));
    }
    if (hasPerm('hr:recruitment:manage')) {
      requests.push(load('requisitions', listRequisitions, (result) => setRequisitions(result.items)));
    }
    if (hasPerm('hr:documents:manage')) {
      requests.push(load('documents', listHrDocuments, (result) => setDocuments(result.items)));
    }
    if (hasPerm('hr:leave:manage')) {
      requests.push(load('leaveTypes', listLeaveTypes, (result) => setLeaveTypes(result.items)));
    }
    if (hasPerm('hr:employees:read')) {
      requests.push(load('policies', listPolicies, (result) => setPolicies(result.items)));
    }
    if (hasPerm('hr:offboarding:manage')) {
      requests.push(load('offboarding', listOffboardingCases, (result) => setOffboarding(result.items)));
    }
    await Promise.all(requests);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [perms.join('|'), user?.role, employeeSearch, employeeOffset]);

  useEffect(() => {
    void loadCore();
  }, [loadCore]);

  async function selectEmployee(empId: string) {
    const selection = ++employeeSelection.current;
    setError(null);
    setVaultPending(false);
    setPrivateVault(null);
    setEmploymentHistory(null);
    setVaultNationalId('');
    setSelectedEmp(null);
    try {
      const detail = await getEmployee(empId);
      if (selection !== employeeSelection.current) return;
      setSelectedEmp(detail);
      if (hasPerm('hr:employees:sensitive')) {
        const vault = await getEmployeePrivate(empId, false);
        if (selection === employeeSelection.current) setPrivateVault(vault);
      }
    } catch (err) {
      if (selection === employeeSelection.current)
        setError(errMsg(err, 'Unable to load employee detail.'));
    }
  }

  async function handleCreateDept(e: FormEvent) {
    e.preventDefault();
    setError(null);
    setNotice(null);
    try {
      await createDepartment({ code: deptCode, name: deptName });
      setDeptCode('');
      setDeptName('');
      setNotice('Department created.');
      await loadCore();
    } catch (err) {
      setError(errMsg(err, 'Failed to create department.'));
    }
  }

  async function handleCreatePos(e: FormEvent) {
    e.preventDefault();
    setError(null);
    setNotice(null);
    try {
      await createPosition({
        code: posCode,
        title: posTitle,
        employment_category: 'permanent',
        headcount_limit: 1,
        approved_count: 1
      });
      setPosCode('');
      setPosTitle('');
      setNotice('Position created.');
      await loadCore();
    } catch (err) {
      setError(errMsg(err, 'Failed to create position.'));
    }
  }

  async function handleCreateEmployee(e: FormEvent) {
    e.preventDefault();
    setError(null);
    setNotice(null);
    try {
      const created = await createEmployee({
        employee_code: empCode,
        first_name: empFirst,
        last_name: empLast,
        work_email: empEmail || null,
        work_phone: empPhone || null,
        employment_status: 'draft',
        employment_category: employmentCategory,
        override_headcount: false
      });
      setEmpCode('');
      setEmpFirst('');
      setEmpLast('');
      setEmpEmail('');
      setEmpPhone('');
      ++employeeSelection.current;
      setVaultPending(false);
      setPrivateVault(null);
      setSelectedEmp(created);
      setNotice(`Employee ${created.employee_code} created.`);
      await loadCore();
    } catch (err) {
      setError(errMsg(err, 'Failed to create employee.'));
    }
  }

  async function handleSavePrivateVault(e: FormEvent) {
    e.preventDefault();
    if (!selectedEmp || vaultPending || !vaultNationalId.trim() || !selectedVault) return;
    const selection = employeeSelection.current;
    setVaultPending(true);
    setError(null);
    setNotice(null);
    try {
      const updated = await upsertEmployeePrivate(selectedEmp.id, {
        expected_revision: selectedVault.record_revision,
        national_id: vaultNationalId
      });
      if (selection !== employeeSelection.current) return;
      setPrivateVault(updated);
      setVaultNationalId('');
      setNotice('Encrypted private vault updated.');
      const detail = await getEmployee(selectedEmp.id);
      if (selection === employeeSelection.current) setSelectedEmp(detail);
    } catch (err) {
      if (selection === employeeSelection.current)
        setError(errMsg(err, 'Could not save or reload the private vault.'));
    } finally {
      if (selection === employeeSelection.current) setVaultPending(false);
    }
  }

  async function reloadPrivateVault(reveal: boolean) {
    if (!selectedEmp || vaultPending) return;
    const selection = employeeSelection.current;
    setVaultPending(true);
    setError(null);
    try {
      const vault = await getEmployeePrivate(selectedEmp.id, reveal);
      if (selection === employeeSelection.current) setPrivateVault(vault);
    } catch (err) {
      if (selection === employeeSelection.current)
        setError(errMsg(err, 'Could not reload the private vault.'));
    } finally {
      if (selection === employeeSelection.current) setVaultPending(false);
    }
  }

  async function handleWorkbookPreview(e: FormEvent) {
    e.preventDefault();
    if (!wbFile || wbPending) return;
    setWbPending(true);
    setError(null);
    setNotice(null);
    setWbPreview(null);
    setWbApplyResult(null);
    try {
      const parsed = JSON.parse(wbOverrides || '{}') as Record<string, string>;
      setWbPreview(await previewHrWorkbook(wbFile, parsed));
    } catch (err) {
      setError(errMsg(err, 'Workbook preview failed. Ensure valid CSV/XLSX and JSON overrides.'));
    } finally {
      setWbPending(false);
    }
  }

  async function handleWorkbookApply() {
    if (!wbPreview || wbPending) return;
    setWbPending(true);
    setError(null);
    setNotice(null);
    try {
      const parsed = JSON.parse(wbOverrides || '{}') as Record<string, string>;
      const res = await applyHrWorkbook({
        rows: wbPreview.rows.map((r) => ({
          user_name: r.user_name,
          email_source: r.email_source,
          portal_access_required: r.portal_access_required_raw,
          role_to_assign: r.role_source,
          role_description_auto: r.role_description_auto,
          privileges_auto: r.privileges_auto,
          access_scope_auto: r.access_scope_auto
        })),
        explicit_role_overrides: parsed,
        allow_missing_email_draft: true,
        create_access_requests: true
      });
      setWbApplyResult(res);
      setNotice(
        `Applied workbook: ${res.employees_created} created, ${res.access_requests_created} access requests queued.`
      );
      await loadCore();
    } catch (err) {
      setError(errMsg(err, 'Workbook apply failed.'));
    } finally {
      setWbPending(false);
    }
  }

  async function handleUploadHrDoc(e: FormEvent) {
    e.preventDefault();
    if (!docFile) return;
    setError(null);
    setNotice(null);
    try {
      await uploadHrDocument({
        file: docFile,
        title: docTitle,
        document_type: uploadCompanyPolicy ? 'policy' : 'contract',
        category: uploadCompanyPolicy ? 'ordinary' : docCategory,
        employee_id: uploadCompanyPolicy ? undefined : selectedEmp?.id,
        is_employee_visible:
          !uploadCompanyPolicy &&
          shareDocument &&
          docCategory === 'ordinary' &&
          Boolean(selectedEmp)
      });
      setDocTitle('');
      setDocFile(null);
      setNotice('HR document uploaded.');
      await loadCore();
    } catch (err) {
      setError(errMsg(err, 'Document upload failed.'));
    }
  }

  async function runChange(action: () => Promise<unknown>, fallback: string, reload = true) {
    if (pending) return;
    setPending(true);
    setError(null);
    try {
      await action();
      if (reload) await loadCore();
    } catch (error) {
      setError(errMsg(error, fallback));
    } finally {
      setPending(false);
    }
  }

  async function runLeaveDecision(
    requestId: string, payload: HrSchemas['LeaveRequestDecisionRequest'], fallback: string
  ) {
    await runChange(async () => {
      await decideLeaveRequest(requestId, payload);
      await queryClient.invalidateQueries({ queryKey: LEAVE_REQUESTS_KEY });
    }, fallback, false);
  }

  async function runLeaveFallback(
    requestId: string,
    payload: HrSchemas['LeaveFallbackRequest'],
    fallback: string
  ) {
    await runChange(async () => {
      await routeLeaveRequestToHrFallback(requestId, payload);
      await queryClient.invalidateQueries({ queryKey: LEAVE_REQUESTS_KEY });
    }, fallback, false);
  }

  async function runLeaveRouteRefresh(requestId: string, expectedRevision: number) {
    await runChange(async () => {
      await refreshLeaveRequestRoute(requestId, expectedRevision);
      await queryClient.invalidateQueries({ queryKey: LEAVE_REQUESTS_KEY });
    }, 'Could not refresh the leave review assignment.', false);
  }

  async function runServiceRequestChange(action: () => Promise<unknown>, fallback: string) {
    await runChange(async () => {
      await action();
      await queryClient.invalidateQueries({ queryKey: SERVICE_REQUESTS_KEY });
    }, fallback, false);
  }

  const tabs: { key: HrTab; label: string; visible: boolean }[] = [
    { key: 'overview', label: 'Overview', visible: hasPerm('hr:reports:view') },
    { key: 'directory', label: 'Directory & Org', visible: hasPerm('hr:employees:read') },
    {
      key: 'access',
      label: 'Access & Workbook',
      visible: hasPerm('hr:employees:read') || hasPerm('users:manage')
    },
    { key: 'recruitment', label: 'Recruitment', visible: hasPerm('hr:recruitment:manage') },
    { key: 'documents', label: 'Docs & Compliance', visible: hasPerm('hr:documents:manage') },
    { key: 'attendance', label: 'Attendance', visible: hasPerm('hr:attendance:record') },
    { key: 'leave', label: 'Leave', visible: hasPerm('hr:leave:manage') },
    { key: 'training', label: 'Training', visible: hasPerm('hr:training:manage') },
    { key: 'performance', label: 'Performance', visible: hasPerm('hr:performance:manage') },
    {
      key: 'payroll', label: 'Payroll',
      visible: hasPerm('hr:payroll:prepare') || hasPerm('hr:payroll:sensitive') || hasPerm('hr:payroll:approve')
    },
    {
      key: 'operations',
      label: 'Policies & Requests',
      visible: hasPerm('hr:policy:manage') || hasPerm('hr:requests:process')
    }
  ];

  return (
    <div className="space-y-6">
      <div className="flex flex-wrap items-end justify-between gap-4">
        <div>
          <p className="text-sm font-medium text-brand-600">Human Resources</p>
          <h2 className="text-2xl font-semibold text-theme-text-primary">HR & Workforce Hub</h2>
          <p className="text-sm text-theme-text-muted">
            Manage workforce records and access requests.
          </p>
        </div>
        <button
          className="rounded-md border border-theme-border bg-theme-card px-3 py-1.5 text-sm font-medium text-theme-text-primary hover:bg-theme-card-elevated"
          onClick={() => {
            void loadCore();
            void queryClient.invalidateQueries({ queryKey: ['hr', 'report-summary'] });
          }}
          type="button"
        >
          Refresh
        </button>
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
      {Object.values(coreLoading).some(Boolean) && (
        <p role="status" className="text-sm text-theme-text-muted">
          Loading HR workspace data…
        </p>
      )}
      {Object.entries(coreErrors).map(([resource, message]) =>
        message ? (
          <div
            key={resource}
            role="alert"
            className="flex flex-wrap items-center gap-2 rounded-md border border-[var(--status-error-border)] bg-[var(--status-error-bg)] px-4 py-2 text-sm text-[var(--status-error-text)]"
          >
            <span>
              {coreResourceLabels[resource as CoreResource]}: {message}
            </span>
            <button
              className="font-semibold underline"
              type="button"
              onClick={() => void loadCore()}
            >
              Retry HR data
            </button>
          </div>
        ) : null
      )}

      <div className="flex flex-wrap gap-2 border-b border-theme-border pb-3">
        {tabs
          .filter((t) => t.visible)
          .map((t) => (
            <button
              className={`rounded-md px-3 py-1.5 text-sm font-medium ${
                tab === t.key
                  ? 'bg-brand-600 text-white'
                  : 'border border-theme-border bg-theme-card text-theme-text-secondary hover:bg-theme-card-elevated'
              }`}
              key={t.key}
              onClick={() => setTab(t.key)}
              type="button"
            >
              {t.label}
            </button>
          ))}
      </div>

      {tab === 'overview' && hasPerm('hr:reports:view') && (
        <HRSummaryPanel departments={departments} />
      )}
      {tab === 'payroll' && user && (hasPerm('hr:payroll:prepare') || hasPerm('hr:payroll:sensitive') || hasPerm('hr:payroll:approve')) && (
        <HRPayroll
          key={user.id}
          actorId={user.id}
          canPrepare={hasPerm('hr:payroll:prepare')}
          canRead={hasPerm('hr:payroll:sensitive')}
          canApprove={hasPerm('hr:payroll:approve')}
        />
      )}

      {tab === 'directory' && (
        <div className="space-y-6">
          {user && hasPerm('hr:employees:sensitive') && (
            <HRDueEmploymentChanges key={user.id} actorId={user.id} inspectEmployee={selectEmployee} />
          )}
          {hasPerm('hr:employees:manage') && (
            <div className="grid gap-4 lg:grid-cols-3">
              <form
                className="rounded-lg border border-theme-border bg-theme-card p-4 space-y-2"
                onSubmit={(e) => void handleCreateDept(e)}
              >
                <h3 className="text-sm font-semibold">New Department</h3>
                <input
                  className="w-full rounded border border-theme-border bg-theme-input px-2.5 py-1.5 text-sm"
                  onChange={(e) => setDeptCode(e.target.value)}
                  placeholder="Code (e.g. ENG)"
                  required
                  value={deptCode}
                />
                <input
                  className="w-full rounded border border-theme-border bg-theme-input px-2.5 py-1.5 text-sm"
                  onChange={(e) => setDeptName(e.target.value)}
                  placeholder="Department Name"
                  required
                  value={deptName}
                />
                <button
                  className="rounded bg-brand-600 px-3 py-1.5 text-xs font-semibold text-white"
                  type="submit"
                >
                  Add department
                </button>
              </form>

              <form
                className="rounded-lg border border-theme-border bg-theme-card p-4 space-y-2"
                onSubmit={(e) => void handleCreatePos(e)}
              >
                <h3 className="text-sm font-semibold">New Position</h3>
                <input
                  className="w-full rounded border border-theme-border bg-theme-input px-2.5 py-1.5 text-sm"
                  onChange={(e) => setPosCode(e.target.value)}
                  placeholder="Code (e.g. QS-L1)"
                  required
                  value={posCode}
                />
                <input
                  className="w-full rounded border border-theme-border bg-theme-input px-2.5 py-1.5 text-sm"
                  onChange={(e) => setPosTitle(e.target.value)}
                  placeholder="Position Title"
                  required
                  value={posTitle}
                />
                <button
                  className="rounded bg-brand-600 px-3 py-1.5 text-xs font-semibold text-white"
                  type="submit"
                >
                  Add position
                </button>
              </form>

              <form
                className="rounded-lg border border-theme-border bg-theme-card p-4 space-y-2"
                onSubmit={(e) => void handleCreateEmployee(e)}
              >
                <h3 className="text-sm font-semibold">New Employee</h3>
                <div className="grid grid-cols-2 gap-2">
                  <input
                    className="rounded border border-theme-border bg-theme-input px-2 py-1.5 text-sm"
                    onChange={(e) => setEmpCode(e.target.value)}
                    aria-label="Employee code"
                    placeholder="Emp Code"
                    required
                    value={empCode}
                  />
                  <input
                    className="rounded border border-theme-border bg-theme-input px-2 py-1.5 text-sm"
                    onChange={(e) => setEmpEmail(e.target.value)}
                    aria-label="Work email"
                    placeholder="Work email"
                    type="email"
                    value={empEmail}
                  />
                  <input
                    className="rounded border border-theme-border bg-theme-input px-2 py-1.5 text-sm"
                    onChange={(e) => setEmpFirst(e.target.value)}
                    aria-label="First name"
                    placeholder="First name"
                    required
                    value={empFirst}
                  />
                  <input
                    className="rounded border border-theme-border bg-theme-input px-2 py-1.5 text-sm"
                    onChange={(e) => setEmpLast(e.target.value)}
                    aria-label="Last name"
                    placeholder="Last name"
                    required
                    value={empLast}
                  />
                </div>
                <label className="block text-sm">
                  Employment category
                  <select
                    value={employmentCategory}
                    aria-label="Employment category"
                    onChange={(event) =>
                      setEmploymentCategory(event.target.value as typeof employmentCategory)
                    }
                    className="w-full rounded border border-theme-border bg-theme-input px-2 py-1.5"
                  >
                    <option value="permanent">Permanent</option>
                    <option value="contract">Contract</option>
                    <option value="probation">Probation</option>
                    <option value="daily_wage">Daily wage</option>
                    <option value="intern">Intern</option>
                    <option value="consultant">Consultant</option>
                  </select>
                </label>
                <input
                  aria-label="Work phone"
                  placeholder="Work phone"
                  type="tel"
                  value={empPhone}
                  className="w-full rounded border border-theme-border bg-theme-input px-2 py-1.5"
                  onChange={(event) => setEmpPhone(event.target.value)}
                />
                <button
                  className="rounded bg-brand-600 px-3 py-1.5 text-xs font-semibold text-white"
                  type="submit"
                >
                  Create employee
                </button>
              </form>
            </div>
          )}

          <div className="grid gap-6 lg:grid-cols-3">
            <div className="lg:col-span-2 rounded-lg border border-theme-border bg-theme-card p-4">
              <h3 className="text-base font-semibold">
                Employee Directory ({employeeTotal}) · {departments.length} Depts ·{' '}
                {positions.length} Positions
              </h3>
              <details
                className="mt-2 text-sm"
                onToggle={(event) => {
                  if (event.currentTarget.open)
                    void runChange(
                      async () => setOrgRoots((await getOrgChart()).roots),
                      'Could not load organization chart.',
                      false
                    );
                }}
              >
                <summary>Organization chart</summary>
                {orgRoots?.length === 0 && <p>No reporting lines yet.</p>}
                <ul className="mt-2 space-y-2">
                  {orgRoots?.map((node) => (
                    <OrgBranch node={node} key={node.employee_id} />
                  ))}
                </ul>
              </details>
              <label className="mt-3 block text-sm">
                Search employees
                <input
                  className="ml-2 rounded border border-theme-border bg-theme-input px-2 py-1"
                  value={employeeSearch}
                  onChange={(event) => {
                    setEmployeeSearch(event.target.value);
                    setEmployeeOffset(0);
                  }}
                />
              </label>
              <div className="flex gap-3 py-2 text-sm">
                <button
                  type="button"
                  disabled={employeeOffset === 0}
                  onClick={() => setEmployeeOffset((offset) => Math.max(0, offset - 50))}
                >
                  Previous
                </button>
                <button
                  type="button"
                  disabled={employeeOffset + 50 >= employeeTotal}
                  onClick={() => setEmployeeOffset((offset) => offset + 50)}
                >
                  Next
                </button>
              </div>
              <div className="mt-3 overflow-x-auto">
                {coreLoading.employees && <p role="status">Loading employees…</p>}
                {!coreLoading.employees &&
                  !coreErrors.employees &&
                  employees.length === 0 && <p>No employees match this directory page.</p>}
                <table className="min-w-full text-left text-sm">
                  <thead className="border-b border-theme-border text-xs uppercase text-theme-text-muted">
                    <tr>
                      <th className="py-2 pr-3">Code</th>
                      <th className="py-2 pr-3">Name</th>
                      <th className="py-2 pr-3">Status</th>
                      <th className="py-2">Action</th>
                    </tr>
                  </thead>
                  <tbody className="divide-y divide-theme-border">
                    {employees.map((e) => (
                      <tr key={e.id}>
                        <td className="py-2 pr-3 font-mono text-xs">{e.employee_code}</td>
                        <td className="py-2 pr-3">
                          {e.full_name}
                          <div className="text-xs text-theme-text-muted">
                            {e.work_email || 'No work email'}
                          </div>
                        </td>
                        <td className="py-2 pr-3">
                          <StatusBadge tone="neutral">{e.employment_status}</StatusBadge>
                        </td>
                        <td className="py-2">
                          <button
                            className="text-xs font-semibold text-brand-600 hover:underline"
                            onClick={() => void selectEmployee(e.id)}
                            type="button"
                          >
                            Inspect
                          </button>
                        </td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            </div>

            <div className="rounded-lg border border-theme-border bg-theme-card p-4 space-y-4">
              <h3 className="text-base font-semibold">Selected Employee</h3>
              {hasPerm('hr:employees:manage') && (
                <HRProjectAssignments
                  key={selectedEmp?.id}
                  employeeId={selectedEmp?.user_id ? selectedEmp.id : undefined}
                />
              )}
              {!selectedEmp ? (
                <p className="text-sm text-theme-text-muted">Select an employee to inspect.</p>
              ) : (
                <div className="space-y-3 text-sm">
                  <p>
                    <strong>{selectedEmp.full_name}</strong> ({selectedEmp.employee_code})
                  </p>
                  <p className="text-xs text-theme-text-muted">
                    Status: {selectedEmp.employment_status} · Revision:{' '}
                    {selectedEmp.record_revision}
                  </p>
                  {user && hasPerm('hr:payroll:sensitive') && (
                    <>
                      <HRCompensation
                        key={`compensation:${user.id}:${selectedEmp.id}`}
                        employeeId={selectedEmp.id}
                        employeeUserId={selectedEmp.user_id}
                        actorId={user.id}
                        canReview={hasPerm('hr:payroll:approve')}
                      />
                      <HRAdvances
                        key={`advances:${user.id}:${selectedEmp.id}`}
                        employeeId={selectedEmp.id}
                        employeeUserId={selectedEmp.user_id}
                        actorId={user.id}
                        canReview={hasPerm('hr:payroll:approve')}
                      />
                      <HRBenefits
                        key={`benefits:${user.id}:${selectedEmp.id}`}
                        employeeId={selectedEmp.id}
                        actorId={user.id}
                        canReview={hasPerm('hr:payroll:approve')}
                      />
                      <HRReimbursements
                        key={`reimbursements:${user.id}:${selectedEmp.id}`}
                        employeeId={selectedEmp.id}
                        employeeUserId={selectedEmp.user_id}
                        actorId={user.id}
                        canReview={hasPerm('hr:payroll:approve')}
                        canManageReceipts={hasPerm('hr:documents:manage')}
                        canReviewReceipts={hasPerm('hr:employees:sensitive')}
                      />
                    </>
                  )}
                  {hasPerm('hr:employees:sensitive') && (
                    <HREmploymentChanges
                      key={selectedEmp.id}
                      employee={selectedEmp}
                      actorId={user?.id}
                      departments={departments}
                      positions={positions}
                      refreshEmployee={async () => {
                        const updated = await getEmployee(selectedEmp.id);
                        setSelectedEmp((current) =>
                          current?.id === updated.id ? updated : current
                        );
                        setEmploymentHistory(null);
                        await loadCore();
                      }}
                    />
                  )}
                  {hasPerm('hr:employees:manage') && (
                    <form
                      key={selectedEmp.id + selectedEmp.record_revision}
                      className="space-y-2"
                      onSubmit={(event) => {
                        event.preventDefault();
                        const form = new FormData(event.currentTarget);
                        void runChange(async () => {
                          const updated = await updateEmployee(selectedEmp.id, {
                            expected_revision: selectedEmp.record_revision,
                            override_headcount: false,
                            ...(form.has('code')
                              ? { employee_code: String(form.get('code')) }
                              : {}),
                            work_email: String(form.get('email') ?? '') || null,
                            work_phone: String(form.get('phone') ?? '') || null,
                            work_location: String(form.get('location') ?? '') || null,
                            department_id: String(form.get('department') ?? '') || null,
                            position_id: String(form.get('position') ?? '') || null,
                            manager_employee_id: String(form.get('manager') ?? '') || null
                          });
                          setSelectedEmp(updated);
                        }, 'Could not save employee.');
                      }}
                    >
                      {hasPerm('hr:employees:sensitive') &&
                        selectedEmp.employee_code.startsWith('DRAFT-') && (
                          <label className="block">
                            Verified employee code{' '}
                            <input
                              className="rounded border border-theme-border bg-theme-input"
                              name="code"
                              required
                            />
                          </label>
                        )}
                      <label className="block">
                        Work email{' '}
                        <input
                          className="rounded border border-theme-border bg-theme-input"
                          name="email"
                          type="email"
                          defaultValue={selectedEmp.work_email ?? ''}
                        />
                      </label>
                      <label className="block">
                        Work phone{' '}
                        <input
                          className="rounded border border-theme-border bg-theme-input"
                          name="phone"
                          type="tel"
                          defaultValue={selectedEmp.work_phone ?? ''}
                        />
                      </label>
                      <label className="block">
                        Work location{' '}
                        <input
                          className="rounded border border-theme-border bg-theme-input"
                          name="location"
                          defaultValue={selectedEmp.work_location ?? ''}
                        />
                      </label>
                      <label className="block">
                        Department{' '}
                        <select
                          name="department"
                          aria-label="Department"
                          defaultValue={selectedEmp.department_id ?? ''}
                        >
                          <option value="">None</option>
                          {selectedEmp.department_id &&
                            !departments.some((dept) => dept.id === selectedEmp.department_id) && (
                              <option value={selectedEmp.department_id}>
                                {selectedEmp.department_name ?? 'Current department'}
                              </option>
                            )}
                          {departments.map((dept) => (
                            <option key={dept.id} value={dept.id}>
                              {dept.name}
                            </option>
                          ))}
                        </select>
                        {coreLoading.departments && <span role="status">Loading departments…</span>}
                        {!coreLoading.departments &&
                          !coreErrors.departments &&
                          departments.length === 0 && <span>No departments are configured.</span>}
                        {coreErrors.departments && (
                          <span role="alert">
                            Department options failed to load.{' '}
                            <button className="underline" type="button" onClick={() => void loadCore()}>
                              Retry
                            </button>
                          </span>
                        )}
                      </label>
                      <label className="block">
                        Position{' '}
                        <select
                          name="position"
                          aria-label="Position"
                          defaultValue={selectedEmp.position_id ?? ''}
                        >
                          <option value="">None</option>
                          {selectedEmp.position_id &&
                            !positions.some((position) => position.id === selectedEmp.position_id) && (
                              <option value={selectedEmp.position_id}>
                                {selectedEmp.position_title ?? 'Current position'}
                              </option>
                            )}
                          {positions.map((position) => (
                            <option key={position.id} value={position.id}>
                              {position.title}
                            </option>
                          ))}
                        </select>
                        {coreLoading.positions && <span role="status">Loading positions…</span>}
                        {!coreLoading.positions &&
                          !coreErrors.positions &&
                          positions.length === 0 && <span>No positions are configured.</span>}
                        {coreErrors.positions && (
                          <span role="alert">
                            Position options failed to load.{' '}
                            <button className="underline" type="button" onClick={() => void loadCore()}>
                              Retry
                            </button>
                          </span>
                        )}
                      </label>
                      <label className="block">
                        Reporting manager{' '}
                        <input
                          className="rounded border border-theme-border bg-theme-input"
                          name="manager"
                          list="hr-reporting-managers"
                          defaultValue={selectedEmp.manager_employee_id ?? ''}
                        />
                      </label>
                      <datalist id="hr-reporting-managers">
                        {employees
                          .filter((employee) => employee.id !== selectedEmp.id)
                          .map((employee) => (
                            <option key={employee.id} value={employee.id}>
                              {employee.full_name}
                            </option>
                          ))}
                      </datalist>
                      <button
                        className="rounded bg-brand-600 px-2.5 py-1 text-xs text-white"
                        disabled={pending}
                        type="submit"
                      >
                        Save employee
                      </button>
                    </form>
                  )}
                  {hasPerm('hr:policy:manage') && selectedEmp.manager_employee_id && (
                    <div className="space-y-2">
                      <p className="text-sm text-theme-text-muted">
                        Line-manager review for future requests:{' '}
                        {selectedEmp.line_manager_reviewer_id ? 'authorized' : 'not authorized'}
                      </p>
                      <button
                        className="rounded border border-theme-border px-2.5 py-1 text-xs font-semibold"
                        disabled={pending}
                        onClick={() =>
                          void runChange(async () => {
                            const updated = await setEmployeeManagerReview(selectedEmp.id, {
                              enabled: !selectedEmp.line_manager_reviewer_id,
                              expected_revision: selectedEmp.record_revision
                            });
                            setSelectedEmp(updated);
                          }, 'Could not change the review authorization.')
                        }
                        type="button"
                      >
                        {selectedEmp.line_manager_reviewer_id
                          ? 'Revoke line-manager review'
                          : 'Authorize line-manager review'}
                      </button>
                    </div>
                  )}
                  {hasPerm('hr:employees:sensitive') &&
                    ['draft', 'onboarding'].includes(selectedEmp.employment_status) && (
                      <button
                        className="rounded border border-brand-600 px-2.5 py-1 text-xs font-semibold text-brand-600"
                        onClick={() =>
                          void runChange(async () => {
                            const updated = await transitionEmployeeStatus(selectedEmp.id, {
                              expected_revision: selectedEmp.record_revision,
                              status:
                                selectedEmp.employment_category === 'probation'
                                  ? 'on_probation'
                                  : 'active',
                              reason: 'HR Manager reviewed employee record'
                            });
                            setSelectedEmp(updated);
                          }, 'Could not activate employee.')
                        }
                        type="button"
                      >
                        Activate employee
                      </button>
                    )}

                  <details
                    onToggle={(event) => {
                      if (event.currentTarget.open)
                        void runChange(
                          async () =>
                            setEmploymentHistory((await getEmployeeHistory(selectedEmp.id)).items),
                          'Could not load employee history.',
                          false
                        );
                    }}
                  >
                    <summary>Employment history</summary>
                    {employmentHistory?.map((item) => (
                      <p key={item.id}>
                        {item.effective_date} · {item.change_type}
                      </p>
                    ))}
                  </details>
                  {hasPerm('hr:employees:sensitive') && (
                    <form
                      className="border-t border-theme-border pt-3 space-y-2"
                      onSubmit={(e) => void handleSavePrivateVault(e)}
                    >
                      <p className="text-xs font-semibold uppercase text-theme-text-muted">
                        Encrypted Private Vault
                      </p>
                      <p className="text-xs">
                        National ID: {selectedVault?.national_id_masked || 'Unset'}
                      </p>
                      <input
                        aria-label="Update National ID"
                        className="w-full rounded border border-theme-border bg-theme-input px-2 py-1 text-xs"
                        onChange={(e) => setVaultNationalId(e.target.value)}
                        placeholder="Update National ID"
                        value={vaultNationalId}
                        disabled={vaultPending}
                      />
                      <div className="flex gap-2">
                        <button
                          className="rounded bg-brand-600 px-2.5 py-1 text-xs text-white"
                          type="submit"
                          disabled={vaultPending || !selectedVault || !vaultNationalId.trim()}
                        >
                          Encrypt & Save
                        </button>
                        <button
                          className="rounded border border-theme-border px-2.5 py-1 text-xs"
                          onClick={() => void reloadPrivateVault(true)}
                          disabled={vaultPending}
                          type="button"
                        >
                          Reveal sensitive
                        </button>
                        <button
                          className="rounded border border-theme-border px-2.5 py-1 text-xs"
                          onClick={() => void reloadPrivateVault(false)}
                          disabled={vaultPending}
                          type="button"
                        >
                          Reload private vault
                        </button>
                      </div>
                      {selectedVault?.national_id_plain ? (
                        <p className="text-xs text-amber-700">
                          National ID: {selectedVault.national_id_plain}
                        </p>
                      ) : null}
                    </form>
                  )}
                </div>
              )}
            </div>
          </div>
        </div>
      )}

      {tab === 'access' && (
        <div className="grid gap-6 lg:grid-cols-2">
          <div className="rounded-lg border border-theme-border bg-theme-card p-5 space-y-4">
            <h3 className="text-base font-semibold">3-Party Portal Access Requests</h3>
            <HRAccessForms
              employees={employees}
              selectedEmployee={selectedEmp}
              requests={accessRequests}
              canRequest={hasPerm('hr:employees:manage')}
              canReview={hasPerm('hr:employees:sensitive')}
              canFulfill={hasPerm('users:manage')}
              actorId={user?.id}
              onChange={loadCore}
            />
          </div>

          {hasPerm('users:manage') && (
            <HRDirectorOffboarding
              actorId={user?.id}
              canReviewSettlement={hasPerm('financial:view')}
            />
          )}

          {hasPerm('hr:employees:manage') && (
            <div className="rounded-lg border border-theme-border bg-theme-card p-5 space-y-4">
              <h3 className="text-base font-semibold">Workbook Reconciliation</h3>
              <form className="space-y-3" onSubmit={(e) => void handleWorkbookPreview(e)}>
                <input
                  accept=".csv,.xlsx"
                  aria-label="Personnel workbook"
                  disabled={wbPending}
                  onChange={(e: ChangeEvent<HTMLInputElement>) => {
                    setWbFile(e.target.files?.[0] ?? null);
                    setWbPreview(null);
                    setWbApplyResult(null);
                  }}
                  required
                  type="file"
                />
                <textarea
                  aria-label="Role mappings"
                  className="w-full rounded border border-theme-border bg-theme-input px-2.5 py-1.5 font-mono text-xs"
                  disabled={wbPending}
                  onChange={(e) => {
                    setWbOverrides(e.target.value);
                    setWbPreview(null);
                    setWbApplyResult(null);
                  }}
                  placeholder='{"Quantity Surveyor": "quantity_surveyor"}'
                  rows={2}
                  value={wbOverrides}
                />
                <button
                  className="rounded bg-brand-600 px-3 py-1.5 text-xs font-semibold text-white"
                  disabled={wbPending}
                  type="submit"
                >
                  Preview workbook
                </button>
              </form>
              {wbPreview && (
                <div className="space-y-3 text-xs">
                  <p>
                    Rows: {wbPreview.total_rows} · Ready: {wbPreview.ready_employee_rows} · Missing
                    Email: {wbPreview.blocked_missing_email_rows} · Unmapped Titles:{' '}
                    {wbPreview.unmapped_role_rows}
                  </p>
                  <ul className="space-y-2" aria-label="Workbook issues">
                    {wbPreview.rows.filter((row) => (row.issues?.length ?? 0) > 0).map((row) => (
                      <li key={row.row_number}>
                        <strong>{row.user_name || `Entry ${row.row_number}`}</strong>
                        <ul className="ml-4 list-disc">
                          {row.issues?.map((issue) => <li key={issue}>{issue}</li>)}
                        </ul>
                      </li>
                    ))}
                  </ul>
                  <button
                    className="rounded border border-brand-600 px-3 py-1.5 font-semibold text-brand-600"
                    disabled={wbPending}
                    onClick={() => void handleWorkbookApply()}
                    type="button"
                  >
                    Apply workbook reconciliation
                  </button>
                </div>
              )}
              {wbApplyResult && (
                <p className="text-xs text-theme-text-secondary">
                  Applied: {wbApplyResult.employees_created} created,{' '}
                  {wbApplyResult.access_requests_created} access requests queued.
                </p>
              )}
            </div>
          )}
        </div>
      )}

      {tab === 'recruitment' && (
        <div className="rounded-lg border border-theme-border bg-theme-card p-5 space-y-4">
          <h3 className="text-base font-semibold">Requisitions ({requisitions.length})</h3>
          <form
            className="flex flex-wrap items-end gap-2"
            onSubmit={(e) => {
              e.preventDefault();
              void createRequisition({
                requisition_code: reqCode,
                title: reqTitle,
                employment_category: 'permanent',
                headcount_requested: Number(reqHeadcount)
              })
                .then(() => {
                  setReqCode('');
                  setReqTitle('');
                  setReqHeadcount('1');
                  return loadCore();
                })
                .catch((err) => setError(errMsg(err, 'Failed to create requisition.')));
            }}
          >
            <input
              aria-label="Requisition code"
              className="rounded border border-theme-border bg-theme-input px-2.5 py-1.5 text-sm"
              onChange={(e) => setReqCode(e.target.value)}
              placeholder="REQ-001"
              required
              value={reqCode}
            />
            <input
              aria-label="Requisition title"
              className="rounded border border-theme-border bg-theme-input px-2.5 py-1.5 text-sm"
              onChange={(e) => setReqTitle(e.target.value)}
              placeholder="Site Supervisor"
              required
              value={reqTitle}
            />
            <label className="flex items-center gap-1.5 text-sm">
              Requested headcount
              <input
                className="w-20 rounded border border-theme-border bg-theme-input px-2.5 py-1.5 text-sm"
                min={1}
                onChange={(e) => setReqHeadcount(e.target.value)}
                required
                type="number"
                value={reqHeadcount}
              />
            </label>
            <button className="rounded bg-brand-600 px-3 py-1.5 text-sm text-white" type="submit">
              Create requisition
            </button>
          </form>
          <HRHiringPanel
            requisitions={requisitions}
            employees={employees}
            canApprove={hasPerm('hr:employees:sensitive')}
            canManageCVs={hasPerm('hr:documents:manage') && hasPerm('hr:employees:sensitive')}
            reviewerId={user?.id}
            reload={loadCore}
          />
        </div>
      )}

      {tab === 'documents' && (
        <div className="grid gap-6 lg:grid-cols-2">
          <div className="rounded-lg border border-theme-border bg-theme-card p-5 space-y-4">
            <h3 className="text-base font-semibold">HR Document Vault ({documents.length})</h3>
            <form className="space-y-2" onSubmit={(e) => void handleUploadHrDoc(e)}>
              <input
                className="w-full rounded border border-theme-border bg-theme-input px-2.5 py-1.5 text-sm"
                onChange={(e) => setDocTitle(e.target.value)}
                aria-label="Document title"
                placeholder="Document title"
                required
                value={docTitle}
              />
              <label className="block text-sm">
                <input
                  type="checkbox"
                  checked={uploadCompanyPolicy}
                  onChange={(event) => setUploadCompanyPolicy(event.target.checked)}
                />{' '}
                Upload company policy file
              </label>
              <select
                disabled={uploadCompanyPolicy}
                className="w-full rounded border border-theme-border bg-theme-input px-2.5 py-1.5 text-sm"
                onChange={(e) =>
                  setDocCategory(
                    e.target.value as
                      'ordinary' | 'confidential' | 'medical' | 'compensation' | 'disciplinary'
                  )
                }
                aria-label="Document category"
                value={uploadCompanyPolicy ? 'ordinary' : docCategory}
              >
                <option value="ordinary">Ordinary</option>
                {hasPerm('hr:employees:sensitive') && (
                  <option value="confidential">Confidential</option>
                )}
                {hasPerm('hr:employees:sensitive') && <option value="medical">Medical</option>}
              </select>
              <input
                onChange={(e: ChangeEvent<HTMLInputElement>) =>
                  setDocFile(e.target.files?.[0] ?? null)
                }
                required
                aria-label="HR document file"
                type="file"
              />
              {!uploadCompanyPolicy && selectedEmp && docCategory === 'ordinary' && (
                <label className="block text-sm">
                  <input
                    type="checkbox"
                    checked={shareDocument}
                    onChange={(event) => setShareDocument(event.target.checked)}
                  />{' '}
                  Share approved version with {selectedEmp.full_name}
                </label>
              )}
              <button
                className="rounded bg-brand-600 px-3 py-1.5 text-xs font-semibold text-white"
                type="submit"
              >
                Upload HR document
              </button>
            </form>
            <div className="space-y-2 text-xs">
              {documents.map((document) => {
                const versions = document.versions ?? [];
                const latest = versions[0];
                return (
                  <article
                    className="space-y-2 rounded border border-theme-border p-3"
                    key={document.id}
                  >
                    <h4 className="font-semibold">{document.title}</h4>
                    <p>
                      {document.category} · {document.status}
                    </p>
                    <ul className="space-y-1">
                      {versions.map((version) => (
                        <li key={version.id} className="flex flex-wrap items-center gap-2">
                          <span>
                            Version {version.version_number} · {version.status}
                          </span>
                          {['active', 'superseded'].includes(version.status) && (
                            <button
                              type="button"
                              className="text-brand-600"
                              disabled={pending}
                              onClick={() =>
                                void runChange(
                                  async () => {
                                    const result = await getHrDocumentDownloadUrl(
                                      document.id,
                                      version.version_number
                                    );
                                    window.location.assign(result.download_url);
                                  },
                                  'Could not download this version.',
                                  false
                                )
                              }
                            >
                              Download
                            </button>
                          )}
                        </li>
                      ))}
                    </ul>
                    {latest?.status === 'pending' &&
                      latest.uploaded_by_id !== user?.id &&
                      hasPerm('hr:employees:sensitive') && (
                        <div className="flex flex-wrap gap-2">
                          <label>
                            Review reason{' '}
                            <input
                              className="rounded border border-theme-border bg-theme-input"
                              value={docDecisionNotes[document.id] ?? ''}
                              onChange={(event) =>
                                setDocDecisionNotes((notes) => ({
                                  ...notes,
                                  [document.id]: event.target.value
                                }))
                              }
                            />
                          </label>
                          <button
                            type="button"
                            disabled={pending}
                            onClick={() =>
                              void runChange(
                                () =>
                                  decideHrDocumentVersion(document.id, latest.version_number, {
                                    decision: 'approve'
                                  }),
                                'Could not approve this version.'
                              )
                            }
                          >
                            Approve version
                          </button>
                          <button
                            type="button"
                            disabled={pending || !docDecisionNotes[document.id]?.trim()}
                            onClick={() =>
                              void runChange(
                                () =>
                                  decideHrDocumentVersion(document.id, latest.version_number, {
                                    decision: 'reject',
                                    notes: docDecisionNotes[document.id]
                                  }),
                                'Could not reject this version.'
                              )
                            }
                          >
                            Reject version
                          </button>
                        </div>
                      )}
                    {latest?.status !== 'pending' && (
                      <form
                        className="flex flex-wrap items-center gap-2"
                        onSubmit={(event) => {
                          event.preventDefault();
                          const form = event.currentTarget;
                          const file = new FormData(form).get('version');
                          if (file instanceof File && file.size > 0)
                            void runChange(async () => {
                              await uploadHrDocumentVersion(document.id, file);
                              form.reset();
                            }, 'Could not upload replacement.');
                        }}
                      >
                        <label>
                          Replacement file <input type="file" name="version" required />
                        </label>
                        <button type="submit" disabled={pending}>
                          Submit replacement
                        </button>
                      </form>
                    )}
                  </article>
                );
              })}
            </div>
          </div>

          <div className="rounded-lg border border-theme-border bg-theme-card p-5 space-y-3">
            <h3 className="text-base font-semibold">Expiring Compliance (60 Days)</h3>
            {compliance?.items.map((item) => (
              <div
                className="flex justify-between rounded border border-theme-border p-2.5 text-xs"
                key={item.record_id}
              >
                <span>
                  {item.title} ({item.source_type})
                </span>
                <span>
                  {item.expiry_date} ({item.days_remaining}d)
                </span>
              </div>
            ))}
          </div>
        </div>
      )}

      {tab === 'attendance' && (
        <>
          {hasPerm('hr:attendance:approve') && (
            <Link className="text-brand-600 underline" to="/hr/site-attendance">
              Engineer-reviewed site attendance
            </Link>
          )}
          <HRTimePanel employees={employees} canReview={hasPerm('hr:attendance:approve')} />
        </>
      )}

      {tab === 'leave' && (
        <div className="grid gap-6 lg:grid-cols-2">
          <div className="rounded-lg border border-theme-border bg-theme-card p-5 space-y-3">
            <h3 className="text-base font-semibold">Leave Types ({leaveTypes.length})</h3>
            {hasPerm('hr:policy:manage') && (
              <form
                className="grid gap-2"
                onSubmit={(e) => {
                  e.preventDefault();
                  const values = new FormData(e.currentTarget);
                  void createLeaveType({
                    code: ltCode,
                    name: ltName,
                    is_paid: values.get('is_paid') === 'paid',
                    requires_attachment: values.get('requires_attachment') === 'required',
                    allow_half_day: values.get('allow_half_day') === 'allowed'
                  })
                    .then(() => {
                      setLtCode('');
                      setLtName('');
                      return loadCore();
                    })
                    .catch((err) => setError(errMsg(err, 'Failed to create leave type.')));
                }}
              >
                <input
                  className="rounded border border-theme-border bg-theme-input px-2 py-1 text-sm"
                  onChange={(e) => setLtCode(e.target.value)}
                  placeholder="ANNUAL"
                  required
                  value={ltCode}
                />
                <input
                  className="rounded border border-theme-border bg-theme-input px-2 py-1 text-sm"
                  onChange={(e) => setLtName(e.target.value)}
                  placeholder="Annual Leave"
                  required
                  value={ltName}
                />
                <label>
                  Pay treatment{' '}
                  <select className={hrInputClass} name="is_paid" required defaultValue="">
                    <option value="" disabled>Choose approved treatment</option>
                    <option value="paid">Paid leave</option>
                    <option value="unpaid">Unpaid leave</option>
                  </select>
                </label>
                <label>
                  Supporting document{' '}
                  <select
                    className={hrInputClass}
                    name="requires_attachment"
                    required
                    defaultValue=""
                  >
                    <option value="" disabled>Choose requirement</option>
                    <option value="required">Required</option>
                    <option value="optional">Not required</option>
                  </select>
                </label>
                <label>
                  Half-day requests{' '}
                  <select className={hrInputClass} name="allow_half_day" required defaultValue="">
                    <option value="" disabled>Choose rule</option>
                    <option value="allowed">Allowed</option>
                    <option value="not_allowed">Not allowed</option>
                  </select>
                </label>
                <button className="rounded bg-brand-600 px-3 py-1 text-xs text-white" type="submit">
                  Add draft leave type
                </button>
              </form>
            )}
            <p className="text-xs text-theme-text-muted">
              New leave types remain unavailable to employees until a separate approved policy
              supplies their entitlement and effective dates. Unpaid leave stays unpaid in payroll.
            </p>
            <ul className="space-y-1 text-xs text-theme-text-muted">
              {leaveTypes.map((type) => (
                <li key={type.id}>
                  {type.name} · {type.is_paid ? 'paid' : 'unpaid'} ·{' '}
                  {type.is_active ? 'available' : 'policy setup required'}
                </li>
              ))}
            </ul>
            {hasPerm('hr:policy:manage') && user && (
              <HRLeavePolicies userId={user.id} leaveTypes={leaveTypes} />
            )}
            {hasPerm('hr:leave:approve') && (
              <>
                <HRLeaveBaseline employees={employees} leaveTypes={leaveTypes} />
                <HRLeaveAccrual employees={employees} leaveTypes={leaveTypes} />
                <HRLeaveRollover employees={employees} leaveTypes={leaveTypes} />
              </>
            )}
            {coreLoading.leaveTypes && <p role="status">Loading leave types…</p>}
            {!coreLoading.leaveTypes &&
              !coreErrors.leaveTypes &&
              leaveTypes.length === 0 && <p>No leave types are configured.</p>}
            {hasPerm('hr:policy:manage') && leaveTypes.length > 0 && (
              <details className="border-t border-theme-border pt-3 text-sm">
                <summary>Record opening leave balance</summary>
                <form
                  className="mt-4 grid gap-2"
                  onSubmit={(event) => {
                    event.preventDefault();
                    const form = event.currentTarget;
                    const values = new FormData(form);
                    void runChange(async () => {
                      await adjustLeaveLedger({
                        employee_id: String(values.get('employee')),
                        leave_type_id: String(values.get('type')),
                        leave_year: Number(values.get('year')),
                        entry_type: 'opening_balance',
                        days_delta: String(values.get('days')),
                        reason: String(values.get('reason'))
                      });
                      form.reset();
                    }, 'Could not record the opening balance.');
                  }}
                >
                  <label>
                    Employee{' '}
                    <select name="employee" required defaultValue="">
                      <option value="" disabled>
                        Select employee
                      </option>
                      {employees.map((employee) => (
                        <option key={employee.id} value={employee.id}>
                          {employee.full_name}
                        </option>
                      ))}
                    </select>
                    {coreLoading.employees && <span role="status">Loading employees…</span>}
                  </label>
                  <label>
                    Leave type{' '}
                    <select name="type" required>
                      {leaveTypes.map((type) => (
                        <option key={type.id} value={type.id}>
                          {type.name}
                        </option>
                      ))}
                    </select>
                  </label>
                  <label>
                    Year <input name="year" type="number" min="2020" max="2100" required />
                  </label>
                  <label>
                    Opening days <input name="days" type="number" step="0.01" min="0" required />
                  </label>
                  <label>
                    Decision reference <input name="reason" required />
                  </label>
                  <button
                    type="submit"
                    disabled={pending}
                    className="rounded bg-brand-600 px-3 py-1 text-white"
                  >
                    Post opening balance
                  </button>
                </form>
              </details>
            )}
            {leaveTypes.map((lt) => (
              <div className="text-xs" key={lt.id}>
                <strong>{lt.code}</strong> — {lt.name}
              </div>
            ))}
          </div>

          {user && <HRLeaveDateEvidence key={user.id} actorId={user.id} />}
          <div className="rounded-lg border border-theme-border bg-theme-card p-5 space-y-3">
            <h3 className="text-base font-semibold">
              Leave Requests{leaveQueue.data && ` (${leaveQueue.data.total})`}
            </h3>
            <label className="block">
              Request status
              <select
                className={hrInputClass}
                value={leaveStatus}
                disabled={pending}
                onChange={(event) => {
                  setLeaveOffset(0);
                  setLeaveStatus(event.target.value);
                }}
              >
                <option value="">All statuses</option>
                <option value="draft">Draft</option>
                <option value="submitted">Submitted</option>
                <option value="approved">Approved</option>
                <option value="rejected">Rejected</option>
                <option value="cancelled">Cancelled</option>
              </select>
            </label>
            {leaveQueue.isPending && <p role="status">Loading leave requests…</p>}
            {leaveQueue.isError && (
              <p role="alert">
                {errMsg(leaveQueue.error, 'Could not load leave requests.')}
                {' '}<button type="button" onClick={() => void leaveQueue.refetch()}>Retry</button>
              </p>
            )}
            {leaveQueue.data?.items.length === 0 && <p>No matching requests on this page.</p>}
            {leaveQueue.data?.items.map((lr) => (
              <div
                className="flex items-center justify-between rounded border border-theme-border p-2.5 text-xs"
                key={lr.id}
              >
                <span>
                  {lr.start_date} → {lr.end_date} ({lr.days_requested}d) · {lr.status}
                  {lr.status === 'submitted' && lr.approval_route &&
                    ` · Final decision: ${lr.approval_route === 'supervisor' ? 'direct supervisor' : 'HR fallback'}`}
                  {lr.setup_error_code === 'LEAVE_APPROVER_NOT_CONFIGURED' &&
                    ' · HR fallback is not staffed; the request remains submitted.'}
                  {lr.manager_recommendation &&
                    ` · Manager recommendation: ${lr.manager_recommendation}`}
                  {!lr.manager_recommendation &&
                    lr.requires_manager_recommendation &&
                    lr.status === 'submitted' &&
                    ' · Pending manager recommendation'}
                </span>
                {hasPerm('hr:leave:approve') &&
                  lr.status === 'submitted' &&
                  lr.approval_route === 'hr_fallback' && (
                  <div className="flex flex-wrap gap-2">
                    <label>
                      Rejection reason{' '}
                      <input
                        className="rounded border border-theme-border bg-theme-input"
                        value={leaveDecisionNotes[lr.id] ?? ''}
                        onChange={(event) =>
                          setLeaveDecisionNotes((notes) => ({
                            ...notes,
                            [lr.id]: event.target.value
                          }))
                        }
                      />
                    </label>
                    <button
                      className="rounded bg-brand-600 px-2 py-1 text-white"
                      disabled={pending}
                      onClick={() =>
                        void runLeaveDecision(
                          lr.id,
                          { decision: 'approved', expected_revision: lr.record_revision },
                          'Could not approve leave.'
                        )
                      }
                      type="button"
                    >
                      Approve
                    </button>
                    <button
                      className="rounded border border-theme-border px-2 py-1"
                      disabled={pending}
                      onClick={() =>
                        void runLeaveDecision(
                          lr.id,
                          {
                            decision: 'rejected',
                            notes: leaveDecisionNotes[lr.id],
                            expected_revision: lr.record_revision
                          },
                          'Could not reject leave.'
                        )
                      }
                      type="button"
                    >
                      Reject
                    </button>
                  </div>
                )}
                {hasPerm('hr:leave:approve') &&
                  lr.status === 'submitted' &&
                  lr.approval_route !== 'hr_fallback' && (
                    <details>
                      <summary className="cursor-pointer">Record HR fallback</summary>
                      <form
                        className="mt-2 flex flex-wrap items-end gap-2"
                        onSubmit={(event) => {
                          event.preventDefault();
                          const fields = new FormData(event.currentTarget);
                          const reasonCode = String(fields.get('reason_code')) as
                            HrSchemas['LeaveFallbackRequest']['reason_code'];
                          const until = String(fields.get('until') ?? '');
                          if (reasonCode === 'manager_temporarily_unavailable' && !until) {
                            setError('Set an end date for temporary HR fallback.');
                            return;
                          }
                          void runLeaveFallback(
                            lr.id,
                            {
                              reason_code: reasonCode,
                              reason: String(fields.get('reason') ?? '').trim(),
                              expected_revision: lr.record_revision,
                              until: until || null
                            },
                            'Could not route leave to HR fallback.'
                          );
                        }}
                      >
                        <label className="block">
                          Fallback reason
                          <select className={hrInputClass} name="reason_code" defaultValue="manager_temporarily_unavailable">
                            <option value="manager_missing">No direct supervisor assigned</option>
                            <option value="manager_ineligible">Direct supervisor is ineligible</option>
                            <option value="manager_absent">Direct supervisor is on approved leave</option>
                            <option value="manager_temporarily_unavailable">Temporary unavailability</option>
                          </select>
                        </label>
                        <label className="block">
                          Temporary fallback through
                          <input className={hrInputClass} name="until" type="date" />
                        </label>
                        <label className="block">
                          Reason (recorded in the audit trail)
                          <input className={hrInputClass} name="reason" maxLength={500} required />
                        </label>
                        <button className="rounded border border-theme-border px-2 py-1" disabled={pending} type="submit">
                          Route to HR
                        </button>
                      </form>
                    </details>
                  )}
                {hasPerm('hr:leave:approve') && lr.status === 'submitted' && (
                  <button
                    className="rounded border border-theme-border px-2 py-1"
                    disabled={pending}
                    onClick={() => void runLeaveRouteRefresh(lr.id, lr.record_revision)}
                    type="button"
                  >
                    Refresh review assignment
                  </button>
                )}
                {hasPerm('hr:leave:approve') && lr.status === 'approved' &&
                  lr.requested_by_id !== user?.id && (
                  <details>
                    <summary className="cursor-pointer">Reverse approved leave</summary>
                    <form
                      className="mt-2 flex flex-wrap items-end gap-2"
                      onSubmit={(event) => {
                        event.preventDefault();
                        if (pending) return;
                        const reason = String(new FormData(event.currentTarget).get('reason')).trim();
                        void runLeaveDecision(
                          lr.id,
                          {
                            decision: 'cancelled',
                            notes: reason,
                            expected_revision: lr.record_revision
                          },
                          'Could not reverse approved leave.'
                        );
                      }}
                    >
                      <label className="block">
                        Reversal reason (visible to employee)
                        <input className={hrInputClass} name="reason" maxLength={500} required />
                      </label>
                      <button
                        className="rounded border border-theme-border px-2 py-1"
                        disabled={pending}
                        type="submit"
                      >
                        Confirm reversal
                      </button>
                    </form>
                  </details>
                )}
              </div>
            ))}
            {(leaveOffset > 0 || (leaveQueue.data?.total ?? 0) > LEAVE_PAGE_SIZE) && (
              <nav className="flex gap-3" aria-label="Leave request pages">
                <button type="button" disabled={pending || leaveOffset === 0}
                  onClick={() => setLeaveOffset(leaveOffset - LEAVE_PAGE_SIZE)}>
                  Previous requests
                </button>
                <button type="button"
                  disabled={pending || leaveOffset + LEAVE_PAGE_SIZE >= (leaveQueue.data?.total ?? 0)}
                  onClick={() => setLeaveOffset(leaveOffset + LEAVE_PAGE_SIZE)}>
                  Next requests
                </button>
              </nav>
            )}
          </div>
        </div>
      )}

      {tab === 'performance' && hasPerm('hr:performance:manage') && (
        <div className="space-y-4">
          <HRPerformanceSetup />
          <HRPerformanceReviews />
        </div>
      )}

      {tab === 'training' && hasPerm('hr:training:manage') && (
        <HRTraining canManageDocuments={hasPerm('hr:documents:manage')} />
      )}

      {tab === 'operations' && (
        <div className="grid gap-6 lg:grid-cols-2">
          {(hasPerm('hr:policy:manage') || hasPerm('hr:requests:process')) && (
            <HRLettersPanel
              canCreate={hasPerm('hr:policy:manage')}
              canIssue={user?.role === 'hr_manager'}
              canRender={hasPerm('hr:requests:process') && hasPerm('hr:employees:read')}
              canReadCompensation={user?.role === 'hr_manager' && hasPerm('hr:payroll:sensitive')}
            />
          )}
          <HRPolicyPublication
            policies={policies}
            canPublish={hasPerm('hr:policy:manage')}
            refresh={loadCore}
          />

          <div className="rounded-lg border border-theme-border bg-theme-card p-5 space-y-3">
            <h3 className="text-base font-semibold">
              Service Requests{requestQueue.data && ` (${requestQueue.data.total})`}
              {' · '}Offboarding ({offboarding.length})
            </h3>
            {canLoadServiceRequests && (
              <>
                <label className="block">
                  Service request status
                  <select
                    className={hrInputClass}
                    value={requestStatus}
                    disabled={pending}
                    onChange={(event) => {
                      setRequestOffset(0);
                      setRequestStatus(event.target.value);
                    }}
                  >
                    <option value="">All statuses</option>
                    <option value="open">Open</option>
                    <option value="in_review">In review</option>
                    <option value="approved">Approved</option>
                    <option value="completed">Completed</option>
                    <option value="rejected">Rejected</option>
                    <option value="cancelled">Cancelled</option>
                  </select>
                </label>
                {requestQueue.isPending && <p role="status">Loading service requests…</p>}
                {requestQueue.isError && (
                  <p role="alert">
                    {errMsg(requestQueue.error, 'Could not load service requests.')}
                    {' '}<button type="button" onClick={() => void requestQueue.refetch()}>Retry</button>
                  </p>
                )}
                {assignees.isError && (
                  <p role="alert">
                    {errMsg(assignees.error, 'Could not load eligible assignees.')}
                    {' '}<button type="button" onClick={() => void assignees.refetch()}>Retry</button>
                  </p>
                )}
                {requestQueue.data?.items.length === 0 && <p>No matching requests on this page.</p>}
              </>
            )}
            {canLoadServiceRequests && requestQueue.data?.items.map((sr) => (
              <div
                className="space-y-2 rounded border border-theme-border p-2.5 text-xs"
                key={sr.id}
              >
                <span>
                  {sr.request_code} — {sr.subject} ({sr.status})
                </span>
                <p>
                  {hrServiceRequestTypes[sr.request_type as HrServiceRequestType] ??
                    sr.request_type.replace(/_/g, ' ')}
                </p>
                {sr.generated_letter_id && (
                  <HRResponseLetter
                    key={sr.generated_letter_id}
                    letterId={sr.generated_letter_id}
                    employeeId={sr.employee_id}
                  />
                )}
                {sr.description && <p className="whitespace-pre-wrap">{sr.description}</p>}
                {['open', 'in_review', 'approved'].includes(sr.status) && (
                  <>
                    <p>
                      Assigned to:{' '}
                      {sr.assigned_to_id
                        ? (requestAssignees.find((assignee) => assignee.id === sr.assigned_to_id)
                            ?.full_name ?? 'Unavailable HR user')
                        : 'Unassigned'}
                    </p>
                    <HRServiceRequestAssignment
                      request={sr}
                      assignees={requestAssignees}
                      pending={pending}
                      onChange={runServiceRequestChange}
                    />
                  </>
                )}
                {sr.status === 'open' && (!sr.assigned_to_id || sr.assigned_to_id === user?.id) && (
                  <div>
                    <button
                      className="rounded bg-brand-600 px-2 py-1 text-white"
                      disabled={pending}
                      onClick={() =>
                        void runServiceRequestChange(
                          () =>
                            resolveServiceRequest(sr.id, {
                              status: 'in_review',
                              expected_updated_at: sr.updated_at
                            }),
                          'Unable to start HR service request review.'
                        )
                      }
                      type="button"
                    >
                      Start review
                    </button>
                  </div>
                )}
                {['in_review', 'approved'].includes(sr.status) &&
                  (!sr.assigned_to_id || sr.assigned_to_id === user?.id) && (
                    <form
                      className="space-y-2"
                      onSubmit={(event) => {
                        event.preventDefault();
                        const response = requestResponses[sr.id];
                        const letter = requestLetters[sr.id];
                        void runServiceRequestChange(async () => {
                          await resolveServiceRequest(sr.id, {
                            status: 'completed',
                            expected_updated_at: sr.updated_at,
                            ...(letter ? { generated_letter_id: letter } : {}),
                            ...(response?.trim() ? { resolution_notes: response.trim() } : {})
                          });
                          setRequestLetters((current) => {
                            const next = { ...current };
                            delete next[sr.id];
                            return next;
                          });
                          setRequestResponses((current) => {
                            const next = { ...current };
                            delete next[sr.id];
                            return next;
                          });
                        }, 'Unable to complete HR service request.');
                      }}
                    >
                      <label className="block">
                        Response shared with the employee
                        <textarea
                          className="mt-1 block w-full rounded border border-theme-border bg-theme-input p-2"
                          disabled={pending}
                          maxLength={2000}
                          onChange={(event) =>
                            setRequestResponses((current) => ({
                              ...current,
                              [sr.id]: event.target.value
                            }))
                          }
                          rows={2}
                          value={requestResponses[sr.id] ?? sr.resolution_notes ?? ''}
                        />
                      </label>
                      <HRIssuedLetterPicker
                        employeeId={sr.employee_id}
                        value={requestLetters[sr.id] ?? ''}
                        onChange={(value) =>
                          setRequestLetters((current) => ({ ...current, [sr.id]: value }))
                        }
                        disabled={pending}
                      />
                      <button
                        className="rounded bg-brand-600 px-2 py-1 text-white"
                        disabled={pending}
                        type="submit"
                      >
                        Complete request
                      </button>
                    </form>
                  )}
              </div>
            ))}
            {canLoadServiceRequests &&
              (requestOffset > 0 || (requestQueue.data?.total ?? 0) > SERVICE_REQUEST_PAGE_SIZE) && (
              <nav className="flex gap-3" aria-label="Service request pages">
                <button type="button" disabled={pending || requestOffset === 0}
                  onClick={() => setRequestOffset(requestOffset - SERVICE_REQUEST_PAGE_SIZE)}>
                  Previous requests
                </button>
                <button type="button"
                  disabled={pending ||
                    requestOffset + SERVICE_REQUEST_PAGE_SIZE >= (requestQueue.data?.total ?? 0)}
                  onClick={() => setRequestOffset(requestOffset + SERVICE_REQUEST_PAGE_SIZE)}>
                  Next requests
                </button>
              </nav>
            )}
            {hasPerm('hr:offboarding:manage') && (
              <HROffboarding employees={employees} cases={offboarding} onChange={loadCore} />
            )}
          </div>
        </div>
      )}
    </div>
  );
}
