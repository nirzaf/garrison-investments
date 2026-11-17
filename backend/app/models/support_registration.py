from datetime import datetime
from uuid import UUID

from sqlalchemy import BigInteger, CheckConstraint, DateTime, ForeignKey, LargeBinary, String
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base, UUIDPrimaryKeyMixin


class SupportRegistration(UUIDPrimaryKeyMixin, Base):
    __tablename__ = "support_registrations"
    __table_args__ = (
        CheckConstraint("grant_epoch > 0", name="grant_epoch"),
        CheckConstraint(
            "(custody_action_id IS NULL) <> (bootstrap_operator_id IS NULL)",
            name="invitation_authority",
        ),
        CheckConstraint(
            "(challenge IS NULL) = (challenge_expires_at IS NULL)"
            " AND (challenge IS NULL OR octet_length(challenge) = 32)",
            name="challenge",
        ),
    )

    custody_action_id: Mapped[UUID | None] = mapped_column(
        ForeignKey("support_custody_actions.id", ondelete="RESTRICT")
    )
    bootstrap_operator_id: Mapped[UUID | None] = mapped_column(
        ForeignKey("support_operators.id", ondelete="RESTRICT")
    )
    invitation_hash: Mapped[str] = mapped_column(String(64), unique=True)
    grant_epoch: Mapped[int] = mapped_column(BigInteger)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    challenge: Mapped[bytes | None] = mapped_column(LargeBinary(32))
    challenge_expires_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    consumed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class SupportBootstrap(Base):
    __tablename__ = "support_bootstrap"
    __table_args__ = (
        CheckConstraint("id = 1 AND first_id <> second_id", name="singleton_pair"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    first_id: Mapped[UUID] = mapped_column(ForeignKey("support_operators.id", ondelete="RESTRICT"))
    second_id: Mapped[UUID] = mapped_column(ForeignKey("support_operators.id", ondelete="RESTRICT"))
    approval_digest: Mapped[str] = mapped_column(String(64))
    started_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    activated_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class SupportBootstrapEvent(UUIDPrimaryKeyMixin, Base):
    __tablename__ = "support_bootstrap_events"
    __table_args__ = (
        CheckConstraint(
            "action IN ('started', 'invitations_issued', 'passkey_added', "
            "'registration_denied', 'activated')",
            name="action",
        ),
    )

    bootstrap_id: Mapped[int] = mapped_column(
        ForeignKey("support_bootstrap.id", ondelete="RESTRICT")
    )
    operator_id: Mapped[UUID | None] = mapped_column(
        ForeignKey("support_operators.id", ondelete="RESTRICT")
    )
    action: Mapped[str] = mapped_column(String(24))
    request_id: Mapped[str] = mapped_column(String(64))
    occurred_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
