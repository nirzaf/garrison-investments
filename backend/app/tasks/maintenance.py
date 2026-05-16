import asyncio
from datetime import time, timedelta

from sqlalchemy import select

from app.config import get_settings
from app.database import AsyncSessionLocal
from app.models.activity_log import ActivityLog
from app.models.daily_report import DailyReport
from app.models.notification import Notification
from app.models.project import Project
from app.models.project_member import ProjectMember
from app.models.user import User
from app.services.notification_service import NotificationService
from app.tasks.celery_app import celery_app
from app.utils.permissions import ROLE_OPERATION_MANAGER, ROLE_PROJECT_MANAGER
from app.utils.security import utc_now


@celery_app.task(name="cleanup_old_notifications", queue="maintenance")
def cleanup_old_notifications() -> str:
    return asyncio.run(_cleanup_old_notifications())


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
    return f"{len(notifications)} notifications cleaned up"


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


async def _late_report_recipients(session, project_id) -> set:
    operation_managers = await session.scalars(
        select(User.id).where(
            User.role == ROLE_OPERATION_MANAGER,
            User.is_active.is_(True),
            User.deleted_at.is_(None),
        )
    )
    project_managers = await session.scalars(
        select(User.id)
        .join(ProjectMember, ProjectMember.user_id == User.id)
        .where(
            ProjectMember.project_id == project_id,
            ProjectMember.deleted_at.is_(None),
            User.role == ROLE_PROJECT_MANAGER,
            User.is_active.is_(True),
            User.deleted_at.is_(None),
        )
    )
    return {*operation_managers.all(), *project_managers.all()}
