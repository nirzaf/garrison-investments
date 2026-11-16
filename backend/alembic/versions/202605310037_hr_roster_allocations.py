"""Add a separate ledger for planned site allocations."""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "202605310037"
down_revision: str | None = "202605310036"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "hr_roster_allocations",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column(
            "employee_id",
            sa.Uuid(),
            sa.ForeignKey("hr_employees.id", ondelete="RESTRICT"),
            nullable=False,
        ),
        sa.Column(
            "project_id",
            sa.Uuid(),
            sa.ForeignKey("projects.id", ondelete="RESTRICT"),
            nullable=False,
        ),
        sa.Column(
            "calendar_id",
            sa.Uuid(),
            sa.ForeignKey("hr_work_calendars.id", ondelete="RESTRICT"),
            nullable=False,
        ),
        sa.Column(
            "shift_id", sa.Uuid(), sa.ForeignKey("hr_shift_assignments.id", ondelete="RESTRICT")
        ),
        sa.Column("employee_name", sa.String(255), nullable=False),
        sa.Column("project_name", sa.String(200), nullable=False),
        sa.Column("work_date", sa.Date(), nullable=False),
        sa.Column("timezone", sa.String(64), nullable=False),
        sa.Column("starts_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("ends_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("planned_hours", sa.Numeric(5, 2), nullable=False),
        sa.Column("created_by_id", sa.Uuid(), sa.ForeignKey("users.id", ondelete="SET NULL")),
        sa.Column("cancelled_at", sa.DateTime(timezone=True)),
        sa.Column("cancelled_by_id", sa.Uuid(), sa.ForeignKey("users.id", ondelete="SET NULL")),
        sa.Column("cancellation_reason", sa.String(500)),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.CheckConstraint("ends_at > starts_at AND planned_hours > 0", name="hr_roster_interval"),
        sa.CheckConstraint(
            "(cancelled_at IS NULL AND cancellation_reason IS NULL) OR "
            "(cancelled_at IS NOT NULL AND cancellation_reason IS NOT NULL)",
            name="hr_roster_cancellation",
        ),
    )
    # Only the new empty table is indexed here, within the schema transaction.
    op.create_index("ix_hr_roster_date_id", "hr_roster_allocations", ["work_date", "id"])
    op.create_index(
        "ix_hr_roster_active_employee_start",
        "hr_roster_allocations",
        ["employee_id", "starts_at"],
        postgresql_where=sa.text("cancelled_at IS NULL"),
    )


def downgrade() -> None:
    if op.get_bind().scalar(sa.text("SELECT EXISTS (SELECT 1 FROM hr_roster_allocations)")):
        raise RuntimeError("Cannot remove retained roster allocations.")
    op.drop_table("hr_roster_allocations")
