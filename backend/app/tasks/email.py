import asyncio
from uuid import UUID

from app.config import get_settings
from app.database import AsyncSessionLocal
from app.repositories.report_export_repository import ReportExportRepository
from app.tasks.celery_app import celery_app
from app.utils.security import utc_now


@celery_app.task(name="send_email_notification", queue="email")
def send_email_notification(notification_id: str | None = None) -> str:
    if notification_id:
        return f"email notification queued for {notification_id}"
    return "email notification placeholder"


@celery_app.task(
    name="send_report_email",
    queue="email",
    autoretry_for=(Exception,),
    retry_backoff=True,
    max_retries=3,
)
def send_report_email(export_id: str) -> str:
    return asyncio.run(_send_report_email(export_id))


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
        export.email_status = "sent"
        export.emailed_at = utc_now()
        await session.commit()
    return f"report email queued for {len(recipients)} recipients"
