"""Record and limit active business audit streams across API workers."""

import sqlalchemy as sa

from alembic import op

revision = "202605310092"
down_revision = "202605310091"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "business_log_streams",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("user_id", sa.Uuid(), nullable=False),
        sa.Column("request_id", sa.String(64), nullable=False),
        sa.Column("opened_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("closed_at", sa.DateTime(timezone=True)),
    )
    with op.get_context().autocommit_block():
        op.create_index(
            "ix_business_log_streams_user_expiry", "business_log_streams",
            ["user_id", "expires_at"], postgresql_concurrently=True,
        )


def downgrade() -> None:
    raise RuntimeError("Preserve business audit stream access records.")
