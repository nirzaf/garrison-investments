from datetime import datetime
from uuid import UUID

from sqlalchemy import CheckConstraint, DateTime, ForeignKey, Index, String
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base, UUIDPrimaryKeyMixin


class SupportCaseAuditRead(UUIDPrimaryKeyMixin, Base):
    __tablename__ = "support_case_audit_reads"
    __table_args__ = (
        Index("ix_support_case_audit_reads_operator_occurred", "operator_id", "occurred_at"),
        CheckConstraint("event_count BETWEEN 0 AND 100", name="event_count"),
    )

    case_id: Mapped[UUID] = mapped_column(ForeignKey("support_cases.id", ondelete="RESTRICT"))
    operator_id: Mapped[UUID] = mapped_column(
        ForeignKey("support_operators.id", ondelete="RESTRICT")
    )
    request_id: Mapped[str] = mapped_column(String(64))
    occurred_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    started_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    ended_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    event_count: Mapped[int]
