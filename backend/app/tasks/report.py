import asyncio
from uuid import UUID

from app.database import AsyncSessionLocal
from app.services.report_export_service import ReportExportService
from app.tasks.celery_app import celery_app
from app.tasks.email import send_report_email


@celery_app.task(
    name="generate_report_pdf",
    queue="report",
    autoretry_for=(Exception,),
    retry_backoff=True,
    max_retries=3,
)
def generate_report_pdf(
    report_id: str,
    actor_id: str | None = None,
    *,
    email_after: bool = False,
) -> str:
    export_id = asyncio.run(_generate_report_pdf(report_id, actor_id))
    if email_after:
        send_report_email.delay(export_id)
    return export_id


async def _generate_report_pdf(report_id: str, actor_id: str | None) -> str:
    async with AsyncSessionLocal() as session:
        export = await ReportExportService(session).generate_pdf_export(
            UUID(report_id),
            actor=None,
        )
        if actor_id:
            export.generated_by = UUID(actor_id)
            await session.commit()
        return str(export.id)


@celery_app.task(name="generate_excel_export", queue="report")
def generate_excel_export() -> str:
    return "excel export placeholder"
