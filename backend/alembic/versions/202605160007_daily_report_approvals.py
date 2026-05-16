"""add daily report approval history

Revision ID: 202605160007
Revises: 202605160006
Create Date: 2026-05-16
"""

from collections.abc import Sequence

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision: str = "202605160007"
down_revision: str | None = "202605160006"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def timestamp_columns() -> list[sa.Column]:
    return [
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
        sa.Column("deleted_at", sa.DateTime(timezone=True), nullable=True),
    ]


def upgrade() -> None:
    op.create_table(
        "daily_report_approval_history",
        sa.Column(
            "id",
            postgresql.UUID(as_uuid=True),
            primary_key=True,
            server_default=sa.text("uuid_generate_v4()"),
        ),
        sa.Column(
            "report_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("daily_reports.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "actor_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("users.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column("decision", sa.String(length=20), nullable=False),
        sa.Column("previous_status", sa.String(length=20), nullable=False),
        sa.Column("comments", sa.Text(), nullable=True),
        sa.Column("decided_at", sa.DateTime(timezone=True), nullable=False),
        *timestamp_columns(),
        sa.CheckConstraint(
            "decision IN ('submitted', 'approved', 'rejected')",
            name="ck_daily_report_approval_history_decision_valid",
        ),
    )
    op.create_index(
        "idx_daily_report_approval_history_report",
        "daily_report_approval_history",
        ["report_id", sa.text("decided_at DESC")],
    )


def downgrade() -> None:
    op.drop_index(
        "idx_daily_report_approval_history_report",
        table_name="daily_report_approval_history",
    )
    op.drop_table("daily_report_approval_history")
