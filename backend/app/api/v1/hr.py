import json
from collections.abc import Callable
from datetime import date
from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, File, Form, Query, UploadFile, status
from fastapi.responses import Response

from app.api.dependencies import CurrentUser, DbSession, require_permission
from app.config import get_settings
from app.models.user import User
from app.schemas.hr import (
    AccessRequestCreateRequest,
    AccessRequestDecisionRequest,
    AccessRequestListResponse,
    AccessRequestResponse,
    ApplicationCreateRequest,
    ApplicationListResponse,
    ApplicationResponse,
    ApplicationStageUpdateRequest,
    AttendanceCorrectionCreateRequest,
    AttendanceCorrectionDecisionRequest,
    AttendanceCorrectionListResponse,
    AttendanceCorrectionResponse,
    AttendanceCorrectionSelfRequest,
    AttendanceEntryCreateRequest,
    AttendanceEntryListResponse,
    AttendanceEntryResponse,
    AttendanceImportPreviewResponse,
    AttendanceReviewRequest,
    BenefitTypeCreateRequest,
    BenefitTypeListResponse,
    BenefitTypeResponse,
    CandidateCreateRequest,
    CandidateListResponse,
    CandidateResponse,
    CertificationCreateRequest,
    CertificationListResponse,
    CertificationResponse,
    CompensationTermCreateRequest,
    CompensationTermListResponse,
    CompensationTermResponse,
    DepartmentCreateRequest,
    DepartmentListResponse,
    DepartmentResponse,
    DepartmentUpdateRequest,
    EmployeeBenefitCreateRequest,
    EmployeeBenefitListResponse,
    EmployeeBenefitResponse,
    EmployeeCreateRequest,
    EmployeeDetailResponse,
    EmployeeDirectoryListResponse,
    EmployeeLinkAccountRequest,
    EmployeeManagerReviewRequest,
    EmployeePrivateUpdateRequest,
    EmployeeSelfResponse,
    EmployeeSelfUpdateRequest,
    EmployeeSensitiveResponse,
    EmployeeStatusTransitionRequest,
    EmployeeUpdateRequest,
    EmploymentHistoryListResponse,
    EmploymentHistoryResponse,
    ExpiringComplianceResponse,
    GoalCreateRequest,
    GoalListResponse,
    GoalResponse,
    GoalUpdateRequest,
    HolidayCreateRequest,
    HolidayListResponse,
    HolidayResponse,
    HrCaseCloseRequest,
    HrCaseCreateRequest,
    HrCaseListResponse,
    HrCaseResponse,
    HrDocumentCategory,
    HrDocumentDecisionRequest,
    HrDocumentDownloadResponse,
    HrDocumentListResponse,
    HrDocumentResponse,
    HrReportFilters,
    HrReportSiteListResponse,
    HrServiceRequestCreateRequest,
    HrServiceRequestListResponse,
    HrServiceRequestReopenRequest,
    HrServiceRequestResolveRequest,
    HrServiceRequestResponse,
    HrSummaryReportResponse,
    HrWorkflowOptionsResponse,
    InterviewCreateRequest,
    InterviewListResponse,
    InterviewResponse,
    InterviewUpdateRequest,
    LeaveBalanceListResponse,
    LeaveLedgerAdjustRequest,
    LeaveLedgerEntryResponse,
    LeavePolicyCreateRequest,
    LeavePolicyListResponse,
    LeavePolicyResponse,
    LeaveRequestCreateRequest,
    LeaveRequestDecisionRequest,
    LeaveRequestListResponse,
    LeaveRequestResponse,
    LeaveTypeCreateRequest,
    LeaveTypeListResponse,
    LeaveTypeResponse,
    LetterGenerateRequest,
    LetterRenderResponse,
    LetterTemplateCreateRequest,
    LetterTemplateListResponse,
    LetterTemplateResponse,
    ManagerReviewDecisionRequest,
    ManagerReviewItemResponse,
    ManagerReviewKind,
    ManagerReviewListResponse,
    OffboardingCaseListResponse,
    OffboardingCaseResponse,
    OffboardingCompleteRequest,
    OffboardingInitiateRequest,
    OffboardingStepUpdateRequest,
    OfferConvertRequest,
    OfferCreateRequest,
    OfferDecisionRequest,
    OfferListResponse,
    OfferResponse,
    OnboardingCaseCreateRequest,
    OnboardingCaseListResponse,
    OnboardingCaseResponse,
    OnboardingTaskUpdateRequest,
    OrgChartResponse,
    OvertimeDecisionRequest,
    OvertimeRequestCreateRequest,
    OvertimeRequestListResponse,
    OvertimeRequestResponse,
    OvertimeSelfCreateRequest,
    PayrollPeriodCreateRequest,
    PayrollPeriodListResponse,
    PayrollPeriodResponse,
    PayrollPolicyCreateRequest,
    PayrollPolicyListResponse,
    PayrollPolicyResponse,
    PayrollRunCreateRequest,
    PayrollRunListResponse,
    PayrollRunResponse,
    PolicyAcknowledgementResponse,
    PolicyAcknowledgeRequest,
    PolicyDocumentCreateRequest,
    PolicyDocumentListResponse,
    PolicyDocumentResponse,
    PositionCreateRequest,
    PositionListResponse,
    PositionResponse,
    PositionUpdateRequest,
    ProbationReviewRequest,
    ReimbursementCreateRequest,
    ReimbursementDecisionRequest,
    ReimbursementListResponse,
    ReimbursementResponse,
    RequisitionCreateRequest,
    RequisitionDecisionRequest,
    RequisitionListResponse,
    RequisitionResponse,
    ReviewCreateRequest,
    ReviewCycleCreateRequest,
    ReviewCycleListResponse,
    ReviewCycleResponse,
    ReviewListResponse,
    ReviewResponse,
    ShiftAssignmentCreateRequest,
    ShiftAssignmentListResponse,
    ShiftAssignmentResponse,
    TimesheetCreateRequest,
    TimesheetDecisionRequest,
    TimesheetListResponse,
    TimesheetResponse,
    TimesheetSelfCreateRequest,
    TimesheetSelfResubmitRequest,
    TrainingCourseCreateRequest,
    TrainingCourseListResponse,
    TrainingCourseResponse,
    TrainingEnrollmentCreateRequest,
    TrainingEnrollmentListResponse,
    TrainingEnrollmentResponse,
    TrainingEnrollmentUpdateRequest,
    WorkbookApplyRequest,
    WorkbookApplyResponse,
    WorkbookPreviewResponse,
    WorkCalendarCreateRequest,
    WorkCalendarDecisionRequest,
    WorkCalendarListResponse,
    WorkCalendarResponse,
    WorkCalendarUpdateRequest,
    WorkScheduleResponse,
)
from app.services.audit_service import AuditService
from app.services.hr_attendance_import import MAX_ATTENDANCE_CSV_BYTES, review_attendance_csv
from app.services.hr_manager_review import (
    can_review_direct_reports,
    list_manager_reviews,
    recommend_request,
)
from app.services.hr_reporting import (
    HR_REPORT_MEDIA_TYPES,
    HrReportFormat,
    build_hr_summary_export,
    get_hr_summary,
    list_hr_report_sites,
)
from app.services.hr_service import HrService
from app.services.hr_workbook import apply_workbook, parse_workbook_bytes, preview_workbook
from app.utils.exceptions import AppException, NotFoundException, PermissionDeniedException
from app.utils.permissions import (
    PERMISSION_HR_ATTENDANCE_APPROVE,
    PERMISSION_HR_ATTENDANCE_RECORD,
    PERMISSION_HR_CASES_RESTRICTED,
    PERMISSION_HR_COMPLIANCE_MANAGE,
    PERMISSION_HR_DOCUMENTS_MANAGE,
    PERMISSION_HR_EMPLOYEES_MANAGE,
    PERMISSION_HR_EMPLOYEES_READ,
    PERMISSION_HR_EMPLOYEES_SENSITIVE,
    PERMISSION_HR_LEAVE_APPROVE,
    PERMISSION_HR_LEAVE_MANAGE,
    PERMISSION_HR_OFFBOARDING_MANAGE,
    PERMISSION_HR_ONBOARDING_MANAGE,
    PERMISSION_HR_PAYROLL_APPROVE,
    PERMISSION_HR_PAYROLL_PREPARE,
    PERMISSION_HR_PAYROLL_SENSITIVE,
    PERMISSION_HR_PERFORMANCE_MANAGE,
    PERMISSION_HR_POLICY_MANAGE,
    PERMISSION_HR_RECRUITMENT_MANAGE,
    PERMISSION_HR_REPORTS_VIEW,
    PERMISSION_HR_REQUESTS_PROCESS,
    PERMISSION_HR_TRAINING_MANAGE,
    PERMISSION_USERS_MANAGE,
    has_permission,
)

router = APIRouter(prefix="/hr", tags=["HR & Workforce"])


def require_any_permission(*permissions: str) -> Callable[[User], User]:
    def dependency(current_user: CurrentUser) -> User:
        if any(has_permission(current_user, perm) for perm in permissions):
            return current_user
        raise PermissionDeniedException(permissions[0])

    return dependency


