from datetime import UTC, date, datetime, time
from math import ceil
from typing import Literal, cast
from uuid import UUID
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from sqlalchemy import func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.sql.elements import ColumnElement

from app.models.hr import (
    HrAttendanceEntry,
    HrEmployee,
    HrHoliday,
    HrRosterAllocation,
    HrShiftAssignment,
    HrSiteAttendanceSubmission,
    HrWorkCalendar,
)
from app.models.project import Project
from app.models.user import User
from app.schemas.hr import (
    SiteAttendanceArrivalAssessment,
    SiteAttendanceCompleteness,
    SiteAttendanceCorrectionRequest,
    SiteAttendanceCreateRequest,
    SiteAttendanceDecisionRequest,
    SiteAttendancePageResponse,
    SiteAttendanceProjectOption,
    SiteAttendanceResponse,
    SiteAttendanceSubmissionResponse,
    SiteAttendanceWorker,
    SiteAttendanceWorkerPage,
)
from app.services.approval_service import ApprovalService
from app.services.authorization import accessible_project_ids, ensure_project_access
from app.services.hr_manager_review import REVIEW_EMPLOYMENT_STATES, verify_request_revision
from app.services.hr_payroll_snapshot import lock_payroll_periods
from app.services.hr_site_eligibility import historical_site_employment
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

    async def project_options(
        self,
        actor: User,
        *,
        historical: bool,
        search: str | None,
        limit: int,
        offset: int,
    ) -> list[SiteAttendanceProjectOption]:
        if actor.role not in SITE_ATTENDANCE_ROLES:
            raise PermissionDeniedException("read site attendance project options")
        statuses = ("active", "completed") if historical else ("active",)
        query = select(Project).where(
            Project.deleted_at.is_(None),
            Project.status.in_(statuses),
        )
        scope = await accessible_project_ids(self.session, actor)
        if scope is not None:
            if not scope:
                return []
            query = query.where(Project.id.in_(scope))
        if search and search.strip():
            term = f"%{search.strip()}%"
            query = query.where(or_(Project.name.ilike(term), Project.code.ilike(term)))
        rows = await self.session.scalars(
            query.order_by(Project.name, Project.id).limit(limit).offset(offset)
        )
        return [
            SiteAttendanceProjectOption(
                id=project.id,
                code=project.code,
                name=project.name,
                status=cast(Literal["active", "completed"], project.status),
            )
            for project in rows
        ]

    async def list_workers(
        self,
        project_id: UUID,
        work_date: date,
        actor: User,
        *,
        search: str | None,
        limit: int,
        offset: int,
        historical: bool = False,
    ) -> SiteAttendanceWorkerPage:
        self._ensure_submitter(actor)
        if historical and work_date >= business_today():
            raise AppException(
                "Historical attendance is limited to past work dates.",
                status_code=422,
                error_code="HISTORICAL_DATE_INVALID",
            )
        await self._ensure_attendance_project(project_id, actor, historical=historical)
        query = select(HrEmployee.id, HrEmployee.employee_code, HrEmployee.full_name).where(
            *self._worker_eligibility(project_id, work_date, historical=historical)
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

    async def completeness(
        self, project_id: UUID, work_date: date, actor: User, *, limit: int, offset: int
    ) -> SiteAttendanceCompleteness:
        self._ensure_reader(actor)
        if actor.role != ROLE_HR_MANAGER:
            await ensure_project_access(self.session, project_id, actor)
        if not await self.session.scalar(
            select(Project.id).where(Project.id == project_id, Project.deleted_at.is_(None))
        ):
            raise NotFoundException("Project")
        entry = HrAttendanceEntry
        review = HrSiteAttendanceSubmission
        recorded = select(entry.id).where(
            entry.employee_id == HrEmployee.id,
            entry.project_id == project_id,
            entry.work_date == work_date,
            entry.source == "site",
            entry.status != "historical",
        )
        confirmed = recorded.join(
            review,
            (review.entry_id == entry.id)
            & (review.submission_revision == entry.site_submission_revision),
        ).where(
            entry.status == "approved",
            review.engineer_decision == "approved",
            review.hr_decision == "approved",
            review.hr_id == entry.approved_by_id,
        )
        scope = self._worker_eligibility(project_id, work_date, historical=True)
        _, employment_unresolved = historical_site_employment(work_date)
        _, assignment_unresolved = self._project_assignment_state(project_id, work_date)
        target_roster = select(HrRosterAllocation.id).where(
            HrRosterAllocation.employee_id == HrEmployee.id,
            HrRosterAllocation.project_id == project_id,
            HrRosterAllocation.work_date == work_date,
            HrRosterAllocation.cancelled_at.is_(None),
        )
        target_shift = select(HrShiftAssignment.id).where(
            HrShiftAssignment.employee_id == HrEmployee.id,
            HrShiftAssignment.project_id == project_id,
            HrShiftAssignment.effective_from <= work_date,
            or_(
                HrShiftAssignment.effective_to.is_(None),
                HrShiftAssignment.effective_to >= work_date,
            ),
        )
        expected, entered, verified = (
            await self.session.execute(
                select(
                    func.count(),
                    func.count().filter(recorded.exists()),
                    func.count().filter(confirmed.exists()),
                )
                .select_from(HrEmployee)
                .where(*scope)
            )
        ).one()
        unresolved_workers = int(
            await self.session.scalar(
                select(func.count(HrEmployee.id)).where(
                    HrEmployee.deleted_at.is_(None),
                    or_(
                        assignment_unresolved,
                        employment_unresolved & or_(target_roster.exists(), target_shift.exists()),
                    ),
                )
            )
            or 0
        )
        rows = await self.session.execute(
            select(HrEmployee.id, HrEmployee.employee_code, HrEmployee.full_name)
            .where(*scope, ~recorded.exists())
            .order_by(HrEmployee.full_name, HrEmployee.id)
            .limit(limit)
            .offset(offset)
        )
        return SiteAttendanceCompleteness(
            expected_workers=expected,
            recorded_workers=entered,
            confirmed_workers=verified,
            missing_workers=expected - entered,
            unresolved_workers=unresolved_workers,
            is_complete=expected > 0 and expected == verified and unresolved_workers == 0,
            empty_roster=expected == 0 and unresolved_workers == 0,
            items=[
                SiteAttendanceWorker(id=id_, employee_code=code, full_name=name)
                for id_, code, name in rows
            ],
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
        historical = payload.historical_remediation
        if historical and payload.work_date >= business_today():
            raise AppException(
                "Historical attendance is limited to past work dates.",
                status_code=422,
                error_code="HISTORICAL_DATE_INVALID",
            )
        await lock_payroll_periods(self.session)
        await self._ensure_attendance_project(payload.project_id, actor, historical=historical)
        employee = await self._require_worker(payload, historical=historical)
        entry = await self.workforce.prepare_attendance(payload, actor, employee)
        entry.site_submission_revision = 1
        self.session.add(entry)
        await self.session.flush()
        return await self._save_submission(entry, payload, employee, actor)

    async def correct(
        self, entry_id: UUID, payload: SiteAttendanceCorrectionRequest, actor: User
    ) -> SiteAttendanceResponse:
        self._ensure_submitter(actor)
        initial_entry = await self._require_entry(entry_id)
        initial_submission = await self.session.get(
            HrSiteAttendanceSubmission,
            (initial_entry.id, initial_entry.site_submission_revision),
        )
        if initial_submission is None:
            raise NotFoundException("Site attendance submission")
        original_requirements = initial_submission.requirements
        original_historical = isinstance(original_requirements, dict) and bool(
            original_requirements.get("historical_remediation")
            or original_requirements.get("historical_reason")
        )
        historical = payload.historical_remediation
        if original_historical and not historical:
            raise AppException(
                "Historical corrections must retain the historical remediation reason.",
                status_code=422,
                error_code="HISTORICAL_REASON_REQUIRED",
            )
        if historical and payload.work_date >= business_today():
            raise AppException(
                "Historical attendance is limited to past work dates.",
                status_code=422,
                error_code="HISTORICAL_DATE_INVALID",
            )
        await lock_payroll_periods(self.session)
        await self._ensure_attendance_project(payload.project_id, actor, historical=historical)
        employee = await self._require_worker(payload, historical=historical)
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
        await lock_payroll_periods(self.session)
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
        historical = requirements.historical_remediation
        await self._ensure_attendance_project(
            requirements.project_id, actor, historical=historical
        )
        await self._require_worker(requirements, historical=historical)
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
        requirements = payload.model_dump(mode="json", exclude={"expected_revision"})
        scheduled_start, arrival_variance, assessment = await self._arrival_schedule_snapshot(
            payload, employee
        )
        requirements["scheduled_start_at"] = (
            scheduled_start.isoformat().replace("+00:00", "Z") if scheduled_start else None
        )
        requirements["arrival_variance_seconds"] = arrival_variance
        requirements["arrival_assessment"] = assessment.model_dump(mode="json")
        submission = HrSiteAttendanceSubmission(
            entry_id=entry.id,
            submission_revision=entry.site_submission_revision,
            submitted_by=actor.id,
            engineer_id=engineer.id,
            requirements=requirements,
        )
        self.session.add(submission)
        await self.session.flush()
        await self.workforce.audit.record(
            action="hr.site_attendance.submitted",
            user_id=actor.id,
            entity_type="hr_attendance_entries",
            entity_id=entry.id,
            new_values={
                "submission_revision": submission.submission_revision,
                **(
                    {"correction_reason": payload.correction_reason}
                    if isinstance(payload, SiteAttendanceCorrectionRequest)
                    else {}
                ),
                **(
                    {"historical_reason": payload.historical_reason}
                    if payload.historical_reason is not None
                    else {}
                ),
            },
        )
        await self._notify(
            engineer.id,
            entry,
            "Site attendance awaiting engineer review",
            "Review the site record.",
        )
        await self.session.commit()
        return self._response(entry, employee, submission)

    async def _arrival_schedule_snapshot(
        self, payload: SiteAttendanceCreateRequest, employee: HrEmployee
    ) -> tuple[datetime | None, int | None, SiteAttendanceArrivalAssessment]:
        """Freeze the applicable schedule and factual arrival comparison at submission."""
        scheduled_start: datetime | None = None
        source: Literal["roster", "shift", "calendar"] | None = None
        source_reference_id: UUID | None = None
        timezone_name: str | None = None
        roster_rows = list(
            await self.session.scalars(
                select(HrRosterAllocation).where(
                    HrRosterAllocation.employee_id == employee.id,
                    HrRosterAllocation.work_date == payload.work_date,
                    HrRosterAllocation.cancelled_at.is_(None),
                )
            )
        )
        if len(roster_rows) == 1 and roster_rows[0].project_id == payload.project_id:
            roster = roster_rows[0]
            scheduled_start = roster.starts_at
            source = "roster"
            source_reference_id = roster.id
            timezone_name = roster.timezone
        elif roster_rows:
            return self._unresolved_arrival()
        else:
            applicable_calendar = (
                HrWorkCalendar.status == "published",
                HrWorkCalendar.deleted_at.is_(None),
                HrWorkCalendar.effective_from <= payload.work_date,
                HrWorkCalendar.effective_to >= payload.work_date,
            )
            shift_rows = list(
                (
                    await self.session.execute(
                        select(HrShiftAssignment, HrWorkCalendar)
                        .join(HrWorkCalendar, HrWorkCalendar.id == HrShiftAssignment.calendar_id)
                        .where(
                            HrShiftAssignment.employee_id == employee.id,
                            HrShiftAssignment.effective_from <= payload.work_date,
                            or_(
                                HrShiftAssignment.effective_to.is_(None),
                                HrShiftAssignment.effective_to >= payload.work_date,
                            ),
                            or_(
                                HrShiftAssignment.project_id == payload.project_id,
                                HrShiftAssignment.project_id.is_(None),
                            ),
                            *applicable_calendar,
                        )
                    )
                ).all()
            )
            project_shifts = [row for row in shift_rows if row[0].project_id == payload.project_id]
            global_shifts = [row for row in shift_rows if row[0].project_id is None]
            candidates = project_shifts if project_shifts else global_shifts
            if len(candidates) == 1:
                shift, calendar = candidates[0]
                scheduled_start = self._local_schedule_start(
                    payload.work_date, shift.start_time, calendar.timezone
                )
                source = "shift"
                source_reference_id = shift.id
                timezone_name = calendar.timezone
            elif len(candidates) > 1:
                return self._unresolved_arrival()
            else:
                calendar_rows = list(
                    await self.session.scalars(
                        select(HrWorkCalendar).where(
                            *applicable_calendar,
                            or_(
                                HrWorkCalendar.id == employee.work_calendar_id,
                                HrWorkCalendar.project_id == payload.project_id,
                                (
                                    HrWorkCalendar.project_id.is_(None)
                                    & HrWorkCalendar.is_default.is_(True)
                                ),
                            ),
                        )
                    )
                )
                calendar_rows = [
                    calendar
                    for calendar in calendar_rows
                    if calendar.project_id in {None, payload.project_id}
                ]
                if not calendar_rows:
                    return self._unresolved_arrival()

                def priority(calendar: HrWorkCalendar) -> int:
                    if calendar.id == employee.work_calendar_id:
                        return 0
                    if calendar.project_id == payload.project_id:
                        return 1
                    return 2

                best_priority = min(map(priority, calendar_rows))
                calendars = [row for row in calendar_rows if priority(row) == best_priority]
                if len(calendars) != 1:
                    return self._unresolved_arrival()
                calendar = calendars[0]
                weekday = ("MON", "TUE", "WED", "THU", "FRI", "SAT", "SUN")[
                    payload.work_date.weekday()
                ]
                holiday = await self.session.scalar(
                    select(HrHoliday.id).where(
                        HrHoliday.calendar_id == calendar.id,
                        HrHoliday.holiday_date == payload.work_date,
                    )
                )
                if holiday is not None or weekday not in calendar.work_days_json:
                    return self._not_applicable_arrival(calendar.timezone, calendar.id)
                scheduled_start = self._local_schedule_start(
                    payload.work_date, calendar.standard_start_time, calendar.timezone
                )
                source = "calendar"
                source_reference_id = calendar.id
                timezone_name = calendar.timezone

        if scheduled_start is None or scheduled_start.tzinfo is None or source is None:
            return self._unresolved_arrival()
        try:
            ZoneInfo(timezone_name or "")
        except (ValueError, ZoneInfoNotFoundError):
            return self._unresolved_arrival()
        scheduled_utc = scheduled_start.astimezone(UTC)
        check_in = payload.check_in_at
        if payload.attendance_status != "present":
            assessment = SiteAttendanceArrivalAssessment(
                scheduled_start_at=scheduled_utc,
                timezone=timezone_name,
                source=source,
                source_reference_id=source_reference_id,
                status="not_applicable",
            )
            return scheduled_utc, None, assessment
        if check_in is None or check_in.tzinfo is None:
            assessment = SiteAttendanceArrivalAssessment(
                scheduled_start_at=scheduled_utc,
                timezone=timezone_name,
                source=source,
                source_reference_id=source_reference_id,
                status="unresolved",
            )
            return scheduled_utc, None, assessment
        arrival_utc = check_in.astimezone(UTC)
        seconds = (arrival_utc - scheduled_utc).total_seconds()
        variance_seconds = round(seconds)
        assessment = SiteAttendanceArrivalAssessment(
            scheduled_start_at=scheduled_utc,
            timezone=timezone_name,
            source=source,
            source_reference_id=source_reference_id,
            status="after_scheduled_start" if seconds > 0 else "on_time",
            minutes_after_start=ceil(seconds / 60) if seconds > 0 else None,
        )
        return scheduled_utc, variance_seconds, assessment

    @staticmethod
    def _unresolved_arrival(
    ) -> tuple[None, None, SiteAttendanceArrivalAssessment]:
        return None, None, SiteAttendanceArrivalAssessment(status="unresolved")

    @staticmethod
    def _not_applicable_arrival(
        timezone_name: str | None, source_reference_id: UUID
    ) -> tuple[None, None, SiteAttendanceArrivalAssessment]:
        return (
            None,
            None,
            SiteAttendanceArrivalAssessment(
                timezone=timezone_name,
                source="calendar",
                source_reference_id=source_reference_id,
                status="not_applicable",
            ),
        )

    @staticmethod
    def _local_schedule_start(
        work_date: date, start_time: time, timezone_name: str | None
    ) -> datetime | None:
        if not timezone_name:
            return None
        try:
            return datetime.combine(work_date, start_time, tzinfo=ZoneInfo(timezone_name))
        except (ValueError, ZoneInfoNotFoundError):
            return None

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
    def _project_assignment(project_id: UUID, work_date: date) -> ColumnElement[bool]:
        assignment, _ = HrSiteAttendanceService._project_assignment_state(project_id, work_date)
        return assignment

    @staticmethod
    def _project_assignment_state(
        project_id: UUID, work_date: date
    ) -> tuple[ColumnElement[bool], ColumnElement[bool]]:
        daily_roster = select(HrRosterAllocation.id).where(
            HrRosterAllocation.employee_id == HrEmployee.id,
            HrRosterAllocation.work_date == work_date,
            HrRosterAllocation.cancelled_at.is_(None),
        )
        target_roster = daily_roster.where(HrRosterAllocation.project_id == project_id)
        roster_count = (
            select(func.count(HrRosterAllocation.id))
            .where(
                HrRosterAllocation.employee_id == HrEmployee.id,
                HrRosterAllocation.work_date == work_date,
                HrRosterAllocation.cancelled_at.is_(None),
            )
            .correlate(HrEmployee)
            .scalar_subquery()
        )
        project_shifts = select(HrShiftAssignment.id).where(
            HrShiftAssignment.employee_id == HrEmployee.id,
            HrShiftAssignment.project_id.is_not(None),
            HrShiftAssignment.effective_from <= work_date,
            or_(
                HrShiftAssignment.effective_to.is_(None),
                HrShiftAssignment.effective_to >= work_date,
            ),
        )
        target_project_shift = project_shifts.where(HrShiftAssignment.project_id == project_id)
        project_shift_count = (
            select(func.count(HrShiftAssignment.id))
            .where(
                HrShiftAssignment.employee_id == HrEmployee.id,
                HrShiftAssignment.project_id.is_not(None),
                HrShiftAssignment.effective_from <= work_date,
                or_(
                    HrShiftAssignment.effective_to.is_(None),
                    HrShiftAssignment.effective_to >= work_date,
                ),
            )
            .correlate(HrEmployee)
            .scalar_subquery()
        )
        assignment = or_(
            (roster_count == 1) & target_roster.exists(),
            (roster_count == 0)
            & (project_shift_count == 1)
            & target_project_shift.exists(),
        )
        conflict = ((roster_count > 1) & target_roster.exists()) | (
            (roster_count == 0)
            & (project_shift_count > 1)
            & target_project_shift.exists()
        )
        return assignment, conflict

    @staticmethod
    def _worker_eligibility(
        project_id: UUID, work_date: date, *, historical: bool = False
    ) -> tuple[ColumnElement[bool], ...]:
        assignment = HrSiteAttendanceService._project_assignment(project_id, work_date)
        if historical:
            eligible, _ = historical_site_employment(work_date)
            return HrEmployee.deleted_at.is_(None), eligible, assignment
        return (
            HrEmployee.deleted_at.is_(None),
            HrEmployee.employment_status.in_(REVIEW_EMPLOYMENT_STATES),
            or_(HrEmployee.join_date.is_(None), HrEmployee.join_date <= work_date),
            or_(HrEmployee.termination_date.is_(None), HrEmployee.termination_date > work_date),
            assignment,
        )

    async def _require_worker(
        self, payload: SiteAttendanceCreateRequest, *, historical: bool = False
    ) -> HrEmployee:
        if payload.work_date > business_today():
            raise AppException(
                "Site attendance cannot be recorded for a future date.", status_code=422
            )
        worker = await self.session.scalar(
            select(HrEmployee)
            .where(
                HrEmployee.id == payload.employee_id,
                *self._worker_eligibility(
                    payload.project_id, payload.work_date, historical=historical
                ),
            )
            .with_for_update()
        )
        if worker is None:
            if historical:
                _, unresolved = historical_site_employment(payload.work_date)
                unresolved_for_worker = await self.session.scalar(
                    select(unresolved)
                    .select_from(HrEmployee)
                    .where(HrEmployee.id == payload.employee_id)
                )
                if unresolved_for_worker:
                    raise AppException(
                        "Historical employment dates require HR reconciliation before "
                        "attendance can be recorded.",
                        status_code=409,
                        error_code="HISTORICAL_EMPLOYMENT_UNRESOLVED",
                    )
                _, assignment_unresolved = self._project_assignment_state(
                    payload.project_id, payload.work_date
                )
                assignment_conflict = await self.session.scalar(
                    select(assignment_unresolved)
                    .select_from(HrEmployee)
                    .where(
                        HrEmployee.id == payload.employee_id,
                        HrEmployee.deleted_at.is_(None),
                    )
                )
                if assignment_conflict:
                    raise AppException(
                        "Historical project assignments conflict for this worker and date; "
                        "HR reconciliation is required.",
                        status_code=409,
                        error_code="HISTORICAL_ASSIGNMENT_CONFLICT",
                    )
            elif await self.session.scalar(
                select(
                    historical_site_employment(payload.work_date)[0]
                    & self._project_assignment(payload.project_id, payload.work_date)
                )
                .select_from(HrEmployee)
                .where(HrEmployee.id == payload.employee_id)
            ):
                raise AppException(
                    "A historical reason is required for a former or otherwise "
                    "ineligible employee.",
                    status_code=422,
                    error_code="HISTORICAL_REASON_REQUIRED",
                )
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

    async def _ensure_attendance_project(
        self, project_id: UUID, actor: User, *, historical: bool
    ) -> None:
        if actor.role != ROLE_HR_MANAGER:
            await ensure_project_access(self.session, project_id, actor)
        status = await self.session.scalar(
            select(Project.status)
            .where(
                Project.id == project_id,
                Project.deleted_at.is_(None),
            )
            .with_for_update(read=True)
        )
        if status == "active":
            return
        if historical and status == "completed":
            return
        if status == "completed" and not historical:
            raise AppException(
                "A reasoned historical attendance submission is required for a completed project.",
                status_code=409,
                error_code="HISTORICAL_REASON_REQUIRED",
            )
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
