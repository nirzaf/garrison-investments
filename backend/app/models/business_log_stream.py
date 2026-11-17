from datetime import datetime
from uuid import UUID

from sqlalchemy import DateTime, Index, String
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base, UUIDPrimaryKeyMixin


class BusinessLogStream(UUIDPrimaryKeyMixin, Base):
    __tablename__ = "business_log_streams"
    __table_args__ = (
        Index("ix_business_log_streams_user_expiry", "user_id", "expires_at"),
    )

    # Preserve the audit identity after a lawful account deletion.
    user_id: Mapped[UUID] = mapped_column()
    request_id: Mapped[str] = mapped_column(String(64))
    opened_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    closed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