CanReadEmployees = Annotated[User, Depends(require_permission(PERMISSION_HR_EMPLOYEES_READ))]
CanManageEmployees = Annotated[User, Depends(require_permission(PERMISSION_HR_EMPLOYEES_MANAGE))]
CanAccessSensitive = Annotated[User, Depends(require_permission(PERMISSION_HR_EMPLOYEES_SENSITIVE))]
CanManageUsers = Annotated[User, Depends(require_permission(PERMISSION_USERS_MANAGE))]
CanAccessQueue = Annotated[
    User,
    Depends(
        require_any_permission(
            PERMISSION_HR_EMPLOYEES_READ,
            PERMISSION_HR_EMPLOYEES_MANAGE,
            PERMISSION_USERS_MANAGE,
        )
    ),
]
CanDecideAccess = Annotated[
    User,
    Depends(
        require_any_permission(
            PERMISSION_HR_EMPLOYEES_MANAGE,
            PERMISSION_HR_EMPLOYEES_SENSITIVE,
            PERMISSION_USERS_MANAGE,
        )
    ),
]
CanManageRecruitment = Annotated[
    User, Depends(require_permission(PERMISSION_HR_RECRUITMENT_MANAGE))
]
CanManageOnboarding = Annotated[User, Depends(require_permission(PERMISSION_HR_ONBOARDING_MANAGE))]
CanManageDocuments = Annotated[User, Depends(require_permission(PERMISSION_HR_DOCUMENTS_MANAGE))]
CanManageCompliance = Annotated[User, Depends(require_permission(PERMISSION_HR_COMPLIANCE_MANAGE))]
CanRecordAttendance = Annotated[User, Depends(require_permission(PERMISSION_HR_ATTENDANCE_RECORD))]
CanApproveAttendance = Annotated[
    User, Depends(require_permission(PERMISSION_HR_ATTENDANCE_APPROVE))
]
CanManageLeave = Annotated[User, Depends(require_permission(PERMISSION_HR_LEAVE_MANAGE))]
CanApproveLeave = Annotated[User, Depends(require_permission(PERMISSION_HR_LEAVE_APPROVE))]
CanProcessRequests = Annotated[User, Depends(require_permission(PERMISSION_HR_REQUESTS_PROCESS))]
CanManagePolicy = Annotated[User, Depends(require_permission(PERMISSION_HR_POLICY_MANAGE))]
CanManageOffboarding = Annotated[
    User, Depends(require_permission(PERMISSION_HR_OFFBOARDING_MANAGE))
]
CanManagePerformance = Annotated[
    User, Depends(require_permission(PERMISSION_HR_PERFORMANCE_MANAGE))
]
CanManageTraining = Annotated[User, Depends(require_permission(PERMISSION_HR_TRAINING_MANAGE))]
CanPreparePayroll = Annotated[User, Depends(require_permission(PERMISSION_HR_PAYROLL_PREPARE))]
CanApprovePayroll = Annotated[User, Depends(require_permission(PERMISSION_HR_PAYROLL_APPROVE))]
CanReadPayrollSensitive = Annotated[
    User, Depends(require_permission(PERMISSION_HR_PAYROLL_SENSITIVE))
]
CanManageCases = Annotated[User, Depends(require_permission(PERMISSION_HR_CASES_RESTRICTED))]
CanViewHrReports = Annotated[User, Depends(require_permission(PERMISSION_HR_REPORTS_VIEW))]


# --- Employee Self-Service (/api/v1/hr/me) ---


@router.get("/me", response_model=EmployeeSelfResponse)
async def get_my_hr_profile(current_user: CurrentUser, session: DbSession) -> EmployeeSelfResponse:
    return await HrService(session).get_self_profile(current_user)


@router.patch("/me", response_model=EmployeeSelfResponse)
async def update_my_hr_profile(
    payload: EmployeeSelfUpdateRequest,
    current_user: CurrentUser,
    session: DbSession,
) -> EmployeeSelfResponse:
    return await HrService(session).update_self_profile(payload, current_user)


@router.get("/me/leave-types", response_model=LeaveTypeListResponse)
async def list_my_leave_types(
    current_user: CurrentUser, session: DbSession
) -> LeaveTypeListResponse:
    svc = HrService(session)
    await svc.require_self_employee(current_user)
    rows, total = await svc.list_leave_types()
    return LeaveTypeListResponse(
        items=[LeaveTypeResponse.model_validate(r) for r in rows], total=total
    )


@router.get("/me/workflow-options", response_model=HrWorkflowOptionsResponse)
async def get_my_workflow_options(
    current_user: CurrentUser, session: DbSession
) -> HrWorkflowOptionsResponse:
    employee = await HrService(session).require_self_employee(current_user)
    return HrWorkflowOptionsResponse(
        can_recommend=await can_review_direct_reports(session, employee),
        self_time_submission_enabled=get_settings().hr_self_time_submission_enabled,
    )


@router.get("/me/manager-reviews", response_model=ManagerReviewListResponse)
async def get_my_manager_reviews(
    current_user: CurrentUser,
    session: DbSession,
    offset: Annotated[int, Query(ge=0)] = 0,
    limit: Annotated[int, Query(ge=1, le=100)] = 50,
) -> ManagerReviewListResponse:
    employee = await HrService(session).require_self_employee(current_user)
    return await list_manager_reviews(session, employee, current_user, offset=offset, limit=limit)


@router.post("/me/manager-reviews/{kind}/{request_id}", response_model=ManagerReviewItemResponse)
async def recommend_direct_report_request(
    kind: ManagerReviewKind,
    request_id: UUID,
    payload: ManagerReviewDecisionRequest,
    current_user: CurrentUser,
    session: DbSession,
) -> ManagerReviewItemResponse:
    return await recommend_request(
        session, kind=kind, request_id=request_id, payload=payload, actor=current_user
    )


def require_self_time_submission() -> None:
    if not get_settings().hr_self_time_submission_enabled:
        raise NotFoundException("Self-service time submission")


@router.get(
    "/me/timesheets",
    response_model=TimesheetListResponse,
    dependencies=[Depends(require_self_time_submission)],
)
async def get_my_timesheets(current_user: CurrentUser, session: DbSession) -> TimesheetListResponse:
    service = HrService(session)
    employee = await service.require_self_employee(current_user)
    rows, total = await service.list_timesheets(employee_id=employee.id)
    return TimesheetListResponse(
        items=[TimesheetResponse.model_validate(row) for row in rows], total=total
    )


@router.post(
    "/me/timesheets",
    response_model=TimesheetResponse,
    status_code=201,
    dependencies=[Depends(require_self_time_submission)],
)
async def create_my_timesheet(
    payload: TimesheetSelfCreateRequest, current_user: CurrentUser, session: DbSession
) -> TimesheetResponse:
    service = HrService(session)
    employee = await service.require_self_employee(current_user)
    request = TimesheetCreateRequest(
        **payload.model_dump(),
        employee_id=employee.id,
        submit=True,
    )
    return TimesheetResponse.model_validate(
        await service.create_timesheet(request, current_user, own_request=True)
    )


@router.put(
    "/me/timesheets/{timesheet_id}/submission",
    response_model=TimesheetResponse,
    dependencies=[Depends(require_self_time_submission)],
)
async def resubmit_my_timesheet(
    timesheet_id: UUID,
    payload: TimesheetSelfResubmitRequest,
    current_user: CurrentUser,
    session: DbSession,
) -> TimesheetResponse:
    row = await HrService(session).resubmit_own_timesheet(timesheet_id, payload, current_user)
    return TimesheetResponse.model_validate(row)


@router.get(
    "/me/overtime",
    response_model=OvertimeRequestListResponse,
    dependencies=[Depends(require_self_time_submission)],
)
async def get_my_overtime(
    current_user: CurrentUser, session: DbSession
) -> OvertimeRequestListResponse:
    service = HrService(session)
    employee = await service.require_self_employee(current_user)
    rows, total = await service.list_overtime_requests(employee_id=employee.id)
    return OvertimeRequestListResponse(
        items=[OvertimeRequestResponse.model_validate(row) for row in rows], total=total
    )


@router.post(
    "/me/overtime",
    response_model=OvertimeRequestResponse,
    status_code=201,
    dependencies=[Depends(require_self_time_submission)],
)
async def create_my_overtime(
    payload: OvertimeSelfCreateRequest, current_user: CurrentUser, session: DbSession
) -> OvertimeRequestResponse:
    service = HrService(session)
    employee = await service.require_self_employee(current_user)
    request = OvertimeRequestCreateRequest(
        **payload.model_dump(),
        employee_id=employee.id,
    )
    return OvertimeRequestResponse.model_validate(
        await service.create_overtime_request(request, current_user, own_request=True)
    )


@router.get("/me/leave-balances", response_model=LeaveBalanceListResponse)
async def get_my_leave_balances(
    current_user: CurrentUser,
    session: DbSession,
    leave_year: Annotated[int | None, Query()] = None,
) -> LeaveBalanceListResponse:
    svc = HrService(session)
    emp = await svc.require_self_employee(current_user)
    return await svc.get_leave_balances(emp.id, leave_year=leave_year)


@router.get("/me/leave-requests", response_model=LeaveRequestListResponse)
async def list_my_leave_requests(
    current_user: CurrentUser, session: DbSession
) -> LeaveRequestListResponse:
    svc = HrService(session)
    emp = await svc.require_self_employee(current_user)
    rows, total = await svc.list_leave_requests(employee_id=emp.id)
    return LeaveRequestListResponse(
        items=[LeaveRequestResponse.model_validate(r) for r in rows], total=total
    )


@router.post("/me/leave-requests", response_model=LeaveRequestResponse, status_code=201)
async def submit_my_leave_request(
    payload: LeaveRequestCreateRequest,
    current_user: CurrentUser,
    session: DbSession,
) -> LeaveRequestResponse:
    svc = HrService(session)
    emp = await svc.require_self_employee(current_user)
    scoped = payload.model_copy(update={"employee_id": emp.id})
    req = await svc.create_leave_request(scoped, current_user, own_request=True)
    return LeaveRequestResponse.model_validate(req)


@router.post("/me/leave-requests/{request_id}/cancel", response_model=LeaveRequestResponse)
async def cancel_my_leave_request(
    request_id: UUID,
    current_user: CurrentUser,
    session: DbSession,
) -> LeaveRequestResponse:
    req = await HrService(session).decide_leave_request(
        request_id,
        LeaveRequestDecisionRequest(decision="cancelled"),
        current_user,
        own_request=True,
    )
    return LeaveRequestResponse.model_validate(req)


