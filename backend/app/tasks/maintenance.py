from datetime import datetime, time, timedelta
from time import monotonic

import structlog
from sqlalchemy import select, text

from app.config import get_settings
from app.database import AsyncSessionLocal
from app.models.daily_report import DailyReport
from app.models.hr import HrEmployee
from app.models.notification import Notification
from app.models.project import Project
from app.models.project_member import ProjectMember
from app.models.supplier import Supplier
from app.models.user import User
from app.schemas.hr import HrReportWindow
from app.services.audit_retention_policy import AuditRetentionPolicyError
from app.services.audit_service import AuditService
from app.services.hr_reporting import count_report_credentials
from app.services.notification_service import NotificationService
from app.tasks.async_utils import run_async_task
from app.tasks.celery_app import celery_app
from app.utils.permissions import (
    COMPANY_RESOURCE_ROLES,
    PERMISSION_HR_COMPLIANCE_MANAGE,
    PERMISSION_SUPPLIERS_MANAGE,
    REPORT_APPROVER_ROLES,
    roles_with_permission,
)
from app.utils.security import utc_now
from app.utils.time import business_now, business_today

logger = structlog.get_logger("celery.task")


@celery_app.task(
    name="archive_and_purge_logs",
    queue="maintenance",
    autoretry_for=(Exception,),
    retry_backoff=True,
    retry_jitter=True,
    max_retries=3,
)
def archive_and_purge_logs() -> str:
    logger.info("logs_retention_starting")
    return run_async_task(_archive_and_purge_logs())


async def _archive_and_purge_logs() -> str:
    started = monotonic()
    cutoff = utc_now()
    policy_revision = None
    mode = "unconfigured"
    try:
        async with AsyncSessionLocal() as session:
            audit = AuditService(session)
            verified = audit.configured_retention_policy()
            if verified is not None:
                policy_revision = verified.policy.revision
                mode = verified.policy.mode
            purge_enabled = audit.settings.log_purge_enabled
            archived = await audit.archive_logs(cutoff_at=cutoff)
            counts = await audit.retention_counts(verified, cutoff)
            purged = await audit.purge_logs(cutoff_at=cutoff)
            receipt = {
                "policy_revision": policy_revision,
                "policy_sha256": verified.sha256 if verified else None,
                "mode": mode,
                "cutoff_utc": cutoff.isoformat(),
                "scanned": counts["total"],
                "archived": archived,
                "purged": purged,
                "deleted": purged,
                "protected": counts["protected"] if purge_enabled else counts["total"],
                "failed": 0,
                "purge_enabled": purge_enabled,
                "preview_count": counts["eligible"],
                "duration_seconds": monotonic() - started,
            }
            await audit.record(
                action="maintenance.logs_retention",
                event_type="system_event",
                severity="INFO",
                entity_type="log_events",
                comments="Log retention cycle completed",
                context_payload=receipt,
            )
            await session.commit()
    except Exception as error:
        logger.error(
            "logs_retention_failed",
            policy_revision=policy_revision,
            mode=mode,
            cutoff_utc=cutoff.isoformat(),
            failed=1,
            reason=str(error)
            if isinstance(error, AuditRetentionPolicyError)
            else type(error).__name__,
            duration_seconds=monotonic() - started,
        )
        raise
    logger.info("logs_retention_completed", **receipt)
    return f"{archived} logs archived, {purged} logs purged"


@celery_app.task(
    name="cleanup_old_notifications",
    queue="maintenance",
    autoretry_for=(Exception,),
    retry_backoff=True,
    retry_jitter=True,
    max_retries=3,
)
def cleanup_old_notifications() -> str:
    logger.info("notifications_cleanup_starting")
    return run_async_task(_cleanup_old_notifications())


