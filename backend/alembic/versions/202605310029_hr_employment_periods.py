"""Retain separate employment periods when an employee separates and returns."""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "202605310029"
down_revision: str | None = "202605310028"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "hr_employment_periods",
        sa.Column("id", sa.Uuid(), primary_key=True, server_default=sa.text("uuid_generate_v4()")),
        sa.Column(
            "employee_id",
            sa.Uuid(),
            sa.ForeignKey("hr_employees.id", ondelete="RESTRICT"),
            nullable=False,
        ),
        sa.Column("started_on", sa.Date()),
        sa.Column("ended_on", sa.Date()),
        sa.Column(
            "separation_case_id",
            sa.Uuid(),
            sa.ForeignKey("hr_offboarding_cases.id", ondelete="RESTRICT"),
            unique=True,
        ),
        sa.Column(
            "rehire_change_id",
            sa.Uuid(),
            sa.ForeignKey("hr_employment_changes.id", ondelete="RESTRICT"),
            unique=True,
        ),
        sa.Column(
            "onboarding_case_id",
            sa.Uuid(),
            sa.ForeignKey("hr_onboarding_cases.id", ondelete="RESTRICT"),
            unique=True,
        ),
        sa.CheckConstraint(
            "(ended_on IS NULL AND started_on IS NOT NULL AND separation_case_id IS NULL) OR "
            "(ended_on IS NOT NULL AND separation_case_id IS NOT NULL "
            "AND (started_on IS NULL OR started_on <= ended_on))",
            name="employment_period_dates",
        ),
    )
    op.create_index(
        "uq_hr_employment_periods_open",
        "hr_employment_periods",
        ["employee_id"],
        unique=True,
        postgresql_where=sa.text("ended_on IS NULL"),
    )
    op.create_index(
        "ix_hr_employment_periods_employee_started",
        "hr_employment_periods",
        ["employee_id", "started_on", "id"],
    )


def downgrade() -> None:
    if op.get_bind().scalar(sa.text("SELECT EXISTS (SELECT 1 FROM hr_employment_periods)")):
        raise RuntimeError("Cannot remove retained employment periods.")
    op.drop_table("hr_employment_periods")
