import json
from collections.abc import Callable
from datetime import date
from typing import Annotated, Literal
from uuid import UUID

from fastapi import APIRouter, Depends, File, Form, Header, Query, UploadFile, status
from fastapi.responses import Response

from app.api.dependencies import CurrentUser, DbSession, require_permission
from app.config import get_settings
from app.models.hr import HrEmployee
from app.models.user import User
from app.schemas.hr import (
    AccessRequestCreateRequest,
    AccessRequestDecisionRequest,
    AccessRequestListResponse,
    AccessRequestResponse,
    ApplicationActivityList,
    ApplicationCreateRequest,
    ApplicationListResponse,
    ApplicationResponse,
    ApplicationStage,
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
    CandidateCorrespondenceCreateRequest,
    CandidateCorrespondenceDecisionRequest,
    CandidateCorrespondenceDetail,
    CandidateCreateRequest,
    CandidateListResponse,
    CandidateResponse,
    CertificationCreateRequest,
    CertificationListResponse,
    CertificationResponse,
    CompensationTermCreateRequest,
    CompensationTermDecisionRequest,
    CompensationTermListResponse,
    CompensationTermResponse,
    DepartmentCreateRequest,
    DepartmentListResponse,
    DepartmentResponse,
    DepartmentUpdateRequest,
    DueEmploymentChangeList,
    EmployeeAdvanceDecision,
    EmployeeAdvanceDisbursement,
    EmployeeAdvanceListResponse,
    EmployeeAdvancePayment,
    EmployeeAdvanceRequest,
    EmployeeAdvanceResponse,
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
    EmploymentChangeDecision,
    EmploymentChangeListResponse,
    EmploymentChangeProposal,
    EmploymentChangeResponse,
    EmploymentHistoryListResponse,
    EmploymentHistoryResponse,
    EmploymentPeriodListResponse,
    EmploymentPeriodMissingStartPage,
    EmploymentPeriodResponse,
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
    HrProjectAssignmentCreateRequest,
    HrProjectAssignmentListResponse,
    HrProjectAssignmentResponse,
    HrReportFilters,
    HrReportSiteListResponse,
    HrServiceRequestAssignee,
    HrServiceRequestAssignmentRequest,
    HrServiceRequestCreateRequest,
    HrServiceRequestListResponse,
    HrServiceRequestReopenRequest,
    HrServiceRequestResolveRequest,
    HrServiceRequestResponse,
    HrSummaryReportResponse,
    HrWorkflowOptionsResponse,
    InterviewCreateRequest,
    InterviewerOptions,
    InterviewListResponse,
    InterviewResponse,
    InterviewUpdateRequest,
    LeaveAccrualApplyRequest,
    LeaveAccrualCatchUpApplyRequest,
    LeaveAccrualCatchUpRequest,
    LeaveAccrualCatchUpResponse,
    LeaveAccrualRequest,
    LeaveAccrualResponse,
    LeaveBalanceListResponse,
    LeaveDateEvidenceCandidates,
    LeaveDateEvidenceCreate,
    LeaveDateEvidenceDecision,
    LeaveDateEvidencePage,
    LeaveDateEvidenceResponse,
    LeaveLedgerAdjustRequest,
    LeaveLedgerEntryResponse,
    LeavePolicyCreateRequest,
    LeavePolicyDecisionRequest,
    LeavePolicyListResponse,
    LeavePolicyResponse,
    LeaveRequestCreateRequest,
    LeaveRequestDecisionRequest,
    LeaveRequestDecisionState,
    LeaveRequestListResponse,
    LeaveRequestResponse,
    LeaveRequestResubmitRequest,
    LeaveRolloverApplyRequest,
    LeaveRolloverRequest,
    LeaveRolloverResponse,
    LeaveTypeCreateRequest,
    LeaveTypeListResponse,
    LeaveTypeResponse,
    LeaveUnitsQuery,
    LeaveUnitsResponse,
    LetterDecisionRequest,
    LetterDetail,
    LetterDraftRequest,
    LetterGenerateRequest,
    LetterListResponse,
    LetterRenderResponse,
    LetterTemplateCreateRequest,
    LetterTemplateListResponse,
    LetterTemplateResponse,
    ManagerReviewDecisionRequest,
    ManagerReviewItemResponse,
    ManagerReviewKind,
    ManagerReviewListResponse,
    MyPolicyFileResponse,
    MyPolicyListResponse,
    OffboardingCaseListResponse,
    OffboardingCaseResponse,
    OffboardingCompleteRequest,
    OffboardingCustodyArea,
    OffboardingCustodyListResponse,
    OffboardingCustodyRequest,
    OffboardingCustodyResponse,
    OffboardingInitiateRequest,
    OffboardingStepUpdateRequest,
    OfferConvertRequest,
    OfferCreateRequest,
    OfferDecisionRequest,
    OfferListResponse,
    OfferReissueRequest,
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
    PayrollAdjustmentCreate,
    PayrollAdjustmentList,
    PayrollAdjustmentResponse,
    PayrollAdjustmentReview,
    PayrollClosureRequest,
    PayrollClosureResponse,
    PayrollCorrectionCreate,
    PayrollCorrectionDecision,
    PayrollCorrectionPage,
    PayrollCorrectionResponse,
    PayrollExportConfirmRequest,
    PayrollExportPreview,
    PayrollExportReceipt,
    PayrollLeaveInputPreview,
    PayrollPeriodCreateRequest,
    PayrollPeriodListResponse,
    PayrollPeriodResponse,
    PayrollPolicyApproveRequest,
    PayrollPolicyCreateRequest,
    PayrollPolicyDraftUpdateRequest,
    PayrollPolicyListResponse,
    PayrollPolicyResponse,
    PayrollRunApproveRequest,
    PayrollRunCalculateRequest,
    PayrollRunCreateRequest,
    PayrollRunListResponse,
    PayrollRunResponse,
    PayrollRunSnapshotResponse,
    PayrollSettlementEventResponse,
    PayrollSettlementEventsResponse,
    PayrollSettlementRequest,
    PayrollSettlementSummary,
    PayrollSnapshotCalculateRequest,
    PayrollTimeDownloadRequest,
    PayrollTimeInputPreview,
    PayslipDetail,
    PayslipListResponse,
    PayslipPublicationResponse,
    PerformanceReviewActionRequest,
    PerformanceReviewDetail,
    PerformanceReviewQueue,
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
    ReimbursementOperatorListResponse,
    ReimbursementOperatorResponse,
    ReimbursementPayableResponse,
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
    RosterAllocationCreateRequest,
    RosterAllocationListResponse,
    RosterAllocationResponse,
    RosterCancellationRequest,
    SelfTrainingListResponse,
    SeparationSettlementListResponse,
    SeparationSettlementProposal,
    SeparationSettlementResponse,
    SeparationSettlementReview,
    ShiftAssignmentCreateRequest,
    ShiftAssignmentListResponse,
    ShiftAssignmentResponse,
    SiteAttendanceCorrectionRequest,
    SiteAttendanceCreateRequest,
    SiteAttendanceDecisionRequest,
    SiteAttendancePageResponse,
    SiteAttendanceResponse,
    SiteAttendanceSubmissionResponse,
    SiteAttendanceWorkerPage,
    TimesheetCreateRequest,
    TimesheetDecisionRequest,
    TimesheetListResponse,
    TimesheetResponse,
    TimesheetSelfCreateRequest,
    TimesheetSelfResubmitRequest,
    TrainingCompletionRequest,
    TrainingCompletionResponse,
    TrainingCourseCreateRequest,
    TrainingCourseListResponse,
    TrainingCourseResponse,
    TrainingEnrollmentCreateRequest,
    TrainingEnrollmentListResponse,
    TrainingEnrollmentResponse,
    TrainingEnrollmentUpdateRequest,
    TrainingRequirementCreateRequest,
    TrainingRequirementListResponse,
    TrainingRequirementStatusListResponse,
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
from app.schemas.projects import ProjectOptionListResponse
from app.services.audit_service import AuditService
from app.services.hr_attendance_import import MAX_ATTENDANCE_CSV_BYTES, review_attendance_csv
from app.services.hr_leave_accrual import process_leave_accrual, process_leave_accrual_catch_up
from app.services.hr_leave_date_evidence import (
    decide_leave_date_evidence,
    list_leave_date_evidence,
    list_missing_leave_dates,
    propose_leave_date_evidence,
    read_leave_date_evidence,
)
from app.services.hr_leave_rollover import process_leave_rollover
from app.services.hr_manager_review import (
    can_review_direct_reports,
    list_manager_reviews,
    recommend_request,
)
from app.services.hr_offboarding_custody import list_offboarding_custody, record_offboarding_custody
from app.services.hr_payroll_correction import (
    decide_payroll_correction,
    list_payroll_corrections,
    propose_payroll_correction,
    read_payroll_correction,
)
from app.services.hr_payroll_export import (
    download_payroll_export,
    preview_payroll_export,
    register_payroll_export,
)
from app.services.hr_payroll_settlement import (
    close_payroll_period,
    list_payroll_settlement_events,
    read_payroll_settlement_event,
    record_payroll_settlement,
    summarize_payroll_settlements,
)
from app.services.hr_payroll_snapshot import (
    approve_payroll_snapshot,
    calculate_payroll_snapshot,
    get_payroll_run,
    list_employee_payslips,
    publish_payslips,
    read_employee_payslip,
    read_frozen_payroll_source,
    read_payroll_adjustments,
    read_payroll_snapshot,
    review_payroll_adjustment,
    submit_payroll_adjustment,
)
from app.services.hr_payroll_time import payroll_leave_inputs, payroll_time_inputs
from app.services.hr_performance import (
    get_performance_review,
    list_performance_reviews,
    record_performance_action,
)
from app.services.hr_project_assignment import HrProjectAssignmentService
from app.services.hr_reporting import (
    HR_REPORT_MEDIA_TYPES,
    HrReportFormat,
    build_hr_summary_export,
    get_hr_summary,
    list_hr_report_sites,
)
from app.services.hr_separation_settlement import (
    list_separation_settlements,
    propose_separation_settlement,
    review_separation_settlement,
)
from app.services.hr_service import HrService
from app.services.hr_site_attendance_service import HrSiteAttendanceService
from app.services.hr_training_requirements import (
    deactivate_rule,
    list_employee_requirements,
    list_rules,
    save_rule,
)
from app.services.hr_workbook import apply_workbook, preview_workbook_upload
from app.utils.exceptions import (
    AppException,
    NotFoundException,
    PermissionDeniedException,
)
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
    PERMISSION_INVENTORY_MANAGE,
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
async def get_my_hr_profile(
    current_user: CurrentUser, session: DbSession, response: Response
) -> EmployeeSelfResponse:
    response.headers["Cache-Control"] = "no-store"
    return await HrService(session).get_self_profile(current_user)


@router.patch("/me", response_model=EmployeeSelfResponse)
async def update_my_hr_profile(
    payload: EmployeeSelfUpdateRequest,
    current_user: CurrentUser,
    session: DbSession,
    response: Response,
) -> EmployeeSelfResponse:
    response.headers["Cache-Control"] = "no-store"
    return await HrService(session).update_self_profile(payload, current_user)


@router.get("/me/training/requirements", response_model=TrainingRequirementStatusListResponse)
async def get_my_training_requirements(
    current_user: CurrentUser,
    session: DbSession,
    limit: Annotated[int, Query(ge=1, le=100)] = 20,
    offset: Annotated[int, Query(ge=0)] = 0,
) -> TrainingRequirementStatusListResponse:
    employee = await HrService(session).require_self_employee(current_user)
    return await list_employee_requirements(session, employee, limit=limit, offset=offset)


@router.get("/me/training", response_model=SelfTrainingListResponse)
async def get_my_training(
    current_user: CurrentUser,
    session: DbSession,
    limit: Annotated[int, Query(ge=1, le=100)] = 20,
    offset: Annotated[int, Query(ge=0)] = 0,
) -> SelfTrainingListResponse:
    return await HrService(session).list_self_training(current_user, limit=limit, offset=offset)


@router.get("/me/payslips", response_model=PayslipListResponse)
async def list_my_payslips(
    current_user: CurrentUser,
    session: DbSession,
    limit: Annotated[int, Query(ge=1, le=50)] = 20,
    offset: Annotated[int, Query(ge=0)] = 0,
) -> PayslipListResponse:
    employee = await HrService(session).require_self_employee(current_user)
    return await list_employee_payslips(session, employee.id, limit, offset)


@router.get("/me/payslips/{run_id}", response_model=PayslipDetail)
async def get_my_payslip(
    run_id: UUID, current_user: CurrentUser, session: DbSession
) -> PayslipDetail:
    employee = await HrService(session).require_self_employee(current_user)
    return await read_employee_payslip(session, run_id, employee.id, current_user)


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


@router.get("/me/leave-units", response_model=LeaveUnitsResponse)
async def quote_my_leave_units(
    payload: Annotated[LeaveUnitsQuery, Query()],
    current_user: CurrentUser,
    session: DbSession,
) -> LeaveUnitsResponse:
    service = HrService(session)
    employee = await service.require_self_employee(current_user)
    return LeaveUnitsResponse(days_requested=await service.get_leave_units(employee, payload))


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


@router.put("/me/leave-requests/{request_id}/submission", response_model=LeaveRequestResponse)
async def resubmit_my_leave_request(
    request_id: UUID,
    payload: LeaveRequestResubmitRequest,
    current_user: CurrentUser,
    session: DbSession,
) -> LeaveRequestResponse:
    req = await HrService(session).resubmit_own_leave_request(request_id, payload, current_user)
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


@router.get("/me/policies", response_model=MyPolicyListResponse)
async def list_my_policies(
    current_user: CurrentUser, session: DbSession, response: Response
) -> MyPolicyListResponse:
    response.headers["Cache-Control"] = "no-store"
    return await HrService(session).list_self_policies(current_user)


@router.get("/me/policies/{policy_id}/download", response_model=MyPolicyFileResponse)
async def download_my_policy(
    policy_id: UUID, current_user: CurrentUser, session: DbSession, response: Response
) -> MyPolicyFileResponse:
    response.headers["Cache-Control"] = "no-store"
    return await HrService(session).get_self_policy_download_url(policy_id, current_user)


@router.post("/me/policies/{policy_id}/acknowledge", response_model=PolicyAcknowledgementResponse)
async def acknowledge_hr_policy(
    policy_id: UUID,
    payload: PolicyAcknowledgeRequest,
    current_user: CurrentUser,
    session: DbSession,
    response: Response,
) -> PolicyAcknowledgementResponse:
    response.headers["Cache-Control"] = "no-store"
    return await HrService(session).acknowledge_policy(policy_id, payload, current_user)


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
    current_user: CanReadPayrollSensitive, session: DbSession, response: Response
) -> ReimbursementListResponse:
    response.headers["Cache-Control"] = "no-store"
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
    response: Response,
    idempotency_key: Annotated[str | None, Header(alias="Idempotency-Key")] = None,
) -> ReimbursementResponse:
    response.headers["Cache-Control"] = "no-store"
    claim = await HrService(session).create_reimbursement(
        payload, current_user, idempotency_key=idempotency_key, own_claim=True
    )
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


