"""Retain one reviewed Finance handoff receipt per approved payroll run."""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "202605310026"
down_revision: str | None = "202605310025"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "hr_payroll_exports",
        sa.Column(
            "run_id",
            sa.Uuid(),
            sa.ForeignKey("hr_payroll_runs.id", ondelete="RESTRICT"),
            primary_key=True,
        ),
        sa.Column(
            "exported_by_id",
            sa.Uuid(),
            sa.ForeignKey("users.id", ondelete="RESTRICT"),
            nullable=False,
        ),
        sa.Column("snapshot_digest", sa.String(64), nullable=False),
        sa.Column("csv_sha256", sa.String(64), nullable=False),
        sa.Column("format_version", sa.Integer(), nullable=False),
        sa.Column(
            "exported_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()
        ),
    )


def downgrade() -> None:
    if op.get_bind().scalar(sa.text("SELECT EXISTS (SELECT 1 FROM hr_payroll_exports)")):
        raise RuntimeError("Cannot remove retained payroll export receipts.")
    op.drop_table("hr_payroll_exports")
