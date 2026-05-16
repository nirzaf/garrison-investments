from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession

from app.models.notification import Notification
from app.models.user import User
from app.repositories.notification_repository import NotificationRepository
from app.tasks.email import send_email_notification
from app.utils.exceptions import NotFoundException
from app.utils.security import utc_now


class NotificationService:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session
        self.notifications = NotificationRepository(session)

    async def create(
        self,
        *,
        user_id: UUID,
        title: str,
        body: str,
        notification_type: str,
        reference_type: str | None = None,
        reference_id: UUID | None = None,
    ) -> Notification:
        notification = await self.notifications.add(
            Notification(
                user_id=user_id,
                title=title,
                body=body,
                notification_type=notification_type,
                reference_type=reference_type,
                reference_id=reference_id,
                email_status="queued",
            )
        )
        try:
            send_email_notification.delay(str(notification.id))
        except Exception:
            notification.email_status = "failed"
        return notification

    async def list_for_user(self, user: User) -> tuple[list[Notification], int]:
        return await self.notifications.list_for_user(user.id)

    async def unread_count(self, user: User) -> int:
        return await self.notifications.unread_count(user.id)

    async def mark_read(self, notification_id: UUID, user: User) -> Notification:
        notification = await self.notifications.get_for_user(notification_id, user.id)
        if not notification:
            raise NotFoundException("Notification")
        notification.is_read = True
        notification.read_at = utc_now()
        await self.session.commit()
        return notification

    async def mark_all_read(self, user: User) -> int:
        changed = await self.notifications.mark_all_read(user.id, utc_now())
        await self.session.commit()
        return changed