async def _cleanup_old_notifications() -> str:
    cutoff = utc_now() - timedelta(days=get_settings().notification_retention_days)

    async with AsyncSessionLocal() as session:
        notifications = list(
            (
                await session.execute(
                    select(Notification).where(
                        Notification.created_at < cutoff,
                        Notification.deleted_at.is_(None),
                    )
                )
            ).scalars()
        )

        for notification in notifications:
            notification.deleted_at = utc_now()

        await session.commit()
    logger.info("notifications_cleanup_completed", cleaned=len(notifications))
    return f"{len(notifications)} notifications cleaned up"


@celery_app.task(
    name="check_late_reports",
    queue="maintenance",
    autoretry_for=(Exception,),
    retry_backoff=True,
    retry_jitter=True,
    max_retries=3,
)
def check_late_reports() -> str:
    logger.info("late_reports_check_starting")
    return run_async_task(_check_late_reports())


async def _check_late_reports() -> str:
    cutoff = time(hour=10)
    now = utc_now()
    local_now = business_now()
    if local_now.time() < cutoff:
        return "late report cutoff has not passed"

    report_date = local_now.date() - timedelta(days=1)
    if report_date.weekday() == 4:
        return "late report check skipped for Friday"

    async with AsyncSessionLocal() as session:
        projects = (
            await session.execute(
                select(Project).where(Project.status == "active", Project.deleted_at.is_(None))
            )
        ).scalars()
        missing_count = 0
        for project in projects:
            existing_report = await session.scalar(
                select(DailyReport.id).where(
                    DailyReport.project_id == project.id,
                    DailyReport.report_date == report_date,
                    DailyReport.deleted_at.is_(None),
                )
            )
            if existing_report:
                continue
            missing_count += 1
            recipients = await _late_report_recipients(session, project.id)
            for user_id in recipients:
                existing = await session.scalar(
                    select(Notification.id).where(
                        Notification.user_id == user_id,
                        Notification.title == "Daily report missing",
                        Notification.reference_type == "projects",
                        Notification.reference_id == project.id,
                        Notification.created_at >= now - timedelta(hours=24),
                        Notification.deleted_at.is_(None),
                    )
                )
                if existing:
                    continue
                await NotificationService(session).create(
                    user_id=user_id,
                    title="Daily report missing",
                    body=f"{project.code} has no daily report for {report_date.isoformat()}.",
                    notification_type="report",
                    reference_type="projects",
                    reference_id=project.id,
                )
            await AuditService(session).record(
                action="daily_reports.late_missing",
                event_type="audit",
                entity_type="projects",
                entity_id=project.id,
                comments=f"Daily report missing for {report_date.isoformat()}",
                new_values={
                    "report_date": report_date.isoformat(),
                    "project_code": project.code,
                },
            )
        await session.commit()
    return f"{missing_count} late daily report alerts recorded"


@celery_app.task(
    name="check_supplier_tds_expiry",
    queue="maintenance",
    autoretry_for=(Exception,),
    retry_backoff=True,
    retry_jitter=True,
    max_retries=3,
)
def check_supplier_tds_expiry() -> str:
    logger.info("supplier_tds_expiry_check_starting")
    return run_async_task(_check_supplier_tds_expiry())


async def _check_supplier_tds_expiry() -> str:
    today = business_today()
    expiry_cutoff = today + timedelta(days=30)
    async with AsyncSessionLocal() as session:
        suppliers = list(
            (
                await session.scalars(
                    select(Supplier).where(
                        Supplier.is_active.is_(True),
                        Supplier.deleted_at.is_(None),
                        Supplier.tds_expiry_date.is_not(None),
                        Supplier.tds_expiry_date <= expiry_cutoff,
                    )
                )
            ).all()
        )
        recipients = await _supplier_compliance_recipients(session)
        sent = 0
        for supplier in suppliers:
            if not supplier.tds_expiry_date:
                continue
            for user_id in recipients:
                if await _recent_supplier_tds_notification_exists(session, user_id, supplier.id):
                    continue
                await NotificationService(session).create(
                    user_id=user_id,
                    title="Supplier TDS expiring",
                    body=(
                        f"{supplier.name} TDS certificate expires on "
                        f"{supplier.tds_expiry_date.isoformat()}."
                    ),
                    notification_type="supplier_compliance",
                    reference_type="suppliers",
                    reference_id=supplier.id,
                )
                sent += 1
        await session.commit()
    return f"{sent} supplier TDS expiry notifications sent"


