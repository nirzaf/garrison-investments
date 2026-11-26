"""Mark obsolete leave action alerts while preserving notification history."""

import sqlalchemy as sa

from alembic import op

revision = "202605310115"
down_revision = "202605310114"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "notifications",
        sa.Column("superseded_at", sa.DateTime(timezone=True), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("notifications", "superseded_at")
