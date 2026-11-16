"""Store separately reviewed payroll adjustments."""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "202605310055"
down_revision: str | None = "202605310054"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "hr_payroll_adjustments",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column(
            "run_id",
            sa.Uuid(),
            sa.ForeignKey("hr_payroll_runs.id", ondelete="RESTRICT"),
            nullable=False,
        ),
        sa.Column(
            "employee_id",
            sa.Uuid(),
            sa.ForeignKey("hr_employees.id", ondelete="RESTRICT"),
            nullable=False,
        ),
        sa.Column(
            "submitted_by_id", sa.Uuid(), sa.ForeignKey("users.id", ondelete="RESTRICT"),
            nullable=False,
        ),
        sa.Column("decided_by_id", sa.Uuid(), sa.ForeignKey("users.id", ondelete="RESTRICT")),
        sa.Column("decided_at", sa.DateTime(timezone=True)),
        sa.Column("status", sa.String(20), server_default="submitted", nullable=False),
        sa.Column("detail_encrypted", sa.Text(), nullable=False),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
    )
    # The index belongs to a new empty table.
    op.create_index("ix_hr_payroll_adjustments_run_id", "hr_payroll_adjustments", ["run_id"])


def downgrade() -> None:
    raise RuntimeError("Payroll adjustment decisions must be preserved.")
