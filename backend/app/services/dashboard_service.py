from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.daily_report import DailyReport
from app.models.document import Document
from app.models.notification import Notification
from app.models.project import Project
from app.models.project_member import ProjectMember
from app.models.user import User
from app.schemas.dashboard import DashboardSummaryResponse
from app.utils.permissions import (
    ROLE_ADMIN,
    ROLE_GENERAL_MANAGER,
    ROLE_OPERATION_MANAGER,
)


class DashboardService:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def summary(self, actor: User) -> DashboardSummaryResponse:
        project_ids = await self._visible_project_ids(actor)
        active_projects = await self._count_projects(project_ids)
        pending_reports = await self._count_reports(project_ids, "submitted")
        approved_reports = await self._count_reports(project_ids, "approved")
        pending_documents = await self._count_documents(project_ids)
        unread_notifications = await self._count_notifications(actor)
        recent_activity = await self._recent_activity(project_ids)
        return DashboardSummaryResponse(
            active_projects=active_projects,
            pending_reports=pending_reports,
            approved_reports=approved_reports,
            pending_documents=pending_documents,
            unread_notifications=unread_notifications,
            recent_activity=recent_activity,
        )

    async def _visible_project_ids(self, actor: User) -> list | None:
        if actor.role in {ROLE_ADMIN, ROLE_GENERAL_MANAGER, ROLE_OPERATION_MANAGER}:
            return None
        result = await self.session.execute(
            select(ProjectMember.project_id).where(
                ProjectMember.user_id == actor.id,
                ProjectMember.deleted_at.is_(None),
            )
        )
        return list(result.scalars().all())

    async def _count_projects(self, project_ids: list | None) -> int:
        query = (
            select(func.count())
            .select_from(Project)
            .where(
                Project.status == "active",
                Project.deleted_at.is_(None),
            )
        )
        if project_ids is not None:
            if not project_ids:
                return 0
            query = query.where(Project.id.in_(project_ids))
        return int(await self.session.scalar(query) or 0)

    async def _count_reports(self, project_ids: list | None, status: str) -> int:
        query = (
            select(func.count())
            .select_from(DailyReport)
            .where(
                DailyReport.status == status,
                DailyReport.deleted_at.is_(None),
            )
        )
        if project_ids is not None:
            if not project_ids:
                return 0
            query = query.where(DailyReport.project_id.in_(project_ids))
        return int(await self.session.scalar(query) or 0)

    async def _count_documents(self, project_ids: list | None) -> int:
        query = (
            select(func.count())
            .select_from(Document)
            .where(
                Document.status == "pending_approval",
                Document.deleted_at.is_(None),
            )
        )
        if project_ids is not None:
            if not project_ids:
                return 0
            query = query.where(Document.project_id.in_(project_ids))
        return int(await self.session.scalar(query) or 0)

    async def _count_notifications(self, actor: User) -> int:
        return int(
            await self.session.scalar(
                select(func.count())
                .select_from(Notification)
                .where(
                    Notification.user_id == actor.id,
                    Notification.is_read.is_(False),
                    Notification.deleted_at.is_(None),
                )
            )
            or 0
        )

    async def _recent_activity(self, project_ids: list | None) -> list[str]:
        query = select(DailyReport.report_number, DailyReport.status).where(
            DailyReport.deleted_at.is_(None)
        )
        if project_ids is not None:
            if not project_ids:
                return []
            query = query.where(DailyReport.project_id.in_(project_ids))
        result = await self.session.execute(query.order_by(DailyReport.created_at.desc()).limit(5))
        return [f"{number or 'Draft report'}: {status}" for number, status in result.all()]
