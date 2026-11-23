from datetime import date
from typing import Literal
from uuid import UUID

from sqlalchemy import func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.sql.elements import ColumnElement

from app.models.hr import (
    HrAttendanceEntry,
    HrEmployee,
    HrRosterAllocation,
    HrShiftAssignment,
    HrSiteAttendanceSubmission,
)
from app.models.project import Project
from app.models.user import User
from app.schemas.hr import (
    SiteAttendanceCorrectionRequest,
    SiteAttendanceCreateRequest,
    SiteAttendanceDecisionRequest,
    SiteAttendancePageResponse,
    SiteAttendanceResponse,
    SiteAttendanceSubmissionResponse,
    SiteAttendanceWorker,
    SiteAttendanceWorkerPage,
)
from app.services.approval_service import ApprovalService
from app.services.authorization import accessible_project_ids, ensure_project_access
from app.services.hr_manager_review import REVIEW_EMPLOYMENT_STATES, verify_request_revision
from app.services.hr_workforce_service import HrWorkforceService
from app.services.notification_service import NotificationService
from app.utils.exceptions import AppException, NotFoundException, PermissionDeniedException
from app.utils.links import append_link, build_frontend_url
from app.utils.permissions import (
    COMPANY_RESOURCE_ROLES,
    PERMISSION_HR_ATTENDANCE_APPROVE,
    ROLE_GROUP_PROJECT_MANAGER,
    ROLE_HR_MANAGER,
    ROLE_MEP_PROJECT_MANAGER,
    SUPERVISOR_ROLES,
    ensure_permission,
)
from app.utils.security import utc_now
from app.utils.time import business_today

SITE_ATTENDANCE_ROLES = (
    SUPERVISOR_ROLES
    | COMPANY_RESOURCE_ROLES
    | {
        ROLE_MEP_PROJECT_MANAGER,
        ROLE_GROUP_PROJECT_MANAGER,
        ROLE_HR_MANAGER,
    }
)


