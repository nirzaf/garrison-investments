"""Add effective-dated approval and publication to HR calendars.

Revision ID: 202605310008
Revises: 202605310007
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "202605310008"
down_revision: str | None = "202605310007"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    table = "hr_work_calendars"
    # Existing calendars need verified dates and timezone before approval.
    op.add_column(table, sa.Column("effective_from", sa.Date(), nullable=True))
    op.add_column(table, sa.Column("effective_to", sa.Date(), nullable=True))
    op.add_column(table, sa.Column("timezone", sa.String(64), nullable=True))
    op.add_column(table, sa.Column("status", sa.String(20), server_default="draft", nullable=False))
    op.add_column(table, sa.Column("revision", sa.Integer(), server_default="1", nullable=False))
    op.add_column(table, sa.Column("published_at", sa.DateTime(timezone=True), nullable=True))
    for column in ("created_by_id", "submitted_by_id", "approved_by_id"):
        op.add_column(table, sa.Column(column, sa.Uuid(), nullable=True))
        op.create_foreign_key(
            f"fk_work_calendar_{column}", table, "users", [column], ["id"], ondelete="SET NULL"
        )
    op.create_check_constraint(
        "hr_calendar_status", table, "status IN ('draft', 'submitted', 'approved', 'published')"
    )
    op.create_check_constraint(
        "hr_calendar_effective_window",
        table,
        "status = 'draft' OR (effective_from IS NOT NULL AND effective_to IS NOT NULL "
        "AND effective_from <= effective_to AND timezone IS NOT NULL)",
    )


def downgrade() -> None:
    table = "hr_work_calendars"
    op.drop_constraint("hr_calendar_effective_window", table, type_="check")
    op.drop_constraint("hr_calendar_status", table, type_="check")
    for column in ("approved_by_id", "submitted_by_id", "created_by_id"):
        op.drop_constraint(f"fk_work_calendar_{column}", table, type_="foreignkey")
        op.drop_column(table, column)
    for column in (
        "published_at",
        "revision",
        "status",
        "timezone",
        "effective_to",
        "effective_from",
    ):
        op.drop_column(table, column)
