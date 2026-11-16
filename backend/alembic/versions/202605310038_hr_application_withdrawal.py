"""Record application-level withdrawal and the retention review plan."""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "202605310038"
down_revision: str | None = "202605310037"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    for column in (
        sa.Column("withdrawn_at", sa.DateTime(timezone=True)),
        sa.Column("withdrawal_reason", sa.String(500)),
        sa.Column("retention_decision", sa.String(32)),
        sa.Column("retention_review_on", sa.Date()),
        sa.Column("retention_policy_reference", sa.String(120)),
    ):
        op.add_column("hr_applications", column)


def downgrade() -> None:
    if op.get_bind().scalar(
        sa.text("SELECT EXISTS (SELECT 1 FROM hr_applications WHERE withdrawn_at IS NOT NULL)")
    ):
        raise RuntimeError("Cannot remove retained application withdrawal decisions.")
    for column_name in (
        "retention_policy_reference",
        "retention_review_on",
        "retention_decision",
        "withdrawal_reason",
        "withdrawn_at",
    ):
        op.drop_column("hr_applications", column_name)