@router.get("/project-assignment-options", response_model=ProjectOptionListResponse)
async def project_assignment_options(
    actor: CanManageEmployees,
    session: DbSession,
    search: Annotated[str | None, Query(max_length=100)] = None,
    limit: Annotated[int, Query(ge=1, le=100)] = 25,
    offset: Annotated[int, Query(ge=0)] = 0,
) -> ProjectOptionListResponse:
    return await HrProjectAssignmentService(session).project_options(
        actor, search=search, limit=limit, offset=offset
    )


@router.get("/project-assignment-requests", response_model=HrProjectAssignmentListResponse)
async def my_project_assignment_requests(
    actor: CanManageEmployees,
    session: DbSession,
    limit: Annotated[int, Query(ge=1, le=100)] = 25,
    offset: Annotated[int, Query(ge=0)] = 0,
) -> HrProjectAssignmentListResponse:
    return await HrProjectAssignmentService(session).list_requests(
        actor, limit=limit, offset=offset
    )


@router.post(
    "/employees/{employee_id}/project-assignment-requests",
    response_model=HrProjectAssignmentResponse,
    status_code=status.HTTP_201_CREATED,
)
async def request_project_assignment(
    employee_id: UUID,
    payload: HrProjectAssignmentCreateRequest,
    actor: CanManageEmployees,
    session: DbSession,
) -> HrProjectAssignmentResponse:
    return await HrProjectAssignmentService(session).create(employee_id, payload, actor)


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


@router.get(
    "/employees/{employee_id}/employment-changes", response_model=EmploymentChangeListResponse
)
async def list_employment_changes(
    employee_id: UUID,
    _: CanAccessSensitive,
    session: DbSession,
    limit: Annotated[int, Query(ge=1, le=50)] = 20,
    offset: Annotated[int, Query(ge=0)] = 0,
) -> EmploymentChangeListResponse:
    return await HrService(session).list_employment_changes(employee_id, limit, offset)


@router.get("/employment-changes/due", response_model=DueEmploymentChangeList)
async def list_due_employment_changes(
    _: CanAccessSensitive,
    session: DbSession,
    limit: Annotated[int, Query(ge=1, le=50)] = 20,
    offset: Annotated[int, Query(ge=0)] = 0,
) -> DueEmploymentChangeList:
    return await HrService(session).list_due_employment_changes(limit, offset)


@router.post(
    "/employees/{employee_id}/employment-changes",
    status_code=201,
    response_model=EmploymentChangeResponse,
)
async def propose_employment_change(
    employee_id: UUID,
    payload: EmploymentChangeProposal,
    actor: CanAccessSensitive,
    session: DbSession,
) -> EmploymentChangeResponse:
    change = await HrService(session).propose_employment_change(employee_id, payload, actor)
    return EmploymentChangeResponse.model_validate(change)


@router.get(
    "/employees/{employee_id}/employment-changes/{change_id}",
    response_model=EmploymentChangeResponse,
)
async def get_employment_change(
    employee_id: UUID, change_id: UUID, _: CanAccessSensitive, session: DbSession
) -> EmploymentChangeResponse:
    change = await HrService(session).get_employment_change(employee_id, change_id)
    return EmploymentChangeResponse.model_validate(change)


@router.post(
    "/employees/{employee_id}/employment-changes/{change_id}/decision",
    response_model=EmploymentChangeResponse,
)
async def decide_employment_change(
    employee_id: UUID,
    change_id: UUID,
    payload: EmploymentChangeDecision,
    actor: CanAccessSensitive,
    session: DbSession,
) -> EmploymentChangeResponse:
    change = await HrService(session).decide_employment_change(
        employee_id, change_id, payload, actor
    )
    return EmploymentChangeResponse.model_validate(change)


@router.post(
    "/employees/{employee_id}/employment-changes/{change_id}/apply",
    response_model=EmploymentChangeResponse,
)
async def apply_employment_change(
    employee_id: UUID, change_id: UUID, actor: CanAccessSensitive, session: DbSession
) -> EmploymentChangeResponse:
    change = await HrService(session).apply_employment_change(employee_id, change_id, actor)
    return EmploymentChangeResponse.model_validate(change)


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


@router.get("/employment-periods/missing-start", response_model=EmploymentPeriodMissingStartPage)
async def list_employment_periods_missing_start(
    _: CanAccessSensitive,
    session: DbSession,
    limit: Annotated[int, Query(ge=1, le=100)] = 20,
    offset: Annotated[int, Query(ge=0)] = 0,
) -> EmploymentPeriodMissingStartPage:
    return await HrService(session).list_employment_periods_missing_start(limit, offset)


@router.get(
    "/employees/{employee_id}/employment-periods", response_model=EmploymentPeriodListResponse
)
async def get_employment_periods(
    employee_id: UUID,
    _: CanReadEmployees,
    session: DbSession,
    limit: Annotated[int, Query(ge=1, le=100)] = 20,
    offset: Annotated[int, Query(ge=0)] = 0,
) -> EmploymentPeriodListResponse:
    rows, total = await HrService(session).list_employment_periods(employee_id, limit, offset)
    return EmploymentPeriodListResponse(
        items=[EmploymentPeriodResponse.model_validate(row) for row in rows], total=total
    )


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
    response: Response,
    reveal_sensitive: Annotated[bool, Query()] = False,
) -> EmployeeSensitiveResponse:
    response.headers["Cache-Control"] = "no-store"
    return await HrService(session).get_employee_private(
        employee_id, actor, reveal_sensitive=reveal_sensitive
    )


