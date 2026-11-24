from datetime import date, datetime
from decimal import Decimal
from uuid import UUID

from sqlalchemy import Date, DateTime, ForeignKey, Integer, Numeric, String, Text, text
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.dialects.postgresql import UUID as PostgresUUID
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base, SoftDeleteMixin, TimestampMixin


class SupervisorUpdate(TimestampMixin, SoftDeleteMixin, Base):
    __tablename__ = "supervisor_updates"

    id: Mapped[UUID] = mapped_column(
        PostgresUUID(as_uuid=True),
        primary_key=True,
        server_default=text("uuid_generate_v4()"),
    )
    project_id: Mapped[UUID] = mapped_column(
        PostgresUUID(as_uuid=True),
        ForeignKey("projects.id", ondelete="CASCADE"),
        nullable=False,
    )
    supervisor_id: Mapped[UUID] = mapped_column(
        PostgresUUID(as_uuid=True),
        ForeignKey("users.id", ondelete="CASCADE"),
        nullable=False,
    )
    update_date: Mapped[date] = mapped_column(Date, nullable=False)
    day_type: Mapped[str] = mapped_column(
        String(20),
        nullable=False,
        server_default=text("'weekday'"),
    )
    work_location: Mapped[str] = mapped_column(String(255), nullable=False)
    attendance_count: Mapped[int] = mapped_column(Integer, nullable=False)
    overtime_hours: Mapped[Decimal] = mapped_column(
        Numeric(5, 2),
        nullable=False,
        server_default=text("0"),
    )
    progress_notes: Mapped[str] = mapped_column(Text, nullable=False)
    delay_notes: Mapped[str | None] = mapped_column(Text, nullable=True)
    required_notes: Mapped[str] = mapped_column(Text, nullable=False)
    attachment_refs: Mapped[list[dict]] = mapped_column(JSONB, nullable=False)
    status: Mapped[str] = mapped_column(String(20), nullable=False, server_default=text("'draft'"))
    submitted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    verified_by: Mapped[UUID | None] = mapped_column(
        PostgresUUID(as_uuid=True),
        ForeignKey("users.id", ondelete="SET NULL"),
        nullable=True,
    )
    verified_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    verified_report_id: Mapped[UUID | None] = mapped_column(
        PostgresUUID(as_uuid=True),
        ForeignKey(
            "daily_reports.id", name="fk_supervisor_updates_verified_report_id", ondelete="RESTRICT"
        ),
        nullable=True,
        index=True,
    )
    verification_notes: Mapped[str | None] = mapped_column(Text, nullable=True)
    revision: Mapped[int] = mapped_column(Integer, nullable=False, server_default=text("1"))
    submission_revision: Mapped[int | None] = mapped_column(Integer)
    previous_id: Mapped[UUID | None] = mapped_column(
        ForeignKey("supervisor_updates.id", ondelete="RESTRICT")
    )
    activity_scope: Mapped[str | None] = mapped_column(Text)
    remaining_work: Mapped[str | None] = mapped_column(Text)
    completed_area: Mapped[str | None] = mapped_column(String(255))
    completed_quantity: Mapped[Decimal | None] = mapped_column(Numeric(14, 3))
    quantity_unit: Mapped[str | None] = mapped_column(String(30))
    progress_percentage: Mapped[Decimal | None] = mapped_column(Numeric(5, 2))


class SupervisorUpdateSubmission(TimestampMixin, Base):
    __tablename__ = "supervisor_update_submissions"

    update_id: Mapped[UUID] = mapped_column(
        ForeignKey("supervisor_updates.id", ondelete="RESTRICT"), primary_key=True
    )
    submission_revision: Mapped[int] = mapped_column(Integer, primary_key=True)
    requirements: Mapped[dict] = mapped_column(JSONB, nullable=False)
    evidence_ids: Mapped[list[str]] = mapped_column(JSONB, nullable=False)
    engineer_id: Mapped[UUID] = mapped_column(ForeignKey("users.id", ondelete="RESTRICT"))
    qs_id: Mapped[UUID | None] = mapped_column(ForeignKey("users.id", ondelete="RESTRICT"))
    qs_decision: Mapped[str | None] = mapped_column(String(20))
    qs_comments: Mapped[str | None] = mapped_column(Text)
    qs_decided_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    engineer_decision: Mapped[str | None] = mapped_column(String(20))
    engineer_comments: Mapped[str | None] = mapped_column(Text)
    engineer_decided_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
