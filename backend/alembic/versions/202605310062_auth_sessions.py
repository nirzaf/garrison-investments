"""Persist authenticated sessions and bind refresh tokens to their owners."""

import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import UUID

from alembic import op

revision = "202605310062"
down_revision = "202605310061"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "auth_sessions",
        sa.Column("id", UUID(), primary_key=True),
        sa.Column("user_id", UUID(), sa.ForeignKey("users.id", ondelete="CASCADE"), nullable=False),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()
        ),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("revoked_at", sa.DateTime(timezone=True), nullable=True),
        sa.UniqueConstraint("id", "user_id", name="uq_auth_sessions_id_user_id"),
        sa.CheckConstraint("expires_at > created_at", name="positive_lifetime"),
    )
    op.create_index("ix_auth_sessions_user_expiry", "auth_sessions", ["user_id", "expires_at"])
    op.add_column("auth_refresh_tokens", sa.Column("session_id", UUID(), nullable=True))
    op.create_foreign_key(
        "fk_auth_refresh_tokens_session_owner",
        "auth_refresh_tokens",
        "auth_sessions",
        ["session_id", "user_id"],
        ["id", "user_id"],
        ondelete="CASCADE",
    )
    op.create_index("ix_auth_refresh_tokens_session_id", "auth_refresh_tokens", ["session_id"])


def downgrade() -> None:
    raise RuntimeError(
        "Retain session ownership and revocation records during application rollback."
    )
