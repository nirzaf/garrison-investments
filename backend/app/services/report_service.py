from uuid import UUID

from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.daily_report import (
    DailyReport,
    DailyReportApprovalHistory,
    ReportEquipment,
    ReportManpower,
    ReportMaterialConsumption,
)
from app.models.user import User
from app.repositories.daily_report_repository import DailyReportRepository
from app.repositories.project_repository import ProjectRepository
from app.repositories.supervisor_update_repository import SupervisorUpdateRepository
from app.schemas.daily_reports import DailyReportCreateRequest, DailyReportUpdateRequest
from app.services.audit_service import AuditService
from app.services.authorization import COMPANY_WIDE_ROLES
from app.services.idempotency import bind, resolve_or_reserve
from app.services.notification_service import NotificationService
from app.utils.exceptions import AppException, NotFoundException
from app.utils.links import append_link, approval_inbox_url, daily_report_url
from app.utils.permissions import (
    ROLE_ADMIN,
    ROLE_CIVIL_ENGINEER,
    ROLE_GENERAL_MANAGER,
    ROLE_OPERATION_MANAGER,
    ROLE_PROJECT_MANAGER,
)
from app.utils.security import utc_now
from app.utils.time import business_today

REPORT_STATUSES = {"draft", "submitted", "approved", "rejected"}
IDEMPOTENCY_ROUTE = "reports.create"


