"""Add optimistic concurrency revisions to daily reports."""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "202605310003"
down_revision: str | None = "202605300003"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "daily_reports",
        sa.Column("revision", sa.Integer(), server_default=sa.text("1"), nullable=False),
    )


def downgrade() -> None:
    op.drop_column("daily_reports", "revision")
