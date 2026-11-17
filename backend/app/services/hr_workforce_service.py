import asyncio
import hashlib
import json
from datetime import UTC, date, datetime, time, timedelta
from decimal import Decimal
from io import BytesIO
from pathlib import Path
from string import Formatter
from typing import Any, Literal
from uuid import UUID, uuid4
from zoneinfo import ZoneInfo

from fastapi import UploadFile
from minio import Minio
from sqlalchemy import (
    Date,
    case,
    false,
    func,
    literal,
    literal_column,
    or_,
    select,
    text,
    type_coerce,
)
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import aliased
from sqlalchemy.sql.elements import ColumnElement

from app.config import get_settings
from app.models.activity_log import ActivityLog
from app.models.hr import (
    HrAdvanceRecovery,
    HrApplication,
    HrAttendanceCorrection,
    HrAttendanceEntry,
    HrBenefitType,
    HrCandidate,
    HrCandidateCorrespondence,
    HrCase,
    HrCertification,
    HrClearanceStep,
    HrCompensationTerm,
    HrDocument,
    HrDocumentVersion,
    HrEmployee,
    HrEmployeeAdvance,
    HrEmployeeBenefit,
    HrEmploymentHistory,
    HrEmploymentPeriod,
    HrGoal,
    HrHoliday,
    HrInterview,
    HrIssuedLetter,
    HrLeaveAccrual,
    HrLeaveLedger,
    HrLeavePolicy,
    HrLeaveRequest,
    HrLeaveRollover,
    HrLeaveType,
    HrLetterTemplate,
    HrOffboardingCase,
    HrOffer,
    HrOnboardingCase,
    HrOnboardingTask,
    HrOvertimeRequest,
    HrPayrollLine,
    HrPayrollPeriod,
    HrPayrollPolicy,
    HrPayrollRun,
    HrPolicyAcknowledgement,
    HrPolicyDocument,
    HrReimbursementClaim,
    HrRequisition,
    HrReview,
    HrReviewCycle,
    HrRosterAllocation,
    HrServiceRequest,
    HrShiftAssignment,
    HrTimesheet,
    HrTrainingCompletion,
    HrTrainingCourse,
    HrTrainingEnrollment,
    HrWorkCalendar,
)
from app.models.project import Project
from app.models.user import User
from app.schemas.hr import (
    ApplicationActivity,
    ApplicationActivityList,
    ApplicationCreateRequest,
    ApplicationListItem,
    ApplicationListResponse,
    ApplicationResponse,
    ApplicationStage,
    ApplicationStageUpdateRequest,
    ApplicationWithdrawalRequest,
    AttendanceCorrectionCreateRequest,
    AttendanceCorrectionDecisionRequest,
    AttendanceEntryCreateRequest,
    AttendanceReviewRequest,
    BenefitTypeCreateRequest,
    CandidateCorrespondenceCreateRequest,
    CandidateCorrespondenceDecisionRequest,
    CandidateCorrespondenceDetail,
    CandidateCreateRequest,
    CertificationCreateRequest,
    ClearanceStepResponse,
    CompensationTermCreateRequest,
    CompensationTermDecisionRequest,
    CompensationTermResponse,
    ComplianceItemResponse,
    EmployeeAdvanceDecision,
    EmployeeAdvanceDisbursement,
    EmployeeAdvancePayment,
    EmployeeAdvanceRecovery,
    EmployeeAdvanceRequest,
    EmployeeAdvanceResponse,
    EmployeeBenefitCreateRequest,
    ExpiringComplianceResponse,
    GoalCreateRequest,
    GoalUpdateRequest,
    HolidayCreateRequest,
    HolidayResponse,
    HrCaseCloseRequest,
    HrCaseCreateRequest,
    HrCaseResponse,
    HrDocumentDecisionRequest,
    HrDocumentDownloadResponse,
    HrDocumentResponse,
    HrServiceRequestAssignee,
    HrServiceRequestAssignmentRequest,
    HrServiceRequestCreateRequest,
    HrServiceRequestResolveRequest,
    InterviewCreateRequest,
    InterviewerOption,
    InterviewerOptions,
    InterviewUpdateRequest,
    LeaveBalanceItem,
    LeaveBalanceListResponse,
    LeaveLedgerAdjustRequest,
    LeavePolicyCreateRequest,
    LeavePolicyDecisionRequest,
    LeaveRequestCreateRequest,
    LeaveRequestDecisionRequest,
    LeaveRequestDecisionState,
    LeaveRequestFields,
    LeaveRequestResubmitRequest,
    LeaveTypeCreateRequest,
    LeaveUnitsQuery,
    LetterDecisionRequest,
    LetterDetail,
    LetterDraftRequest,
    LetterGenerateRequest,
    LetterListResponse,
    LetterRenderResponse,
    LetterSummary,
    LetterTemplateCreateRequest,
    MyPolicyFileResponse,
    MyPolicyListResponse,
    MyPolicyResponse,
    OffboardingCaseResponse,
    OffboardingCompleteRequest,
    OffboardingInitiateRequest,
    OffboardingStepUpdateRequest,
    OfferConvertRequest,
    OfferCreateRequest,
    OfferDecisionRequest,
    OfferReissueRequest,
    OnboardingCaseCreateRequest,
    OnboardingCaseResponse,
    OnboardingTaskResponse,
    OnboardingTaskUpdateRequest,
    OvertimeDecisionRequest,
    OvertimeRequestCreateRequest,
    PayrollPeriodCreateRequest,
    PayrollPolicyCreateRequest,
    PayrollPolicyDraftUpdateRequest,
    PayrollRunCreateRequest,
    PolicyAcknowledgementResponse,
    PolicyAcknowledgeRequest,
    PolicyDocumentCreateRequest,
    PolicyDocumentResponse,
    ReimbursementCreateRequest,
    ReimbursementDecisionRequest,
    ReimbursementPayable,
    ReimbursementPayableResponse,
    RequisitionCreateRequest,
    RequisitionDecisionRequest,
    ReviewCreateRequest,
    ReviewCycleCreateRequest,
    RosterAllocationCreateRequest,
    SelfTrainingItem,
    SelfTrainingListResponse,
    ShiftAssignmentCreateRequest,
    ShiftAssignmentResponse,
    TimesheetCreateRequest,
    TimesheetDecisionRequest,
    TimesheetSelfResubmitRequest,
    TrainingCompletionRequest,
    TrainingCompletionResponse,
    TrainingCourseCreateRequest,
    TrainingEnrollmentCreateRequest,
    TrainingEnrollmentUpdateRequest,
    WorkCalendarCreateRequest,
    WorkCalendarDecisionRequest,
    WorkCalendarResponse,
    WorkCalendarUpdateRequest,
    WorkScheduleResponse,
)
from app.services.audit_service import AuditService
from app.services.hr_crypto import (
    MAX_HR_DOCUMENT_SIZE,
    decrypt_hr_value,
    encrypt_hr_value,
    mask_identifier,
    validate_hr_document_file,
)
from app.services.hr_leave_accrual import ensure_leave_year_open
from app.services.hr_leave_date_evidence import (
    require_approved_leave_debit,
    require_unlocked_leave_payroll,
)
from app.services.hr_manager_review import (
    REVIEW_EMPLOYMENT_STATES,
    eligible_reviewer,
    require_manager_recommendation,
    start_manager_review,
    verify_request_revision,
)
from app.services.hr_offboarding_custody import (
    IT_AREA,
    STORE_AREA,
    confirmed_access_revocation,
    require_custody_clearance,
)
from app.services.hr_payroll_snapshot import lock_payroll_periods, validate_payroll_policy
from app.services.hr_separation_settlement import FINANCE_AREA, require_settlement_clearance
from app.services.idempotency import bind, resolve_or_reserve, validate_key
from app.services.notification_service import NotificationService
from app.services.storage_service import discard_new_uploads, minio_client, minio_signed_url_client
from app.utils.exceptions import AppException, NotFoundException, PermissionDeniedException
from app.utils.permissions import (
    PERMISSION_HR_CASES_RESTRICTED,
    PERMISSION_HR_DOCUMENTS_MANAGE,
    PERMISSION_HR_EMPLOYEES_SENSITIVE,
    PERMISSION_HR_PAYROLL_APPROVE,
    PERMISSION_HR_PAYROLL_SENSITIVE,
    PERMISSION_HR_POLICY_MANAGE,
    PERMISSION_HR_REQUESTS_PROCESS,
    ROLE_HR_MANAGER,
    ensure_permission,
    has_permission,
    roles_with_permission,
)
from app.utils.security import utc_now
from app.utils.time import business_today

RESTRICTED_DOC_CATEGORIES = {"confidential", "medical", "compensation", "disciplinary"}
SIGNED_URL_SECONDS = 300
WORKDAYS = ("MON", "TUE", "WED", "THU", "FRI", "SAT", "SUN")


def _stored_leave_fields(request: HrLeaveRequest) -> LeaveRequestFields:
    period: Literal["morning", "afternoon"] | None
    if request.half_day_period == "morning":
        period = "morning"
    elif request.half_day_period == "afternoon":
        period = "afternoon"
    elif request.half_day_period is None:
        period = None
    else:
        raise AppException("The request has an invalid half-day period.", status_code=422)
    return LeaveRequestFields(
        leave_type_id=request.leave_type_id,
        start_date=request.start_date,
        end_date=request.end_date,
        is_half_day=request.is_half_day,
        half_day_period=period,
        attachment_document_id=request.attachment_document_id,
    )