@router.get("/me/attendance", response_model=AttendanceEntryListResponse)
async def list_my_attendance(
    current_user: CurrentUser,
    session: DbSession,
    date_from: Annotated[date | None, Query()] = None,
    date_to: Annotated[date | None, Query()] = None,
) -> AttendanceEntryListResponse:
    svc = HrService(session)
    emp = await svc.require_self_employee(current_user)
    rows, total = await svc.list_attendance(
        employee_id=emp.id, date_from=date_from, date_to=date_to
    )
    return AttendanceEntryListResponse(
        items=[AttendanceEntryResponse.model_validate(r) for r in rows], total=total
    )


@router.post(
    "/me/attendance/corrections", response_model=AttendanceCorrectionResponse, status_code=201
)
async def request_my_attendance_correction(
    payload: AttendanceCorrectionSelfRequest,
    current_user: CurrentUser,
    session: DbSession,
) -> AttendanceCorrectionResponse:
    service = HrService(session)
    employee = await service.require_self_employee(current_user)
    correction = await service.create_attendance_correction(
        AttendanceCorrectionCreateRequest(employee_id=employee.id, **payload.model_dump()),
        current_user,
    )
    return AttendanceCorrectionResponse.model_validate(correction)


@router.get("/me/documents", response_model=HrDocumentListResponse)
async def list_my_hr_documents(
    current_user: CurrentUser, session: DbSession
) -> HrDocumentListResponse:
    rows, total = await HrService(session).list_self_hr_documents(current_user)
    return HrDocumentListResponse(items=rows, total=total)


@router.get("/me/documents/{document_id}/download", response_model=HrDocumentDownloadResponse)
async def download_my_hr_document(
    document_id: UUID, current_user: CurrentUser, session: DbSession
) -> HrDocumentDownloadResponse:
    return await HrService(session).get_self_hr_document_download_url(document_id, current_user)


@router.get("/me/policies", response_model=PolicyDocumentListResponse)
async def list_my_policies(
    current_user: CurrentUser, session: DbSession
) -> PolicyDocumentListResponse:
    await HrService(session).require_self_employee(current_user)
    rows, total = await HrService(session).list_policy_documents()
    return PolicyDocumentListResponse(
        items=[PolicyDocumentResponse.model_validate(r) for r in rows], total=total
    )


@router.post("/me/policies/{policy_id}/acknowledge", response_model=PolicyAcknowledgementResponse)
async def acknowledge_hr_policy(
    policy_id: UUID,
    payload: PolicyAcknowledgeRequest,
    current_user: CurrentUser,
    session: DbSession,
) -> PolicyAcknowledgementResponse:
    ack = await HrService(session).acknowledge_policy(policy_id, payload, current_user)
    return PolicyAcknowledgementResponse.model_validate(ack)


@router.get("/me/requests", response_model=HrServiceRequestListResponse)
async def list_my_service_requests(
    current_user: CurrentUser, session: DbSession
) -> HrServiceRequestListResponse:
    svc = HrService(session)
    emp = await svc.require_self_employee(current_user)
    rows, total = await svc.list_service_requests(employee_id=emp.id)
    return HrServiceRequestListResponse(
        items=[HrServiceRequestResponse.model_validate(r) for r in rows], total=total
    )


@router.post("/me/requests", response_model=HrServiceRequestResponse, status_code=201)
async def create_my_service_request(
    payload: HrServiceRequestCreateRequest,
    current_user: CurrentUser,
    session: DbSession,
) -> HrServiceRequestResponse:
    svc = HrService(session)
    emp = await svc.require_self_employee(current_user)
    scoped = payload.model_copy(update={"employee_id": emp.id})
    req = await svc.create_service_request(scoped, current_user)
    return HrServiceRequestResponse.model_validate(req)


@router.post("/me/requests/{req_id}/reopen", response_model=HrServiceRequestResponse)
async def reopen_my_service_request(
    req_id: UUID,
    payload: HrServiceRequestReopenRequest,
    current_user: CurrentUser,
    session: DbSession,
) -> HrServiceRequestResponse:
    req = await HrService(session).reopen_my_service_request(
        req_id, payload.expected_updated_at, current_user
    )
    return HrServiceRequestResponse.model_validate(req)


@router.get("/me/reimbursements", response_model=ReimbursementListResponse)
async def list_my_reimbursements(
    current_user: CanReadPayrollSensitive, session: DbSession
) -> ReimbursementListResponse:
    svc = HrService(session)
    emp = await svc.require_self_employee(current_user)
    rows, total = await svc.list_reimbursements(employee_id=emp.id)
    return ReimbursementListResponse(
        items=[ReimbursementResponse.model_validate(r) for r in rows], total=total
    )


@router.post("/me/reimbursements", response_model=ReimbursementResponse, status_code=201)
async def create_my_reimbursement(
    payload: ReimbursementCreateRequest,
    current_user: CanReadPayrollSensitive,
    session: DbSession,
) -> ReimbursementResponse:
    svc = HrService(session)
    emp = await svc.require_self_employee(current_user)
    scoped = payload.model_copy(update={"employee_id": emp.id})
    claim = await svc.create_reimbursement(scoped, current_user)
    return ReimbursementResponse.model_validate(claim)


# --- Departments, Positions, Org Chart ---


@router.get("/departments", response_model=DepartmentListResponse)
async def list_departments(_: CanReadEmployees, session: DbSession) -> DepartmentListResponse:
    rows, total = await HrService(session).list_departments()
    return DepartmentListResponse(
        items=[DepartmentResponse.model_validate(r) for r in rows], total=total
    )


@router.post("/departments", response_model=DepartmentResponse, status_code=status.HTTP_201_CREATED)
async def create_department(
    payload: DepartmentCreateRequest, actor: CanManageEmployees, session: DbSession
) -> DepartmentResponse:
    row = await HrService(session).create_department(payload, actor)
    return DepartmentResponse.model_validate(row)


@router.patch("/departments/{department_id}", response_model=DepartmentResponse)
async def update_department(
    department_id: UUID,
    payload: DepartmentUpdateRequest,
    actor: CanManageEmployees,
    session: DbSession,
) -> DepartmentResponse:
    row = await HrService(session).update_department(department_id, payload, actor)
    return DepartmentResponse.model_validate(row)


@router.get("/positions", response_model=PositionListResponse)
async def list_positions(_: CanReadEmployees, session: DbSession) -> PositionListResponse:
    rows, total = await HrService(session).list_positions()
    return PositionListResponse(
        items=[PositionResponse.model_validate(r) for r in rows], total=total
    )


@router.post("/positions", response_model=PositionResponse, status_code=status.HTTP_201_CREATED)
async def create_position(
    payload: PositionCreateRequest, actor: CanManageEmployees, session: DbSession
) -> PositionResponse:
    row = await HrService(session).create_position(payload, actor)
    return PositionResponse.model_validate(row)


@router.patch("/positions/{position_id}", response_model=PositionResponse)
async def update_position(
    position_id: UUID,
    payload: PositionUpdateRequest,
    actor: CanManageEmployees,
    session: DbSession,
) -> PositionResponse:
    row = await HrService(session).update_position(position_id, payload, actor)
    return PositionResponse.model_validate(row)


@router.get("/org-chart", response_model=OrgChartResponse)
async def get_org_chart(_: CanReadEmployees, session: DbSession) -> OrgChartResponse:
    return await HrService(session).get_org_chart()


# --- Employees & Private Vault ---


@router.get("/employees", response_model=EmployeeDirectoryListResponse)
async def list_employees(
    _: CanReadEmployees,
    session: DbSession,
    search: Annotated[str | None, Query(max_length=120)] = None,
    employment_status: Annotated[str | None, Query()] = None,
    department_id: Annotated[UUID | None, Query()] = None,
    limit: Annotated[int, Query(ge=1, le=200)] = 100,
    offset: Annotated[int, Query(ge=0)] = 0,
) -> EmployeeDirectoryListResponse:
    items, total = await HrService(session).list_employees(
        search=search,
        status=employment_status,
        department_id=department_id,
        limit=limit,
        offset=offset,
    )
    return EmployeeDirectoryListResponse(items=items, total=total)


@router.post(
    "/employees", response_model=EmployeeDetailResponse, status_code=status.HTTP_201_CREATED
)
async def create_employee(
    payload: EmployeeCreateRequest, actor: CanManageEmployees, session: DbSession
) -> EmployeeDetailResponse:
    return await HrService(session).create_employee(payload, actor)


@router.get("/employees/{employee_id}", response_model=EmployeeDetailResponse)
async def get_employee(
    employee_id: UUID, _: CanReadEmployees, session: DbSession
) -> EmployeeDetailResponse:
    return await HrService(session).get_employee_detail(employee_id)


@router.patch("/employees/{employee_id}", response_model=EmployeeDetailResponse)
async def update_employee(
    employee_id: UUID,
    payload: EmployeeUpdateRequest,
    actor: CanManageEmployees,
    session: DbSession,
) -> EmployeeDetailResponse:
    return await HrService(session).update_employee(employee_id, payload, actor)


@router.put("/employees/{employee_id}/manager-review", response_model=EmployeeDetailResponse)
async def set_employee_manager_review(
    employee_id: UUID,
    payload: EmployeeManagerReviewRequest,
    actor: CanManagePolicy,
    session: DbSession,
) -> EmployeeDetailResponse:
    return await HrService(session).set_employee_manager_review(employee_id, payload, actor)


