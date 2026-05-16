from uuid import UUID

from fastapi import APIRouter

from app.api.dependencies import CurrentUser, DbSession
from app.schemas.notifications import (
    NotificationListResponse,
    NotificationResponse,
    UnreadCountResponse,
)
from app.services.notification_service import NotificationService

router = APIRouter(prefix="/notifications", tags=["Notifications"])


@router.get("", response_model=NotificationListResponse)
async def list_notifications(
    current_user: CurrentUser,
    session: DbSession,
) -> NotificationListResponse:
    notifications, total = await NotificationService(session).list_for_user(current_user)
    return NotificationListResponse(
        items=[NotificationResponse.model_validate(item) for item in notifications],
        total=total,
    )


@router.get("/unread-count", response_model=UnreadCountResponse)
async def unread_count(current_user: CurrentUser, session: DbSession) -> UnreadCountResponse:
    return UnreadCountResponse(
        unread_count=await NotificationService(session).unread_count(current_user)
    )


@router.patch("/{notification_id}/read", response_model=NotificationResponse)
async def mark_read(
    notification_id: UUID,
    current_user: CurrentUser,
    session: DbSession,
) -> NotificationResponse:
    notification = await NotificationService(session).mark_read(notification_id, current_user)
    return NotificationResponse.model_validate(notification)


@router.post("/mark-all-read")
async def mark_all_read(current_user: CurrentUser, session: DbSession) -> dict[str, int]:
    return {"updated": await NotificationService(session).mark_all_read(current_user)}
