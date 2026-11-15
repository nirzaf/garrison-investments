from datetime import timedelta
from uuid import UUID

import structlog
from sqlalchemy import select

from app.database import AsyncSessionLocal
from app.models.inventory import InventoryLocationStock
from app.models.notification import Notification
from app.models.project_member import ProjectMember
from app.models.user import User
from app.services.approval_service import ApprovalService
from app.services.inventory_service import InventoryService
from app.services.notification_service import NotificationService
from app.tasks.async_utils import run_async_task
from app.tasks.celery_app import celery_app
from app.utils.permissions import (
    COMPANY_RESOURCE_ROLES,
    PERMISSION_INVENTORY_VIEW,
    roles_with_permission,
)
from app.utils.security import utc_now

logger = structlog.get_logger("celery.task")


@celery_app.task(
    name="process_approval_reminders",
    queue="maintenance",
    autoretry_for=(Exception,),
    retry_backoff=True,
    retry_jitter=True,
    max_retries=3,
)
def process_approval_reminders() -> dict[str, int]:
    logger.info("approval_reminders_starting")

    async def run() -> dict[str, int]:
        async with AsyncSessionLocal() as session:
            reminded, escalated = await ApprovalService(session).send_reminders_and_escalations()
            return {"reminded": reminded, "escalated": escalated}

    return run_async_task(run())


@celery_app.task(
    name="check_low_stock",
    queue="maintenance",
    autoretry_for=(Exception,),
    retry_backoff=True,
    retry_jitter=True,
    max_retries=3,
)
def check_low_stock() -> dict[str, int]:
    logger.info("low_stock_check_starting")

    async def run() -> dict[str, int]:
        async with AsyncSessionLocal() as session:
            rows = await InventoryService(session).low_stock()
            sent = 0
            for row in rows:
                recipients = await _low_stock_recipients(session, row)
                for user_id in recipients:
                    if await _recent_notification_exists(session, user_id, row.id):
                        continue
                    await NotificationService(session).create(
                        user_id=user_id,
                        title="Low stock alert",
                        body=(
                            f"{row.item.name} at {row.location.name} is at "
                            f"{row.on_hand_qty} on hand, below reorder level "
                            f"{row.item.reorder_level}."
                        ),
                        notification_type="inventory",
                        reference_type="inventory_location_stock",
                        reference_id=row.id,
                    )
                    sent += 1
            await session.commit()
            logger.info(
                "low_stock_check_completed",
                low_stock_items=len(rows),
                notifications_sent=sent,
            )
            return {"low_stock_items": len(rows), "notifications_sent": sent}

    return run_async_task(run())


async def _low_stock_recipients(session, row: InventoryLocationStock) -> set[UUID]:
    role_users = await session.scalars(
        select(User.id).where(
            User.role.in_(COMPANY_RESOURCE_ROLES),
            User.is_active.is_(True),
            User.deleted_at.is_(None),
        )
    )
    recipients = set(role_users.all())
    if row.location.project_id:
        project_viewers = await session.scalars(
            select(User.id)
            .join(ProjectMember, ProjectMember.user_id == User.id)
            .where(
                ProjectMember.project_id == row.location.project_id,
                ProjectMember.deleted_at.is_(None),
                User.role.in_(
                    roles_with_permission(PERMISSION_INVENTORY_VIEW) - COMPANY_RESOURCE_ROLES
                ),
                User.is_active.is_(True),
                User.deleted_at.is_(None),
            )
        )
        recipients.update(project_viewers.all())
    return recipients


async def _recent_notification_exists(session, user_id: UUID, stock_id: UUID) -> bool:
    cutoff = utc_now() - timedelta(hours=24)
    existing = await session.scalar(
        select(Notification.id).where(
            Notification.user_id == user_id,
            Notification.title == "Low stock alert",
            Notification.reference_type == "inventory_location_stock",
            Notification.reference_id == stock_id,
            Notification.created_at >= cutoff,
            Notification.deleted_at.is_(None),
        )
    )
    return existing is not None