class ReportService:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session
        self.reports = DailyReportRepository(session)
        self.projects = ProjectRepository(session)
        self.supervisor_updates = SupervisorUpdateRepository(session)
        self.audit = AuditService(session)
        self.notifications = NotificationService(session)

    async def create_report(
        self,
        payload: DailyReportCreateRequest,
        actor: User,
        *,
        idempotency_key: str | None = None,
    ) -> DailyReport:
        self._ensure_engineer(actor)
        if idempotency_key:
            # A replayed offline-queue create must return the original report, not a twin.
            existing_id = await resolve_or_reserve(
                self.session,
                key=idempotency_key,
                user_id=actor.id,
                route=IDEMPOTENCY_ROUTE,
            )
            if existing_id is not None:
                return await self.get_report(existing_id, actor)
        self._validate_report_date(payload.report_date, actor)
        project = await self._ensure_project_member(payload.project_id, actor)
        report = DailyReport(
            engineer_id=actor.id,
            status="draft",
            report_number=None,
            **self._report_values(payload),
        )
        await self.reports.add(report)
        await self._replace_children(report, payload)
        await self.audit.record(
            action="daily_reports.created",
            user_id=actor.id,
            entity_type="daily_reports",
            entity_id=report.id,
            new_values={"project_id": str(project.id), "date": str(report.report_date)},
        )
        if idempotency_key:
            winner_id = await bind(
                self.session,
                key=idempotency_key,
                user_id=actor.id,
                route=IDEMPOTENCY_ROUTE,
                resource_type="daily_report",
                resource_id=report.id,
            )
            if winner_id != report.id:
                await self.session.rollback()
                return await self.get_report(winner_id, actor)
        await self.session.commit()
        return await self._get_required(report.id)

    async def update_report(
        self,
        report_id: UUID,
        payload: DailyReportUpdateRequest,
        actor: User,
    ) -> DailyReport:
        self._ensure_engineer(actor)
        report = await self._get_required(report_id)
        if report.engineer_id != actor.id:
            raise NotFoundException("Daily report")
        if report.status == "approved":
            raise AppException(
                "Approved reports cannot be edited.",
                status_code=409,
                error_code="DAILY_REPORT_APPROVED_LOCKED",
            )
        if report.status == "submitted":
            raise AppException(
                "Submitted reports are locked until reviewed.",
                status_code=409,
                error_code="DAILY_REPORT_SUBMITTED_LOCKED",
            )
        self._validate_report_date(payload.report_date, actor)
        await self._ensure_project_member(payload.project_id, actor)
        for key, value in self._report_values(payload).items():
            setattr(report, key, value)
        if report.status == "rejected":
            report.status = "draft"
        await self._replace_children(report, payload)
        await self.audit.record(
            action="daily_reports.updated",
            user_id=actor.id,
            entity_type="daily_reports",
            entity_id=report.id,
        )
        await self.session.commit()
        return await self._get_required(report.id)

    async def submit_report(self, report_id: UUID, actor: User) -> DailyReport:
        self._ensure_engineer(actor)
        report = await self._get_required(report_id, for_update=True)
        if report.engineer_id != actor.id:
            raise NotFoundException("Daily report")
        if report.status not in {"draft", "rejected"}:
            raise AppException(
                "Only draft or rejected reports can be submitted.",
                status_code=409,
                error_code="DAILY_REPORT_LOCKED",
            )
        self._validate_report_date(report.report_date, actor)
        project = await self._ensure_project_member(report.project_id, actor)
        await self._verify_supervisor_updates(report, actor)
        if not report.report_number:
            # Serialise numbering per project+date so two engineers submitting at the same
            # instant cannot both read the same COUNT+1. Existing numbers are never changed.
            await self.session.execute(
                select(
                    func.pg_advisory_xact_lock(
                        func.hashtext(f"{report.project_id}:{report.report_date}")
                    )
                )
            )
            sequence = await self.reports.next_report_sequence(
                report.project_id,
                report.report_date,
            )
            report.report_number = (
                f"{project.code}-DR-{report.report_date.strftime('%Y%m%d')}-{sequence:03d}"
            )
        # The try block starts here, not at commit(): history/audit/notification inserts
        # autoflush, so a number collision can surface before commit() is ever reached.
        try:
            previous_status = report.status
            report.status = "submitted"
            report.submitted_at = utc_now()
            report.rejection_comments = None
            await self._record_history(
                report=report,
                actor=actor,
                decision="submitted",
                previous_status=previous_status,
                comments=None,
            )
            await self.audit.record(
                action="daily_reports.submitted",
                user_id=actor.id,
                entity_type="daily_reports",
                entity_id=report.id,
                new_values={"report_number": report.report_number},
            )
            await self._notify_project_managers(
                report,
                title="Daily report pending approval",
                body=append_link(
                    f"{report.report_number} is ready for approval.",
                    label="Open approval",
                    url=approval_inbox_url(tab="reports", report_id=report.id),
                ),
                notification_type="approval",
            )
            await self.session.commit()
        except IntegrityError as exc:
            await self.session.rollback()
            raise AppException(
                "A report number was already assigned for this project and date.",
                status_code=409,
                error_code="DAILY_REPORT_NUMBER_CONFLICT",
            ) from exc
        return await self._get_required(report.id)

    async def approve_report(
        self,
        report_id: UUID,
        actor: User,
        comments: str | None = None,
        target_covered: bool = False,
    ) -> DailyReport:
        report = await self._get_required(report_id, for_update=True)
        await self._ensure_approver(report, actor)
        if not target_covered:
            raise AppException(
                "Approver must confirm the report target was covered.",
                status_code=422,
                error_code="DAILY_REPORT_TARGET_CONFIRMATION_REQUIRED",
            )
        if report.status != "submitted":
            raise AppException(
                "Only submitted reports can be approved.",
                status_code=409,
                error_code="DAILY_REPORT_NOT_SUBMITTED",
            )
        previous_status = report.status
        report.status = "approved"
        report.approved_by = actor.id
        report.approved_at = utc_now()
        report.rejection_comments = None
        await self._record_history(
            report=report,
            actor=actor,
            decision="approved",
            previous_status=previous_status,
            comments=comments,
        )
        await self.audit.record(
            action="daily_reports.approved",
            user_id=actor.id,
            entity_type="daily_reports",
            entity_id=report.id,
            comments=comments,
            new_values={"target_covered": target_covered},
        )
        await self._consume_report_materials(report, actor)
        await self.notifications.create(
            user_id=report.engineer_id,
            title="Daily report approved",
            body=append_link(
                f"{report.report_number} has been approved.",
                label="Open report",
                url=daily_report_url(report.id),
            ),
            notification_type="approval",
            reference_type="daily_report",
            reference_id=report.id,
        )
        await self.session.commit()
        self._queue_post_approval_tasks(report.id, actor.id)
        return await self._get_required(report.id)

    async def override_report(
        self,
        report_id: UUID,
        actor: User,
        *,
        decision: str,
        reason: str,
        target_covered: bool,
    ) -> DailyReport:
        if actor.role != ROLE_ADMIN:
            raise AppException(
                "Only Admin can override daily report approvals.",
                status_code=403,
                error_code="DAILY_REPORT_OVERRIDE_FORBIDDEN",
            )
        if decision == "approved" and not target_covered:
            raise AppException(
                "Admin approval override requires target-covered confirmation.",
                status_code=422,
                error_code="DAILY_REPORT_TARGET_CONFIRMATION_REQUIRED",
            )
        report = await self._get_required(report_id, for_update=True)
        if report.status == "approved":
            raise AppException(
                "Approved reports cannot be overridden.",
                status_code=409,
                error_code="DAILY_REPORT_APPROVED_LOCKED",
            )
        previous_status = report.status
        if decision == "approved":
            report.status = "approved"
            report.approved_by = actor.id
            report.approved_at = utc_now()
            report.rejection_comments = None
            await self._consume_report_materials(report, actor)
        else:
            report.status = "draft"
            report.rejection_comments = reason.strip()
        await self._record_history(
            report=report,
            actor=actor,
            decision=decision,
            previous_status=previous_status,
            comments=f"Admin override: {reason.strip()}",
        )
        await self.audit.record(
            action=f"daily_reports.override_{decision}",
            user_id=actor.id,
            entity_type="daily_reports",
            entity_id=report.id,
            comments=reason.strip(),
            new_values={"target_covered": target_covered},
        )
        await self.notifications.create(
            user_id=report.engineer_id,
            title="Daily report override",
            body=append_link(
                f"{report.report_number or 'Daily report'} was overridden: {decision}.",
                label="Open report",
                url=daily_report_url(report.id),
            ),
            notification_type="approval",
            reference_type="daily_report",
            reference_id=report.id,
        )
        await self.session.commit()
        if decision == "approved":
            self._queue_post_approval_tasks(report.id, actor.id)
        return await self._get_required(report.id)

    async def reject_report(
        self,
        report_id: UUID,
        actor: User,
        comments: str | None,
    ) -> DailyReport:
        report = await self._get_required(report_id, for_update=True)
        await self._ensure_approver(report, actor)
        if not comments or not comments.strip():
            raise AppException(
                "Rejection reason is required.",
                status_code=422,
                error_code="DAILY_REPORT_REJECTION_REASON_REQUIRED",
            )
        if report.status != "submitted":
            raise AppException(
                "Only submitted reports can be rejected.",
                status_code=409,
                error_code="DAILY_REPORT_NOT_SUBMITTED",
            )
        previous_status = report.status
        report.status = "draft"
        report.rejection_comments = comments.strip()
        await self._record_history(
            report=report,
            actor=actor,
            decision="rejected",
            previous_status=previous_status,
            comments=comments.strip(),
        )
        await self.audit.record(
            action="daily_reports.rejected",
            user_id=actor.id,
            entity_type="daily_reports",
            entity_id=report.id,
            comments=comments.strip(),
        )
        await self.notifications.create(
            user_id=report.engineer_id,
            title="Daily report rejected",
            body=append_link(
                comments.strip(),
                label="Open report",
                url=daily_report_url(report.id),
            ),
            notification_type="approval",
            reference_type="daily_report",
            reference_id=report.id,
        )
        await self.session.commit()
        return await self._get_required(report.id)

    async def get_report(self, report_id: UUID, actor: User) -> DailyReport:
        report = await self._get_required(report_id)
        await self._ensure_report_access(report, actor)
        return report

    async def list_reports(
        self,
        *,
        actor: User,
        project_id: UUID | None,
        status: str | None,
        limit: int,
        offset: int,
    ) -> tuple[list[DailyReport], int]:
        self._validate_status(status)
        engineer_id = actor.id if actor.role == ROLE_CIVIL_ENGINEER else None
        project_ids: list[UUID] | None = None
        if actor.role == ROLE_PROJECT_MANAGER:
            if project_id is None:
                project_ids = await self.projects.list_project_ids_for_user(actor.id)
                if not project_ids:
                    return [], 0
            else:
                await self._ensure_project_member(project_id, actor)
        elif actor.role == ROLE_CIVIL_ENGINEER and project_id:
            await self._ensure_project_member(project_id, actor)
        elif actor.role not in COMPANY_WIDE_ROLES:
            if actor.role != ROLE_CIVIL_ENGINEER:
                raise AppException(
                    "You do not have access to daily reports.",
                    status_code=403,
                    error_code="DAILY_REPORT_FORBIDDEN",
                )
        return await self.reports.list_reports(
            project_id=project_id,
            project_ids=project_ids,
            engineer_id=engineer_id,
            status=status,
            limit=min(limit, 200),
            offset=max(offset, 0),
        )

    async def _get_required(self, report_id: UUID, *, for_update: bool = False) -> DailyReport:
        if for_update:
            # Take the parent row lock before reading children so concurrent decisions
            # serialise and material consumption cannot run twice.
            locked = await self.reports.lock_by_id(report_id)
            if not locked:
                raise NotFoundException("Daily report")
        report = await self.reports.get_by_id(report_id)
        if not report:
            raise NotFoundException("Daily report")
        return report

    async def _replace_children(
        self,
        report: DailyReport,
        payload: DailyReportCreateRequest | DailyReportUpdateRequest,
    ) -> None:
        await self.reports.replace_children(
            report,
            manpower_entries=[
                ReportManpower(report_id=report.id, **entry.model_dump())
                for entry in payload.manpower_entries
            ],
            equipment_entries=[
                ReportEquipment(report_id=report.id, **entry.model_dump())
                for entry in payload.equipment_entries
            ],
            material_consumption=[
                ReportMaterialConsumption(report_id=report.id, **entry.model_dump())
                for entry in payload.material_consumption
            ],
        )

    async def _verify_supervisor_updates(self, report: DailyReport, actor: User) -> None:
        for update_id in report.supervisor_update_ids:
            supervisor_update = await self.supervisor_updates.get_by_id(UUID(update_id))
            if not supervisor_update or supervisor_update.project_id != report.project_id:
                raise AppException(
                    "Supervisor update does not belong to this project.",
                    status_code=422,
                    error_code="SUPERVISOR_UPDATE_PROJECT_MISMATCH",
                )
            if supervisor_update.status != "submitted":
                raise AppException(
                    "Supervisor update must be submitted before verification.",
                    status_code=409,
                    error_code="SUPERVISOR_UPDATE_NOT_SUBMITTED",
                )
            supervisor_update.status = "verified"
            supervisor_update.verified_by = actor.id
            supervisor_update.verified_at = utc_now()

    async def _ensure_project_member(self, project_id: UUID, actor: User):
        project = await self.projects.get_by_id(project_id)
        if not project:
            raise NotFoundException("Project")
        if actor.role in {ROLE_ADMIN, ROLE_GENERAL_MANAGER, ROLE_OPERATION_MANAGER}:
            return project
        members = await self.projects.list_members(project_id)
        if not any(member.user_id == actor.id for member in members):
            raise NotFoundException("Project")
        return project

    async def _ensure_report_access(self, report: DailyReport, actor: User) -> None:
        if actor.role == ROLE_CIVIL_ENGINEER and report.engineer_id == actor.id:
            return
        if actor.role in {ROLE_ADMIN, ROLE_GENERAL_MANAGER, ROLE_OPERATION_MANAGER}:
            return
        if actor.role == ROLE_PROJECT_MANAGER:
            await self._ensure_project_member(report.project_id, actor)
            return
        raise NotFoundException("Daily report")

    async def _ensure_approver(self, report: DailyReport, actor: User) -> None:
        if actor.role in {ROLE_ADMIN, ROLE_GENERAL_MANAGER, ROLE_OPERATION_MANAGER}:
            return
        if actor.role == ROLE_PROJECT_MANAGER:
            await self._ensure_project_member(report.project_id, actor)
            return
        raise AppException(
            "You do not have approval access for this daily report.",
            status_code=403,
            error_code="DAILY_REPORT_APPROVAL_FORBIDDEN",
        )

    async def _record_history(
        self,
        *,
        report: DailyReport,
        actor: User,
        decision: str,
        previous_status: str,
        comments: str | None,
    ) -> None:
        history = DailyReportApprovalHistory(
            report_id=report.id,
            actor_id=actor.id,
            decision=decision,
            previous_status=previous_status,
            comments=comments,
            decided_at=utc_now(),
        )
        await self.reports.add_history(history)
        report.approval_history.append(history)

    async def _notify_project_managers(
        self,
        report: DailyReport,
        *,
        title: str,
        body: str,
        notification_type: str,
    ) -> None:
        members = await self.projects.list_members(report.project_id)
        for member in members:
            if member.role_in_project == "project_manager":
                await self.notifications.create(
                    user_id=member.user_id,
                    title=title,
                    body=body,
                    notification_type=notification_type,
                    reference_type="daily_report",
                    reference_id=report.id,
                )

    async def _consume_report_materials(self, report: DailyReport, actor: User) -> None:
        from app.services.inventory_service import InventoryService

        await InventoryService(self.session).consume_daily_report_materials(report, actor)

    def _ensure_engineer(self, actor: User) -> None:
        if actor.role not in {ROLE_ADMIN, ROLE_CIVIL_ENGINEER}:
            raise AppException(
                "Only Civil Engineers can manage official daily reports.",
                status_code=403,
                error_code="DAILY_REPORT_ENGINEER_REQUIRED",
            )

    def _validate_report_date(self, report_date, actor: User) -> None:
        if actor.role == ROLE_ADMIN:
            return
        if report_date < business_today():
            raise AppException(
                "Past-dated daily reports require Admin submission.",
                status_code=422,
                error_code="DAILY_REPORT_PAST_DATE_REQUIRES_ADMIN",
            )

    def _report_values(self, payload: DailyReportCreateRequest | DailyReportUpdateRequest) -> dict:
        values = payload.model_dump(
            exclude={"manpower_entries", "equipment_entries", "material_consumption"}
        )
        values["supervisor_update_ids"] = [
            str(update_id) for update_id in payload.supervisor_update_ids
        ]
        values["photo_refs"] = [ref.model_dump() for ref in payload.photo_refs]
        values["attachment_refs"] = [ref.model_dump() for ref in payload.attachment_refs]
        return values

    def _validate_status(self, status: str | None) -> None:
        if status and status not in REPORT_STATUSES:
            raise AppException(
                "Invalid daily report status.",
                status_code=422,
                error_code="INVALID_DAILY_REPORT_STATUS",
            )

    def _queue_post_approval_tasks(self, report_id: UUID, actor_id: UUID) -> None:
        try:
            from app.tasks.report import generate_report_pdf

            generate_report_pdf.delay(str(report_id), str(actor_id), email_after=True)
        except Exception:
            # Approval is the source-of-truth workflow action; export failures are tracked by tasks.
            return

    async def get_report_for_export(self, report_id: UUID) -> DailyReport:
        return await self._get_required(report_id)