class HrSiteAttendanceService:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session
        self.workforce = HrWorkforceService(session)
        self.notifications = NotificationService(session)

    async def list_workers(
        self,
        project_id: UUID,
        work_date: date,
        actor: User,
        *,
        search: str | None,
        limit: int,
        offset: int,
    ) -> SiteAttendanceWorkerPage:
        self._ensure_submitter(actor)
        await self._ensure_active_project(project_id, actor)
        query = select(HrEmployee.id, HrEmployee.employee_code, HrEmployee.full_name).where(
            *self._worker_eligibility(project_id, work_date)
        )
        if search and search.strip():
            term = f"%{search.strip()}%"
            query = query.where(
                or_(HrEmployee.full_name.ilike(term), HrEmployee.employee_code.ilike(term))
            )
        total = await self.session.scalar(select(func.count()).select_from(query.subquery()))
        rows = await self.session.execute(
            query.order_by(HrEmployee.full_name, HrEmployee.id).limit(limit).offset(offset)
        )
        return SiteAttendanceWorkerPage(
            items=[
                SiteAttendanceWorker(id=id_, employee_code=code, full_name=name)
                for id_, code, name in rows
            ],
            total=int(total or 0),
        )

    async def list_entries(
        self,
        actor: User,
        *,
        project_id: UUID | None,
        work_date: date | None,
        entry_id: UUID | None,
        limit: int,
        offset: int,
    ) -> SiteAttendancePageResponse:
        self._ensure_reader(actor)
        entry = HrAttendanceEntry
        submission = HrSiteAttendanceSubmission
        query = (
            select(entry, HrEmployee, submission)
            .join(HrEmployee, HrEmployee.id == entry.employee_id)
            .join(Project, Project.id == entry.project_id)
            .join(
                submission,
                (submission.entry_id == entry.id)
                & (submission.submission_revision == entry.site_submission_revision),
            )
            .where(entry.source == "site", Project.deleted_at.is_(None))
        )
        if actor.role != ROLE_HR_MANAGER:
            scoped = await accessible_project_ids(self.session, actor)
            if scoped is not None:
                query = query.where(entry.project_id.in_(scoped))
        if project_id is not None:
            query = query.where(entry.project_id == project_id)
        if work_date is not None:
            query = query.where(entry.work_date == work_date)
        if entry_id is not None:
            query = query.where(entry.id == entry_id)
        count_query = query.with_only_columns(
            func.count(),
            func.count().filter(entry.attendance_status == "present", entry.status != "returned"),
            func.count().filter(
                entry.attendance_status == "present",
                entry.status == "approved",
                submission.engineer_decision == "approved",
                submission.hr_decision == "approved",
            ),
        )
        total, present, confirmed = (await self.session.execute(count_query)).one()
        rows = await self.session.execute(
            query.order_by(entry.work_date.desc(), HrEmployee.full_name, entry.id)
            .limit(limit)
            .offset(offset)
        )
        return SiteAttendancePageResponse(
            items=[self._response(record, worker, route) for record, worker, route in rows],
            total=total,
            submitted_present=present,
            confirmed_present=confirmed,
        )

    async def history(self, entry_id: UUID, actor: User) -> list[SiteAttendanceSubmissionResponse]:
        self._ensure_reader(actor)
        entry = await self._require_entry(entry_id)
        await self._ensure_scope(entry, actor)
        history = await self.session.scalars(
            select(HrSiteAttendanceSubmission)
            .where(HrSiteAttendanceSubmission.entry_id == entry_id)
            .order_by(HrSiteAttendanceSubmission.submission_revision.desc())
        )
        return [SiteAttendanceSubmissionResponse.model_validate(row) for row in history]

    async def submit(
        self, payload: SiteAttendanceCreateRequest, actor: User
    ) -> SiteAttendanceResponse:
        self._ensure_submitter(actor)
        await self._ensure_active_project(payload.project_id, actor)
        employee = await self._require_worker(payload)
        entry = await self.workforce.prepare_attendance(payload, actor, employee)
        entry.site_submission_revision = 1
        self.session.add(entry)
        await self.session.flush()
        return await self._save_submission(entry, payload, employee, actor)

    async def correct(
        self, entry_id: UUID, payload: SiteAttendanceCorrectionRequest, actor: User
    ) -> SiteAttendanceResponse:
        self._ensure_submitter(actor)
        await self._ensure_active_project(payload.project_id, actor)
        employee = await self._require_worker(payload)
        entry = await self._require_entry(entry_id, lock=True)
        if (
            entry.recorded_by_id != actor.id
            or entry.project_id != payload.project_id
            or entry.employee_id != employee.id
            or entry.work_date != payload.work_date
        ):
            raise NotFoundException("Site attendance")
        verify_request_revision(entry, payload.expected_revision)
        if entry.status not in {"returned", "approved"}:
            raise AppException(
                "Only returned or previously checked attendance may be corrected.", status_code=409
            )
        replacement = await self.workforce.prepare_attendance(
            payload,
            actor,
            employee,
            replacing_site_entry=entry.id,
        )
        entry.attendance_status = replacement.attendance_status
        entry.check_in_at = replacement.check_in_at
        entry.check_out_at = replacement.check_out_at
        entry.worked_hours = replacement.worked_hours
        entry.calendar_id = replacement.calendar_id
        entry.shift_assignment_id = replacement.shift_assignment_id
        entry.scheduled_workday = replacement.scheduled_workday
        entry.notes = replacement.notes
        entry.status = "submitted"
        entry.review_note = None
        entry.approved_by_id = None
        entry.approved_at = None
        entry.record_revision += 1
        entry.site_submission_revision = (entry.site_submission_revision or 0) + 1
        return await self._save_submission(entry, payload, employee, actor)

    async def decide(
        self, entry_id: UUID, payload: SiteAttendanceDecisionRequest, actor: User
    ) -> SiteAttendanceResponse:
        expected_role = ROLE_HR_MANAGER if payload.stage == "hr" else ROLE_MEP_PROJECT_MANAGER
        if actor.role != expected_role:
            raise PermissionDeniedException("perform this site attendance review")
        if actor.role == ROLE_HR_MANAGER:
            ensure_permission(actor, PERMISSION_HR_ATTENDANCE_APPROVE)
        initial = await self._require_entry(entry_id)
        await self._ensure_scope(initial, actor)
        employee = await self.workforce._require_employee(initial.employee_id, for_update=True)
        entry = await self._require_entry(entry_id, lock=True)
        verify_request_revision(entry, payload.expected_revision)
        submission = await self.session.get(
            HrSiteAttendanceSubmission, (entry.id, entry.site_submission_revision)
        )
        if submission is None:
            raise NotFoundException("Site attendance submission")
        stage = self._stage(entry, submission)
        if stage != f"pending_{payload.stage}":
            raise AppException("This attendance stage is no longer open.", status_code=409)
        if (
            actor.id in {submission.submitted_by, employee.user_id}
            or (payload.stage == "engineer" and actor.id != submission.engineer_id)
            or (payload.stage == "hr" and actor.id == submission.engineer_id)
        ):
            raise PermissionDeniedException("review this site attendance")
        requirements = SiteAttendanceCreateRequest.model_validate(submission.requirements)
        await self._ensure_active_project(requirements.project_id, actor)
        await self._require_worker(requirements)
        await self.workforce._ensure_attendance_period_open(employee.id, entry.work_date)
        if payload.stage == "engineer":
            await ApprovalService(self.session).require_project_reviewer(
                requirements.project_id,
                ROLE_MEP_PROJECT_MANAGER,
                approver_id=actor.id,
                excluded_user_ids={submission.submitted_by},
            )
        comments = (payload.comments or "").strip() or None
        if payload.decision != "approved" and comments is None:
            raise AppException(
                "Give a reason for returning or rejecting attendance.",
                status_code=422,
                error_code="DECISION_REASON_REQUIRED",
            )
        now = utc_now()
        if payload.stage == "engineer":
            submission.engineer_decision = payload.decision
            submission.engineer_comments = comments
            submission.engineer_decided_at = now
        else:
            submission.hr_id = actor.id
            submission.hr_decision = payload.decision
            submission.hr_comments = comments
            submission.hr_decided_at = now
        if payload.decision != "approved":
            entry.status = "returned"
            entry.review_note = comments
            await self._notify(
                submission.submitted_by,
                entry,
                f"Site attendance {payload.decision}",
                comments or "",
            )
        elif payload.stage == "engineer":
            reviewers = await self._hr_reviewers(
                {submission.submitted_by, submission.engineer_id, employee.user_id}
            )
            for reviewer_id in reviewers:
                await self._notify(
                    reviewer_id,
                    entry,
                    "Site attendance awaiting HR verification",
                    "The project engineer approved this submission.",
                )
        else:
            entry.status = "approved"
            entry.approved_by_id = actor.id
            entry.approved_at = now
            await self._notify(
                submission.submitted_by,
                entry,
                "Site attendance verified",
                "The engineer and HR reviews are complete.",
            )
        entry.record_revision += 1
        await self.workforce.audit.record(
            action=f"hr.site_attendance.{payload.stage}.{payload.decision}",
            user_id=actor.id,
            entity_type="hr_attendance_entries",
            entity_id=entry.id,
            comments=comments,
            new_values={
                "submission_revision": submission.submission_revision,
                "status": entry.status,
            },
        )
        await self.session.commit()
        return self._response(entry, employee, submission)

    async def _save_submission(
        self,
        entry: HrAttendanceEntry,
        payload: SiteAttendanceCreateRequest,
        employee: HrEmployee,
        actor: User,
    ) -> SiteAttendanceResponse:
        excluded = {actor.id}
        if employee.user_id:
            excluded.add(employee.user_id)
        engineer = await ApprovalService(self.session).require_project_reviewer(
            payload.project_id,
            ROLE_MEP_PROJECT_MANAGER,
            excluded_user_ids=excluded,
        )
        await self._hr_reviewers({*excluded, engineer.id})
        submission = HrSiteAttendanceSubmission(
            entry_id=entry.id,
            submission_revision=entry.site_submission_revision,
            submitted_by=actor.id,
            engineer_id=engineer.id,
            requirements=payload.model_dump(mode="json", exclude={"expected_revision"}),
        )
        self.session.add(submission)
        await self.session.flush()
        await self.workforce.audit.record(
            action="hr.site_attendance.submitted",
            user_id=actor.id,
            entity_type="hr_attendance_entries",
            entity_id=entry.id,
            new_values={"submission_revision": submission.submission_revision},
        )
        await self._notify(
            engineer.id,
            entry,
            "Site attendance awaiting engineer review",
            "Review the site record.",
        )
        await self.session.commit()
        return self._response(entry, employee, submission)

    async def _hr_reviewers(self, excluded: set[UUID | None]) -> list[UUID]:
        reviewers = list(
            await self.session.scalars(
                select(User.id)
                .where(
                    User.role == ROLE_HR_MANAGER,
                    User.is_active.is_(True),
                    User.deleted_at.is_(None),
                    User.id.not_in({user_id for user_id in excluded if user_id is not None}),
                )
                .order_by(User.id)
            )
        )
        if not reviewers:
            raise AppException(
                "An independent active HR Manager must be available for the second check.",
                status_code=409,
                error_code="APPROVER_NOT_CONFIGURED",
            )
        return reviewers

    @staticmethod
    def _worker_eligibility(project_id: UUID, work_date: date) -> tuple[ColumnElement[bool], ...]:
        daily_roster = select(HrRosterAllocation.id).where(
            HrRosterAllocation.employee_id == HrEmployee.id,
            HrRosterAllocation.work_date == work_date,
            HrRosterAllocation.cancelled_at.is_(None),
        )
        project_shift = select(HrShiftAssignment.id).where(
            HrShiftAssignment.employee_id == HrEmployee.id,
            HrShiftAssignment.project_id == project_id,
            HrShiftAssignment.effective_from <= work_date,
            or_(
                HrShiftAssignment.effective_to.is_(None),
                HrShiftAssignment.effective_to >= work_date,
            ),
        )
        return (
            HrEmployee.deleted_at.is_(None),
            HrEmployee.employment_status.in_(REVIEW_EMPLOYMENT_STATES),
            or_(HrEmployee.join_date.is_(None), HrEmployee.join_date <= work_date),
            or_(HrEmployee.termination_date.is_(None), HrEmployee.termination_date > work_date),
            or_(
                daily_roster.where(HrRosterAllocation.project_id == project_id).exists(),
                ~daily_roster.exists() & project_shift.exists(),
            ),
        )

    async def _require_worker(self, payload: SiteAttendanceCreateRequest) -> HrEmployee:
        if payload.work_date > business_today():
            raise AppException(
                "Site attendance cannot be recorded for a future date.", status_code=422
            )
        worker = await self.session.scalar(
            select(HrEmployee)
            .where(
                HrEmployee.id == payload.employee_id,
                *self._worker_eligibility(payload.project_id, payload.work_date),
            )
            .with_for_update()
        )
        if worker is None:
            raise NotFoundException("Eligible assigned worker")
        return worker

    async def _require_entry(self, entry_id: UUID, *, lock: bool = False) -> HrAttendanceEntry:
        query = select(HrAttendanceEntry).where(
            HrAttendanceEntry.id == entry_id,
            HrAttendanceEntry.source == "site",
        )
        if lock:
            query = query.with_for_update().execution_options(populate_existing=True)
        entry = await self.session.scalar(query)
        if entry is None:
            raise NotFoundException("Site attendance")
        return entry

    async def _ensure_scope(self, entry: HrAttendanceEntry, actor: User) -> None:
        if actor.role != ROLE_HR_MANAGER:
            scope = await accessible_project_ids(self.session, actor)
            if scope is not None and entry.project_id not in scope:
                raise NotFoundException("Site attendance")

    async def _ensure_active_project(self, project_id: UUID, actor: User) -> None:
        if actor.role != ROLE_HR_MANAGER:
            await ensure_project_access(self.session, project_id, actor)
        if not await self.session.scalar(
            select(Project.id)
            .where(
                Project.id == project_id,
                Project.status == "active",
                Project.deleted_at.is_(None),
            )
            .with_for_update(read=True)
        ):
            raise NotFoundException("Active project")

    @staticmethod
    def _ensure_submitter(actor: User) -> None:
        if actor.role not in SUPERVISOR_ROLES:
            raise PermissionDeniedException("submit site attendance")

    @staticmethod
    def _ensure_reader(actor: User) -> None:
        if actor.role == ROLE_HR_MANAGER:
            ensure_permission(actor, PERMISSION_HR_ATTENDANCE_APPROVE)
        if actor.role not in SITE_ATTENDANCE_ROLES:
            raise PermissionDeniedException("read site attendance")

    @staticmethod
    def _stage(
        entry: HrAttendanceEntry,
        submission: HrSiteAttendanceSubmission,
    ) -> Literal["pending_engineer", "pending_hr", "approved", "returned", "rejected"]:
        if entry.status == "approved":
            return "approved"
        if entry.status == "returned":
            return (
                "rejected"
                if "rejected" in {submission.engineer_decision, submission.hr_decision}
                else "returned"
            )
        return "pending_hr" if submission.engineer_decision == "approved" else "pending_engineer"

    @classmethod
    def _response(
        cls, entry: HrAttendanceEntry, employee: HrEmployee, submission: HrSiteAttendanceSubmission
    ) -> SiteAttendanceResponse:
        return SiteAttendanceResponse(
            id=entry.id,
            record_revision=entry.record_revision,
            worker=SiteAttendanceWorker(
                id=employee.id, employee_code=employee.employee_code, full_name=employee.full_name
            ),
            stage=cls._stage(entry, submission),
            submission=SiteAttendanceSubmissionResponse.model_validate(submission),
        )

    async def _notify(self, user_id: UUID, entry: HrAttendanceEntry, title: str, body: str) -> None:
        await self.notifications.create(
            user_id=user_id,
            title=title,
            body=append_link(
                body,
                label="Open site attendance",
                url=build_frontend_url(
                    "/hr/site-attendance", query={"attendanceId": str(entry.id)}
                ),
            ),
            notification_type="hr",
            reference_type="hr_attendance_entries",
            reference_id=entry.id,
        )
