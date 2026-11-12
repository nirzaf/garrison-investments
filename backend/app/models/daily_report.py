from datetime import date, datetime
from decimal import Decimal
from typing import Any
from uuid import UUID

from sqlalchemy import Date, DateTime, ForeignKey, Integer, Numeric, String, Text, text
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.dialects.postgresql import UUID as PostgresUUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models.base import Base, SoftDeleteMixin, TimestampMixin


class DailyReport(TimestampMixin, SoftDeleteMixin, Base):
    __tablename__ = "daily_reports"

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
    engineer_id: Mapped[UUID] = mapped_column(
        PostgresUUID(as_uuid=True),
        ForeignKey("users.id", ondelete="CASCADE"),
        nullable=False,
    )
    revision: Mapped[int] = mapped_column(Integer, nullable=False, server_default=text("1"))
    report_number: Mapped[str | None] = mapped_column(String(60), nullable=True)
    report_date: Mapped[date] = mapped_column(Date, nullable=False)
    work_location: Mapped[str] = mapped_column(String(255), nullable=False)
    manpower_total: Mapped[int] = mapped_column(Integer, nullable=False, server_default=text("0"))
    overtime_hours: Mapped[Decimal] = mapped_column(
        Numeric(5, 2),
        nullable=False,
        server_default=text("0"),
    )
    work_completed: Mapped[str] = mapped_column(Text, nullable=False)
    progress_percentage: Mapped[Decimal] = mapped_column(Numeric(5, 2), nullable=False)
    safety_incidents: Mapped[int] = mapped_column(Integer, nullable=False, server_default=text("0"))
    safety_notes: Mapped[str | None] = mapped_column(Text, nullable=True)
    wir_status: Mapped[str] = mapped_column(String(50), nullable=False)
    inspection_status: Mapped[str] = mapped_column(String(50), nullable=False)
    delay_notes: Mapped[str | None] = mapped_column(Text, nullable=True)
    next_day_plan: Mapped[str] = mapped_column(Text, nullable=False)
    supervisor_update_ids: Mapped[list[str]] = mapped_column(JSONB, nullable=False)
    photo_refs: Mapped[list[dict[str, Any]]] = mapped_column(JSONB, nullable=False)
    attachment_refs: Mapped[list[dict[str, Any]]] = mapped_column(JSONB, nullable=False)
    status: Mapped[str] = mapped_column(String(20), nullable=False, server_default=text("'draft'"))
    submitted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    approved_by: Mapped[UUID | None] = mapped_column(
        PostgresUUID(as_uuid=True),
        ForeignKey("users.id", ondelete="SET NULL"),
        nullable=True,
    )
    approved_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    rejection_comments: Mapped[str | None] = mapped_column(Text, nullable=True)
    extra_fields: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False)

    manpower_entries: Mapped[list["ReportManpower"]] = relationship(
        back_populates="report",
        cascade="all, delete-orphan",
        lazy="selectin",
    )
    equipment_entries: Mapped[list["ReportEquipment"]] = relationship(
        back_populates="report",
        cascade="all, delete-orphan",
        lazy="selectin",
    )
    material_consumption: Mapped[list["ReportMaterialConsumption"]] = relationship(
        back_populates="report",
        cascade="all, delete-orphan",
        lazy="selectin",
    )
    approval_history: Mapped[list["DailyReportApprovalHistory"]] = relationship(
        back_populates="report",
        cascade="all, delete-orphan",
        lazy="selectin",
        order_by="DailyReportApprovalHistory.decided_at",
    )


class ReportManpower(TimestampMixin, SoftDeleteMixin, Base):
    __tablename__ = "report_manpower"

    id: Mapped[UUID] = mapped_column(
        PostgresUUID(as_uuid=True),
        primary_key=True,
        server_default=text("uuid_generate_v4()"),
    )
    report_id: Mapped[UUID] = mapped_column(
        PostgresUUID(as_uuid=True),
        ForeignKey("daily_reports.id", ondelete="CASCADE"),
        nullable=False,
    )
    trade: Mapped[str] = mapped_column(String(100), nullable=False)
    count: Mapped[int] = mapped_column(Integer, nullable=False)
    overtime_hours: Mapped[Decimal] = mapped_column(
        Numeric(5, 2),
        nullable=False,
        server_default=text("0"),
    )

    report: Mapped[DailyReport] = relationship(back_populates="manpower_entries")


class ReportEquipment(TimestampMixin, SoftDeleteMixin, Base):
    __tablename__ = "report_equipment"

    id: Mapped[UUID] = mapped_column(
        PostgresUUID(as_uuid=True),
        primary_key=True,
        server_default=text("uuid_generate_v4()"),
    )
    report_id: Mapped[UUID] = mapped_column(
        PostgresUUID(as_uuid=True),
        ForeignKey("daily_reports.id", ondelete="CASCADE"),
        nullable=False,
    )
    equipment_name: Mapped[str] = mapped_column(String(120), nullable=False)
    quantity: Mapped[int] = mapped_column(Integer, nullable=False)
    hours_used: Mapped[Decimal] = mapped_column(
        Numeric(6, 2),
        nullable=False,
        server_default=text("0"),
    )
    remarks: Mapped[str | None] = mapped_column(Text, nullable=True)

    report: Mapped[DailyReport] = relationship(back_populates="equipment_entries")


class ReportMaterialConsumption(TimestampMixin, SoftDeleteMixin, Base):
    __tablename__ = "report_material_consumption"

    id: Mapped[UUID] = mapped_column(
        PostgresUUID(as_uuid=True),
        primary_key=True,
        server_default=text("uuid_generate_v4()"),
    )
    report_id: Mapped[UUID] = mapped_column(
        PostgresUUID(as_uuid=True),
        ForeignKey("daily_reports.id", ondelete="CASCADE"),
        nullable=False,
    )
    boq_item_id: Mapped[UUID | None] = mapped_column(
        PostgresUUID(as_uuid=True),
        ForeignKey("boq_items.id", ondelete="SET NULL"),
        nullable=True,
    )
    material_name: Mapped[str] = mapped_column(String(160), nullable=False)
    unit: Mapped[str] = mapped_column(String(30), nullable=False)
    quantity: Mapped[Decimal] = mapped_column(Numeric(14, 3), nullable=False)
    remarks: Mapped[str | None] = mapped_column(Text, nullable=True)

    report: Mapped[DailyReport] = relationship(back_populates="material_consumption")


class DailyReportApprovalHistory(TimestampMixin, SoftDeleteMixin, Base):
    __tablename__ = "daily_report_approval_history"

    id: Mapped[UUID] = mapped_column(
        PostgresUUID(as_uuid=True),
        primary_key=True,
        server_default=text("uuid_generate_v4()"),
    )
    report_id: Mapped[UUID] = mapped_column(
        PostgresUUID(as_uuid=True),
        ForeignKey("daily_reports.id", ondelete="CASCADE"),
        nullable=False,
    )
    actor_id: Mapped[UUID | None] = mapped_column(
        PostgresUUID(as_uuid=True),
        ForeignKey("users.id", ondelete="SET NULL"),
        nullable=True,
    )
    decision: Mapped[str] = mapped_column(String(20), nullable=False)
    previous_status: Mapped[str] = mapped_column(String(20), nullable=False)
    comments: Mapped[str | None] = mapped_column(Text, nullable=True)
    decided_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)

    report: Mapped[DailyReport] = relationship(back_populates="approval_history")
