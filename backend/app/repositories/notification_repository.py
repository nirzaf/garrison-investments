from datetime import datetime
from uuid import UUID

from sqlalchemy import func, or_, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.notification import Notification


class NotificationRepository:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def get_by_id(self, notification_id: UUID) -> Notification | None:
        result = await self.session.execute(
            select(Notification).where(
                Notification.id == notification_id,
                Notification.deleted_at.is_(None),
            )
        )
        return result.scalar_one_or_none()

    async def add(self, notification: Notification) -> Notification:
        self.session.add(notification)
        await self.session.flush()
        return notification

    async def get_for_user(self, notification_id: UUID, user_id: UUID) -> Notification | None:
        result = await self.session.execute(
            select(Notification).where(
                Notification.id == notification_id,
                Notification.user_id == user_id,
                Notification.deleted_at.is_(None),
            )
        )
        return result.scalar_one_or_none()

    async def list_for_user(
        self, user_id: UUID, *, limit: int = 100, offset: int = 0
    ) -> tuple[list[Notification], int]:
        query = select(Notification).where(
            Notification.user_id == user_id,
            Notification.deleted_at.is_(None),
        )
        total = await self.session.scalar(
            select(func.count()).select_from(query.with_only_columns(Notification.id).subquery())
        )
        result = await self.session.execute(
            query.order_by(Notification.created_at.desc(), Notification.id.desc())
            .limit(limit)
            .offset(offset)
        )
        return list(result.scalars().all()), int(total or 0)

    async def unread_count(self, user_id: UUID) -> int:
        total = await self.session.scalar(
            select(func.count())
            .select_from(Notification)
            .where(
                Notification.user_id == user_id,
                Notification.is_read.is_(False),
                Notification.muted.is_(False),
                Notification.deleted_at.is_(None),
                or_(
                    Notification.reference_type.is_(None),
                    Notification.reference_type != "hr_leave_request",
                    Notification.event_code.is_(None),
                    Notification.event_code.not_in(("submitted", "resubmitted", "rerouted")),
                    Notification.superseded_at.is_(None),
                ),
            )
        )
        return int(total or 0)

    async def mark_all_read(self, user_id: UUID, read_at: datetime) -> int:
        result = await self.session.execute(
            update(Notification)
            .where(
                Notification.user_id == user_id,
                Notification.is_read.is_(False),
                Notification.deleted_at.is_(None),
            )
            .values(
                is_read=True,
                read_at=func.coalesce(Notification.read_at, read_at),
            )
            .returning(Notification.id)
            .execution_options(synchronize_session=False)
        )
        return len(result.scalars().all())
