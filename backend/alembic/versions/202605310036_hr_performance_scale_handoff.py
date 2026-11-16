"""Record optional cycle ratings and preserve open-review manager handoffs."""

from collections.abc import Sequence

import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import JSONB

from alembic import op

revision: str = "202605310036"
down_revision: str | None = "202605310035"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "hr_review_cycles",
        sa.Column("rating_scale", JSONB(), nullable=False, server_default=sa.text("'[]'::jsonb")),
    )
    op.add_column("hr_performance_events", sa.Column("rating", sa.String(60)))
    op.add_column("hr_performance_events", sa.Column("previous_reviewer_id", sa.Uuid()))
    op.add_column("hr_performance_events", sa.Column("replacement_reviewer_id", sa.Uuid()))


def downgrade() -> None:
    if op.get_bind().scalar(
        sa.text(
            "SELECT EXISTS (SELECT 1 FROM hr_performance_events "
            "WHERE rating IS NOT NULL OR replacement_reviewer_id IS NOT NULL) "
            "OR EXISTS (SELECT 1 FROM hr_review_cycles WHERE rating_scale <> '[]'::jsonb)"
        )
    ):
        raise RuntimeError("Cannot remove retained performance ratings or handoffs.")
    op.drop_column("hr_performance_events", "replacement_reviewer_id")
    op.drop_column("hr_performance_events", "previous_reviewer_id")
    op.drop_column("hr_performance_events", "rating")
    op.drop_column("hr_review_cycles", "rating_scale")
