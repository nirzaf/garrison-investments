from datetime import datetime
from uuid import UUID

from sqlalchemy import (
    BigInteger,
    CheckConstraint,
    DateTime,
    ForeignKey,
    LargeBinary,
    String,
    UniqueConstraint,
    Uuid,
)
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base, UUIDPrimaryKeyMixin


class SupportBusinessAction(UUIDPrimaryKeyMixin, Base):
    __tablename__ = "support_business_actions"
    __table_args__ = (
        CheckConstraint(
            "(kind IN ('revoke_sessions','unlock','disable','reactivate')"
            " AND permission_key IS NULL AND permission_session_id IS NULL"
            " AND recovery_destination_digest IS NULL AND source_event_id IS NULL"
            " AND project_id IS NULL AND project_scope_digest IS NULL)"
            " OR (kind = 'permission_view' AND permission_key IS NOT NULL"
            " AND permission_session_id IS NOT NULL AND recovery_destination_digest IS NULL"
            " AND source_event_id IS NULL AND project_id IS NULL AND project_scope_digest IS NULL)"
            " OR (kind = 'recover' AND permission_key IS NULL AND permission_session_id IS NULL"
            " AND recovery_destination_digest IS NOT NULL AND source_event_id IS NULL"
            " AND project_id IS NULL AND project_scope_digest IS NULL)"
            " OR (kind = 'request_summary' AND permission_key IS NULL"
            " AND permission_session_id IS NOT NULL AND recovery_destination_digest IS NULL"
            " AND source_event_id IS NOT NULL AND project_id IS NULL"
            " AND project_scope_digest IS NULL)"
            " OR (kind = 'navigation_view' AND permission_key IS NULL"
            " AND permission_session_id IS NOT NULL AND recovery_destination_digest IS NULL"
            " AND source_event_id IS NULL AND project_id IS NULL AND project_scope_digest IS NULL)"
            " OR (kind IN ('project_list','portal_preview') AND permission_key IS NULL"
            " AND permission_session_id IS NOT NULL AND recovery_destination_digest IS NULL"
            " AND source_event_id IS NULL AND project_id IS NULL"
            " AND project_scope_digest IS NOT NULL)"
            " OR (kind = 'project_detail' AND permission_key IS NULL"
            " AND permission_session_id IS NOT NULL AND recovery_destination_digest IS NULL"
            " AND source_event_id IS NULL AND project_id IS NOT NULL"
            " AND project_scope_digest IS NULL)",
            name="kind",
        ),
        UniqueConstraint("case_id", "requester_id", "command_key"),
    )

    case_id: Mapped[UUID] = mapped_column(ForeignKey("support_cases.id", ondelete="RESTRICT"))
    requester_id: Mapped[UUID] = mapped_column(
        ForeignKey("support_operators.id", ondelete="RESTRICT")
    )
    requester_epoch: Mapped[int] = mapped_column(BigInteger)
    user_id: Mapped[UUID] = mapped_column(Uuid())
    user_revision: Mapped[int]
    case_revision: Mapped[int]
    command_key: Mapped[UUID] = mapped_column(Uuid())
    kind: Mapped[str] = mapped_column(String(16))
    owner_session_id: Mapped[UUID | None] = mapped_column(ForeignKey("support_sessions.id"))

    @property
    def authorization_mode(self) -> str:
        return "paired" if self.owner_session_id is None else "single_owner"

    permission_session_id: Mapped[UUID | None] = mapped_column(ForeignKey("support_sessions.id"))
    permission_key: Mapped[str | None] = mapped_column(String(64))
    source_event_id: Mapped[UUID | None] = mapped_column(Uuid())
    project_id: Mapped[UUID | None] = mapped_column(Uuid())
    project_scope_digest: Mapped[str | None] = mapped_column(String(64))
    recovery_destination_digest: Mapped[str | None] = mapped_column(String(64))
    reason_code: Mapped[str] = mapped_column(String(32))
    reason: Mapped[str] = mapped_column(String(300))
    digest: Mapped[str] = mapped_column(String(64))
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    applied_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class SupportBusinessApproval(Base):
    __tablename__ = "support_business_approvals"

    action_id: Mapped[UUID] = mapped_column(
        ForeignKey("support_business_actions.id", ondelete="RESTRICT"), primary_key=True
    )
    reviewer_id: Mapped[UUID] = mapped_column(
        ForeignKey("support_operators.id", ondelete="RESTRICT"), primary_key=True
    )
    reviewer_epoch: Mapped[int] = mapped_column(BigInteger)
    occurred_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    request_id: Mapped[str] = mapped_column(String(64))


class SupportBusinessProof(UUIDPrimaryKeyMixin, Base):
    __tablename__ = "support_business_proofs"
    __table_args__ = (CheckConstraint("stage IN ('review', 'execute')", name="stage"),)

    action_id: Mapped[UUID] = mapped_column(
        ForeignKey("support_business_actions.id", ondelete="RESTRICT")
    )
    session_id: Mapped[UUID] = mapped_column(ForeignKey("support_sessions.id", ondelete="RESTRICT"))
    stage: Mapped[str] = mapped_column(String(8))
    contact_ref: Mapped[UUID | None] = mapped_column(Uuid())
    challenge: Mapped[bytes] = mapped_column(LargeBinary(32))
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    consumed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class SupportBusinessContact(Base):
    """Custodian attestation of an independently verified offline contact."""

    __tablename__ = "support_business_contacts"

    action_id: Mapped[UUID] = mapped_column(
        ForeignKey("support_business_actions.id", ondelete="RESTRICT"), primary_key=True
    )
    verifier_id: Mapped[UUID] = mapped_column(
        ForeignKey("support_operators.id", ondelete="RESTRICT")
    )
    verifier_epoch: Mapped[int] = mapped_column(BigInteger)
    contact_ref: Mapped[UUID] = mapped_column(Uuid(), unique=True)
    action_digest: Mapped[str] = mapped_column(String(64))
    verified_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))


class SupportRecoveryDelivery(Base):
    __tablename__ = "support_recovery_deliveries"
    __table_args__ = (
        CheckConstraint(
            "status IN ('pending','dispatching','accepted','unknown','cancelled')", name="status"
        ),
    )

    action_id: Mapped[UUID] = mapped_column(
        ForeignKey("support_business_actions.id", ondelete="RESTRICT"), primary_key=True
    )
    challenge_id: Mapped[UUID] = mapped_column(
        ForeignKey("auth_otp_challenges.id", ondelete="RESTRICT"), unique=True
    )
    status: Mapped[str] = mapped_column(String(16))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    dispatch_started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    dispatch_finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class SupportBusinessEvent(UUIDPrimaryKeyMixin, Base):
    __tablename__ = "support_business_events"
    __table_args__ = (
        CheckConstraint(
            "event IN ('proposed', 'proof_denied', 'applied', 'status_read')", name="event"
        ),
    )

    action_id: Mapped[UUID] = mapped_column(
        ForeignKey("support_business_actions.id", ondelete="RESTRICT")
    )
    actor_id: Mapped[UUID] = mapped_column(ForeignKey("support_operators.id", ondelete="RESTRICT"))
    event: Mapped[str] = mapped_column(String(16))
    request_id: Mapped[str] = mapped_column(String(64))
    occurred_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
