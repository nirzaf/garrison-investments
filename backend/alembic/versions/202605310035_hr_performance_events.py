"""Retain participant decisions and addenda for performance reviews."""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "202605310035"
down_revision: str | None = "202605310034"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "hr_performance_events",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column(
            "review_id",
            sa.Uuid(),
            sa.ForeignKey("hr_reviews.id", ondelete="RESTRICT"),
            nullable=False,
        ),
        sa.Column("revision", sa.Integer(), nullable=False),
        sa.Column("action", sa.String(32), nullable=False),
        sa.Column("participant", sa.String(16), nullable=False),
        sa.Column(
            "actor_id", sa.Uuid(), sa.ForeignKey("users.id", ondelete="RESTRICT"), nullable=False
        ),
        sa.Column("notes", sa.Text()),
        sa.Column(
            "occurred_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()
        ),
        sa.UniqueConstraint("review_id", "revision"),
    )


def downgrade() -> None:
    if op.get_bind().scalar(sa.text("SELECT EXISTS (SELECT 1 FROM hr_performance_events)")):
        raise RuntimeError("Cannot remove retained performance decisions.")
    op.drop_table("hr_performance_events")
