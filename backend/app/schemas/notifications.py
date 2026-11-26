from datetime import datetime
from uuid import UUID

from pydantic import BaseModel, ConfigDict


class NotificationResponse(BaseModel):
    id: UUID
    user_id: UUID
    title: str
    body: str
    notification_type: str
    reference_type: str | None
    reference_id: UUID | None
    is_read: bool
    muted: bool
    email_status: str | None
    read_at: datetime | None
    created_at: datetime
    superseded_at: datetime | None = None

    model_config = ConfigDict(from_attributes=True)


class NotificationListResponse(BaseModel):
    items: list[NotificationResponse]
    total: int


class UnreadCountResponse(BaseModel):
    unread_count: int
