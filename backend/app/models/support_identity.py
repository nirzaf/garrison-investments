from datetime import datetime
from uuid import UUID

from sqlalchemy import BigInteger, CheckConstraint, DateTime, ForeignKey, Index, LargeBinary, String
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base, TimestampMixin, UUIDPrimaryKeyMixin


class SupportOperator(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "support_operators"
    __table_args__ = (
        CheckConstraint("status IN ('pending', 'active', 'suspended', 'revoked')", name="status"),
        CheckConstraint("grant_epoch > 0", name="grant_epoch"),
    )

    display_label: Mapped[str] = mapped_column(String(120))
    status: Mapped[str] = mapped_column(String(16))
    grant_epoch: Mapped[int] = mapped_column(BigInteger)


class SupportCredential(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "support_credentials"
    __table_args__ = (
        CheckConstraint("sign_count BETWEEN 0 AND 4294967295", name="sign_count"),
        CheckConstraint("octet_length(public_key) BETWEEN 1 AND 4096", name="public_key"),
    )

    operator_id: Mapped[UUID] = mapped_column(
        ForeignKey("support_operators.id", ondelete="RESTRICT"), index=True
    )
    credential_hash: Mapped[str] = mapped_column(String(64), unique=True)
    public_key: Mapped[bytes] = mapped_column(LargeBinary)
    sign_count: Mapped[int] = mapped_column(BigInteger)
    revoked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class SupportLoginChallenge(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "support_login_challenges"
    __table_args__ = (
        Index("ix_support_login_challenges_operator_created", "operator_id", "created_at"),
        CheckConstraint("octet_length(challenge) = 32", name="challenge_size"),
        CheckConstraint(
            "(cli_token_hash IS NULL) = (cli_csrf_hash IS NULL)"
            " AND (cli_token_hash IS NULL) = (cli_code_hash IS NULL)",
            name="cli_binding",
        ),
    )

    operator_id: Mapped[UUID] = mapped_column(
        ForeignKey("support_operators.id", ondelete="RESTRICT")
    )
    challenge: Mapped[bytes] = mapped_column(LargeBinary)
    grant_epoch: Mapped[int] = mapped_column(BigInteger)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    consumed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    cli_token_hash: Mapped[str | None] = mapped_column(String(64))
    cli_csrf_hash: Mapped[str | None] = mapped_column(String(64))
    cli_code_hash: Mapped[str | None] = mapped_column(String(64))


class SupportEmailOtp(UUIDPrimaryKeyMixin, Base):
    __tablename__ = "support_email_otps"
    __table_args__ = (CheckConstraint("attempts BETWEEN 0 AND 5", name="attempts"),)

    login_challenge_id: Mapped[UUID] = mapped_column(
        ForeignKey("support_login_challenges.id", ondelete="RESTRICT"), unique=True
    )
    code_digest: Mapped[str] = mapped_column(String(64))
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    attempts: Mapped[int] = mapped_column()
    accepted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    used_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class SupportSession(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "support_sessions"
    __table_args__ = (Index("ix_support_sessions_operator_expiry", "operator_id", "expires_at"),)

    operator_id: Mapped[UUID] = mapped_column(
        ForeignKey("support_operators.id", ondelete="RESTRICT")
    )
    token_hash: Mapped[str] = mapped_column(String(64), unique=True)
    csrf_hash: Mapped[str] = mapped_column(String(64))
    grant_epoch: Mapped[int] = mapped_column(BigInteger)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    last_seen_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    revoked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class SupportAuthEvent(UUIDPrimaryKeyMixin, Base):
    __tablename__ = "support_auth_events"
    __table_args__ = (
        CheckConstraint("action IN ('login', 'login_denied', 'logout')", name="action"),
        Index("ix_support_auth_events_operator_occurred", "operator_id", "occurred_at"),
    )

    operator_id: Mapped[UUID] = mapped_column(
        ForeignKey("support_operators.id", ondelete="RESTRICT")
    )
    action: Mapped[str] = mapped_column(String(20))
    request_id: Mapped[str] = mapped_column(String(64))
    occurred_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
