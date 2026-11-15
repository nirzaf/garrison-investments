import asyncio
from datetime import date, datetime, timedelta
from decimal import Decimal
from io import BytesIO
from pathlib import Path
from string import Formatter
from typing import Any
from uuid import UUID, uuid4
from zoneinfo import ZoneInfo

from fastapi import UploadFile
from minio import Minio
from sqlalchemy import case, false, func, or_, select, text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.sql.elements import ColumnElement

from app.config import get_settings
from app.models.hr import (
    HrAccessRequest,
    HrApplication,
    HrAttendanceCorrection,
    HrAttendanceEntry,
    HrBenefitType,
    HrCandidate,
    HrCase,
    HrCertification,
    HrClearanceStep,
    HrCompensationTerm,
    HrDocument,
    HrDocumentVersion,
    HrEmployee,
    HrEmployeeBenefit,
    HrEmploymentHistory,
    HrGoal,
    HrHoliday,
    HrInterview,
    HrLeaveLedger,
    HrLeavePolicy,
    HrLeaveRequest,
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
    HrServiceRequest,
    HrShiftAssignment,
    HrTimesheet,
    HrTrainingCourse,
    HrTrainingEnrollment,
    HrWorkCalendar,
)
from app.models.project import Project
from app.models.user import User
from app.schemas.hr import (
    ApplicationCreateRequest,
    ApplicationStageUpdateRequest,
    AttendanceCorrectionCreateRequest,
    AttendanceCorrectionDecisionRequest,
    AttendanceEntryCreateRequest,
    AttendanceReviewRequest,
    BenefitTypeCreateRequest,
    CandidateCreateRequest,
    CertificationCreateRequest,
    ClearanceStepResponse,
    CompensationTermCreateRequest,
    CompensationTermResponse,
    ComplianceItemResponse,
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
    HrServiceRequestCreateRequest,
    HrServiceRequestResolveRequest,
    InterviewCreateRequest,
    InterviewUpdateRequest,
    LeaveBalanceItem,
    LeaveBalanceListResponse,
    LeaveLedgerAdjustRequest,
    LeavePolicyCreateRequest,
    LeaveRequestCreateRequest,
    LeaveRequestDecisionRequest,
    LeaveTypeCreateRequest,
    LetterGenerateRequest,
    LetterRenderResponse,
    LetterTemplateCreateRequest,
    OffboardingCaseResponse,
    OffboardingCompleteRequest,
    OffboardingInitiateRequest,
    OffboardingStepUpdateRequest,
    OfferConvertRequest,
    OfferCreateRequest,
    OfferDecisionRequest,
    OnboardingCaseCreateRequest,
    OnboardingCaseResponse,
    OnboardingTaskResponse,
    OnboardingTaskUpdateRequest,
    OvertimeDecisionRequest,
    OvertimeRequestCreateRequest,
    PayrollPeriodCreateRequest,
    PayrollPolicyCreateRequest,
    PayrollRunCreateRequest,
    PolicyAcknowledgeRequest,
    PolicyDocumentCreateRequest,
    ReimbursementCreateRequest,
    ReimbursementDecisionRequest,
    RequisitionCreateRequest,
    RequisitionDecisionRequest,
    ReviewCreateRequest,
    ReviewCycleCreateRequest,
    ShiftAssignmentCreateRequest,
    ShiftAssignmentResponse,
    TimesheetCreateRequest,
    TimesheetDecisionRequest,
    TimesheetSelfResubmitRequest,
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
from app.services.hr_manager_review import (
    REVIEW_EMPLOYMENT_STATES,
    require_manager_recommendation,
    start_manager_review,
    verify_request_revision,
)
from app.services.storage_service import discard_new_uploads, minio_client, minio_signed_url_client
from app.utils.exceptions import AppException, NotFoundException, PermissionDeniedException
from app.utils.permissions import (
    PERMISSION_HR_CASES_RESTRICTED,
    PERMISSION_HR_EMPLOYEES_SENSITIVE,
    PERMISSION_HR_PAYROLL_APPROVE,
    PERMISSION_HR_PAYROLL_SENSITIVE,
    PERMISSION_HR_POLICY_MANAGE,
    PERMISSION_HR_REQUESTS_PROCESS,
    ensure_permission,
    has_permission,
)
from app.utils.security import utc_now

RESTRICTED_DOC_CATEGORIES = {"confidential", "medical", "compensation", "disciplinary"}
SIGNED_URL_SECONDS = 300
WORKDAYS = ("MON", "TUE", "WED", "THU", "FRI", "SAT", "SUN")


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

    async def _employee_for_user(self, user: User) -> HrEmployee:
        emp = await self.session.scalar(
            select(HrEmployee).where(
                HrEmployee.user_id == user.id,
                HrEmployee.deleted_at.is_(None),
                HrEmployee.employment_status.in_(REVIEW_EMPLOYMENT_STATES),
            )
        )
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
        self, *, status: str | None = None, limit: int = 100, offset: int = 0
    ) -> tuple[list[HrRequisition], int]:
        stmt = select(HrRequisition).where(HrRequisition.deleted_at.is_(None))
        count_stmt = select(func.count(HrRequisition.id)).where(HrRequisition.deleted_at.is_(None))
        if status:
            stmt = stmt.where(HrRequisition.status == status)
            count_stmt = count_stmt.where(HrRequisition.status == status)
        rows = list(
            await self.session.scalars(
                stmt.order_by(HrRequisition.created_at.desc()).limit(limit).offset(offset)
            )
        )
        total = int(await self.session.scalar(count_stmt) or 0)
        return rows, total

    async def decide_requisition(
        self, requisition_id: UUID, payload: RequisitionDecisionRequest, actor: User
    ) -> HrRequisition:
        req = await self.session.scalar(
            select(HrRequisition)
            .where(HrRequisition.id == requisition_id, HrRequisition.deleted_at.is_(None))
            .with_for_update()
        )
        if req is None:
            raise NotFoundException("Requisition")
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
        if payload.status == "rejected" and not (payload.notes or "").strip():
            raise AppException("Rejection requires a reason.", status_code=422)
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
        self, *, search: str | None = None, limit: int = 100, offset: int = 0
    ) -> tuple[list[HrCandidate], int]:
        stmt = select(HrCandidate).where(HrCandidate.deleted_at.is_(None))
        count_stmt = select(func.count(HrCandidate.id)).where(HrCandidate.deleted_at.is_(None))
        if search:
            like = f"%{search.strip()}%"
            filt = or_(
                HrCandidate.full_name.ilike(like),
                HrCandidate.candidate_code.ilike(like),
                HrCandidate.email.ilike(like),
            )
            stmt = stmt.where(filt)
            count_stmt = count_stmt.where(filt)
        rows = list(
            await self.session.scalars(
                stmt.order_by(HrCandidate.created_at.desc()).limit(limit).offset(offset)
            )
        )
        total = int(await self.session.scalar(count_stmt) or 0)
        return rows, total

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
        self, *, requisition_id: UUID | None = None, limit: int = 100, offset: int = 0
    ) -> tuple[list[HrApplication], int]:
        stmt = select(HrApplication)
        count_stmt = select(func.count(HrApplication.id))
        if requisition_id:
            stmt = stmt.where(HrApplication.requisition_id == requisition_id)
            count_stmt = count_stmt.where(HrApplication.requisition_id == requisition_id)
        rows = list(
            await self.session.scalars(
                stmt.order_by(HrApplication.created_at.desc()).limit(limit).offset(offset)
            )
        )
        total = int(await self.session.scalar(count_stmt) or 0)
        return rows, total

    async def update_application_stage(
        self, application_id: UUID, payload: ApplicationStageUpdateRequest, actor: User
    ) -> HrApplication:
        app_row = await self.session.scalar(
            select(HrApplication).where(HrApplication.id == application_id).with_for_update()
        )
        if app_row is None:
            raise NotFoundException("Application")
        transitions = {
            "applied": {"screening", "rejected", "withdrawn"},
            "screening": {"interview", "rejected", "withdrawn"},
            "interview": {"evaluation", "rejected", "withdrawn"},
            "evaluation": {"offer", "rejected", "withdrawn"},
        }
        if payload.stage not in transitions.get(app_row.stage, set()):
            raise AppException("This application cannot make that transition.", status_code=409)
        if payload.stage == "evaluation" and not await self.session.scalar(
            select(HrInterview.id)
            .where(HrInterview.application_id == app_row.id, HrInterview.status == "completed")
            .limit(1)
        ):
            raise AppException("Record a completed interview before evaluation.", status_code=409)
        if payload.stage == "rejected" and not (payload.rejection_reason or "").strip():
            raise AppException("Rejection requires a reason.", status_code=422)
        app_row.stage = payload.stage
        if payload.overall_score is not None:
            app_row.overall_score = payload.overall_score
        if payload.screening_notes is not None:
            app_row.screening_notes = payload.screening_notes
        if payload.rejection_reason is not None:
            app_row.rejection_reason = payload.rejection_reason
        await self.audit.record(
            action="hr.application.stage_changed",
            user_id=actor.id,
            entity_type="hr_applications",
            entity_id=app_row.id,
            new_values={"stage": payload.stage},
        )
        await self._commit_and_refresh(app_row)
        return app_row

    async def create_interview(self, payload: InterviewCreateRequest, actor: User) -> HrInterview:
        interview = HrInterview(
            application_id=payload.application_id,
            round_number=payload.round_number,
            interview_type=payload.interview_type,
            scheduled_at=payload.scheduled_at,
            interviewer_user_id=payload.interviewer_user_id,
            interviewer_name=payload.interviewer_name,
        )
        self.session.add(interview)
        await self.session.flush()
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
        interview = await self.session.scalar(
            select(HrInterview).where(HrInterview.id == interview_id)
        )
        if interview is None:
            raise NotFoundException("Interview")
        if payload.recommendation is not None:
            interview.recommendation = payload.recommendation
        if payload.score is not None:
            interview.score = payload.score
        if payload.feedback_notes is not None:
            interview.feedback_notes = payload.feedback_notes
        if payload.status is not None:
            interview.status = payload.status
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
        application = await self.session.scalar(
            select(HrApplication)
            .where(HrApplication.id == payload.application_id)
            .with_for_update()
        )
        if application is None:
            raise NotFoundException("Application")
        if application.stage != "evaluation":
            raise AppException("Complete interviews before drafting an offer.", status_code=409)
        if payload.proposed_salary is not None:
            raise PermissionDeniedException(PERMISSION_HR_PAYROLL_SENSITIVE)
        if await self.session.scalar(
            select(HrOffer.id)
            .where(
                HrOffer.application_id == application.id,
                HrOffer.status.notin_(["declined", "withdrawn"]),
            )
            .limit(1)
        ):
            raise AppException(
                "This application already has an open or accepted offer.", status_code=409
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
                new_values={"offer_code": offer.offer_code},
            )
            await self.session.commit()
        except IntegrityError as exc:
            await self.session.rollback()
            raise AppException(
                "Offer code already exists.",
                status_code=409,
                error_code="OFFER_EXISTS",
            ) from exc
        return offer

    async def list_offers(
        self, *, status: str | None = None, limit: int = 100, offset: int = 0
    ) -> tuple[list[HrOffer], int]:
        stmt = select(HrOffer)
        count_stmt = select(func.count(HrOffer.id))
        if status:
            stmt = stmt.where(HrOffer.status == status)
            count_stmt = count_stmt.where(HrOffer.status == status)
        rows = list(
            await self.session.scalars(
                stmt.order_by(HrOffer.created_at.desc()).limit(limit).offset(offset)
            )
        )
        total = int(await self.session.scalar(count_stmt) or 0)
        return rows, total

    async def decide_offer(
        self, offer_id: UUID, payload: OfferDecisionRequest, actor: User
    ) -> HrOffer:
        offer = await self.session.scalar(
            select(HrOffer).where(HrOffer.id == offer_id).with_for_update()
        )
        if offer is None:
            raise NotFoundException("Offer")
        if payload.status == "approved" and not has_permission(
            actor, PERMISSION_HR_EMPLOYEES_SENSITIVE
        ):
            raise PermissionDeniedException(PERMISSION_HR_EMPLOYEES_SENSITIVE)
        transitions = {
            "draft": {"pending_approval", "withdrawn"},
            "pending_approval": {"approved", "withdrawn"},
            "approved": {"issued", "withdrawn"},
            "issued": {"accepted", "declined", "withdrawn"},
        }
        if payload.status not in transitions.get(offer.status, set()):
            raise AppException("This offer cannot make that transition.", status_code=409)
        now = utc_now()
        offer.status = payload.status
        if payload.status == "approved":
            offer.approved_by_id = actor.id
            offer.approved_at = now
        elif payload.status == "issued":
            offer.issued_at = now
        elif payload.status in {"accepted", "declined"}:
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
        offer = await self.session.scalar(
            select(HrOffer).where(HrOffer.id == offer_id).with_for_update()
        )
        if offer is None:
            raise NotFoundException("Offer")
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
        app_row = await self.session.scalar(
            select(HrApplication).where(HrApplication.id == offer.application_id)
        )
        if app_row is None:
            raise NotFoundException("Application")
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
        self, *, employee_id: UUID | None = None
    ) -> tuple[list[OnboardingCaseResponse], int]:
        stmt = select(HrOnboardingCase)
        count_stmt = select(func.count(HrOnboardingCase.id))
        if employee_id:
            stmt = stmt.where(HrOnboardingCase.employee_id == employee_id)
            count_stmt = count_stmt.where(HrOnboardingCase.employee_id == employee_id)
        cases = list(await self.session.scalars(stmt.order_by(HrOnboardingCase.created_at.desc())))
        total = int(await self.session.scalar(count_stmt) or 0)
        return [await self._serialize_onboarding_case(c) for c in cases], total

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
        self, document_id: UUID, file: UploadFile, actor: User
    ) -> HrDocumentResponse:
        doc = await self._get_hr_document(document_id, for_update=True)
        self._ensure_hr_doc_access(doc, actor)
        latest = await self.session.scalar(
            select(HrDocumentVersion)
            .where(HrDocumentVersion.document_id == doc.id)
            .order_by(HrDocumentVersion.version_number.desc())
            .limit(1)
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
                stmt.order_by(HrDocument.created_at.desc()).limit(limit).offset(offset)
            )
        )
        total = int(await self.session.scalar(count_stmt) or 0)
        return [await self._serialize_hr_document(d) for d in docs], total

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
    ) -> HrDocumentDownloadResponse:
        visible_version: ColumnElement[bool] = HrDocumentVersion.status.in_(
            ["active", "superseded"] if include_category else ["active"]
        )
        if (
            include_category
            and version_number is not None
            and doc.document_type == "candidate_cv"
            and doc.candidate_id is not None
            and doc.category == "confidential"
            and has_permission(actor, PERMISSION_HR_EMPLOYEES_SENSITIVE)
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
            employee_calendar = (HrWorkCalendar.id == employee.work_calendar_id) & (
                HrWorkCalendar.project_id.is_(None)
                | (HrWorkCalendar.project_id == employee.primary_project_id)
            )
            company_default = HrWorkCalendar.project_id.is_(None) & HrWorkCalendar.is_default.is_(
                True
            )
            project_calendar = (
                HrWorkCalendar.project_id == employee.primary_project_id
                if employee.primary_project_id is not None
                else false()
            )
            calendar = await self.session.scalar(
                select(HrWorkCalendar)
                .where(*applicable, or_(employee_calendar, project_calendar, company_default))
                .order_by(case((employee_calendar, 0), (project_calendar, 1), else_=2))
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
            if outstanding or correction:
                raise AppException(
                    "Review attendance and pending corrections before locking this period.",
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
        leave_type = await self.session.scalar(
            select(HrLeaveType).where(HrLeaveType.id == payload.leave_type_id).with_for_update()
        )
        if leave_type is None or not leave_type.is_active:
            raise NotFoundException("Leave type")
        if payload.approve_immediately and await self.session.scalar(
            select(HrLeavePolicy.id)
            .where(
                HrLeavePolicy.leave_type_id == leave_type.id,
                HrLeavePolicy.employment_category == payload.employment_category,
                HrLeavePolicy.is_active.is_(True),
                HrLeavePolicy.approved_at.is_not(None),
            )
            .limit(1)
        ):
            raise AppException("An approved policy already covers this group.", status_code=409)
        data = payload.model_dump(exclude={"approve_immediately"})
        pol = HrLeavePolicy(
            **data,
            approved_by_id=actor.id if payload.approve_immediately else None,
            approved_at=utc_now() if payload.approve_immediately else None,
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
        leave_type = await self.session.get(HrLeaveType, payload.leave_type_id)
        if not leave_type or not leave_type.is_active:
            raise NotFoundException("Leave type")
        if payload.days_delta == 0 or (
            payload.entry_type in {"opening_balance", "accrual", "carry_forward"}
            and payload.days_delta < 0
        ):
            raise AppException("The adjustment amount is invalid.", status_code=422)
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

    async def create_leave_request(
        self, payload: LeaveRequestCreateRequest, actor: User, *, own_request: bool = False
    ) -> HrLeaveRequest:
        employee_id = payload.employee_id or (await self._employee_for_user(actor)).id
        target_emp = await self._require_employee(employee_id, for_update=True)
        if own_request:
            self._verify_self_request(target_emp, actor)
        calendar_days = (payload.end_date - payload.start_date).days + 1
        if (
            calendar_days <= 0
            or payload.start_date.year != payload.end_date.year
            or payload.days_requested > calendar_days
        ):
            raise AppException(
                "Invalid leave dates or units. Split requests across calendar years.",
                status_code=422,
            )
        if payload.is_half_day and (
            calendar_days != 1
            or payload.days_requested != Decimal("0.5")
            or not payload.half_day_period
        ):
            raise AppException("Specify one date and a period for half-day leave.", status_code=422)
        if not payload.is_half_day and payload.half_day_period is not None:
            raise AppException("A half-day period requires half-day leave.", status_code=422)
        lt = await self.session.get(HrLeaveType, payload.leave_type_id)
        if lt is None or not lt.is_active:
            raise NotFoundException("Leave type")
        if payload.is_half_day and not lt.allow_half_day:
            raise AppException("This leave type does not allow half days.", status_code=422)
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
        if payload.submit_immediately:
            await self._ensure_no_leave_overlap(target_emp.id, payload.start_date, payload.end_date)
        req = HrLeaveRequest(
            employee_id=target_emp.id,
            leave_type_id=payload.leave_type_id,
            start_date=payload.start_date,
            end_date=payload.end_date,
            days_requested=payload.days_requested,
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

    async def decide_leave_request(
        self,
        leave_request_id: UUID,
        payload: LeaveRequestDecisionRequest,
        actor: User,
        *,
        own_request: bool = False,
    ) -> HrLeaveRequest:
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
        if payload.decision == "submitted":
            await self._ensure_no_leave_overlap(
                emp.id, req.start_date, req.end_date, exclude=req.id
            )
            await start_manager_review(self.session, req, emp)
        if payload.decision == "rejected" and not (payload.notes or "").strip():
            raise AppException("Rejection requires a reason.", status_code=422)
        if payload.decision in {"approved", "rejected"} and (
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
        if payload.decision == "approved":
            lt = await self.session.scalar(
                select(HrLeaveType).where(HrLeaveType.id == req.leave_type_id)
            )
            policy = await self.session.scalar(
                select(HrLeavePolicy)
                .where(
                    HrLeavePolicy.leave_type_id == req.leave_type_id,
                    HrLeavePolicy.is_active.is_(True),
                    HrLeavePolicy.approved_at.is_not(None),
                    or_(
                        HrLeavePolicy.employment_category == emp.employment_category,
                        HrLeavePolicy.employment_category.is_(None),
                    ),
                )
                .order_by(
                    HrLeavePolicy.employment_category.is_(None), HrLeavePolicy.approved_at.desc()
                )
                .limit(1)
            )
            allow_neg = policy.allow_negative_balance if policy else False
            if lt and lt.is_paid and not allow_neg:
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
        elif payload.decision == "cancelled" and prev_status == "approved":
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
        req.decision_notes = payload.notes
        req.record_revision += 1
        await self.audit.record(
            action=f"hr.leave_request.{payload.decision}",
            user_id=actor.id,
            entity_type="hr_leave_requests",
            entity_id=req.id,
        )
        await self._commit_and_refresh(req)
        return req

    async def list_leave_requests(
        self, *, employee_id: UUID | None = None, status: str | None = None
    ) -> tuple[list[HrLeaveRequest], int]:
        stmt = select(HrLeaveRequest)
        if employee_id:
            stmt = stmt.where(HrLeaveRequest.employee_id == employee_id)
        if status:
            stmt = stmt.where(HrLeaveRequest.status == status)
        rows = list(await self.session.scalars(stmt.order_by(HrLeaveRequest.created_at.desc())))
        return rows, len(rows)

    # --- Policies, Letter Templates, HR Service Requests (HR-016) ---

    async def create_policy_document(
        self, payload: PolicyDocumentCreateRequest, actor: User
    ) -> HrPolicyDocument:
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

    async def acknowledge_policy(
        self, policy_id: UUID, payload: PolicyAcknowledgeRequest, actor: User
    ) -> HrPolicyAcknowledgement:
        emp = await self._employee_for_user(actor)
        ack = HrPolicyAcknowledgement(
            policy_id=policy_id,
            employee_id=emp.id,
            acknowledged_at=utc_now(),
            acknowledged_by_user_id=actor.id,
            notes=payload.notes,
        )
        self.session.add(ack)
        try:
            await self.session.flush()
            await self.audit.record(
                action="hr.policy.acknowledged",
                user_id=actor.id,
                entity_type="hr_policy_acknowledgements",
                entity_id=ack.id,
            )
            await self.session.commit()
        except IntegrityError as exc:
            await self.session.rollback()
            raise AppException(
                "Policy already acknowledged by employee.",
                status_code=409,
                error_code="POLICY_ALREADY_ACKNOWLEDGED",
            ) from exc
        return ack

    @staticmethod
    def _validate_letter_template(*templates: str) -> None:
        try:
            for template in templates:
                for _, field, spec, conversion in Formatter().parse(template):
                    if field is not None and (
                        not field.isascii() or not field.isidentifier() or spec or conversion
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
        self._validate_letter_template(payload.subject_template, payload.body_template)
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

    async def list_letter_templates(self) -> tuple[list[HrLetterTemplate], int]:
        rows = list(
            await self.session.scalars(select(HrLetterTemplate).order_by(HrLetterTemplate.code))
        )
        return rows, len(rows)

    async def render_letter(
        self, payload: LetterGenerateRequest, actor: User
    ) -> LetterRenderResponse:
        tmpl = await self.session.scalar(
            select(HrLetterTemplate).where(
                HrLetterTemplate.id == payload.template_id,
                HrLetterTemplate.is_active.is_(True),
            )
        )
        if tmpl is None:
            raise NotFoundException("Letter template")
        if tmpl.requires_hr_manager and not has_permission(
            actor, PERMISSION_HR_EMPLOYEES_SENSITIVE
        ):
            raise PermissionDeniedException(PERMISSION_HR_EMPLOYEES_SENSITIVE)
        emp = await self._require_employee(payload.employee_id)
        self._validate_letter_template(tmpl.subject_template, tmpl.body_template)
        context = {
            "employee_code": emp.employee_code,
            "full_name": emp.full_name,
            "join_date": emp.join_date.isoformat() if emp.join_date else "",
            "employment_status": emp.employment_status,
        }
        if context.keys() & payload.extra_vars.keys():
            raise AppException(
                "Employee fields are filled from the employee record.",
                status_code=422,
                error_code="LETTER_EMPLOYEE_FIELD_OVERRIDE",
            )
        context.update(payload.extra_vars)
        try:
            subject = tmpl.subject_template.format(**context)
            body = tmpl.body_template.format(**context)
        except KeyError as exc:
            raise AppException(
                f"Missing template placeholder value: {exc}",
                status_code=422,
                error_code="MISSING_TEMPLATE_VAR",
            ) from exc
        await self.audit.record(
            action="hr.letter.rendered",
            user_id=actor.id,
            entity_type="hr_employees",
            entity_id=emp.id,
            new_values={"template_code": tmpl.code},
        )
        await self.session.commit()
        return LetterRenderResponse(
            template_id=tmpl.id, employee_id=emp.id, subject=subject, body=body
        )

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

    async def resolve_service_request(
        self, req_id: UUID, payload: HrServiceRequestResolveRequest, actor: User
    ) -> HrServiceRequest:
        ensure_permission(actor, PERMISSION_HR_REQUESTS_PROCESS)
        req = await self.session.scalar(
            select(HrServiceRequest)
            .where(HrServiceRequest.id == req_id)
            .with_for_update()
            .execution_options(populate_existing=True)
        )
        if req is None:
            raise NotFoundException("HR service request")
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
        prior_status = req.status
        req.status = payload.status
        if "resolution_notes" in payload.model_fields_set:
            req.resolution_notes = payload.resolution_notes
        if "generated_document_id" in payload.model_fields_set:
            req.generated_document_id = payload.generated_document_id
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
            old_values={"status": prior_status},
            new_values={"status": req.status},
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
        req.status = "open"
        req.assigned_to_id = None
        req.resolved_by_id = None
        req.resolved_at = None
        await self.audit.record(
            action="hr.service_request.reopened",
            user_id=actor.id,
            entity_type="hr_hr_requests",
            entity_id=req.id,
            old_values={"status": prior_status},
            new_values={"status": req.status},
        )
        await self._commit_and_refresh(req)
        return req

    async def list_service_requests(
        self, *, employee_id: UUID | None = None
    ) -> tuple[list[HrServiceRequest], int]:
        stmt = select(HrServiceRequest)
        if employee_id:
            stmt = stmt.where(HrServiceRequest.employee_id == employee_id)
        rows = list(await self.session.scalars(stmt.order_by(HrServiceRequest.created_at.desc())))
        return rows, len(rows)

    # --- Offboarding & Clearance (HR-017, HR-018) ---

    async def initiate_offboarding(
        self, payload: OffboardingInitiateRequest, actor: User
    ) -> OffboardingCaseResponse:
        emp = await self._require_employee(payload.employee_id, for_update=True)
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
            ("it_admin", "Revoke portal access & IT credentials"),
            ("store_inventory", "Return site tools, PPE, and store items"),
            ("finance_accounts", "Clear advances & final settlement check"),
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
        if payload.status in {"cleared", "waived"} and not (payload.notes or "").strip():
            raise AppException("Provide a clearance or exception reference.", status_code=422)
        if step.department_area == "it_admin" and payload.status in {"cleared", "waived"}:
            emp = await self._require_employee(case.employee_id, for_update=True)
            if emp.user_id:
                case.access_revoked_at = await self._confirmed_access_revocation(emp)
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

    async def _confirmed_access_revocation(self, employee: HrEmployee) -> datetime:
        deactivated_at = await self.session.scalar(
            select(HrAccessRequest.admin_actioned_at)
            .join(User, User.id == HrAccessRequest.linked_user_id)
            .where(
                HrAccessRequest.employee_id == employee.id,
                HrAccessRequest.request_type == "deactivate",
                HrAccessRequest.status == "admin_actioned",
                User.id == employee.user_id,
                User.is_active.is_(False),
            )
            .order_by(HrAccessRequest.admin_actioned_at.desc().nulls_last())
            .limit(1)
        )
        if deactivated_at is None:
            raise AppException(
                "A director must fulfill a deactivation request before IT clearance.",
                status_code=409,
                error_code="ACCESS_REVOCATION_REQUIRED",
            )
        return deactivated_at

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
        emp = await self._require_employee(case.employee_id, for_update=True)
        if emp.user_id:
            case.access_revoked_at = await self._confirmed_access_revocation(emp)
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
        await self._require_employee(payload.employee_id)
        goal = HrGoal(**payload.model_dump())
        self.session.add(goal)
        await self.session.flush()
        await self.audit.record(
            action="hr.goal.created", user_id=actor.id, entity_type="hr_goals", entity_id=goal.id
        )
        await self._commit_and_refresh(goal)
        return goal

    async def update_goal(self, goal_id: UUID, payload: GoalUpdateRequest, actor: User) -> HrGoal:
        goal = await self.session.scalar(select(HrGoal).where(HrGoal.id == goal_id))
        if goal is None:
            raise NotFoundException("Goal")
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
        rev = HrReview(**payload.model_dump())
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
            select(HrTrainingEnrollment).where(HrTrainingEnrollment.id == enrollment_id)
        )
        if enr is None:
            raise NotFoundException("Training enrollment")
        enr.status = payload.status
        enr.completed_date = payload.completed_date
        enr.score = payload.score
        await self.audit.record(
            action="hr.training.updated",
            user_id=actor.id,
            entity_type="hr_training_enrollments",
            entity_id=enr.id,
        )
        await self._commit_and_refresh(enr)
        return enr

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
        bt = HrBenefitType(**payload.model_dump())
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

    async def list_benefit_types(self) -> tuple[list[HrBenefitType], int]:
        rows = list(
            await self.session.scalars(select(HrBenefitType).order_by(HrBenefitType.code.asc()))
        )
        return rows, len(rows)

    async def create_employee_benefit(
        self, payload: EmployeeBenefitCreateRequest, actor: User
    ) -> HrEmployeeBenefit:
        await self._require_employee(payload.employee_id)
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

    async def create_reimbursement(
        self, payload: ReimbursementCreateRequest, actor: User
    ) -> HrReimbursementClaim:
        emp = (
            await self._require_employee(payload.employee_id)
            if payload.employee_id
            else await self._employee_for_user(actor)
        )
        claim = HrReimbursementClaim(
            claim_code=f"CLM-{uuid4().hex[:8].upper()}",
            employee_id=emp.id,
            claim_type=payload.claim_type,
            claim_date=payload.claim_date,
            amount=payload.amount,
            currency=payload.currency,
            description=payload.description,
            receipt_document_id=payload.receipt_document_id,
        )
        self.session.add(claim)
        await self.session.flush()
        await self.audit.record(
            action="hr.reimbursement.submitted",
            user_id=actor.id,
            entity_type="hr_reimbursement_claims",
            entity_id=claim.id,
        )
        await self._commit_and_refresh(claim)
        return claim

    async def decide_reimbursement(
        self, claim_id: UUID, payload: ReimbursementDecisionRequest, actor: User
    ) -> HrReimbursementClaim:
        claim = await self.session.scalar(
            select(HrReimbursementClaim).where(HrReimbursementClaim.id == claim_id)
        )
        if claim is None:
            raise NotFoundException("Reimbursement claim")
        claim.status = payload.decision
        claim.decided_by_id = actor.id
        claim.decided_at = utc_now()
        claim.decision_notes = payload.notes
        await self.audit.record(
            action=f"hr.reimbursement.{payload.decision}",
            user_id=actor.id,
            entity_type="hr_reimbursement_claims",
            entity_id=claim.id,
        )
        await self._commit_and_refresh(claim)
        return claim

    async def list_reimbursements(
        self, *, employee_id: UUID | None = None
    ) -> tuple[list[HrReimbursementClaim], int]:
        stmt = select(HrReimbursementClaim)
        if employee_id:
            stmt = stmt.where(HrReimbursementClaim.employee_id == employee_id)
        rows = list(
            await self.session.scalars(stmt.order_by(HrReimbursementClaim.claim_date.desc()))
        )
        return rows, len(rows)

    async def create_compensation_term(
        self, payload: CompensationTermCreateRequest, actor: User
    ) -> CompensationTermResponse:
        await self._require_employee(payload.employee_id)
        # Supersede prior current terms
        prev_rows = list(
            await self.session.scalars(
                select(HrCompensationTerm).where(
                    HrCompensationTerm.employee_id == payload.employee_id,
                    HrCompensationTerm.is_current.is_(True),
                )
            )
        )
        for prev in prev_rows:
            prev.is_current = False
        import json

        term = HrCompensationTerm(
            employee_id=payload.employee_id,
            effective_from=payload.effective_from,
            pay_frequency=payload.pay_frequency,
            currency=payload.currency,
            base_salary_encrypted=encrypt_hr_value(payload.base_salary) or "",
            base_salary_masked=mask_identifier(payload.base_salary) or "****",
            allowances_encrypted=encrypt_hr_value(json.dumps(payload.allowances_json))
            if payload.allowances_json
            else None,
            is_current=True,
            approved_by_id=actor.id,
            approved_at=utc_now(),
        )
        self.session.add(term)
        await self.session.flush()
        await self.audit.record(
            action="hr.compensation.updated",
            user_id=actor.id,
            entity_type="hr_compensation_terms",
            entity_id=term.id,
        )
        await self.session.commit()
        return CompensationTermResponse(
            id=term.id,
            employee_id=term.employee_id,
            effective_from=term.effective_from,
            pay_frequency=term.pay_frequency,
            currency=term.currency,
            base_salary_masked=term.base_salary_masked,
            base_salary_plain=None,
            is_current=term.is_current,
            approved_by_id=term.approved_by_id,
            approved_at=term.approved_at,
            created_at=term.created_at,
        )

    async def list_compensation_terms(
        self, *, employee_id: UUID, actor: User, reveal_sensitive: bool = False
    ) -> tuple[list[CompensationTermResponse], int]:
        rows = list(
            await self.session.scalars(
                select(HrCompensationTerm)
                .where(HrCompensationTerm.employee_id == employee_id)
                .order_by(HrCompensationTerm.effective_from.desc())
            )
        )
        if reveal_sensitive:
            await self.audit.record(
                action="hr.compensation.revealed",
                user_id=actor.id,
                entity_type="hr_employees",
                entity_id=employee_id,
            )
            await self.session.commit()
        return [
            CompensationTermResponse(
                id=t.id,
                employee_id=t.employee_id,
                effective_from=t.effective_from,
                pay_frequency=t.pay_frequency,
                currency=t.currency,
                base_salary_masked=t.base_salary_masked,
                base_salary_plain=decrypt_hr_value(t.base_salary_encrypted)
                if reveal_sensitive
                else None,
                is_current=t.is_current,
                approved_by_id=t.approved_by_id,
                approved_at=t.approved_at,
                created_at=t.created_at,
            )
            for t in rows
        ], len(rows)

    async def create_payroll_policy(
        self, payload: PayrollPolicyCreateRequest, actor: User
    ) -> HrPayrollPolicy:
        pol = HrPayrollPolicy(
            code=payload.code.strip(),
            name=payload.name.strip(),
            rules_json=payload.rules_json,
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

    async def approve_payroll_policy(self, policy_id: UUID, actor: User) -> HrPayrollPolicy:
        pol = await self.session.scalar(
            select(HrPayrollPolicy).where(HrPayrollPolicy.id == policy_id)
        )
        if pol is None:
            raise NotFoundException("Payroll policy")
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

    async def calculate_payroll_run(self, run_id: UUID, actor: User) -> HrPayrollRun:
        run = await self.session.scalar(select(HrPayrollRun).where(HrPayrollRun.id == run_id))
        if run is None:
            raise NotFoundException("Payroll run")
        policy = (
            await self.session.scalar(
                select(HrPayrollPolicy).where(HrPayrollPolicy.id == run.policy_id)
            )
            if run.policy_id
            else None
        )
        if (
            policy is None
            or not policy.is_approved
            or policy.approved_by_id is None
            or policy.second_approved_by_id is None
            or not policy.rules_json
        ):
            raise AppException(
                "POLICY_NOT_APPROVED: Payroll and statutory calculations require an active, "
                "dual-approved HR payroll policy with explicit rules.",
                status_code=409,
                error_code="POLICY_NOT_APPROVED",
            )

        # Compute deterministic lines from active compensation terms when explicitly authorized
        terms = list(
            await self.session.scalars(
                select(HrCompensationTerm).where(HrCompensationTerm.is_current.is_(True))
            )
        )
        ded_rate = Decimal(str(policy.rules_json.get("employee_deduction_rate", "0")))
        for term in terms:
            raw_salary = decrypt_hr_value(term.base_salary_encrypted) or "0"
            gross = Decimal(raw_salary)
            ded = (gross * ded_rate).quantize(Decimal("0.01"))
            net = gross - ded
            self.session.add(
                HrPayrollLine(
                    payroll_run_id=run.id,
                    employee_id=term.employee_id,
                    gross_encrypted=encrypt_hr_value(str(gross)) or "",
                    deductions_encrypted=encrypt_hr_value(str(ded)) or "",
                    net_encrypted=encrypt_hr_value(str(net)) or "",
                    breakdown_json={"policy_code": policy.code, "deduction_rate": str(ded_rate)},
                )
            )
        run.status = "calculated"
        await self.audit.record(
            action="hr.payroll_run.calculated",
            user_id=actor.id,
            entity_type="hr_payroll_runs",
            entity_id=run.id,
        )
        await self._commit_and_refresh(run)
        return run

    async def approve_payroll_run(self, run_id: UUID, actor: User) -> HrPayrollRun:
        if not has_permission(actor, PERMISSION_HR_PAYROLL_APPROVE):
            raise PermissionDeniedException(PERMISSION_HR_PAYROLL_APPROVE)
        run = await self.session.scalar(select(HrPayrollRun).where(HrPayrollRun.id == run_id))
        if run is None:
            raise NotFoundException("Payroll run")
        policy = (
            await self.session.scalar(
                select(HrPayrollPolicy).where(HrPayrollPolicy.id == run.policy_id)
            )
            if run.policy_id
            else None
        )
        if policy is None or not policy.is_approved:
            raise AppException(
                "POLICY_NOT_APPROVED: Cannot approve payroll without an approved payroll policy.",
                status_code=409,
                error_code="POLICY_NOT_APPROVED",
            )
        run.status = "approved"
        run.approved_by_id = actor.id
        run.approved_at = utc_now()
        await self.audit.record(
            action="hr.payroll_run.approved",
            user_id=actor.id,
            entity_type="hr_payroll_runs",
            entity_id=run.id,
        )
        await self._commit_and_refresh(run)
        return run

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