@router.post("/employees/{employee_id}/status", response_model=EmployeeDetailResponse)
async def transition_employee_status(
    employee_id: UUID,
    payload: EmployeeStatusTransitionRequest,
    actor: CanAccessSensitive,
    session: DbSession,
) -> EmployeeDetailResponse:
    return await HrService(session).transition_employee_status(employee_id, payload, actor)


@router.get("/employees/{employee_id}/history", response_model=EmploymentHistoryListResponse)
async def get_employee_history(
    employee_id: UUID, _: CanReadEmployees, session: DbSession
) -> EmploymentHistoryListResponse:
    rows, total = await HrService(session).list_employment_history(employee_id)
    return EmploymentHistoryListResponse(
        items=[EmploymentHistoryResponse.model_validate(r) for r in rows], total=total
    )


@router.get("/employees/{employee_id}/private", response_model=EmployeeSensitiveResponse)
async def get_employee_private(
    employee_id: UUID,
    actor: CanAccessSensitive,
    session: DbSession,
    reveal_sensitive: Annotated[bool, Query()] = False,
) -> EmployeeSensitiveResponse:
    return await HrService(session).get_employee_private(
        employee_id, actor, reveal_sensitive=reveal_sensitive
    )


@router.put("/employees/{employee_id}/private", response_model=EmployeeSensitiveResponse)
async def upsert_employee_private(
    employee_id: UUID,
    payload: EmployeePrivateUpdateRequest,
    actor: CanAccessSensitive,
    session: DbSession,
) -> EmployeeSensitiveResponse:
    return await HrService(session).upsert_employee_private(employee_id, payload, actor)


@router.post("/employees/{employee_id}/link-account", response_model=EmployeeDetailResponse)
async def link_employee_account(
    employee_id: UUID,
    payload: EmployeeLinkAccountRequest,
    actor: CanManageUsers,
    session: DbSession,
) -> EmployeeDetailResponse:
    return await HrService(session).link_employee_account(employee_id, payload, actor)


# --- Portal Access Requests & Workbook Reconciliation ---


@router.get("/access-requests", response_model=AccessRequestListResponse)
async def list_access_requests(
    _: CanAccessQueue,
    session: DbSession,
    request_status: Annotated[str | None, Query()] = None,
) -> AccessRequestListResponse:
    rows, total = await HrService(session).list_access_requests(status=request_status)
    return AccessRequestListResponse(
        items=[AccessRequestResponse.model_validate(r) for r in rows], total=total
    )


@router.post(
    "/access-requests",
    response_model=AccessRequestResponse,
    status_code=status.HTTP_201_CREATED,
)
async def create_access_request(
    payload: AccessRequestCreateRequest, actor: CanManageEmployees, session: DbSession
) -> AccessRequestResponse:
    req = await HrService(session).create_access_request(payload, actor)
    return AccessRequestResponse.model_validate(req)


@router.post("/access-requests/{request_id}/decision", response_model=AccessRequestResponse)
async def decide_access_request(
    request_id: UUID,
    payload: AccessRequestDecisionRequest,
    actor: CanDecideAccess,
    session: DbSession,
) -> AccessRequestResponse:
    req = await HrService(session).decide_access_request(request_id, payload, actor)
    return AccessRequestResponse.model_validate(req)


@router.post("/imports/workbook-preview", response_model=WorkbookPreviewResponse)
async def preview_hr_workbook(
    actor: CanManageEmployees,
    session: DbSession,
    file: Annotated[UploadFile, File()],
    explicit_role_overrides_json: Annotated[str | None, Form()] = None,
) -> WorkbookPreviewResponse:
    upload_limit = 10 * 1024 * 1024
    content = await file.read(upload_limit + 1)
    if len(content) > upload_limit:
        raise AppException("Workbook exceeds 10 MiB.", status_code=413)
    overrides: dict[str, str] = {}
    if explicit_role_overrides_json:
        try:
            parsed = json.loads(explicit_role_overrides_json)
            if not isinstance(parsed, dict):
                raise ValueError("must be an object")
            overrides = {str(k): str(v) for k, v in parsed.items()}
        except ValueError as exc:
            raise AppException(
                "explicit_role_overrides_json must be a JSON object mapping titles to roles.",
                status_code=422,
                error_code="INVALID_ROLE_OVERRIDES_JSON",
            ) from exc
    rows = parse_workbook_bytes(content)
    res = await preview_workbook(session, rows, explicit_role_overrides=overrides)
    await AuditService(session).record(
        action="hr.workbook.previewed",
        user_id=actor.id,
        entity_type="hr_employees",
        new_values={
            "total_rows": res.total_rows,
            "blocked_missing_email": res.blocked_missing_email_rows,
            "unmapped_roles": res.unmapped_role_rows,
        },
    )
    await session.commit()
    return res


@router.post("/imports/workbook-apply", response_model=WorkbookApplyResponse)
async def apply_hr_workbook(
    payload: WorkbookApplyRequest, actor: CanManageEmployees, session: DbSession
) -> WorkbookApplyResponse:
    return await apply_workbook(session, payload, actor)


# --- Recruitment & Onboarding ---


@router.get("/requisitions", response_model=RequisitionListResponse)
async def list_requisitions(
    _: CanManageRecruitment,
    session: DbSession,
    req_status: Annotated[str | None, Query()] = None,
) -> RequisitionListResponse:
    rows, total = await HrService(session).list_requisitions(status=req_status)
    return RequisitionListResponse(
        items=[RequisitionResponse.model_validate(r) for r in rows], total=total
    )


@router.post(
    "/requisitions", response_model=RequisitionResponse, status_code=status.HTTP_201_CREATED
)
async def create_requisition(
    payload: RequisitionCreateRequest, actor: CanManageRecruitment, session: DbSession
) -> RequisitionResponse:
    row = await HrService(session).create_requisition(payload, actor)
    return RequisitionResponse.model_validate(row)


@router.post("/requisitions/{requisition_id}/decision", response_model=RequisitionResponse)
async def decide_requisition(
    requisition_id: UUID,
    payload: RequisitionDecisionRequest,
    actor: CanManageRecruitment,
    session: DbSession,
) -> RequisitionResponse:
    row = await HrService(session).decide_requisition(requisition_id, payload, actor)
    return RequisitionResponse.model_validate(row)


@router.get("/candidates", response_model=CandidateListResponse)
async def list_candidates(
    _: CanManageRecruitment,
    session: DbSession,
    search: Annotated[str | None, Query()] = None,
) -> CandidateListResponse:
    rows, total = await HrService(session).list_candidates(search=search)
    return CandidateListResponse(
        items=[CandidateResponse.model_validate(r) for r in rows], total=total
    )


@router.post("/candidates", response_model=CandidateResponse, status_code=status.HTTP_201_CREATED)
async def create_candidate(
    payload: CandidateCreateRequest, actor: CanManageRecruitment, session: DbSession
) -> CandidateResponse:
    row = await HrService(session).create_candidate(payload, actor)
    return CandidateResponse.model_validate(row)


@router.get("/applications", response_model=ApplicationListResponse)
async def list_applications(
    _: CanManageRecruitment,
    session: DbSession,
    requisition_id: Annotated[UUID | None, Query()] = None,
) -> ApplicationListResponse:
    rows, total = await HrService(session).list_applications(requisition_id=requisition_id)
    return ApplicationListResponse(
        items=[ApplicationResponse.model_validate(r) for r in rows], total=total
    )


@router.post(
    "/applications", response_model=ApplicationResponse, status_code=status.HTTP_201_CREATED
)
async def create_application(
    payload: ApplicationCreateRequest, actor: CanManageRecruitment, session: DbSession
) -> ApplicationResponse:
    row = await HrService(session).create_application(payload, actor)
    return ApplicationResponse.model_validate(row)


@router.patch("/applications/{application_id}/stage", response_model=ApplicationResponse)
async def update_application_stage(
    application_id: UUID,
    payload: ApplicationStageUpdateRequest,
    actor: CanManageRecruitment,
    session: DbSession,
) -> ApplicationResponse:
    row = await HrService(session).update_application_stage(application_id, payload, actor)
    return ApplicationResponse.model_validate(row)


@router.get("/interviews", response_model=InterviewListResponse)
async def list_interviews(
    _: CanManageRecruitment,
    session: DbSession,
    application_id: Annotated[UUID | None, Query()] = None,
) -> InterviewListResponse:
    rows, total = await HrService(session).list_interviews(application_id=application_id)
    return InterviewListResponse(
        items=[InterviewResponse.model_validate(r) for r in rows], total=total
    )


@router.post("/interviews", response_model=InterviewResponse, status_code=status.HTTP_201_CREATED)
async def create_interview(
    payload: InterviewCreateRequest, actor: CanManageRecruitment, session: DbSession
) -> InterviewResponse:
    row = await HrService(session).create_interview(payload, actor)
    return InterviewResponse.model_validate(row)


@router.patch("/interviews/{interview_id}", response_model=InterviewResponse)
async def update_interview(
    interview_id: UUID,
    payload: InterviewUpdateRequest,
    actor: CanManageRecruitment,
    session: DbSession,
) -> InterviewResponse:
    row = await HrService(session).update_interview(interview_id, payload, actor)
    return InterviewResponse.model_validate(row)


@router.get("/offers", response_model=OfferListResponse)
async def list_offers(
    _: CanManageRecruitment,
    session: DbSession,
    offer_status: Annotated[str | None, Query()] = None,
) -> OfferListResponse:
    rows, total = await HrService(session).list_offers(status=offer_status)
    return OfferListResponse(items=[OfferResponse.model_validate(r) for r in rows], total=total)


@router.post("/offers", response_model=OfferResponse, status_code=status.HTTP_201_CREATED)
async def create_offer(
    payload: OfferCreateRequest, actor: CanManageRecruitment, session: DbSession
) -> OfferResponse:
    row = await HrService(session).create_offer(payload, actor)
    return OfferResponse.model_validate(row)


