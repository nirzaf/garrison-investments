"""Add opt-in routing and advisory manager review to time and leave requests.

Revision ID: 202605310010
Revises: 202605310009
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "202605310010"
down_revision: str | None = "202605310009"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

TABLES = ("hr_leave_requests", "hr_overtime_requests", "hr_timesheets")


def upgrade() -> None:
    op.add_column("hr_employees", sa.Column("line_manager_reviewer_id", sa.Uuid(), nullable=True))
    op.create_foreign_key(
        "fk_hr_employee_line_manager_reviewer",
        "hr_employees",
        "hr_employees",
        ["line_manager_reviewer_id"],
        ["id"],
        ondelete="SET NULL",
    )
    for table in TABLES:
        op.add_column(
            table, sa.Column("record_revision", sa.Integer(), server_default="1", nullable=False)
        )
        op.add_column(
            table,
            sa.Column(
                "requires_manager_recommendation",
                sa.Boolean(),
                server_default="false",
                nullable=False,
            ),
        )
        op.add_column(table, sa.Column("manager_recommendation", sa.String(20), nullable=True))
        op.add_column(table, sa.Column("manager_recommended_by_id", sa.Uuid(), nullable=True))
        op.add_column(
            table, sa.Column("manager_recommended_at", sa.DateTime(timezone=True), nullable=True)
        )
        op.create_foreign_key(
            f"fk_{table}_manager_recommended_by",
            table,
            "users",
            ["manager_recommended_by_id"],
            ["id"],
            ondelete="SET NULL",
        )
    op.add_column("hr_timesheets", sa.Column("submitted_by_id", sa.Uuid(), nullable=True))
    op.create_foreign_key(
        "fk_hr_timesheets_submitted_by",
        "hr_timesheets",
        "users",
        ["submitted_by_id"],
        ["id"],
        ondelete="SET NULL",
    )


def downgrade() -> None:
    op.drop_constraint("fk_hr_timesheets_submitted_by", "hr_timesheets", type_="foreignkey")
    op.drop_column("hr_timesheets", "submitted_by_id")
    for table in reversed(TABLES):
        op.drop_constraint(f"fk_{table}_manager_recommended_by", table, type_="foreignkey")
        for column in (
            "manager_recommended_at",
            "manager_recommended_by_id",
            "manager_recommendation",
            "requires_manager_recommendation",
            "record_revision",
        ):
            op.drop_column(table, column)
    op.drop_constraint("fk_hr_employee_line_manager_reviewer", "hr_employees", type_="foreignkey")
    op.drop_column("hr_employees", "line_manager_reviewer_id")