class HrWorkforceService:
    """Domain operations for recruitment, documents, attendance, leave, offboarding, and P2."""

    def __init__(self, session: AsyncSession) -> None:
        self.session = session
        self.settings = get_settings()
        self.audit = AuditService(session)

    async def _commit_and_refresh(self, *instances: object) -> None:
        await self.session.commit()
        for instance in instances:
            await self.session.refresh(instance)

    async def _require_employee(self, employee_id: UUID, *, for_update: bool = False) -> HrEmployee:
        query = select(HrEmployee).where(
            HrEmployee.id == employee_id, HrEmployee.deleted_at.is_(None)
        )
        if for_update:
            query = query.with_for_update().execution_options(populate_existing=True)
        emp = await self.session.scalar(query)
        if emp is None:
            raise NotFoundException("Employee")
        return emp

    async def require_self_employee(self, user: User) -> HrEmployee:
        return await self._employee_for_user(user)

    async def _employee_for_user(self, user: User, *, for_update: bool = False) -> HrEmployee:
        query = select(HrEmployee).where(
            HrEmployee.user_id == user.id,
            HrEmployee.deleted_at.is_(None),
            HrEmployee.employment_status.in_(REVIEW_EMPLOYMENT_STATES),
        )
        if for_update:
            query = query.with_for_update().execution_options(populate_existing=True)
        emp = await self.session.scalar(query)
        if emp is None:
            raise AppException(
                "No employee profile is linked to this user account.",
                status_code=404,
                error_code="EMPLOYEE_PROFILE_NOT_LINKED",
            )
        return emp

    # --- Recruitment (HR-007, HR-008) ---

    async def create_requisition(
        self, payload: RequisitionCreateRequest, actor: User
    ) -> HrRequisition:
        req = HrRequisition(
            requisition_code=payload.requisition_code.strip(),
            title=payload.title.strip(),
            department_id=payload.department_id,
            position_id=payload.position_id,
            project_id=payload.project_id,
            employment_category=payload.employment_category,
            headcount_requested=payload.headcount_requested,
            status="draft",
            justification=payload.justification,
            budget_notes=payload.budget_notes,
            requested_by_id=actor.id,
            target_join_date=payload.target_join_date,
        )
        self.session.add(req)
        try:
            await self.session.flush()
            await self.audit.record(
                action="hr.requisition.created",
                user_id=actor.id,
                entity_type="hr_requisitions",
                entity_id=req.id,
                new_values={"code": req.requisition_code, "title": req.title},
            )
            await self.session.commit()
            await self.session.refresh(req)
        except IntegrityError as exc:
            await self.session.rollback()
            raise AppException(
                "Requisition code already exists.",
                status_code=409,
                error_code="REQUISITION_EXISTS",
            ) from exc
        return req

    async def list_requisitions(
        self,
        *,
        status: str | None = None,
        code: str | None = None,
        limit: int = 100,
        offset: int = 0,
    ) -> tuple[list[HrRequisition], int]:
        stmt = select(HrRequisition).where(HrRequisition.deleted_at.is_(None))
        count_stmt = select(func.count(HrRequisition.id)).where(HrRequisition.deleted_at.is_(None))
        if status:
            stmt = stmt.where(HrRequisition.status == status)
            count_stmt = count_stmt.where(HrRequisition.status == status)
        if code is not None:
            stmt = stmt.where(HrRequisition.requisition_code == code)
            count_stmt = count_stmt.where(HrRequisition.requisition_code == code)
        rows = list(
            await self.session.scalars(
                stmt.order_by(HrRequisition.created_at.desc(), HrRequisition.id.desc())
                .limit(limit)
                .offset(offset)
            )
        )
        total = int(await self.session.scalar(count_stmt) or 0)
        return rows, total

    async def get_requisition(self, requisition_id: UUID, *, lock: bool = False) -> HrRequisition:
        statement = select(HrRequisition).where(
            HrRequisition.id == requisition_id, HrRequisition.deleted_at.is_(None)
        )
        if lock:
            statement = statement.with_for_update().execution_options(populate_existing=True)
        req = await self.session.scalar(statement)
        if req is None:
            raise NotFoundException("Requisition")
        return req

    async def decide_requisition(
        self, requisition_id: UUID, payload: RequisitionDecisionRequest, actor: User
    ) -> HrRequisition:
        req = await self.get_requisition(requisition_id, lock=True)
        if (
            payload.expected_updated_at is not None
            and req.updated_at != payload.expected_updated_at
        ):
            raise AppException(
                "Review the current requisition before recording a decision.", status_code=409
            )
        transitions = {
            "draft": {"submitted", "cancelled"},
            "submitted": {"approved", "rejected", "cancelled"},
            "approved": {"open", "cancelled"},
            "open": {"on_hold", "filled", "closed", "cancelled"},
            "on_hold": {"open", "closed", "cancelled"},
        }
        if payload.status not in transitions.get(req.status, set()):
            raise AppException("This requisition cannot make that transition.", status_code=409)
        if payload.status != "submitted" and not has_permission(
            actor, PERMISSION_HR_EMPLOYEES_SENSITIVE
        ):
            raise PermissionDeniedException(PERMISSION_HR_EMPLOYEES_SENSITIVE)
        if (
            payload.status == "filled"
            and await self._hired_headcount(req.id) < req.headcount_requested
        ):
            raise AppException(
                "The requisition still has unfilled vacancies.",
                status_code=409,
                error_code="REQUISITION_VACANCIES_REMAIN",
            )
        if payload.status == "rejected":
            reason = (payload.notes or "").strip()
            if not reason:
                raise AppException("Rejection requires a reason.", status_code=422)
            req.rejection_reason = reason
        req.status = payload.status
        if payload.status in {"approved", "open"} and req.approved_by_id is None:
            req.approved_by_id = actor.id
            req.approved_at = utc_now()
        await self.audit.record(
            action=f"hr.requisition.{payload.status}",
            user_id=actor.id,
            entity_type="hr_requisitions",
            entity_id=req.id,
        )
        await self._commit_and_refresh(req)
        return req

    async def create_candidate(self, payload: CandidateCreateRequest, actor: User) -> HrCandidate:
        cand = HrCandidate(
            candidate_code=payload.candidate_code.strip(),
            full_name=payload.full_name.strip(),
            email=payload.email.lower() if payload.email else None,
            phone=payload.phone,
            source=payload.source,
            current_organization=payload.current_organization,
            years_experience=payload.years_experience,
            notes=payload.notes,
            created_by_id=actor.id,
        )
        self.session.add(cand)
        try:
            await self.session.flush()
            await self.audit.record(
                action="hr.candidate.created",
                user_id=actor.id,
                entity_type="hr_candidates",
                entity_id=cand.id,
                new_values={"code": cand.candidate_code},
            )
            await self.session.commit()
        except IntegrityError as exc:
            await self.session.rollback()
            raise AppException(
                "Candidate code already exists.",
                status_code=409,
                error_code="CANDIDATE_EXISTS",
            ) from exc
        return cand

    async def list_candidates(
        self,
        *,
        search: str | None = None,
        code: str | None = None,
        limit: int = 100,
        offset: int = 0,
    ) -> tuple[list[HrCandidate], int]:
        stmt = select(HrCandidate).where(HrCandidate.deleted_at.is_(None))
        count_stmt = select(func.count(HrCandidate.id)).where(HrCandidate.deleted_at.is_(None))
        if code is not None:
            stmt = stmt.where(HrCandidate.candidate_code == code)
            count_stmt = count_stmt.where(HrCandidate.candidate_code == code)
        if search and (term := search.strip()):
            filt = or_(
                HrCandidate.full_name.icontains(term, autoescape=True),
                HrCandidate.candidate_code.icontains(term, autoescape=True),
                HrCandidate.email.icontains(term, autoescape=True),
            )
            stmt = stmt.where(filt)
            count_stmt = count_stmt.where(filt)
        rows = list(
            await self.session.scalars(
                stmt.order_by(HrCandidate.created_at.desc(), HrCandidate.id.desc())
                .limit(limit)
                .offset(offset)
            )
        )
        total = int(await self.session.scalar(count_stmt) or 0)
        return rows, total

    async def get_candidate(self, candidate_id: UUID) -> HrCandidate:
        row = await self.session.scalar(
            select(HrCandidate).where(
                HrCandidate.id == candidate_id, HrCandidate.deleted_at.is_(None)
            )
        )
        if row is None:
            raise NotFoundException("Candidate")
        return row

    async def create_application(
        self, payload: ApplicationCreateRequest, actor: User
    ) -> HrApplication:
        requisition = await self.session.scalar(
            select(HrRequisition)
            .where(HrRequisition.id == payload.requisition_id, HrRequisition.deleted_at.is_(None))
            .with_for_update()
        )
        if requisition is None:
            raise NotFoundException("Requisition")
        if (
            payload.expected_requisition_updated_at is not None
            and requisition.updated_at != payload.expected_requisition_updated_at
        ):
            raise AppException("Review the current requisition before applying.", status_code=409)
        if requisition.status != "open":
            raise AppException("Requisition must be open to receive applications.", status_code=409)
        if not await self.session.scalar(
            select(HrCandidate.id).where(
                HrCandidate.id == payload.candidate_id, HrCandidate.deleted_at.is_(None)
            )
        ):
            raise NotFoundException("Candidate")
        app_row = HrApplication(
            requisition_id=payload.requisition_id,
            candidate_id=payload.candidate_id,
            stage="applied",
            screening_notes=payload.screening_notes,
            assigned_recruiter_id=actor.id,
        )
        self.session.add(app_row)
        try:
            await self.session.flush()
            await self.audit.record(
                action="hr.application.created",
                user_id=actor.id,
                entity_type="hr_applications",
                entity_id=app_row.id,
            )
            await self.session.commit()
        except IntegrityError as exc:
            await self.session.rollback()
            raise AppException(
                "Candidate already applied to this requisition.",
                status_code=409,
                error_code="APPLICATION_EXISTS",
            ) from exc
        return app_row

    async def list_applications(
        self,
        *,
        requisition_id: UUID | None = None,
        candidate_id: UUID | None = None,
        search: str | None = None,
        stage: ApplicationStage | None = None,
        limit: int = 100,
        offset: int = 0,
    ) -> ApplicationListResponse:
        catalog = (
            select(
                HrApplication,
                HrCandidate.full_name,
                HrCandidate.candidate_code,
                HrRequisition.title,
            )
            .join(HrCandidate, HrCandidate.id == HrApplication.candidate_id)
            .join(HrRequisition, HrRequisition.id == HrApplication.requisition_id)
            .where(HrCandidate.deleted_at.is_(None), HrRequisition.deleted_at.is_(None))
        )
        if requisition_id:
            catalog = catalog.where(HrApplication.requisition_id == requisition_id)
        if candidate_id:
            catalog = catalog.where(HrApplication.candidate_id == candidate_id)
        if stage:
            catalog = catalog.where(HrApplication.stage == stage)
        if search and (term := search.strip()):
            catalog = catalog.where(
                or_(
                    HrCandidate.full_name.icontains(term, autoescape=True),
                    HrCandidate.candidate_code.icontains(term, autoescape=True),
                )
            )
        count = await self.session.scalar(select(func.count()).select_from(catalog.subquery()))
        rows = await self.session.execute(
            catalog.order_by(HrApplication.created_at.desc(), HrApplication.id.desc())
            .limit(limit)
            .offset(offset)
        )
        return ApplicationListResponse(
            items=[
                ApplicationListItem(
                    **ApplicationResponse.model_validate(row).model_dump(),
                    candidate_name=name,
                    candidate_code=code,
                    position_title=title,
                )
                for row, name, code, title in rows
            ],
            total=count or 0,
        )

    async def list_application_activity(
        self, application_id: UUID, *, limit: int, offset: int
    ) -> ApplicationActivityList:
        await self.get_application(application_id)
        terminal = {
            "hr.application.created": "applied",
            "hr.application.withdrawn": "withdrawn",
            "hr.application.hired": "hired",
        }
        filters = (
            ActivityLog.entity_type == literal_column("'hr_applications'"),
            ActivityLog.entity_id == application_id,
            ActivityLog.deleted_at.is_(None),
            ActivityLog.action.in_([*terminal, "hr.application.stage_changed"]),
        )
        stage = case(
            terminal, value=ActivityLog.action, else_=ActivityLog.new_values["stage"].astext
        )
        query = (
            select(ActivityLog.id, stage, User.full_name, ActivityLog.created_at)
            .outerjoin(User, User.id == ActivityLog.user_id)
            .where(*filters)
            .order_by(ActivityLog.created_at.desc(), ActivityLog.id.desc())
            .limit(limit)
            .offset(offset)
        )
        rows = await self.session.execute(query)
        total = await self.session.scalar(
            select(func.count()).select_from(ActivityLog).where(*filters)
        )
        return ApplicationActivityList(
            items=[
                ApplicationActivity(
                    id=log_id, stage=stage_name or "unknown", actor_name=name, created_at=created
                )
                for log_id, stage_name, name, created in rows
            ],
            total=total or 0,
        )

    async def get_application(self, application_id: UUID, *, lock: bool = False) -> HrApplication:
        query = select(HrApplication).where(HrApplication.id == application_id)
        if lock:
            query = query.with_for_update().execution_options(populate_existing=True)
        app_row = await self.session.scalar(query)
        if app_row is None:
            raise NotFoundException("Application")
        return app_row

    @staticmethod
    def _require_open_recruitment_application(application: HrApplication) -> None:
        if application.stage == "withdrawn":
            raise AppException(
                "This application has been withdrawn.",
                status_code=409,
                error_code="APPLICATION_WITHDRAWN",
            )

        if application.stage == "rejected":
            raise AppException(
                "This application has been rejected.",
                status_code=409,
                error_code="APPLICATION_REJECTED",
            )

    async def _close_application_recruitment(self, application: HrApplication) -> dict[str, int]:

        # Related recruitment writers also lock the application before any child.
        offers = list(
            await self.session.scalars(
                select(HrOffer).where(
                    HrOffer.application_id == application.id,
                    HrOffer.status.in_(
                        ("draft", "pending_approval", "approved", "issued", "accepted", "converted")
                    ),
                )
            )
        )
        if any(offer.status in {"accepted", "converted"} for offer in offers):
            raise AppException(
                "An accepted offer requires its own disposition before closing the application.",
                status_code=409,
                error_code="OFFER_ALREADY_ACCEPTED",
            )
        for offer in offers:
            offer.status = "withdrawn"
        scheduled = list(
            await self.session.scalars(
                select(HrInterview).where(
                    HrInterview.application_id == application.id, HrInterview.status == "scheduled"
                )
            )
        )
        for interview in scheduled:
            interview.status = "cancelled"
            await self._notify_interviewer(interview, cancelled=True)
        return {"cancelled_interviews": len(scheduled), "withdrawn_offers": len(offers)}

    async def _withdraw_application(
        self, application: HrApplication, payload: ApplicationWithdrawalRequest, actor: User
    ) -> HrApplication:
        values = payload.model_dump(exclude={"expected_stage", "reason"})
        values["withdrawal_reason"] = payload.reason
        if application.stage == "withdrawn":
            if all(getattr(application, field) == value for field, value in values.items()):
                return application
            self._require_open_recruitment_application(application)
        if application.stage != payload.expected_stage:
            raise AppException(
                "Review the current application stage before withdrawing.", status_code=409
            )
        if (
            payload.retention_review_on is not None
            and payload.retention_review_on < business_today()
        ):
            raise AppException("The retention review date cannot be in the past.", status_code=422)
        closed = await self._close_application_recruitment(application)
        application.stage = "withdrawn"
        application.withdrawn_at = utc_now()
        for field, value in values.items():
            setattr(application, field, value)
        await self.audit.record(
            action="hr.application.withdrawn",
            user_id=actor.id,
            entity_type="hr_applications",
            entity_id=application.id,
            new_values={
                "retention_decision": payload.retention_decision,
                **closed,
            },
        )
        await self._commit_and_refresh(application)
        return application

    async def update_application_stage(
        self, application_id: UUID, payload: ApplicationStageUpdateRequest, actor: User
    ) -> HrApplication:
        app_row = await self.get_application(application_id, lock=True)
        if (
            payload.expected_updated_at is not None
            and app_row.updated_at != payload.expected_updated_at
        ):
            raise AppException(
                "Review the current application before changing stage.", status_code=409
            )
        if payload.withdrawal is not None:
            return await self._withdraw_application(app_row, payload.withdrawal, actor)
        transitions = {
            "applied": {"screening", "rejected"},
            "screening": {"shortlisted", "rejected"},
            "shortlisted": {"interview", "rejected"},
            "interview": {"evaluation", "rejected"},
            "evaluation": {"offer", "rejected"},
            "offer": {"rejected"},
        }
        if payload.stage not in transitions.get(app_row.stage, set()):
            raise AppException("This application cannot make that transition.", status_code=409)
        if payload.stage == "evaluation" and not await self.session.scalar(
            select(HrInterview.id)
            .where(HrInterview.application_id == app_row.id, HrInterview.status == "completed")
            .limit(1)
        ):
            raise AppException("Record a completed interview before evaluation.", status_code=409)
        closed = {}
        if payload.stage == "rejected":
            reason = (payload.rejection_reason or "").strip()
            if not reason:
                raise AppException("Rejection requires a reason.", status_code=422)
            closed = await self._close_application_recruitment(app_row)
            app_row.rejection_reason = reason
        app_row.stage = payload.stage
        if payload.overall_score is not None:
            app_row.overall_score = payload.overall_score
        if payload.screening_notes is not None:
            app_row.screening_notes = payload.screening_notes
        await self.audit.record(
            action="hr.application.stage_changed",
            user_id=actor.id,
            entity_type="hr_applications",
            entity_id=app_row.id,
            new_values={"stage": payload.stage, **closed},
        )
        await self._commit_and_refresh(app_row)
        return app_row

    async def list_interviewer_options(
        self, *, search: str, limit: int, offset: int
    ) -> InterviewerOptions:
        exact_code = func.lower(User.employee_code) == search.lower()
        filters = (
            User.is_active.is_(True),
            User.deleted_at.is_(None),
            or_(exact_code, User.full_name.icontains(search, autoescape=True)),
        )
        rows = await self.session.execute(
            select(User.id, User.full_name, User.employee_code)
            .where(*filters)
            .order_by(case((exact_code, 0), else_=1), func.lower(User.full_name), User.id)
            .limit(limit)
            .offset(offset)
        )
        total = await self.session.scalar(select(func.count()).select_from(User).where(*filters))
        return InterviewerOptions(
            items=[
                InterviewerOption(id=user_id, full_name=name, employee_code=code)
                for user_id, name, code in rows
            ],
            total=total or 0,
        )

    async def _notify_interviewer(
        self, interview: HrInterview, *, cancelled: bool = False, require_active: bool = False
    ) -> None:
        if interview.interviewer_user_id is None:
            return
        recipient = await self.session.scalar(
            select(User.id).where(
                User.id == interview.interviewer_user_id,
                User.is_active.is_(True),
                User.deleted_at.is_(None),
            )
        )
        if recipient is None and require_active:
            raise AppException("Choose an active portal interviewer.", status_code=422)
        if recipient is None or interview.scheduled_at is None:
            return
        await NotificationService(self.session).create(
            user_id=recipient,
            title="Recruitment interview cancelled"
            if cancelled
            else "Recruitment interview invitation",
            body=(
                "An interview assigned to you was cancelled. Contact HR if you need details."
                if cancelled
                else "HR has invited you to an interview. Contact HR for the schedule and details."
            ),
            notification_type="hr_interview_cancelled" if cancelled else "hr_interview_invitation",
            send_email=False,
        )

    async def create_interview(self, payload: InterviewCreateRequest, actor: User) -> HrInterview:
        application = await self.get_application(payload.application_id, lock=True)
        schedule = payload.model_dump(exclude={"interview_id", "expected_application_updated_at"})
        if payload.interview_id is not None:
            existing = await self.session.get(HrInterview, payload.interview_id)
            if existing is not None:
                if any(getattr(existing, key) != value for key, value in schedule.items()):
                    raise AppException("This interview reference is already used.", status_code=409)
                return existing
        if (
            payload.expected_application_updated_at is not None
            and application.updated_at != payload.expected_application_updated_at
        ):
            raise AppException("Review the current application before scheduling.", status_code=409)
        self._require_open_recruitment_application(application)
        if application.stage not in {"shortlisted", "interview", "evaluation"}:
            raise AppException(
                "Shortlist the application before scheduling an interview.",
                status_code=409,
                error_code="APPLICATION_NOT_READY_FOR_INTERVIEW",
            )
        interview = HrInterview(id=payload.interview_id, **schedule)
        await self._notify_interviewer(interview, require_active=True)
        self.session.add(interview)
        try:
            await self.session.flush()
        except IntegrityError as error:
            if getattr(error.orig, "sqlstate", None) == "23505":
                raise AppException(
                    "This interview reference is already used.", status_code=409
                ) from error
            raise
        await self.audit.record(
            action="hr.interview.scheduled",
            user_id=actor.id,
            entity_type="hr_interviews",
            entity_id=interview.id,
        )
        await self._commit_and_refresh(interview)
        return interview

    async def update_interview(
        self, interview_id: UUID, payload: InterviewUpdateRequest, actor: User
    ) -> HrInterview:
        application_id = await self.session.scalar(
            select(HrInterview.application_id).where(HrInterview.id == interview_id)
        )
        if application_id is None:
            raise NotFoundException("Interview")
        self._require_open_recruitment_application(
            await self.get_application(application_id, lock=True)
        )
        interview = await self.session.scalar(
            select(HrInterview).where(HrInterview.id == interview_id).with_for_update()
        )
        if interview is None:
            raise NotFoundException("Interview")
        if (
            payload.expected_updated_at is not None
            and interview.updated_at != payload.expected_updated_at
        ):
            raise AppException("Review the current interview before updating.", status_code=409)
        if payload.recommendation is not None:
            interview.recommendation = payload.recommendation
        if payload.score is not None:
            interview.score = payload.score
        if payload.feedback_notes is not None:
            interview.feedback_notes = payload.feedback_notes
        if payload.status is not None:
            prior_status = interview.status
            interview.status = payload.status
            if prior_status == "scheduled" and payload.status == "cancelled":
                await self._notify_interviewer(interview, cancelled=True)
            if prior_status == "cancelled" and payload.status == "scheduled":
                await self._notify_interviewer(interview, require_active=True)
        await self.audit.record(
            action="hr.interview.updated",
            user_id=actor.id,
            entity_type="hr_interviews",
            entity_id=interview.id,
            new_values={"status": interview.status, "recommendation": interview.recommendation},
        )
        await self._commit_and_refresh(interview)
        return interview

    async def list_interviews(
        self, *, application_id: UUID | None = None
    ) -> tuple[list[HrInterview], int]:
        stmt = select(HrInterview)
        count_stmt = select(func.count(HrInterview.id))
        if application_id:
            stmt = stmt.where(HrInterview.application_id == application_id)
            count_stmt = count_stmt.where(HrInterview.application_id == application_id)
        rows = list(await self.session.scalars(stmt.order_by(HrInterview.round_number.asc())))
        total = int(await self.session.scalar(count_stmt) or 0)
        return rows, total

    async def create_offer(self, payload: OfferCreateRequest, actor: User) -> HrOffer:
        if payload.supersedes_offer_id is not None:
            if payload.expected_application_updated_at is not None:
                raise AppException(
                    "Use the offer reissue endpoint with an offer precondition.", status_code=422
                )
            reissue_payload = OfferReissueRequest(
                **payload.model_dump(
                    exclude={
                        "application_id",
                        "supersedes_offer_id",
                        "expected_application_updated_at",
                    }
                )
            )
            return await self.reissue_offer(
                payload.supersedes_offer_id,
                reissue_payload,
                actor,
                expected_application_id=payload.application_id,
            )
        if payload.proposed_salary is not None:
            raise PermissionDeniedException(PERMISSION_HR_PAYROLL_SENSITIVE)
        if payload.valid_until is not None and payload.valid_until < business_today():
            raise AppException("Offer validity date must not be in the past.", status_code=422)
        application = await self.get_application(payload.application_id, lock=True)
        if (
            payload.expected_application_updated_at is not None
            and application.updated_at != payload.expected_application_updated_at
        ):
            raise AppException(
                "Review the current application before drafting an offer.", status_code=409
            )
        if application.stage != "evaluation":
            raise AppException("Complete interviews before drafting an offer.", status_code=409)
        if await self.session.scalar(
            select(HrOffer.id)
            .where(
                HrOffer.application_id == application.id,
                HrOffer.status.notin_(["declined", "withdrawn", "expired", "superseded"]),
            )
            .limit(1)
        ):
            raise AppException(
                "This application already has an open or accepted offer.", status_code=409
            )
        if payload.document_version_id is not None:
            await self._offer_document_version(
                payload.document_version_id, application, actor, attaching=True
            )
        next_version = (
            int(
                await self.session.scalar(
                    select(func.coalesce(func.max(HrOffer.version_number), 0)).where(
                        HrOffer.application_id == application.id
                    )
                )
                or 0
            )
            + 1
        )
        offer = HrOffer(
            offer_code=payload.offer_code.strip(),
            application_id=payload.application_id,
            proposed_title=payload.proposed_title.strip(),
            proposed_department_id=payload.proposed_department_id,
            proposed_position_id=payload.proposed_position_id,
            proposed_join_date=payload.proposed_join_date,
            proposed_salary_encrypted=encrypt_hr_value(payload.proposed_salary),
            proposed_salary_masked=mask_identifier(payload.proposed_salary),
            currency=payload.currency or self.settings.business_currency,
            status="draft",
            valid_until=payload.valid_until,
            version_number=next_version,
            document_version_id=payload.document_version_id,
            notes=payload.notes,
        )
        self.session.add(offer)
        try:
            await self.session.flush()
            await self.audit.record(
                action="hr.offer.created",
                user_id=actor.id,
                entity_type="hr_offers",
                entity_id=offer.id,
                new_values={"offer_code": offer.offer_code, "version_number": offer.version_number},
            )
            await self.session.commit()
            await self.session.refresh(offer)
        except IntegrityError as exc:
            await self.session.rollback()
            raise AppException(
                "Offer code already exists.",
                status_code=409,
                error_code="OFFER_EXISTS",
            ) from exc
        return offer

    async def reissue_offer(
        self,
        offer_id: UUID,
        payload: OfferReissueRequest,
        actor: User,
        *,
        expected_application_id: UUID | None = None,
    ) -> HrOffer:
        if payload.proposed_salary is not None:
            raise PermissionDeniedException(PERMISSION_HR_PAYROLL_SENSITIVE)
        if payload.valid_until is not None and payload.valid_until < business_today():
            raise AppException("Offer validity date must not be in the past.", status_code=422)
        application_id = await self.session.scalar(
            select(HrOffer.application_id).where(HrOffer.id == offer_id)
        )
        if application_id is None:
            raise NotFoundException("Offer")
        if expected_application_id is not None and application_id != expected_application_id:
            raise AppException(
                "Superseded offer belongs to a different application.", status_code=422
            )
        application = await self.get_application(application_id, lock=True)
        self._require_open_recruitment_application(application)
        prior_offer = await self.session.scalar(
            select(HrOffer)
            .where(HrOffer.id == offer_id)
            .with_for_update()
            .execution_options(populate_existing=True)
        )
        if prior_offer is None:
            raise NotFoundException("Offer")
        if (
            payload.expected_updated_at is not None
            and prior_offer.updated_at != payload.expected_updated_at
        ):
            raise AppException("Review the current offer before reissuing.", status_code=409)
        if prior_offer.status == "converted" or prior_offer.converted_employee_id is not None:
            raise AppException(
                "Converted offers cannot be superseded.",
                status_code=409,
                error_code="OFFER_ALREADY_CONVERTED",
            )
        if (
            prior_offer.status in {"superseded", "withdrawn"}
            or prior_offer.superseded_by_id is not None
        ):
            raise AppException(
                "This offer version cannot be superseded.",
                status_code=409,
                error_code="OFFER_SUPERSEDED",
            )
        if prior_offer.document_version_id is not None and payload.document_version_id in {
            None,
            prior_offer.document_version_id,
        }:
            raise AppException(
                "Select a different approved file for the replacement offer.", status_code=422
            )
        if payload.document_version_id is not None:
            await self._offer_document_version(
                payload.document_version_id, application, actor, attaching=True
            )
        if await self.session.scalar(
            select(HrOffer.id)
            .where(
                HrOffer.application_id == prior_offer.application_id,
                HrOffer.id != prior_offer.id,
                HrOffer.status.notin_(["declined", "withdrawn", "expired", "superseded"]),
            )
            .limit(1)
        ):
            raise AppException(
                "This application already has an open or accepted offer.", status_code=409
            )
        max_version = int(
            await self.session.scalar(
                select(func.coalesce(func.max(HrOffer.version_number), 0)).where(
                    HrOffer.application_id == prior_offer.application_id
                )
            )
            or 0
        )
        now = utc_now()
        prior_offer.status = "superseded"
        prior_offer.superseded_at = now
        new_offer = HrOffer(
            offer_code=payload.offer_code.strip(),
            application_id=prior_offer.application_id,
            proposed_title=payload.proposed_title.strip(),
            proposed_department_id=payload.proposed_department_id,
            proposed_position_id=payload.proposed_position_id,
            proposed_join_date=payload.proposed_join_date,
            proposed_salary_encrypted=encrypt_hr_value(payload.proposed_salary),
            proposed_salary_masked=mask_identifier(payload.proposed_salary),
            currency=payload.currency or prior_offer.currency or self.settings.business_currency,
            status="draft",
            valid_until=payload.valid_until,
            version_number=max(prior_offer.version_number, max_version) + 1,
            document_version_id=payload.document_version_id,
            supersedes_offer_id=prior_offer.id,
            notes=payload.notes,
        )
        self.session.add(new_offer)
        try:
            await self.session.flush()
            prior_offer.superseded_by_id = new_offer.id
            await self.audit.record(
                action="hr.offer.reissued",
                user_id=actor.id,
                entity_type="hr_offers",
                entity_id=new_offer.id,
                new_values={
                    "offer_code": new_offer.offer_code,
                    "version_number": new_offer.version_number,
                    "supersedes_offer_id": str(prior_offer.id),
                },
            )
            await self.session.commit()
            await self.session.refresh(new_offer)
        except IntegrityError as exc:
            await self.session.rollback()
            raise AppException(
                "Offer code already exists.",
                status_code=409,
                error_code="OFFER_EXISTS",
            ) from exc
        return new_offer

    async def list_offers(
        self,
        *,
        status: str | None = None,
        application_id: UUID | None = None,
        limit: int = 100,
        offset: int = 0,
    ) -> tuple[list[HrOffer], int]:
        stmt = select(HrOffer)
        count_stmt = select(func.count(HrOffer.id))
        if status:
            stmt = stmt.where(HrOffer.status == status)
            count_stmt = count_stmt.where(HrOffer.status == status)
        if application_id is not None:
            stmt = stmt.where(HrOffer.application_id == application_id)
            count_stmt = count_stmt.where(HrOffer.application_id == application_id)
        rows = list(
            await self.session.scalars(
                stmt.order_by(HrOffer.created_at.desc(), HrOffer.id.desc())
                .limit(limit)
                .offset(offset)
            )
        )
        total = int(await self.session.scalar(count_stmt) or 0)
        return rows, total

    async def get_offer(self, offer_id: UUID) -> HrOffer:
        offer = await self.session.get(HrOffer, offer_id)
        if offer is None:
            raise NotFoundException("Offer")
        return offer

    async def _offer_document_version(
        self, version_id: UUID, application: HrApplication, actor: User, *, attaching: bool = False
    ) -> tuple[HrDocument, HrDocumentVersion]:
        for permission in (PERMISSION_HR_DOCUMENTS_MANAGE, PERMISSION_HR_EMPLOYEES_SENSITIVE):
            if not has_permission(actor, permission):
                raise PermissionDeniedException(permission)
        statement = (
            select(HrDocument, HrDocumentVersion)
            .join(HrDocumentVersion, HrDocumentVersion.document_id == HrDocument.id)
            .where(
                HrDocumentVersion.id == version_id,
                HrDocumentVersion.mime_type == "application/pdf",
                HrDocument.candidate_id == application.candidate_id,
                HrDocument.document_type == "candidate_offer",
                HrDocument.category == "confidential",
                HrDocument.deleted_at.is_(None),
            )
        )
        if attaching:
            statement = statement.where(
                HrDocumentVersion.status == "active",
                HrDocument.current_version == HrDocumentVersion.version_number,
            ).with_for_update(of=HrDocument)
        else:
            statement = statement.where(HrDocumentVersion.status.in_(["active", "superseded"]))
        row = (await self.session.execute(statement)).one_or_none()
        if row is None:
            raise NotFoundException("Approved candidate offer file")
        return row[0], row[1]

    async def download_offer_document(
        self, offer_id: UUID, actor: User
    ) -> HrDocumentDownloadResponse:
        offer = await self.get_offer(offer_id)
        if offer.document_version_id is None:
            raise NotFoundException("Offer document")
        application = await self.get_application(offer.application_id)
        document, version = await self._offer_document_version(
            offer.document_version_id, application, actor
        )
        return await self._presign_document_version(
            document,
            actor,
            action="hr.offer.document_downloaded",
            include_category=True,
            version_number=version.version_number,
        )

    async def decide_offer(
        self, offer_id: UUID, payload: OfferDecisionRequest, actor: User
    ) -> HrOffer:
        application_id = await self.session.scalar(
            select(HrOffer.application_id).where(HrOffer.id == offer_id)
        )
        if application_id is None:
            raise NotFoundException("Offer")
        self._require_open_recruitment_application(
            await self.get_application(application_id, lock=True)
        )
        offer = await self.session.scalar(
            select(HrOffer)
            .where(HrOffer.id == offer_id)
            .with_for_update()
            .execution_options(populate_existing=True)
        )
        if offer is None:
            raise NotFoundException("Offer")
        if payload.status == "approved" and not has_permission(
            actor, PERMISSION_HR_EMPLOYEES_SENSITIVE
        ):
            raise PermissionDeniedException(PERMISSION_HR_EMPLOYEES_SENSITIVE)
        if (
            payload.expected_updated_at is not None
            and offer.updated_at != payload.expected_updated_at
        ):
            raise AppException(
                "Review the current offer before recording a decision.", status_code=409
            )
        if offer.status == "superseded" or offer.superseded_by_id is not None:
            raise AppException(
                "This offer version has been superseded by newer terms.",
                status_code=409,
                error_code="OFFER_SUPERSEDED",
            )
        if (
            payload.expected_version_number is not None
            and offer.version_number != payload.expected_version_number
        ):
            raise AppException(
                "Offer version does not match current terms.",
                status_code=409,
                error_code="OFFER_VERSION_CONFLICT",
            )
        transitions = {
            "draft": {"pending_approval", "withdrawn"},
            "pending_approval": {"approved", "withdrawn"},
            "approved": {"issued", "withdrawn"},
            "issued": {"accepted", "declined", "expired", "withdrawn"},
        }
        if payload.status not in transitions.get(offer.status, set()):
            raise AppException("This offer cannot make that transition.", status_code=409)
        today = business_today()
        if payload.valid_until is not None:
            if payload.status not in {"pending_approval", "approved", "issued"}:
                raise AppException(
                    "Offer validity can only be updated before or at issuance.",
                    status_code=409,
                )
            if payload.valid_until < today:
                raise AppException("Offer validity date must not be in the past.", status_code=422)
            offer.valid_until = payload.valid_until
        if (
            payload.status in {"approved", "issued"}
            and offer.valid_until is not None
            and offer.valid_until < today
        ):
            raise AppException("Offer validity date must not be in the past.", status_code=422)
        if (
            payload.status == "accepted"
            and offer.valid_until is not None
            and today > offer.valid_until
        ):
            raise AppException(
                "This offer has expired and cannot be accepted.",
                status_code=409,
                error_code="OFFER_EXPIRED",
            )
        if payload.status == "expired" and (
            offer.valid_until is None or today <= offer.valid_until
        ):
            raise AppException(
                "Offer has not passed its validity deadline.",
                status_code=409,
                error_code="OFFER_NOT_EXPIRED",
            )
        now = utc_now()
        offer.status = payload.status
        if payload.status == "approved":
            offer.approved_by_id = actor.id
            offer.approved_at = now
        elif payload.status == "issued":
            offer.issued_at = now
        elif payload.status in {"accepted", "declined", "expired"}:
            offer.responded_at = now
        if payload.notes:
            offer.notes = payload.notes
        await self.audit.record(
            action=f"hr.offer.{payload.status}",
            user_id=actor.id,
            entity_type="hr_offers",
            entity_id=offer.id,
        )
        await self._commit_and_refresh(offer)
        return offer

    async def convert_offer_to_employee(
        self, offer_id: UUID, payload: OfferConvertRequest, actor: User
    ) -> OnboardingCaseResponse:
        application_id = await self.session.scalar(
            select(HrOffer.application_id).where(HrOffer.id == offer_id)
        )
        if application_id is None:
            raise NotFoundException("Offer")
        # Match offer creation and reissue: lock the application before the offer.
        app_row = await self.get_application(application_id, lock=True)
        self._require_open_recruitment_application(app_row)
        offer = await self.session.scalar(
            select(HrOffer)
            .where(HrOffer.id == offer_id)
            .with_for_update()
            .execution_options(populate_existing=True)
        )
        if offer is None:
            raise NotFoundException("Offer")
        if offer.status == "superseded" or offer.superseded_by_id is not None:
            raise AppException(
                "This offer version has been superseded by newer terms.",
                status_code=409,
                error_code="OFFER_SUPERSEDED",
            )
        if offer.status == "converted":
            existing = await self.session.scalar(
                select(HrOnboardingCase).where(HrOnboardingCase.offer_id == offer.id)
            )
            if existing:
                return await self._serialize_onboarding_case(existing)
        if offer.status != "accepted":
            raise AppException(
                "Only accepted offers can be converted to an employee and onboarding case.",
                status_code=409,
                error_code="OFFER_NOT_ACCEPTED",
            )
        if app_row.stage == "hired":
            raise AppException(
                "This application already resulted in a hire.",
                status_code=409,
                error_code="APPLICATION_ALREADY_HIRED",
            )
        # Different applications can compete for the same vacancy.
        requisition = await self.session.scalar(
            select(HrRequisition)
            .where(HrRequisition.id == app_row.requisition_id, HrRequisition.deleted_at.is_(None))
            .with_for_update()
        )
        if requisition is None:
            raise NotFoundException("Requisition")
        hired = await self._hired_headcount(requisition.id)
        if hired >= requisition.headcount_requested:
            raise AppException(
                "The requisition has no remaining vacancies.",
                status_code=409,
                error_code="REQUISITION_CAPACITY_REACHED",
            )
        if requisition.status != "open":
            raise AppException(
                "Reopen the requisition before converting this offer."
                if requisition.status == "on_hold"
                else "The requisition must be open to convert an offer.",
                status_code=409,
                error_code="REQUISITION_NOT_OPEN",
            )
        cand = await self.session.scalar(
            select(HrCandidate).where(HrCandidate.id == app_row.candidate_id)
        )
        if cand is None:
            raise NotFoundException("Candidate")

        name_parts = [p for p in cand.full_name.strip().split() if p]
        first_name = name_parts[0] if name_parts else cand.full_name
        last_name = " ".join(name_parts[1:]) if len(name_parts) > 1 else ""
        join_date = payload.join_date or offer.proposed_join_date or utc_now().date()

        emp = HrEmployee(
            employee_code=payload.employee_code.strip(),
            first_name=first_name,
            last_name=last_name,
            full_name=cand.full_name.strip(),
            work_email=payload.work_email.lower() if payload.work_email else None,
            work_phone=payload.work_phone,
            employment_status="onboarding",
            employment_category="probation" if payload.probation_days > 0 else "permanent",
            join_date=join_date,
            department_id=offer.proposed_department_id,
            position_id=offer.proposed_position_id,
            record_revision=1,
            created_by_id=actor.id,
            updated_by_id=actor.id,
        )
        self.session.add(emp)
        try:
            await self.session.flush()
            self.session.add(
                HrEmploymentHistory(
                    employee_id=emp.id,
                    change_type="hired_from_offer",
                    effective_date=join_date,
                    previous_snapshot=None,
                    new_snapshot={
                        "employee_code": emp.employee_code,
                        "offer_code": offer.offer_code,
                        "employment_status": emp.employment_status,
                    },
                    reason=f"Converted from accepted offer {offer.offer_code}",
                    actor_user_id=actor.id,
                )
            )
            offer.status = "converted"
            offer.converted_employee_id = emp.id
            app_row.stage = "hired"
            cand.status = "hired"
            await self.audit.record(
                action="hr.application.hired",
                user_id=actor.id,
                entity_type="hr_applications",
                entity_id=app_row.id,
            )
            if hired + 1 == requisition.headcount_requested:
                requisition.status = "filled"
                await self.audit.record(
                    action="hr.requisition.filled",
                    user_id=actor.id,
                    entity_type="hr_requisitions",
                    entity_id=requisition.id,
                )

            probation_end = (
                join_date + timedelta(days=payload.probation_days)
                if payload.probation_days > 0
                else None
            )
            case = await self._create_onboarding_case_internal(
                employee_id=emp.id,
                offer_id=offer.id,
                start_date=join_date,
                probation_end_date=probation_end,
                owner_user_id=actor.id,
            )
            await self.audit.record(
                action="hr.offer.converted",
                user_id=actor.id,
                entity_type="hr_employees",
                entity_id=emp.id,
                new_values={"offer_id": str(offer.id), "onboarding_case_id": str(case.id)},
            )
            await self.session.commit()
            await self.session.refresh(case)
        except IntegrityError as exc:
            await self.session.rollback()
            raise AppException(
                "Employee code or work email already exists.",
                status_code=409,
                error_code="EMPLOYEE_CONFLICT",
            ) from exc
        return await self._serialize_onboarding_case(case)

    async def _hired_headcount(self, requisition_id: UUID) -> int:
        return int(
            await self.session.scalar(
                select(func.count(HrApplication.id)).where(
                    HrApplication.requisition_id == requisition_id,
                    HrApplication.stage == "hired",
                )
            )
            or 0
        )

    async def _create_onboarding_case_internal(
        self,
        *,
        employee_id: UUID,
        offer_id: UUID | None,
        start_date: date,
        probation_end_date: date | None,
        owner_user_id: UUID | None,
    ) -> HrOnboardingCase:
        case = HrOnboardingCase(
            employee_id=employee_id,
            offer_id=offer_id,
            status="open",
            start_date=start_date,
            probation_end_date=probation_end_date,
            owner_user_id=owner_user_id,
        )
        self.session.add(case)
        await self.session.flush()
        defaults = [
            ("ONB-HR-01", "Collect NIC/passport copies & signed employment contract", "hr"),
            ("ONB-IT-01", "Provision portal & email access (IT Admin workflow)", "it_admin"),
            ("ONB-MGR-01", "Assign manager & site orientation", "manager"),
            ("ONB-EMP-01", "Acknowledge company HR & safety policies", "employee"),
            ("ONB-OPS-01", "Issue safety PPE & site induction", "operations"),
        ]
        for code, title, role_area in defaults:
            self.session.add(
                HrOnboardingTask(
                    onboarding_case_id=case.id,
                    code=code,
                    title=title,
                    assignee_role=role_area,
                    is_mandatory=True,
                    due_date=None,
                )
            )
        await self.session.flush()
        return case

    async def create_onboarding_case(
        self, payload: OnboardingCaseCreateRequest, actor: User
    ) -> OnboardingCaseResponse:
        employee = await self._require_employee(payload.employee_id, for_update=True)
        if employee.employment_status not in {"draft", "onboarding"}:
            raise AppException("Only a draft employee can start onboarding.", status_code=409)
        if await self.session.scalar(
            select(HrOnboardingCase.id)
            .where(
                HrOnboardingCase.employee_id == employee.id,
                HrOnboardingCase.status.in_(["open", "in_progress"]),
            )
            .limit(1)
        ):
            raise AppException("An open onboarding case already exists.", status_code=409)
        if payload.probation_end_date and payload.probation_end_date < payload.start_date:
            raise AppException("Probation cannot end before the start date.", status_code=422)
        employee.employment_status = "onboarding"
        employee.record_revision += 1
        case = await self._create_onboarding_case_internal(
            employee_id=payload.employee_id,
            offer_id=None,
            start_date=payload.start_date,
            probation_end_date=payload.probation_end_date,
            owner_user_id=payload.owner_user_id or actor.id,
        )
        await self.audit.record(
            action="hr.onboarding.created",
            user_id=actor.id,
            entity_type="hr_onboarding_cases",
            entity_id=case.id,
        )
        await self._commit_and_refresh(case)
        return await self._serialize_onboarding_case(case)

    async def list_onboarding_cases(
        self,
        *,
        employee_id: UUID | None = None,
        status: str | None = None,
        limit: int | None = None,
        offset: int = 0,
    ) -> tuple[list[OnboardingCaseResponse], int]:
        stmt = select(HrOnboardingCase)
        count_stmt = select(func.count(HrOnboardingCase.id))
        if employee_id:
            stmt = stmt.where(HrOnboardingCase.employee_id == employee_id)
            count_stmt = count_stmt.where(HrOnboardingCase.employee_id == employee_id)
        if status is not None:
            stmt = stmt.where(HrOnboardingCase.status == status)
            count_stmt = count_stmt.where(HrOnboardingCase.status == status)
        cases = list(
            await self.session.scalars(
                stmt.order_by(HrOnboardingCase.created_at.desc(), HrOnboardingCase.id.desc())
                .limit(limit)
                .offset(offset)
            )
        )
        total = int(await self.session.scalar(count_stmt) or 0)
        return [await self._serialize_onboarding_case(c) for c in cases], total

    async def get_onboarding_case(self, case_id: UUID) -> OnboardingCaseResponse:
        case = await self.session.get(HrOnboardingCase, case_id)
        if case is None:
            raise NotFoundException("Onboarding case")
        return await self._serialize_onboarding_case(case)

    async def update_onboarding_task(
        self, task_id: UUID, payload: OnboardingTaskUpdateRequest, actor: User
    ) -> OnboardingCaseResponse:
        task = await self.session.scalar(
            select(HrOnboardingTask).where(HrOnboardingTask.id == task_id)
        )
        if task is None:
            raise NotFoundException("Onboarding task")
        case = await self.session.scalar(
            select(HrOnboardingCase)
            .where(HrOnboardingCase.id == task.onboarding_case_id)
            .with_for_update()
        )
        if case is None:
            raise NotFoundException("Onboarding case")
        if case.status == "completed":
            raise AppException("This onboarding case is already closed.", status_code=409)
        await self.session.refresh(task)
        if (
            payload.expected_updated_at is not None
            and task.updated_at != payload.expected_updated_at
        ):
            raise AppException(
                "Review the current checklist task before updating.", status_code=409
            )
        if payload.status in {"completed", "waived"}:
            employee = await self._require_employee(case.employee_id)
            if employee.user_id == actor.id:
                raise AppException(
                    "Employees cannot approve their own onboarding tasks.", status_code=403
                )
            if not (payload.evidence_notes or "").strip():
                raise AppException("Checklist evidence is required.", status_code=422)
        if payload.status == "waived" and not has_permission(
            actor, PERMISSION_HR_EMPLOYEES_SENSITIVE
        ):
            raise PermissionDeniedException(PERMISSION_HR_EMPLOYEES_SENSITIVE)
        task.status = payload.status
        task.evidence_notes = payload.evidence_notes
        if payload.status in {"completed", "waived"}:
            task.completed_by_id = actor.id
            task.completed_at = utc_now()
        else:
            task.completed_by_id = None
            task.completed_at = None
        all_tasks = list(
            await self.session.scalars(
                select(HrOnboardingTask).where(HrOnboardingTask.onboarding_case_id == case.id)
            )
        )
        if all(t.status in {"completed", "waived"} or not t.is_mandatory for t in all_tasks):
            if not has_permission(actor, PERMISSION_HR_EMPLOYEES_SENSITIVE):
                raise PermissionDeniedException(PERMISSION_HR_EMPLOYEES_SENSITIVE)
            case.status = "completed"
            case.completed_at = utc_now()
        else:
            case.status = "in_progress"
        await self.audit.record(
            action="hr.onboarding_task.updated",
            user_id=actor.id,
            entity_type="hr_onboarding_tasks",
            entity_id=task.id,
            new_values={"status": task.status},
        )
        await self._commit_and_refresh(task, case)
        return await self._serialize_onboarding_case(case)

    async def _serialize_onboarding_case(self, case: HrOnboardingCase) -> OnboardingCaseResponse:
        employee_state = None
        if case.probation_end_date:
            employee_state = (
                await self.session.execute(
                    select(
                        HrEmployee.employment_status,
                        HrEmployee.record_revision,
                        HrEmployee.employment_category,
                        HrEmployee.full_name,
                    ).where(HrEmployee.id == case.employee_id, HrEmployee.deleted_at.is_(None))
                )
            ).one_or_none()
        tasks = list(
            await self.session.scalars(
                select(HrOnboardingTask)
                .where(HrOnboardingTask.onboarding_case_id == case.id)
                .order_by(HrOnboardingTask.code.asc())
            )
        )
        return OnboardingCaseResponse(
            id=case.id,
            employee_id=case.employee_id,
            offer_id=case.offer_id,
            status=case.status,
            start_date=case.start_date,
            probation_end_date=case.probation_end_date,
            employee_name=employee_state[3] if employee_state else None,
            employee_status=employee_state[0] if employee_state else None,
            employee_revision=employee_state[1] if employee_state else None,
            employee_category=employee_state[2] if employee_state else None,
            owner_user_id=case.owner_user_id,
            completion_notes=case.completion_notes,
            completed_at=case.completed_at,
            tasks=[OnboardingTaskResponse.model_validate(t) for t in tasks],
            created_at=case.created_at,
            updated_at=case.updated_at,
        )

    # --- HR Document Vault & Compliance (HR-010, HR-011) ---

    def _client(self) -> Minio:
        return minio_client(self.settings)

    def _upload_object(self, object_key: str, data: bytes, mime_type: str) -> None:
        client = self._client()
        if not client.bucket_exists(self.settings.minio_bucket):
            client.make_bucket(self.settings.minio_bucket)
        client.put_object(
            self.settings.minio_bucket,
            object_key,
            BytesIO(data),
            length=len(data),
            content_type=mime_type,
        )

    def _allowed_doc_categories(self, actor: User) -> list[str]:
        categories = ["ordinary"]
        if has_permission(actor, PERMISSION_HR_EMPLOYEES_SENSITIVE):
            categories.extend(["confidential", "medical", "identity"])
        if has_permission(actor, PERMISSION_HR_PAYROLL_SENSITIVE):
            categories.append("compensation")
        if has_permission(actor, PERMISSION_HR_CASES_RESTRICTED):
            categories.append("disciplinary")
        return categories

    def _ensure_hr_doc_access(self, doc: HrDocument, actor: User) -> None:
        if doc.category not in self._allowed_doc_categories(actor):
            raise NotFoundException("HR Document")

    async def _get_hr_document(self, document_id: UUID, *, for_update: bool = False) -> HrDocument:
        stmt = select(HrDocument).where(
            HrDocument.id == document_id, HrDocument.deleted_at.is_(None)
        )
        doc = await self.session.scalar(stmt.with_for_update() if for_update else stmt)
        if doc is None:
            raise NotFoundException("HR Document")
        return doc

    async def upload_hr_document(
        self,
        *,
        title: str,
        document_type: str,
        category: str,
        employee_id: UUID | None,
        candidate_id: UUID | None,
        issue_date: date | None,
        expiry_date: date | None,
        issuing_authority: str | None,
        reference_number: str | None,
        is_employee_visible: bool,
        file: UploadFile,
        actor: User,
    ) -> HrDocumentResponse:
        if category not in self._allowed_doc_categories(actor):
            raise PermissionDeniedException(PERMISSION_HR_EMPLOYEES_SENSITIVE)
        if employee_id is not None and candidate_id is not None:
            raise AppException("Choose a single document owner.", status_code=422)
        if employee_id is not None:
            await self._require_employee(employee_id)
        is_cv = document_type.strip() == "candidate_cv"
        if document_type.strip() == "candidate_offer" and (
            candidate_id is None or category != "confidential"
        ):
            raise AppException(
                "An offer file requires a candidate and confidential access.", status_code=422
            )
        if document_type.strip() == "policy" and (
            category != "ordinary" or employee_id is not None or candidate_id is not None
        ):
            raise AppException(
                "Company policies must be ordinary and have no personal owner.", status_code=422
            )
        if is_cv and (candidate_id is None or category != "confidential"):
            raise AppException(
                "A candidate CV requires a candidate and confidential access.", status_code=422
            )
        candidate = None
        if candidate_id is not None:
            candidate_query = select(HrCandidate).where(
                HrCandidate.id == candidate_id, HrCandidate.deleted_at.is_(None)
            )
            candidate = await self.session.scalar(
                candidate_query.with_for_update() if is_cv else candidate_query
            )
            if candidate is None:
                raise NotFoundException("Candidate")
            if is_cv and candidate.resume_document_id:
                raise AppException("Upload a new version of the existing CV.", status_code=409)
        if is_employee_visible and (category != "ordinary" or employee_id is None):
            raise AppException("Only ordinary employee documents can be shared.", status_code=422)
        if issue_date and expiry_date and expiry_date < issue_date:
            raise AppException("Expiry cannot precede the issue date.", status_code=422)
        if not title.strip() or not document_type.strip():
            raise AppException("Title and document type are required.", status_code=422)

        doc = HrDocument(
            employee_id=employee_id,
            candidate_id=candidate_id,
            title=title.strip(),
            document_type=document_type.strip(),
            category=category,
            current_version=0,
            issue_date=issue_date,
            expiry_date=expiry_date,
            issuing_authority=issuing_authority,
            reference_number=reference_number,
            status="pending",
            is_employee_visible=is_employee_visible,
            created_by_id=actor.id,
        )
        self.session.add(doc)
        await self.session.flush()
        if is_cv and candidate is not None:
            candidate.resume_document_id = doc.id
        return await self._store_hr_document_version(doc, file, actor, version_number=1)

    async def upload_hr_document_version(
        self,
        document_id: UUID,
        file: UploadFile,
        actor: User,
        *,
        expected_latest_version: int | None = None,
    ) -> HrDocumentResponse:
        doc = await self._get_hr_document(document_id, for_update=True)
        self._ensure_hr_doc_access(doc, actor)
        latest = await self.session.scalar(
            select(HrDocumentVersion)
            .where(HrDocumentVersion.document_id == doc.id)
            .order_by(HrDocumentVersion.version_number.desc())
            .limit(1)
        )
        if expected_latest_version is not None and expected_latest_version != (
            latest.version_number if latest else 0
        ):
            raise AppException(
                "Review the newest document version before uploading.", status_code=409
            )
        if latest and latest.status == "pending":
            raise AppException("Decide the pending version first.", status_code=409)
        return await self._store_hr_document_version(
            doc, file, actor, version_number=(latest.version_number + 1 if latest else 1)
        )

    async def _store_hr_document_version(
        self, doc: HrDocument, file: UploadFile, actor: User, *, version_number: int
    ) -> HrDocumentResponse:
        data = await file.read(MAX_HR_DOCUMENT_SIZE + 1)
        filename = Path(file.filename or "hr-document.pdf").name[:255]
        mime_type, checksum = validate_hr_document_file(filename, data)
        if doc.document_type == "candidate_offer" and mime_type != "application/pdf":
            raise AppException("Offer files must be PDFs.", status_code=422)
        object_key = f"hr-documents/{doc.id}/v{version_number}/{uuid4().hex}"
        try:
            await asyncio.to_thread(self._upload_object, object_key, data, mime_type)
            ver = HrDocumentVersion(
                document_id=doc.id,
                version_number=version_number,
                status="pending",
                object_key=object_key,
                file_name=filename,
                mime_type=mime_type,
                file_size=len(data),
                sha256_checksum=checksum,
                uploaded_by_id=actor.id,
            )
            self.session.add(ver)
            await self.audit.record(
                action="hr.document.uploaded",
                user_id=actor.id,
                entity_type="hr_documents",
                entity_id=doc.id,
                new_values={"category": doc.category, "version": version_number},
            )
            await self.session.commit()
        except Exception:
            await self.session.rollback()
            await discard_new_uploads(self._client(), self.settings.minio_bucket, [object_key])
            raise
        return await self._serialize_hr_document(doc)

    async def decide_hr_document_version(
        self,
        document_id: UUID,
        version_number: int,
        payload: HrDocumentDecisionRequest,
        actor: User,
    ) -> HrDocumentResponse:
        doc = await self._get_hr_document(document_id, for_update=True)
        self._ensure_hr_doc_access(doc, actor)
        version = await self.session.scalar(
            select(HrDocumentVersion).where(
                HrDocumentVersion.document_id == doc.id,
                HrDocumentVersion.version_number == version_number,
            )
        )
        if version is None:
            raise NotFoundException("HR Document version")
        if version.status != "pending":
            raise AppException("This version is already decided.", status_code=409)
        if version.uploaded_by_id == actor.id:
            raise AppException(
                "A different HR Manager must review this version.",
                status_code=403,
                error_code="SELF_APPROVAL_BLOCKED",
            )
        if payload.decision == "approve":
            if doc.current_version:
                previous = await self.session.scalar(
                    select(HrDocumentVersion).where(
                        HrDocumentVersion.document_id == doc.id,
                        HrDocumentVersion.version_number == doc.current_version,
                    )
                )
                if previous:
                    previous.status = "superseded"
            version.status = "active"
            doc.current_version = version_number
            doc.status = "active"
        else:
            if not payload.notes or not payload.notes.strip():
                raise AppException("Rejection requires a reason.", status_code=422)
            version.status = "rejected"
            if not doc.current_version:
                doc.status = "rejected"
        version.notes = payload.notes
        await self.audit.record(
            action=f"hr.document.{payload.decision}",
            user_id=actor.id,
            entity_type="hr_documents",
            entity_id=doc.id,
            new_values={"version": version_number},
        )
        await self._commit_and_refresh(doc)
        return await self._serialize_hr_document(doc)

    async def list_hr_documents(
        self,
        *,
        actor: User,
        employee_id: UUID | None = None,
        candidate_id: UUID | None = None,
        category: str | None = None,
        document_type: str | None = None,
        limit: int = 100,
        offset: int = 0,
    ) -> tuple[list[HrDocumentResponse], int]:
        allowed_categories = self._allowed_doc_categories(actor)
        stmt = select(HrDocument).where(
            HrDocument.deleted_at.is_(None),
            HrDocument.category.in_(allowed_categories),
        )
        count_stmt = select(func.count(HrDocument.id)).where(
            HrDocument.deleted_at.is_(None),
            HrDocument.category.in_(allowed_categories),
        )
        if employee_id:
            stmt = stmt.where(HrDocument.employee_id == employee_id)
            count_stmt = count_stmt.where(HrDocument.employee_id == employee_id)
        if candidate_id:
            stmt = stmt.where(HrDocument.candidate_id == candidate_id)
            count_stmt = count_stmt.where(HrDocument.candidate_id == candidate_id)
        if category:
            stmt = stmt.where(HrDocument.category == category)
            count_stmt = count_stmt.where(HrDocument.category == category)
        if document_type:
            stmt = stmt.where(HrDocument.document_type == document_type)
            count_stmt = count_stmt.where(HrDocument.document_type == document_type)
        docs = list(
            await self.session.scalars(
                stmt.order_by(HrDocument.created_at.desc(), HrDocument.id.desc())
                .limit(limit)
                .offset(offset)
            )
        )
        total = int(await self.session.scalar(count_stmt) or 0)
        return [await self._serialize_hr_document(d) for d in docs], total

    async def get_hr_document_detail(self, document_id: UUID, actor: User) -> HrDocumentResponse:
        doc = await self._get_hr_document(document_id)
        self._ensure_hr_doc_access(doc, actor)
        return await self._serialize_hr_document(doc)

    async def get_hr_document_download_url(
        self, document_id: UUID, actor: User, *, version_number: int | None = None
    ) -> HrDocumentDownloadResponse:
        doc = await self.session.scalar(
            select(HrDocument).where(HrDocument.id == document_id, HrDocument.deleted_at.is_(None))
        )
        if doc is None:
            raise NotFoundException("HR Document")
        self._ensure_hr_doc_access(doc, actor)
        return await self._presign_document_version(
            doc,
            actor,
            action="hr.document.downloaded",
            include_category=True,
            version_number=version_number,
        )

    async def list_self_hr_documents(self, actor: User) -> tuple[list[HrDocumentResponse], int]:
        emp = await self._employee_for_user(actor)
        docs = list(
            await self.session.scalars(
                select(HrDocument)
                .where(
                    HrDocument.deleted_at.is_(None),
                    HrDocument.employee_id == emp.id,
                    HrDocument.is_employee_visible.is_(True),
                    HrDocument.category == "ordinary",
                    HrDocument.status == "active",
                )
                .order_by(HrDocument.created_at.desc())
            )
        )
        return [await self._serialize_hr_document(d, self_service=True) for d in docs], len(docs)

    async def get_self_hr_document_download_url(
        self, document_id: UUID, actor: User
    ) -> HrDocumentDownloadResponse:
        emp = await self._employee_for_user(actor)
        doc = await self.session.scalar(
            select(HrDocument).where(HrDocument.id == document_id, HrDocument.deleted_at.is_(None))
        )
        if (
            doc is None
            or doc.employee_id != emp.id
            or not doc.is_employee_visible
            or doc.status != "active"
        ):
            raise NotFoundException("HR Document")
        if doc.category != "ordinary":
            raise PermissionDeniedException(PERMISSION_HR_EMPLOYEES_SENSITIVE)
        return await self._presign_document_version(
            doc, actor, action="hr.self_document.downloaded", include_category=False
        )

    async def _presign_document_version(
        self,
        doc: HrDocument,
        actor: User,
        *,
        action: str,
        include_category: bool,
        version_number: int | None = None,
        allow_superseded: bool = False,
    ) -> HrDocumentDownloadResponse:
        visible_version: ColumnElement[bool] = HrDocumentVersion.status.in_(
            ["active", "superseded"] if include_category or allow_superseded else ["active"]
        )
        if (
            include_category
            and version_number is not None
            and (
                (
                    doc.document_type in {"candidate_cv", "candidate_offer"}
                    and doc.candidate_id is not None
                    and doc.category == "confidential"
                    and has_permission(actor, PERMISSION_HR_EMPLOYEES_SENSITIVE)
                )
                or (
                    doc.document_type == "reimbursement_receipt"
                    and doc.employee_id is not None
                    and doc.category == "compensation"
                    and has_permission(actor, PERMISSION_HR_PAYROLL_SENSITIVE)
                    and has_permission(actor, PERMISSION_HR_EMPLOYEES_SENSITIVE)
                )
            )
        ):
            visible_version = or_(
                visible_version,
                (HrDocumentVersion.status == "pending")
                & HrDocumentVersion.uploaded_by_id.is_distinct_from(actor.id),
            )
        ver = await self.session.scalar(
            select(HrDocumentVersion).where(
                HrDocumentVersion.document_id == doc.id,
                HrDocumentVersion.version_number == (version_number or doc.current_version),
                visible_version,
            )
        )
        if ver is None:
            raise NotFoundException("HR Document version")
        values: dict[str, Any] = {"version": ver.version_number}
        if include_category:
            values["category"] = doc.category
        await self.audit.record(
            action=action,
            user_id=actor.id,
            entity_type="hr_documents",
            entity_id=doc.id,
            new_values=values,
        )
        await self.session.commit()
        url = minio_signed_url_client(self.settings).presigned_get_object(
            self.settings.minio_bucket,
            ver.object_key,
            expires=timedelta(seconds=SIGNED_URL_SECONDS),
            response_headers={"response-content-disposition": "attachment"},
        )
        return HrDocumentDownloadResponse(
            document_id=doc.id,
            version_number=ver.version_number,
            file_name=ver.file_name,
            download_url=url,
            expires_in_seconds=SIGNED_URL_SECONDS,
        )

    async def _serialize_hr_document(
        self, doc: HrDocument, *, self_service: bool = False
    ) -> HrDocumentResponse:
        from app.schemas.hr import HrDocumentVersionResponse

        versions = list(
            await self.session.scalars(
                select(HrDocumentVersion)
                .where(HrDocumentVersion.document_id == doc.id)
                .order_by(HrDocumentVersion.version_number.desc())
            )
        )
        data = HrDocumentResponse.model_validate(doc)
        data.versions = [
            HrDocumentVersionResponse.model_validate(v)
            for v in versions
            if not self_service or v.status == "active"
        ]
        if self_service:
            data.reference_number = None
            data.created_by_id = None
            for version_data in data.versions:
                version_data.notes = None
                version_data.uploaded_by_id = None
        return data

    async def list_expiring_compliance(
        self, *, within_days: int = 30, actor: User
    ) -> ExpiringComplianceResponse:
        today = utc_now().date()
        cutoff = today + timedelta(days=within_days)
        items: list[ComplianceItemResponse] = []

        doc_stmt = select(HrDocument).where(
            HrDocument.deleted_at.is_(None),
            HrDocument.expiry_date.is_not(None),
            HrDocument.expiry_date <= cutoff,
            HrDocument.status == "active",
        )
        doc_stmt = doc_stmt.where(HrDocument.category.in_(self._allowed_doc_categories(actor)))
        for doc in await self.session.scalars(doc_stmt):
            if doc.expiry_date:
                items.append(
                    ComplianceItemResponse(
                        source_type="document",
                        record_id=doc.id,
                        employee_id=doc.employee_id,
                        title=doc.title,
                        expiry_date=doc.expiry_date,
                        days_remaining=(doc.expiry_date - today).days,
                        status="expired" if doc.expiry_date < today else "expiring_soon",
                    )
                )

        cert_stmt = select(HrCertification).where(
            HrCertification.expiry_date.is_not(None),
            HrCertification.expiry_date <= cutoff,
        )
        for cert in await self.session.scalars(cert_stmt):
            if cert.expiry_date:
                items.append(
                    ComplianceItemResponse(
                        source_type="certification",
                        record_id=cert.id,
                        employee_id=cert.employee_id,
                        title=cert.name,
                        expiry_date=cert.expiry_date,
                        days_remaining=(cert.expiry_date - today).days,
                        status="expired" if cert.expiry_date < today else "expiring_soon",
                    )
                )

        items.sort(key=lambda item: item.expiry_date)
        return ExpiringComplianceResponse(within_days=within_days, items=items, total=len(items))

    # --- Calendars, Shifts, Attendance, Corrections, Timesheets, Overtime (HR-012 to HR-014) ---

    async def create_work_calendar(
        self, payload: WorkCalendarCreateRequest, actor: User
    ) -> HrWorkCalendar:
        await self._validate_calendar_rules(payload)
        cal = HrWorkCalendar(**payload.model_dump(), created_by_id=actor.id)
        self.session.add(cal)
        return await self._save_work_calendar(cal, actor, "created")

    async def _validate_calendar_rules(self, payload: WorkCalendarCreateRequest) -> None:
        if (
            len(set(payload.work_days_json)) != len(payload.work_days_json)
            or payload.standard_start_time.utcoffset() is not None
            or payload.standard_end_time.utcoffset() is not None
            or payload.standard_end_time <= payload.standard_start_time
            or payload.effective_from > payload.effective_to
        ):
            raise AppException(
                "Specify unique workdays and valid daily and effective ranges.", status_code=422
            )
        if payload.project_id is not None and not await self.session.scalar(
            select(Project.id).where(Project.id == payload.project_id, Project.deleted_at.is_(None))
        ):
            raise NotFoundException("Project")
        if payload.project_id is not None and payload.is_default:
            raise AppException("A project calendar cannot be the company default.", status_code=422)

    async def _save_work_calendar(
        self, calendar: HrWorkCalendar, actor: User, action: str, *, reason: str | None = None
    ) -> HrWorkCalendar:
        try:
            await self.session.flush()
            await self.audit.record(
                action=f"hr.calendar.{action}",
                user_id=actor.id,
                entity_type="hr_work_calendars",
                entity_id=calendar.id,
                new_values={
                    "revision": calendar.revision,
                    "status": calendar.status,
                    "reason": reason,
                },
            )
            await self._commit_and_refresh(calendar)
        except IntegrityError as exc:
            await self.session.rollback()
            raise AppException(
                "Calendar code already exists.", status_code=409, error_code="CALENDAR_EXISTS"
            ) from exc
        return calendar

    async def update_work_calendar(
        self, calendar_id: UUID, payload: WorkCalendarUpdateRequest, actor: User
    ) -> HrWorkCalendar:
        calendar = await self._require_work_calendar(calendar_id, for_update=True)
        self._check_calendar_revision(calendar, payload.expected_revision)
        if calendar.status != "draft":
            raise AppException("Only a draft calendar can be edited.", status_code=409)
        await self._validate_calendar_rules(payload)
        existing_holiday_outside_window = await self.session.scalar(
            select(HrHoliday.id)
            .where(
                HrHoliday.calendar_id == calendar_id,
                or_(
                    HrHoliday.holiday_date < payload.effective_from,
                    HrHoliday.holiday_date > payload.effective_to,
                ),
            )
            .limit(1)
        )
        if existing_holiday_outside_window:
            raise AppException("The new window excludes an existing holiday.", status_code=409)
        for field, value in payload.model_dump(exclude={"expected_revision"}).items():
            setattr(calendar, field, value)
        if calendar.created_by_id is None:
            calendar.created_by_id = actor.id
        calendar.revision += 1
        return await self._save_work_calendar(calendar, actor, "updated")

    @staticmethod
    def _check_calendar_revision(calendar: HrWorkCalendar, expected: int) -> None:
        if calendar.revision != expected:
            raise AppException(
                "The work calendar changed. Reload it and try again.", status_code=409
            )

    async def decide_work_calendar(
        self, calendar_id: UUID, payload: WorkCalendarDecisionRequest, actor: User
    ) -> HrWorkCalendar:
        if payload.action != "submit" and not has_permission(actor, PERMISSION_HR_POLICY_MANAGE):
            raise PermissionDeniedException("Only an HR Manager may review or publish calendars.")
        calendar = await self._require_work_calendar(calendar_id, for_update=True)
        self._check_calendar_revision(calendar, payload.expected_revision)
        start, end = calendar.effective_from, calendar.effective_to
        if payload.action == "submit" and calendar.status == "draft":
            if start is None or end is None or not calendar.timezone:
                raise AppException(
                    "Set effective dates and timezone before submitting.", status_code=422
                )
            calendar.status = "submitted"
            calendar.submitted_by_id = actor.id
        elif payload.action == "approve" and calendar.status == "submitted":
            if actor.id in {calendar.created_by_id, calendar.submitted_by_id}:
                raise PermissionDeniedException("Another HR Manager must approve this calendar.")
            calendar.status = "approved"
            calendar.approved_by_id = actor.id
        elif payload.action == "return_to_draft" and calendar.status in {"submitted", "approved"}:
            if not payload.reason or len(payload.reason.strip()) < 2:
                raise AppException(
                    "Enter a reason for returning this calendar to draft.", status_code=422
                )
            calendar.status = "draft"
            calendar.submitted_by_id = None
            calendar.approved_by_id = None
        elif payload.action == "publish" and calendar.status == "approved":
            if start is None or end is None:
                raise AppException(
                    "Set the calendar effective dates before publishing.", status_code=422
                )
            # A company scope and each project scope publish independently. Hold the lock
            # through commit so parallel reviewers cannot publish overlapping windows.
            await self.session.execute(
                text("select pg_advisory_xact_lock(hashtextextended(:lock_key, 0))"),
                {"lock_key": f"garrison.hr.calendar:{calendar.project_id or 'company'}"},
            )
            conflict = await self.session.scalar(
                select(HrWorkCalendar.id)
                .where(
                    HrWorkCalendar.status == "published",
                    HrWorkCalendar.deleted_at.is_(None),
                    HrWorkCalendar.project_id.is_not_distinct_from(calendar.project_id),
                    HrWorkCalendar.effective_from <= end,
                    HrWorkCalendar.effective_to >= start,
                )
                .limit(1)
            )
            if conflict is not None:
                raise AppException(
                    "A published calendar already covers this window and scope.", status_code=409
                )
            calendar.status = "published"
            calendar.published_at = utc_now()
        else:
            raise AppException(
                "This action is unavailable for the calendar status.", status_code=409
            )
        calendar.revision += 1
        return await self._save_work_calendar(
            calendar, actor, payload.action, reason=payload.reason
        )

    async def list_work_calendars(self) -> tuple[list[HrWorkCalendar], int]:
        rows = list(
            await self.session.scalars(
                select(HrWorkCalendar)
                .where(HrWorkCalendar.deleted_at.is_(None))
                .order_by(HrWorkCalendar.code.asc())
            )
        )
        return rows, len(rows)

    async def _require_work_calendar(
        self, calendar_id: UUID, *, for_update: bool = False
    ) -> HrWorkCalendar:
        stmt = select(HrWorkCalendar).where(
            HrWorkCalendar.id == calendar_id, HrWorkCalendar.deleted_at.is_(None)
        )
        if for_update:
            stmt = stmt.with_for_update()
        calendar = await self.session.scalar(stmt)
        if calendar is None:
            raise NotFoundException("Work calendar")
        return calendar

    async def create_holiday(self, payload: HolidayCreateRequest, actor: User) -> HrHoliday:
        calendar = await self._require_work_calendar(payload.calendar_id, for_update=True)
        if (
            calendar.status != "draft"
            or calendar.effective_from is None
            or calendar.effective_to is None
        ):
            raise AppException(
                "Holidays require an editable draft with effective dates.", status_code=409
            )
        if not calendar.effective_from <= payload.holiday_date <= calendar.effective_to:
            raise AppException(
                "The holiday falls outside the calendar's effective window.", status_code=422
            )
        calendar.revision += 1
        holiday = HrHoliday(**payload.model_dump())
        self.session.add(holiday)
        try:
            await self.session.flush()
            await self.audit.record(
                action="hr.holiday.created",
                user_id=actor.id,
                entity_type="hr_holidays",
                entity_id=holiday.id,
            )
            await self.session.commit()
        except IntegrityError as exc:
            await self.session.rollback()
            raise AppException(
                "Holiday already exists on that calendar date.",
                status_code=409,
                error_code="HOLIDAY_EXISTS",
            ) from exc
        return holiday

    async def list_holidays(
        self, *, calendar_id: UUID | None = None
    ) -> tuple[list[HrHoliday], int]:
        stmt = select(HrHoliday)
        if calendar_id:
            stmt = stmt.where(HrHoliday.calendar_id == calendar_id)
        rows = list(await self.session.scalars(stmt.order_by(HrHoliday.holiday_date.asc())))
        return rows, len(rows)

    async def create_shift_assignment(
        self, payload: ShiftAssignmentCreateRequest, actor: User
    ) -> HrShiftAssignment:
        employee = await self._require_employee(payload.employee_id, for_update=True)
        calendar = await self._require_work_calendar(payload.calendar_id)
        calendar_start, calendar_end = calendar.effective_from, calendar.effective_to
        if calendar.status != "published" or calendar_start is None or calendar_end is None:
            raise AppException("Shifts require a published calendar.", status_code=409)
        start = payload.effective_from
        end = payload.effective_to or calendar_end
        if end < start:
            raise AppException("Shift end date must follow its start.", status_code=422)
        if start < calendar_start or end > calendar_end:
            raise AppException(
                "The shift falls outside the calendar's effective window.", status_code=422
            )
        project_id = payload.project_id or calendar.project_id or employee.primary_project_id
        if calendar.project_id is not None and calendar.project_id != project_id:
            raise AppException("The shift must use the calendar's project scope.", status_code=422)
        if (
            payload.start_time.utcoffset() is not None
            or payload.end_time.utcoffset() is not None
            or payload.start_time == payload.end_time
        ):
            raise AppException(
                "Enter different local start and end times for the shift.", status_code=422
            )
        overlap = (
            select(HrShiftAssignment.id)
            .join(HrWorkCalendar, HrWorkCalendar.id == HrShiftAssignment.calendar_id)
            .where(
                HrShiftAssignment.employee_id == payload.employee_id,
                HrWorkCalendar.status == "published",
                or_(
                    HrShiftAssignment.effective_to.is_(None),
                    HrShiftAssignment.effective_to >= start,
                ),
                HrShiftAssignment.effective_from <= end,
            )
        )
        if await self.session.scalar(overlap.limit(1)):
            raise AppException("This employee has an overlapping shift.", status_code=409)
        shift = HrShiftAssignment(
            **payload.model_dump(exclude={"project_id", "effective_to"}),
            project_id=project_id,
            effective_to=end,
            assigned_by_id=actor.id,
        )
        self.session.add(shift)
        await self.session.flush()
        await self.audit.record(
            action="hr.shift.assigned",
            user_id=actor.id,
            entity_type="hr_shift_assignments",
            entity_id=shift.id,
        )
        await self.session.commit()
        return shift

    async def get_work_schedule(self, employee_id: UUID, work_date: date) -> WorkScheduleResponse:
        employee = await self._require_employee(employee_id)
        return await self._resolve_work_schedule(employee, work_date)

    async def list_roster_allocations(
        self,
        *,
        date_from: date,
        date_to: date,
        project_id: UUID | None,
        employee_id: UUID | None,
        limit: int,
        offset: int,
    ) -> tuple[list[HrRosterAllocation], int]:
        if not 0 <= (date_to - date_from).days < 31:
            raise AppException("Choose an ordered date range of at most 31 days.", status_code=422)
        filters: list[ColumnElement[bool]] = [
            HrRosterAllocation.work_date.between(date_from, date_to)
        ]
        if project_id is not None:
            filters.append(HrRosterAllocation.project_id == project_id)
        if employee_id is not None:
            filters.append(HrRosterAllocation.employee_id == employee_id)
        total = await self.session.scalar(
            select(func.count()).select_from(HrRosterAllocation).where(*filters)
        )
        rows = await self.session.scalars(
            select(HrRosterAllocation)
            .where(*filters)
            .order_by(HrRosterAllocation.work_date, HrRosterAllocation.id)
            .limit(limit)
            .offset(offset)
        )
        return list(rows), total or 0

    async def get_roster_allocation(self, allocation_id: UUID) -> HrRosterAllocation:
        row = await self.session.get(HrRosterAllocation, allocation_id)
        if row is None:
            raise NotFoundException("Roster allocation")
        return row

    @staticmethod
    def _roster_instant(day: date, local_time: time, zone: ZoneInfo) -> datetime:
        local = datetime.combine(day, local_time.replace(tzinfo=None))
        earlier = local.replace(tzinfo=zone, fold=0)
        later = local.replace(tzinfo=zone, fold=1)
        if earlier.utcoffset() != later.utcoffset():
            raise AppException(
                "A shift endpoint is an ambiguous or missing local time.",
                status_code=409,
            )
        return earlier.astimezone(UTC)

    async def create_roster_allocation(
        self, payload: RosterAllocationCreateRequest, actor: User
    ) -> HrRosterAllocation:
        employee = await self._require_employee(payload.employee_id, for_update=True)
        existing = await self.session.get(HrRosterAllocation, payload.id)
        if existing is not None:
            if (existing.employee_id, existing.project_id, existing.work_date) == (
                payload.employee_id,
                payload.project_id,
                payload.work_date,
            ):
                return existing
            raise AppException("That allocation ID has already been used.", status_code=409)
        if (
            employee.employment_status not in {"active", "on_probation", "notice_period"}
            or (employee.join_date is not None and payload.work_date < employee.join_date)
            or (
                employee.termination_date is not None
                and payload.work_date >= employee.termination_date
            )
        ):
            raise AppException(
                "The employee is not eligible for this roster date.", status_code=409
            )
        project = await self.session.scalar(
            select(Project).where(Project.id == payload.project_id, Project.deleted_at.is_(None))
        )
        if project is None:
            raise NotFoundException("Project")
        if project.status in {"completed", "cancelled"}:
            raise AppException("The project no longer accepts allocations.", status_code=409)
        schedule = await self._resolve_work_schedule(employee, payload.work_date)
        calendar, shift = schedule.calendar, schedule.shift
        if calendar is None or calendar.timezone is None or schedule.is_workday is not True:
            raise AppException("This roster date requires a published workday.", status_code=409)
        local_start = shift.start_time if shift else calendar.standard_start_time
        local_end = shift.end_time if shift else calendar.standard_end_time
        end_day = payload.work_date
        if local_end < local_start:
            if end_day == date.max:
                raise AppException(
                    "The overnight schedule exceeds the supported date range.", status_code=422
                )
            end_day += timedelta(days=1)
        zone = ZoneInfo(calendar.timezone)
        starts_at = self._roster_instant(payload.work_date, local_start, zone)
        ends_at = self._roster_instant(end_day, local_end, zone)
        span = ends_at - starts_at
        planned_hours = (
            (Decimal(span.days * 86400 + span.seconds) + Decimal(span.microseconds) / 1000000)
            / 3600
            if shift
            else calendar.daily_hours
        ).quantize(Decimal("0.01"))
        if ends_at <= starts_at or planned_hours <= 0:
            raise AppException("The published schedule has no allocatable hours.", status_code=409)
        overlap = await self.session.scalar(
            select(HrRosterAllocation.id)
            .where(
                HrRosterAllocation.employee_id == employee.id,
                HrRosterAllocation.cancelled_at.is_(None),
                or_(
                    HrRosterAllocation.work_date == payload.work_date,
                    (HrRosterAllocation.starts_at < ends_at)
                    & (HrRosterAllocation.ends_at > starts_at),
                ),
            )
            .limit(1)
        )
        if overlap is not None:
            raise AppException(
                "This employee already has an overlapping allocation.", status_code=409
            )
        row = HrRosterAllocation(
            **payload.model_dump(),
            calendar_id=calendar.id,
            shift_id=shift.id if shift else None,
            employee_name=employee.full_name,
            project_name=project.name,
            timezone=calendar.timezone,
            starts_at=starts_at,
            ends_at=ends_at,
            planned_hours=planned_hours,
            created_by_id=actor.id,
        )
        self.session.add(row)
        try:
            await self.session.flush()
        except IntegrityError as error:
            if getattr(error.orig, "sqlstate", None) == "23505":
                raise AppException(
                    "That allocation ID has already been used.", status_code=409
                ) from error
            raise
        await self.audit.record(
            action="hr.roster.allocated",
            user_id=actor.id,
            entity_type=HrRosterAllocation.__tablename__,
            entity_id=row.id,
        )
        await self._commit_and_refresh(row)
        return row

    async def cancel_roster_allocation(
        self, allocation_id: UUID, reason: str, actor: User
    ) -> HrRosterAllocation:
        employee_id = await self.session.scalar(
            select(HrRosterAllocation.employee_id).where(HrRosterAllocation.id == allocation_id)
        )
        if employee_id is None:
            raise NotFoundException("Roster allocation")
        await self.session.scalar(
            select(HrEmployee.id).where(HrEmployee.id == employee_id).with_for_update()
        )
        row = await self.session.get(HrRosterAllocation, allocation_id, populate_existing=True)
        if row is None:
            raise NotFoundException("Roster allocation")
        if row.cancelled_at is not None:
            if row.cancellation_reason != reason:
                raise AppException("This allocation has already been cancelled.", status_code=409)
            return row
        row.cancelled_at = utc_now()
        row.cancelled_by_id = actor.id
        row.cancellation_reason = reason
        await self.audit.record(
            action="hr.roster.cancelled",
            user_id=actor.id,
            entity_type=HrRosterAllocation.__tablename__,
            entity_id=row.id,
        )
        await self._commit_and_refresh(row)
        return row

    async def _resolve_work_schedule(
        self, employee: HrEmployee, work_date: date
    ) -> WorkScheduleResponse:
        applicable = (
            HrWorkCalendar.status == "published",
            HrWorkCalendar.deleted_at.is_(None),
            HrWorkCalendar.effective_from <= work_date,
            HrWorkCalendar.effective_to >= work_date,
        )
        assigned = (
            await self.session.execute(
                select(HrShiftAssignment, HrWorkCalendar)
                .join(HrWorkCalendar, HrWorkCalendar.id == HrShiftAssignment.calendar_id)
                .where(
                    *applicable,
                    HrShiftAssignment.employee_id == employee.id,
                    HrShiftAssignment.effective_from <= work_date,
                    HrShiftAssignment.effective_to >= work_date,
                )
            )
        ).one_or_none()
        calendar: HrWorkCalendar | None
        if assigned is not None:
            shift, calendar = assigned
        else:
            shift = None
            scope, priority = self._work_calendar_scope(employee)
            calendar = await self.session.scalar(
                select(HrWorkCalendar)
                .where(*applicable, scope)
                .order_by(priority, HrWorkCalendar.id)
                .limit(1)
            )
        if calendar is None:
            return WorkScheduleResponse(work_date=work_date)
        holiday = await self.session.scalar(
            select(HrHoliday).where(
                HrHoliday.calendar_id == calendar.id, HrHoliday.holiday_date == work_date
            )
        )
        return WorkScheduleResponse(
            work_date=work_date,
            calendar=WorkCalendarResponse.model_validate(calendar),
            shift=ShiftAssignmentResponse.model_validate(shift) if shift is not None else None,
            holiday=HolidayResponse.model_validate(holiday) if holiday is not None else None,
            is_workday=holiday is None and WORKDAYS[work_date.weekday()] in calendar.work_days_json,
        )

    @staticmethod
    def _work_calendar_scope(
        employee: HrEmployee,
    ) -> tuple[ColumnElement[bool], ColumnElement[int]]:
        employee_calendar = (HrWorkCalendar.id == employee.work_calendar_id) & (
            HrWorkCalendar.project_id.is_(None)
            | (HrWorkCalendar.project_id == employee.primary_project_id)
        )
        company_default = HrWorkCalendar.project_id.is_(None) & HrWorkCalendar.is_default.is_(True)
        project_calendar = (
            HrWorkCalendar.project_id == employee.primary_project_id
            if employee.primary_project_id is not None
            else false()
        )
        return (
            or_(employee_calendar, project_calendar, company_default),
            case((employee_calendar, 0), (project_calendar, 1), else_=2),
        )

    async def list_shift_assignments(
        self, *, employee_id: UUID | None = None
    ) -> tuple[list[HrShiftAssignment], int]:
        stmt = select(HrShiftAssignment)
        if employee_id:
            stmt = stmt.where(HrShiftAssignment.employee_id == employee_id)
        rows = list(
            await self.session.scalars(stmt.order_by(HrShiftAssignment.effective_from.desc()))
        )
        return rows, len(rows)

    @staticmethod
    def _validate_local_work_date(
        check_in: datetime | None, work_date: date, timezone: str | None
    ) -> None:
        if check_in and timezone and check_in.astimezone(ZoneInfo(timezone)).date() != work_date:
            raise AppException(
                "Check-in must start on the work date in the calendar timezone.", status_code=422
            )

    @staticmethod
    def _attendance_schedule_values(
        schedule: WorkScheduleResponse,
    ) -> dict[str, UUID | bool | None]:
        return {
            "calendar_id": schedule.calendar.id if schedule.calendar else None,
            "shift_assignment_id": schedule.shift.id if schedule.shift else None,
            "scheduled_workday": schedule.is_workday,
        }

    @staticmethod
    def _validate_attendance_time(
        check_in: datetime | None, check_out: datetime | None, hours: Decimal, status: str
    ) -> None:
        if (check_in is None) != (check_out is None):
            raise AppException("Enter both clock times or neither.", status_code=422)
        if (
            check_in
            and check_out
            and (
                check_in.utcoffset() is None
                or check_out.utcoffset() is None
                or check_out <= check_in
            )
        ):
            raise AppException("Clock times require offsets and must be in order.", status_code=422)
        if status in {"absent", "on_leave", "holiday"} and (hours or check_in):
            raise AppException("Nonworking attendance cannot record worked hours.", status_code=422)
        if check_in is not None and check_out is not None:
            elapsed = check_out - check_in
            if elapsed > timedelta(days=1) or elapsed < timedelta(seconds=int(hours * 3600)):
                raise AppException(
                    "Worked hours must fit within the clock interval of up to 24 hours.",
                    status_code=422,
                )

    async def _ensure_attendance_period_open(self, employee_id: UUID, work_date: date) -> None:
        if await self.session.scalar(
            select(HrTimesheet.id)
            .where(
                HrTimesheet.employee_id == employee_id,
                HrTimesheet.status == "locked",
                HrTimesheet.period_start <= work_date,
                HrTimesheet.period_end >= work_date,
            )
            .limit(1)
        ):
            raise AppException("Attendance belongs to a locked timesheet period.", status_code=409)

    async def record_attendance(
        self, payload: AttendanceEntryCreateRequest, actor: User
    ) -> HrAttendanceEntry:
        employee = await self._require_employee(payload.employee_id, for_update=True)
        entry = await self.prepare_attendance(payload, actor, employee)
        await self.persist_attendance([entry], actor)
        return entry

    async def prepare_attendance(
        self, payload: AttendanceEntryCreateRequest, actor: User, employee: HrEmployee
    ) -> HrAttendanceEntry:
        await self._ensure_attendance_period_open(payload.employee_id, payload.work_date)
        self._validate_attendance_time(
            payload.check_in_at,
            payload.check_out_at,
            payload.worked_hours,
            payload.attendance_status,
        )
        existing = await self.session.scalar(
            select(HrAttendanceEntry).where(
                HrAttendanceEntry.employee_id == payload.employee_id,
                HrAttendanceEntry.work_date == payload.work_date,
            )
        )
        if existing is not None:
            raise AppException(
                "Attendance entry already exists for this employee and work date; "
                "submit an attendance correction instead.",
                status_code=409,
                error_code="ATTENDANCE_ALREADY_EXISTS",
            )
        schedule = await self._resolve_work_schedule(employee, payload.work_date)
        if schedule.holiday and payload.attendance_status == "absent":
            raise AppException(
                "A published holiday must not be recorded as absence.", status_code=422
            )
        self._validate_local_work_date(
            payload.check_in_at,
            payload.work_date,
            schedule.calendar.timezone if schedule.calendar else None,
        )
        entry = HrAttendanceEntry(
            **payload.model_dump(),
            **self._attendance_schedule_values(schedule),
            recorded_by_id=actor.id,
        )
        await start_manager_review(self.session, entry, employee)
        return entry

    async def persist_attendance(self, entries: list[HrAttendanceEntry], actor: User) -> None:
        self.session.add_all(entries)
        await self.session.flush()
        for entry in entries:
            await self.audit.record(
                action="hr.attendance.recorded",
                user_id=actor.id,
                entity_type="hr_attendance_entries",
                entity_id=entry.id,
                new_values={"source": entry.source},
            )
        await self.session.commit()

    async def get_attendance_entry(self, record_id: UUID) -> HrAttendanceEntry:
        row = await self.session.get(HrAttendanceEntry, record_id)
        if row is None:
            raise NotFoundException("Attendance entry")
        return row

    async def decide_attendance(
        self, entry_id: UUID, payload: AttendanceReviewRequest, actor: User
    ) -> HrAttendanceEntry:
        employee_id = await self.session.scalar(
            select(HrAttendanceEntry.employee_id).where(HrAttendanceEntry.id == entry_id)
        )
        if employee_id is None:
            raise NotFoundException("Attendance entry")
        employee = await self._require_employee(employee_id, for_update=True)
        entry = await self.session.scalar(
            select(HrAttendanceEntry).where(HrAttendanceEntry.id == entry_id).with_for_update()
        )
        if entry is None:
            raise NotFoundException("Attendance entry")
        await self._ensure_attendance_period_open(employee_id, entry.work_date)
        verify_request_revision(entry, payload.expected_revision)
        if entry.status != "submitted":
            raise AppException("This attendance entry is already decided.", status_code=409)
        if actor.id in {entry.recorded_by_id, employee.user_id}:
            raise PermissionDeniedException("decide attendance you recorded or your own attendance")
        await require_manager_recommendation(
            self.session, entry, employee, actor, payload.expected_revision
        )
        note = (payload.note or "").strip()
        if payload.decision == "returned" and not note:
            raise AppException("Enter a reason for returning attendance.", status_code=422)
        entry.status = payload.decision
        entry.review_note = note or None
        if payload.decision == "approved":
            entry.approved_by_id, entry.approved_at = actor.id, utc_now()
        entry.record_revision += 1
        await self.audit.record(
            action=f"hr.attendance.{payload.decision}",
            user_id=actor.id,
            entity_type="hr_attendance_entries",
            entity_id=entry.id,
        )
        await self._commit_and_refresh(entry)
        return entry

    async def list_attendance(
        self,
        *,
        employee_id: UUID | None = None,
        date_from: date | None = None,
        date_to: date | None = None,
    ) -> tuple[list[HrAttendanceEntry], int]:
        stmt = select(HrAttendanceEntry)
        if employee_id:
            stmt = stmt.where(HrAttendanceEntry.employee_id == employee_id)
        if date_from:
            stmt = stmt.where(HrAttendanceEntry.work_date >= date_from)
        if date_to:
            stmt = stmt.where(HrAttendanceEntry.work_date <= date_to)
        rows = list(await self.session.scalars(stmt.order_by(HrAttendanceEntry.work_date.desc())))
        return rows, len(rows)

    async def create_attendance_correction(
        self, payload: AttendanceCorrectionCreateRequest, actor: User
    ) -> HrAttendanceCorrection:
        employee = await self._require_employee(payload.employee_id, for_update=True)
        await self._ensure_attendance_period_open(payload.employee_id, payload.work_date)
        self._validate_attendance_time(
            payload.requested_check_in_at,
            payload.requested_check_out_at,
            payload.requested_worked_hours,
            payload.requested_status,
        )
        entry = await self.session.scalar(
            select(HrAttendanceEntry).where(
                HrAttendanceEntry.employee_id == payload.employee_id,
                HrAttendanceEntry.work_date == payload.work_date,
            )
        )
        if payload.attendance_entry_id and (
            entry is None or entry.id != payload.attendance_entry_id
        ):
            raise NotFoundException("Attendance entry")
        if entry is None:
            schedule = await self._resolve_work_schedule(employee, payload.work_date)
            timezone = schedule.calendar.timezone if schedule.calendar else None
        else:
            timezone = (
                await self.session.scalar(
                    select(HrWorkCalendar.timezone).where(HrWorkCalendar.id == entry.calendar_id)
                )
                if entry.calendar_id
                else None
            )
        self._validate_local_work_date(payload.requested_check_in_at, payload.work_date, timezone)
        if await self.session.scalar(
            select(HrAttendanceCorrection.id)
            .where(
                HrAttendanceCorrection.employee_id == payload.employee_id,
                HrAttendanceCorrection.work_date == payload.work_date,
                HrAttendanceCorrection.status == "submitted",
            )
            .limit(1)
        ):
            raise AppException(
                "There is already a pending correction for this day.", status_code=409
            )
        corr = HrAttendanceCorrection(
            **payload.model_dump(exclude={"attendance_entry_id"}),
            attendance_entry_id=entry.id if entry is not None else None,
            entry_revision=entry.record_revision if entry is not None else None,
            status="submitted",
            requested_by_id=actor.id,
        )
        self.session.add(corr)
        await self.session.flush()
        await self.audit.record(
            action="hr.attendance_correction.submitted",
            user_id=actor.id,
            entity_type="hr_attendance_corrections",
            entity_id=corr.id,
        )
        await self._commit_and_refresh(corr)
        return corr

    async def get_attendance_correction(self, record_id: UUID) -> HrAttendanceCorrection:
        row = await self.session.get(HrAttendanceCorrection, record_id)
        if row is None:
            raise NotFoundException("Attendance correction")
        return row

    async def decide_attendance_correction(
        self, correction_id: UUID, payload: AttendanceCorrectionDecisionRequest, actor: User
    ) -> HrAttendanceCorrection:
        corr = await self.session.scalar(
            select(HrAttendanceCorrection)
            .where(HrAttendanceCorrection.id == correction_id)
            .with_for_update()
        )
        if corr is None:
            raise NotFoundException("Attendance correction")
        employee = await self._require_employee(corr.employee_id, for_update=True)
        if corr.status != "submitted":
            raise AppException("This correction is already decided.", status_code=409)
        if payload.decision == "approved" and actor.id in {corr.requested_by_id, employee.user_id}:
            raise AppException(
                "An independent HR Manager must approve this correction.", status_code=403
            )
        await self._ensure_attendance_period_open(corr.employee_id, corr.work_date)
        before = None
        corr.status = payload.decision
        corr.decided_by_id = actor.id
        corr.decided_at = utc_now()
        corr.decision_notes = payload.notes
        if payload.decision == "approved":
            entry = await self.session.scalar(
                select(HrAttendanceEntry).where(
                    HrAttendanceEntry.employee_id == corr.employee_id,
                    HrAttendanceEntry.work_date == corr.work_date,
                )
            )
            if (entry.id if entry else None) != corr.attendance_entry_id or (
                entry.record_revision if entry else None
            ) != corr.entry_revision:
                raise AppException(
                    "Attendance changed after this correction was submitted. "
                    "Return it and request a new correction.",
                    status_code=409,
                    error_code="REVISION_CONFLICT",
                )
            if entry is None:
                schedule = await self._resolve_work_schedule(employee, corr.work_date)
                self._validate_local_work_date(
                    corr.requested_check_in_at,
                    corr.work_date,
                    schedule.calendar.timezone if schedule.calendar else None,
                )
                entry = HrAttendanceEntry(
                    employee_id=corr.employee_id,
                    work_date=corr.work_date,
                    attendance_status=corr.requested_status,
                    check_in_at=corr.requested_check_in_at,
                    check_out_at=corr.requested_check_out_at,
                    worked_hours=corr.requested_worked_hours,
                    source="correction",
                    notes=None,
                    recorded_by_id=corr.requested_by_id,
                    approved_by_id=actor.id,
                    approved_at=utc_now(),
                    status="approved",
                    **self._attendance_schedule_values(schedule),
                )
                self.session.add(entry)
            else:
                if entry.calendar_id:
                    timezone = await self.session.scalar(
                        select(HrWorkCalendar.timezone).where(
                            HrWorkCalendar.id == entry.calendar_id
                        )
                    )
                    self._validate_local_work_date(
                        corr.requested_check_in_at, corr.work_date, timezone
                    )
                before = {
                    "status": entry.attendance_status,
                    "worked_hours": str(entry.worked_hours),
                    "check_in_at": entry.check_in_at.isoformat() if entry.check_in_at else None,
                    "check_out_at": entry.check_out_at.isoformat() if entry.check_out_at else None,
                }
                entry.attendance_status = corr.requested_status
                entry.check_in_at = corr.requested_check_in_at
                entry.check_out_at = corr.requested_check_out_at
                entry.worked_hours = corr.requested_worked_hours
                entry.source = "correction"
                entry.approved_by_id = actor.id
                entry.approved_at = utc_now()
                entry.status = "approved"
                entry.record_revision += 1
                entry.review_note = None
            await self.session.flush()
            corr.attendance_entry_id = entry.id
        await self.audit.record(
            action=f"hr.attendance_correction.{payload.decision}",
            user_id=actor.id,
            entity_type="hr_attendance_corrections",
            entity_id=corr.id,
            old_values=before,
        )
        await self._commit_and_refresh(corr)
        return corr

    async def list_attendance_corrections(
        self, *, employee_id: UUID | None = None
    ) -> tuple[list[HrAttendanceCorrection], int]:
        stmt = select(HrAttendanceCorrection)
        if employee_id:
            stmt = stmt.where(HrAttendanceCorrection.employee_id == employee_id)
        rows = list(
            await self.session.scalars(stmt.order_by(HrAttendanceCorrection.created_at.desc()))
        )
        return rows, len(rows)

    @staticmethod
    def _validate_timesheet_hours(start: date, end: date, hours: Decimal) -> None:
        days = (end - start).days + 1
        if days <= 0 or hours > days * 24:
            raise AppException("Invalid timesheet dates or total hours.", status_code=422)

    async def create_timesheet(
        self, payload: TimesheetCreateRequest, actor: User, *, own_request: bool = False
    ) -> HrTimesheet:
        employee = await self._require_employee(payload.employee_id, for_update=True)
        if own_request:
            self._verify_self_request(employee, actor)
        self._validate_timesheet_hours(
            payload.period_start, payload.period_end, payload.regular_hours + payload.overtime_hours
        )
        if await self.session.scalar(
            select(HrTimesheet.id)
            .where(
                HrTimesheet.employee_id == payload.employee_id,
                HrTimesheet.period_start <= payload.period_end,
                HrTimesheet.period_end >= payload.period_start,
            )
            .limit(1)
        ):
            raise AppException("Timesheet periods cannot overlap.", status_code=409)
        ts = HrTimesheet(
            employee_id=payload.employee_id,
            project_id=employee.primary_project_id if own_request else payload.project_id,
            period_start=payload.period_start,
            period_end=payload.period_end,
            regular_hours=payload.regular_hours,
            overtime_hours=payload.overtime_hours,
            status="submitted" if payload.submit else "draft",
            submitted_at=utc_now() if payload.submit else None,
            submitted_by_id=actor.id if payload.submit else None,
            notes=payload.notes,
        )
        if payload.submit:
            await start_manager_review(self.session, ts, employee)
        self.session.add(ts)
        try:
            await self.session.flush()
            await self.audit.record(
                action="hr.timesheet.created",
                user_id=actor.id,
                entity_type="hr_timesheets",
                entity_id=ts.id,
            )
            await self.session.commit()
        except IntegrityError as exc:
            await self.session.rollback()
            raise AppException(
                "Timesheet already exists for this period.",
                status_code=409,
                error_code="TIMESHEET_EXISTS",
            ) from exc
        return ts

    async def resubmit_own_timesheet(
        self, timesheet_id: UUID, payload: TimesheetSelfResubmitRequest, actor: User
    ) -> HrTimesheet:
        employee = await self._employee_for_user(actor)
        ts = await self.session.scalar(
            select(HrTimesheet)
            .where(HrTimesheet.id == timesheet_id, HrTimesheet.employee_id == employee.id)
            .with_for_update()
        )
        if ts is None:
            raise NotFoundException("Timesheet")
        employee = await self._require_employee(ts.employee_id, for_update=True)
        if (
            employee.user_id != actor.id
            or employee.employment_status not in REVIEW_EMPLOYMENT_STATES
        ):
            raise NotFoundException("Timesheet")
        verify_request_revision(ts, payload.expected_revision)
        if ts.status not in {"draft", "rejected"}:
            raise AppException(
                "Only a draft or rejected timesheet may be resubmitted.", status_code=409
            )
        self._validate_timesheet_hours(
            ts.period_start, ts.period_end, payload.regular_hours + payload.overtime_hours
        )
        ts.regular_hours = payload.regular_hours
        ts.overtime_hours = payload.overtime_hours
        ts.notes = payload.notes
        ts.status = "submitted"
        ts.submitted_by_id = actor.id
        ts.submitted_at = utc_now()
        ts.rejection_reason = None
        ts.record_revision += 1
        await start_manager_review(self.session, ts, employee)
        await self.audit.record(
            action="hr.timesheet.resubmitted",
            user_id=actor.id,
            entity_type="hr_timesheets",
            entity_id=ts.id,
        )
        await self._commit_and_refresh(ts)
        return ts

    async def get_timesheet(self, record_id: UUID) -> HrTimesheet:
        row = await self.session.get(HrTimesheet, record_id)
        if row is None:
            raise NotFoundException("Timesheet")
        return row

    async def decide_timesheet(
        self, timesheet_id: UUID, payload: TimesheetDecisionRequest, actor: User
    ) -> HrTimesheet:
        ts = await self.session.scalar(
            select(HrTimesheet).where(HrTimesheet.id == timesheet_id).with_for_update()
        )
        if ts is None:
            raise NotFoundException("Timesheet")
        employee = await self._require_employee(ts.employee_id, for_update=True)
        verify_request_revision(ts, payload.expected_revision)
        sources = {
            "submitted": {"draft", "rejected"},
            "approved": {"submitted"},
            "rejected": {"submitted"},
            "locked": {"approved"},
        }
        if ts.status not in sources[payload.decision]:
            raise AppException("This timesheet cannot make that transition.", status_code=409)
        if payload.decision in {"approved", "rejected", "locked"} and employee.user_id == actor.id:
            raise AppException("Employees cannot decide their own timesheets.", status_code=403)
        if payload.decision in {"approved", "rejected"}:
            if ts.submitted_by_id == actor.id:
                raise AppException(
                    "A different HR Manager must decide a submitted timesheet.", status_code=403
                )
            await require_manager_recommendation(
                self.session, ts, employee, actor, payload.expected_revision
            )
        if payload.decision == "rejected" and not (payload.notes or "").strip():
            raise AppException("Rejection requires a reason.", status_code=422)
        if payload.decision == "locked":
            outstanding = await self.session.scalar(
                select(HrAttendanceEntry.id)
                .where(
                    HrAttendanceEntry.employee_id == employee.id,
                    HrAttendanceEntry.work_date.between(ts.period_start, ts.period_end),
                    HrAttendanceEntry.status.not_in(("approved", "historical")),
                )
                .limit(1)
            )
            correction = await self.session.scalar(
                select(HrAttendanceCorrection.id)
                .where(
                    HrAttendanceCorrection.employee_id == employee.id,
                    HrAttendanceCorrection.work_date.between(ts.period_start, ts.period_end),
                    HrAttendanceCorrection.status == "submitted",
                )
                .limit(1)
            )
            pending_overtime = await self.session.scalar(
                select(HrOvertimeRequest.id)
                .where(
                    HrOvertimeRequest.employee_id == employee.id,
                    HrOvertimeRequest.work_date.between(ts.period_start, ts.period_end),
                    HrOvertimeRequest.status == "submitted",
                )
                .limit(1)
            )
            if outstanding or correction or pending_overtime:
                raise AppException(
                    "Review attendance, pending corrections and overtime before locking.",
                    status_code=409,
                )
        ts.status = payload.decision
        if payload.decision == "submitted":
            ts.submitted_at = utc_now()
            ts.submitted_by_id = actor.id
            ts.rejection_reason = None
            await start_manager_review(self.session, ts, employee)
        elif payload.decision == "approved":
            ts.approved_by_id = actor.id
            ts.approved_at = utc_now()
        elif payload.decision == "rejected":
            ts.rejection_reason = payload.notes
        ts.record_revision += 1
        await self.audit.record(
            action=f"hr.timesheet.{payload.decision}",
            user_id=actor.id,
            entity_type="hr_timesheets",
            entity_id=ts.id,
        )
        await self._commit_and_refresh(ts)
        return ts

    async def list_timesheets(
        self, *, employee_id: UUID | None = None
    ) -> tuple[list[HrTimesheet], int]:
        stmt = select(HrTimesheet)
        if employee_id:
            stmt = stmt.where(HrTimesheet.employee_id == employee_id)
        rows = list(await self.session.scalars(stmt.order_by(HrTimesheet.period_start.desc())))
        return rows, len(rows)

    async def create_overtime_request(
        self, payload: OvertimeRequestCreateRequest, actor: User, *, own_request: bool = False
    ) -> HrOvertimeRequest:
        employee = await self._require_employee(payload.employee_id, for_update=True)
        if own_request:
            self._verify_self_request(employee, actor)
        await self._ensure_attendance_period_open(payload.employee_id, payload.work_date)
        if await self.session.scalar(
            select(HrOvertimeRequest.id)
            .where(
                HrOvertimeRequest.employee_id == payload.employee_id,
                HrOvertimeRequest.work_date == payload.work_date,
                HrOvertimeRequest.status.in_(["submitted", "approved"]),
            )
            .limit(1)
        ):
            raise AppException("An overtime request already covers this day.", status_code=409)
        ot = HrOvertimeRequest(
            **payload.model_dump(exclude={"project_id"}),
            project_id=employee.primary_project_id if own_request else payload.project_id,
            status="submitted",
            requested_by_id=actor.id,
        )
        await start_manager_review(self.session, ot, employee)
        self.session.add(ot)
        await self.session.flush()
        await self.audit.record(
            action="hr.overtime.submitted",
            user_id=actor.id,
            entity_type="hr_overtime_requests",
            entity_id=ot.id,
        )
        await self._commit_and_refresh(ot)
        return ot

    async def get_overtime_request(self, record_id: UUID) -> HrOvertimeRequest:
        row = await self.session.get(HrOvertimeRequest, record_id)
        if row is None:
            raise NotFoundException("Overtime request")
        return row

    async def decide_overtime_request(
        self, ot_id: UUID, payload: OvertimeDecisionRequest, actor: User
    ) -> HrOvertimeRequest:
        ot = await self.session.scalar(
            select(HrOvertimeRequest).where(HrOvertimeRequest.id == ot_id).with_for_update()
        )
        if ot is None:
            raise NotFoundException("Overtime request")
        employee = await self._require_employee(ot.employee_id, for_update=True)
        verify_request_revision(ot, payload.expected_revision)
        await self._ensure_attendance_period_open(ot.employee_id, ot.work_date)
        if ot.status != "submitted":
            raise AppException("This overtime request is already decided.", status_code=409)
        if payload.decision in {"approved", "rejected"} and actor.id in {
            employee.user_id,
            ot.requested_by_id,
        }:
            raise AppException(
                "An independent HR Manager must decide this request.", status_code=403
            )
        if payload.decision in {"approved", "rejected"}:
            await require_manager_recommendation(
                self.session, ot, employee, actor, payload.expected_revision
            )
        if payload.approved_hours is not None and (
            payload.decision != "approved" or payload.approved_hours > ot.requested_hours
        ):
            raise AppException("Approved hours cannot exceed requested overtime.", status_code=422)
        ot.status = payload.decision
        ot.approved_hours = (
            (payload.approved_hours if payload.approved_hours is not None else ot.requested_hours)
            if payload.decision == "approved"
            else None
        )
        ot.decided_by_id = actor.id
        ot.decided_at = utc_now()
        ot.decision_notes = payload.notes
        ot.record_revision += 1
        await self.audit.record(
            action=f"hr.overtime.{payload.decision}",
            user_id=actor.id,
            entity_type="hr_overtime_requests",
            entity_id=ot.id,
        )
        await self._commit_and_refresh(ot)
        return ot

    async def list_overtime_requests(
        self, *, employee_id: UUID | None = None
    ) -> tuple[list[HrOvertimeRequest], int]:
        stmt = select(HrOvertimeRequest)
        if employee_id:
            stmt = stmt.where(HrOvertimeRequest.employee_id == employee_id)
        rows = list(await self.session.scalars(stmt.order_by(HrOvertimeRequest.work_date.desc())))
        return rows, len(rows)

    # --- Leave Management (HR-015) ---

    async def create_leave_type(self, payload: LeaveTypeCreateRequest, actor: User) -> HrLeaveType:
        lt = HrLeaveType(**payload.model_dump())
        self.session.add(lt)
        try:
            await self.session.flush()
            await self.audit.record(
                action="hr.leave_type.created",
                user_id=actor.id,
                entity_type="hr_leave_types",
                entity_id=lt.id,
            )
            await self.session.commit()
        except IntegrityError as exc:
            await self.session.rollback()
            raise AppException(
                "Leave type code already exists.", status_code=409, error_code="LEAVE_TYPE_EXISTS"
            ) from exc
        return lt

    async def list_leave_types(self) -> tuple[list[HrLeaveType], int]:
        rows = list(await self.session.scalars(select(HrLeaveType).order_by(HrLeaveType.code)))
        return rows, len(rows)

    async def create_leave_policy(
        self, payload: LeavePolicyCreateRequest, actor: User
    ) -> HrLeavePolicy:
        if payload.approve_immediately:
            raise AppException(
                "A different HR Manager must review the policy.",
                status_code=422,
                error_code="LEAVE_POLICY_REVIEW_REQUIRED",
            )
        if payload.effective_from > payload.effective_to:
            raise AppException("Enter effective dates in order.", status_code=422)
        await self._active_leave_type(payload.leave_type_id)
        data = payload.model_dump(exclude={"approve_immediately"})
        pol = HrLeavePolicy(
            **data,
            created_by_id=actor.id,
            status="draft",
            is_active=False,
        )
        self.session.add(pol)
        try:
            await self.session.flush()
            await self.audit.record(
                action="hr.leave_policy.created",
                user_id=actor.id,
                entity_type="hr_leave_policies",
                entity_id=pol.id,
            )
            await self.session.commit()
        except IntegrityError as exc:
            await self.session.rollback()
            raise AppException(
                "Leave policy code already exists.",
                status_code=409,
                error_code="LEAVE_POLICY_EXISTS",
            ) from exc
        return pol

    async def get_leave_policy(self, policy_id: UUID) -> HrLeavePolicy:
        policy = await self.session.get(HrLeavePolicy, policy_id)
        if policy is None:
            raise NotFoundException("Leave policy")
        return policy

    async def decide_leave_policy(
        self, policy_id: UUID, payload: LeavePolicyDecisionRequest, actor: User
    ) -> HrLeavePolicy:
        leave_type_id = await self.session.scalar(
            select(HrLeavePolicy.leave_type_id).where(HrLeavePolicy.id == policy_id)
        )
        if leave_type_id is None:
            raise NotFoundException("Leave policy")
        # Serialize decisions for all policy windows of this leave type.
        leave_type = await self.session.scalar(
            select(HrLeaveType).where(HrLeaveType.id == leave_type_id).with_for_update()
        )
        if leave_type is None:
            raise NotFoundException("Leave type")
        policy = await self.get_leave_policy(policy_id)
        if policy.status != "draft":
            raise AppException("Only a draft leave policy can be reviewed.", status_code=409)
        if policy.created_by_id is None or policy.created_by_id == actor.id:
            raise PermissionDeniedException("review a leave policy without an independent preparer")
        if payload.decision == "approved":
            if not leave_type.is_active:
                raise AppException("This leave type is inactive.", status_code=409)
            start, end = policy.effective_from, policy.effective_to
            if start is None or end is None:
                raise AppException("The draft has no effective window.", status_code=409)
            overlap = await self.session.scalar(
                select(HrLeavePolicy.id)
                .where(
                    HrLeavePolicy.leave_type_id == leave_type_id,
                    HrLeavePolicy.employment_category.is_not_distinct_from(
                        policy.employment_category
                    ),
                    HrLeavePolicy.status == "approved",
                    HrLeavePolicy.effective_from <= end,
                    HrLeavePolicy.effective_to >= start,
                )
                .limit(1)
            )
            if overlap is not None:
                raise AppException(
                    "An approved leave policy overlaps these dates for this employment category.",
                    status_code=409,
                    error_code="LEAVE_POLICY_OVERLAP",
                )
            policy.approved_by_id = actor.id
            policy.approved_at = utc_now()
            policy.is_active = True
        else:
            reason = (payload.reason or "").strip()
            if not reason:
                raise AppException("Enter a reason for rejecting the policy.", status_code=422)
            policy.rejection_reason = reason
        policy.status = payload.decision
        await self.audit.record(
            action=f"hr.leave_policy.{payload.decision}",
            user_id=actor.id,
            entity_type="hr_leave_policies",
            entity_id=policy.id,
        )
        await self._commit_and_refresh(policy)
        return policy

    async def _leave_allows_negative_balance(
        self, request: HrLeaveRequest, category: str | None
    ) -> bool:
        policies = list(
            await self.session.scalars(
                select(HrLeavePolicy)
                .where(
                    HrLeavePolicy.leave_type_id == request.leave_type_id,
                    HrLeavePolicy.is_active.is_(True),
                    HrLeavePolicy.approved_at.is_not(None),
                    or_(
                        HrLeavePolicy.employment_category == category,
                        HrLeavePolicy.employment_category.is_(None),
                    ),
                    or_(
                        HrLeavePolicy.status == "legacy",
                        (HrLeavePolicy.status == "approved")
                        & (HrLeavePolicy.effective_from <= request.end_date)
                        & (HrLeavePolicy.effective_to >= request.start_date),
                    ),
                )
                .order_by(
                    HrLeavePolicy.employment_category.is_(None),
                    HrLeavePolicy.status == "legacy",
                    HrLeavePolicy.approved_at.desc(),
                    HrLeavePolicy.id,
                )
            )
        )
        for offset in range((request.end_date - request.start_date).days + 1):
            day = request.start_date + timedelta(days=offset)
            policy = next(
                (
                    row
                    for row in policies
                    if row.status == "legacy"
                    or (
                        row.effective_from is not None
                        and row.effective_to is not None
                        and row.effective_from <= day <= row.effective_to
                    )
                ),
                None,
            )
            if policy is None or not policy.allow_negative_balance:
                return False
        return bool(policies)

    async def list_leave_policies(self) -> tuple[list[HrLeavePolicy], int]:
        rows = list(await self.session.scalars(select(HrLeavePolicy).order_by(HrLeavePolicy.code)))
        return rows, len(rows)

    async def _leave_balance(self, employee_id: UUID, leave_type_id: UUID, year: int) -> Decimal:
        return Decimal(
            await self.session.scalar(
                select(func.coalesce(func.sum(HrLeaveLedger.days_delta), 0)).where(
                    HrLeaveLedger.employee_id == employee_id,
                    HrLeaveLedger.leave_type_id == leave_type_id,
                    HrLeaveLedger.leave_year == year,
                )
            )
            or 0
        )

    async def adjust_leave_ledger(
        self, payload: LeaveLedgerAdjustRequest, actor: User
    ) -> HrLeaveLedger:
        await self._require_employee(payload.employee_id, for_update=True)
        await ensure_leave_year_open(
            self.session, payload.employee_id, payload.leave_type_id, payload.leave_year
        )
        leave_type = await self.session.get(HrLeaveType, payload.leave_type_id)
        if not leave_type or not leave_type.is_active:
            raise NotFoundException("Leave type")
        if payload.days_delta == 0 or (
            payload.entry_type in {"opening_balance", "accrual", "carry_forward"}
            and payload.days_delta < 0
        ):
            raise AppException("The adjustment amount is invalid.", status_code=422)
        if payload.entry_type in {"opening_balance", "carry_forward"} and await self.session.scalar(
            select(HrLeaveRollover.id).where(
                HrLeaveRollover.employee_id == payload.employee_id,
                HrLeaveRollover.leave_type_id == payload.leave_type_id,
                HrLeaveRollover.source_year == payload.leave_year - 1,
            )
        ):
            raise AppException(
                "A reviewed rollover already accounted for carry-forward into this year.",
                status_code=409,
                error_code="LEAVE_ROLLOVER_ALREADY_POSTED",
            )
        if payload.entry_type in {"opening_balance", "accrual"} and await self.session.scalar(
            select(HrLeaveAccrual.id)
            .where(
                HrLeaveAccrual.employee_id == payload.employee_id,
                HrLeaveAccrual.leave_type_id == payload.leave_type_id,
                HrLeaveAccrual.period_start.between(
                    date(payload.leave_year, 1, 1), date(payload.leave_year, 12, 31)
                ),
            )
            .limit(1)
        ):
            raise AppException(
                "Policy accrual has already posted for this year. Record a reconciled adjustment.",
                status_code=409,
                error_code="LEAVE_ACCRUAL_ALREADY_STARTED",
            )
        if payload.entry_type == "opening_balance" and await self.session.scalar(
            select(HrLeaveLedger.id)
            .where(
                HrLeaveLedger.employee_id == payload.employee_id,
                HrLeaveLedger.leave_type_id == payload.leave_type_id,
                HrLeaveLedger.leave_year == payload.leave_year,
                HrLeaveLedger.entry_type == "opening_balance",
            )
            .limit(1)
        ):
            raise AppException("An opening balance already exists for this year.", status_code=409)
        balance = await self._leave_balance(
            payload.employee_id, payload.leave_type_id, payload.leave_year
        )
        if leave_type.is_paid and balance + payload.days_delta < 0:
            raise AppException("This adjustment would create a negative balance.", status_code=409)
        entry = HrLeaveLedger(
            employee_id=payload.employee_id,
            leave_type_id=payload.leave_type_id,
            entry_type=payload.entry_type,
            days_delta=payload.days_delta,
            leave_year=payload.leave_year,
            reason=payload.reason,
            actor_user_id=actor.id,
        )
        self.session.add(entry)
        await self.session.flush()
        await self.audit.record(
            action="hr.leave_ledger.adjusted",
            user_id=actor.id,
            entity_type="hr_leave_ledger",
            entity_id=entry.id,
            new_values={"days_delta": str(payload.days_delta), "year": payload.leave_year},
        )
        await self.session.commit()
        return entry

    async def get_leave_balances(
        self, employee_id: UUID, *, leave_year: int | None = None
    ) -> LeaveBalanceListResponse:
        await self._require_employee(employee_id)
        yr = leave_year or utc_now().year
        leave_types = {
            lt.id: lt
            for lt in await self.session.scalars(
                select(HrLeaveType).where(HrLeaveType.is_active.is_(True))
            )
        }
        rows = await self.session.execute(
            select(
                HrLeaveLedger.leave_type_id,
                func.coalesce(func.sum(HrLeaveLedger.days_delta), 0),
            )
            .where(HrLeaveLedger.employee_id == employee_id, HrLeaveLedger.leave_year == yr)
            .group_by(HrLeaveLedger.leave_type_id)
        )
        balances = {row[0]: Decimal(row[1]) for row in rows}
        items = [
            LeaveBalanceItem(
                leave_type_id=lt.id,
                leave_type_code=lt.code,
                leave_type_name=lt.name,
                leave_year=yr,
                balance_days=balances.get(lt.id, Decimal("0.00")),
            )
            for lt in leave_types.values()
        ]
        return LeaveBalanceListResponse(employee_id=employee_id, items=items)

    @staticmethod
    def _verify_self_request(employee: HrEmployee, actor: User) -> None:
        if (
            employee.user_id != actor.id
            or employee.employment_status not in REVIEW_EMPLOYMENT_STATES
        ):
            raise NotFoundException("Employee profile")

    async def quote_employee_leave_units(
        self, employee_id: UUID, payload: LeaveUnitsQuery
    ) -> Decimal:
        return await self.get_leave_units(await self._require_employee(employee_id), payload)

    async def _active_leave_type(self, leave_type_id: UUID) -> HrLeaveType:
        lt = await self.session.get(HrLeaveType, leave_type_id)
        if lt is None or not lt.is_active:
            raise NotFoundException("Leave type")
        return lt

    async def get_leave_units(self, employee: HrEmployee, payload: LeaveUnitsQuery) -> Decimal:
        units, _ = await self._calculate_leave_schedule(
            employee, payload, await self._active_leave_type(payload.leave_type_id)
        )
        return units

    async def _calculate_leave_schedule(
        self, employee: HrEmployee, payload: LeaveUnitsQuery, lt: HrLeaveType
    ) -> tuple[Decimal, list[date]]:
        calendar_days = (payload.end_date - payload.start_date).days + 1
        if calendar_days <= 0 or payload.start_date.year != payload.end_date.year:
            raise AppException(
                "Enter dates in order and split requests across calendar years.",
                status_code=422,
            )
        if payload.is_half_day and (calendar_days != 1 or not payload.half_day_period):
            raise AppException("Specify one date and a period for half-day leave.", status_code=422)
        if not payload.is_half_day and payload.half_day_period is not None:
            raise AppException("A half-day period requires half-day leave.", status_code=422)
        if payload.is_half_day and not lt.allow_half_day:
            raise AppException("This leave type does not allow half days.", status_code=422)
        workdays = await self._leave_work_dates(employee, payload.start_date, calendar_days)
        if not workdays:
            raise AppException(
                "The requested dates have no scheduled workdays.",
                status_code=422,
                error_code="NO_LEAVE_WORKDAYS",
            )
        units = Decimal("0.50") if payload.is_half_day else Decimal(len(workdays))
        return units, workdays

    async def _leave_work_dates(
        self, employee: HrEmployee, start: date, calendar_days: int
    ) -> list[date]:
        # One query for at most one calendar year. Resolve each date independently
        # so revisions and shift assignments can change within a request.
        offsets = func.generate_series(0, calendar_days - 1).table_valued("n").render_derived()
        work_date = type_coerce(literal(start) + offsets.c.n, Date())
        applicable = (
            HrWorkCalendar.status == "published",
            HrWorkCalendar.deleted_at.is_(None),
            HrWorkCalendar.effective_from <= work_date,
            HrWorkCalendar.effective_to >= work_date,
        )
        scope, priority = self._work_calendar_scope(employee)
        shift_calendar = (
            select(HrShiftAssignment.calendar_id)
            .join(HrWorkCalendar, HrWorkCalendar.id == HrShiftAssignment.calendar_id)
            .where(
                *applicable,
                HrShiftAssignment.employee_id == employee.id,
                HrShiftAssignment.effective_from <= work_date,
                HrShiftAssignment.effective_to >= work_date,
            )
            .order_by(HrShiftAssignment.id)
            .limit(1)
            .correlate(offsets)
            .scalar_subquery()
        )
        fallback_calendar = (
            select(HrWorkCalendar.id)
            .where(*applicable, scope)
            .order_by(priority, HrWorkCalendar.id)
            .limit(1)
            .correlate(offsets)
            .scalar_subquery()
        )
        schedule = (
            select(
                work_date.label("work_date"),
                func.coalesce(shift_calendar, fallback_calendar).label("calendar_id"),
            )
            .select_from(offsets)
            .cte("leave_schedule")
        )
        rows = await self.session.execute(
            select(schedule.c.work_date, HrWorkCalendar.work_days_json, HrHoliday.id)
            .select_from(schedule)
            .outerjoin(HrWorkCalendar, HrWorkCalendar.id == schedule.c.calendar_id)
            .outerjoin(
                HrHoliday,
                (HrHoliday.calendar_id == schedule.c.calendar_id)
                & (HrHoliday.holiday_date == schedule.c.work_date),
            )
            .order_by(schedule.c.work_date)
        )
        workdays = []
        for day, work_days, holiday_id in rows:
            if work_days is None:
                raise AppException(
                    f"No published work calendar covers {day.isoformat()}. Contact HR.",
                    status_code=409,
                    error_code="LEAVE_SCHEDULE_MISSING",
                )
            if holiday_id is None and WORKDAYS[day.weekday()] in work_days:
                workdays.append(day)
        return workdays

    async def _validate_leave_request(
        self, payload: LeaveRequestFields, target_emp: HrEmployee, actor: User
    ) -> tuple[Decimal, list[date]]:
        await ensure_leave_year_open(
            self.session, target_emp.id, payload.leave_type_id, payload.start_date.year
        )
        lt = await self._active_leave_type(payload.leave_type_id)
        units, workdays = await self._calculate_leave_schedule(target_emp, payload, lt)
        if payload.days_requested is not None and payload.days_requested != units:
            raise AppException(
                f"The published schedule counts {units} leave days. Check the dates and try again.",
                status_code=409,
                error_code="LEAVE_UNITS_MISMATCH",
            )
        if lt.requires_attachment and payload.attachment_document_id is None:
            raise AppException(
                "A supporting document is required.",
                status_code=422,
                error_code="ATTACHMENT_REQUIRED",
            )
        if payload.attachment_document_id is not None:
            doc = await self._get_hr_document(payload.attachment_document_id)
            if doc.employee_id != target_emp.id or doc.status != "active":
                raise NotFoundException("HR Document")
            if target_emp.user_id == actor.id:
                if not (doc.is_employee_visible and doc.category == "ordinary"):
                    raise NotFoundException("HR Document")
            else:
                self._ensure_hr_doc_access(doc, actor)
        return units, workdays

    async def create_leave_request(
        self, payload: LeaveRequestCreateRequest, actor: User, *, own_request: bool = False
    ) -> HrLeaveRequest:
        employee_id = payload.employee_id or (await self._employee_for_user(actor)).id
        target_emp = await self._require_employee(employee_id, for_update=True)
        if own_request:
            self._verify_self_request(target_emp, actor)
        units, workdays = await self._validate_leave_request(payload, target_emp, actor)
        if payload.submit_immediately:
            await self._ensure_no_leave_overlap(target_emp.id, payload.start_date, payload.end_date)
        req = HrLeaveRequest(
            employee_id=target_emp.id,
            leave_type_id=payload.leave_type_id,
            start_date=payload.start_date,
            end_date=payload.end_date,
            days_requested=units,
            scheduled_work_dates=workdays if payload.submit_immediately else None,
            is_half_day=payload.is_half_day,
            half_day_period=payload.half_day_period,
            reason=payload.reason,
            attachment_document_id=payload.attachment_document_id,
            status="submitted" if payload.submit_immediately else "draft",
            requested_by_id=actor.id,
        )
        if payload.submit_immediately:
            await start_manager_review(self.session, req, target_emp)
        self.session.add(req)
        await self.session.flush()
        await self.audit.record(
            action="hr.leave_request.created",
            user_id=actor.id,
            entity_type="hr_leave_requests",
            entity_id=req.id,
            new_values={"status": req.status, "days": str(req.days_requested)},
        )
        await self._commit_and_refresh(req)
        return req

    async def resubmit_own_leave_request(
        self, request_id: UUID, payload: LeaveRequestResubmitRequest, actor: User
    ) -> HrLeaveRequest:
        employee = await self._employee_for_user(actor)
        req = await self.session.scalar(
            select(HrLeaveRequest)
            .where(
                HrLeaveRequest.id == request_id,
                HrLeaveRequest.employee_id == employee.id,
                HrLeaveRequest.requested_by_id == actor.id,
            )
            .with_for_update()
        )
        if req is None:
            raise NotFoundException("Leave request")
        employee = await self._require_employee(req.employee_id, for_update=True)
        self._verify_self_request(employee, actor)
        verify_request_revision(req, payload.expected_revision)
        if req.status not in {"draft", "rejected"}:
            raise AppException(
                "Only a draft or rejected leave request can be resubmitted.",
                status_code=409,
                error_code="INVALID_STATE",
            )
        units, workdays = await self._validate_leave_request(payload, employee, actor)
        await self._ensure_no_leave_overlap(
            employee.id, payload.start_date, payload.end_date, exclude=req.id
        )
        previous_status = req.status
        req.leave_type_id = payload.leave_type_id
        req.start_date = payload.start_date
        req.end_date = payload.end_date
        req.days_requested = units
        req.scheduled_work_dates = workdays
        req.is_half_day = payload.is_half_day
        req.half_day_period = payload.half_day_period
        req.reason = payload.reason
        req.attachment_document_id = payload.attachment_document_id
        req.status = "submitted"
        req.decided_by_id = None
        req.decided_at = None
        req.decision_notes = None
        req.record_revision += 1
        await start_manager_review(self.session, req, employee)
        await self.audit.record(
            action="hr.leave_request.resubmitted",
            user_id=actor.id,
            entity_type="hr_leave_requests",
            entity_id=req.id,
            old_values={"status": previous_status},
            new_values={"status": req.status, "revision": req.record_revision},
        )
        await self._commit_and_refresh(req)
        return req

    async def _ensure_no_leave_overlap(
        self, employee_id: UUID, start: date, end: date, *, exclude: UUID | None = None
    ) -> None:
        query = select(HrLeaveRequest.id).where(
            HrLeaveRequest.employee_id == employee_id,
            HrLeaveRequest.status.in_(["submitted", "approved"]),
            HrLeaveRequest.start_date <= end,
            HrLeaveRequest.end_date >= start,
        )
        if exclude is not None:
            query = query.where(HrLeaveRequest.id != exclude)
        if await self.session.scalar(query.limit(1)):
            raise AppException(
                "This request overlaps existing leave.", status_code=409, error_code="LEAVE_OVERLAP"
            )

    async def get_leave_decision_state(self, leave_request_id: UUID) -> LeaveRequestDecisionState:
        request = await self.session.get(HrLeaveRequest, leave_request_id)
        if request is None:
            raise NotFoundException("Leave request")
        return LeaveRequestDecisionState.model_validate(request)

    async def decide_leave_request(
        self,
        leave_request_id: UUID,
        payload: LeaveRequestDecisionRequest,
        actor: User,
        *,
        own_request: bool = False,
    ) -> HrLeaveRequest:
        if not own_request and payload.decision in {"approved", "cancelled"}:
            # Payroll approval and leave evidence take the same lock before employee rows.
            await lock_payroll_periods(self.session)
        req = await self.session.scalar(
            select(HrLeaveRequest).where(HrLeaveRequest.id == leave_request_id).with_for_update()
        )
        if req is None:
            raise NotFoundException("Leave request")
        emp = await self._require_employee(req.employee_id, for_update=True)
        prev_status = req.status
        if own_request and (emp.user_id != actor.id or req.requested_by_id != actor.id):
            raise NotFoundException("Leave request")
        verify_request_revision(req, payload.expected_revision)
        allowed_sources = {
            "submitted": {"draft"},
            "approved": {"submitted"},
            "rejected": {"submitted"},
            "cancelled": {"draft", "submitted", "approved"}
            if not own_request
            else {"draft", "submitted"},
        }
        if prev_status not in allowed_sources[payload.decision]:
            raise AppException(
                "This leave request cannot make that transition.",
                status_code=409,
                error_code="INVALID_STATE",
            )
        reversal = payload.decision == "cancelled" and prev_status == "approved"
        if payload.decision == "approved" or reversal:
            await ensure_leave_year_open(
                self.session, req.employee_id, req.leave_type_id, req.start_date.year
            )
            await require_unlocked_leave_payroll(self.session, req)
        if payload.decision == "submitted":
            req.days_requested, req.scheduled_work_dates = await self._validate_leave_request(
                _stored_leave_fields(req), emp, actor
            )
            await self._ensure_no_leave_overlap(
                emp.id, req.start_date, req.end_date, exclude=req.id
            )
            await start_manager_review(self.session, req, emp)
        if payload.decision == "rejected" and not (payload.notes or "").strip():
            raise AppException("Rejection requires a reason.", status_code=422)
        if (payload.decision in {"approved", "rejected"} or reversal) and (
            emp.user_id == actor.id or req.requested_by_id == actor.id
        ):
            raise AppException(
                "Employees cannot decide their own leave or requests they submitted.",
                status_code=403,
                error_code="SELF_APPROVAL_BLOCKED",
            )
        if payload.decision in {"approved", "rejected"}:
            await require_manager_recommendation(
                self.session, req, emp, actor, payload.expected_revision
            )
        reversed_debit_id = None
        decision_notes = payload.notes
        if payload.decision == "approved":
            lt = await self._active_leave_type(req.leave_type_id)
            units, workdays = await self._calculate_leave_schedule(
                emp, _stored_leave_fields(req), lt
            )
            if units != req.days_requested or (
                req.scheduled_work_dates is not None and req.scheduled_work_dates != workdays
            ):
                raise AppException(
                    "The work schedule changed after submission. "
                    "Reject the request so it can be resubmitted.",
                    status_code=409,
                    error_code="LEAVE_SCHEDULE_CHANGED",
                )
            req.scheduled_work_dates = workdays
            if lt.is_paid and not await self._leave_allows_negative_balance(
                req, emp.employment_category
            ):
                yr = req.start_date.year
                current_bal = await self._leave_balance(req.employee_id, req.leave_type_id, yr)
                if current_bal < req.days_requested:
                    raise AppException(
                        f"Insufficient leave balance ({current_bal} days available, "
                        f"{req.days_requested} requested).",
                        status_code=409,
                        error_code="INSUFFICIENT_LEAVE_BALANCE",
                    )
            self.session.add(
                HrLeaveLedger(
                    employee_id=req.employee_id,
                    leave_type_id=req.leave_type_id,
                    entry_type="taken",
                    days_delta=-req.days_requested,
                    leave_year=req.start_date.year,
                    reference_request_id=req.id,
                    reason=f"Approved leave {req.start_date} to {req.end_date}",
                    actor_user_id=actor.id,
                )
            )
        elif reversal:
            reason = (payload.notes or "").strip()
            if not reason or len(reason) > 500:
                raise AppException(
                    "Supply a cancellation reason of 1 to 500 characters for approved leave.",
                    status_code=422,
                )
            decision_notes = reason
            reversed_debit_id = await require_approved_leave_debit(self.session, req)
            self.session.add(
                HrLeaveLedger(
                    employee_id=req.employee_id,
                    leave_type_id=req.leave_type_id,
                    entry_type="reversal",
                    days_delta=req.days_requested,
                    leave_year=req.start_date.year,
                    reference_request_id=req.id,
                    reason=f"Cancelled approved leave {req.start_date} to {req.end_date}",
                    actor_user_id=actor.id,
                )
            )

        req.status = payload.decision
        req.decided_by_id = actor.id
        req.decided_at = utc_now()
        req.decision_notes = decision_notes
        req.record_revision += 1
        await self.audit.record(
            action=f"hr.leave_request.{payload.decision}",
            user_id=actor.id,
            entity_type="hr_leave_requests",
            entity_id=req.id,
            new_values={"reversed_debit_id": str(reversed_debit_id)} if reversed_debit_id else None,
        )
        await self._commit_and_refresh(req)
        return req

    async def list_leave_requests(
        self, *, employee_id: UUID | None = None, status: str | None = None,
        limit: int | None = None, offset: int = 0,
    ) -> tuple[list[HrLeaveRequest], int]:
        stmt = select(HrLeaveRequest)
        if employee_id:
            stmt = stmt.where(HrLeaveRequest.employee_id == employee_id)
        if status:
            stmt = stmt.where(HrLeaveRequest.status == status)
        ordered = stmt.order_by(HrLeaveRequest.created_at.desc(), HrLeaveRequest.id.desc())
        if limit is None and offset == 0:
            rows = list(await self.session.scalars(ordered))
            return rows, len(rows)
        total = await self.session.scalar(select(func.count()).select_from(stmt.subquery()))
        rows = list(await self.session.scalars(ordered.offset(offset).limit(limit)))
        return rows, total or 0

    # --- Policies, Letter Templates, HR Service Requests (HR-016) ---

    async def _company_policy_file(
        self, document_id: UUID | None, version_number: int | None, *, publishing: bool = False
    ) -> HrDocument | None:
        if document_id is None:
            return None
        if version_number is None:
            raise AppException(
                "HR must republish this policy with the exact file version.", status_code=409
            )
        doc = await self._get_hr_document(document_id, for_update=publishing)
        if (
            doc.employee_id is not None
            or doc.candidate_id is not None
            or doc.document_type != "policy"
            or doc.category != "ordinary"
            or doc.status != "active"
        ):
            raise AppException("Select an approved company policy file.", status_code=409)
        version = await self.session.scalar(
            select(HrDocumentVersion.id).where(
                HrDocumentVersion.document_id == doc.id,
                HrDocumentVersion.version_number == version_number,
                HrDocumentVersion.status.in_(
                    ("active",) if publishing else ("active", "superseded")
                ),
            )
        )
        if version is None or (publishing and version_number != doc.current_version):
            raise AppException(
                "Select the current approved document version for publication.", status_code=409
            )
        return doc

    @staticmethod
    def _current_policy(today: date) -> ColumnElement[bool]:
        successor = aliased(HrPolicyDocument)
        return (
            HrPolicyDocument.is_active.is_(True)
            & HrPolicyDocument.published_at.is_not(None)
            & (HrPolicyDocument.effective_date <= today)
            & ~select(successor.id)
            .where(
                successor.supersedes_policy_id == HrPolicyDocument.id,
                successor.is_active.is_(True),
                successor.published_at.is_not(None),
                successor.effective_date <= today,
            )
            .exists()
        )

    async def create_policy_document(
        self, payload: PolicyDocumentCreateRequest, actor: User
    ) -> HrPolicyDocument:
        if payload.supersedes_policy_id is not None:
            previous = await self.session.scalar(
                select(HrPolicyDocument)
                .where(HrPolicyDocument.id == payload.supersedes_policy_id)
                .with_for_update()
            )
            if previous is None or previous.published_at is None:
                raise NotFoundException("Previous policy edition")
            if (
                payload.effective_date <= previous.effective_date
                or payload.version == previous.version
            ):
                raise AppException(
                    "Use a new version label and a later effective date.", status_code=422
                )
            if await self.session.scalar(
                select(HrPolicyDocument.id)
                .where(HrPolicyDocument.supersedes_policy_id == previous.id)
                .limit(1)
            ):
                raise AppException(
                    "This policy edition already has a replacement.", status_code=409
                )
        await self._company_policy_file(
            payload.document_id, payload.document_version_number, publishing=True
        )
        pol = HrPolicyDocument(
            **payload.model_dump(), published_by_id=actor.id, published_at=utc_now()
        )
        self.session.add(pol)
        try:
            await self.session.flush()
            await self.audit.record(
                action="hr.policy.published",
                user_id=actor.id,
                entity_type="hr_policy_documents",
                entity_id=pol.id,
                new_values={
                    "version": pol.version,
                    "document_version": pol.document_version_number,
                },
            )
            await self.session.commit()
        except IntegrityError as exc:
            await self.session.rollback()
            raise AppException(
                "Policy code already exists.", status_code=409, error_code="POLICY_EXISTS"
            ) from exc
        return pol

    async def list_policy_documents(self) -> tuple[list[HrPolicyDocument], int]:
        rows = list(
            await self.session.scalars(
                select(HrPolicyDocument).order_by(HrPolicyDocument.effective_date.desc())
            )
        )
        return rows, len(rows)

    async def list_self_policies(self, actor: User) -> MyPolicyListResponse:
        employee = await self._employee_for_user(actor)
        current = self._current_policy(business_today())
        result = await self.session.execute(
            select(HrPolicyDocument, current, HrPolicyAcknowledgement.acknowledged_at)
            .outerjoin(
                HrPolicyAcknowledgement,
                (HrPolicyAcknowledgement.policy_id == HrPolicyDocument.id)
                & (HrPolicyAcknowledgement.employee_id == employee.id),
            )
            .where(or_(current, HrPolicyAcknowledgement.id.is_not(None)))
            .order_by(HrPolicyDocument.effective_date.desc(), HrPolicyDocument.id)
        )
        items = [
            MyPolicyResponse(
                **PolicyDocumentResponse.model_validate(policy).model_dump(),
                is_current=is_current,
                acknowledged_at=acknowledged_at,
            )
            for policy, is_current, acknowledged_at in result
        ]
        return MyPolicyListResponse(items=items, total=len(items))

    async def get_self_policy_download_url(
        self, policy_id: UUID, actor: User
    ) -> MyPolicyFileResponse:
        employee = await self._employee_for_user(actor)
        policy = await self.session.scalar(
            select(HrPolicyDocument).where(
                HrPolicyDocument.id == policy_id,
                or_(
                    self._current_policy(business_today()),
                    select(HrPolicyAcknowledgement.id)
                    .where(
                        HrPolicyAcknowledgement.policy_id == HrPolicyDocument.id,
                        HrPolicyAcknowledgement.employee_id == employee.id,
                    )
                    .exists(),
                ),
            )
        )
        if policy is None:
            raise NotFoundException("Policy edition")
        doc = await self._company_policy_file(policy.document_id, policy.document_version_number)
        if doc is None:
            raise NotFoundException("Policy file")
        version = await self.session.scalar(
            select(HrDocumentVersion).where(
                HrDocumentVersion.document_id == doc.id,
                HrDocumentVersion.version_number == policy.document_version_number,
            )
        )
        if version is None:
            raise NotFoundException("Policy document version")
        link = await self._presign_document_version(
            doc,
            actor,
            action="hr.policy.document_downloaded",
            include_category=False,
            version_number=policy.document_version_number,
            allow_superseded=True,
        )
        return MyPolicyFileResponse(
            **link.model_dump(),
            file_size=version.file_size,
            sha256_checksum=version.sha256_checksum,
        )

    @staticmethod
    def _policy_receipt(
        ack: HrPolicyAcknowledgement, policy: HrPolicyDocument
    ) -> PolicyAcknowledgementResponse:
        return PolicyAcknowledgementResponse(
            id=ack.id,
            policy_id=ack.policy_id,
            employee_id=ack.employee_id,
            acknowledged_at=ack.acknowledged_at,
            acknowledged_by_user_id=ack.acknowledged_by_user_id,
            notes=ack.notes,
            policy_version=policy.version,
            document_version_number=policy.document_version_number,
        )

    async def acknowledge_policy(
        self, policy_id: UUID, payload: PolicyAcknowledgeRequest, actor: User
    ) -> PolicyAcknowledgementResponse:
        emp = await self._employee_for_user(actor, for_update=True)
        policy = await self.session.scalar(
            select(HrPolicyDocument).where(HrPolicyDocument.id == policy_id).with_for_update()
        )
        if policy is None:
            raise NotFoundException("Policy edition")
        ack = await self.session.scalar(
            select(HrPolicyAcknowledgement).where(
                HrPolicyAcknowledgement.policy_id == policy.id,
                HrPolicyAcknowledgement.employee_id == emp.id,
            )
        )
        if ack is None and not await self.session.scalar(
            select(HrPolicyDocument.id).where(
                HrPolicyDocument.id == policy.id, self._current_policy(business_today())
            )
        ):
            raise NotFoundException("Policy edition")
        if (payload.expected_version, payload.expected_document_version) != (
            policy.version,
            policy.document_version_number,
        ):
            raise AppException(
                "Review the exact published policy before acknowledging it.", status_code=409
            )
        if ack is not None:
            return self._policy_receipt(ack, policy)
        if not policy.requires_acknowledgement:
            raise AppException("This policy does not require acknowledgement.", status_code=409)
        await self._company_policy_file(policy.document_id, policy.document_version_number)
        ack = HrPolicyAcknowledgement(
            policy_id=policy.id,
            employee_id=emp.id,
            acknowledged_at=utc_now(),
            acknowledged_by_user_id=actor.id,
            notes=payload.notes,
        )
        self.session.add(ack)
        await self.session.flush()
        await self.audit.record(
            action="hr.policy.acknowledged",
            user_id=actor.id,
            entity_type="hr_policy_acknowledgements",
            entity_id=ack.id,
            new_values={
                "policy_id": str(policy.id),
                "version": policy.version,
                "document_version": policy.document_version_number,
            },
        )
        await self.session.commit()
        return self._policy_receipt(ack, policy)

    @staticmethod
    def _validate_letter_template(*templates: str, allowed_fields: set[str] | None = None) -> None:
        try:
            for template in templates:
                for _, field, spec, conversion in Formatter().parse(template):
                    if field is not None and (
                        not field.isascii()
                        or not field.isidentifier()
                        or spec
                        or conversion
                        or (allowed_fields is not None and field not in allowed_fields)
                    ):
                        raise ValueError
        except ValueError as exc:
            raise AppException(
                "Use named placeholders such as {full_name} and double braces for literal braces.",
                status_code=422,
                error_code="INVALID_LETTER_TEMPLATE",
            ) from exc

    async def create_letter_template(
        self, payload: LetterTemplateCreateRequest, actor: User
    ) -> HrLetterTemplate:
        allowed_fields = None
        if payload.letter_type == "candidate_rejection":
            self._require_letter_manager(actor)
            allowed_fields = {"candidate_name", "position_title"}
        self._validate_letter_template(
            payload.subject_template, payload.body_template, allowed_fields=allowed_fields
        )
        tmpl = HrLetterTemplate(**payload.model_dump())
        self.session.add(tmpl)
        try:
            await self.session.flush()
            await self.audit.record(
                action="hr.letter_template.created",
                user_id=actor.id,
                entity_type="hr_letter_templates",
                entity_id=tmpl.id,
            )
            await self.session.commit()
        except IntegrityError as exc:
            await self.session.rollback()
            raise AppException(
                "Letter template code already exists.",
                status_code=409,
                error_code="TEMPLATE_EXISTS",
            ) from exc
        return tmpl

    async def list_letter_templates(
        self, *, candidate: bool = False
    ) -> tuple[list[HrLetterTemplate], int]:
        rows = list(
            await self.session.scalars(
                select(HrLetterTemplate)
                .where(
                    HrLetterTemplate.letter_type == "candidate_rejection"
                    if candidate
                    else HrLetterTemplate.letter_type != "candidate_rejection"
                )
                .order_by(HrLetterTemplate.code)
            )
        )
        return rows, len(rows)

    async def _letter_text(
        self, payload: LetterGenerateRequest, actor: User, emp: HrEmployee
    ) -> tuple[HrLetterTemplate, str, str, UUID | None]:
        tmpl = await self.session.scalar(
            select(HrLetterTemplate).where(
                HrLetterTemplate.id == payload.template_id,
                HrLetterTemplate.is_active.is_(True),
                HrLetterTemplate.letter_type != "candidate_rejection",
            )
        )
        if tmpl is None:
            raise NotFoundException("Letter template")
        if tmpl.letter_type == "salary_confirmation":
            self._require_letter_manager(actor)
            ensure_permission(actor, PERMISSION_HR_PAYROLL_SENSITIVE)
        if tmpl.requires_hr_manager and not has_permission(
            actor, PERMISSION_HR_EMPLOYEES_SENSITIVE
        ):
            raise PermissionDeniedException(PERMISSION_HR_EMPLOYEES_SENSITIVE)
        self._validate_letter_template(tmpl.subject_template, tmpl.body_template)
        if len(tmpl.body_template) > 12000 or any(
            len(value) > 2000 for value in payload.extra_vars.values()
        ):
            raise AppException(
                "The letter template or one of its values is too long.", status_code=422
            )
        context = {
            "employee_code": emp.employee_code,
            "full_name": emp.full_name,
            "join_date": emp.join_date.isoformat() if emp.join_date else "",
            "employment_status": emp.employment_status,
        }
        compensation_fields = (
            {"base_salary", "salary_currency", "pay_frequency"}
            if tmpl.letter_type == "salary_confirmation"
            else set()
        )
        if (context.keys() | compensation_fields) & payload.extra_vars.keys():
            raise AppException(
                "Employee and compensation fields are filled from approved records.",
                status_code=422,
                error_code="LETTER_EMPLOYEE_FIELD_OVERRIDE",
            )
        term_id = None
        if tmpl.letter_type == "salary_confirmation":
            fields = {
                field
                for template in (tmpl.subject_template, tmpl.body_template)
                for _, field, _, _ in Formatter().parse(template)
                if field
            }
            if not compensation_fields <= fields:
                raise AppException(
                    "The salary template must include base salary, currency and pay frequency.",
                    status_code=422,
                )
            terms = await self._compensation_history(emp.id)
            term_id = self._current_compensation(terms)
            if term_id is None:
                raise AppException(
                    "No independently approved current compensation term.", status_code=409
                )
            term = next(term for term in terms if term.id == term_id)
            if term.proposed_by_id is None or term.proposed_by_id == term.approved_by_id:
                raise AppException(
                    "The current term has no independent approval record.", status_code=409
                )
            salary = decrypt_hr_value(term.base_salary_encrypted)
            if not salary:
                raise AppException(
                    "The approved compensation term has no salary value.", status_code=409
                )
            context.update(
                base_salary=salary, salary_currency=term.currency, pay_frequency=term.pay_frequency
            )
        context.update(payload.extra_vars)
        return tmpl, *self._format_letter_text(tmpl, context), term_id

    @staticmethod
    def _format_letter_text(tmpl: HrLetterTemplate, context: dict[str, str]) -> tuple[str, str]:
        try:
            subject = tmpl.subject_template.format(**context)
            body = tmpl.body_template.format(**context)
        except KeyError as exc:
            raise AppException(
                f"Missing template placeholder value: {exc}",
                status_code=422,
                error_code="MISSING_TEMPLATE_VAR",
            ) from exc
        if not subject.strip() or not body.strip() or len(subject) > 500 or len(body) > 24000:
            raise AppException("The rendered letter is empty or too long.", status_code=422)
        return subject, body

    @staticmethod
    def _letter_digest(
        actor: User, employee_id: UUID, revision: int, template_id: UUID, subject: str, body: str,
        term_id: UUID | None = None,
    ) -> str:
        fields = [str(actor.id), str(employee_id), revision, str(template_id), subject, body]
        if term_id is not None:
            fields.append(str(term_id))
        return hashlib.sha256(json.dumps(fields).encode()).hexdigest()

    @staticmethod
    def _require_letter_manager(actor: User) -> None:
        if actor.role != ROLE_HR_MANAGER:
            raise PermissionDeniedException(PERMISSION_HR_REQUESTS_PROCESS)

    async def render_letter(
        self, payload: LetterGenerateRequest, actor: User
    ) -> LetterRenderResponse:
        emp = await self._require_employee(payload.employee_id)
        tmpl, subject, body, term_id = await self._letter_text(payload, actor, emp)
        digest = (
            self._letter_digest(actor, emp.id, emp.record_revision, tmpl.id, subject, body, term_id)
            if actor.role == ROLE_HR_MANAGER
            else None
        )
        await self.audit.record(
            action="hr.letter.rendered",
            user_id=actor.id,
            entity_type="hr_employees",
            entity_id=emp.id,
            new_values={
                "template_code": tmpl.code,
                **({"compensation_term_id": str(term_id)} if term_id else {}),
            },
        )
        await self.session.commit()
        return LetterRenderResponse(
            template_id=tmpl.id, employee_id=emp.id, subject=subject, body=body, digest=digest
        )

    @staticmethod
    def _letter_summary(
        row: HrIssuedLetter, template_name: str, reviewer: User | None
    ) -> LetterSummary:
        return LetterSummary(
            id=row.id,
            template_name=template_name,
            status=row.status,
            created_at=row.created_at,
            decided_at=row.decided_at,
            can_decide=reviewer is not None
            and row.status == "draft"
            and row.prepared_by != reviewer.id,
        )

    def _letter_detail(
        self, row: HrIssuedLetter, template_name: str, reviewer: User | None
    ) -> LetterDetail:
        subject, body = json.loads(decrypt_hr_value(row.content_encrypted) or "null")
        return LetterDetail(
            **self._letter_summary(row, template_name, reviewer).model_dump(),
            subject=subject,
            body=body,
            rejection_reason=decrypt_hr_value(row.reason_encrypted) if reviewer else None,
        )

    async def draft_letter(self, payload: LetterDraftRequest, actor: User) -> LetterDetail:
        self._require_letter_manager(actor)
        emp = await self._require_employee(payload.employee_id, for_update=True)
        existing = await self.session.get(HrIssuedLetter, payload.draft_id)
        if existing is not None:
            if (existing.prepared_by, existing.employee_id, existing.template_id) == (
                actor.id,
                emp.id,
                payload.template_id,
            ):
                template = await self.session.get(HrLetterTemplate, existing.template_id)
                assert template is not None
                if existing.compensation_term_id is not None:
                    ensure_permission(actor, PERMISSION_HR_PAYROLL_SENSITIVE)
                detail = self._letter_detail(existing, template.name, actor)
                digest = self._letter_digest(
                    actor,
                    emp.id,
                    existing.employee_revision,
                    template.id,
                    detail.subject,
                    detail.body,
                    existing.compensation_term_id,
                )
                if digest == payload.expected_digest:
                    return detail
            raise AppException("The letter draft reference is already used.", status_code=409)
        tmpl, subject, body, term_id = await self._letter_text(payload, actor, emp)
        digest = self._letter_digest(
            actor, emp.id, emp.record_revision, tmpl.id, subject, body, term_id
        )
        if digest != payload.expected_digest:
            raise AppException("The letter preview changed. Review it again.", status_code=409)
        row = HrIssuedLetter(
            id=payload.draft_id,
            employee_id=emp.id,
            template_id=tmpl.id,
            employee_revision=emp.record_revision,
            compensation_term_id=term_id,
            content_encrypted=encrypt_hr_value(json.dumps([subject, body])),
            prepared_by=actor.id,
        )
        self.session.add(row)
        try:
            await self.session.flush()
        except IntegrityError as exc:
            await self.session.rollback()
            raise AppException(
                "The letter draft reference is already used.", status_code=409
            ) from exc
        await self._audit_letter(row, actor)
        await self.session.commit()
        return self._letter_detail(row, tmpl.name, actor)

    async def _audit_letter(self, row: HrIssuedLetter, actor: User) -> None:
        await self.audit.record(
            action=f"hr.letter.{row.status}",
            user_id=actor.id,
            entity_type="hr_issued_letters",
            entity_id=row.id,
            new_values={
                "template_id": str(row.template_id),
                "employee_id": str(row.employee_id),
                **({"compensation_term_id": str(row.compensation_term_id)}
                   if row.compensation_term_id else {}),
            },
        )

    async def _letter_employee(self, employee_id: UUID | None, actor: User) -> HrEmployee:
        if employee_id is None:
            return await self._employee_for_user(actor)
        self._require_letter_manager(actor)
        return await self._require_employee(employee_id)

    async def list_letters(
        self,
        employee_id: UUID | None,
        actor: User,
        limit: int,
        offset: int,
        *,
        issued_only: bool = False,
    ) -> LetterListResponse:
        emp = await self._letter_employee(employee_id, actor)
        filters = [HrIssuedLetter.employee_id == emp.id]
        if employee_id is not None and not has_permission(actor, PERMISSION_HR_PAYROLL_SENSITIVE):
            filters.append(HrIssuedLetter.compensation_term_id.is_(None))
        if employee_id is None or issued_only:
            filters.append(HrIssuedLetter.status == "issued")
        rows = await self.session.execute(
            select(HrIssuedLetter, HrLetterTemplate.name)
            .join(HrLetterTemplate, HrLetterTemplate.id == HrIssuedLetter.template_id)
            .where(*filters)
            .order_by(HrIssuedLetter.created_at.desc(), HrIssuedLetter.id.desc())
            .limit(limit)
            .offset(offset)
        )
        total = await self.session.scalar(
            select(func.count()).select_from(HrIssuedLetter).where(*filters)
        )
        reviewer = actor if employee_id is not None and emp.user_id != actor.id else None
        return LetterListResponse(
            items=[self._letter_summary(row, name, reviewer) for row, name in rows],
            total=total or 0,
        )

    async def get_letter(
        self, letter_id: UUID, employee_id: UUID | None, actor: User
    ) -> LetterDetail:
        emp = await self._letter_employee(employee_id, actor)
        query = (
            select(HrIssuedLetter, HrLetterTemplate.name)
            .join(HrLetterTemplate, HrLetterTemplate.id == HrIssuedLetter.template_id)
            .where(HrIssuedLetter.id == letter_id, HrIssuedLetter.employee_id == emp.id)
        )
        if employee_id is None:
            query = query.where(HrIssuedLetter.status == "issued")
        elif not has_permission(actor, PERMISSION_HR_PAYROLL_SENSITIVE):
            query = query.where(HrIssuedLetter.compensation_term_id.is_(None))
        result = (await self.session.execute(query)).one_or_none()
        if result is None:
            raise NotFoundException("HR letter")
        row, name = result
        reviewer = actor if employee_id is not None and emp.user_id != actor.id else None
        detail = self._letter_detail(row, name, reviewer)
        if row.compensation_term_id is not None:
            await self.audit.record(
                action="hr.letter.salary_viewed",
                user_id=actor.id,
                entity_type="hr_issued_letters",
                entity_id=row.id,
            )
            await self.session.commit()
        return detail

    async def decide_letter(
        self, employee_id: UUID, letter_id: UUID, payload: LetterDecisionRequest, actor: User
    ) -> LetterDetail:
        self._require_letter_manager(actor)
        emp = await self._require_employee(employee_id, for_update=True)
        result = (
            await self.session.execute(
                select(HrIssuedLetter, HrLetterTemplate.name)
                .join(HrLetterTemplate, HrLetterTemplate.id == HrIssuedLetter.template_id)
                .where(HrIssuedLetter.id == letter_id, HrIssuedLetter.employee_id == emp.id)
                .with_for_update(of=HrIssuedLetter)
            )
        ).one_or_none()
        if result is None:
            raise NotFoundException("HR letter")
        row, name = result
        if row.compensation_term_id is not None and not has_permission(
            actor, PERMISSION_HR_PAYROLL_SENSITIVE
        ):
            raise NotFoundException("HR letter")
        if actor.id in (row.prepared_by, emp.user_id):
            raise PermissionDeniedException("independent HR letter review")
        reason = (payload.reason or "").strip()
        if (payload.decision == "rejected") != bool(reason):
            raise AppException("Provide a reason only when rejecting a letter.", status_code=422)
        if row.status != "draft":
            if (row.status, row.decided_by, decrypt_hr_value(row.reason_encrypted) or "") == (
                payload.decision,
                actor.id,
                reason,
            ):
                return self._letter_detail(row, name, actor)
            raise AppException("The letter already has a final decision.", status_code=409)
        if payload.decision == "issued":
            if row.compensation_term_id is not None and row.compensation_term_id != (
                self._current_compensation(await self._compensation_history(emp.id))
            ):
                raise AppException(
                    "The approved compensation changed. Prepare a new draft.", status_code=409
                )
            if emp.record_revision != row.employee_revision:
                raise AppException("Employee data changed. Prepare a new draft.", status_code=409)
            if emp.user_id is None or emp.employment_status not in REVIEW_EMPLOYMENT_STATES:
                raise AppException(
                    "The recipient needs an active linked employee profile.", status_code=409
                )
            recipient = await self.session.get(User, emp.user_id)
            if recipient is None or not recipient.is_active or recipient.deleted_at is not None:
                raise AppException("The recipient needs an active portal account.", status_code=409)
        # Verify the retained text can be read before finalizing a decision.
        self._letter_detail(row, name, actor)
        row.status = payload.decision
        row.decided_by = actor.id
        row.decided_at = utc_now()
        row.reason_encrypted = encrypt_hr_value(reason) if reason else None
        await self._audit_letter(row, actor)
        await self.session.commit()
        return self._letter_detail(row, name, actor)

    async def _candidate_letter_text(
        self, application: HrApplication, template_id: UUID
    ) -> tuple[HrLetterTemplate, str, str]:
        if application.stage != "rejected":
            raise AppException(
                "Reject the application before drafting correspondence.", status_code=409
            )
        if await self.session.scalar(
            select(HrOffer.id)
            .where(
                HrOffer.application_id == application.id,
                HrOffer.status.in_(("accepted", "converted")),
            )
            .limit(1)
        ):
            raise AppException(
                "Resolve the accepted offer before preparing correspondence.", status_code=409
            )
        template = await self.session.scalar(
            select(HrLetterTemplate).where(
                HrLetterTemplate.id == template_id,
                HrLetterTemplate.is_active.is_(True),
                HrLetterTemplate.letter_type == "candidate_rejection",
            )
        )
        if template is None:
            raise NotFoundException("Candidate rejection template")
        profile = (
            await self.session.execute(
                select(HrCandidate.full_name, HrRequisition.title)
                .select_from(HrCandidate)
                .join(HrRequisition, HrRequisition.id == application.requisition_id)
                .where(
                    HrCandidate.id == application.candidate_id,
                    HrCandidate.deleted_at.is_(None),
                    HrRequisition.deleted_at.is_(None),
                )
            )
        ).one_or_none()
        if profile is None:
            raise NotFoundException("Candidate or requisition")
        context = {"candidate_name": profile.full_name, "position_title": profile.title}
        self._validate_letter_template(
            template.subject_template, template.body_template, allowed_fields=set(context)
        )
        subject, body = self._format_letter_text(template, context)
        if "\r" in subject or "\n" in subject:
            raise AppException("Correspondence subjects must be on one line.", status_code=422)
        return template, subject, body

    @staticmethod
    def _candidate_letter_summary(
        row: HrCandidateCorrespondence, template_name: str, actor: User
    ) -> LetterSummary:
        return LetterSummary(
            id=row.id,
            template_name=template_name,
            status=row.status,
            can_decide=row.status == "draft" and row.prepared_by != actor.id,
            created_at=row.created_at,
            decided_at=row.decided_at,
        )

    def _candidate_letter_detail(
        self, row: HrCandidateCorrespondence, template_name: str, actor: User
    ) -> CandidateCorrespondenceDetail:
        content = decrypt_hr_value(row.content_encrypted)
        assert content is not None
        subject, body = json.loads(content)
        digest = hashlib.sha256(
            json.dumps([str(row.application_id), str(row.id), subject, body]).encode()
        ).hexdigest()
        return CandidateCorrespondenceDetail(
            **self._candidate_letter_summary(row, template_name, actor).model_dump(),
            subject=subject,
            body=body,
            digest=digest,
            rejection_reason=decrypt_hr_value(row.reason_encrypted),
        )

    async def _audit_candidate_letter(
        self, row: HrCandidateCorrespondence, actor: User, action: str
    ) -> None:
        await self.audit.record(
            action=f"hr.candidate_correspondence.{action}",
            user_id=actor.id,
            entity_type="hr_candidate_correspondence",
            entity_id=row.id,
            new_values={
                "application_id": str(row.application_id),
                "template_id": str(row.template_id),
            },
        )

    async def draft_candidate_correspondence(
        self, application_id: UUID, payload: CandidateCorrespondenceCreateRequest, actor: User
    ) -> CandidateCorrespondenceDetail:
        self._require_letter_manager(actor)
        application = await self.get_application(application_id, lock=True)
        existing = await self.session.get(HrCandidateCorrespondence, payload.draft_id)
        if existing is not None:
            if (existing.application_id, existing.template_id, existing.prepared_by) == (
                application.id,
                payload.template_id,
                actor.id,
            ):
                return await self.get_candidate_correspondence(application_id, existing.id, actor)
            raise AppException("This correspondence reference is already used.", status_code=409)
        if await self.session.scalar(
            select(HrCandidateCorrespondence.id)
            .where(
                HrCandidateCorrespondence.application_id == application.id,
                HrCandidateCorrespondence.status.in_(("draft", "approved")),
            )
            .limit(1)
        ):
            raise AppException(
                "Review the existing draft or use the approved correspondence.", status_code=409
            )
        template, subject, body = await self._candidate_letter_text(
            application, payload.template_id
        )
        content = encrypt_hr_value(json.dumps([subject, body]))
        assert content is not None
        row = HrCandidateCorrespondence(
            id=payload.draft_id,
            application_id=application.id,
            template_id=template.id,
            prepared_by=actor.id,
            content_encrypted=content,
        )
        self.session.add(row)
        try:
            await self.session.flush()
        except IntegrityError as error:
            if getattr(error.orig, "sqlstate", None) == "23505":
                raise AppException(
                    "This correspondence reference is already used.", status_code=409
                ) from error
            raise
        await self._audit_candidate_letter(row, actor, "drafted")
        await self.session.commit()
        return self._candidate_letter_detail(row, template.name, actor)

    async def list_candidate_correspondence(
        self, application_id: UUID, actor: User, *, limit: int, offset: int
    ) -> LetterListResponse:
        self._require_letter_manager(actor)
        await self.get_application(application_id)
        rows = await self.session.execute(
            select(HrCandidateCorrespondence, HrLetterTemplate.name)
            .join(HrLetterTemplate, HrLetterTemplate.id == HrCandidateCorrespondence.template_id)
            .where(HrCandidateCorrespondence.application_id == application_id)
            .order_by(
                HrCandidateCorrespondence.created_at.desc(), HrCandidateCorrespondence.id.desc()
            )
            .limit(limit)
            .offset(offset)
        )
        total = await self.session.scalar(
            select(func.count())
            .select_from(HrCandidateCorrespondence)
            .where(HrCandidateCorrespondence.application_id == application_id)
        )
        return LetterListResponse(
            items=[self._candidate_letter_summary(row, name, actor) for row, name in rows],
            total=total or 0,
        )

    async def _candidate_correspondence_row(
        self, application_id: UUID, draft_id: UUID
    ) -> tuple[HrCandidateCorrespondence, str]:
        result = (
            await self.session.execute(
                select(HrCandidateCorrespondence, HrLetterTemplate.name)
                .join(
                    HrLetterTemplate, HrLetterTemplate.id == HrCandidateCorrespondence.template_id
                )
                .where(
                    HrCandidateCorrespondence.id == draft_id,
                    HrCandidateCorrespondence.application_id == application_id,
                )
            )
        ).one_or_none()
        if result is None:
            raise NotFoundException("Candidate correspondence")
        return result[0], result[1]

    async def get_candidate_correspondence(
        self, application_id: UUID, draft_id: UUID, actor: User
    ) -> CandidateCorrespondenceDetail:
        self._require_letter_manager(actor)
        row, name = await self._candidate_correspondence_row(application_id, draft_id)
        detail = self._candidate_letter_detail(row, name, actor)
        await self._audit_candidate_letter(row, actor, "viewed")
        await self.session.commit()
        return detail

    async def decide_candidate_correspondence(
        self,
        application_id: UUID,
        draft_id: UUID,
        payload: CandidateCorrespondenceDecisionRequest,
        actor: User,
    ) -> CandidateCorrespondenceDetail:
        self._require_letter_manager(actor)
        application = await self.get_application(application_id, lock=True)
        row, name = await self._candidate_correspondence_row(application.id, draft_id)
        if row.prepared_by == actor.id:
            raise PermissionDeniedException("independent candidate correspondence review")
        detail = self._candidate_letter_detail(row, name, actor)
        if detail.digest != payload.expected_digest:
            raise AppException(
                "Open the exact correspondence draft before deciding.", status_code=409
            )
        reason = payload.reason or ""
        if (payload.decision == "rejected") != bool(reason):
            raise AppException(
                "Provide a reason only when rejecting correspondence.", status_code=422
            )
        if row.status != "draft":
            if (row.status, row.decided_by, detail.rejection_reason or "") == (
                payload.decision,
                actor.id,
                reason,
            ):
                return detail
            raise AppException("This correspondence already has a final decision.", status_code=409)
        if payload.decision == "approved":
            _, subject, body = await self._candidate_letter_text(application, row.template_id)
            if (subject, body) != (detail.subject, detail.body):
                raise AppException(
                    "The source changed. Reject this draft and prepare a new one.", status_code=409
                )
        row.status = payload.decision
        row.decided_by = actor.id
        row.decided_at = utc_now()
        row.reason_encrypted = encrypt_hr_value(reason) if reason else None
        await self._audit_candidate_letter(row, actor, payload.decision)
        await self.session.commit()
        return self._candidate_letter_detail(row, name, actor)

    async def create_service_request(
        self, payload: HrServiceRequestCreateRequest, actor: User
    ) -> HrServiceRequest:
        emp = (
            await self._require_employee(payload.employee_id)
            if payload.employee_id
            else await self._employee_for_user(actor)
        )
        req = HrServiceRequest(
            request_code=f"HREQ-{uuid4().hex[:8].upper()}",
            employee_id=emp.id,
            request_type=payload.request_type,
            subject=payload.subject.strip(),
            description=payload.description,
            status="open",
        )
        self.session.add(req)
        await self.session.flush()
        await self.audit.record(
            action="hr.service_request.created",
            user_id=actor.id,
            entity_type="hr_hr_requests",
            entity_id=req.id,
        )
        await self._commit_and_refresh(req)
        return req

    async def get_service_request(
        self, req_id: UUID, *, for_update: bool = False
    ) -> HrServiceRequest:
        query = select(HrServiceRequest).where(HrServiceRequest.id == req_id)
        if for_update:
            query = query.with_for_update().execution_options(populate_existing=True)
        req = await self.session.scalar(query)
        if req is None:
            raise NotFoundException("HR service request")
        return req

    async def list_service_request_assignees(self) -> list[HrServiceRequestAssignee]:
        rows = await self.session.execute(
            select(User.id, User.full_name)
            .where(
                User.deleted_at.is_(None),
                User.is_active.is_(True),
                User.role.in_(roles_with_permission(PERMISSION_HR_REQUESTS_PROCESS)),
            )
            .order_by(User.full_name, User.id)
        )
        return [HrServiceRequestAssignee(id=row.id, full_name=row.full_name) for row in rows]

    async def assign_service_request(
        self, req_id: UUID, payload: HrServiceRequestAssignmentRequest, actor: User
    ) -> HrServiceRequest:
        ensure_permission(actor, PERMISSION_HR_REQUESTS_PROCESS)
        req = await self.get_service_request(req_id, for_update=True)
        if req.updated_at != payload.expected_updated_at:
            raise AppException(
                "This request changed. Refresh it before assigning it.",
                status_code=409,
                error_code="HR_SERVICE_REQUEST_CONFLICT",
            )
        if req.status not in {"open", "in_review", "approved"}:
            raise AppException("Only an active request can be assigned.", status_code=409)
        reason = payload.reason.strip()
        if not reason:
            raise AppException("Enter a reason for the handoff.", status_code=422)
        assignee = await self.session.scalar(
            select(User)
            .where(
                User.id == payload.assigned_to_id,
                User.deleted_at.is_(None),
                User.is_active.is_(True),
                User.role.in_(roles_with_permission(PERMISSION_HR_REQUESTS_PROCESS)),
            )
            .with_for_update()
        )
        if assignee is None:
            raise NotFoundException("Eligible HR request assignee")
        if req.assigned_to_id == assignee.id:
            return req
        previous = str(req.assigned_to_id) if req.assigned_to_id else None
        req.assigned_to_id = assignee.id
        await self.audit.record(
            action="hr.service_request.assigned",
            user_id=actor.id,
            entity_type="hr_hr_requests",
            entity_id=req.id,
            comments=reason,
            old_values={"assigned_to_id": previous},
            new_values={"assigned_to_id": str(assignee.id)},
        )
        await self._commit_and_refresh(req)
        return req

    async def resolve_service_request(
        self, req_id: UUID, payload: HrServiceRequestResolveRequest, actor: User
    ) -> HrServiceRequest:
        ensure_permission(actor, PERMISSION_HR_REQUESTS_PROCESS)
        req = await self.get_service_request(req_id, for_update=True)
        if (
            payload.expected_updated_at is not None
            and req.updated_at != payload.expected_updated_at
        ):
            raise AppException(
                "This request changed. Refresh it before applying changes.",
                status_code=409,
                error_code="HR_SERVICE_REQUEST_CONFLICT",
            )
        allowed = {
            "open": {"in_review", "cancelled"},
            "in_review": {"approved", "completed", "rejected", "cancelled"},
            "approved": {"completed"},
        }
        if payload.status not in allowed.get(req.status, set()):
            raise AppException("This service request cannot make that transition.", status_code=409)
        if payload.status in {"in_review", "completed"} and req.assigned_to_id not in {
            None,
            actor.id,
        }:
            raise AppException(
                "The assigned HR user must take this action. Reassign the request first.",
                status_code=409,
                error_code="HR_SERVICE_REQUEST_ASSIGNED_ELSEWHERE",
            )
        if payload.status in {"approved", "rejected"} and not has_permission(
            actor, PERMISSION_HR_EMPLOYEES_SENSITIVE
        ):
            raise PermissionDeniedException(PERMISSION_HR_EMPLOYEES_SENSITIVE)
        if payload.generated_document_id:
            doc = await self._get_hr_document(payload.generated_document_id)
            self._ensure_hr_doc_access(doc, actor)
            if (
                not doc.is_employee_visible
                or doc.status != "active"
                or doc.employee_id != req.employee_id
                or doc.category != "ordinary"
            ):
                raise NotFoundException("HR Document")
        letter_id = payload.generated_letter_id
        if letter_id is not None:
            if payload.status != "completed" or payload.expected_updated_at is None:
                raise AppException(
                    "Select a letter only when completing the current version of the request.",
                    status_code=422,
                )
            self._require_letter_manager(actor)
            issued_query = select(HrIssuedLetter.id).where(
                HrIssuedLetter.id == letter_id,
                HrIssuedLetter.employee_id == req.employee_id,
                HrIssuedLetter.status == "issued",
            )
            if not has_permission(actor, PERMISSION_HR_PAYROLL_SENSITIVE):
                issued_query = issued_query.where(HrIssuedLetter.compensation_term_id.is_(None))
            issued = await self.session.scalar(issued_query)
            if issued is None:
                raise NotFoundException("Issued HR letter")
        prior_status = req.status
        previous_letter = req.generated_letter_id
        prior_assignee = str(req.assigned_to_id) if req.assigned_to_id else None
        req.status = payload.status
        if "resolution_notes" in payload.model_fields_set:
            req.resolution_notes = payload.resolution_notes
        if "generated_document_id" in payload.model_fields_set:
            req.generated_document_id = payload.generated_document_id
        if letter_id is not None:
            req.generated_letter_id = letter_id
        if payload.status in {"approved", "completed", "rejected"}:
            req.resolved_by_id = actor.id
            req.resolved_at = utc_now()
        if payload.status == "in_review":
            req.assigned_to_id = actor.id
        await self.audit.record(
            action=f"hr.service_request.{payload.status}",
            user_id=actor.id,
            entity_type="hr_hr_requests",
            entity_id=req.id,
            old_values={
                "status": prior_status,
                "assigned_to_id": prior_assignee,
                "generated_letter_id": str(previous_letter) if previous_letter else None,
            },
            new_values={
                "status": req.status,
                "generated_letter_id": str(req.generated_letter_id)
                if req.generated_letter_id
                else None,
                "assigned_to_id": str(req.assigned_to_id) if req.assigned_to_id else None,
            },
        )
        await self._commit_and_refresh(req)
        return req

    async def reopen_my_service_request(
        self, req_id: UUID, expected_updated_at: datetime, actor: User
    ) -> HrServiceRequest:
        employee = await self._employee_for_user(actor)
        req = await self.session.scalar(
            select(HrServiceRequest)
            .where(HrServiceRequest.id == req_id, HrServiceRequest.employee_id == employee.id)
            .with_for_update()
            .execution_options(populate_existing=True)
        )
        if req is None:
            raise NotFoundException("HR service request")
        if req.updated_at != expected_updated_at or req.status not in {"completed", "rejected"}:
            raise AppException(
                "Only the current version of a completed or rejected request can be reopened.",
                status_code=409,
                error_code="HR_SERVICE_REQUEST_CONFLICT",
            )
        prior_status = req.status
        prior_assignee = str(req.assigned_to_id) if req.assigned_to_id else None
        req.status = "open"
        req.assigned_to_id = None
        req.resolved_by_id = None
        req.resolved_at = None
        await self.audit.record(
            action="hr.service_request.reopened",
            user_id=actor.id,
            entity_type="hr_hr_requests",
            entity_id=req.id,
            old_values={"status": prior_status, "assigned_to_id": prior_assignee},
            new_values={
                "status": req.status,
                "assigned_to_id": str(req.assigned_to_id) if req.assigned_to_id else None,
            },
        )
        await self._commit_and_refresh(req)
        return req

    async def list_service_requests(
        self, *, employee_id: UUID | None = None, status: str | None = None,
        limit: int | None = None, offset: int = 0,
    ) -> tuple[list[HrServiceRequest], int]:
        stmt = select(HrServiceRequest)
        if employee_id:
            stmt = stmt.where(HrServiceRequest.employee_id == employee_id)
        if status is not None:
            stmt = stmt.where(HrServiceRequest.status == status)
        ordered = stmt.order_by(HrServiceRequest.created_at.desc(), HrServiceRequest.id.desc())
        if limit is None and offset == 0:
            rows = list(await self.session.scalars(ordered))
            return rows, len(rows)
        total = await self.session.scalar(select(func.count()).select_from(stmt.subquery()))
        rows = list(await self.session.scalars(ordered.offset(offset).limit(limit)))
        return rows, total or 0

    # --- Offboarding & Clearance (HR-017, HR-018) ---

    async def initiate_offboarding(
        self, payload: OffboardingInitiateRequest, actor: User
    ) -> OffboardingCaseResponse:
        emp = await self._require_employee(payload.employee_id, for_update=True)
        if emp.join_date is not None and payload.last_working_date < emp.join_date:
            raise AppException("The last working day precedes employment.", status_code=422)
        if payload.notice_date and payload.last_working_date < payload.notice_date:
            raise AppException("Last working day cannot precede notice.", status_code=422)
        if emp.employment_status in {"notice_period", "resigned", "terminated", "archived"}:
            raise AppException(
                "The employee already has a separation in progress or recorded.", status_code=409
            )
        case = HrOffboardingCase(
            employee_id=emp.id,
            separation_type=payload.separation_type,
            notice_date=payload.notice_date,
            last_working_date=payload.last_working_date,
            reason=payload.reason,
            status="initiated",
            initiated_by_id=actor.id,
        )
        self.session.add(case)
        await self.session.flush()
        steps = [
            ("hr", "Exit interview & employee file closure"),
            (IT_AREA, "Revoke IT access and return assigned devices"),
            (STORE_AREA, "Return site tools, PPE, and store items"),
            (FINANCE_AREA, "Review advances and final settlement"),
            ("project_ops", "Handover active project site duties"),
        ]
        for area, title in steps:
            self.session.add(
                HrClearanceStep(
                    offboarding_case_id=case.id, department_area=area, title=title, status="pending"
                )
            )
        prev_status = emp.employment_status
        emp.employment_status = "notice_period"
        emp.record_revision += 1
        emp.updated_by_id = actor.id
        self.session.add(
            HrEmploymentHistory(
                employee_id=emp.id,
                change_type="offboarding_initiated",
                effective_date=payload.notice_date or utc_now().date(),
                previous_snapshot={"employment_status": prev_status},
                new_snapshot={"employment_status": "notice_period"},
                reason=payload.reason or f"Separation: {payload.separation_type}",
                actor_user_id=actor.id,
            )
        )
        await self.audit.record(
            action="hr.offboarding.initiated",
            user_id=actor.id,
            entity_type="hr_offboarding_cases",
            entity_id=case.id,
        )
        await self._commit_and_refresh(case)
        return await self._serialize_offboarding_case(case)

    async def update_clearance_step(
        self, step_id: UUID, payload: OffboardingStepUpdateRequest, actor: User
    ) -> OffboardingCaseResponse:
        step = await self.session.get(HrClearanceStep, step_id)
        if step is None:
            raise NotFoundException("Clearance step")
        case = await self.session.scalar(
            select(HrOffboardingCase)
            .where(HrOffboardingCase.id == step.offboarding_case_id)
            .with_for_update()
        )
        if case is None or case.status == "completed":
            raise AppException("The offboarding case is closed.", status_code=409)
        await self.session.refresh(step)
        if step.department_area in {STORE_AREA, IT_AREA, FINANCE_AREA}:
            raise PermissionDeniedException("department owner clearance")
        if payload.status in {"cleared", "waived"} and not (payload.notes or "").strip():
            raise AppException("Provide a clearance or exception reference.", status_code=422)
        step.status = payload.status
        step.notes = payload.notes
        if payload.status in {"cleared", "waived"}:
            step.cleared_by_id = actor.id
            step.cleared_at = utc_now()
        else:
            step.cleared_by_id = None
            step.cleared_at = None
        case.status = "clearance_in_progress"
        await self.audit.record(
            action="hr.clearance_step.updated",
            user_id=actor.id,
            entity_type="hr_clearance_steps",
            entity_id=step.id,
            new_values={"status": step.status},
        )
        await self._commit_and_refresh(step, case)
        return await self._serialize_offboarding_case(case)

    async def complete_offboarding(
        self, case_id: UUID, payload: OffboardingCompleteRequest, actor: User
    ) -> OffboardingCaseResponse:
        case = await self.session.scalar(
            select(HrOffboardingCase).where(HrOffboardingCase.id == case_id).with_for_update()
        )
        if case is None:
            raise NotFoundException("Offboarding case")
        if case.status == "completed":
            raise AppException("The offboarding case is already closed.", status_code=409)
        steps = list(
            await self.session.scalars(
                select(HrClearanceStep).where(HrClearanceStep.offboarding_case_id == case.id)
            )
        )
        if any(s.status not in {"cleared", "waived"} for s in steps):
            raise AppException(
                "All clearance steps must be cleared or waived before completing offboarding.",
                status_code=409,
                error_code="CLEARANCE_INCOMPLETE",
            )
        for area in (STORE_AREA, IT_AREA):
            custody_step = next((step for step in steps if step.department_area == area), None)
            if custody_step is None:
                raise AppException("A custody clearance step is missing.", status_code=409)
            await require_custody_clearance(self.session, case, custody_step)
        finance_step = next((step for step in steps if step.department_area == FINANCE_AREA), None)
        if finance_step is None:
            raise AppException("The Finance clearance step is missing.", status_code=409)
        await require_settlement_clearance(self.session, case, finance_step)
        emp = await self._require_employee(case.employee_id, for_update=True)
        if emp.user_id:
            case.access_revoked_at = await confirmed_access_revocation(self.session, emp)
        if emp.join_date is not None and case.last_working_date < emp.join_date:
            raise AppException("The last working day precedes employment.", status_code=409)
        period = await self.session.scalar(
            select(HrEmploymentPeriod).where(
                HrEmploymentPeriod.employee_id == emp.id, HrEmploymentPeriod.ended_on.is_(None)
            )
        )
        if period is None:
            period = HrEmploymentPeriod(employee_id=emp.id, started_on=emp.join_date)
            self.session.add(period)
        period.ended_on = case.last_working_date
        period.separation_case_id = case.id
        new_emp_status = "resigned" if case.separation_type == "resignation" else "terminated"
        prev_status = emp.employment_status
        emp.employment_status = new_emp_status
        emp.termination_date = case.last_working_date
        emp.record_revision += 1
        emp.updated_by_id = actor.id
        self.session.add(
            HrEmploymentHistory(
                employee_id=emp.id,
                change_type="offboarding_completed",
                effective_date=case.last_working_date,
                previous_snapshot={"employment_status": prev_status},
                new_snapshot={
                    "employment_status": new_emp_status,
                    "termination_date": case.last_working_date.isoformat(),
                },
                reason=f"Offboarding completed ({case.separation_type})",
                actor_user_id=actor.id,
            )
        )
        case.status = "completed"
        case.exit_interview_notes = payload.exit_interview_notes
        case.rehire_eligible = payload.rehire_eligible
        case.completed_by_id = actor.id
        case.completed_at = utc_now()

        await self.audit.record(
            action="hr.offboarding.completed",
            user_id=actor.id,
            entity_type="hr_offboarding_cases",
            entity_id=case.id,
        )
        await self._commit_and_refresh(case)
        return await self._serialize_offboarding_case(case)

    async def list_offboarding_cases(
        self, *, employee_id: UUID | None = None
    ) -> tuple[list[OffboardingCaseResponse], int]:
        stmt = select(HrOffboardingCase)
        if employee_id:
            stmt = stmt.where(HrOffboardingCase.employee_id == employee_id)
        rows = list(await self.session.scalars(stmt.order_by(HrOffboardingCase.created_at.desc())))
        return [await self._serialize_offboarding_case(r) for r in rows], len(rows)

    async def _serialize_offboarding_case(self, case: HrOffboardingCase) -> OffboardingCaseResponse:
        steps = list(
            await self.session.scalars(
                select(HrClearanceStep)
                .where(HrClearanceStep.offboarding_case_id == case.id)
                .order_by(HrClearanceStep.department_area)
            )
        )
        return OffboardingCaseResponse(
            id=case.id,
            employee_id=case.employee_id,
            separation_type=case.separation_type,
            notice_date=case.notice_date,
            last_working_date=case.last_working_date,
            reason=case.reason,
            status=case.status,
            exit_interview_notes=case.exit_interview_notes,
            rehire_eligible=case.rehire_eligible,
            access_revoked_at=case.access_revoked_at,
            initiated_by_id=case.initiated_by_id,
            completed_by_id=case.completed_by_id,
            completed_at=case.completed_at,
            steps=[ClearanceStepResponse.model_validate(s) for s in steps],
            created_at=case.created_at,
            updated_at=case.updated_at,
        )

    # --- P2 Policy-Gated Modules (HR-019 to HR-024) ---

    async def create_goal(self, payload: GoalCreateRequest, actor: User) -> HrGoal:
        employee = await self._require_employee(payload.employee_id, for_update=True)
        cycle = await self.session.scalar(
            select(HrReviewCycle).where(HrReviewCycle.code == payload.cycle_name)
        )
        if cycle is None:
            raise NotFoundException("Review cycle")
        if payload.target_date and not cycle.start_date <= payload.target_date <= cycle.end_date:
            raise AppException("The goal target must be inside the review cycle.", status_code=422)
        await self._ensure_goals_editable(employee.id, cycle.code)
        goal = HrGoal(**payload.model_dump())
        self.session.add(goal)
        await self.session.flush()
        await self.audit.record(
            action="hr.goal.created", user_id=actor.id, entity_type="hr_goals", entity_id=goal.id
        )
        await self._commit_and_refresh(goal)
        return goal

    async def _ensure_goals_editable(self, employee_id: UUID, cycle_code: str) -> None:
        if await self.session.scalar(
            select(HrReview.id)
            .join(HrReviewCycle, HrReviewCycle.id == HrReview.cycle_id)
            .where(HrReview.employee_id == employee_id, HrReviewCycle.code == cycle_code)
            .limit(1)
        ):
            raise AppException("Goals are retained once the review is opened.", status_code=409)

    async def update_goal(self, goal_id: UUID, payload: GoalUpdateRequest, actor: User) -> HrGoal:
        employee_id = await self.session.scalar(
            select(HrGoal.employee_id).where(HrGoal.id == goal_id)
        )
        if employee_id is None:
            raise NotFoundException("Goal")
        await self._require_employee(employee_id, for_update=True)
        goal = await self.session.get(HrGoal, goal_id)
        if goal is None:
            raise NotFoundException("Goal")
        await self._ensure_goals_editable(goal.employee_id, goal.cycle_name)
        if payload.progress_percent is not None:
            goal.progress_percent = payload.progress_percent
        if payload.status is not None:
            goal.status = payload.status
        await self.audit.record(
            action="hr.goal.updated", user_id=actor.id, entity_type="hr_goals", entity_id=goal.id
        )
        await self._commit_and_refresh(goal)
        return goal

    async def list_goals(self, *, employee_id: UUID | None = None) -> tuple[list[HrGoal], int]:
        stmt = select(HrGoal)
        if employee_id:
            stmt = stmt.where(HrGoal.employee_id == employee_id)
        rows = list(await self.session.scalars(stmt.order_by(HrGoal.created_at.desc())))
        return rows, len(rows)

    async def create_review_cycle(
        self, payload: ReviewCycleCreateRequest, actor: User
    ) -> HrReviewCycle:
        cycle = HrReviewCycle(**payload.model_dump())
        self.session.add(cycle)
        try:
            await self.session.flush()
            await self.audit.record(
                action="hr.review_cycle.created",
                user_id=actor.id,
                entity_type="hr_review_cycles",
                entity_id=cycle.id,
            )
            await self.session.commit()
        except IntegrityError as exc:
            await self.session.rollback()
            raise AppException(
                "Review cycle code already exists.", status_code=409, error_code="CYCLE_EXISTS"
            ) from exc
        return cycle

    async def list_review_cycles(self) -> tuple[list[HrReviewCycle], int]:
        rows = list(
            await self.session.scalars(
                select(HrReviewCycle).order_by(HrReviewCycle.start_date.desc())
            )
        )
        return rows, len(rows)

    async def create_review(self, payload: ReviewCreateRequest, actor: User) -> HrReview:
        if payload.status != "draft" or any(
            value is not None
            for value in (
                payload.self_rating,
                payload.manager_rating,
                payload.final_rating,
                payload.summary_notes,
            )
        ):
            raise AppException(
                "Start a draft and record decisions through its participants.", status_code=422
            )
        employee = await self._require_employee(payload.employee_id, for_update=True)
        manager = await eligible_reviewer(self.session, employee)
        if actor.id == employee.user_id or actor.id == manager:
            raise PermissionDeniedException("open one's own participant review")
        if (
            employee.user_id is None
            or manager is None
            or (
                payload.reviewer_employee_id is not None
                and payload.reviewer_employee_id != employee.manager_employee_id
            )
        ):
            raise AppException(
                "Link the employee and authorize the current direct reviewer before opening.",
                status_code=409,
            )
        cycle = await self.session.get(HrReviewCycle, payload.cycle_id)
        if cycle is None:
            raise NotFoundException("Review cycle")
        await self._ensure_goals_editable(employee.id, cycle.code)
        if not await self.session.scalar(
            select(HrGoal.id)
            .where(
                HrGoal.employee_id == employee.id,
                HrGoal.cycle_name == cycle.code,
                HrGoal.status == "active",
            )
            .limit(1)
        ):
            raise AppException("Record a goal for this employee and cycle first.", status_code=409)
        rev = HrReview(
            employee_id=employee.id,
            cycle_id=cycle.id,
            reviewer_employee_id=employee.manager_employee_id,
            status="draft",
        )
        self.session.add(rev)
        await self.session.flush()
        await self.audit.record(
            action="hr.review.created",
            user_id=actor.id,
            entity_type="hr_reviews",
            entity_id=rev.id,
        )
        await self.session.commit()
        return rev

    async def list_reviews(self, *, employee_id: UUID | None = None) -> tuple[list[HrReview], int]:
        stmt = select(HrReview)
        if employee_id:
            stmt = stmt.where(HrReview.employee_id == employee_id)
        rows = list(await self.session.scalars(stmt.order_by(HrReview.created_at.desc())))
        return rows, len(rows)

    async def list_self_training(
        self, actor: User, *, limit: int, offset: int
    ) -> SelfTrainingListResponse:
        employee = await self.require_self_employee(actor)
        own = HrTrainingEnrollment.employee_id == employee.id
        rows = await self.session.execute(
            select(
                HrTrainingEnrollment,
                HrTrainingCourse.title,
                HrTrainingCompletion.certificate_id,
                HrCertification.expiry_date,
            )
            .join(HrTrainingCourse, HrTrainingCourse.id == HrTrainingEnrollment.course_id)
            .outerjoin(
                HrTrainingCompletion, HrTrainingCompletion.enrollment_id == HrTrainingEnrollment.id
            )
            .outerjoin(HrCertification, HrCertification.id == HrTrainingCompletion.certificate_id)
            .where(own)
            .order_by(HrTrainingEnrollment.created_at.desc(), HrTrainingEnrollment.id.desc())
            .limit(limit)
            .offset(offset)
        )
        total = await self.session.scalar(select(func.count(HrTrainingEnrollment.id)).where(own))
        today = business_today()
        return SelfTrainingListResponse(
            items=[
                SelfTrainingItem(
                    enrollment_id=row.id,
                    course_title=title,
                    status=row.status,
                    scheduled_date=row.scheduled_date,
                    completed_date=row.completed_date,
                    verified=certificate_id is not None,
                    certificate_expiry=expiry,
                    certificate_expired=expiry is not None and expiry < today,
                )
                for row, title, certificate_id, expiry in rows
            ],
            total=total or 0,
        )

    async def create_training_course(
        self, payload: TrainingCourseCreateRequest, actor: User
    ) -> HrTrainingCourse:
        course = HrTrainingCourse(**payload.model_dump())
        self.session.add(course)
        try:
            await self.session.flush()
            await self.audit.record(
                action="hr.training_course.created",
                user_id=actor.id,
                entity_type="hr_training_courses",
                entity_id=course.id,
            )
            await self.session.commit()
        except IntegrityError as exc:
            await self.session.rollback()
            raise AppException(
                "Course code already exists.", status_code=409, error_code="COURSE_EXISTS"
            ) from exc
        return course

    async def list_training_courses(self) -> tuple[list[HrTrainingCourse], int]:
        rows = list(
            await self.session.scalars(
                select(HrTrainingCourse).order_by(HrTrainingCourse.code.asc())
            )
        )
        return rows, len(rows)

    async def create_training_enrollment(
        self, payload: TrainingEnrollmentCreateRequest, actor: User
    ) -> HrTrainingEnrollment:
        employee = await self._require_employee(payload.employee_id, for_update=True)
        if employee.employment_status not in {
            "onboarding",
            "active",
            "on_probation",
            "on_leave",
            "notice_period",
        }:
            raise AppException(
                "Enroll an employee in a current employment period.", status_code=409
            )
        if not await self.session.scalar(
            select(HrTrainingCourse.id).where(
                HrTrainingCourse.id == payload.course_id, HrTrainingCourse.is_active.is_(True)
            )
        ):
            raise NotFoundException("Active training course")
        if await self.session.scalar(
            select(HrTrainingEnrollment.id)
            .where(
                HrTrainingEnrollment.employee_id == employee.id,
                HrTrainingEnrollment.course_id == payload.course_id,
                HrTrainingEnrollment.status.in_(("enrolled", "in_progress")),
            )
            .limit(1)
        ):
            raise AppException("This employee already has an open enrollment.", status_code=409)
        enr = HrTrainingEnrollment(**payload.model_dump())
        self.session.add(enr)
        await self.session.flush()
        await self.audit.record(
            action="hr.training.enrolled",
            user_id=actor.id,
            entity_type="hr_training_enrollments",
            entity_id=enr.id,
        )
        await self._commit_and_refresh(enr)
        return enr

    async def update_training_enrollment(
        self, enrollment_id: UUID, payload: TrainingEnrollmentUpdateRequest, actor: User
    ) -> HrTrainingEnrollment:
        enr = await self.session.scalar(
            select(HrTrainingEnrollment)
            .where(HrTrainingEnrollment.id == enrollment_id)
            .with_for_update()
        )
        if enr is None:
            raise NotFoundException("Training enrollment")
        if payload.status == "completed":
            raise AppException(
                "Verify certificate evidence to complete training.",
                status_code=409,
                error_code="TRAINING_EVIDENCE_REQUIRED",
            )
        if enr.status not in {"enrolled", "in_progress"}:
            raise AppException("The training enrollment is closed.", status_code=409)
        if payload.expected_status is not None and payload.expected_status != enr.status:
            raise AppException(
                "The enrollment changed. Reload it before updating its status.", status_code=409
            )
        if payload.completed_date is not None or payload.score is not None:
            raise AppException("Date and score belong to verified completion.", status_code=422)
        previous_status = enr.status
        enr.status = payload.status
        await self.audit.record(
            action="hr.training.updated",
            user_id=actor.id,
            entity_type="hr_training_enrollments",
            entity_id=enr.id,
            old_values={"status": previous_status},
            new_values={"status": enr.status},
        )
        await self._commit_and_refresh(enr)
        return enr

    async def get_training_completion(self, enrollment_id: UUID) -> TrainingCompletionResponse:
        result = (
            await self.session.execute(
                select(HrTrainingCompletion, HrTrainingEnrollment, HrDocumentVersion)
                .join(
                    HrTrainingEnrollment,
                    HrTrainingEnrollment.id == HrTrainingCompletion.enrollment_id,
                )
                .join(
                    HrDocumentVersion,
                    HrDocumentVersion.id == HrTrainingCompletion.document_version_id,
                )
                .where(HrTrainingCompletion.enrollment_id == enrollment_id)
            )
        ).one_or_none()
        if result is None:
            raise NotFoundException("Verified training completion")
        evidence, enrollment, version = result
        if enrollment.completed_date is None:
            raise AppException("The retained training completion is incomplete.", status_code=409)
        return TrainingCompletionResponse(
            enrollment_id=enrollment.id,
            certificate_id=evidence.certificate_id,
            document_id=version.document_id,
            version_number=version.version_number,
            completed_date=enrollment.completed_date,
            score=enrollment.score,
            verified_at=evidence.verified_at,
            verified_by_id=evidence.verified_by_id,
        )

    async def complete_training_enrollment(
        self, enrollment_id: UUID, payload: TrainingCompletionRequest, actor: User
    ) -> TrainingCompletionResponse:
        employee_id = await self.session.scalar(
            select(HrTrainingEnrollment.employee_id).where(HrTrainingEnrollment.id == enrollment_id)
        )
        if employee_id is None:
            raise NotFoundException("Training enrollment")
        employee = await self._require_employee(employee_id, for_update=True)
        if employee.user_id == actor.id:
            raise PermissionDeniedException("verify one's own training completion")
        enrollment = await self.session.scalar(
            select(HrTrainingEnrollment)
            .where(HrTrainingEnrollment.id == enrollment_id)
            .with_for_update()
        )
        if enrollment is None:
            raise NotFoundException("Training enrollment")
        receipt = await self.session.get(HrTrainingCompletion, enrollment_id)
        if receipt is not None:
            verified = await self.get_training_completion(enrollment_id)
            if receipt.verified_by_id == actor.id and (
                verified.document_id,
                verified.version_number,
                verified.completed_date,
                verified.score,
            ) == (
                payload.document_id,
                payload.version_number,
                payload.completed_date,
                payload.score,
            ):
                return verified
            raise AppException("The training completion is already verified.", status_code=409)
        if enrollment.status not in {"enrolled", "in_progress"}:
            raise AppException("The training enrollment is closed.", status_code=409)
        today = business_today()
        if (
            payload.completed_date > today
            or (employee.join_date is not None and payload.completed_date < employee.join_date)
            or (
                employee.termination_date is not None
                and payload.completed_date > employee.termination_date
            )
            or (
                enrollment.scheduled_date is not None
                and payload.completed_date < enrollment.scheduled_date
            )
        ):
            raise AppException(
                "Choose a completed date within the scheduled employment period.", status_code=422
            )

        document = await self._get_hr_document(payload.document_id, for_update=True)
        if (
            document.employee_id != employee.id
            or document.candidate_id is not None
            or document.document_type != "training_certificate"
            or document.category != "ordinary"
        ):
            raise NotFoundException("Employee training certificate")
        version = await self.session.scalar(
            select(HrDocumentVersion).where(
                HrDocumentVersion.document_id == document.id,
                HrDocumentVersion.version_number == payload.version_number,
            )
        )
        if (
            version is None
            or version.status != "active"
            or document.status != "active"
            or document.current_version != payload.version_number
        ):
            raise AppException(
                "Select the current approved training certificate version.", status_code=409
            )
        if (
            document.issue_date is None
            or document.issue_date < payload.completed_date
            or document.issue_date > today
            or (document.expiry_date is not None and document.expiry_date < document.issue_date)
        ):
            raise AppException(
                "The certificate needs a valid issue date and expiry window.", status_code=422
            )
        if await self.session.scalar(
            select(HrTrainingCompletion.enrollment_id).where(
                HrTrainingCompletion.document_version_id == version.id
            )
        ):
            raise AppException(
                "This certificate version is already used for a completion.", status_code=409
            )

        certificate = HrCertification(
            employee_id=employee.id,
            name=document.title,
            document_id=document.id,
            issuing_body=document.issuing_authority,
            certificate_number=document.reference_number,
            issued_date=document.issue_date,
            expiry_date=document.expiry_date,
            status="valid",
        )
        self.session.add(certificate)
        await self.session.flush()
        enrollment.status = "completed"
        enrollment.completed_date = payload.completed_date
        enrollment.score = payload.score
        self.session.add(
            HrTrainingCompletion(
                enrollment_id=enrollment.id,
                certificate_id=certificate.id,
                document_version_id=version.id,
                verified_by_id=actor.id,
            )
        )
        await self.audit.record(
            action="hr.training.completed",
            user_id=actor.id,
            entity_type="hr_training_enrollments",
            entity_id=enrollment.id,
            new_values={
                "certificate_id": str(certificate.id),
                "evidence_version": version.version_number,
            },
        )
        await self.session.commit()
        return await self.get_training_completion(enrollment_id)

    async def list_training_enrollments(
        self, *, employee_id: UUID | None = None
    ) -> tuple[list[HrTrainingEnrollment], int]:
        stmt = select(HrTrainingEnrollment)
        if employee_id:
            stmt = stmt.where(HrTrainingEnrollment.employee_id == employee_id)
        rows = list(
            await self.session.scalars(stmt.order_by(HrTrainingEnrollment.created_at.desc()))
        )
        return rows, len(rows)

    async def create_certification(
        self, payload: CertificationCreateRequest, actor: User
    ) -> HrCertification:
        await self._require_employee(payload.employee_id)
        if payload.document_id is not None:
            document = await self._get_hr_document(payload.document_id)
            self._ensure_hr_doc_access(document, actor)
            if document.employee_id != payload.employee_id or document.candidate_id is not None:
                raise NotFoundException("Employee certificate")
            if document.document_type == "training_certificate":
                raise AppException(
                    "Verify the associated training enrollment first.", status_code=409
                )
        cert = HrCertification(**payload.model_dump())
        self.session.add(cert)
        await self.session.flush()
        await self.audit.record(
            action="hr.certification.created",
            user_id=actor.id,
            entity_type="hr_certifications",
            entity_id=cert.id,
        )
        await self.session.commit()
        return cert

    async def list_certifications(
        self, *, employee_id: UUID | None = None
    ) -> tuple[list[HrCertification], int]:
        stmt = select(HrCertification)
        if employee_id:
            stmt = stmt.where(HrCertification.employee_id == employee_id)
        rows = list(await self.session.scalars(stmt.order_by(HrCertification.expiry_date.asc())))
        return rows, len(rows)

    async def create_benefit_type(
        self, payload: BenefitTypeCreateRequest, actor: User
    ) -> HrBenefitType:
        ensure_permission(actor, PERMISSION_HR_PAYROLL_SENSITIVE)
        if (payload.reimbursement_ceiling is None) != (payload.reimbursement_currency is None):
            raise AppException("Set both the ceiling and its currency.", status_code=422)
        if payload.reimbursement_ceiling is not None and not payload.requires_policy_approval:
            raise AppException(
                "A reimbursement ceiling requires independent approval.", status_code=422
            )
        if payload.allows_advances and payload.reimbursement_ceiling is None:
            raise AppException("An advance requires a benefit ceiling.", status_code=422)
        code = payload.code.strip().upper()
        if not code:
            raise AppException("Provide a benefit code.", status_code=422)
        bt = HrBenefitType(
            **payload.model_dump(exclude={"code"}),
            code=code,
            proposed_by_id=actor.id if payload.reimbursement_ceiling is not None else None,
        )
        self.session.add(bt)
        try:
            await self.session.flush()
            await self.audit.record(
                action="hr.benefit_type.created",
                user_id=actor.id,
                entity_type="hr_benefit_types",
                entity_id=bt.id,
            )
            await self.session.commit()
        except IntegrityError as exc:
            await self.session.rollback()
            raise AppException(
                "Benefit code already exists.", status_code=409, error_code="BENEFIT_TYPE_EXISTS"
            ) from exc
        return bt

    async def approve_benefit_policy(self, benefit_type_id: UUID, actor: User) -> HrBenefitType:
        ensure_permission(actor, PERMISSION_HR_PAYROLL_SENSITIVE)
        ensure_permission(actor, PERMISSION_HR_PAYROLL_APPROVE)
        benefit = await self.session.get(HrBenefitType, benefit_type_id, with_for_update=True)
        if benefit is None or not benefit.is_active:
            raise NotFoundException("Benefit type")
        if (
            benefit.reimbursement_ceiling is None
            or benefit.reimbursement_currency is None
            or benefit.proposed_by_id is None
        ):
            raise AppException("Configure a ceiling and currency before approval.", status_code=409)
        if benefit.proposed_by_id == actor.id:
            raise PermissionDeniedException("Independent benefit policy approval")
        if benefit.approved_at is not None:
            if benefit.approved_by_id != actor.id:
                raise AppException("This benefit policy is already approved.", status_code=409)
            return benefit
        benefit.approved_by_id = actor.id
        benefit.approved_at = utc_now()
        await self.audit.record(
            action="hr.benefit_type.reimbursement_policy_approved",
            user_id=actor.id,
            entity_type="hr_benefit_types",
            entity_id=benefit.id,
        )
        await self._commit_and_refresh(benefit)
        return benefit

    async def list_benefit_types(self) -> tuple[list[HrBenefitType], int]:
        rows = list(
            await self.session.scalars(select(HrBenefitType).order_by(HrBenefitType.code.asc()))
        )
        return rows, len(rows)

    async def create_employee_benefit(
        self, payload: EmployeeBenefitCreateRequest, actor: User
    ) -> HrEmployeeBenefit:
        ensure_permission(actor, PERMISSION_HR_PAYROLL_SENSITIVE)
        await self._require_employee(payload.employee_id, for_update=True)
        benefit = await self.session.get(HrBenefitType, payload.benefit_type_id)
        if benefit is None or not benefit.is_active:
            raise NotFoundException("Benefit type")
        if benefit.reimbursement_ceiling is not None:
            self._approved_benefit_ceiling(benefit)
            if payload.effective_to is None:
                raise AppException("A capped benefit needs an end date.", status_code=422)
        if payload.effective_to is not None and payload.effective_to < payload.effective_from:
            raise AppException("Enter the benefit dates in order.", status_code=422)
        overlap = select(HrEmployeeBenefit.id).where(
            HrEmployeeBenefit.employee_id == payload.employee_id,
            HrEmployeeBenefit.benefit_type_id == payload.benefit_type_id,
            HrEmployeeBenefit.status == "active",
            or_(
                HrEmployeeBenefit.effective_to.is_(None),
                HrEmployeeBenefit.effective_to >= payload.effective_from,
            ),
        )
        if payload.effective_to is not None:
            overlap = overlap.where(HrEmployeeBenefit.effective_from <= payload.effective_to)
        if await self.session.scalar(overlap.limit(1)) is not None:
            raise AppException("This benefit overlaps existing coverage.", status_code=409)
        eb = HrEmployeeBenefit(**payload.model_dump())
        self.session.add(eb)
        await self.session.flush()
        await self.audit.record(
            action="hr.employee_benefit.assigned",
            user_id=actor.id,
            entity_type="hr_employee_benefits",
            entity_id=eb.id,
        )
        await self.session.commit()
        return eb

    async def list_employee_benefits(
        self, *, employee_id: UUID | None = None
    ) -> tuple[list[HrEmployeeBenefit], int]:
        stmt = select(HrEmployeeBenefit)
        if employee_id:
            stmt = stmt.where(HrEmployeeBenefit.employee_id == employee_id)
        rows = list(
            await self.session.scalars(stmt.order_by(HrEmployeeBenefit.effective_from.desc()))
        )
        return rows, len(rows)

    @staticmethod
    def _approved_benefit_ceiling(benefit: HrBenefitType) -> Decimal:
        if (
            not benefit.is_active
            or benefit.reimbursement_ceiling is None
            or benefit.reimbursement_ceiling <= 0
            or benefit.reimbursement_currency is None
            or benefit.proposed_by_id is None
            or benefit.approved_by_id is None
            or benefit.approved_by_id == benefit.proposed_by_id
            or benefit.approved_at is None
        ):
            raise AppException(
                "This benefit lacks an approved reimbursement ceiling.", status_code=409
            )
        return benefit.reimbursement_ceiling

    async def _ensure_benefit_coverage(
        self,
        assignment_id: UUID | None,
        employee_id: UUID,
        claim_type: str | None,
        claim_date: date,
        amount: Decimal,
        currency: str,
        *,
        exclude_claim_id: UUID | None = None,
        exclude_advance_id: UUID | None = None,
    ) -> None:
        # Submission, approval and benefit assignment all hold the employee lock.
        if assignment_id is None:
            raise AppException(
                "Reconcile the claim against approved benefit coverage.", status_code=409
            )
        row = (
            await self.session.execute(
                select(HrEmployeeBenefit, HrBenefitType)
                .join(HrBenefitType, HrBenefitType.id == HrEmployeeBenefit.benefit_type_id)
                .where(
                    HrEmployeeBenefit.id == assignment_id,
                    HrEmployeeBenefit.employee_id == employee_id,
                )
            )
        ).one_or_none()
        if row is None:
            raise NotFoundException("Benefit coverage")
        assignment, benefit = row
        ceiling = self._approved_benefit_ceiling(benefit)
        if (
            assignment.status != "active"
            or assignment.effective_to is None
            or not assignment.effective_from <= claim_date <= assignment.effective_to
            or (claim_type is not None and claim_type != benefit.code)
            or (claim_type is None and not benefit.allows_advances)
            or currency != benefit.reimbursement_currency
        ):
            raise AppException(
                "The request falls outside the approved benefit coverage.", status_code=409
            )
        totals = select(func.sum(HrReimbursementClaim.amount)).where(
            HrReimbursementClaim.benefit_assignment_id == assignment.id,
            HrReimbursementClaim.status.in_(("submitted", "approved", "paid")),
        )
        if exclude_claim_id is not None:
            totals = totals.where(HrReimbursementClaim.id != exclude_claim_id)
        reserved = await self.session.scalar(totals) or Decimal("0")
        advances = select(func.sum(HrEmployeeAdvance.amount)).where(
            HrEmployeeAdvance.benefit_assignment_id == assignment.id,
            HrEmployeeAdvance.status.in_(("submitted", "approved", "disbursed")),
        )
        if exclude_advance_id is not None:
            advances = advances.where(HrEmployeeAdvance.id != exclude_advance_id)
        open_principal = await self.session.scalar(advances) or Decimal("0")
        if reserved + open_principal + amount > ceiling:
            raise AppException(
                "The request exceeds the remaining coverage ceiling.",
                status_code=409,
                error_code="BENEFIT_CEILING_EXCEEDED",
            )

    async def _locked_advance(self, advance_id: UUID) -> tuple[HrEmployeeAdvance, HrEmployee]:
        employee_id = await self.session.scalar(
            select(HrEmployeeAdvance.employee_id).where(HrEmployeeAdvance.id == advance_id)
        )
        if employee_id is None:
            raise NotFoundException("Employee advance")
        employee = await self._require_employee(employee_id, for_update=True)
        advance = await self.session.get(HrEmployeeAdvance, advance_id, populate_existing=True)
        if advance is None:
            raise NotFoundException("Employee advance")
        return advance, employee

    @staticmethod
    def _advance_digest(advance: HrEmployeeAdvance) -> str | None:
        if advance.status not in {"approved", "disbursed", "settled"} or advance.decided_at is None:
            return None
        payload = [
            "employee-advance-v1",
            str(advance.id),
            str(advance.employee_id),
            str(advance.benefit_assignment_id),
            format(advance.amount, ".2f"),
            advance.currency,
            advance.decided_at.astimezone(UTC).isoformat(),
        ]
        return hashlib.sha256(json.dumps(payload, separators=(",", ":")).encode()).hexdigest()

    async def _advance_response(self, advance: HrEmployeeAdvance) -> EmployeeAdvanceResponse:
        await self.session.flush()
        recoveries = list(
            await self.session.scalars(
                select(HrAdvanceRecovery)
                .where(HrAdvanceRecovery.advance_id == advance.id)
                .order_by(HrAdvanceRecovery.occurred_on, HrAdvanceRecovery.id)
            )
        )
        recovered = sum((item.amount for item in recoveries), Decimal("0.00"))
        return EmployeeAdvanceResponse(
            id=advance.id,
            employee_id=advance.employee_id,
            benefit_assignment_id=advance.benefit_assignment_id,
            requested_on=advance.requested_on,
            amount=advance.amount,
            currency=advance.currency,
            status=advance.status,
            submitted_by_id=advance.submitted_by_id,
            decided_by_id=advance.decided_by_id,
            decided_at=advance.decided_at,
            payable_sha256=self._advance_digest(advance),
            disbursed_on=advance.disbursed_on,
            disbursement_reference=advance.disbursement_reference,
            recovered=recovered,
            outstanding=advance.amount - recovered if advance.disbursed_on else Decimal("0.00"),
            recoveries=[EmployeeAdvanceRecovery.model_validate(item) for item in recoveries],
        )

    async def _record_advance(
        self, advance: HrEmployeeAdvance, actor: User, action: str
    ) -> EmployeeAdvanceResponse:
        await self.audit.record(
            action=f"hr.advance.{action}",
            user_id=actor.id,
            entity_type="hr_employee_advances",
            entity_id=advance.id,
        )
        result = await self._advance_response(advance)
        await self.session.commit()
        return result

    async def submit_advance(
        self, payload: EmployeeAdvanceRequest, actor: User, *, idempotency_key: str | None
    ) -> EmployeeAdvanceResponse:
        ensure_permission(actor, PERMISSION_HR_PAYROLL_SENSITIVE)
        key = validate_key(idempotency_key)
        if key is None:
            raise AppException("Supply an Idempotency-Key for this advance.", status_code=422)
        await self._require_employee(payload.employee_id, for_update=True)
        route = "hr.employee_advance"
        existing_id = await resolve_or_reserve(self.session, key=key, user_id=actor.id, route=route)
        if existing_id is not None:
            prior = await self.session.get(HrEmployeeAdvance, existing_id)
            if prior is None or any(
                getattr(prior, field) != value for field, value in payload.model_dump().items()
            ):
                raise AppException("This key belongs to a different advance.", status_code=409)
            return await self._advance_response(prior)
        await self._ensure_benefit_coverage(
            payload.benefit_assignment_id,
            payload.employee_id,
            None,
            payload.requested_on,
            payload.amount,
            payload.currency,
        )
        advance = HrEmployeeAdvance(**payload.model_dump(), submitted_by_id=actor.id)
        self.session.add(advance)
        await self.session.flush()
        await bind(
            self.session,
            key=key,
            user_id=actor.id,
            route=route,
            resource_type="hr_employee_advance",
            resource_id=advance.id,
        )
        return await self._record_advance(advance, actor, "submitted")

    async def read_advance(self, advance_id: UUID, actor: User) -> EmployeeAdvanceResponse:
        ensure_permission(actor, PERMISSION_HR_PAYROLL_SENSITIVE)
        advance, _ = await self._locked_advance(advance_id)
        return await self._record_advance(advance, actor, "read")

    async def list_advances(
        self, employee_id: UUID, actor: User, *, limit: int, offset: int
    ) -> tuple[list[EmployeeAdvanceResponse], int]:
        ensure_permission(actor, PERMISSION_HR_PAYROLL_SENSITIVE)
        await self._require_employee(employee_id, for_update=True)
        scope = HrEmployeeAdvance.employee_id == employee_id
        rows = list(
            await self.session.scalars(
                select(HrEmployeeAdvance)
                .where(scope)
                .order_by(HrEmployeeAdvance.created_at.desc(), HrEmployeeAdvance.id)
                .limit(limit)
                .offset(offset)
            )
        )
        total = await self.session.scalar(
            select(func.count()).select_from(HrEmployeeAdvance).where(scope)
        )
        await self.audit.record(
            action="hr.advance.listed",
            user_id=actor.id,
            entity_type="hr_employees",
            entity_id=employee_id,
        )
        items = [await self._advance_response(row) for row in rows]
        await self.session.commit()
        return items, total or 0

    async def decide_advance(
        self, advance_id: UUID, payload: EmployeeAdvanceDecision, actor: User
    ) -> EmployeeAdvanceResponse:
        ensure_permission(actor, PERMISSION_HR_PAYROLL_SENSITIVE)
        ensure_permission(actor, PERMISSION_HR_PAYROLL_APPROVE)
        advance, employee = await self._locked_advance(advance_id)
        if actor.id in {advance.submitted_by_id, employee.user_id}:
            raise PermissionDeniedException("Independent advance approval")
        if advance.status != "submitted":
            raise AppException("Only submitted advances can be decided.", status_code=409)
        if payload.decision == "approved":
            await self._ensure_benefit_coverage(
                advance.benefit_assignment_id,
                advance.employee_id,
                None,
                advance.requested_on,
                advance.amount,
                advance.currency,
                exclude_advance_id=advance.id,
            )
        advance.status = payload.decision
        advance.decided_by_id = actor.id
        advance.decided_at = utc_now()
        return await self._record_advance(advance, actor, payload.decision)

    async def disburse_advance(
        self, advance_id: UUID, payload: EmployeeAdvanceDisbursement, actor: User
    ) -> EmployeeAdvanceResponse:
        ensure_permission(actor, PERMISSION_HR_PAYROLL_SENSITIVE)
        ensure_permission(actor, PERMISSION_HR_PAYROLL_APPROVE)
        advance, employee = await self._locked_advance(advance_id)
        if actor.id in {advance.submitted_by_id, advance.decided_by_id, employee.user_id}:
            raise PermissionDeniedException("Independent advance disbursement confirmation")
        reference = payload.reference.strip()
        if (
            not reference
            or payload.expected_payable_sha256 != self._advance_digest(advance)
            or (payload.amount, payload.currency) != (advance.amount, advance.currency)
        ):
            raise AppException("Disbursement must match the approved advance.", status_code=409)
        if advance.status in {"disbursed", "settled"} and (
            advance.disbursement_reference,
            advance.disbursed_on,
        ) == (reference, payload.occurred_on):
            return await self._advance_response(advance)
        approval_date = (
            advance.decided_at.astimezone(ZoneInfo(get_settings().business_timezone)).date()
            if advance.decided_at
            else None
        )
        if (
            advance.status != "approved"
            or approval_date is None
            or not max(advance.requested_on, approval_date)
            <= payload.occurred_on
            <= business_today()
        ):
            raise AppException("The advance cannot be disbursed on this date.", status_code=409)
        advance.status = "disbursed"
        advance.disbursement_reference = reference
        advance.disbursed_on = payload.occurred_on
        return await self._record_advance(advance, actor, "disbursement_recorded")

    async def recover_advance(
        self, advance_id: UUID, payload: EmployeeAdvancePayment, actor: User
    ) -> EmployeeAdvanceResponse:
        ensure_permission(actor, PERMISSION_HR_PAYROLL_SENSITIVE)
        ensure_permission(actor, PERMISSION_HR_PAYROLL_APPROVE)
        advance, employee = await self._locked_advance(advance_id)
        if actor.id in {advance.submitted_by_id, advance.decided_by_id, employee.user_id}:
            raise PermissionDeniedException("Independent advance recovery confirmation")
        reference = payload.reference.strip()
        if (
            not reference
            or reference == advance.disbursement_reference
            or advance.disbursed_on is None
            or not advance.disbursed_on <= payload.occurred_on <= business_today()
            or payload.currency != advance.currency
        ):
            raise AppException(
                "Repayment must match the funded advance and currency.", status_code=409
            )
        current = await self._advance_response(advance)
        prior = next((item for item in current.recoveries if item.reference == reference), None)
        if prior is not None:
            if (prior.amount, prior.occurred_on) == (payload.amount, payload.occurred_on):
                return current
            raise AppException(
                "This repayment reference already has different details.", status_code=409
            )
        if advance.status != "disbursed" or payload.amount > current.outstanding:
            raise AppException("The repayment exceeds the outstanding principal.", status_code=409)
        self.session.add(
            HrAdvanceRecovery(
                advance_id=advance.id,
                recorded_by_id=actor.id,
                reference=reference,
                occurred_on=payload.occurred_on,
                amount=payload.amount,
            )
        )
        if payload.amount == current.outstanding:
            advance.status = "settled"
        return await self._record_advance(advance, actor, "repayment_recorded")

    async def create_reimbursement(
        self,
        payload: ReimbursementCreateRequest,
        actor: User,
        *,
        idempotency_key: str | None,
        own_claim: bool = False,
    ) -> HrReimbursementClaim:
        ensure_permission(actor, PERMISSION_HR_PAYROLL_SENSITIVE)
        key = validate_key(idempotency_key)
        if key is None:
            raise AppException("Supply an Idempotency-Key for this claim.", status_code=422)
        emp = (
            await self._require_employee(payload.employee_id, for_update=True)
            if payload.employee_id and not own_claim
            else await self._employee_for_user(actor, for_update=True)
        )
        if own_claim and payload.employee_id not in {None, emp.id}:
            raise NotFoundException("Employee")
        route = "hr.reimbursement.self" if own_claim else "hr.reimbursement"
        claim_type = payload.claim_type.strip().upper()
        existing_id = await resolve_or_reserve(self.session, key=key, user_id=actor.id, route=route)
        if existing_id is not None:
            existing = await self.session.get(HrReimbursementClaim, existing_id)
            if (
                existing is None
                or existing.employee_id != emp.id
                or existing.receipt_version_id is None
            ):
                raise AppException("This key belongs to a different claim.", status_code=409)
            existing_version = await self.session.get(
                HrDocumentVersion, existing.receipt_version_id
            )
            if (
                existing_version is None
                or existing_version.document_id != payload.receipt_document_id
                or existing_version.version_number != payload.receipt_version_number
                or existing.benefit_assignment_id != payload.benefit_assignment_id
                or (
                    existing.claim_type,
                    existing.claim_date,
                    existing.amount,
                    existing.currency,
                    existing.description,
                )
                != (
                    claim_type,
                    payload.claim_date,
                    payload.amount,
                    payload.currency,
                    payload.description,
                )
            ):
                raise AppException("This key belongs to a different claim.", status_code=409)
            return existing

        await self._ensure_benefit_coverage(
            payload.benefit_assignment_id,
            emp.id,
            claim_type,
            payload.claim_date,
            payload.amount,
            payload.currency,
        )
        document = await self._get_hr_document(payload.receipt_document_id, for_update=True)
        if (
            document.employee_id != emp.id
            or document.category != "compensation"
            or document.document_type != "reimbursement_receipt"
            or document.status != "active"
        ):
            raise NotFoundException("Reimbursement receipt")
        self._ensure_hr_doc_access(document, actor)
        receipt = await self.session.scalar(
            select(HrDocumentVersion).where(
                HrDocumentVersion.document_id == document.id,
                HrDocumentVersion.version_number == payload.receipt_version_number,
                HrDocumentVersion.status == "active",
            )
        )
        if receipt is None or document.current_version != payload.receipt_version_number:
            raise AppException("Select the current approved receipt version.", status_code=409)
        already_claimed = await self.session.scalar(
            select(HrReimbursementClaim.id)
            .outerjoin(
                HrDocumentVersion, HrDocumentVersion.id == HrReimbursementClaim.receipt_version_id
            )
            .where(
                HrReimbursementClaim.employee_id == emp.id,
                HrReimbursementClaim.status.in_(("submitted", "approved", "paid")),
                or_(
                    HrReimbursementClaim.receipt_document_id == document.id,
                    HrDocumentVersion.sha256_checksum == receipt.sha256_checksum,
                ),
            )
            .limit(1)
        )
        if already_claimed is not None:
            raise AppException("This receipt is already associated with a claim.", status_code=409)
        claim = HrReimbursementClaim(
            claim_code=f"CLM-{uuid4().hex[:8].upper()}",
            employee_id=emp.id,
            claim_type=claim_type,
            benefit_assignment_id=payload.benefit_assignment_id,
            claim_date=payload.claim_date,
            amount=payload.amount,
            currency=payload.currency,
            description=payload.description,
            receipt_document_id=payload.receipt_document_id,
            receipt_version_id=receipt.id,
            submitted_by_id=actor.id,
        )
        self.session.add(claim)
        await self.session.flush()
        await bind(
            self.session,
            key=key,
            user_id=actor.id,
            route=route,
            resource_type="hr_reimbursement_claim",
            resource_id=claim.id,
        )
        await self.audit.record(
            action="hr.reimbursement.submitted",
            user_id=actor.id,
            entity_type="hr_reimbursement_claims",
            entity_id=claim.id,
        )
        await self._commit_and_refresh(claim)
        return claim

    @staticmethod
    def _reimbursement_payable(claim: HrReimbursementClaim) -> ReimbursementPayableResponse:
        if (
            claim.status not in {"approved", "paid"}
            or claim.submitted_by_id is None
            or claim.receipt_version_id is None
            or claim.decided_at is None
            or claim.decided_by_id is None
            or claim.decided_by_id == claim.submitted_by_id
        ):
            raise AppException(
                "Only independently approved claims have a payable.", status_code=409
            )
        reference = ReimbursementPayable(
            claim_id=claim.id,
            payable_reference=claim.claim_code,
            employee_id=claim.employee_id,
            amount=claim.amount,
            currency=claim.currency,
            approved_at=claim.decided_at.astimezone(UTC),
        )
        encoded = json.dumps(
            reference.model_dump(mode="json"),
            sort_keys=True,
            separators=(",", ":"),
            ensure_ascii=False,
            allow_nan=False,
        ).encode("utf-8")
        return ReimbursementPayableResponse(
            reference=reference,
            reference_sha256=hashlib.sha256(encoded).hexdigest(),
            status="paid" if claim.status == "paid" else "approved",
        )

    async def read_reimbursement_payable(
        self, claim_id: UUID, actor: User
    ) -> ReimbursementPayableResponse:
        ensure_permission(actor, PERMISSION_HR_PAYROLL_SENSITIVE)
        claim = await self.session.get(HrReimbursementClaim, claim_id)
        if claim is None:
            raise NotFoundException("Reimbursement claim")
        result = self._reimbursement_payable(claim)
        await self.audit.record(
            action="hr.reimbursement.payable_read",
            user_id=actor.id,
            entity_type="hr_reimbursement_claims",
            entity_id=claim.id,
        )
        await self.session.commit()
        return result

    async def decide_reimbursement(
        self, claim_id: UUID, payload: ReimbursementDecisionRequest, actor: User
    ) -> HrReimbursementClaim:
        ensure_permission(actor, PERMISSION_HR_PAYROLL_APPROVE)
        employee_id = await self.session.scalar(
            select(HrReimbursementClaim.employee_id).where(HrReimbursementClaim.id == claim_id)
        )
        if employee_id is None:
            raise NotFoundException("Reimbursement claim")
        employee = await self._require_employee(employee_id, for_update=True)
        claim = await self.session.get(HrReimbursementClaim, claim_id, populate_existing=True)
        if claim is None:
            raise NotFoundException("Reimbursement claim")
        if actor.id in {employee.user_id, claim.submitted_by_id}:
            raise PermissionDeniedException("Independent reimbursement review")
        if claim.submitted_by_id is None or claim.receipt_version_id is None:
            raise AppException(
                "Reconcile the legacy claim evidence before review.", status_code=409
            )
        reference = (payload.settlement_reference or "").strip()
        if payload.decision == "paid":
            ensure_permission(actor, PERMISSION_HR_PAYROLL_SENSITIVE)
            if (
                not reference
                or payload.expected_payable_sha256 is None
                or payload.settled_amount is None
                or payload.settled_currency is None
            ):
                raise AppException(
                    "Supply the external reference, reviewed payable digest, amount and currency.",
                    status_code=422,
                )
            if actor.id == claim.decided_by_id:
                raise PermissionDeniedException("Independent settlement confirmation")
            payable = self._reimbursement_payable(claim)
            if payable.reference_sha256 != payload.expected_payable_sha256:
                raise AppException(
                    "The payable does not match the reviewed reference.", status_code=409
                )
            if (payload.settled_amount, payload.settled_currency) != (claim.amount, claim.currency):
                raise AppException(
                    "The external amount and currency must match the payable.", status_code=409
                )
            if claim.status == "paid" and claim.settlement_reference == reference:
                return claim
            if claim.status != "approved" or claim.decided_by_id is None:
                raise AppException("Only approved claims may be settled.", status_code=409)
            claim.settlement_reference = reference
        else:
            if any(
                value is not None
                for value in (
                    payload.settlement_reference,
                    payload.expected_payable_sha256,
                    payload.settled_amount,
                    payload.settled_currency,
                )
            ):
                raise AppException(
                    "Settlement references require a paid decision.", status_code=422
                )
            if claim.status != "submitted":
                raise AppException("Only submitted claims may be decided.", status_code=409)
            if payload.decision == "approved":
                await self._ensure_benefit_coverage(
                    claim.benefit_assignment_id,
                    claim.employee_id,
                    claim.claim_type,
                    claim.claim_date,
                    claim.amount,
                    claim.currency,
                    exclude_claim_id=claim.id,
                )
            if payload.decision in {"rejected", "cancelled"} and not (payload.notes or "").strip():
                raise AppException("Provide a reason for this decision.", status_code=422)
            claim.decided_by_id = actor.id
            claim.decided_at = utc_now()
            claim.decision_notes = payload.notes
        claim.status = payload.decision
        await self.audit.record(
            action=f"hr.reimbursement.{payload.decision}",
            user_id=actor.id,
            entity_type="hr_reimbursement_claims",
            entity_id=claim.id,
        )
        await self._commit_and_refresh(claim)
        return claim

    async def list_reimbursements(
        self, *, employee_id: UUID | None = None, limit: int | None = None, offset: int = 0
    ) -> tuple[list[HrReimbursementClaim], int]:
        stmt = select(HrReimbursementClaim)
        if employee_id:
            stmt = stmt.where(HrReimbursementClaim.employee_id == employee_id)
        total = await self.session.scalar(select(func.count()).select_from(stmt.subquery()))
        rows = list(
            await self.session.scalars(
                stmt.order_by(HrReimbursementClaim.claim_date.desc(), HrReimbursementClaim.id)
                .limit(limit)
                .offset(offset)
            )
        )
        return rows, total or 0

    @staticmethod
    def _compensation_term_response(
        term: HrCompensationTerm, *, current: bool = False, reveal_sensitive: bool = False
    ) -> CompensationTermResponse:
        allowances = decrypt_hr_value(term.allowances_encrypted) if reveal_sensitive else None
        return CompensationTermResponse(
            id=term.id,
            employee_id=term.employee_id,
            effective_from=term.effective_from,
            pay_frequency=term.pay_frequency,
            currency=term.currency,
            base_salary_masked="********",
            base_salary_plain=decrypt_hr_value(term.base_salary_encrypted)
            if reveal_sensitive
            else None,
            allowances_json=json.loads(allowances) if allowances else None,
            is_current=current,
            approval_status=term.approval_status,
            proposed_by_id=term.proposed_by_id,
            rejection_reason=decrypt_hr_value(term.rejection_reason_encrypted)
            if reveal_sensitive
            else None,
            approved_by_id=term.approved_by_id,
            approved_at=term.approved_at,
            created_at=term.created_at,
        )

    async def _compensation_history(self, employee_id: UUID) -> list[HrCompensationTerm]:
        return list(
            await self.session.scalars(
                select(HrCompensationTerm)
                .where(HrCompensationTerm.employee_id == employee_id)
                .order_by(HrCompensationTerm.effective_from.desc(), HrCompensationTerm.id)
            )
        )

    @staticmethod
    def _current_compensation(terms: list[HrCompensationTerm]) -> UUID | None:
        today = business_today()
        effective = [
            term
            for term in terms
            if term.approval_status == "approved"
            and term.approved_at is not None
            and term.approved_by_id is not None
            and term.effective_from <= today
        ]
        if not effective or (
            len(effective) > 1 and effective[0].effective_from == effective[1].effective_from
        ):
            return None
        return effective[0].id

    async def create_compensation_term(
        self, payload: CompensationTermCreateRequest, actor: User
    ) -> CompensationTermResponse:
        ensure_permission(actor, PERMISSION_HR_PAYROLL_SENSITIVE)
        await self._require_employee(payload.employee_id, for_update=True)
        terms = await self._compensation_history(payload.employee_id)
        if any(term.approval_status == "proposed" for term in terms):
            raise AppException("Decide the existing compensation proposal first.", status_code=409)
        if any(
            term.approval_status == "approved" and term.effective_from == payload.effective_from
            for term in terms
        ):
            raise AppException("A compensation term already starts on this date.", status_code=409)

        term = HrCompensationTerm(
            employee_id=payload.employee_id,
            effective_from=payload.effective_from,
            pay_frequency=payload.pay_frequency,
            currency=payload.currency,
            base_salary_encrypted=encrypt_hr_value(payload.base_salary) or "",
            base_salary_masked="********",
            allowances_encrypted=encrypt_hr_value(json.dumps(payload.allowances_json))
            if payload.allowances_json
            else None,
            is_current=False,
            approval_status="proposed",
            proposed_by_id=actor.id,
        )
        self.session.add(term)
        await self.session.flush()
        await self.audit.record(
            action="hr.compensation.proposed",
            user_id=actor.id,
            entity_type="hr_compensation_terms",
            entity_id=term.id,
        )
        await self.session.commit()
        return self._compensation_term_response(term)

    async def decide_compensation_term(
        self, term_id: UUID, payload: CompensationTermDecisionRequest, actor: User
    ) -> CompensationTermResponse:
        ensure_permission(actor, PERMISSION_HR_PAYROLL_APPROVE)
        ensure_permission(actor, PERMISSION_HR_PAYROLL_SENSITIVE)
        employee_id = await self.session.scalar(
            select(HrCompensationTerm.employee_id).where(HrCompensationTerm.id == term_id)
        )
        if employee_id is None:
            raise NotFoundException("Compensation term")
        if payload.decision == "approve":
            # Payroll also locks periods before locking employees.
            await lock_payroll_periods(self.session)
        employee = await self._require_employee(employee_id, for_update=True)
        terms = await self._compensation_history(employee.id)
        term = next((record for record in terms if record.id == term_id), None)
        if term is None:
            raise NotFoundException("Compensation term")
        if term.proposed_by_id is None or actor.id in {term.proposed_by_id, employee.user_id}:
            raise PermissionDeniedException("Independent compensation review")
        if term.approval_status != "proposed":
            raise AppException("Only proposed compensation terms can be decided.", status_code=409)

        if payload.decision == "approve":
            approved = [record for record in terms if record.approval_status == "approved"]
            if any(record.effective_from == term.effective_from for record in approved):
                raise AppException(
                    "A compensation term already starts on this date.", status_code=409
                )
            locked_period = (
                select(HrPayrollPeriod.id)
                .join(HrPayrollRun, HrPayrollRun.payroll_period_id == HrPayrollPeriod.id)
                .join(HrPayrollLine, HrPayrollLine.payroll_run_id == HrPayrollRun.id)
                .where(
                    HrPayrollLine.employee_id == employee.id,
                    HrPayrollRun.status == "approved",
                    HrPayrollPeriod.status == "locked",
                    HrPayrollPeriod.period_end >= term.effective_from,
                )
                .limit(1)
            )
            next_start = min(
                (
                    row.effective_from
                    for row in approved
                    if row.effective_from > term.effective_from
                ),
                default=None,
            )
            if next_start is not None:
                locked_period = locked_period.where(HrPayrollPeriod.period_start < next_start)
            if await self.session.scalar(locked_period):
                raise AppException(
                    "This change affects locked payroll. Use an approved correction process.",
                    status_code=409,
                )
            term.approval_status = "approved"
            term.approved_by_id = actor.id
            term.approved_at = utc_now()
            # Keep the stored latest-approval flag compatible with existing rows.
            latest = next(row for row in terms if row.approval_status == "approved")
            for row in terms:
                row.is_current = row.id == latest.id
        else:
            if not (payload.reason or "").strip():
                raise AppException("Give a reason for rejecting the proposal.", status_code=422)
            term.rejection_reason_encrypted = encrypt_hr_value(payload.reason)
            term.approval_status = "rejected"

        await self.audit.record(
            action=f"hr.compensation.{term.approval_status}",
            user_id=actor.id,
            entity_type="hr_compensation_terms",
            entity_id=term.id,
        )
        await self.session.commit()
        return self._compensation_term_response(
            term, current=term.id == self._current_compensation(terms)
        )

    async def list_compensation_terms(
        self,
        *,
        employee_id: UUID,
        actor: User,
        reveal_sensitive: bool = False,
        term_id: UUID | None = None,
    ) -> tuple[list[CompensationTermResponse], int]:
        ensure_permission(actor, PERMISSION_HR_PAYROLL_SENSITIVE)
        rows = await self._compensation_history(employee_id)
        current = self._current_compensation(rows)
        if term_id is not None:
            rows = [row for row in rows if row.id == term_id]
            if not rows:
                raise NotFoundException("Compensation term")
        if reveal_sensitive:
            await self.audit.record(
                action="hr.compensation.revealed",
                user_id=actor.id,
                entity_type="hr_compensation_terms" if term_id else "hr_employees",
                entity_id=term_id or employee_id,
            )
            await self.session.commit()
        return [
            self._compensation_term_response(
                term, current=term.id == current, reveal_sensitive=reveal_sensitive
            )
            for term in rows
        ], len(rows)

    async def create_payroll_policy(
        self, payload: PayrollPolicyCreateRequest, actor: User
    ) -> HrPayrollPolicy:
        pol = HrPayrollPolicy(
            code=payload.code.strip(),
            name=payload.name.strip(),
            rules_json=payload.rules_json,
            controlled_record=(
                payload.controlled_record.model_dump(mode="json")
                if payload.controlled_record
                else None
            ),
            is_approved=False,
            approved_by_id=actor.id,
        )
        self.session.add(pol)
        try:
            await self.session.flush()
            await self.audit.record(
                action="hr.payroll_policy.drafted",
                user_id=actor.id,
                entity_type="hr_payroll_policies",
                entity_id=pol.id,
            )
            await self.session.commit()
        except IntegrityError as exc:
            await self.session.rollback()
            raise AppException(
                "Payroll policy code already exists.",
                status_code=409,
                error_code="PAYROLL_POLICY_EXISTS",
            ) from exc
        return pol

    async def get_payroll_policy(self, policy_id: UUID) -> HrPayrollPolicy:
        policy = await self.session.get(HrPayrollPolicy, policy_id)
        if policy is None:
            raise NotFoundException("Payroll policy")
        return policy

    async def _lock_payroll_policy(self, policy_id: UUID) -> HrPayrollPolicy:
        pol = await self.session.scalar(
            select(HrPayrollPolicy).where(HrPayrollPolicy.id == policy_id).with_for_update()
        )
        if pol is None:
            raise NotFoundException("Payroll policy")
        return pol

    async def update_payroll_policy_draft(
        self, policy_id: UUID, payload: PayrollPolicyDraftUpdateRequest, actor: User
    ) -> HrPayrollPolicy:
        pol = await self._lock_payroll_policy(policy_id)
        if pol.approved_by_id != actor.id:
            raise PermissionDeniedException("edit this payroll policy")
        if pol.is_approved or pol.controlled_record is None:
            raise AppException(
                "Only pending controlled payroll policies can be edited.", status_code=409
            )
        if pol.updated_at != payload.expected_updated_at:
            raise AppException("The payroll policy changed. Reload the draft.", status_code=409)
        name = payload.name.strip()
        if len(name) < 2:
            raise AppException("Enter a policy name of at least two characters.", status_code=422)
        pol.name = name
        pol.rules_json = payload.rules_json
        pol.controlled_record = payload.controlled_record.model_dump(mode="json")
        pol.updated_at = utc_now()
        await self.audit.record(
            action="hr.payroll_policy.draft_updated",
            user_id=actor.id,
            entity_type="hr_payroll_policies",
            entity_id=pol.id,
        )
        await self._commit_and_refresh(pol)
        return pol

    async def approve_payroll_policy(
        self, policy_id: UUID, actor: User, *, expected_updated_at: datetime | None = None
    ) -> HrPayrollPolicy:
        pol = await self._lock_payroll_policy(policy_id)
        if not pol.rules_json:
            raise AppException(
                "Payroll policy rules_json must define calculation formulas before approval.",
                status_code=422,
                error_code="PAYROLL_RULES_EMPTY",
            )
        if pol.approved_by_id == actor.id:
            raise AppException(
                "Payroll policy approval requires a second distinct approver.",
                status_code=409,
                error_code="DUAL_APPROVAL_REQUIRED",
            )
        if pol.is_approved:
            if pol.second_approved_by_id == actor.id:
                return pol
            raise AppException("This payroll policy already has a final approval.", status_code=409)
        if pol.controlled_record is not None and pol.updated_at != expected_updated_at:
            raise AppException(
                "The payroll policy changed or its review version is missing. Open it again.",
                status_code=409,
                error_code="PAYROLL_POLICY_REVIEW_STALE",
            )
        validate_payroll_policy(pol)
        pol.second_approved_by_id = actor.id
        pol.is_approved = True
        pol.approved_at = utc_now()
        await self.audit.record(
            action="hr.payroll_policy.approved",
            user_id=actor.id,
            entity_type="hr_payroll_policies",
            entity_id=pol.id,
        )
        await self._commit_and_refresh(pol)
        return pol

    async def list_payroll_policies(self) -> tuple[list[HrPayrollPolicy], int]:
        rows = list(
            await self.session.scalars(
                select(HrPayrollPolicy).order_by(HrPayrollPolicy.created_at.desc())
            )
        )
        return rows, len(rows)

    async def create_payroll_period(
        self, payload: PayrollPeriodCreateRequest, actor: User
    ) -> HrPayrollPeriod:
        if not payload.period_start <= payload.period_end <= payload.pay_date:
            raise AppException(
                "Enter the payroll start, end and pay dates in order.", status_code=422
            )
        await lock_payroll_periods(self.session)
        if await self.session.scalar(
            select(HrPayrollPeriod.id)
            .where(
                HrPayrollPeriod.period_start <= payload.period_end,
                HrPayrollPeriod.period_end >= payload.period_start,
            )
            .limit(1)
        ):
            raise AppException("This payroll period overlaps an existing period.", status_code=409)
        period = HrPayrollPeriod(**payload.model_dump())
        self.session.add(period)
        try:
            await self.session.flush()
            await self.audit.record(
                action="hr.payroll_period.created",
                user_id=actor.id,
                entity_type="hr_payroll_periods",
                entity_id=period.id,
            )
            await self.session.commit()
        except IntegrityError as exc:
            await self.session.rollback()
            raise AppException(
                "Payroll period code already exists.",
                status_code=409,
                error_code="PAYROLL_PERIOD_EXISTS",
            ) from exc
        return period

    async def list_payroll_periods(self) -> tuple[list[HrPayrollPeriod], int]:
        rows = list(
            await self.session.scalars(
                select(HrPayrollPeriod).order_by(HrPayrollPeriod.period_start.desc())
            )
        )
        return rows, len(rows)

    async def create_payroll_run(
        self, payload: PayrollRunCreateRequest, actor: User
    ) -> HrPayrollRun:
        period = await self.session.scalar(
            select(HrPayrollPeriod)
            .where(HrPayrollPeriod.id == payload.payroll_period_id)
            .with_for_update()
        )
        if period is None:
            raise NotFoundException("Payroll period")
        if period.status != "open":
            raise AppException("The payroll period is locked.", status_code=409)
        if (
            payload.policy_id is not None
            and await self.session.get(HrPayrollPolicy, payload.policy_id) is None
        ):
            raise NotFoundException("Payroll policy")
        run = HrPayrollRun(
            payroll_period_id=payload.payroll_period_id,
            policy_id=payload.policy_id,
            status="draft",
            prepared_by_id=actor.id,
            notes=payload.notes,
        )
        self.session.add(run)
        await self.session.flush()
        await self.audit.record(
            action="hr.payroll_run.created",
            user_id=actor.id,
            entity_type="hr_payroll_runs",
            entity_id=run.id,
        )
        await self._commit_and_refresh(run)
        return run

    async def list_payroll_runs(self) -> tuple[list[HrPayrollRun], int]:
        stmt = select(HrPayrollRun).order_by(HrPayrollRun.created_at.desc())
        rows = list(await self.session.scalars(stmt))
        return rows, len(rows)

    # --- Restricted Cases (HR-024) ---

    async def create_hr_case(self, payload: HrCaseCreateRequest, actor: User) -> HrCaseResponse:
        case = HrCase(
            case_code=payload.case_code.strip(),
            employee_id=payload.employee_id,
            case_type=payload.case_type,
            severity=payload.severity,
            title=payload.title.strip(),
            details_encrypted=encrypt_hr_value(payload.details) or "",
            status="open",
            opened_by_id=actor.id,
        )
        self.session.add(case)
        try:
            await self.session.flush()
            await self.audit.record(
                action="hr.case.opened",
                user_id=actor.id,
                entity_type="hr_cases",
                entity_id=case.id,
                new_values={"case_code": case.case_code, "case_type": case.case_type},
            )
            await self.session.commit()
        except IntegrityError as exc:
            await self.session.rollback()
            raise AppException(
                "Case code already exists.", status_code=409, error_code="CASE_EXISTS"
            ) from exc
        return HrCaseResponse(
            id=case.id,
            case_code=case.case_code,
            employee_id=case.employee_id,
            case_type=case.case_type,
            severity=case.severity,
            title=case.title,
            details_plain=decrypt_hr_value(case.details_encrypted),
            status=case.status,
            opened_by_id=case.opened_by_id,
            closed_by_id=case.closed_by_id,
            closed_at=case.closed_at,
            resolution_notes=case.resolution_notes,
            created_at=case.created_at,
        )

    async def list_hr_cases(self) -> tuple[list[HrCaseResponse], int]:
        rows = list(await self.session.scalars(select(HrCase).order_by(HrCase.created_at.desc())))
        return [
            HrCaseResponse(
                id=c.id,
                case_code=c.case_code,
                employee_id=c.employee_id,
                case_type=c.case_type,
                severity=c.severity,
                title=c.title,
                details_plain=decrypt_hr_value(c.details_encrypted),
                status=c.status,
                opened_by_id=c.opened_by_id,
                closed_by_id=c.closed_by_id,
                closed_at=c.closed_at,
                resolution_notes=c.resolution_notes,
                created_at=c.created_at,
            )
            for c in rows
        ], len(rows)

    async def close_hr_case(
        self, case_id: UUID, payload: HrCaseCloseRequest, actor: User
    ) -> HrCaseResponse:
        case = await self.session.scalar(select(HrCase).where(HrCase.id == case_id))
        if case is None:
            raise NotFoundException("HR Case")
        case.status = payload.status
        case.resolution_notes = payload.resolution_notes
        if payload.status == "closed":
            case.closed_by_id = actor.id
            case.closed_at = utc_now()
        await self.audit.record(
            action=f"hr.case.{payload.status}",
            user_id=actor.id,
            entity_type="hr_cases",
            entity_id=case.id,
        )
        await self._commit_and_refresh(case)
        return HrCaseResponse(
            id=case.id,
            case_code=case.case_code,
            employee_id=case.employee_id,
            case_type=case.case_type,
            severity=case.severity,
            title=case.title,
            details_plain=decrypt_hr_value(case.details_encrypted),
            status=case.status,
            opened_by_id=case.opened_by_id,
            closed_by_id=case.closed_by_id,
            closed_at=case.closed_at,
            resolution_notes=case.resolution_notes,
            created_at=case.created_at,
        )
