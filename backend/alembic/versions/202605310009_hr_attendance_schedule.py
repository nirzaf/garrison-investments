"""Retain the published schedule used for each new attendance entry.

Revision ID: 202605310009
Revises: 202605310008
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "202605310009"
down_revision: str | None = "202605310008"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    table = "hr_attendance_entries"
    op.add_column(table, sa.Column("calendar_id", sa.Uuid(), nullable=True))
    op.add_column(table, sa.Column("shift_assignment_id", sa.Uuid(), nullable=True))
    op.add_column(table, sa.Column("scheduled_workday", sa.Boolean(), nullable=True))
    op.create_foreign_key(
        "fk_hr_attendance_schedule_calendar",
        table,
        "hr_work_calendars",
        ["calendar_id"],
        ["id"],
        ondelete="RESTRICT",
    )
    op.create_foreign_key(
        "fk_hr_attendance_schedule_shift",
        table,
        "hr_shift_assignments",
        ["shift_assignment_id"],
        ["id"],
        ondelete="RESTRICT",
    )


def downgrade() -> None:
    table = "hr_attendance_entries"
    op.drop_constraint("fk_hr_attendance_schedule_shift", table, type_="foreignkey")
    op.drop_constraint("fk_hr_attendance_schedule_calendar", table, type_="foreignkey")
    op.drop_column(table, "scheduled_workday")
    op.drop_column(table, "shift_assignment_id")
    op.drop_column(table, "calendar_id")
