from uuid import UUID

from sqlalchemy import CheckConstraint, ForeignKey, Index, Integer, String, Text, UniqueConstraint
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base, TimestampMixin, UUIDPrimaryKeyMixin


class UserFeedback(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "user_feedback"
    __table_args__ = (
        CheckConstraint("category IN ('bug', 'suggestion', 'other')", name="category"),
        CheckConstraint("status IN ('new', 'investigating', 'resolved')", name="status"),
        CheckConstraint("revision >= 1", name="revision"),
        UniqueConstraint("reporter_id", "submission_id"),
        Index("ix_user_feedback_reporter_created", "reporter_id", "created_at"),
        Index("ix_user_feedback_created", "created_at", "id"),
    )

    reporter_id: Mapped[UUID | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"))
    submission_id: Mapped[UUID]
    submission_fingerprint: Mapped[str] = mapped_column(String(64))
    category: Mapped[str] = mapped_column(String(16))
    title: Mapped[str] = mapped_column(String(140))
    description: Mapped[str] = mapped_column(Text)
    status: Mapped[str] = mapped_column(String(16), server_default="new")
    revision: Mapped[int] = mapped_column(Integer, server_default="1")
    diagnostics: Mapped[list[dict[str, str | int]]] = mapped_column(JSONB)
