from uuid import UUID

from sqlalchemy import Select, func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.sql.elements import ColumnElement

from app.models.activity_log import ActivityLog


class AuditService:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def record(
        self,
        *,
        action: str,
        user_id: UUID | None = None,
        entity_type: str | None = None,
        entity_id: UUID | None = None,
        ip_address: str | None = None,
        user_agent: str | None = None,
        comments: str | None = None,
        old_values: dict | None = None,
        new_values: dict | None = None,
    ) -> None:
        self.session.add(
            ActivityLog(
                user_id=user_id,
                action=action,
                entity_type=entity_type,
                entity_id=entity_id,
                ip_address=ip_address,
                user_agent=user_agent,
                comments=comments,
                old_values=old_values,
                new_values=new_values,
            )
        )

    async def list_logs(
        self,
        *,
        action: str | None = None,
        entity_type: str | None = None,
        user_id: UUID | None = None,
        search: str | None = None,
        limit: int = 100,
        offset: int = 0,
    ) -> tuple[list[ActivityLog], int]:
        filters: list[ColumnElement[bool]] = [ActivityLog.deleted_at.is_(None)]
        if action:
            filters.append(ActivityLog.action == action)
        if entity_type:
            filters.append(ActivityLog.entity_type == entity_type)
        if user_id:
            filters.append(ActivityLog.user_id == user_id)
        if search:
            pattern = f"%{search.strip()}%"
            filters.append(
                or_(
                    ActivityLog.action.ilike(pattern),
                    ActivityLog.entity_type.ilike(pattern),
                    ActivityLog.comments.ilike(pattern),
                )
            )

        query: Select[tuple[ActivityLog]] = (
            select(ActivityLog)
            .where(*filters)
            .order_by(ActivityLog.created_at.desc())
            .limit(limit)
            .offset(offset)
        )
        total_query = select(func.count()).select_from(ActivityLog).where(*filters)
        logs = list((await self.session.scalars(query)).all())
        total = int(await self.session.scalar(total_query) or 0)
        return logs, total
