from uuid import UUID

from sqlalchemy import Select, and_, case, cast, func, literal, or_, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import aliased
from sqlalchemy.types import Date, Integer

from app.models.daily_report import DailyReport
from app.models.document import Document
from app.models.hr import (
    HrAttendanceEntry,
    HrEmployee,
    HrEmployeePrivate,
    HrEmploymentPeriod,
    HrSiteAttendanceSubmission,
)
from app.models.inventory import InventoryRegistration, MaterialRequest
from app.models.notification import Notification
from app.models.project import Project
from app.models.project_member import ProjectMember
from app.models.supervisor_update import SupervisorUpdate
from app.models.user import User
from app.schemas.dashboard import (
    AnniversaryItem,
    AnniversaryPageResponse,
    BirthdayItem,
    BirthdayPageResponse,
    DashboardSummaryResponse,
    SiteOperationsSummary,
)
from app.services.approval_service import MATERIAL_STAGE_STATES
from app.utils.permissions import (
    COMPANY_RESOURCE_ROLES,
    PERMISSION_DASHBOARD_COMPANY,
    PERMISSION_REPORTS_VIEW,
    PROJECT_OPERATIONAL_MANAGER_ROLES,
    has_permission,
)
from app.utils.time import business_today

ACTIVE_EMPLOYMENT_STATUSES = ("active", "on_probation", "on_leave", "notice_period")


