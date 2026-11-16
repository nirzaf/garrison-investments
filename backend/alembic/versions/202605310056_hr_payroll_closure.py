"""Retain immutable payroll closure receipts."""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "202605310056"
down_revision: str | None = "202605310055"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "hr_payroll_closures",
        sa.Column(
            "run_id", sa.Uuid(), sa.ForeignKey("hr_payroll_runs.id", ondelete="RESTRICT"),
            primary_key=True,
        ),
        sa.Column(
            "closed_by_id", sa.Uuid(), sa.ForeignKey("users.id", ondelete="RESTRICT"),
            nullable=False,
        ),
        sa.Column("snapshot_digest", sa.String(64), nullable=False),
        sa.Column("csv_sha256", sa.String(64), nullable=False),
        sa.Column("settlement_digest", sa.String(64), nullable=False),
        sa.Column("closed_at", sa.DateTime(timezone=True), server_default=sa.func.now(),
                  nullable=False),
    )


def downgrade() -> None:
    raise RuntimeError("Payroll closure receipts must be preserved.")