@celery_app.task(
    name="check_hr_credential_expiry",
    autoretry_for=(Exception,),
    retry_backoff=True,
    retry_jitter=True,
    max_retries=3,
)
def check_hr_credential_expiry() -> int:
    return run_async_task(_check_hr_credential_expiry())


async def _check_hr_credential_expiry() -> int:
    days = get_settings().hr_reminder_window_days
    if days is None:
        return 0
    now = business_now()
    today = now.date()
    start = datetime.combine(today, time.min, tzinfo=now.tzinfo)
    end = datetime.combine(today + timedelta(days=1), time.min, tzinfo=now.tzinfo)
    async with AsyncSessionLocal() as session:
        await session.execute(text("SELECT pg_advisory_xact_lock(hashtext('garrison.hr_expiry'))"))
        employees = select(HrEmployee.id).where(
            HrEmployee.deleted_at.is_(None),
            HrEmployee.employment_status.in_(
                ("onboarding", "active", "on_probation", "on_leave", "notice_period")
            ),
        )
        window = HrReportWindow(date_from=today, date_to=today + timedelta(days=days))
        if not await count_report_credentials(session, employees, window):
            return 0
        already_notified = select(Notification.user_id).where(
            Notification.notification_type == "hr_credential_expiry",
            Notification.created_at >= start,
            Notification.created_at < end,
        )
        recipients = (
            await session.scalars(
                select(User.id).where(
                    User.role.in_(roles_with_permission(PERMISSION_HR_COMPLIANCE_MANAGE)),
                    User.is_active.is_(True),
                    User.deleted_at.is_(None),
                    User.id.not_in(already_notified),
                )
            )
        ).all()
        notifications = NotificationService(session)
        for user_id in recipients:
            await notifications.create(
                user_id=user_id,
                title="HR review reminder",
                body="Open HR & Workforce to review upcoming credential deadlines.",
                notification_type="hr_credential_expiry",
                send_email=False,
            )
        await session.commit()
        return len(recipients)


async def _late_report_recipients(session, project_id) -> set:
    company_directors = await session.scalars(
        select(User.id).where(
            User.role.in_(COMPANY_RESOURCE_ROLES),
            User.is_active.is_(True),
            User.deleted_at.is_(None),
        )
    )
    scoped_approvers = await session.scalars(
        select(User.id)
        .join(ProjectMember, ProjectMember.user_id == User.id)
        .where(
            ProjectMember.project_id == project_id,
            ProjectMember.deleted_at.is_(None),
            User.role.in_(REPORT_APPROVER_ROLES - COMPANY_RESOURCE_ROLES),
            User.is_active.is_(True),
            User.deleted_at.is_(None),
        )
    )
    return {*company_directors.all(), *scoped_approvers.all()}


async def _supplier_compliance_recipients(session) -> set:
    users = await session.scalars(
        select(User.id).where(
            User.role.in_(roles_with_permission(PERMISSION_SUPPLIERS_MANAGE)),
            User.is_active.is_(True),
            User.deleted_at.is_(None),
        )
    )
    return set(users.all())


async def _recent_supplier_tds_notification_exists(
    session,
    user_id,
    supplier_id,
) -> bool:
    cutoff = utc_now() - timedelta(days=7)
    existing = await session.scalar(
        select(Notification.id).where(
            Notification.user_id == user_id,
            Notification.title == "Supplier TDS expiring",
            Notification.reference_type == "suppliers",
            Notification.reference_id == supplier_id,
            Notification.created_at >= cutoff,
            Notification.deleted_at.is_(None),
        )
    )
    return existing is not None