@router.post("/offers/{offer_id}/decision", response_model=OfferResponse)
async def decide_offer(
    offer_id: UUID,
    payload: OfferDecisionRequest,
    actor: CanManageRecruitment,
    session: DbSession,
) -> OfferResponse:
    row = await HrService(session).decide_offer(offer_id, payload, actor)
    return OfferResponse.model_validate(row)


@router.post("/offers/{offer_id}/convert", response_model=OnboardingCaseResponse)
async def convert_offer(
    offer_id: UUID,
    payload: OfferConvertRequest,
    actor: CanManageRecruitment,
    session: DbSession,
) -> OnboardingCaseResponse:
    return await HrService(session).convert_offer_to_employee(offer_id, payload, actor)


@router.get("/onboarding", response_model=OnboardingCaseListResponse)
async def list_onboarding(
    _: CanManageOnboarding,
    session: DbSession,
    employee_id: Annotated[UUID | None, Query()] = None,
) -> OnboardingCaseListResponse:
    items, total = await HrService(session).list_onboarding_cases(employee_id=employee_id)
    return OnboardingCaseListResponse(items=items, total=total)


@router.post(
    "/onboarding", response_model=OnboardingCaseResponse, status_code=status.HTTP_201_CREATED
)
async def create_onboarding(
    payload: OnboardingCaseCreateRequest, actor: CanManageOnboarding, session: DbSession
) -> OnboardingCaseResponse:
    return await HrService(session).create_onboarding_case(payload, actor)


@router.patch("/onboarding/tasks/{task_id}", response_model=OnboardingCaseResponse)
async def update_onboarding_task(
    task_id: UUID,
    payload: OnboardingTaskUpdateRequest,
    actor: CanManageOnboarding,
    session: DbSession,
) -> OnboardingCaseResponse:
    return await HrService(session).update_onboarding_task(task_id, payload, actor)


@router.post("/onboarding/{case_id}/probation-review", response_model=OnboardingCaseResponse)
async def record_probation_review(
    case_id: UUID,
    payload: ProbationReviewRequest,
    actor: CanAccessSensitive,
    session: DbSession,
) -> OnboardingCaseResponse:
    return await HrService(session).record_probation_review(case_id, payload, actor)


# --- HR Document Vault & Compliance ---


@router.get("/documents", response_model=HrDocumentListResponse)
async def list_hr_documents(
    actor: CanManageDocuments,
    session: DbSession,
    employee_id: Annotated[UUID | None, Query()] = None,
    candidate_id: Annotated[UUID | None, Query()] = None,
    category: Annotated[str | None, Query()] = None,
    document_type: Annotated[str | None, Query(max_length=40)] = None,
) -> HrDocumentListResponse:
    items, total = await HrService(session).list_hr_documents(
        actor=actor,
        employee_id=employee_id,
        candidate_id=candidate_id,
        category=category,
        document_type=document_type,
    )
    return HrDocumentListResponse(items=items, total=total)


@router.post("/documents", response_model=HrDocumentResponse, status_code=status.HTTP_201_CREATED)
async def upload_hr_document(
    actor: CanManageDocuments,
    session: DbSession,
    file: Annotated[UploadFile, File()],
    title: Annotated[str, Form(min_length=1, max_length=255)],
    document_type: Annotated[str, Form(min_length=1, max_length=40)],
    category: Annotated[HrDocumentCategory, Form()] = "ordinary",
    employee_id: Annotated[UUID | None, Form()] = None,
    candidate_id: Annotated[UUID | None, Form()] = None,
    issue_date: Annotated[date | None, Form()] = None,
    expiry_date: Annotated[date | None, Form()] = None,
    issuing_authority: Annotated[str | None, Form(max_length=160)] = None,
    reference_number: Annotated[str | None, Form(max_length=80)] = None,
    is_employee_visible: Annotated[bool, Form()] = False,
) -> HrDocumentResponse:
    return await HrService(session).upload_hr_document(
        title=title,
        document_type=document_type,
        category=category,
        employee_id=employee_id,
        candidate_id=candidate_id,
        issue_date=issue_date,
        expiry_date=expiry_date,
        issuing_authority=issuing_authority,
        reference_number=reference_number,
        is_employee_visible=is_employee_visible,
        file=file,
        actor=actor,
    )


@router.post(
    "/documents/{document_id}/versions", response_model=HrDocumentResponse, status_code=201
)
async def upload_hr_document_version(
    document_id: UUID,
    actor: CanManageDocuments,
    session: DbSession,
    file: Annotated[UploadFile, File()],
) -> HrDocumentResponse:
    return await HrService(session).upload_hr_document_version(document_id, file, actor)


@router.post(
    "/documents/{document_id}/versions/{version_number}/decision", response_model=HrDocumentResponse
)
async def decide_hr_document_version(
    document_id: UUID,
    version_number: int,
    payload: HrDocumentDecisionRequest,
    actor: CanAccessSensitive,
    session: DbSession,
) -> HrDocumentResponse:
    return await HrService(session).decide_hr_document_version(
        document_id, version_number, payload, actor
    )


@router.get("/documents/{document_id}/download", response_model=HrDocumentDownloadResponse)
async def download_hr_document(
    document_id: UUID,
    actor: CanManageDocuments,
    session: DbSession,
    version_number: Annotated[int | None, Query(ge=1)] = None,
) -> HrDocumentDownloadResponse:
    return await HrService(session).get_hr_document_download_url(
        document_id, actor, version_number=version_number
    )


@router.get("/compliance/expiring", response_model=ExpiringComplianceResponse)
async def list_expiring_compliance(
    actor: CanManageCompliance,
    session: DbSession,
    within_days: Annotated[int, Query(ge=1, le=365)] = 30,
) -> ExpiringComplianceResponse:
    return await HrService(session).list_expiring_compliance(within_days=within_days, actor=actor)


# --- Calendars, Shifts, Attendance, Corrections, Timesheets, Overtime ---


@router.get("/calendars", response_model=WorkCalendarListResponse)
async def list_calendars(_: CanRecordAttendance, session: DbSession) -> WorkCalendarListResponse:
    rows, total = await HrService(session).list_work_calendars()
    return WorkCalendarListResponse(
        items=[WorkCalendarResponse.model_validate(r) for r in rows], total=total
    )


@router.post("/calendars", response_model=WorkCalendarResponse, status_code=status.HTTP_201_CREATED)
async def create_calendar(
    payload: WorkCalendarCreateRequest, actor: CanRecordAttendance, session: DbSession
) -> WorkCalendarResponse:
    row = await HrService(session).create_work_calendar(payload, actor)
    return WorkCalendarResponse.model_validate(row)


@router.patch("/calendars/{calendar_id}", response_model=WorkCalendarResponse)
async def update_calendar(
    calendar_id: UUID,
    payload: WorkCalendarUpdateRequest,
    actor: CanRecordAttendance,
    session: DbSession,
) -> WorkCalendarResponse:
    row = await HrService(session).update_work_calendar(calendar_id, payload, actor)
    return WorkCalendarResponse.model_validate(row)


@router.post("/calendars/{calendar_id}/decision", response_model=WorkCalendarResponse)
async def decide_calendar(
    calendar_id: UUID,
    payload: WorkCalendarDecisionRequest,
    actor: CanRecordAttendance,
    session: DbSession,
) -> WorkCalendarResponse:
    row = await HrService(session).decide_work_calendar(calendar_id, payload, actor)
    return WorkCalendarResponse.model_validate(row)


@router.get("/schedule", response_model=WorkScheduleResponse)
async def get_work_schedule(
    employee_id: UUID,
    work_date: date,
    _: CanRecordAttendance,
    session: DbSession,
) -> WorkScheduleResponse:
    return await HrService(session).get_work_schedule(employee_id, work_date)


@router.get("/holidays", response_model=HolidayListResponse)
async def list_holidays(
    _: CanRecordAttendance,
    session: DbSession,
    calendar_id: Annotated[UUID | None, Query()] = None,
) -> HolidayListResponse:
    rows, total = await HrService(session).list_holidays(calendar_id=calendar_id)
    return HolidayListResponse(items=[HolidayResponse.model_validate(r) for r in rows], total=total)


@router.post("/holidays", response_model=HolidayResponse, status_code=status.HTTP_201_CREATED)
async def create_holiday(
    payload: HolidayCreateRequest, actor: CanRecordAttendance, session: DbSession
) -> HolidayResponse:
    row = await HrService(session).create_holiday(payload, actor)
    return HolidayResponse.model_validate(row)


@router.get("/shifts", response_model=ShiftAssignmentListResponse)
async def list_shifts(
    _: CanRecordAttendance,
    session: DbSession,
    employee_id: Annotated[UUID | None, Query()] = None,
) -> ShiftAssignmentListResponse:
    rows, total = await HrService(session).list_shift_assignments(employee_id=employee_id)
    return ShiftAssignmentListResponse(
        items=[ShiftAssignmentResponse.model_validate(r) for r in rows], total=total
    )


@router.post("/shifts", response_model=ShiftAssignmentResponse, status_code=status.HTTP_201_CREATED)
async def create_shift(
    payload: ShiftAssignmentCreateRequest, actor: CanManagePolicy, session: DbSession
) -> ShiftAssignmentResponse:
    row = await HrService(session).create_shift_assignment(payload, actor)
    return ShiftAssignmentResponse.model_validate(row)


@router.get("/attendance", response_model=AttendanceEntryListResponse)
async def list_attendance(
    _: CanRecordAttendance,
    session: DbSession,
    employee_id: Annotated[UUID | None, Query()] = None,
    date_from: Annotated[date | None, Query()] = None,
    date_to: Annotated[date | None, Query()] = None,
) -> AttendanceEntryListResponse:
    rows, total = await HrService(session).list_attendance(
        employee_id=employee_id, date_from=date_from, date_to=date_to
    )
    return AttendanceEntryListResponse(
        items=[AttendanceEntryResponse.model_validate(r) for r in rows], total=total
    )


