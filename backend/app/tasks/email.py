import asyncio
from uuid import UUID

import structlog
from sqlalchemy import select

from app.config import get_settings
from app.database import AsyncSessionLocal
from app.models.hr import HrEmployee, HrLeaveRequest
from app.models.notification import Notification
from app.repositories.notification_repository import NotificationRepository
from app.repositories.report_export_repository import ReportExportRepository
from app.repositories.user_repository import UserRepository
from app.services.email_service import EmailDeliveryError, EmailService
from app.tasks.async_utils import run_async_task
from app.tasks.celery_app import celery_app
from app.utils.permissions import BUSINESS_ROLES, PERMISSION_HR_LEAVE_APPROVE, has_permission
from app.utils.security import utc_now
from app.utils.time import business_today

logger = structlog.get_logger("celery.task")


@celery_app.task(
    name="send_email_notification",
    queue="email",
    autoretry_for=(Exception,),
    retry_backoff=True,
    retry_jitter=True,
    max_retries=3,
)
def send_email_notification(notification_id: str | None = None) -> str:
    if notification_id is None:
        logger.warning("email_skipped", reason="notification_id is None")
        return "notification id required"
    logger.info("email_sending", notification_id=notification_id)
    return run_async_task(_send_email_notification(notification_id))


async def _send_email_notification(notification_id: str) -> str:
    # ApprovalService creates notifications through the service that queues this task.
    from app.services.approval_service import ApprovalService

    async with AsyncSessionLocal() as session:
        notifications = NotificationRepository(session)
        users = UserRepository(session)

        notification = await notifications.get_by_id(UUID(notification_id))
        if not notification:
            logger.warning("email_notification_not_found", notification_id=notification_id)
            return "notification not found"
        if notification.reference_type == "hr_leave_request":
            notification = await session.scalar(
                select(Notification)
                .where(Notification.id == notification.id, Notification.deleted_at.is_(None))
                .with_for_update()
                .execution_options(populate_existing=True)
            )
            if notification is None:
                return "notification not found"
        if notification.email_status == "sent":
            return "notification email already sent"
        if notification.muted:
            notification.email_status = "skipped"
            await session.commit()
            logger.info("email_muted", notification_id=notification_id)
            return "notification email skipped"
        user = await users.get_by_id(notification.user_id)
        if user is None:
            notification.email_status = "failed"
            await session.commit()
            logger.error("email_recipient_not_found", user_id=str(notification.user_id))
            return "notification recipient not found"
        if notification.reference_type == "hr_leave_request":
            if not await _can_deliver_leave_notification(session, notification, user):
                notification.email_status = "skipped"
                await session.commit()
                logger.info("leave_email_no_longer_actionable", notification_id=notification_id)
                return "notification email skipped"
        elif not await ApprovalService(session).can_deliver_scheduled_email(notification):
            if notification.email_status != "sent":
                notification.email_status = "skipped"
            await session.commit()
            logger.info("approval_email_no_longer_actionable", notification_id=notification_id)
            return "notification email skipped"

        try:
            delivered = await asyncio.to_thread(
                EmailService().send,
                recipients=[user.email],
                subject=notification.title,
                body=notification.body,
            )
            if delivered <= 0:
                raise EmailDeliveryError("No notification recipient accepted the email.")
        except Exception:
            notification.email_status = "failed"
            await session.commit()
            raise
        notification.email_status = "sent"
        await session.commit()
    logger.info("email_sent", notification_id=notification_id, recipient=user.email)
    return f"notification email sent to {delivered} recipient"


async def _can_deliver_leave_notification(session, notification: Notification, user) -> bool:
    if (
        notification.reference_id is None
        or notification.event_code
        not in {"submitted", "resubmitted", "rerouted", "approved", "rejected", "cancelled"}
        or notification.event_revision is None
        or not user.is_active
        or user.deleted_at is not None
        or user.role not in BUSINESS_ROLES
    ):
        return False
    request = await session.scalar(
        select(HrLeaveRequest).where(HrLeaveRequest.id == notification.reference_id)
    )
    if request is None or request.record_revision != notification.event_revision:
        return False
    event = notification.event_code
    manager_employee_id = await session.scalar(
        select(HrEmployee.manager_employee_id).where(
            HrEmployee.id == request.employee_id,
            HrEmployee.deleted_at.is_(None),
        )
    )
    current_manager_user = None
    if manager_employee_id is not None:
        current_manager_user = await session.scalar(
            select(HrEmployee.user_id).where(
                HrEmployee.id == manager_employee_id,
                HrEmployee.deleted_at.is_(None),
                HrEmployee.employment_status.in_(
                    ("active", "on_probation", "on_leave", "notice_period")
                ),
            )
        )
    if event in {"submitted", "resubmitted", "rerouted"}:
        if request.status != "submitted":
            return False
        if request.approval_route == "supervisor":
            return (
                request.assigned_supervisor_user_id == user.id
                and request.requested_by_id != user.id
                and request.assigned_supervisor_user_id == current_manager_user
            )
        return (
            request.approval_route == "hr_fallback"
            and has_permission(user, PERMISSION_HR_LEAVE_APPROVE)
            and (request.fallback_until is None or request.fallback_until >= business_today())
        )
    if request.status != event:
        return False
    if has_permission(user, PERMISSION_HR_LEAVE_APPROVE):
        return True
    if request.requested_by_id == user.id:
        return True
    employee_user = await session.scalar(
        select(HrEmployee.user_id).where(
            HrEmployee.id == request.employee_id,
            HrEmployee.deleted_at.is_(None),
        )
    )
    if employee_user == user.id:
        return True
    if request.assigned_supervisor_user_id != user.id:
        return False
    return current_manager_user == user.id


@celery_app.task(
    name="send_report_email",
    queue="email",
    autoretry_for=(Exception,),
    retry_backoff=True,
    max_retries=3,
)
def send_report_email(export_id: str) -> str:
    logger.info("report_email_sending", export_id=export_id)
    return run_async_task(_send_report_email(export_id))


async def _send_report_email(export_id: str) -> str:
    settings = get_settings()
    recipients = [
        item.strip() for item in settings.report_email_recipients.split(",") if item.strip()
    ]
    async with AsyncSessionLocal() as session:
        export = await ReportExportRepository(session).get_by_id(UUID(export_id), for_update=True)
        if not export:
            logger.warning("report_email_export_not_found", export_id=export_id)
            return "report export not found"
        if export.email_status == "sent":
            return "report email already sent"
        if not recipients:
            export.email_status = "skipped"
            export.email_error = "No report email recipients configured."
            await session.commit()
            logger.warning("report_email_no_recipients")
            return "report email skipped"

        try:
            delivered = await asyncio.to_thread(
                EmailService().send,
                recipients=recipients,
                subject=f"Daily report export ready: {export.file_name}",
                body=(
                    "A daily report export is ready.\n\n"
                    f"File: {export.file_name}\n"
                    f"Object key: {export.object_key}\n"
                    f"Content type: {export.content_type}\n"
                ),
            )
            if delivered <= 0:
                raise EmailDeliveryError("No report recipient accepted the email.")
        except Exception as exc:
            export.email_status = "failed"
            export.email_error = str(exc)
            await session.commit()
            raise
        export.email_status = "sent"
        export.email_error = None
        export.emailed_at = utc_now()
        await session.commit()
    logger.info(
        "report_email_sent",
        export_id=export_id,
        file_name=export.file_name,
        recipients=recipients,
    )
    return f"report email sent to {delivered} recipients"
