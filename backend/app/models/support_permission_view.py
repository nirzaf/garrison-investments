from datetime import datetime
from uuid import UUID

from sqlalchemy import CheckConstraint, DateTime, ForeignKey, Index, String
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base, UUIDPrimaryKeyMixin


class SupportPermissionView(UUIDPrimaryKeyMixin, Base):
    __tablename__ = "support_permission_views"
    __table_args__ = (
        Index("ix_support_permission_views_session_expiry", "session_id", "expires_at"),
    )

    id: Mapped[UUID] = mapped_column(
        ForeignKey("support_business_actions.id", ondelete="RESTRICT"), primary_key=True
    )
    session_id: Mapped[UUID] = mapped_column(ForeignKey("support_sessions.id", ondelete="RESTRICT"))
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    last_seen_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    ended_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class SupportPermissionViewEvent(UUIDPrimaryKeyMixin, Base):
    __tablename__ = "support_permission_view_events"
    __table_args__ = (CheckConstraint("event IN ('opened', 'read', 'ended')", name="event"),)

    view_id: Mapped[UUID] = mapped_column(
        ForeignKey("support_permission_views.id", ondelete="RESTRICT")
    )
    actor_id: Mapped[UUID] = mapped_column(ForeignKey("support_operators.id", ondelete="RESTRICT"))
    event: Mapped[str] = mapped_column(String(12))
    occurred_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    request_id: Mapped[str] = mapped_column(String(64))