@router.post(
    "/attendance", response_model=AttendanceEntryResponse, status_code=status.HTTP_201_CREATED
)
async def record_attendance(
    payload: AttendanceEntryCreateRequest, actor: CanRecordAttendance, session: DbSession
) -> AttendanceEntryResponse:
    if payload.source != "manual":
        raise AppException(
            "Use manual entry, the attendance import or the correction workflow.", status_code=422
        )
    row = await HrService(session).record_attendance(payload, actor)
    return AttendanceEntryResponse.model_validate(row)


@router.post("/attendance/{entry_id}/decision", response_model=AttendanceEntryResponse)
async def decide_attendance_entry(
    entry_id: UUID,
    payload: AttendanceReviewRequest,
    actor: CanApproveAttendance,
    session: DbSession,
) -> AttendanceEntryResponse:
    entry = await HrService(session).decide_attendance(entry_id, payload, actor)
    return AttendanceEntryResponse.model_validate(entry)


@router.post("/attendance/imports/preview", response_model=AttendanceImportPreviewResponse)
async def preview_attendance_import(
    actor: CanRecordAttendance, session: DbSession, file: UploadFile
) -> AttendanceImportPreviewResponse:
    return await review_attendance_csv(
        HrService(session), await file.read(MAX_ATTENDANCE_CSV_BYTES + 1), actor
    )


@router.post(
    "/attendance/imports/apply", response_model=AttendanceImportPreviewResponse, status_code=201
)
async def apply_attendance_import(
    actor: CanRecordAttendance,
    session: DbSession,
    file: UploadFile,
    expected_digest: Annotated[str, Form(pattern=r"^[0-9a-f]{64}$")],
) -> AttendanceImportPreviewResponse:
    return await review_attendance_csv(
        HrService(session),
        await file.read(MAX_ATTENDANCE_CSV_BYTES + 1),
        actor,
        expected_digest=expected_digest,
    )


@router.get("/attendance/corrections", response_model=AttendanceCorrectionListResponse)
async def list_attendance_corrections(
    _: CanRecordAttendance,
    session: DbSession,
    employee_id: Annotated[UUID | None, Query()] = None,
) -> AttendanceCorrectionListResponse:
    rows, total = await HrService(session).list_attendance_corrections(employee_id=employee_id)
    return AttendanceCorrectionListResponse(
        items=[AttendanceCorrectionResponse.model_validate(r) for r in rows], total=total
    )


@router.post(
    "/attendance/corrections",
    response_model=AttendanceCorrectionResponse,
    status_code=status.HTTP_201_CREATED,
)
async def create_attendance_correction(
    payload: AttendanceCorrectionCreateRequest, actor: CanRecordAttendance, session: DbSession
) -> AttendanceCorrectionResponse:
    row = await HrService(session).create_attendance_correction(payload, actor)
    return AttendanceCorrectionResponse.model_validate(row)


@router.post(
    "/attendance/corrections/{correction_id}/decision",
    response_model=AttendanceCorrectionResponse,
)
async def decide_attendance_correction(
    correction_id: UUID,
    payload: AttendanceCorrectionDecisionRequest,
    actor: CanApproveAttendance,
    session: DbSession,
) -> AttendanceCorrectionResponse:
    row = await HrService(session).decide_attendance_correction(correction_id, payload, actor)
    return AttendanceCorrectionResponse.model_validate(row)


@router.get("/timesheets", response_model=TimesheetListResponse)
async def list_timesheets(
    _: CanRecordAttendance,
    session: DbSession,
    employee_id: Annotated[UUID | None, Query()] = None,
) -> TimesheetListResponse:
    rows, total = await HrService(session).list_timesheets(employee_id=employee_id)
    return TimesheetListResponse(
        items=[TimesheetResponse.model_validate(r) for r in rows], total=total
    )


@router.post("/timesheets", response_model=TimesheetResponse, status_code=status.HTTP_201_CREATED)
async def create_timesheet(
    payload: TimesheetCreateRequest, actor: CanRecordAttendance, session: DbSession
) -> TimesheetResponse:
    row = await HrService(session).create_timesheet(payload, actor)
    return TimesheetResponse.model_validate(row)


@router.post("/timesheets/{timesheet_id}/decision", response_model=TimesheetResponse)
async def decide_timesheet(
    timesheet_id: UUID,
    payload: TimesheetDecisionRequest,
    actor: CanApproveAttendance,
    session: DbSession,
) -> TimesheetResponse:
    row = await HrService(session).decide_timesheet(timesheet_id, payload, actor)
    return TimesheetResponse.model_validate(row)


@router.get("/overtime", response_model=OvertimeRequestListResponse)
async def list_overtime_requests(
    _: CanRecordAttendance,
    session: DbSession,
    employee_id: Annotated[UUID | None, Query()] = None,
) -> OvertimeRequestListResponse:
    rows, total = await HrService(session).list_overtime_requests(employee_id=employee_id)
    return OvertimeRequestListResponse(
        items=[OvertimeRequestResponse.model_validate(r) for r in rows], total=total
    )


@router.post(
    "/overtime", response_model=OvertimeRequestResponse, status_code=status.HTTP_201_CREATED
)
async def create_overtime_request(
    payload: OvertimeRequestCreateRequest, actor: CanRecordAttendance, session: DbSession
) -> OvertimeRequestResponse:
    row = await HrService(session).create_overtime_request(payload, actor)
    return OvertimeRequestResponse.model_validate(row)


@router.post("/overtime/{overtime_id}/decision", response_model=OvertimeRequestResponse)
async def decide_overtime_request(
    overtime_id: UUID,
    payload: OvertimeDecisionRequest,
    actor: CanApproveAttendance,
    session: DbSession,
) -> OvertimeRequestResponse:
    row = await HrService(session).decide_overtime_request(overtime_id, payload, actor)
    return OvertimeRequestResponse.model_validate(row)


# --- Leave Management ---


@router.get("/leave/types", response_model=LeaveTypeListResponse)
async def list_leave_types(_: CanManageLeave, session: DbSession) -> LeaveTypeListResponse:
    rows, total = await HrService(session).list_leave_types()
    return LeaveTypeListResponse(
        items=[LeaveTypeResponse.model_validate(r) for r in rows], total=total
    )


@router.post("/leave/types", response_model=LeaveTypeResponse, status_code=status.HTTP_201_CREATED)
async def create_leave_type(
    payload: LeaveTypeCreateRequest, actor: CanManagePolicy, session: DbSession
) -> LeaveTypeResponse:
    row = await HrService(session).create_leave_type(payload, actor)
    return LeaveTypeResponse.model_validate(row)


@router.get("/leave/policies", response_model=LeavePolicyListResponse)
async def list_leave_policies(_: CanManageLeave, session: DbSession) -> LeavePolicyListResponse:
    rows, total = await HrService(session).list_leave_policies()
    return LeavePolicyListResponse(
        items=[LeavePolicyResponse.model_validate(r) for r in rows], total=total
    )


@router.post(
    "/leave/policies", response_model=LeavePolicyResponse, status_code=status.HTTP_201_CREATED
)
async def create_leave_policy(
    payload: LeavePolicyCreateRequest, actor: CanManagePolicy, session: DbSession
) -> LeavePolicyResponse:
    row = await HrService(session).create_leave_policy(payload, actor)
    return LeavePolicyResponse.model_validate(row)


@router.get("/leave/balances/{employee_id}", response_model=LeaveBalanceListResponse)
async def get_employee_leave_balances(
    employee_id: UUID,
    _: CanManageLeave,
    session: DbSession,
    leave_year: Annotated[int | None, Query()] = None,
) -> LeaveBalanceListResponse:
    return await HrService(session).get_leave_balances(employee_id, leave_year=leave_year)


@router.post(
    "/leave/ledger", response_model=LeaveLedgerEntryResponse, status_code=status.HTTP_201_CREATED
)
async def adjust_leave_ledger(
    payload: LeaveLedgerAdjustRequest, actor: CanApproveLeave, session: DbSession
) -> LeaveLedgerEntryResponse:
    row = await HrService(session).adjust_leave_ledger(payload, actor)
    return LeaveLedgerEntryResponse.model_validate(row)


@router.get("/leave/requests", response_model=LeaveRequestListResponse)
async def list_leave_requests(
    _: CanManageLeave,
    session: DbSession,
    employee_id: Annotated[UUID | None, Query()] = None,
    req_status: Annotated[str | None, Query()] = None,
) -> LeaveRequestListResponse:
    rows, total = await HrService(session).list_leave_requests(
        employee_id=employee_id, status=req_status
    )
    return LeaveRequestListResponse(
        items=[LeaveRequestResponse.model_validate(r) for r in rows], total=total
    )


@router.post(
    "/leave/requests", response_model=LeaveRequestResponse, status_code=status.HTTP_201_CREATED
)
async def create_leave_request(
    payload: LeaveRequestCreateRequest, actor: CanManageLeave, session: DbSession
) -> LeaveRequestResponse:
    row = await HrService(session).create_leave_request(payload, actor)
    return LeaveRequestResponse.model_validate(row)


@router.post("/leave/requests/{leave_request_id}/decision", response_model=LeaveRequestResponse)
async def decide_leave_request(
    leave_request_id: UUID,
    payload: LeaveRequestDecisionRequest,
    actor: CanApproveLeave,
    session: DbSession,
) -> LeaveRequestResponse:
    row = await HrService(session).decide_leave_request(leave_request_id, payload, actor)
    return LeaveRequestResponse.model_validate(row)


# --- Policies, Letter Templates, Service Requests ---


