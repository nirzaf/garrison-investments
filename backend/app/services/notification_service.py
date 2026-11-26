from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession

from app.models.notification import Notification
from app.models.task_outbox import TaskOutbox, notification_email_outbox_dedupe_key
from app.models.user import User
from app.repositories.notification_repository import NotificationRepository

# Kept as a module attribute for existing test/operator patch points; dispatch is persisted below.
from app.tasks.email import send_email_notification  # noqa: F401
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
        send_email: bool = True,
        event_code: str | None = None,
        event_revision: int | None = None,
    ) -> Notification:
        notification = await self.notifications.add(
            Notification(
                user_id=user_id,
                title=title,
                body=body,
                notification_type=notification_type,
                reference_type=reference_type,
                reference_id=reference_id,
                event_code=event_code,
                event_revision=event_revision,
                email_status="queued" if send_email else None,
            )
        )
        if send_email:
            self.session.add(
                TaskOutbox(
                    dedupe_key=notification_email_outbox_dedupe_key(notification.id),
                    task_name="send_email_notification",
                    args_json=[str(notification.id)],
                    kwargs_json={},
                )
            )
        return notification

    async def list_for_user(
        self, user: User, *, limit: int = 100, offset: int = 0
    ) -> tuple[list[Notification], int]:
        return await self.notifications.list_for_user(user.id, limit=limit, offset=offset)

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

    async def set_muted(
        self,
        notification_id: UUID,
        user: User,
        *,
        muted: bool,
    ) -> Notification:
        notification = await self.notifications.get_for_user(notification_id, user.id)
        if not notification:
            raise NotFoundException("Notification")
        notification.muted = muted
        if muted:
            notification.is_read = True
            notification.read_at = notification.read_at or utc_now()
        await self.session.commit()
        return notification