@router.put("/employees/{employee_id}/private", response_model=EmployeeSensitiveResponse)
async def upsert_employee_private(
    employee_id: UUID,
    payload: EmployeePrivateUpdateRequest,
    actor: CanAccessSensitive,
    session: DbSession,
    response: Response,
) -> EmployeeSensitiveResponse:
    response.headers["Cache-Control"] = "no-store"
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
    res = await preview_workbook_upload(session, content, explicit_role_overrides=overrides)
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
    code: Annotated[str | None, Query(min_length=1, max_length=40)] = None,
    limit: Annotated[int, Query(ge=1, le=100)] = 100,
    offset: Annotated[int, Query(ge=0)] = 0,
) -> RequisitionListResponse:
    rows, total = await HrService(session).list_requisitions(
        status=req_status, code=code, limit=limit, offset=offset
    )
    return RequisitionListResponse(
        items=[RequisitionResponse.model_validate(r) for r in rows], total=total
    )


@router.get("/requisitions/{requisition_id}", response_model=RequisitionResponse)
async def get_requisition(
    requisition_id: UUID, _: CanManageRecruitment, session: DbSession, response: Response
) -> RequisitionResponse:
    response.headers["Cache-Control"] = "no-store"
    return RequisitionResponse.model_validate(
        await HrService(session).get_requisition(requisition_id)
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
    response: Response,
    search: Annotated[str | None, Query(max_length=255)] = None,
    code: Annotated[str | None, Query(min_length=1, max_length=40)] = None,
    limit: Annotated[int, Query(ge=1, le=100)] = 100,
    offset: Annotated[int, Query(ge=0)] = 0,
) -> CandidateListResponse:
    response.headers["Cache-Control"] = "no-store"
    rows, total = await HrService(session).list_candidates(
        search=search, code=code, limit=limit, offset=offset
    )
    return CandidateListResponse(
        items=[CandidateResponse.model_validate(r) for r in rows], total=total
    )


@router.get("/candidates/{candidate_id}", response_model=CandidateResponse)
async def get_candidate(
    candidate_id: UUID, _: CanManageRecruitment, session: DbSession, response: Response
) -> CandidateResponse:
    response.headers["Cache-Control"] = "no-store"
    return CandidateResponse.model_validate(await HrService(session).get_candidate(candidate_id))


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
    response: Response,
    requisition_id: Annotated[UUID | None, Query()] = None,
    candidate_id: Annotated[UUID | None, Query()] = None,
    stage: ApplicationStage | None = None,
    search: Annotated[str | None, Query(max_length=120)] = None,
    limit: Annotated[int, Query(ge=1, le=100)] = 100,
    offset: Annotated[int, Query(ge=0)] = 0,
) -> ApplicationListResponse:
    response.headers["Cache-Control"] = "no-store"
    return await HrService(session).list_applications(
        requisition_id=requisition_id,
        candidate_id=candidate_id,
        stage=stage,
        search=search,
        limit=limit,
        offset=offset,
    )


@router.post(
    "/applications", response_model=ApplicationResponse, status_code=status.HTTP_201_CREATED
)
async def create_application(
    payload: ApplicationCreateRequest,
    actor: CanManageRecruitment,
    session: DbSession,
    response: Response,
) -> ApplicationResponse:
    response.headers["Cache-Control"] = "no-store"
    row = await HrService(session).create_application(payload, actor)
    return ApplicationResponse.model_validate(row)


@router.patch("/applications/{application_id}/stage", response_model=ApplicationResponse)
async def update_application_stage(
    application_id: UUID,
    payload: ApplicationStageUpdateRequest,
    actor: CanManageRecruitment,
    session: DbSession,
    response: Response,
) -> ApplicationResponse:
    response.headers["Cache-Control"] = "no-store"
    row = await HrService(session).update_application_stage(application_id, payload, actor)
    return ApplicationResponse.model_validate(row)


@router.get("/applications/{application_id}", response_model=ApplicationResponse)
async def get_application(
    application_id: UUID, _: CanManageRecruitment, session: DbSession, response: Response
) -> ApplicationResponse:
    response.headers["Cache-Control"] = "no-store"
    return ApplicationResponse.model_validate(
        await HrService(session).get_application(application_id)
    )


@router.get("/applications/{application_id}/activity", response_model=ApplicationActivityList)
async def list_application_activity(
    application_id: UUID,
    _: CanManageRecruitment,
    session: DbSession,
    response: Response,
    limit: Annotated[int, Query(ge=1, le=100)] = 20,
    offset: Annotated[int, Query(ge=0)] = 0,
) -> ApplicationActivityList:
    response.headers["Cache-Control"] = "no-store"
    return await HrService(session).list_application_activity(
        application_id, limit=limit, offset=offset
    )


@router.get("/candidate-correspondence/templates", response_model=LetterTemplateListResponse)
async def list_candidate_letter_templates(
    _: CanManageRecruitment, session: DbSession, response: Response
) -> LetterTemplateListResponse:
    response.headers["Cache-Control"] = "no-store"
    rows, total = await HrService(session).list_letter_templates(candidate=True)
    return LetterTemplateListResponse(
        items=[LetterTemplateResponse.model_validate(r) for r in rows], total=total
    )


@router.get("/applications/{application_id}/correspondence", response_model=LetterListResponse)
async def list_candidate_correspondence(
    application_id: UUID,
    actor: CanManageRecruitment,
    session: DbSession,
    response: Response,
    limit: Annotated[int, Query(ge=1, le=100)] = 20,
    offset: Annotated[int, Query(ge=0)] = 0,
) -> LetterListResponse:
    response.headers["Cache-Control"] = "no-store"
    return await HrService(session).list_candidate_correspondence(
        application_id, actor, limit=limit, offset=offset
    )


@router.post(
    "/applications/{application_id}/correspondence",
    response_model=CandidateCorrespondenceDetail,
    status_code=status.HTTP_201_CREATED,
)
async def draft_candidate_correspondence(
    application_id: UUID,
    payload: CandidateCorrespondenceCreateRequest,
    actor: CanManageRecruitment,
    session: DbSession,
    response: Response,
) -> CandidateCorrespondenceDetail:
    response.headers["Cache-Control"] = "no-store"
    return await HrService(session).draft_candidate_correspondence(application_id, payload, actor)


@router.get(
    "/applications/{application_id}/correspondence/{draft_id}",
    response_model=CandidateCorrespondenceDetail,
)
async def get_candidate_correspondence(
    application_id: UUID,
    draft_id: UUID,
    actor: CanManageRecruitment,
    session: DbSession,
    response: Response,
) -> CandidateCorrespondenceDetail:
    response.headers["Cache-Control"] = "no-store"
    return await HrService(session).get_candidate_correspondence(application_id, draft_id, actor)


@router.post(
    "/applications/{application_id}/correspondence/{draft_id}/decision",
    response_model=CandidateCorrespondenceDetail,
)
async def decide_candidate_correspondence(
    application_id: UUID,
    draft_id: UUID,
    payload: CandidateCorrespondenceDecisionRequest,
    actor: CanManageRecruitment,
    session: DbSession,
    response: Response,
) -> CandidateCorrespondenceDetail:
    response.headers["Cache-Control"] = "no-store"
    return await HrService(session).decide_candidate_correspondence(
        application_id, draft_id, payload, actor
    )


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


@router.get("/interviews/interviewer-options", response_model=InterviewerOptions)
async def list_interviewer_options(
    _: CanManageRecruitment,
    session: DbSession,
    response: Response,
    search: Annotated[str, Query(max_length=120)] = "",
    limit: Annotated[int, Query(ge=1, le=100)] = 20,
    offset: Annotated[int, Query(ge=0)] = 0,
) -> InterviewerOptions:
    response.headers["Cache-Control"] = "no-store"
    return await HrService(session).list_interviewer_options(
        search=search.strip(), limit=limit, offset=offset
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
    application_id: Annotated[UUID | None, Query()] = None,
    limit: Annotated[int, Query(ge=1, le=100)] = 100,
    offset: Annotated[int, Query(ge=0)] = 0,
) -> OfferListResponse:
    rows, total = await HrService(session).list_offers(
        status=offer_status, application_id=application_id, limit=limit, offset=offset
    )
    return OfferListResponse(items=[OfferResponse.model_validate(r) for r in rows], total=total)


@router.get("/offers/{offer_id}", response_model=OfferResponse)
async def get_offer(offer_id: UUID, _: CanManageRecruitment, session: DbSession) -> OfferResponse:
    return OfferResponse.model_validate(await HrService(session).get_offer(offer_id))


@router.get("/offers/{offer_id}/document", response_model=HrDocumentDownloadResponse)
async def download_offer_document(
    offer_id: UUID, actor: CanManageRecruitment, session: DbSession, response: Response
) -> HrDocumentDownloadResponse:
    response.headers["Cache-Control"] = "no-store"
    return await HrService(session).download_offer_document(offer_id, actor)


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


@router.post(
    "/offers/{offer_id}/reissue",
    response_model=OfferResponse,
    status_code=status.HTTP_201_CREATED,
)
async def reissue_offer(
    offer_id: UUID,
    payload: OfferReissueRequest,
    actor: CanManageRecruitment,
    session: DbSession,
) -> OfferResponse:
    row = await HrService(session).reissue_offer(offer_id, payload, actor)
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
    actor: CanManageOnboarding,
    session: DbSession,
    response: Response,
    employee_id: Annotated[UUID | None, Query()] = None,
    case_status: Annotated[str | None, Query(max_length=30)] = None,
    limit: Annotated[int | None, Query(ge=1, le=100)] = None,
    offset: Annotated[int, Query(ge=0)] = 0,
) -> OnboardingCaseListResponse:
    response.headers["Cache-Control"] = "no-store"
    items, total = await HrService(session).list_onboarding_cases(
        actor=actor, employee_id=employee_id, status=case_status, limit=limit, offset=offset
    )
    return OnboardingCaseListResponse(items=items, total=total)


