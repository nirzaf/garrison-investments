"""Store year-end leave receipts and explicit policy authority to expire excess leave."""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "202605310018"
down_revision: str | None = "202605310017"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "hr_leave_policies",
        sa.Column(
            "expire_excess_on_rollover", sa.Boolean(), nullable=False, server_default=sa.false()
        ),
    )
    op.create_table(
        "hr_leave_rollovers",
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
        sa.Column("source_year", sa.Integer(), nullable=False),
        sa.Column("carried_days", sa.Numeric(6, 2), nullable=False),
        sa.Column("expired_days", sa.Numeric(6, 2), nullable=False),
        sa.Column(
            "transferred_out_id",
            sa.Uuid(),
            sa.ForeignKey("hr_leave_ledger.id", ondelete="RESTRICT"),
            unique=True,
        ),
        sa.Column(
            "transferred_in_id",
            sa.Uuid(),
            sa.ForeignKey("hr_leave_ledger.id", ondelete="RESTRICT"),
            unique=True,
        ),
        sa.Column(
            "expiry_entry_id",
            sa.Uuid(),
            sa.ForeignKey("hr_leave_ledger.id", ondelete="RESTRICT"),
            unique=True,
        ),
        sa.Column("actor_user_id", sa.Uuid(), sa.ForeignKey("users.id", ondelete="SET NULL")),
        sa.Column("plan_digest", sa.String(64), nullable=False),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()
        ),
        sa.UniqueConstraint("employee_id", "leave_type_id", "source_year"),
        sa.CheckConstraint("carried_days >= 0 AND expired_days >= 0", name="nonnegative_days"),
    )


def downgrade() -> None:
    if op.get_bind().scalar(sa.text("SELECT EXISTS (SELECT 1 FROM hr_leave_rollovers)")):
        raise RuntimeError("Cannot remove leave year closure after posting a rollover.")
    op.drop_table("hr_leave_rollovers")
    op.drop_column("hr_leave_policies", "expire_excess_on_rollover")