@router.get("/policies", response_model=PolicyDocumentListResponse)
async def list_policies(_: CanReadEmployees, session: DbSession) -> PolicyDocumentListResponse:
    rows, total = await HrService(session).list_policy_documents()
    return PolicyDocumentListResponse(
        items=[PolicyDocumentResponse.model_validate(r) for r in rows], total=total
    )


@router.post(
    "/policies", response_model=PolicyDocumentResponse, status_code=status.HTTP_201_CREATED
)
async def create_policy(
    payload: PolicyDocumentCreateRequest, actor: CanManagePolicy, session: DbSession
) -> PolicyDocumentResponse:
    row = await HrService(session).create_policy_document(payload, actor)
    return PolicyDocumentResponse.model_validate(row)


@router.get("/letter-templates", response_model=LetterTemplateListResponse)
async def list_letter_templates(
    _: CanProcessRequests, session: DbSession
) -> LetterTemplateListResponse:
    rows, total = await HrService(session).list_letter_templates()
    return LetterTemplateListResponse(
        items=[LetterTemplateResponse.model_validate(r) for r in rows], total=total
    )


@router.post(
    "/letter-templates", response_model=LetterTemplateResponse, status_code=status.HTTP_201_CREATED
)
async def create_letter_template(
    payload: LetterTemplateCreateRequest, actor: CanManagePolicy, session: DbSession
) -> LetterTemplateResponse:
    row = await HrService(session).create_letter_template(payload, actor)
    return LetterTemplateResponse.model_validate(row)


@router.post("/letters/render", response_model=LetterRenderResponse)
async def render_letter(
    payload: LetterGenerateRequest, actor: CanProcessRequests, session: DbSession
) -> LetterRenderResponse:
    return await HrService(session).render_letter(payload, actor)


@router.get("/requests", response_model=HrServiceRequestListResponse)
async def list_service_requests(
    _: CanProcessRequests,
    session: DbSession,
    employee_id: Annotated[UUID | None, Query()] = None,
) -> HrServiceRequestListResponse:
    rows, total = await HrService(session).list_service_requests(employee_id=employee_id)
    return HrServiceRequestListResponse(
        items=[HrServiceRequestResponse.model_validate(r) for r in rows], total=total
    )


@router.post(
    "/requests", response_model=HrServiceRequestResponse, status_code=status.HTTP_201_CREATED
)
async def create_service_request(
    payload: HrServiceRequestCreateRequest, actor: CanProcessRequests, session: DbSession
) -> HrServiceRequestResponse:
    row = await HrService(session).create_service_request(payload, actor)
    return HrServiceRequestResponse.model_validate(row)


@router.post("/requests/{req_id}/resolve", response_model=HrServiceRequestResponse)
async def resolve_service_request(
    req_id: UUID,
    payload: HrServiceRequestResolveRequest,
    actor: CanProcessRequests,
    session: DbSession,
) -> HrServiceRequestResponse:
    row = await HrService(session).resolve_service_request(req_id, payload, actor)
    return HrServiceRequestResponse.model_validate(row)


# --- Offboarding & Clearance ---


@router.get("/offboarding", response_model=OffboardingCaseListResponse)
async def list_offboarding_cases(
    _: CanManageOffboarding,
    session: DbSession,
    employee_id: Annotated[UUID | None, Query()] = None,
) -> OffboardingCaseListResponse:
    items, total = await HrService(session).list_offboarding_cases(employee_id=employee_id)
    return OffboardingCaseListResponse(items=items, total=total)


@router.post(
    "/offboarding", response_model=OffboardingCaseResponse, status_code=status.HTTP_201_CREATED
)
async def initiate_offboarding(
    payload: OffboardingInitiateRequest, actor: CanManageOffboarding, session: DbSession
) -> OffboardingCaseResponse:
    return await HrService(session).initiate_offboarding(payload, actor)


@router.patch("/offboarding/steps/{step_id}", response_model=OffboardingCaseResponse)
async def update_clearance_step(
    step_id: UUID,
    payload: OffboardingStepUpdateRequest,
    actor: CanManageOffboarding,
    session: DbSession,
) -> OffboardingCaseResponse:
    return await HrService(session).update_clearance_step(step_id, payload, actor)


@router.post("/offboarding/{case_id}/complete", response_model=OffboardingCaseResponse)
async def complete_offboarding(
    case_id: UUID,
    payload: OffboardingCompleteRequest,
    actor: CanManageOffboarding,
    session: DbSession,
) -> OffboardingCaseResponse:
    return await HrService(session).complete_offboarding(case_id, payload, actor)


# --- P2 Performance, Training, Benefits, Compensation, Payroll, Cases, Reports ---


@router.get("/goals", response_model=GoalListResponse)
async def list_goals(
    _: CanManagePerformance,
    session: DbSession,
    employee_id: Annotated[UUID | None, Query()] = None,
) -> GoalListResponse:
    rows, total = await HrService(session).list_goals(employee_id=employee_id)
    return GoalListResponse(items=[GoalResponse.model_validate(r) for r in rows], total=total)


@router.post("/goals", response_model=GoalResponse, status_code=status.HTTP_201_CREATED)
async def create_goal(
    payload: GoalCreateRequest, actor: CanManagePerformance, session: DbSession
) -> GoalResponse:
    row = await HrService(session).create_goal(payload, actor)
    return GoalResponse.model_validate(row)


@router.patch("/goals/{goal_id}", response_model=GoalResponse)
async def update_goal(
    goal_id: UUID, payload: GoalUpdateRequest, actor: CanManagePerformance, session: DbSession
) -> GoalResponse:
    row = await HrService(session).update_goal(goal_id, payload, actor)
    return GoalResponse.model_validate(row)


@router.get("/review-cycles", response_model=ReviewCycleListResponse)
async def list_review_cycles(
    _: CanManagePerformance, session: DbSession
) -> ReviewCycleListResponse:
    rows, total = await HrService(session).list_review_cycles()
    return ReviewCycleListResponse(
        items=[ReviewCycleResponse.model_validate(r) for r in rows], total=total
    )


@router.post(
    "/review-cycles", response_model=ReviewCycleResponse, status_code=status.HTTP_201_CREATED
)
async def create_review_cycle(
    payload: ReviewCycleCreateRequest, actor: CanManagePerformance, session: DbSession
) -> ReviewCycleResponse:
    row = await HrService(session).create_review_cycle(payload, actor)
    return ReviewCycleResponse.model_validate(row)


@router.get("/reviews", response_model=ReviewListResponse)
async def list_reviews(
    _: CanManagePerformance,
    session: DbSession,
    employee_id: Annotated[UUID | None, Query()] = None,
) -> ReviewListResponse:
    rows, total = await HrService(session).list_reviews(employee_id=employee_id)
    return ReviewListResponse(items=[ReviewResponse.model_validate(r) for r in rows], total=total)


@router.post("/reviews", response_model=ReviewResponse, status_code=status.HTTP_201_CREATED)
async def create_review(
    payload: ReviewCreateRequest, actor: CanManagePerformance, session: DbSession
) -> ReviewResponse:
    row = await HrService(session).create_review(payload, actor)
    return ReviewResponse.model_validate(row)


@router.get("/training/courses", response_model=TrainingCourseListResponse)
async def list_training_courses(
    _: CanManageTraining, session: DbSession
) -> TrainingCourseListResponse:
    rows, total = await HrService(session).list_training_courses()
    return TrainingCourseListResponse(
        items=[TrainingCourseResponse.model_validate(r) for r in rows], total=total
    )


@router.post(
    "/training/courses", response_model=TrainingCourseResponse, status_code=status.HTTP_201_CREATED
)
async def create_training_course(
    payload: TrainingCourseCreateRequest, actor: CanManageTraining, session: DbSession
) -> TrainingCourseResponse:
    row = await HrService(session).create_training_course(payload, actor)
    return TrainingCourseResponse.model_validate(row)


@router.get("/training/enrollments", response_model=TrainingEnrollmentListResponse)
async def list_training_enrollments(
    _: CanManageTraining,
    session: DbSession,
    employee_id: Annotated[UUID | None, Query()] = None,
) -> TrainingEnrollmentListResponse:
    rows, total = await HrService(session).list_training_enrollments(employee_id=employee_id)
    return TrainingEnrollmentListResponse(
        items=[TrainingEnrollmentResponse.model_validate(r) for r in rows], total=total
    )


@router.post(
    "/training/enrollments",
    response_model=TrainingEnrollmentResponse,
    status_code=status.HTTP_201_CREATED,
)
async def create_training_enrollment(
    payload: TrainingEnrollmentCreateRequest, actor: CanManageTraining, session: DbSession
) -> TrainingEnrollmentResponse:
    row = await HrService(session).create_training_enrollment(payload, actor)
    return TrainingEnrollmentResponse.model_validate(row)


@router.patch("/training/enrollments/{enrollment_id}", response_model=TrainingEnrollmentResponse)
async def update_training_enrollment(
    enrollment_id: UUID,
    payload: TrainingEnrollmentUpdateRequest,
    actor: CanManageTraining,
    session: DbSession,
) -> TrainingEnrollmentResponse:
    row = await HrService(session).update_training_enrollment(enrollment_id, payload, actor)
    return TrainingEnrollmentResponse.model_validate(row)


@router.get("/certifications", response_model=CertificationListResponse)
async def list_certifications(
    _: CanManageTraining,
    session: DbSession,
    employee_id: Annotated[UUID | None, Query()] = None,
) -> CertificationListResponse:
    rows, total = await HrService(session).list_certifications(employee_id=employee_id)
    return CertificationListResponse(
        items=[CertificationResponse.model_validate(r) for r in rows], total=total
    )


