from datetime import datetime
from uuid import UUID

from sqlalchemy import CheckConstraint, DateTime, ForeignKey, Index, String
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base, UUIDPrimaryKeyMixin


class SupportHealthEvent(UUIDPrimaryKeyMixin, Base):
    __tablename__ = "support_health_events"
    __table_args__ = (
        Index("ix_support_health_events_operator_occurred", "operator_id", "occurred_at"),
        CheckConstraint("action IN ('requested', 'returned')", name="action"),
    )

    operator_id: Mapped[UUID] = mapped_column(
        ForeignKey("support_operators.id", ondelete="RESTRICT")
    )
    action: Mapped[str] = mapped_column(String(12))
    request_id: Mapped[str] = mapped_column(String(64))
    occurred_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
