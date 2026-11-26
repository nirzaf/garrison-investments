import asyncio
from datetime import timedelta
from uuid import UUID

import structlog
from sqlalchemy import select

from app.config import get_settings
from app.database import AsyncSessionLocal
from app.models.hr import HrEmployee, HrLeaveRequest
from app.models.notification import Notification
from app.models.task_outbox import TaskOutbox, notification_email_outbox_dedupe_key
from app.repositories.report_export_repository import ReportExportRepository
from app.repositories.user_repository import UserRepository
from app.services.email_service import EmailDeliveryError, EmailService
from app.tasks.async_utils import run_async_task
from app.tasks.celery_app import celery_app
from app.utils.permissions import BUSINESS_ROLES, PERMISSION_HR_LEAVE_APPROVE, has_permission
from app.utils.security import utc_now

logger = structlog.get_logger("celery.task")


@celery_app.task(
    name="send_email_notification",
    queue="email",
)
def send_email_notification(notification_id: str | None = None) -> str:
    if notification_id is None:
        logger.warning("email_skipped", reason="notification_id is None")
        return "notification id required"
    logger.info("email_sending", notification_id=notification_id)
    return run_async_task(_send_email_notification(notification_id))


async def _send_email_notification(notification_id: str) -> str:
    from app.services.approval_service import ApprovalService

    parsed_id = UUID(notification_id)
    title: str | None = None
    body: str | None = None
    recipient: str | None = None
    async with AsyncSessionLocal() as session:
        users = UserRepository(session)
        outbox = await session.scalar(
            select(TaskOutbox)
            .where(TaskOutbox.dedupe_key == notification_email_outbox_dedupe_key(parsed_id))
            .with_for_update()
            .execution_options(populate_existing=True)
        )
        notification = await session.scalar(
            select(Notification)
            .where(Notification.id == parsed_id, Notification.deleted_at.is_(None))
            .with_for_update()
            .execution_options(populate_existing=True)
        )
        if not notification:
            logger.warning("email_notification_not_found", notification_id=notification_id)
            if outbox is not None:
                outbox.status = "failed"
                outbox.lease_until = None
                await session.commit()
            return "notification not found"
        if outbox is not None and outbox.status in {"completed", "failed", "manual_review"}:
            return "notification email is not eligible for delivery"
        if outbox is not None and outbox.status == "processing" and outbox.lease_until is not None:
            if outbox.lease_until > utc_now():
                return "notification email is already claimed"
            outbox.status = "manual_review"
            outbox.lease_until = None
            notification.email_status = "unknown"
            await session.commit()
            return "notification email delivery outcome requires review"
        if outbox is not None and outbox.status not in {"dispatching", "dispatched"}:
            return "notification email is not ready for delivery"
        if notification.email_status == "sent":
            if outbox is not None:
                outbox.status = "completed"
                outbox.lease_until = None
                await session.commit()
            return "notification email already sent"
        if notification.email_status in {"skipped", "unknown", "sending"}:
            return "notification email is not eligible for delivery"
        if notification.muted or notification.superseded_at is not None:
            notification.email_status = "skipped"
            if outbox is not None:
                outbox.status = "completed"
                outbox.lease_until = None
            await session.commit()
            logger.info("email_not_actionable", notification_id=notification_id)
            return "notification email skipped"
        user = await users.get_by_id(notification.user_id)
        if user is None or not user.is_active or user.deleted_at is not None:
            notification.email_status = "failed"
            if outbox is not None:
                outbox.status = "failed"
                outbox.lease_until = None
            await session.commit()
            logger.error("email_recipient_not_eligible", notification_id=notification_id)
            return "notification recipient not found"
        if notification.reference_type == "hr_leave_request":
            if not await _can_deliver_leave_notification(session, notification, user):
                notification.email_status = "skipped"
                if outbox is not None:
                    outbox.status = "completed"
                    outbox.lease_until = None
                await session.commit()
                logger.info("leave_email_no_longer_actionable", notification_id=notification_id)
                return "notification email skipped"
        elif not await ApprovalService(session).can_deliver_scheduled_email(notification):
            if notification.email_status != "sent":
                notification.email_status = "skipped"
            if outbox is not None:
                outbox.status = "completed"
                outbox.lease_until = None
            await session.commit()
            logger.info("approval_email_no_longer_actionable", notification_id=notification_id)
            return "notification email skipped"
        notification.email_status = "sending"
        title = notification.title
        body = notification.body
        recipient = user.email
        if outbox is not None:
            outbox.status = "processing"
            outbox.lease_until = utc_now() + timedelta(minutes=5)
        await session.commit()

    if title is None or body is None or recipient is None:
        return "notification email not eligible for delivery"
    try:
        delivered = await asyncio.to_thread(
            EmailService().send,
            recipients=[recipient],
            subject=title,
            body=body,
        )
        if delivered <= 0:
            raise EmailDeliveryError("No notification recipient accepted the email.")
    except Exception as exc:
        async with AsyncSessionLocal() as session:
            outbox = await session.scalar(
                select(TaskOutbox)
                .where(TaskOutbox.dedupe_key == notification_email_outbox_dedupe_key(parsed_id))
                .with_for_update()
                .execution_options(populate_existing=True)
            )
            notification = await session.scalar(
                select(Notification)
                .where(Notification.id == parsed_id)
                .with_for_update()
                .execution_options(populate_existing=True)
            )
            if notification is not None and notification.email_status == "sending":
                notification.email_status = "unknown"
            if outbox is not None and outbox.status == "processing":
                outbox.status = "manual_review"
                outbox.lease_until = None
            await session.commit()
        logger.warning(
            "email_delivery_outcome_unknown",
            notification_id=notification_id,
            error_type=type(exc).__name__,
        )
        return "notification email delivery outcome requires review"

    async with AsyncSessionLocal() as session:
        outbox = await session.scalar(
            select(TaskOutbox)
            .where(TaskOutbox.dedupe_key == notification_email_outbox_dedupe_key(parsed_id))
            .with_for_update()
            .execution_options(populate_existing=True)
        )
        notification = await session.scalar(
            select(Notification)
            .where(Notification.id == parsed_id)
            .with_for_update()
            .execution_options(populate_existing=True)
        )
        if notification is not None and notification.email_status == "sending":
            notification.email_status = "sent"
        if outbox is not None and outbox.status == "processing":
            outbox.status = "completed"
            outbox.lease_until = None
        await session.commit()
    logger.info("email_sent", notification_id=notification_id)
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
    from app.services.hr_workforce_service import HrWorkforceService

    workflow = HrWorkforceService(session)
    employee = await session.scalar(
        select(HrEmployee).where(
            HrEmployee.id == request.employee_id,
            HrEmployee.deleted_at.is_(None),
        )
    )
    if employee is None:
        return False
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
        if (
            request.status != "submitted"
            or user.id in {employee.user_id, request.requested_by_id}
            or not await workflow._leave_route_is_current(request, employee)
        ):
            return False
        if request.approval_route == "supervisor":
            return (
                request.assigned_supervisor_user_id == user.id
                and request.requested_by_id != user.id
                and request.assigned_supervisor_user_id == current_manager_user
            )
        if request.approval_route != "hr_fallback" or not has_permission(
            user, PERMISSION_HR_LEAVE_APPROVE
        ):
            return False
        eligible = await workflow._eligible_hr_leave_approver_ids(request)
        return user.id in eligible
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
