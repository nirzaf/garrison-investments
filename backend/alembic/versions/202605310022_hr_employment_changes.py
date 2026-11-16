"""Keep proposed and independently reviewed effective-dated employee changes."""

from collections.abc import Sequence

import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import JSONB

from alembic import op

revision: str = "202605310022"
down_revision: str | None = "202605310021"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "hr_employment_changes",
        sa.Column("id", sa.Uuid(), primary_key=True, server_default=sa.text("uuid_generate_v4()")),
        sa.Column(
            "employee_id",
            sa.Uuid(),
            sa.ForeignKey("hr_employees.id", ondelete="RESTRICT"),
            nullable=False,
        ),
        sa.Column("change_type", sa.String(20), nullable=False),
        sa.Column("effective_date", sa.Date(), nullable=False),
        sa.Column("employee_revision", sa.Integer(), nullable=False),
        sa.Column("updates", JSONB(), nullable=False),
        sa.Column("reason", sa.Text(), nullable=False),
        sa.Column("status", sa.String(16), nullable=False, server_default="proposed"),
        sa.Column(
            "proposed_by",
            sa.Uuid(),
            sa.ForeignKey("users.id", ondelete="RESTRICT"),
            nullable=False,
        ),
        sa.Column("decided_by", sa.Uuid(), sa.ForeignKey("users.id", ondelete="RESTRICT")),
        sa.Column("decided_at", sa.DateTime(timezone=True)),
        sa.Column("decision_reason", sa.Text()),
        sa.Column("applied_by", sa.Uuid(), sa.ForeignKey("users.id", ondelete="RESTRICT")),
        sa.Column("applied_at", sa.DateTime(timezone=True)),
        sa.Column("applied_employee_revision", sa.Integer()),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()
        ),
        sa.CheckConstraint(
            "(status = 'proposed' AND decided_by IS NULL AND decided_at IS NULL) OR "
            "(status IN ('approved', 'rejected', 'applied') AND decided_by IS NOT NULL "
            "AND decided_by <> proposed_by AND decided_at IS NOT NULL)",
            name="employment_change_review",
        ),
        sa.CheckConstraint(
            "(status = 'applied' AND applied_by IS NOT NULL AND applied_at IS NOT NULL "
            "AND applied_employee_revision = employee_revision + 1 "
            "AND applied_employee_revision IS NOT NULL) OR "
            "(status <> 'applied' AND applied_by IS NULL AND applied_at IS NULL "
            "AND applied_employee_revision IS NULL)",
            name="employment_change_apply",
        ),
    )
    op.create_index(
        "ix_hr_employment_changes_employee_created",
        "hr_employment_changes",
        ["employee_id", "created_at", "id"],
    )


def downgrade() -> None:
    if op.get_bind().scalar(sa.text("SELECT EXISTS (SELECT 1 FROM hr_employment_changes)")):
        raise RuntimeError("Cannot remove reviewed employment change records.")
    op.drop_table("hr_employment_changes")
