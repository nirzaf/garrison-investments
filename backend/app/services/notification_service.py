import asyncio
from uuid import UUID

from sqlalchemy import event
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import Session as SyncSession

from app.database import AsyncSessionLocal
from app.models.notification import Notification
from app.models.user import User
from app.repositories.notification_repository import NotificationRepository
from app.tasks.email import send_email_notification
from app.utils.exceptions import NotFoundException
from app.utils.security import utc_now

PENDING_EMAIL_NOTIFICATION_IDS = "pending_email_notification_ids"


async def _mark_email_enqueue_failed(notification_id: UUID) -> None:
    async with AsyncSessionLocal() as session:
        notification = await session.get(Notification, notification_id)
        if not notification:
            return
        notification.email_status = "failed"
        await session.commit()


def _schedule_email_enqueue_failure_update(notification_id: UUID) -> None:
    try:
        loop = asyncio.get_running_loop()
    except RuntimeError:
        asyncio.run(_mark_email_enqueue_failed(notification_id))
        return
    loop.create_task(_mark_email_enqueue_failed(notification_id))


@event.listens_for(SyncSession, "after_commit")
def _enqueue_pending_notification_emails(session: SyncSession) -> None:
    notification_ids = session.info.pop(PENDING_EMAIL_NOTIFICATION_IDS, set())
    for notification_id in notification_ids:
        try:
            send_email_notification.delay(str(notification_id))
        except Exception:
            _schedule_email_enqueue_failure_update(notification_id)


@event.listens_for(SyncSession, "after_rollback")
def _discard_pending_notification_emails(session: SyncSession) -> None:
    session.info.pop(PENDING_EMAIL_NOTIFICATION_IDS, None)


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
        pending_ids = self.session.info.setdefault(PENDING_EMAIL_NOTIFICATION_IDS, set())
        pending_ids.add(notification.id)
        self.session.sync_session.info[PENDING_EMAIL_NOTIFICATION_IDS] = pending_ids
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