@router.get("/onboarding/{case_id}", response_model=OnboardingCaseResponse)
async def get_onboarding_case(
    case_id: UUID, actor: CanManageOnboarding, session: DbSession, response: Response
) -> OnboardingCaseResponse:
    response.headers["Cache-Control"] = "no-store"
    return await HrService(session).get_onboarding_case(case_id, actor)


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
    response: Response,
    employee_id: Annotated[UUID | None, Query()] = None,
    candidate_id: Annotated[UUID | None, Query()] = None,
    category: Annotated[str | None, Query()] = None,
    document_type: Annotated[str | None, Query(max_length=40)] = None,
    limit: Annotated[int, Query(ge=1, le=100)] = 100,
    offset: Annotated[int, Query(ge=0)] = 0,
) -> HrDocumentListResponse:
    response.headers["Cache-Control"] = "no-store"
    items, total = await HrService(session).list_hr_documents(
        actor=actor,
        employee_id=employee_id,
        candidate_id=candidate_id,
        category=category,
        document_type=document_type,
        limit=limit,
        offset=offset,
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


@router.get("/documents/{document_id}", response_model=HrDocumentResponse)
async def get_hr_document(
    document_id: UUID, actor: CanManageDocuments, session: DbSession, response: Response
) -> HrDocumentResponse:
    response.headers["Cache-Control"] = "no-store"
    return await HrService(session).get_hr_document_detail(document_id, actor)


@router.post(
    "/documents/{document_id}/versions", response_model=HrDocumentResponse, status_code=201
)
async def upload_hr_document_version(
    document_id: UUID,
    actor: CanManageDocuments,
    session: DbSession,
    file: Annotated[UploadFile, File()],
    expected_latest_version: Annotated[int | None, Form(ge=0)] = None,
) -> HrDocumentResponse:
    return await HrService(session).upload_hr_document_version(
        document_id, file, actor, expected_latest_version=expected_latest_version
    )


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
    response: Response,
    version_number: Annotated[int | None, Query(ge=1)] = None,
) -> HrDocumentDownloadResponse:
    response.headers["Cache-Control"] = "no-store"
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


@router.get("/roster", response_model=RosterAllocationListResponse)
async def list_roster(
    _: CanRecordAttendance,
    session: DbSession,
    date_from: date,
    date_to: date,
    project_id: UUID | None = None,
    employee_id: UUID | None = None,
    limit: Annotated[int, Query(ge=1, le=100)] = 25,
    offset: Annotated[int, Query(ge=0)] = 0,
) -> RosterAllocationListResponse:
    rows, total = await HrService(session).list_roster_allocations(
        date_from=date_from,
        date_to=date_to,
        project_id=project_id,
        employee_id=employee_id,
        limit=limit,
        offset=offset,
    )
    return RosterAllocationListResponse(
        items=[RosterAllocationResponse.model_validate(row) for row in rows], total=total
    )


@router.get("/roster/{allocation_id}", response_model=RosterAllocationResponse)
async def read_roster_allocation(
    allocation_id: UUID, response: Response, _: CanRecordAttendance, session: DbSession
) -> RosterAllocationResponse:
    row = await HrService(session).get_roster_allocation(allocation_id)
    response.headers["Cache-Control"] = "no-store"
    return RosterAllocationResponse.model_validate(row)


@router.post(
    "/roster", response_model=RosterAllocationResponse, status_code=status.HTTP_201_CREATED
)
async def create_roster_allocation(
    payload: RosterAllocationCreateRequest, actor: CanRecordAttendance, session: DbSession
) -> RosterAllocationResponse:
    row = await HrService(session).create_roster_allocation(payload, actor)
    return RosterAllocationResponse.model_validate(row)


@router.post("/roster/{allocation_id}/cancel", response_model=RosterAllocationResponse)
async def cancel_roster_allocation(
    allocation_id: UUID,
    payload: RosterCancellationRequest,
    actor: CanRecordAttendance,
    session: DbSession,
) -> RosterAllocationResponse:
    row = await HrService(session).cancel_roster_allocation(allocation_id, payload.reason, actor)
    return RosterAllocationResponse.model_validate(row)


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
    actor: CanRecordAttendance, session: DbSession, file: UploadFile, response: Response
) -> AttendanceImportPreviewResponse:
    response.headers["Cache-Control"] = "no-store"
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
    response: Response,
    expected_digest: Annotated[str, Form(pattern=r"^[0-9a-f]{64}$")],
) -> AttendanceImportPreviewResponse:
    response.headers["Cache-Control"] = "no-store"
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


@router.get("/attendance/corrections/{correction_id}", response_model=AttendanceCorrectionResponse)
async def read_attendance_correction(
    correction_id: UUID, _: CanRecordAttendance, session: DbSession, response: Response
) -> AttendanceCorrectionResponse:
    response.headers["Cache-Control"] = "no-store"
    return AttendanceCorrectionResponse.model_validate(
        await HrService(session).get_attendance_correction(correction_id)
    )


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


@router.get("/attendance/{entry_id}", response_model=AttendanceEntryResponse)
async def read_attendance_entry(
    entry_id: UUID, _: CanRecordAttendance, session: DbSession, response: Response
) -> AttendanceEntryResponse:
    response.headers["Cache-Control"] = "no-store"
    return AttendanceEntryResponse.model_validate(
        await HrService(session).get_attendance_entry(entry_id)
    )


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


@router.get("/timesheets/{timesheet_id}", response_model=TimesheetResponse)
async def read_timesheet(
    timesheet_id: UUID, _: CanRecordAttendance, session: DbSession, response: Response
) -> TimesheetResponse:
    response.headers["Cache-Control"] = "no-store"
    return TimesheetResponse.model_validate(await HrService(session).get_timesheet(timesheet_id))


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


@router.get("/overtime/{overtime_id}", response_model=OvertimeRequestResponse)
async def read_overtime(
    overtime_id: UUID, _: CanRecordAttendance, session: DbSession, response: Response
) -> OvertimeRequestResponse:
    response.headers["Cache-Control"] = "no-store"
    return OvertimeRequestResponse.model_validate(
        await HrService(session).get_overtime_request(overtime_id)
    )


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


@router.get("/leave/policies/{policy_id}", response_model=LeavePolicyResponse)
async def get_leave_policy(
    policy_id: UUID, _: CanManageLeave, session: DbSession
) -> LeavePolicyResponse:
    return LeavePolicyResponse.model_validate(await HrService(session).get_leave_policy(policy_id))


@router.post("/leave/policies/{policy_id}/decision", response_model=LeavePolicyResponse)
async def decide_leave_policy(
    policy_id: UUID, payload: LeavePolicyDecisionRequest, actor: CanManagePolicy, session: DbSession
) -> LeavePolicyResponse:
    row = await HrService(session).decide_leave_policy(policy_id, payload, actor)
    return LeavePolicyResponse.model_validate(row)


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


@router.post("/leave/accrual/preview", response_model=LeaveAccrualResponse)
async def preview_leave_accrual(
    payload: LeaveAccrualRequest, actor: CanApproveLeave, session: DbSession
) -> LeaveAccrualResponse:
    return await process_leave_accrual(session, payload, actor)


@router.post("/leave/accrual/apply", response_model=LeaveAccrualResponse)
async def apply_leave_accrual(
    payload: LeaveAccrualApplyRequest, actor: CanApproveLeave, session: DbSession
) -> LeaveAccrualResponse:
    return await process_leave_accrual(
        session, payload, actor, expected_digest=payload.expected_digest
    )


@router.post("/leave/accrual/catch-up/preview", response_model=LeaveAccrualCatchUpResponse)
async def preview_leave_accrual_catch_up(
    payload: LeaveAccrualCatchUpRequest, actor: CanApproveLeave, session: DbSession
) -> LeaveAccrualCatchUpResponse:
    return await process_leave_accrual_catch_up(session, payload, actor)


@router.post("/leave/accrual/catch-up/apply", response_model=LeaveAccrualCatchUpResponse)
async def apply_leave_accrual_catch_up(
    payload: LeaveAccrualCatchUpApplyRequest, actor: CanApproveLeave, session: DbSession
) -> LeaveAccrualCatchUpResponse:
    return await process_leave_accrual_catch_up(
        session, payload, actor, expected_digest=payload.expected_digest
    )


@router.post("/leave/rollover/preview", response_model=LeaveRolloverResponse)
async def preview_leave_rollover(
    payload: LeaveRolloverRequest, actor: CanApproveLeave, session: DbSession
) -> LeaveRolloverResponse:
    return await process_leave_rollover(session, payload, actor)


@router.post("/leave/rollover/apply", response_model=LeaveRolloverResponse)
async def apply_leave_rollover(
    payload: LeaveRolloverApplyRequest, actor: CanApproveLeave, session: DbSession
) -> LeaveRolloverResponse:
    return await process_leave_rollover(
        session, payload, actor, expected_digest=payload.expected_digest
    )


@router.get("/leave/employees/{employee_id}/units", response_model=LeaveUnitsResponse)
async def quote_employee_leave_units(
    employee_id: UUID,
    payload: Annotated[LeaveUnitsQuery, Query()],
    _: CanManageLeave,
    session: DbSession,
) -> LeaveUnitsResponse:
    units = await HrService(session).quote_employee_leave_units(employee_id, payload)
    return LeaveUnitsResponse(days_requested=units)


