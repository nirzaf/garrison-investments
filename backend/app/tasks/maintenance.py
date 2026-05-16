import asyncio
from datetime import time, timedelta

from sqlalchemy import select

from app.database import AsyncSessionLocal
from app.models.activity_log import ActivityLog
from app.models.daily_report import DailyReport
from app.models.project import Project
from app.tasks.celery_app import celery_app
from app.utils.security import utc_now


@celery_app.task(name="cleanup_old_notifications", queue="maintenance")
def cleanup_old_notifications() -> str:
    return "notification cleanup placeholder"


@celery_app.task(name="check_late_reports", queue="maintenance")
def check_late_reports() -> str:
    return asyncio.run(_check_late_reports())


async def _check_late_reports() -> str:
    cutoff = time(hour=10)
    now = utc_now()
    if now.time() < cutoff:
        return "late report cutoff has not passed"

    report_date = now.date() - timedelta(days=1)
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
            session.add(
                ActivityLog(
                    action="daily_reports.late_missing",
                    entity_type="projects",
                    entity_id=project.id,
                    comments=f"Daily report missing for {report_date.isoformat()}",
                    new_values={
                        "report_date": report_date.isoformat(),
                        "project_code": project.code,
                    },
                )
            )
        await session.commit()
    return f"{missing_count} late daily report alerts recorded"


@celery_app.task(name="check_low_stock", queue="maintenance")
def check_low_stock() -> str:
    return "low stock check placeholder"
