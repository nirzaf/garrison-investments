from datetime import datetime
from typing import Any
from uuid import UUID

from sqlalchemy import (
    BigInteger,
    CheckConstraint,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    LargeBinary,
    String,
    UniqueConstraint,
    Uuid,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base, UUIDPrimaryKeyMixin
from app.models.support_oversight import sql_quoted_list

SUPPORT_ADMIN_COMMAND_KINDS: tuple[str, ...] = (
    "create_business_account",
    "set_account_state",
    "unlock_account",
    "change_business_role",
    "change_project_membership",
    "request_account_recovery",
    "revoke_business_session",
    "update_safe_setting",
    "retry_safe_job",
    "bulk_account_lifecycle",
)

SUPPORT_ADMIN_COMMAND_STATUSES: tuple[str, ...] = (
    "planned",
    "expired",
    "succeeded",
    "delivery_pending",
    "delivery_failed",
    "rejected",
)

SUPPORT_ADMIN_COMMAND_EVENTS: tuple[str, ...] = (
    "planned",
    "proof_issued",
    "proof_denied",
    "executed",
    "replayed",
    "rejected",
    "delivery_updated",
)

ALLOWLISTED_SAFE_SETTING_KEYS: tuple[str, ...] = (
    "company_display_name",
    "support_banner_notice",
    "default_directory_page_size",
    "maintenance_window_notice",
)


class SupportAdminCommand(UUIDPrimaryKeyMixin, Base):
    """Typed, revision-bound company administrative command and durable receipt."""

    __tablename__ = "support_admin_commands"
    __table_args__ = (
        UniqueConstraint(
            "operator_id",
            "command_kind",
            "idempotency_key",
            name="uq_support_admin_commands_operator_kind_key",
        ),
        CheckConstraint(
            f"command_kind IN ({sql_quoted_list(SUPPORT_ADMIN_COMMAND_KINDS)})",
            name="command_kind",
        ),
        CheckConstraint(
            f"status IN ({sql_quoted_list(SUPPORT_ADMIN_COMMAND_STATUSES)})",
            name="status",
        ),
        CheckConstraint(
            "authorization_mode IN ('single_owner', 'paired')",
            name="authorization_mode",
        ),
        Index("ix_support_admin_commands_target_created", "target_user_id", "created_at"),
        Index("ix_support_admin_commands_operator_created", "operator_id", "created_at"),
    )

    operator_id: Mapped[UUID] = mapped_column(
        ForeignKey("support_operators.id", ondelete="RESTRICT"), nullable=False
    )
    operator_epoch: Mapped[int] = mapped_column(BigInteger, nullable=False)
    session_id: Mapped[UUID] = mapped_column(
        ForeignKey("support_sessions.id", ondelete="RESTRICT"), nullable=False
    )
    case_id: Mapped[UUID | None] = mapped_column(
        ForeignKey("support_cases.id", ondelete="RESTRICT"), nullable=True
    )
    authorization_mode: Mapped[str] = mapped_column(String(16), nullable=False)
    command_kind: Mapped[str] = mapped_column(String(32), nullable=False)
    idempotency_key: Mapped[str] = mapped_column(String(64), nullable=False)
    target_user_id: Mapped[UUID | None] = mapped_column(Uuid(), nullable=True)
    target_revision: Mapped[int | None] = mapped_column(Integer, nullable=True)
    project_id: Mapped[UUID | None] = mapped_column(Uuid(), nullable=True)
    project_revision: Mapped[int | None] = mapped_column(Integer, nullable=True)
    policy_version: Mapped[str] = mapped_column(String(32), nullable=False)
    reason_code: Mapped[str] = mapped_column(String(32), nullable=False)
    reason: Mapped[str] = mapped_column(String(300), nullable=False)
    plan_sha256: Mapped[str] = mapped_column(String(64), nullable=False)
    payload_json: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False)
    result_json: Mapped[dict[str, Any] | None] = mapped_column(JSONB, nullable=True)
    status: Mapped[str] = mapped_column(String(24), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class SupportAdminCommandProof(UUIDPrimaryKeyMixin, Base):
    """One-use session- and command-bound passkey proof challenge."""

    __tablename__ = "support_admin_command_proofs"
    __table_args__ = (
        Index("ix_support_admin_command_proofs_command_id", "command_id"),
        CheckConstraint("octet_length(challenge) = 32", name="challenge_size"),
    )

    command_id: Mapped[UUID] = mapped_column(
        ForeignKey("support_admin_commands.id", ondelete="RESTRICT"), nullable=False
    )
    session_id: Mapped[UUID] = mapped_column(
        ForeignKey("support_sessions.id", ondelete="RESTRICT"), nullable=False
    )
    challenge: Mapped[bytes] = mapped_column(LargeBinary(32), nullable=False)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    consumed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class SupportAdminCommandEvent(UUIDPrimaryKeyMixin, Base):
    """Append-only technical audit ledger for company control centre commands."""

    __tablename__ = "support_admin_command_events"
    __table_args__ = (
        Index("ix_support_admin_command_events_command_occurred", "command_id", "occurred_at"),
        CheckConstraint(
            f"event IN ({sql_quoted_list(SUPPORT_ADMIN_COMMAND_EVENTS)})",
            name="event",
        ),
    )

    command_id: Mapped[UUID] = mapped_column(
        ForeignKey("support_admin_commands.id", ondelete="RESTRICT"), nullable=False
    )
    actor_id: Mapped[UUID] = mapped_column(
        ForeignKey("support_operators.id", ondelete="RESTRICT"), nullable=False
    )
    event: Mapped[str] = mapped_column(String(24), nullable=False)
    request_id: Mapped[str] = mapped_column(String(64), nullable=False)
    occurred_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)


class SupportSafeSetting(Base):
    """Allowlisted non-secret operational settings managed via audited commands."""

    __tablename__ = "support_safe_settings"
    __table_args__ = (
        CheckConstraint(
            f"key IN ({sql_quoted_list(ALLOWLISTED_SAFE_SETTING_KEYS)})",
            name="key",
        ),
        CheckConstraint("revision >= 1", name="revision"),
    )

    key: Mapped[str] = mapped_column(String(64), primary_key=True)
    value_json: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False)
    revision: Mapped[int] = mapped_column(Integer, nullable=False, default=1, server_default="1")
    updated_by_operator_id: Mapped[UUID] = mapped_column(
        ForeignKey("support_operators.id", ondelete="RESTRICT"), nullable=False
    )
    updated_by_command_id: Mapped[UUID] = mapped_column(
        ForeignKey("support_admin_commands.id", ondelete="RESTRICT"), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
