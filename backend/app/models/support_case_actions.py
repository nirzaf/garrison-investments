from datetime import datetime
from uuid import UUID

from sqlalchemy import (
    BigInteger,
    CheckConstraint,
    DateTime,
    ForeignKey,
    Index,
    LargeBinary,
    String,
    Uuid,
)
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base, UUIDPrimaryKeyMixin


class SupportCaseAction(UUIDPrimaryKeyMixin, Base):
    __tablename__ = "support_case_actions"
    __table_args__ = (
        Index("ix_support_case_actions_case_expiry", "case_id", "expires_at"),
        CheckConstraint(
            "(kind IN ('member_add', 'member_remove') AND member_id IS NOT NULL"
            " AND source_event_id IS NULL AND subject_user_id IS NULL AND project_id IS NULL)"
            " OR (kind IN ('evidence_link', 'verify') AND member_id IS NULL"
            " AND source_event_id IS NOT NULL AND subject_user_id IS NULL AND project_id IS NULL)"
            " OR (kind IN ('close', 'subject_remove') AND member_id IS NULL"
            " AND source_event_id IS NULL AND subject_user_id IS NULL AND project_id IS NULL)"
            " OR (kind = 'subject_set' AND member_id IS NULL AND source_event_id IS NULL"
            " AND subject_user_id IS NOT NULL AND project_id IS NULL)"
            " OR (kind IN ('project_add', 'project_remove') AND member_id IS NULL"
            " AND source_event_id IS NULL AND subject_user_id IS NULL AND project_id IS NOT NULL)",
            name="payload",
        ),
        CheckConstraint("(applied_at IS NULL) = (reviewer_id IS NULL)", name="decision"),
        CheckConstraint("reviewer_id IS NULL OR reviewer_id <> requester_id", name="independent"),
    )

    case_id: Mapped[UUID] = mapped_column(ForeignKey("support_cases.id", ondelete="RESTRICT"))
    requester_id: Mapped[UUID] = mapped_column(
        ForeignKey("support_operators.id", ondelete="RESTRICT")
    )
    reviewer_id: Mapped[UUID | None] = mapped_column(
        ForeignKey("support_operators.id", ondelete="RESTRICT")
    )
    member_id: Mapped[UUID | None] = mapped_column(
        ForeignKey("support_operators.id", ondelete="RESTRICT")
    )
    # Retain the opaque identifier independently of the operational log's retention.
    subject_user_id: Mapped[UUID | None] = mapped_column(Uuid())
    project_id: Mapped[UUID | None] = mapped_column(Uuid())
    source_event_id: Mapped[UUID | None] = mapped_column(Uuid())
    source_request_id: Mapped[str | None] = mapped_column(String(36))
    source_status: Mapped[int | None]
    kind: Mapped[str] = mapped_column(String(16))
    case_revision: Mapped[int]
    requester_epoch: Mapped[int] = mapped_column(BigInteger)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    applied_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class SupportCaseProject(Base):
    __tablename__ = "support_case_projects"

    case_id: Mapped[UUID] = mapped_column(
        ForeignKey("support_cases.id", ondelete="RESTRICT"), primary_key=True
    )
    # Keep a case-scope record independent of the business project's retention.
    project_id: Mapped[UUID] = mapped_column(Uuid(), primary_key=True)


class SupportCaseActionProof(UUIDPrimaryKeyMixin, Base):
    __tablename__ = "support_case_action_proofs"

    action_id: Mapped[UUID] = mapped_column(
        ForeignKey("support_case_actions.id", ondelete="RESTRICT")
    )
    session_id: Mapped[UUID] = mapped_column(ForeignKey("support_sessions.id", ondelete="RESTRICT"))
    challenge: Mapped[bytes] = mapped_column(LargeBinary(32))
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    consumed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class SupportCaseActionEvent(UUIDPrimaryKeyMixin, Base):
    __tablename__ = "support_case_action_events"
    __table_args__ = (
        CheckConstraint("event IN ('requested', 'proof_denied', 'applied')", name="event"),
    )

    action_id: Mapped[UUID] = mapped_column(
        ForeignKey("support_case_actions.id", ondelete="RESTRICT")
    )
    actor_id: Mapped[UUID] = mapped_column(ForeignKey("support_operators.id", ondelete="RESTRICT"))
    event: Mapped[str] = mapped_column(String(16))
    request_id: Mapped[str] = mapped_column(String(64))
    occurred_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
