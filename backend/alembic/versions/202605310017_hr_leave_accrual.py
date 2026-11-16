"""Store one policy-backed leave accrual receipt per employee and period."""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "202605310017"
down_revision: str | None = "202605310016"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "hr_leave_accruals",
        sa.Column("id", sa.Uuid(), primary_key=True, server_default=sa.text("uuid_generate_v4()")),
        sa.Column(
            "employee_id",
            sa.Uuid(),
            sa.ForeignKey("hr_employees.id", ondelete="RESTRICT"),
            nullable=False,
        ),
        sa.Column(
            "leave_type_id",
            sa.Uuid(),
            sa.ForeignKey("hr_leave_types.id", ondelete="RESTRICT"),
            nullable=False,
        ),
        sa.Column(
            "policy_id",
            sa.Uuid(),
            sa.ForeignKey("hr_leave_policies.id", ondelete="RESTRICT"),
            nullable=False,
        ),
        sa.Column(
            "ledger_id",
            sa.Uuid(),
            sa.ForeignKey("hr_leave_ledger.id", ondelete="RESTRICT"),
            nullable=False,
            unique=True,
        ),
        sa.Column("period_start", sa.Date(), nullable=False),
        sa.Column("period_end", sa.Date(), nullable=False),
        sa.Column("plan_digest", sa.String(64), nullable=False),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()
        ),
        sa.UniqueConstraint(
            "employee_id", "leave_type_id", "period_start", name="uq_hr_leave_accrual_period"
        ),
        sa.CheckConstraint("period_start <= period_end", name="leave_accrual_dates"),
    )


def downgrade() -> None:
    if op.get_bind().scalar(sa.text("SELECT EXISTS (SELECT 1 FROM hr_leave_accruals)")):
        raise RuntimeError("Cannot remove accrual receipt protection after posting leave credits.")
    op.drop_table("hr_leave_accruals")
