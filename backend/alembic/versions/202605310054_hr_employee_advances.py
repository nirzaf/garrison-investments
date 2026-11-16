"""Record approved employee advances and external recoveries."""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "202605310054"
down_revision: str | None = "202605310053"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "hr_benefit_types",
        sa.Column("allows_advances", sa.Boolean(), server_default=sa.false(), nullable=False),
    )
    op.create_table(
        "hr_employee_advances",
        sa.Column("id", sa.Uuid(), primary_key=True, server_default=sa.text("uuid_generate_v4()")),
        sa.Column(
            "employee_id",
            sa.Uuid(),
            sa.ForeignKey("hr_employees.id", ondelete="RESTRICT"),
            nullable=False,
        ),
        sa.Column(
            "benefit_assignment_id",
            sa.Uuid(),
            sa.ForeignKey("hr_employee_benefits.id", ondelete="RESTRICT"),
            nullable=False,
        ),
        sa.Column(
            "submitted_by_id",
            sa.Uuid(),
            sa.ForeignKey("users.id", ondelete="RESTRICT"),
            nullable=False,
        ),
        sa.Column("requested_on", sa.Date(), nullable=False),
        sa.Column("amount", sa.Numeric(15, 2), nullable=False),
        sa.Column("currency", sa.String(3), nullable=False),
        sa.Column("status", sa.String(20), server_default="submitted", nullable=False),
        sa.Column("decided_by_id", sa.Uuid(), sa.ForeignKey("users.id", ondelete="RESTRICT")),
        sa.Column("decided_at", sa.DateTime(timezone=True)),
        sa.Column("disbursement_reference", sa.String(100)),
        sa.Column("disbursed_on", sa.Date()),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
    )
    # The table is new and empty in this transaction.
    op.create_index(
        "ix_hr_employee_advances_benefit_assignment_id",
        "hr_employee_advances",
        ["benefit_assignment_id"],
    )
    op.create_table(
        "hr_advance_recoveries",
        sa.Column("id", sa.Uuid(), primary_key=True, server_default=sa.text("uuid_generate_v4()")),
        sa.Column(
            "advance_id",
            sa.Uuid(),
            sa.ForeignKey("hr_employee_advances.id", ondelete="RESTRICT"),
            nullable=False,
        ),
        sa.Column(
            "recorded_by_id",
            sa.Uuid(),
            sa.ForeignKey("users.id", ondelete="RESTRICT"),
            nullable=False,
        ),
        sa.Column("reference", sa.String(100), nullable=False),
        sa.Column("occurred_on", sa.Date(), nullable=False),
        sa.Column("amount", sa.Numeric(15, 2), nullable=False),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.UniqueConstraint("advance_id", "reference", name="uq_hr_advance_recovery_reference"),
    )


def downgrade() -> None:
    if op.get_bind().scalar(
        sa.text(
            "SELECT EXISTS (SELECT 1 FROM hr_employee_advances) OR "
            "EXISTS (SELECT 1 FROM hr_benefit_types WHERE allows_advances)"
        )
    ):
        raise RuntimeError("Cannot discard retained advance evidence.")
    op.drop_table("hr_advance_recoveries")
    op.drop_table("hr_employee_advances")
    op.drop_column("hr_benefit_types", "allows_advances")
