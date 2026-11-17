from datetime import datetime
from uuid import UUID

from sqlalchemy import Boolean, CheckConstraint, DateTime, ForeignKey, LargeBinary, String
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base, UUIDPrimaryKeyMixin


class SupportCustodyAction(UUIDPrimaryKeyMixin, Base):
    __tablename__ = "support_custody_actions"
    __table_args__ = (
        CheckConstraint(
            "(kind IN ('suspend', 'enroll', 'recover') AND capability IS NULL"
            " AND enable IS NULL) OR "
            "(kind = 'grant_change' AND capability IS NOT NULL AND "
            "capability IN ('cases.manage', 'logs.runtime', 'health.read', 'directory.read', "
            "'account.request', 'logs.audit', 'simulation.start', 'logs.stream', 'logs.export')"
            " AND enable IS NOT NULL)",
            name="bounded_action",
        ),
        CheckConstraint("target_id <> requester_id", name="distinct_target"),
        CheckConstraint(
            "reviewer_id IS NULL OR reviewer_id NOT IN (target_id, requester_id)",
            name="independent_reviewer",
        ),
    )

    kind: Mapped[str] = mapped_column(String(16), default="suspend", server_default="suspend")
    capability: Mapped[str | None] = mapped_column(String(32))
    enable: Mapped[bool | None] = mapped_column(Boolean)
    target_id: Mapped[UUID] = mapped_column(ForeignKey("support_operators.id", ondelete="RESTRICT"))
    requester_id: Mapped[UUID] = mapped_column(
        ForeignKey("support_operators.id", ondelete="RESTRICT")
    )
    reviewer_id: Mapped[UUID | None] = mapped_column(
        ForeignKey("support_operators.id", ondelete="RESTRICT")
    )
    target_epoch: Mapped[int]
    requester_epoch: Mapped[int]
    reviewer_epoch: Mapped[int | None]
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    executed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class SupportCustodyProof(UUIDPrimaryKeyMixin, Base):
    __tablename__ = "support_custody_proofs"
    __table_args__ = (CheckConstraint("stage IN ('review', 'execute')", name="stage"),)

    custody_action_id: Mapped[UUID] = mapped_column(
        ForeignKey("support_custody_actions.id", ondelete="RESTRICT")
    )
    session_id: Mapped[UUID] = mapped_column(ForeignKey("support_sessions.id", ondelete="RESTRICT"))
    stage: Mapped[str] = mapped_column(String(8))
    challenge: Mapped[bytes] = mapped_column(LargeBinary(32))
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    consumed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class SupportCustodyEvent(UUIDPrimaryKeyMixin, Base):
    __tablename__ = "support_custody_events"
    __table_args__ = (
        CheckConstraint(
            "action IN ('proposed', 'reviewed', 'executed', 'proof_denied', 'floor_denied', "
            "'passkey_added', 'operator_activated', 'registration_denied')",
            name="action",
        ),
    )

    custody_action_id: Mapped[UUID] = mapped_column(
        ForeignKey("support_custody_actions.id", ondelete="RESTRICT")
    )
    actor_id: Mapped[UUID] = mapped_column(ForeignKey("support_operators.id", ondelete="RESTRICT"))
    action: Mapped[str] = mapped_column(String(24))
    request_id: Mapped[str] = mapped_column(String(64))
    occurred_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
