from datetime import date
from uuid import UUID

import structlog

from app.database import AsyncSessionLocal
from app.models.user import User
from app.services.analytics_service import AnalyticsService
from app.services.report_export_service import ReportExportService
from app.tasks.async_utils import run_async_task
from app.tasks.celery_app import celery_app
from app.tasks.email import send_report_email

logger = structlog.get_logger("celery.task")


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
    logger.info("pdf_generating", report_id=report_id, actor_id=actor_id, email_after=email_after)
    export_id = run_async_task(_generate_report_pdf(report_id, actor_id))
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
        logger.info("pdf_generated", report_id=report_id, export_id=str(export.id))
        return str(export.id)


@celery_app.task(
    name="generate_excel_export",
    queue="report",
    autoretry_for=(Exception,),
    retry_backoff=True,
    retry_jitter=True,
    max_retries=3,
)
def generate_excel_export(
    export_type: str = "project-progress",
    actor_id: str | None = None,
    filters: dict | None = None,
) -> str:
    if actor_id is None:
        raise ValueError("Export actor is required")
    if export_type == "management-summary":
        raise ValueError("generate_excel_export only supports XLSX exports")
    logger.info("excel_generating", export_type=export_type, actor_id=actor_id)
    return run_async_task(_generate_management_export(export_type, actor_id, filters or {}))


@celery_app.task(
    name="generate_management_export",
    queue="report",
    autoretry_for=(Exception,),
    retry_backoff=True,
    retry_jitter=True,
    max_retries=3,
)
def generate_management_export(export_type: str, actor_id: str, filters: dict) -> str:
    logger.info("management_export_generating", export_type=export_type, actor_id=actor_id)
    return run_async_task(_generate_management_export(export_type, actor_id, filters))


async def _generate_management_export(export_type: str, actor_id: str, filters: dict) -> str:
    async with AsyncSessionLocal() as session:
        actor = await session.get(User, UUID(actor_id))
        if actor is None:
            raise ValueError("Export actor not found")
        service = AnalyticsService(session)
        project_id = UUID(filters["project_id"]) if filters.get("project_id") else None
        date_from = (
            date.fromisoformat(filters["date_from"]) if filters.get("date_from") else None
        )
        date_to = date.fromisoformat(filters["date_to"]) if filters.get("date_to") else None
        location = filters.get("location")
        department = filters.get("department")
        if export_type == "project-progress":
            data = await service.project_progress_export(
                actor,
                project_id=project_id,
                date_from=date_from,
                date_to=date_to,
                location=location,
                department=department,
            )
            content_type = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
        elif export_type == "material-usage":
            data = await service.material_usage_export(
                actor,
                project_id=project_id,
                date_from=date_from,
                date_to=date_to,
                department=department,
            )
            content_type = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
        elif export_type == "management-summary":
            data = await service.management_pdf_summary(
                actor,
                project_id=project_id,
                date_from=date_from,
                date_to=date_to,
                location=location,
                department=department,
            )
            content_type = "application/pdf"
        else:
            raise ValueError("Unknown management export type")
        object_key = service.upload_export(export_type, data, content_type)
        logger.info("management_export_completed", export_type=export_type, object_key=object_key)
        return object_key
