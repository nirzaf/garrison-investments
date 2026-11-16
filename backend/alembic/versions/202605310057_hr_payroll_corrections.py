"""Retain reviewed payroll corrections independently from closed runs."""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "202605310057"
down_revision: str | None = "202605310056"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "hr_payroll_corrections",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column(
            "line_id", sa.Uuid(), sa.ForeignKey("hr_payroll_lines.id", ondelete="RESTRICT"),
            nullable=False,
        ),
        sa.Column(
            "previous_id", sa.Uuid(),
            sa.ForeignKey("hr_payroll_corrections.id", ondelete="RESTRICT"),
        ),
        sa.Column("snapshot_digest", sa.String(64), nullable=False),
        sa.Column("detail_encrypted", sa.Text(), nullable=False),
        sa.Column("status", sa.String(20), server_default="submitted", nullable=False),
        sa.Column(
            "submitted_by_id", sa.Uuid(), sa.ForeignKey("users.id", ondelete="RESTRICT"),
            nullable=False,
        ),
        sa.Column("decided_by_id", sa.Uuid(), sa.ForeignKey("users.id", ondelete="RESTRICT")),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.Column("decided_at", sa.DateTime(timezone=True)),
        sa.CheckConstraint(
            "(status = 'submitted' AND decided_by_id IS NULL AND decided_at IS NULL) OR "
            "(status IN ('approved', 'rejected') AND decided_by_id IS NOT NULL "
            "AND decided_at IS NOT NULL AND decided_by_id <> submitted_by_id)",
            name="payroll_correction_decision",
        ),
    )
    # This index is created inside the new table's transaction.
    op.create_index(
        "ix_hr_payroll_corrections_line_created", "hr_payroll_corrections",
        ["line_id", "created_at", "id"],
    )


def downgrade() -> None:
    raise RuntimeError("Retained payroll correction records must be preserved.")