@router.get("/leave/requests", response_model=LeaveRequestListResponse)
async def list_leave_requests(
    _: CanManageLeave,
    session: DbSession,
    employee_id: Annotated[UUID | None, Query()] = None,
    req_status: Annotated[str | None, Query()] = None,
    limit: Annotated[int | None, Query(ge=1, le=100)] = None,
    offset: Annotated[int, Query(ge=0)] = 0,
) -> LeaveRequestListResponse:
    rows, total = await HrService(session).list_leave_requests(
        employee_id=employee_id, status=req_status, limit=limit, offset=offset
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


@router.get("/leave/requests/{leave_request_id}/decision", response_model=LeaveRequestDecisionState)
async def get_leave_decision_state(
    leave_request_id: UUID, _: CanApproveLeave, session: DbSession
) -> LeaveRequestDecisionState:
    return await HrService(session).get_leave_decision_state(leave_request_id)


@router.post("/leave/requests/{leave_request_id}/decision", response_model=LeaveRequestResponse)
async def decide_leave_request(
    leave_request_id: UUID,
    payload: LeaveRequestDecisionRequest,
    actor: CanApproveLeave,
    session: DbSession,
) -> LeaveRequestResponse:
    row = await HrService(session).decide_leave_request(leave_request_id, payload, actor)
    return LeaveRequestResponse.model_validate(row)


@router.get("/leave/date-evidence/candidates", response_model=LeaveDateEvidenceCandidates)
async def find_legacy_leave_dates(
    actor: CanManageLeave,
    session: DbSession,
    response: Response,
    employee_id: Annotated[UUID | None, Query()] = None,
    limit: Annotated[int, Query(ge=1, le=50)] = 20,
    offset: Annotated[int, Query(ge=0)] = 0,
) -> LeaveDateEvidenceCandidates:
    response.headers["Cache-Control"] = "no-store"
    return await list_missing_leave_dates(
        session,
        actor,
        employee_id=employee_id,
        limit=limit,
        offset=offset,
    )


@router.get("/leave/requests/{request_id}/date-evidence", response_model=LeaveDateEvidencePage)
async def read_legacy_leave_dates(
    request_id: UUID,
    actor: CanManageLeave,
    session: DbSession,
    response: Response,
    limit: Annotated[int, Query(ge=1, le=50)] = 20,
    offset: Annotated[int, Query(ge=0)] = 0,
) -> LeaveDateEvidencePage:
    response.headers["Cache-Control"] = "no-store"
    return await list_leave_date_evidence(session, request_id, actor, limit=limit, offset=offset)


@router.post("/leave/requests/{request_id}/date-evidence", response_model=LeaveDateEvidenceResponse)
async def propose_legacy_leave_dates(
    request_id: UUID,
    payload: LeaveDateEvidenceCreate,
    actor: CanManageLeave,
    session: DbSession,
    response: Response,
) -> LeaveDateEvidenceResponse:
    response.headers["Cache-Control"] = "no-store"
    return await propose_leave_date_evidence(session, request_id, payload, actor)


@router.get(
    "/leave/requests/{request_id}/date-evidence/{proposal_id}",
    response_model=LeaveDateEvidenceResponse,
)
async def show_legacy_leave_date_proposal(
    request_id: UUID,
    proposal_id: UUID,
    actor: CanManageLeave,
    session: DbSession,
    response: Response,
) -> LeaveDateEvidenceResponse:
    response.headers["Cache-Control"] = "no-store"
    return await read_leave_date_evidence(session, request_id, proposal_id, actor)


@router.post(
    "/leave/requests/{request_id}/date-evidence/{proposal_id}/decision",
    response_model=LeaveDateEvidenceResponse,
)
async def decide_legacy_leave_dates(
    request_id: UUID,
    proposal_id: UUID,
    payload: LeaveDateEvidenceDecision,
    actor: CanApproveLeave,
    session: DbSession,
    response: Response,
) -> LeaveDateEvidenceResponse:
    response.headers["Cache-Control"] = "no-store"
    return await decide_leave_date_evidence(session, request_id, proposal_id, payload, actor)


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


@router.post("/letters/drafts", response_model=LetterDetail, status_code=201)
async def draft_letter(
    payload: LetterDraftRequest, actor: CanProcessRequests, session: DbSession
) -> LetterDetail:
    return await HrService(session).draft_letter(payload, actor)


@router.get("/employees/{employee_id}/letters", response_model=LetterListResponse)
async def list_employee_letters(
    employee_id: UUID,
    actor: CanProcessRequests,
    session: DbSession,
    limit: Annotated[int, Query(ge=1, le=50)] = 20,
    offset: Annotated[int, Query(ge=0)] = 0,
    issued_only: bool = False,
) -> LetterListResponse:
    return await HrService(session).list_letters(
        employee_id, actor, limit, offset, issued_only=issued_only
    )


@router.get("/employees/{employee_id}/letters/{letter_id}", response_model=LetterDetail)
async def get_employee_letter(
    employee_id: UUID, letter_id: UUID, actor: CanProcessRequests, session: DbSession
) -> LetterDetail:
    return await HrService(session).get_letter(letter_id, employee_id, actor)


@router.post("/employees/{employee_id}/letters/{letter_id}/decision", response_model=LetterDetail)
async def decide_letter(
    employee_id: UUID,
    letter_id: UUID,
    payload: LetterDecisionRequest,
    actor: CanProcessRequests,
    session: DbSession,
) -> LetterDetail:
    return await HrService(session).decide_letter(employee_id, letter_id, payload, actor)


@router.get("/me/letters", response_model=LetterListResponse)
async def list_my_letters(
    current_user: CurrentUser,
    session: DbSession,
    limit: Annotated[int, Query(ge=1, le=50)] = 20,
    offset: Annotated[int, Query(ge=0)] = 0,
) -> LetterListResponse:
    return await HrService(session).list_letters(None, current_user, limit, offset)


@router.get("/me/letters/{letter_id}", response_model=LetterDetail)
async def get_my_letter(
    letter_id: UUID, current_user: CurrentUser, session: DbSession
) -> LetterDetail:
    return await HrService(session).get_letter(letter_id, None, current_user)


@router.get("/requests", response_model=HrServiceRequestListResponse)
async def list_service_requests(
    _: CanProcessRequests,
    session: DbSession,
    employee_id: Annotated[UUID | None, Query()] = None,
    req_status: Annotated[
        Literal["open", "in_review", "approved", "completed", "rejected", "cancelled"] | None,
        Query(),
    ] = None,
    limit: Annotated[int | None, Query(ge=1, le=100)] = None,
    offset: Annotated[int, Query(ge=0)] = 0,
) -> HrServiceRequestListResponse:
    rows, total = await HrService(session).list_service_requests(
        employee_id=employee_id, status=req_status, limit=limit, offset=offset
    )
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


@router.get("/requests/assignees", response_model=list[HrServiceRequestAssignee])
async def list_service_request_assignees(
    _: CanProcessRequests, session: DbSession
) -> list[HrServiceRequestAssignee]:
    return await HrService(session).list_service_request_assignees()


@router.get("/requests/{req_id}", response_model=HrServiceRequestResponse)
async def get_service_request(
    req_id: UUID, _: CanProcessRequests, session: DbSession
) -> HrServiceRequestResponse:
    row = await HrService(session).get_service_request(req_id)
    return HrServiceRequestResponse.model_validate(row)


@router.post("/requests/{req_id}/assign", response_model=HrServiceRequestResponse)
async def assign_service_request(
    req_id: UUID,
    payload: HrServiceRequestAssignmentRequest,
    actor: CanProcessRequests,
    session: DbSession,
) -> HrServiceRequestResponse:
    row = await HrService(session).assign_service_request(req_id, payload, actor)
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


@router.get("/offboarding/{case_id}/custody", response_model=OffboardingCustodyListResponse)
async def get_offboarding_custody(
    case_id: UUID,
    session: DbSession,
    actor: Annotated[
        User,
        Depends(
            require_any_permission(
                PERMISSION_HR_OFFBOARDING_MANAGE,
                PERMISSION_INVENTORY_MANAGE,
                PERMISSION_USERS_MANAGE,
            )
        ),
    ],
    limit: Annotated[int, Query(ge=1, le=100)] = 20,
    offset: Annotated[int, Query(ge=0)] = 0,
    event_id: Annotated[UUID | None, Query()] = None,
    area: Annotated[OffboardingCustodyArea, Query()] = "store_inventory",
) -> OffboardingCustodyListResponse:
    return await list_offboarding_custody(
        session, case_id, actor, limit=limit, offset=offset, event_id=event_id, area=area
    )


@router.post("/offboarding/{case_id}/custody", response_model=OffboardingCustodyResponse)
async def post_offboarding_custody(
    case_id: UUID,
    payload: OffboardingCustodyRequest,
    session: DbSession,
    actor: Annotated[
        User, Depends(require_any_permission(PERMISSION_INVENTORY_MANAGE, PERMISSION_USERS_MANAGE))
    ],
) -> OffboardingCustodyResponse:
    event = await record_offboarding_custody(session, case_id, payload, actor)
    return OffboardingCustodyResponse.model_validate(event)


@router.get("/offboarding/{case_id}/settlement", response_model=SeparationSettlementListResponse)
async def get_separation_settlement(
    case_id: UUID,
    session: DbSession,
    actor: Annotated[
        User,
        Depends(require_any_permission(PERMISSION_HR_OFFBOARDING_MANAGE, PERMISSION_USERS_MANAGE)),
    ],
    limit: Annotated[int, Query(ge=1, le=100)] = 20,
    offset: Annotated[int, Query(ge=0)] = 0,
    event_id: Annotated[UUID | None, Query()] = None,
) -> SeparationSettlementListResponse:
    return await list_separation_settlements(
        session, case_id, actor, limit=limit, offset=offset, event_id=event_id
    )


@router.post("/offboarding/{case_id}/settlement", response_model=SeparationSettlementResponse)
async def propose_offboarding_settlement(
    case_id: UUID, payload: SeparationSettlementProposal, session: DbSession, actor: CanManageUsers
) -> SeparationSettlementResponse:
    row = await propose_separation_settlement(session, case_id, payload, actor)
    return SeparationSettlementResponse.model_validate(row)


@router.post(
    "/offboarding/{case_id}/settlement/{event_id}/review",
    response_model=SeparationSettlementResponse,
)
async def review_offboarding_settlement(
    case_id: UUID,
    event_id: UUID,
    payload: SeparationSettlementReview,
    session: DbSession,
    actor: CanManageUsers,
) -> SeparationSettlementResponse:
    row = await review_separation_settlement(session, case_id, event_id, payload, actor)
    return SeparationSettlementResponse.model_validate(row)


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


@router.get("/performance/reviews", response_model=PerformanceReviewQueue)
async def list_participant_reviews(
    actor: CurrentUser,
    session: DbSession,
    response: Response,
    limit: Annotated[int, Query(ge=1, le=100)] = 20,
    offset: Annotated[int, Query(ge=0)] = 0,
) -> PerformanceReviewQueue:
    response.headers["Cache-Control"] = "no-store"
    return await list_performance_reviews(session, actor, limit=limit, offset=offset)


@router.get("/performance/reviews/{review_id}", response_model=PerformanceReviewDetail)
async def get_participant_review(
    review_id: UUID,
    actor: CurrentUser,
    session: DbSession,
    response: Response,
) -> PerformanceReviewDetail:
    response.headers["Cache-Control"] = "no-store"
    return await get_performance_review(session, review_id, actor)


@router.post("/performance/reviews/{review_id}/actions", response_model=PerformanceReviewDetail)
async def act_on_performance_review(
    review_id: UUID,
    payload: PerformanceReviewActionRequest,
    actor: CurrentUser,
    session: DbSession,
    response: Response,
) -> PerformanceReviewDetail:
    response.headers["Cache-Control"] = "no-store"
    return await record_performance_action(session, review_id, payload, actor)


@router.get("/training/requirements", response_model=TrainingRequirementListResponse)
async def get_training_rules(
    _: CanManageTraining,
    session: DbSession,
    limit: Annotated[int, Query(ge=1, le=100)] = 20,
    offset: Annotated[int, Query(ge=0)] = 0,
) -> TrainingRequirementListResponse:
    return await list_rules(session, limit=limit, offset=offset)


@router.post("/training/requirements")
async def create_training_rule(
    payload: TrainingRequirementCreateRequest,
    actor: CanManageTraining,
    session: DbSession,
) -> dict[str, UUID]:
    return {"id": await save_rule(session, payload, actor)}


@router.delete("/training/requirements/{rule_id}", status_code=204)
async def remove_training_rule(
    rule_id: UUID,
    actor: CanManageTraining,
    session: DbSession,
) -> Response:
    await deactivate_rule(session, rule_id, actor)
    return Response(status_code=204)


@router.get(
    "/training/requirements/employees/{employee_id}",
    response_model=TrainingRequirementStatusListResponse,
)
async def get_employee_training_requirements(
    employee_id: UUID,
    _: CanManageTraining,
    session: DbSession,
    limit: Annotated[int, Query(ge=1, le=100)] = 20,
    offset: Annotated[int, Query(ge=0)] = 0,
) -> TrainingRequirementStatusListResponse:
    employee = await session.get(HrEmployee, employee_id)
    if employee is None or employee.deleted_at is not None:
        raise NotFoundException("Employee")
    return await list_employee_requirements(session, employee, limit=limit, offset=offset)


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


@router.get(
    "/training/enrollments/{enrollment_id}/completion", response_model=TrainingCompletionResponse
)
async def get_training_completion(
    enrollment_id: UUID, _: CanManageTraining, session: DbSession
) -> TrainingCompletionResponse:
    return await HrService(session).get_training_completion(enrollment_id)


@router.post(
    "/training/enrollments/{enrollment_id}/completion", response_model=TrainingCompletionResponse
)
async def verify_training_completion(
    enrollment_id: UUID,
    payload: TrainingCompletionRequest,
    actor: CanManageTraining,
    session: DbSession,
) -> TrainingCompletionResponse:
    return await HrService(session).complete_training_enrollment(enrollment_id, payload, actor)


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
    _: CanReadPayrollSensitive, session: DbSession, response: Response
) -> BenefitTypeListResponse:
    response.headers["Cache-Control"] = "no-store"
    rows, total = await HrService(session).list_benefit_types()
    return BenefitTypeListResponse(
        items=[BenefitTypeResponse.model_validate(r) for r in rows], total=total
    )


