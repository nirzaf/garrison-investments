"""Create the separate support identity realm without enrolling operators."""

import sqlalchemy as sa

from alembic import op

revision = "202605310063"
down_revision = "202605310062"
branch_labels = None
depends_on = None


def _timestamps() -> tuple[sa.Column, sa.Column]:
    return tuple(  # type: ignore[return-value]
        sa.Column(name, sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now())
        for name in ("created_at", "updated_at")
    )


def _operator_fk() -> sa.Column:
    return sa.Column(
        "operator_id",
        sa.Uuid(),
        sa.ForeignKey("support_operators.id", ondelete="RESTRICT"),
        nullable=False,
    )


def upgrade() -> None:
    op.create_table(
        "support_operators",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("display_label", sa.String(120), nullable=False),
        sa.Column("status", sa.String(16), nullable=False),
        sa.Column("grant_epoch", sa.BigInteger(), nullable=False),
        sa.CheckConstraint("status IN ('pending','active','suspended','revoked')", name="status"),
        sa.CheckConstraint("grant_epoch > 0", name="grant_epoch"),
        *_timestamps(),
    )
    op.create_table(
        "support_credentials",
        sa.Column("id", sa.Uuid(), primary_key=True),
        _operator_fk(),
        sa.Column("credential_hash", sa.String(64), nullable=False, unique=True),
        sa.Column("public_key", sa.LargeBinary(), nullable=False),
        sa.Column("sign_count", sa.BigInteger(), nullable=False),
        sa.Column("revoked_at", sa.DateTime(timezone=True)),
        sa.CheckConstraint("sign_count BETWEEN 0 AND 4294967295", name="sign_count"),
        sa.CheckConstraint("octet_length(public_key) BETWEEN 1 AND 4096", name="public_key"),
        *_timestamps(),
    )
    op.create_index("ix_support_credentials_operator_id", "support_credentials", ["operator_id"])
    op.create_table(
        "support_login_challenges",
        sa.Column("id", sa.Uuid(), primary_key=True),
        _operator_fk(),
        sa.Column("challenge", sa.LargeBinary(), nullable=False),
        sa.Column("grant_epoch", sa.BigInteger(), nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("consumed_at", sa.DateTime(timezone=True)),
        sa.CheckConstraint("octet_length(challenge) = 32", name="challenge_size"),
        *_timestamps(),
    )
    op.create_index(
        "ix_support_login_challenges_operator_created",
        "support_login_challenges",
        ["operator_id", "created_at"],
    )
    op.create_table(
        "support_sessions",
        sa.Column("id", sa.Uuid(), primary_key=True),
        _operator_fk(),
        sa.Column("token_hash", sa.String(64), nullable=False, unique=True),
        sa.Column("csrf_hash", sa.String(64), nullable=False),
        sa.Column("grant_epoch", sa.BigInteger(), nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("last_seen_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("revoked_at", sa.DateTime(timezone=True)),
        *_timestamps(),
    )
    op.create_index(
        "ix_support_sessions_operator_expiry", "support_sessions", ["operator_id", "expires_at"]
    )
    op.create_table(
        "support_auth_events",
        sa.Column("id", sa.Uuid(), primary_key=True),
        _operator_fk(),
        sa.Column("action", sa.String(20), nullable=False),
        sa.Column("request_id", sa.String(64), nullable=False),
        sa.Column("occurred_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint("action IN ('login','login_denied','logout')", name="action"),
    )
    op.create_index(
        "ix_support_auth_events_operator_occurred",
        "support_auth_events",
        ["operator_id", "occurred_at"],
    )


def downgrade() -> None:
    raise RuntimeError("Preserve technical operator identity and audit evidence during rollback.")
