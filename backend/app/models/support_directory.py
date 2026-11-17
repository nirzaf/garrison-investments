from datetime import datetime
from uuid import UUID

from sqlalchemy import DateTime, ForeignKey, Index, String, Uuid
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base, UUIDPrimaryKeyMixin


class SupportCaseSubject(Base):
    __tablename__ = "support_case_subjects"

    case_id: Mapped[UUID] = mapped_column(
        ForeignKey("support_cases.id", ondelete="RESTRICT"), primary_key=True
    )
    # A support case must not prevent a lawful business account removal.
    user_id: Mapped[UUID] = mapped_column(Uuid())


class SupportDirectoryRead(UUIDPrimaryKeyMixin, Base):
    __tablename__ = "support_directory_reads"
    __table_args__ = (
        Index("ix_support_directory_reads_operator_occurred", "operator_id", "occurred_at"),
    )

    case_id: Mapped[UUID] = mapped_column(ForeignKey("support_cases.id", ondelete="RESTRICT"))
    operator_id: Mapped[UUID] = mapped_column(
        ForeignKey("support_operators.id", ondelete="RESTRICT")
    )
    subject_user_id: Mapped[UUID] = mapped_column(Uuid())
    request_id: Mapped[str] = mapped_column(String(64))
    occurred_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