@router.post(
    "/benefits/types", response_model=BenefitTypeResponse, status_code=status.HTTP_201_CREATED
)
async def create_benefit_type(
    payload: BenefitTypeCreateRequest,
    actor: CanReadPayrollSensitive,
    session: DbSession,
    response: Response,
) -> BenefitTypeResponse:
    response.headers["Cache-Control"] = "no-store"
    row = await HrService(session).create_benefit_type(payload, actor)
    return BenefitTypeResponse.model_validate(row)


@router.post("/benefits/types/{benefit_type_id}/approve", response_model=BenefitTypeResponse)
async def approve_benefit_policy(
    benefit_type_id: UUID, actor: CanApprovePayroll, session: DbSession, response: Response
) -> BenefitTypeResponse:
    response.headers["Cache-Control"] = "no-store"
    row = await HrService(session).approve_benefit_policy(benefit_type_id, actor)
    return BenefitTypeResponse.model_validate(row)


@router.get("/benefits/assignments", response_model=EmployeeBenefitListResponse)
async def list_employee_benefits(
    _: CanReadPayrollSensitive,
    session: DbSession,
    response: Response,
    employee_id: Annotated[UUID | None, Query()] = None,
) -> EmployeeBenefitListResponse:
    response.headers["Cache-Control"] = "no-store"
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
    payload: EmployeeBenefitCreateRequest,
    actor: CanReadPayrollSensitive,
    session: DbSession,
    response: Response,
) -> EmployeeBenefitResponse:
    response.headers["Cache-Control"] = "no-store"
    row = await HrService(session).create_employee_benefit(payload, actor)
    return EmployeeBenefitResponse.model_validate(row)


@router.get("/advances", response_model=EmployeeAdvanceListResponse)
async def list_advances(
    actor: CanReadPayrollSensitive,
    session: DbSession,
    response: Response,
    employee_id: Annotated[UUID, Query()],
    limit: Annotated[int, Query(ge=1, le=50)] = 20,
    offset: Annotated[int, Query(ge=0)] = 0,
) -> EmployeeAdvanceListResponse:
    response.headers["Cache-Control"] = "no-store"
    items, total = await HrService(session).list_advances(
        employee_id, actor, limit=limit, offset=offset
    )
    return EmployeeAdvanceListResponse(items=items, total=total)


@router.post("/advances", response_model=EmployeeAdvanceResponse, status_code=201)
async def submit_advance(
    payload: EmployeeAdvanceRequest,
    actor: CanReadPayrollSensitive,
    session: DbSession,
    response: Response,
    idempotency_key: Annotated[str | None, Header(alias="Idempotency-Key")] = None,
) -> EmployeeAdvanceResponse:
    response.headers["Cache-Control"] = "no-store"
    return await HrService(session).submit_advance(payload, actor, idempotency_key=idempotency_key)


@router.get("/advances/{advance_id}", response_model=EmployeeAdvanceResponse)
async def read_advance(
    advance_id: UUID, actor: CanReadPayrollSensitive, session: DbSession, response: Response
) -> EmployeeAdvanceResponse:
    response.headers["Cache-Control"] = "no-store"
    return await HrService(session).read_advance(advance_id, actor)


@router.post("/advances/{advance_id}/decision", response_model=EmployeeAdvanceResponse)
async def decide_advance(
    advance_id: UUID,
    payload: EmployeeAdvanceDecision,
    actor: CanApprovePayroll,
    session: DbSession,
    response: Response,
) -> EmployeeAdvanceResponse:
    response.headers["Cache-Control"] = "no-store"
    return await HrService(session).decide_advance(advance_id, payload, actor)


@router.post("/advances/{advance_id}/disburse", response_model=EmployeeAdvanceResponse)
async def disburse_advance(
    advance_id: UUID,
    payload: EmployeeAdvanceDisbursement,
    actor: CanApprovePayroll,
    session: DbSession,
    response: Response,
) -> EmployeeAdvanceResponse:
    response.headers["Cache-Control"] = "no-store"
    return await HrService(session).disburse_advance(advance_id, payload, actor)


@router.post("/advances/{advance_id}/repayments", response_model=EmployeeAdvanceResponse)
async def recover_advance(
    advance_id: UUID,
    payload: EmployeeAdvancePayment,
    actor: CanApprovePayroll,
    session: DbSession,
    response: Response,
) -> EmployeeAdvanceResponse:
    response.headers["Cache-Control"] = "no-store"
    return await HrService(session).recover_advance(advance_id, payload, actor)


@router.get("/reimbursements", response_model=ReimbursementOperatorListResponse)
async def list_reimbursements(
    _: CanReadPayrollSensitive,
    session: DbSession,
    response: Response,
    employee_id: Annotated[UUID | None, Query()] = None,
    limit: Annotated[int | None, Query(ge=1, le=50)] = None,
    offset: Annotated[int, Query(ge=0)] = 0,
) -> ReimbursementOperatorListResponse:
    response.headers["Cache-Control"] = "no-store"
    rows, total = await HrService(session).list_reimbursements(
        employee_id=employee_id, limit=limit, offset=offset
    )
    return ReimbursementOperatorListResponse(
        items=[ReimbursementOperatorResponse.model_validate(r) for r in rows], total=total
    )


@router.post(
    "/reimbursements",
    response_model=ReimbursementOperatorResponse,
    status_code=status.HTTP_201_CREATED,
)
async def create_reimbursement(
    payload: ReimbursementCreateRequest,
    actor: CanReadPayrollSensitive,
    session: DbSession,
    response: Response,
    idempotency_key: Annotated[str | None, Header(alias="Idempotency-Key")] = None,
) -> ReimbursementOperatorResponse:
    response.headers["Cache-Control"] = "no-store"
    row = await HrService(session).create_reimbursement(
        payload, actor, idempotency_key=idempotency_key
    )
    return ReimbursementOperatorResponse.model_validate(row)


@router.get("/reimbursements/{claim_id}", response_model=ReimbursementOperatorResponse)
async def get_reimbursement(
    claim_id: UUID,
    actor: CanReadPayrollSensitive,
    session: DbSession,
    response: Response,
) -> ReimbursementOperatorResponse:
    response.headers["Cache-Control"] = "no-store"
    row = await HrService(session).get_reimbursement_for_review(claim_id, actor)
    return ReimbursementOperatorResponse.model_validate(row)


@router.post("/reimbursements/{claim_id}/decision", response_model=ReimbursementOperatorResponse)
async def decide_reimbursement(
    claim_id: UUID,
    payload: ReimbursementDecisionRequest,
    actor: CanApprovePayroll,
    session: DbSession,
    response: Response,
) -> ReimbursementOperatorResponse:
    response.headers["Cache-Control"] = "no-store"
    row = await HrService(session).decide_reimbursement(claim_id, payload, actor)
    return ReimbursementOperatorResponse.model_validate(row)


