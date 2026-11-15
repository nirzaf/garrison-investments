"""Track attendance review and the source revision of corrections.

Revision ID: 202605310012
Revises: 202605310011
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "202605310012"
down_revision: str | None = "202605310011"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    table = "hr_attendance_entries"
    op.add_column(
        table, sa.Column("record_revision", sa.Integer(), nullable=False, server_default="1")
    )
    op.add_column(
        table, sa.Column("status", sa.String(20), nullable=False, server_default="submitted")
    )
    op.add_column(table, sa.Column("review_note", sa.Text(), nullable=True))
    op.add_column(
        table,
        sa.Column(
            "requires_manager_recommendation", sa.Boolean(), nullable=False, server_default="false"
        ),
    )
    op.add_column(table, sa.Column("manager_recommendation", sa.String(20), nullable=True))
    op.add_column(table, sa.Column("manager_recommended_by_id", sa.Uuid(), nullable=True))
    op.add_column(
        table, sa.Column("manager_recommended_at", sa.DateTime(timezone=True), nullable=True)
    )
    op.create_foreign_key(
        "fk_hr_attendance_manager_reviewer",
        table,
        "users",
        ["manager_recommended_by_id"],
        ["id"],
        ondelete="SET NULL",
    )
    op.add_column(
        "hr_attendance_corrections", sa.Column("entry_revision", sa.Integer(), nullable=True)
    )
    op.execute("UPDATE hr_attendance_entries SET status = 'approved' WHERE approved_at IS NOT NULL")
    op.execute("""
        UPDATE hr_attendance_entries a SET status = 'historical'
        WHERE a.status = 'submitted' AND EXISTS (
            SELECT 1 FROM hr_timesheets t WHERE t.employee_id = a.employee_id
            AND t.status = 'locked' AND a.work_date BETWEEN t.period_start AND t.period_end
        )
    """)
    op.execute("""
        UPDATE hr_attendance_corrections c SET entry_revision = a.record_revision,
            attendance_entry_id = a.id
        FROM hr_attendance_entries a WHERE c.employee_id = a.employee_id
            AND c.work_date = a.work_date AND c.status = 'submitted'
    """)


def downgrade() -> None:
    table = "hr_attendance_entries"
    op.drop_column("hr_attendance_corrections", "entry_revision")
    op.drop_constraint("fk_hr_attendance_manager_reviewer", table, type_="foreignkey")
    for column in (
        "manager_recommended_at",
        "manager_recommended_by_id",
        "manager_recommendation",
        "requires_manager_recommendation",
        "review_note",
        "status",
        "record_revision",
    ):
        op.drop_column(table, column)