@router.post(
    "/certifications", response_model=CertificationResponse, status_code=status.HTTP_201_CREATED
)
async def create_certification(
    payload: CertificationCreateRequest, actor: CanManageTraining, session: DbSession
) -> CertificationResponse:
    row = await HrService(session).create_certification(payload, actor)
    return CertificationResponse.model_validate(row)


@router.get("/benefits/types", response_model=BenefitTypeListResponse)
async def list_benefit_types(
    _: CanReadPayrollSensitive, session: DbSession
) -> BenefitTypeListResponse:
    rows, total = await HrService(session).list_benefit_types()
    return BenefitTypeListResponse(
        items=[BenefitTypeResponse.model_validate(r) for r in rows], total=total
    )


@router.post(
    "/benefits/types", response_model=BenefitTypeResponse, status_code=status.HTTP_201_CREATED
)
async def create_benefit_type(
    payload: BenefitTypeCreateRequest, actor: CanReadPayrollSensitive, session: DbSession
) -> BenefitTypeResponse:
    row = await HrService(session).create_benefit_type(payload, actor)
    return BenefitTypeResponse.model_validate(row)


@router.get("/benefits/assignments", response_model=EmployeeBenefitListResponse)
async def list_employee_benefits(
    _: CanReadPayrollSensitive,
    session: DbSession,
    employee_id: Annotated[UUID | None, Query()] = None,
) -> EmployeeBenefitListResponse:
    rows, total = await HrService(session).list_employee_benefits(employee_id=employee_id)
    return EmployeeBenefitListResponse(
        items=[EmployeeBenefitResponse.model_validate(r) for r in rows], total=total
    )


@router.post(
    "/benefits/assignments",
    response_model=EmployeeBenefitResponse,
    status_code=status.HTTP_201_CREATED,
)
async def create_employee_benefit(
    payload: EmployeeBenefitCreateRequest, actor: CanReadPayrollSensitive, session: DbSession
) -> EmployeeBenefitResponse:
    row = await HrService(session).create_employee_benefit(payload, actor)
    return EmployeeBenefitResponse.model_validate(row)


@router.get("/reimbursements", response_model=ReimbursementListResponse)
async def list_reimbursements(
    _: CanReadPayrollSensitive,
    session: DbSession,
    employee_id: Annotated[UUID | None, Query()] = None,
) -> ReimbursementListResponse:
    rows, total = await HrService(session).list_reimbursements(employee_id=employee_id)
    return ReimbursementListResponse(
        items=[ReimbursementResponse.model_validate(r) for r in rows], total=total
    )


@router.post(
    "/reimbursements", response_model=ReimbursementResponse, status_code=status.HTTP_201_CREATED
)
async def create_reimbursement(
    payload: ReimbursementCreateRequest, actor: CanReadPayrollSensitive, session: DbSession
) -> ReimbursementResponse:
    row = await HrService(session).create_reimbursement(payload, actor)
    return ReimbursementResponse.model_validate(row)


@router.post("/reimbursements/{claim_id}/decision", response_model=ReimbursementResponse)
async def decide_reimbursement(
    claim_id: UUID,
    payload: ReimbursementDecisionRequest,
    actor: CanApprovePayroll,
    session: DbSession,
) -> ReimbursementResponse:
    row = await HrService(session).decide_reimbursement(claim_id, payload, actor)
    return ReimbursementResponse.model_validate(row)


@router.get("/compensation/{employee_id}", response_model=CompensationTermListResponse)
async def list_compensation(
    employee_id: UUID,
    actor: CanReadPayrollSensitive,
    session: DbSession,
    reveal_sensitive: Annotated[bool, Query()] = False,
) -> CompensationTermListResponse:
    items, total = await HrService(session).list_compensation_terms(
        employee_id=employee_id, actor=actor, reveal_sensitive=reveal_sensitive
    )
    return CompensationTermListResponse(items=items, total=total)


@router.post(
    "/compensation", response_model=CompensationTermResponse, status_code=status.HTTP_201_CREATED
)
async def create_compensation(
    payload: CompensationTermCreateRequest, actor: CanReadPayrollSensitive, session: DbSession
) -> CompensationTermResponse:
    return await HrService(session).create_compensation_term(payload, actor)


@router.get("/payroll/policies", response_model=PayrollPolicyListResponse)
async def list_payroll_policies(
    _: CanPreparePayroll, session: DbSession
) -> PayrollPolicyListResponse:
    rows, total = await HrService(session).list_payroll_policies()
    return PayrollPolicyListResponse(
        items=[PayrollPolicyResponse.model_validate(r) for r in rows], total=total
    )


@router.post(
    "/payroll/policies", response_model=PayrollPolicyResponse, status_code=status.HTTP_201_CREATED
)
async def create_payroll_policy(
    payload: PayrollPolicyCreateRequest, actor: CanPreparePayroll, session: DbSession
) -> PayrollPolicyResponse:
    row = await HrService(session).create_payroll_policy(payload, actor)
    return PayrollPolicyResponse.model_validate(row)


@router.post("/payroll/policies/{policy_id}/approve", response_model=PayrollPolicyResponse)
async def approve_payroll_policy(
    policy_id: UUID, actor: CanApprovePayroll, session: DbSession
) -> PayrollPolicyResponse:
    row = await HrService(session).approve_payroll_policy(policy_id, actor)
    return PayrollPolicyResponse.model_validate(row)


@router.get("/payroll/periods", response_model=PayrollPeriodListResponse)
async def list_payroll_periods(
    _: CanPreparePayroll, session: DbSession
) -> PayrollPeriodListResponse:
    rows, total = await HrService(session).list_payroll_periods()
    return PayrollPeriodListResponse(
        items=[PayrollPeriodResponse.model_validate(r) for r in rows], total=total
    )


@router.post(
    "/payroll/periods", response_model=PayrollPeriodResponse, status_code=status.HTTP_201_CREATED
)
async def create_payroll_period(
    payload: PayrollPeriodCreateRequest, actor: CanPreparePayroll, session: DbSession
) -> PayrollPeriodResponse:
    row = await HrService(session).create_payroll_period(payload, actor)
    return PayrollPeriodResponse.model_validate(row)


@router.get("/payroll/runs", response_model=PayrollRunListResponse)
async def list_payroll_runs(_: CanPreparePayroll, session: DbSession) -> PayrollRunListResponse:
    rows, total = await HrService(session).list_payroll_runs()
    return PayrollRunListResponse(
        items=[PayrollRunResponse.model_validate(r) for r in rows], total=total
    )


@router.post(
    "/payroll/runs", response_model=PayrollRunResponse, status_code=status.HTTP_201_CREATED
)
async def create_payroll_run(
    payload: PayrollRunCreateRequest, actor: CanPreparePayroll, session: DbSession
) -> PayrollRunResponse:
    row = await HrService(session).create_payroll_run(payload, actor)
    return PayrollRunResponse.model_validate(row)


@router.post("/payroll/runs/{run_id}/calculate", response_model=PayrollRunResponse)
async def calculate_payroll_run(
    run_id: UUID, actor: CanPreparePayroll, session: DbSession
) -> PayrollRunResponse:
    row = await HrService(session).calculate_payroll_run(run_id, actor)
    return PayrollRunResponse.model_validate(row)


@router.post("/payroll/runs/{run_id}/approve", response_model=PayrollRunResponse)
async def approve_payroll_run(
    run_id: UUID, actor: CanApprovePayroll, session: DbSession
) -> PayrollRunResponse:
    row = await HrService(session).approve_payroll_run(run_id, actor)
    return PayrollRunResponse.model_validate(row)


@router.get("/cases", response_model=HrCaseListResponse)
async def list_hr_cases(_: CanManageCases, session: DbSession) -> HrCaseListResponse:
    items, total = await HrService(session).list_hr_cases()
    return HrCaseListResponse(items=items, total=total)


@router.post("/cases", response_model=HrCaseResponse, status_code=status.HTTP_201_CREATED)
async def create_hr_case(
    payload: HrCaseCreateRequest, actor: CanManageCases, session: DbSession
) -> HrCaseResponse:
    return await HrService(session).create_hr_case(payload, actor)


@router.post("/cases/{case_id}/close", response_model=HrCaseResponse)
async def close_hr_case(
    case_id: UUID, payload: HrCaseCloseRequest, actor: CanManageCases, session: DbSession
) -> HrCaseResponse:
    return await HrService(session).close_hr_case(case_id, payload, actor)


@router.get("/reports/summary", response_model=HrSummaryReportResponse)
async def get_hr_summary_report(
    actor: CanViewHrReports, session: DbSession, filters: Annotated[HrReportFilters, Query()]
) -> HrSummaryReportResponse:
    return await get_hr_summary(session, actor, filters)


@router.get("/reports/sites", response_model=HrReportSiteListResponse)
async def list_report_sites(
    _: CanViewHrReports,
    session: DbSession,
    offset: Annotated[int, Query(ge=0)] = 0,
    limit: Annotated[int, Query(ge=1, le=100)] = 50,
) -> HrReportSiteListResponse:
    return await list_hr_report_sites(session, offset=offset, limit=limit)


@router.get(
    "/reports/summary.{output_format}",
    response_class=Response,
    responses={
        200: {
            "content": {
                media: {"schema": {"type": "string", "format": "binary"}}
                for media in HR_REPORT_MEDIA_TYPES.values()
            }
        }
    },
)
async def export_hr_summary(
    output_format: HrReportFormat,
    actor: CanViewHrReports,
    session: DbSession,
    filters: Annotated[HrReportFilters, Query()],
) -> Response:
    summary = await get_hr_summary(session, actor, filters)
    return Response(
        build_hr_summary_export(summary, output_format),
        media_type=HR_REPORT_MEDIA_TYPES[output_format],
        headers={"Content-Disposition": f'attachment; filename="hr-summary.{output_format}"'},
    )
