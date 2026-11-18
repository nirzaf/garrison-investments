"""Bind single-owner account actions to their proposing session."""

import sqlalchemy as sa

from alembic import op

revision = "202605310097"
down_revision = "202605310096"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "support_business_actions",
        sa.Column("owner_session_id", sa.Uuid(), sa.ForeignKey("support_sessions.id")),
    )


def downgrade() -> None:
    raise RuntimeError("Preserve the authorization context of immutable account actions.")
