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
from app.models.project_member import ProjectMember
from app.models.supervisor_update import SupervisorUpdate, SupervisorUpdateSubmission
from app.models.task_outbox import TaskOutbox
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
    COMPANY_RESOURCE_ROLES,
    OFFICIAL_REPORT_AUTHOR_ROLES,
    PERMISSION_REPORTS_APPROVE,
    PERMISSION_REPORTS_SUBMIT,
    PERMISSION_REPORTS_VIEW,
    REPORT_APPROVER_ROLES,
    ROLE_PERMISSIONS,
    has_permission,
)
from app.utils.security import utc_now
from app.utils.time import business_today

REPORT_STATUSES = {"draft", "submitted", "approved", "rejected"}
DAILY_REPORT_READ_ROLES = {
    role for role, permissions in ROLE_PERMISSIONS.items() if PERMISSION_REPORTS_VIEW in permissions
}
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
        return await self._commit_report_snapshot(report)

    async def _commit_report_snapshot(self, report: DailyReport) -> DailyReport:
        # Capture this write before releasing the lock. A subsequent edit is a new revision.
        await self.session.flush()
        await self.session.refresh(
            report,
            attribute_names=[
                "manpower_entries",
                "equipment_entries",
                "material_consumption",
                "approval_history",
            ],
        )
        await self.session.commit()
        return report

    async def update_report(
        self,
        report_id: UUID,
        payload: DailyReportUpdateRequest,
        actor: User,
    ) -> DailyReport:
        self._ensure_engineer(actor)
        report = await self._get_required(report_id, for_update=True)
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
        await self._ensure_project_member(report.project_id, actor)
        if payload.expected_revision is None:
            raise AppException(
                "Reload the report before editing so the current revision can be checked.",
                status_code=409,
                error_code="DAILY_REPORT_REVISION_REQUIRED",
            )
        if report.revision != payload.expected_revision:
            raise AppException(
                "The report changed since it was opened. Reload it before editing.",
                status_code=409,
                error_code="DAILY_REPORT_REVISION_CONFLICT",
            )
        # The report date was accepted when the official number was assigned.
        if not report.report_number or payload.report_date != report.report_date:
            self._validate_report_date(payload.report_date, actor)
        if payload.project_id != report.project_id:
            await self._ensure_project_member(payload.project_id, actor)
        bound_ids = await self.supervisor_updates.bound_ids(report.id)
        if bound_ids and (
            payload.project_id != report.project_id
            or not bound_ids.issubset(payload.supervisor_update_ids)
        ):
            raise AppException(
                "Keep verified supervisor updates and their project on this report.",
                status_code=409,
                error_code="SUPERVISOR_UPDATE_VERIFICATION_LOCKED",
            )
        for key, value in self._report_values(payload).items():
            setattr(report, key, value)
        if report.status == "rejected":
            report.status = "draft"
        report.revision += 1
        await self._replace_children(report, payload)
        await self.audit.record(
            action="daily_reports.updated",
            user_id=actor.id,
            entity_type="daily_reports",
            entity_id=report.id,
        )
        return await self._commit_report_snapshot(report)

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
        if not report.report_number:
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
            report.revision += 1
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
        report.revision += 1
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
        self._queue_post_approval_tasks(report.id, actor.id)
        await self.session.commit()
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
        del report_id, actor, decision, reason, target_covered
        raise AppException(
            "Report override is not part of the supported role policy.",
            status_code=403,
            error_code="DAILY_REPORT_OVERRIDE_FORBIDDEN",
        )

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
        report.revision += 1
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

    async def list_supervisor_evidence(
        self, report_id: UUID, actor: User
    ) -> list[SupervisorUpdate]:
        report = await self.get_report(report_id, actor)
        return await self.supervisor_updates.list_report_evidence(
            report.id, report.project_id, self._supervisor_update_ids(report)
        )

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
        has_view = has_permission(actor, PERMISSION_REPORTS_VIEW)
        has_submit = has_permission(actor, PERMISSION_REPORTS_SUBMIT)
        if not has_view and not has_submit:
            raise AppException(
                "You do not have access to daily reports.",
                status_code=403,
                error_code="DAILY_REPORT_FORBIDDEN",
            )
        own_work_only = not has_view
        engineer_id = actor.id if own_work_only else None
        project_ids: list[UUID] | None = None
        if actor.role not in COMPANY_RESOURCE_ROLES:
            if project_id is not None:
                await self._ensure_project_member(project_id, actor)
            else:
                project_ids = await self.projects.list_project_ids_for_user(actor.id)
                if not project_ids:
                    return [], 0
        if not own_work_only and actor.role not in DAILY_REPORT_READ_ROLES:
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

    @staticmethod
    def _supervisor_update_ids(report: DailyReport) -> list[UUID]:
        try:
            return [UUID(update_id) for update_id in report.supervisor_update_ids]
        except ValueError as exc:
            raise AppException(
                "The report contains an invalid supervisor update reference.",
                status_code=422,
                error_code="INVALID_SUPERVISOR_UPDATE_REFERENCE",
            ) from exc

    async def _verify_supervisor_updates(self, report: DailyReport, actor: User) -> None:
        update_ids = self._supervisor_update_ids(report)
        updates = await self.supervisor_updates.lock_linked(update_ids)
        if len(updates) != len(update_ids) or any(
            update.project_id != report.project_id for update in updates
        ):
            raise AppException(
                "Select distinct supervisor updates from this project.",
                status_code=422,
                error_code="SUPERVISOR_UPDATE_PROJECT_MISMATCH",
            )
        for update in updates:
            if update.status == "verified" and update.verified_report_id == report.id:
                continue
            if update.verified_report_id is not None:
                raise AppException(
                    "This update is already retained on another report.",
                    status_code=409,
                    error_code="SUPERVISOR_UPDATE_ALREADY_VERIFIED",
                )
            submission = (
                await self.session.get(
                    SupervisorUpdateSubmission, (update.id, update.submission_revision)
                )
                if update.submission_revision is not None
                else None
            )
            if (
                update.status != "verified"
                or submission is None
                or submission.engineer_decision != "approved"
                or submission.engineer_decided_at is None
                or update.verified_by != submission.engineer_id
                or (
                    submission.qs_id is not None
                    and (submission.qs_decision != "approved" or submission.qs_decided_at is None)
                )
            ):
                error_code = (
                    "SUPERVISOR_UPDATE_VERIFICATION_UNRESOLVED"
                    if update.status == "verified" and submission is None
                    else "SUPERVISOR_UPDATE_NOT_CONFIRMED"
                )
                raise AppException(
                    "Select site progress with all required independent checks complete.",
                    status_code=409,
                    error_code=error_code,
                )
            update.verified_report_id = report.id
            await self.audit.record(
                action="reports.supervisor_evidence_linked",
                user_id=actor.id,
                entity_type="daily_reports",
                entity_id=report.id,
                new_values={
                    "supervisor_update_id": str(update.id),
                    "submission_revision": update.submission_revision,
                },
            )

    async def _ensure_project_member(self, project_id: UUID, actor: User):
        project = await self.projects.get_by_id(project_id)
        if not project:
            raise NotFoundException("Project")
        if actor.role in COMPANY_RESOURCE_ROLES:
            return project
        members = await self.projects.list_members(project_id)
        if not any(member.user_id == actor.id for member in members):
            raise NotFoundException("Project")
        return project

    async def _ensure_report_access(self, report: DailyReport, actor: User) -> None:
        if report.engineer_id == actor.id and has_permission(actor, PERMISSION_REPORTS_SUBMIT):
            await self._ensure_project_member(report.project_id, actor)
            return
        if actor.role in COMPANY_WIDE_ROLES:
            return
        if has_permission(actor, PERMISSION_REPORTS_VIEW):
            await self._ensure_project_member(report.project_id, actor)
            return
        raise NotFoundException("Daily report")

    async def _ensure_approver(self, report: DailyReport, actor: User) -> None:
        if actor.role not in REPORT_APPROVER_ROLES or not has_permission(
            actor, PERMISSION_REPORTS_APPROVE
        ):
            raise AppException(
                "You do not have approval access for this daily report.",
                status_code=403,
                error_code="DAILY_REPORT_APPROVAL_FORBIDDEN",
            )
        if report.engineer_id == actor.id:
            raise AppException(
                "Authors cannot approve their own daily reports.",
                status_code=403,
                error_code="REPORT_SELF_APPROVAL_FORBIDDEN",
            )
        if actor.role in COMPANY_RESOURCE_ROLES:
            return
        if actor.role in REPORT_APPROVER_ROLES:
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
        recipients = await self.session.scalars(
            select(User.id)
            .join(ProjectMember, ProjectMember.user_id == User.id)
            .where(
                ProjectMember.project_id == report.project_id,
                ProjectMember.deleted_at.is_(None),
                User.role.in_(REPORT_APPROVER_ROLES - COMPANY_RESOURCE_ROLES),
                User.is_active.is_(True),
                User.deleted_at.is_(None),
            )
        )
        for user_id in recipients:
            await self.notifications.create(
                user_id=user_id,
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
        if actor.role not in OFFICIAL_REPORT_AUTHOR_ROLES or not has_permission(
            actor, PERMISSION_REPORTS_SUBMIT
        ):
            raise AppException(
                "This role cannot author official daily reports.",
                status_code=403,
                error_code="DAILY_REPORT_ENGINEER_REQUIRED",
            )

    def _validate_report_date(self, report_date, actor: User) -> None:
        if report_date < business_today():
            raise AppException(
                "Past-dated daily reports are not supported.",
                status_code=422,
                error_code="DAILY_REPORT_PAST_DATE_UNSUPPORTED",
            )

    def _report_values(self, payload: DailyReportCreateRequest | DailyReportUpdateRequest) -> dict:
        values = payload.model_dump(
            exclude={
                "manpower_entries",
                "equipment_entries",
                "material_consumption",
                "expected_revision",
            }
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
        self.session.add(
            TaskOutbox(
                dedupe_key=f"report-pdf:{report_id}",
                task_name="generate_report_pdf",
                args_json=[str(report_id), str(actor_id)],
                kwargs_json={"email_after": True},
            )
        )

    async def get_report_for_export(
        self, report_id: UUID, *, for_update: bool = False
    ) -> DailyReport:
        return await self._get_required(report_id, for_update=for_update)
