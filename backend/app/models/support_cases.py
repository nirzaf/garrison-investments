from datetime import datetime
from uuid import UUID

from sqlalchemy import CheckConstraint, DateTime, ForeignKey, Index, Integer, String
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base, TimestampMixin, UUIDPrimaryKeyMixin
from app.models.support_oversight import ALL_SUPPORT_CAPABILITIES, sql_quoted_list


class SupportOperatorGrant(Base):
    __tablename__ = "support_operator_grants"
    __table_args__ = (
        CheckConstraint(
            f"capability IN ({sql_quoted_list(ALL_SUPPORT_CAPABILITIES)})",
            name="capability",
        ),
    )

    operator_id: Mapped[UUID] = mapped_column(
        ForeignKey("support_operators.id", ondelete="RESTRICT"), primary_key=True
    )
    capability: Mapped[str] = mapped_column(String(32), primary_key=True)


class SupportCase(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "support_cases"
    __table_args__ = (
        CheckConstraint(
            "status IN ('open', 'investigating', 'mitigated', 'verified', 'closed')", name="status"
        ),
        CheckConstraint("revision >= 1", name="revision"),
        CheckConstraint(
            "(owner_id IS NULL AND external_ref IS NULL AND severity IS NULL"
            " AND reason_code IS NULL)"
            " OR (owner_id IS NOT NULL AND external_ref IS NOT NULL AND severity IS NOT NULL"
            " AND reason_code IS NOT NULL)",
            name="metadata",
        ),
        CheckConstraint("severity IN ('low', 'medium', 'high', 'critical')", name="severity"),
        CheckConstraint(
            "reason_code IN ('availability', 'access', 'functional', 'data_integrity')",
            name="reason_code",
        ),
    )

    external_ref: Mapped[str | None] = mapped_column(String(120), unique=True)
    owner_id: Mapped[UUID | None] = mapped_column(
        ForeignKey("support_operators.id", ondelete="RESTRICT")
    )
    severity: Mapped[str | None] = mapped_column(String(8))
    reason_code: Mapped[str | None] = mapped_column(String(24))
    revision: Mapped[int] = mapped_column(default=1, server_default="1")
    status: Mapped[str] = mapped_column(String(16))


class SupportCaseMember(Base):
    __tablename__ = "support_case_members"
    __table_args__ = (Index("ix_support_case_members_operator_case", "operator_id", "case_id"),)

    case_id: Mapped[UUID] = mapped_column(
        ForeignKey("support_cases.id", ondelete="RESTRICT"), primary_key=True
    )
    operator_id: Mapped[UUID] = mapped_column(
        ForeignKey("support_operators.id", ondelete="RESTRICT"), primary_key=True
    )


class SupportCaseRequest(Base):
    __tablename__ = "support_case_requests"

    case_id: Mapped[UUID] = mapped_column(
        ForeignKey("support_cases.id", ondelete="RESTRICT"), primary_key=True
    )
    request_id: Mapped[str] = mapped_column(String(36), primary_key=True)


class SupportLogRead(UUIDPrimaryKeyMixin, Base):
    __tablename__ = "support_log_reads"
    __table_args__ = (
        Index("ix_support_log_reads_operator_occurred", "operator_id", "occurred_at"),
        CheckConstraint("event_count BETWEEN 0 AND 100", name="event_count"),
        CheckConstraint("requested_limit BETWEEN 1 AND 100", name="requested_limit"),
        CheckConstraint(
            "filter_status_code IS NULL OR filter_status_code BETWEEN 100 AND 599",
            name="filter_status_code",
        ),
    )

    operator_id: Mapped[UUID] = mapped_column(
        ForeignKey("support_operators.id", ondelete="RESTRICT")
    )
    case_id: Mapped[UUID] = mapped_column(ForeignKey("support_cases.id", ondelete="RESTRICT"))
    request_id: Mapped[str] = mapped_column(String(64))
    source_request_id: Mapped[str] = mapped_column(String(36))
    started_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    ended_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    filter_status_code: Mapped[int | None] = mapped_column(Integer)
    requested_limit: Mapped[int] = mapped_column(Integer)
    event_count: Mapped[int] = mapped_column(Integer)
    occurred_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))


class SupportLogStream(UUIDPrimaryKeyMixin, Base):
    __tablename__ = "support_log_streams"
    __table_args__ = (Index("ix_support_log_streams_operator_expiry", "operator_id", "expires_at"),)

    operator_id: Mapped[UUID] = mapped_column(
        ForeignKey("support_operators.id", ondelete="RESTRICT")
    )
    session_id: Mapped[UUID] = mapped_column(
        ForeignKey("support_sessions.id", ondelete="RESTRICT")
    )
    case_id: Mapped[UUID] = mapped_column(ForeignKey("support_cases.id", ondelete="RESTRICT"))
    request_id: Mapped[str] = mapped_column(String(64))
    source_request_id: Mapped[str] = mapped_column(String(36))
    started_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    opened_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    closed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class SupportCaseEvent(UUIDPrimaryKeyMixin, Base):
    __tablename__ = "support_case_events"
    __table_args__ = (
        Index("ix_support_case_events_case_occurred", "case_id", "occurred_at"),
        CheckConstraint(
            "action IN ('created', 'read', 'transitioned', 'timeline_read')", name="action"
        ),
    )

    operator_id: Mapped[UUID] = mapped_column(
        ForeignKey("support_operators.id", ondelete="RESTRICT")
    )
    case_id: Mapped[UUID] = mapped_column(ForeignKey("support_cases.id", ondelete="RESTRICT"))
    action: Mapped[str] = mapped_column(String(16))
    revision: Mapped[int]
    status: Mapped[str] = mapped_column(String(16))
    reason_code: Mapped[str | None] = mapped_column(String(24))
    request_id: Mapped[str] = mapped_column(String(64))
    occurred_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