@router.get("/reimbursements/{claim_id}/payable", response_model=ReimbursementPayableResponse)
async def get_reimbursement_payable(
    claim_id: UUID,
    actor: CanReadPayrollSensitive,
    session: DbSession,
    response: Response,
) -> ReimbursementPayableResponse:
    response.headers["Cache-Control"] = "no-store"
    return await HrService(session).read_reimbursement_payable(claim_id, actor)


@router.get("/compensation/{employee_id}", response_model=CompensationTermListResponse)
async def list_compensation(
    employee_id: UUID,
    actor: CanReadPayrollSensitive,
    session: DbSession,
    response: Response,
    reveal_sensitive: Annotated[bool, Query()] = False,
    term_id: Annotated[UUID | None, Query()] = None,
) -> CompensationTermListResponse:
    response.headers["Cache-Control"] = "no-store"
    items, total = await HrService(session).list_compensation_terms(
        employee_id=employee_id, actor=actor, reveal_sensitive=reveal_sensitive, term_id=term_id
    )
    return CompensationTermListResponse(items=items, total=total)


@router.post(
    "/compensation", response_model=CompensationTermResponse, status_code=status.HTTP_201_CREATED
)
async def create_compensation(
    payload: CompensationTermCreateRequest,
    actor: CanReadPayrollSensitive,
    session: DbSession,
    response: Response,
) -> CompensationTermResponse:
    response.headers["Cache-Control"] = "no-store"
    return await HrService(session).create_compensation_term(payload, actor)


@router.post("/compensation/{term_id}/decision", response_model=CompensationTermResponse)
async def decide_compensation(
    term_id: UUID,
    payload: CompensationTermDecisionRequest,
    actor: CanApprovePayroll,
    session: DbSession,
    response: Response,
) -> CompensationTermResponse:
    response.headers["Cache-Control"] = "no-store"
    return await HrService(session).decide_compensation_term(term_id, payload, actor)


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


@router.get("/payroll/policies/{policy_id}", response_model=PayrollPolicyResponse)
async def get_payroll_policy(
    policy_id: UUID, actor: CurrentUser, session: DbSession, response: Response
) -> PayrollPolicyResponse:
    response.headers["Cache-Control"] = "no-store"
    can_approve = has_permission(actor, PERMISSION_HR_PAYROLL_APPROVE)
    if not can_approve and not has_permission(actor, PERMISSION_HR_PAYROLL_PREPARE):
        raise PermissionDeniedException("read payroll policy")
    policy = await HrService(session).get_payroll_policy(policy_id)
    if not can_approve and policy.approved_by_id != actor.id:
        raise PermissionDeniedException("read payroll policy")
    return PayrollPolicyResponse.model_validate(policy)


@router.put("/payroll/policies/{policy_id}/draft", response_model=PayrollPolicyResponse)
async def update_payroll_policy_draft(
    policy_id: UUID,
    payload: PayrollPolicyDraftUpdateRequest,
    actor: CanPreparePayroll,
    session: DbSession,
) -> PayrollPolicyResponse:
    row = await HrService(session).update_payroll_policy_draft(policy_id, payload, actor)
    return PayrollPolicyResponse.model_validate(row)


@router.post("/payroll/policies/{policy_id}/approve", response_model=PayrollPolicyResponse)
async def approve_payroll_policy(
    policy_id: UUID,
    actor: CanApprovePayroll,
    session: DbSession,
    payload: PayrollPolicyApproveRequest | None = None,
) -> PayrollPolicyResponse:
    row = await HrService(session).approve_payroll_policy(
        policy_id, actor, expected_updated_at=payload.expected_updated_at if payload else None
    )
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


@router.post(
    "/payroll/periods/{period_id}/time-inputs/preview",
    response_model=PayrollTimeInputPreview,
)
async def preview_payroll_time_inputs(
    period_id: UUID,
    payload: PayrollRunCalculateRequest,
    actor: CanPreparePayroll,
    session: DbSession,
    response: Response,
) -> PayrollTimeInputPreview:
    result, _ = await payroll_time_inputs(session, period_id, payload.employee_ids, actor)
    response.headers["Cache-Control"] = "no-store"
    return result


@router.post(
    "/payroll/periods/{period_id}/time-inputs.csv",
    response_class=Response,
    responses={200: {"content": {"text/csv": {"schema": {"type": "string"}}}}},
)
async def download_payroll_time_inputs(
    period_id: UUID,
    payload: PayrollTimeDownloadRequest,
    actor: CanPreparePayroll,
    session: DbSession,
) -> Response:
    result, content = await payroll_time_inputs(
        session,
        period_id,
        payload.employee_ids,
        actor,
        expected_csv_sha256=payload.expected_csv_sha256,
    )
    return Response(
        content=content,
        media_type="text/csv",
        headers={
            "Cache-Control": "no-store",
            "Content-Disposition": f'attachment; filename="payroll-time-{period_id}.csv"',
            "X-Payroll-Export-SHA256": result.csv_sha256 or "",
        },
    )


@router.post(
    "/payroll/periods/{period_id}/leave-inputs/preview",
    response_model=PayrollLeaveInputPreview,
)
async def preview_payroll_leave_inputs(
    period_id: UUID,
    payload: PayrollRunCalculateRequest,
    actor: CanPreparePayroll,
    session: DbSession,
    response: Response,
) -> PayrollLeaveInputPreview:
    result, _ = await payroll_leave_inputs(session, period_id, payload.employee_ids, actor)
    response.headers["Cache-Control"] = "no-store"
    return result


@router.post(
    "/payroll/periods/{period_id}/leave-inputs.csv",
    response_class=Response,
    responses={200: {"content": {"text/csv": {"schema": {"type": "string"}}}}},
)
async def download_payroll_leave_inputs(
    period_id: UUID,
    payload: PayrollTimeDownloadRequest,
    actor: CanPreparePayroll,
    session: DbSession,
) -> Response:
    result, content = await payroll_leave_inputs(
        session,
        period_id,
        payload.employee_ids,
        actor,
        expected_csv_sha256=payload.expected_csv_sha256,
    )
    return Response(
        content=content,
        media_type="text/csv",
        headers={
            "Cache-Control": "no-store",
            "Content-Disposition": f'attachment; filename="payroll-leave-{period_id}.csv"',
            "X-Payroll-Export-SHA256": result.csv_sha256 or "",
        },
    )


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


@router.get("/payroll/runs/{run_id}", response_model=PayrollRunResponse)
async def read_payroll_run(
    run_id: UUID, _: CanPreparePayroll, session: DbSession
) -> PayrollRunResponse:
    return PayrollRunResponse.model_validate(await get_payroll_run(session, run_id))


@router.get("/payroll/runs/{run_id}/adjustments", response_model=PayrollAdjustmentList)
async def list_run_adjustments(
    run_id: UUID, actor: CanReadPayrollSensitive, session: DbSession, response: Response
) -> PayrollAdjustmentList:
    response.headers["Cache-Control"] = "no-store"
    return await read_payroll_adjustments(session, run_id, actor)


@router.post("/payroll/runs/{run_id}/adjustments", response_model=PayrollAdjustmentResponse)
async def propose_run_adjustment(
    run_id: UUID,
    payload: PayrollAdjustmentCreate,
    actor: CanPreparePayroll,
    session: DbSession,
    response: Response,
) -> PayrollAdjustmentResponse:
    response.headers["Cache-Control"] = "no-store"
    return await submit_payroll_adjustment(session, run_id, payload, actor)


@router.post(
    "/payroll/runs/{run_id}/adjustments/{adjustment_id}/decision",
    response_model=PayrollAdjustmentResponse,
)
async def decide_run_adjustment(
    run_id: UUID,
    adjustment_id: UUID,
    payload: PayrollAdjustmentReview,
    actor: CanApprovePayroll,
    session: DbSession,
    response: Response,
) -> PayrollAdjustmentResponse:
    response.headers["Cache-Control"] = "no-store"
    return await review_payroll_adjustment(session, run_id, adjustment_id, payload, actor)


@router.post("/payroll/runs/{run_id}/calculate", response_model=PayrollRunResponse)
async def calculate_payroll_run(
    run_id: UUID,
    payload: PayrollSnapshotCalculateRequest,
    actor: CanPreparePayroll,
    session: DbSession,
) -> PayrollRunResponse:
    row = await calculate_payroll_snapshot(
        session, run_id, payload.employee_ids, actor, source_evidence=payload.source_evidence
    )
    return PayrollRunResponse.model_validate(row)


@router.get("/payroll/runs/{run_id}/snapshot", response_model=PayrollRunSnapshotResponse)
async def get_payroll_snapshot(
    run_id: UUID, actor: CanReadPayrollSensitive, session: DbSession, response: Response
) -> PayrollRunSnapshotResponse:
    response.headers["Cache-Control"] = "no-store"
    return await read_payroll_snapshot(session, run_id, actor)


@router.get(
    "/payroll/runs/{run_id}/snapshot/sources/{source}",
    response_class=Response,
    responses={200: {"content": {"text/csv": {"schema": {"type": "string"}}}}},
)
async def download_frozen_payroll_source(
    run_id: UUID,
    source: Literal["time", "leave"],
    actor: CanReadPayrollSensitive,
    session: DbSession,
) -> Response:
    content, digest = await read_frozen_payroll_source(session, run_id, source, actor)
    return Response(
        content=content,
        media_type="text/csv",
        headers={
            "Cache-Control": "no-store",
            "Content-Disposition": f'attachment; filename="payroll-{source}-{run_id}.csv"',
            "X-Payroll-Export-SHA256": digest,
        },
    )


@router.post("/payroll/runs/{run_id}/approve", response_model=PayrollRunResponse)
async def approve_payroll_run(
    run_id: UUID, payload: PayrollRunApproveRequest, actor: CanApprovePayroll, session: DbSession
) -> PayrollRunResponse:
    row = await approve_payroll_snapshot(session, run_id, payload.expected_snapshot_digest, actor)
    return PayrollRunResponse.model_validate(row)


@router.post("/payroll/runs/{run_id}/publish-payslips", response_model=PayslipPublicationResponse)
async def publish_run_payslips(
    run_id: UUID, payload: PayrollRunApproveRequest, actor: CanApprovePayroll, session: DbSession
) -> PayslipPublicationResponse:
    result = await publish_payslips(session, run_id, payload.expected_snapshot_digest, actor)
    return PayslipPublicationResponse.model_validate(result)


