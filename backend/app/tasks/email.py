from uuid import UUID

from app.config import get_settings
from app.database import AsyncSessionLocal
from app.repositories.notification_repository import NotificationRepository
from app.repositories.report_export_repository import ReportExportRepository
from app.repositories.user_repository import UserRepository
from app.services.email_service import EmailService
from app.tasks.async_utils import run_async_task
from app.tasks.celery_app import celery_app
from app.utils.security import utc_now


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
        return "notification id required"
    return run_async_task(_send_email_notification(notification_id))


async def _send_email_notification(notification_id: str) -> str:
    async with AsyncSessionLocal() as session:
        notifications = NotificationRepository(session)
        users = UserRepository(session)

        notification = await notifications.get_by_id(UUID(notification_id))
        if not notification:
            return "notification not found"
        if notification.muted:
            notification.email_status = "skipped"
            await session.commit()
            return "notification email skipped"

        user = await users.get_by_id(notification.user_id)
        if user is None:
            notification.email_status = "failed"
            await session.commit()
            return "notification recipient not found"

        try:
            delivered = EmailService().send(
                recipients=[user.email],
                subject=notification.title,
                body=notification.body,
            )
        except Exception:
            notification.email_status = "failed"
            await session.commit()
            raise
        notification.email_status = "sent"
        await session.commit()
    return f"notification email sent to {delivered} recipient"


@celery_app.task(
    name="send_report_email",
    queue="email",
    autoretry_for=(Exception,),
    retry_backoff=True,
    max_retries=3,
)
def send_report_email(export_id: str) -> str:
    return run_async_task(_send_report_email(export_id))


async def _send_report_email(export_id: str) -> str:
    settings = get_settings()
    recipients = [
        item.strip() for item in settings.report_email_recipients.split(",") if item.strip()
    ]
    async with AsyncSessionLocal() as session:
        export = await ReportExportRepository(session).get_by_id(UUID(export_id))
        if not export:
            return "report export not found"
        if not recipients:
            export.email_status = "skipped"
            export.email_error = "No report email recipients configured."
            await session.commit()
            return "report email skipped"

        try:
            delivered = EmailService().send(
                recipients=recipients,
                subject=f"Daily report export ready: {export.file_name}",
                body=(
                    "A daily report export is ready.\n\n"
                    f"File: {export.file_name}\n"
                    f"Object key: {export.object_key}\n"
                    f"Content type: {export.content_type}\n"
                ),
            )
        except Exception as exc:
            export.email_status = "failed"
            export.email_error = str(exc)
            await session.commit()
            raise
        export.email_status = "sent"
        export.email_error = None
        export.emailed_at = utc_now()
        await session.commit()
    return f"report email sent to {delivered} recipients"