class DashboardService:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def summary(self, actor: User) -> DashboardSummaryResponse:
        project_ids = await self._visible_project_ids(actor)
        active_projects = await self._count_projects(project_ids)
        pending_reports = await self._count_reports(project_ids, "submitted")
        approved_reports = await self._count_reports(project_ids, "approved")
        pending_documents = await self._count_documents(project_ids)
        unread_notifications = await self._count_notifications(actor)
        recent_activity: list[str] = []
        if has_permission(actor, PERMISSION_REPORTS_VIEW):
            recent_project_ids = (
                None
                if actor.role in COMPANY_RESOURCE_ROLES
                else await self._assigned_project_ids(actor)
            )
            recent_activity = await self._recent_activity(recent_project_ids)
        return DashboardSummaryResponse(
            active_projects=active_projects,
            pending_reports=pending_reports,
            approved_reports=approved_reports,
            pending_documents=pending_documents,
            unread_notifications=unread_notifications,
            recent_activity=recent_activity,
            site_operations=(
                await self._site_operations(project_ids)
                if actor.role in PROJECT_OPERATIONAL_MANAGER_ROLES
                else None
            ),
        )

    async def upcoming_birthdays(self, *, offset: int, limit: int) -> BirthdayPageResponse:
        today = business_today()
        offsets = func.generate_series(0, 6).table_valued("day_offset").render_derived()
        occurrence = cast(literal(today) + offsets.c.day_offset, Date)
        active_period_count = (
            select(func.count(HrEmploymentPeriod.id))
            .where(
                HrEmploymentPeriod.employee_id == HrEmployee.id,
                HrEmploymentPeriod.ended_on.is_(None),
            )
            .correlate(HrEmployee)
            .scalar_subquery()
        )
        any_period_count = (
            select(func.count(HrEmploymentPeriod.id))
            .where(HrEmploymentPeriod.employee_id == HrEmployee.id)
            .correlate(HrEmployee)
            .scalar_subquery()
        )
        active_service_start = (
            select(HrEmploymentPeriod.started_on)
            .where(
                HrEmploymentPeriod.employee_id == HrEmployee.id,
                HrEmploymentPeriod.ended_on.is_(None),
            )
            .limit(1)
            .correlate(HrEmployee)
            .scalar_subquery()
        )
        service_start = cast(
            case(
                (any_period_count == 0, HrEmployee.join_date),
                (active_period_count == 1, active_service_start),
                else_=None,
            ),
            Date,
        )
        source_month = cast(func.extract("month", HrEmployeePrivate.date_of_birth), Integer)
        source_day = cast(func.extract("day", HrEmployeePrivate.date_of_birth), Integer)
        occurrence_month = cast(func.extract("month", occurrence), Integer)
        occurrence_day = cast(func.extract("day", occurrence), Integer)
        occurrence_year = cast(func.extract("year", occurrence), Integer)
        leap_year = (occurrence_year % 4 == 0) & (
            (occurrence_year % 100 != 0) | (occurrence_year % 400 == 0)
        )
        birthday_match = or_(
            and_(source_month == occurrence_month, source_day == occurrence_day),
            and_(
                source_month == 2,
                source_day == 29,
                occurrence_month == 2,
                occurrence_day == 28,
                ~leap_year,
            ),
        )
        employees = (
            select(
                HrEmployee.full_name.label("name"),
                occurrence_day.label("day"),
                occurrence_month.label("month"),
                occurrence.label("occurrence"),
                func.lower(HrEmployee.full_name).label("name_sort"),
                HrEmployee.id.label("tie_breaker"),
            )
            .select_from(HrEmployee)
            .join(HrEmployeePrivate, HrEmployeePrivate.employee_id == HrEmployee.id)
            .join(offsets, literal(True))
            .where(
                HrEmployee.deleted_at.is_(None),
                HrEmployee.employment_status.in_(ACTIVE_EMPLOYMENT_STATUSES),
                or_(
                    HrEmployee.termination_date.is_(None),
                    HrEmployee.termination_date >= occurrence,
                ),
                HrEmployeePrivate.date_of_birth.is_not(None),
                HrEmployeePrivate.date_of_birth <= today,
                service_start.is_not(None),
                service_start <= today,
                service_start <= occurrence,
                birthday_match,
            )
            .subquery()
        )
        total = int(await self.session.scalar(select(func.count()).select_from(employees)) or 0)
        rows = (
            await self.session.execute(
                select(employees.c.name, employees.c.day, employees.c.month)
                .order_by(employees.c.occurrence, employees.c.name_sort, employees.c.tie_breaker)
                .offset(offset)
                .limit(limit)
            )
        ).all()
        return BirthdayPageResponse(
            items=[BirthdayItem(name=name, day=day, month=month) for name, day, month in rows],
            total=total,
            offset=offset,
            limit=limit,
        )

    async def upcoming_anniversaries(
        self, *, offset: int, limit: int
    ) -> AnniversaryPageResponse:
        today = business_today()
        offsets = func.generate_series(0, 29).table_valued("day_offset").render_derived()
        occurrence = cast(literal(today) + offsets.c.day_offset, Date)
        active_period_count = (
            select(func.count(HrEmploymentPeriod.id))
            .where(
                HrEmploymentPeriod.employee_id == HrEmployee.id,
                HrEmploymentPeriod.ended_on.is_(None),
            )
            .correlate(HrEmployee)
            .scalar_subquery()
        )
        any_period_count = (
            select(func.count(HrEmploymentPeriod.id))
            .where(HrEmploymentPeriod.employee_id == HrEmployee.id)
            .correlate(HrEmployee)
            .scalar_subquery()
        )
        active_service_start = (
            select(HrEmploymentPeriod.started_on)
            .where(
                HrEmploymentPeriod.employee_id == HrEmployee.id,
                HrEmploymentPeriod.ended_on.is_(None),
            )
            .limit(1)
            .correlate(HrEmployee)
            .scalar_subquery()
        )
        service_start = cast(
            case(
                (any_period_count == 0, HrEmployee.join_date),
                (active_period_count == 1, active_service_start),
                else_=None,
            ),
            Date,
        )
        source_month = cast(func.extract("month", service_start), Integer)
        source_day = cast(func.extract("day", service_start), Integer)
        occurrence_month = cast(func.extract("month", occurrence), Integer)
        occurrence_day = cast(func.extract("day", occurrence), Integer)
        occurrence_year = cast(func.extract("year", occurrence), Integer)
        leap_year = (occurrence_year % 4 == 0) & (
            (occurrence_year % 100 != 0) | (occurrence_year % 400 == 0)
        )
        anniversary_match = or_(
            and_(source_month == occurrence_month, source_day == occurrence_day),
            and_(
                source_month == 2,
                source_day == 29,
                occurrence_month == 2,
                occurrence_day == 28,
                ~leap_year,
            ),
        )
        years = occurrence_year - cast(func.extract("year", service_start), Integer)
        employees = (
            select(
                HrEmployee.full_name.label("name"),
                occurrence_day.label("day"),
                occurrence_month.label("month"),
                years.label("completed_years"),
                occurrence.label("occurrence"),
                func.lower(HrEmployee.full_name).label("name_sort"),
                HrEmployee.id.label("tie_breaker"),
            )
            .select_from(HrEmployee)
            .join(offsets, literal(True))
            .where(
                HrEmployee.deleted_at.is_(None),
                HrEmployee.employment_status.in_(ACTIVE_EMPLOYMENT_STATUSES),
                or_(
                    HrEmployee.termination_date.is_(None),
                    HrEmployee.termination_date >= occurrence,
                ),
                service_start.is_not(None),
                service_start <= today,
                service_start <= occurrence,
                years >= 1,
                anniversary_match,
            )
            .subquery()
        )
        total = int(await self.session.scalar(select(func.count()).select_from(employees)) or 0)
        rows = (
            await self.session.execute(
                select(
                    employees.c.name,
                    employees.c.day,
                    employees.c.month,
                    employees.c.completed_years,
                )
                .order_by(employees.c.occurrence, employees.c.name_sort, employees.c.tie_breaker)
                .offset(offset)
                .limit(limit)
            )
        ).all()
        return AnniversaryPageResponse(
            items=[
                AnniversaryItem(
                    name=name, day=day, month=month, completed_years=completed_years
                )
                for name, day, month, completed_years in rows
            ],
            total=total,
            offset=offset,
            limit=limit,
        )

    async def _site_operations(self, project_ids: list[UUID] | None) -> SiteOperationsSummary:
        project_scope = select(Project.id).where(Project.deleted_at.is_(None))
        if project_ids is not None:
            project_scope = project_scope.where(Project.id.in_(project_ids))
        progress = select(func.count(SupervisorUpdate.id)).where(
            SupervisorUpdate.project_id.in_(project_scope),
            SupervisorUpdate.deleted_at.is_(None),
        )
        registrations = select(func.count(InventoryRegistration.id)).where(
            InventoryRegistration.project_id.in_(project_scope),
        )
        successor = aliased(SupervisorUpdate)
        site_counts: dict[str, Select[int]] = {
            "confirmed_progress": progress.where(
                SupervisorUpdate.status == "verified",
                SupervisorUpdate.submission_revision.is_not(None),
                ~select(successor.id)
                .where(
                    successor.previous_id == SupervisorUpdate.id,
                    successor.status == "verified",
                    successor.deleted_at.is_(None),
                )
                .exists(),
            ),
            "progress_awaiting_review": progress.where(
                SupervisorUpdate.status.in_(("submitted", "pending_qs", "pending_engineer")),
            ),
            "material_requests_awaiting_review": select(func.count(MaterialRequest.id)).where(
                MaterialRequest.project_id.in_(project_scope),
                MaterialRequest.deleted_at.is_(None),
                MaterialRequest.status.in_(("requested", *MATERIAL_STAGE_STATES.values())),
            ),
            "registrations_awaiting_review": registrations.where(
                InventoryRegistration.status == "pending_engineer",
            ),
            "confirmed_registrations": select(
                func.count(
                    func.distinct(
                        func.coalesce(InventoryRegistration.root_id, InventoryRegistration.id)
                    )
                )
            ).where(
                InventoryRegistration.project_id.in_(project_scope),
                InventoryRegistration.status == "approved",
                InventoryRegistration.confirmed_item_id.is_not(None),
            ),
            "confirmed_present_today": select(func.count(HrAttendanceEntry.id))
            .join(
                HrSiteAttendanceSubmission,
                (HrSiteAttendanceSubmission.entry_id == HrAttendanceEntry.id)
                & (
                    HrSiteAttendanceSubmission.submission_revision
                    == HrAttendanceEntry.site_submission_revision
                ),
            )
            .where(
                HrAttendanceEntry.project_id.in_(project_scope),
                HrAttendanceEntry.work_date == business_today(),
                HrAttendanceEntry.source == "site",
                HrAttendanceEntry.status == "approved",
                HrAttendanceEntry.attendance_status == "present",
                HrSiteAttendanceSubmission.engineer_decision == "approved",
                HrSiteAttendanceSubmission.hr_decision == "approved",
            ),
        }
        counters = (
            (
                await self.session.execute(
                    select(
                        *(query.scalar_subquery().label(key) for key, query in site_counts.items())
                    )
                )
            )
            .mappings()
            .one()
        )
        return SiteOperationsSummary.model_validate(dict(counters))

    async def _visible_project_ids(self, actor: User) -> list | None:
        if actor.role in COMPANY_RESOURCE_ROLES or has_permission(
            actor, PERMISSION_DASHBOARD_COMPANY
        ):
            return None
        return await self._assigned_project_ids(actor)

    async def _assigned_project_ids(self, actor: User) -> list:
        result = await self.session.execute(
            select(ProjectMember.project_id).where(
                ProjectMember.user_id == actor.id,
                ProjectMember.deleted_at.is_(None),
            )
        )
        return list(result.scalars().all())

    async def _count_projects(self, project_ids: list | None) -> int:
        query = (
            select(func.count())
            .select_from(Project)
            .where(
                Project.status == "active",
                Project.deleted_at.is_(None),
            )
        )
        if project_ids is not None:
            if not project_ids:
                return 0
            query = query.where(Project.id.in_(project_ids))
        return int(await self.session.scalar(query) or 0)

    async def _count_reports(self, project_ids: list | None, status: str) -> int:
        query = (
            select(func.count())
            .select_from(DailyReport)
            .where(
                DailyReport.status == status,
                DailyReport.deleted_at.is_(None),
            )
        )
        if project_ids is not None:
            if not project_ids:
                return 0
            query = query.where(DailyReport.project_id.in_(project_ids))
        return int(await self.session.scalar(query) or 0)

    async def _count_documents(self, project_ids: list | None) -> int:
        query = (
            select(func.count())
            .select_from(Document)
            .where(
                Document.status == "pending_approval",
                Document.deleted_at.is_(None),
            )
        )
        if project_ids is not None:
            if not project_ids:
                return 0
            query = query.where(Document.project_id.in_(project_ids))
        return int(await self.session.scalar(query) or 0)

    async def _count_notifications(self, actor: User) -> int:
        return int(
            await self.session.scalar(
                select(func.count())
                .select_from(Notification)
                .where(
                    Notification.user_id == actor.id,
                    Notification.is_read.is_(False),
                    Notification.deleted_at.is_(None),
                )
            )
            or 0
        )

    async def _recent_activity(self, project_ids: list | None) -> list[str]:
        query = select(DailyReport.report_number, DailyReport.status).where(
            DailyReport.deleted_at.is_(None)
        )
        if project_ids is not None:
            if not project_ids:
                return []
            query = query.where(DailyReport.project_id.in_(project_ids))
        result = await self.session.execute(query.order_by(DailyReport.created_at.desc()).limit(5))
        return [f"{number or 'Draft report'}: {status}" for number, status in result.all()]