@router.get("/payroll/runs/{run_id}/payment-export/preview", response_model=PayrollExportPreview)
async def preview_run_payment_export(
    run_id: UUID, actor: CanApprovePayroll, session: DbSession
) -> PayrollExportPreview:
    return await preview_payroll_export(session, run_id, actor)


@router.post("/payroll/runs/{run_id}/payment-export", response_model=PayrollExportReceipt)
async def register_run_payment_export(
    run_id: UUID, payload: PayrollExportConfirmRequest, actor: CanApprovePayroll, session: DbSession
) -> PayrollExportReceipt:
    result = await register_payroll_export(session, run_id, payload, actor)
    return PayrollExportReceipt.model_validate(result)


@router.get(
    "/payroll/runs/{run_id}/payment-export",
    response_class=Response,
    responses={200: {"content": {"text/csv": {"schema": {"type": "string"}}}}},
)
async def download_run_payment_export(
    run_id: UUID, actor: CanApprovePayroll, session: DbSession
) -> Response:
    content, digest = await download_payroll_export(session, run_id, actor)
    return Response(
        content=content,
        media_type="text/csv",
        headers={
            "Content-Disposition": f'attachment; filename="payroll-handoff-{run_id}.csv"',
            "X-Payroll-Export-SHA256": digest,
        },
    )


@router.get("/payroll/runs/{run_id}/settlements", response_model=PayrollSettlementSummary)
async def get_payroll_settlement_summary(
    run_id: UUID, actor: CanApprovePayroll, session: DbSession, response: Response
) -> PayrollSettlementSummary:
    response.headers["Cache-Control"] = "no-store"
    return await summarize_payroll_settlements(session, run_id, actor)


@router.post("/payroll/runs/{run_id}/close", response_model=PayrollClosureResponse)
async def close_run_period(
    run_id: UUID,
    payload: PayrollClosureRequest,
    actor: CanApprovePayroll,
    session: DbSession,
    response: Response,
) -> PayrollClosureResponse:
    response.headers["Cache-Control"] = "no-store"
    return await close_payroll_period(session, run_id, payload, actor)


@router.get(
    "/payroll/runs/{run_id}/lines/{line_id}/corrections", response_model=PayrollCorrectionPage
)
async def get_run_payroll_corrections(
    run_id: UUID,
    line_id: UUID,
    actor: CanReadPayrollSensitive,
    session: DbSession,
    response: Response,
    limit: Annotated[int, Query(ge=1, le=50)] = 20,
    offset: Annotated[int, Query(ge=0)] = 0,
) -> PayrollCorrectionPage:
    response.headers["Cache-Control"] = "no-store"
    return await list_payroll_corrections(
        session, run_id, line_id, actor, limit=limit, offset=offset
    )


@router.post(
    "/payroll/runs/{run_id}/lines/{line_id}/corrections",
    response_model=PayrollCorrectionResponse,
)
async def propose_run_payroll_correction(
    run_id: UUID,
    line_id: UUID,
    payload: PayrollCorrectionCreate,
    actor: CanPreparePayroll,
    session: DbSession,
    response: Response,
) -> PayrollCorrectionResponse:
    response.headers["Cache-Control"] = "no-store"
    return await propose_payroll_correction(session, run_id, line_id, payload, actor)


@router.get(
    "/payroll/runs/{run_id}/lines/{line_id}/corrections/{correction_id}",
    response_model=PayrollCorrectionResponse,
)
async def show_run_payroll_correction(
    run_id: UUID,
    line_id: UUID,
    correction_id: UUID,
    actor: CanReadPayrollSensitive,
    session: DbSession,
    response: Response,
) -> PayrollCorrectionResponse:
    response.headers["Cache-Control"] = "no-store"
    return await read_payroll_correction(session, run_id, line_id, correction_id, actor)


@router.post(
    "/payroll/runs/{run_id}/lines/{line_id}/corrections/{correction_id}/decision",
    response_model=PayrollCorrectionResponse,
)
async def decide_run_payroll_correction(
    run_id: UUID,
    line_id: UUID,
    correction_id: UUID,
    payload: PayrollCorrectionDecision,
    actor: CanApprovePayroll,
    session: DbSession,
    response: Response,
) -> PayrollCorrectionResponse:
    response.headers["Cache-Control"] = "no-store"
    return await decide_payroll_correction(session, run_id, line_id, correction_id, payload, actor)


@router.get(
    "/payroll/runs/{run_id}/settlements/events", response_model=PayrollSettlementEventsResponse
)
async def get_payroll_settlement_events(
    run_id: UUID,
    actor: CanApprovePayroll,
    session: DbSession,
    limit: Annotated[int, Query(ge=1, le=50)] = 20,
    offset: Annotated[int, Query(ge=0)] = 0,
    payment_reference: Annotated[UUID | None, Query()] = None,
) -> PayrollSettlementEventsResponse:
    return await list_payroll_settlement_events(
        session,
        run_id,
        actor,
        limit=limit,
        offset=offset,
        payment_reference=payment_reference,
    )


@router.get(
    "/payroll/runs/{run_id}/settlements/events/{event_id}",
    response_model=PayrollSettlementEventResponse,
)
async def get_payroll_settlement_event(
    run_id: UUID, event_id: UUID, actor: CanApprovePayroll, session: DbSession
) -> PayrollSettlementEventResponse:
    return await read_payroll_settlement_event(session, run_id, event_id, actor)


@router.post(
    "/payroll/runs/{run_id}/settlements/events", response_model=PayrollSettlementEventResponse
)
async def add_payroll_settlement_event(
    run_id: UUID, payload: PayrollSettlementRequest, actor: CanApprovePayroll, session: DbSession
) -> PayrollSettlementEventResponse:
    return await record_payroll_settlement(session, run_id, payload, actor)


@router.get("/cases", response_model=HrCaseListResponse)
async def list_hr_cases(
    actor: CanManageCases,
    session: DbSession,
    response: Response,
    limit: Annotated[int, Query(ge=1, le=100)] = 50,
    offset: Annotated[int, Query(ge=0)] = 0,
) -> HrCaseListResponse:
    response.headers["Cache-Control"] = "no-store"
    items, total = await HrService(session).list_hr_cases(actor, limit=limit, offset=offset)
    return HrCaseListResponse(items=items, total=total)


@router.post("/cases", response_model=HrCaseResponse, status_code=status.HTTP_201_CREATED)
async def create_hr_case(
    payload: HrCaseCreateRequest, actor: CanManageCases, session: DbSession, response: Response
) -> HrCaseResponse:
    response.headers["Cache-Control"] = "no-store"
    return await HrService(session).create_hr_case(payload, actor)


@router.get(
    "/cases/{case_id}",
    response_model=HrCaseResponse,
    responses={200: {"headers": {"X-HR-Case-Review": {"schema": {"type": "string"}}}}},
)
async def get_hr_case(
    case_id: UUID, actor: CanManageCases, session: DbSession, response: Response
) -> HrCaseResponse:
    response.headers["Cache-Control"] = "no-store"
    case = await HrService(session).get_hr_case(case_id, actor)
    response.headers["X-HR-Case-Review"] = case.reviewed_state_sha256()
    return case


@router.post("/cases/{case_id}/close", response_model=HrCaseResponse)
async def close_hr_case(
    case_id: UUID,
    payload: HrCaseCloseRequest,
    actor: CanManageCases,
    session: DbSession,
    response: Response,
) -> HrCaseResponse:
    response.headers["Cache-Control"] = "no-store"
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


@router.get("/site-attendance/workers", response_model=SiteAttendanceWorkerPage)
async def list_site_attendance_workers(
    project_id: UUID,
    work_date: date,
    actor: CurrentUser,
    session: DbSession,
    search: Annotated[str | None, Query(max_length=120)] = None,
    limit: Annotated[int, Query(ge=1, le=100)] = 30,
    offset: Annotated[int, Query(ge=0)] = 0,
) -> SiteAttendanceWorkerPage:
    return await HrSiteAttendanceService(session).list_workers(
        project_id, work_date, actor, search=search, limit=limit, offset=offset
    )


@router.get("/site-attendance", response_model=SiteAttendancePageResponse)
async def list_site_attendance(
    actor: CurrentUser,
    session: DbSession,
    project_id: UUID | None = None,
    work_date: date | None = None,
    entry_id: UUID | None = None,
    limit: Annotated[int, Query(ge=1, le=100)] = 30,
    offset: Annotated[int, Query(ge=0)] = 0,
) -> SiteAttendancePageResponse:
    return await HrSiteAttendanceService(session).list_entries(
        actor,
        project_id=project_id,
        work_date=work_date,
        entry_id=entry_id,
        limit=limit,
        offset=offset,
    )


@router.post(
    "/site-attendance",
    response_model=SiteAttendanceResponse,
    status_code=status.HTTP_201_CREATED,
)
async def submit_site_attendance(
    payload: SiteAttendanceCreateRequest, actor: CurrentUser, session: DbSession
) -> SiteAttendanceResponse:
    return await HrSiteAttendanceService(session).submit(payload, actor)


@router.post("/site-attendance/{entry_id}/decision", response_model=SiteAttendanceResponse)
async def review_site_attendance(
    entry_id: UUID, payload: SiteAttendanceDecisionRequest, actor: CurrentUser, session: DbSession
) -> SiteAttendanceResponse:
    return await HrSiteAttendanceService(session).decide(entry_id, payload, actor)


@router.post("/site-attendance/{entry_id}/correction", response_model=SiteAttendanceResponse)
async def correct_site_attendance(
    entry_id: UUID, payload: SiteAttendanceCorrectionRequest, actor: CurrentUser, session: DbSession
) -> SiteAttendanceResponse:
    return await HrSiteAttendanceService(session).correct(entry_id, payload, actor)


@router.get(
    "/site-attendance/{entry_id}/history",
    response_model=list[SiteAttendanceSubmissionResponse],
)
async def site_attendance_history(
    entry_id: UUID, actor: CurrentUser, session: DbSession
) -> list[SiteAttendanceSubmissionResponse]:
    return await HrSiteAttendanceService(session).history(entry_id, actor)
