"""add supervisor updates

Revision ID: 202605160005
Revises: 202605160004
Create Date: 2026-05-16
"""

from collections.abc import Sequence

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision: str = "202605160005"
down_revision: str | None = "202605160004"
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
        "supervisor_updates",
        sa.Column(
            "id",
            postgresql.UUID(as_uuid=True),
            primary_key=True,
            server_default=sa.text("uuid_generate_v4()"),
        ),
        sa.Column(
            "project_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("projects.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "supervisor_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("users.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("update_date", sa.Date(), nullable=False),
        sa.Column(
            "day_type",
            sa.String(length=20),
            nullable=False,
            server_default=sa.text("'weekday'"),
        ),
        sa.Column("work_location", sa.String(length=255), nullable=False),
        sa.Column("attendance_count", sa.Integer(), nullable=False),
        sa.Column("overtime_hours", sa.Numeric(5, 2), nullable=False, server_default=sa.text("0")),
        sa.Column("progress_notes", sa.Text(), nullable=False),
        sa.Column("delay_notes", sa.Text(), nullable=True),
        sa.Column("required_notes", sa.Text(), nullable=False),
        sa.Column("attachment_refs", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column(
            "status",
            sa.String(length=20),
            nullable=False,
            server_default=sa.text("'draft'"),
        ),
        sa.Column("submitted_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "verified_by",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("users.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column("verified_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("verification_notes", sa.Text(), nullable=True),
        *timestamp_columns(),
        sa.CheckConstraint(
            "status IN ('draft', 'submitted', 'verified', 'rejected')",
            name="ck_supervisor_updates_status_valid",
        ),
        sa.CheckConstraint(
            "day_type IN ('weekday', 'weekend', 'holiday')",
            name="ck_supervisor_updates_day_type_valid",
        ),
    )
    op.create_index(
        "idx_supervisor_updates_project_date",
        "supervisor_updates",
        ["project_id", "update_date"],
        postgresql_where=sa.text("deleted_at IS NULL"),
    )
    op.create_index(
        "idx_supervisor_updates_supervisor",
        "supervisor_updates",
        ["supervisor_id"],
        postgresql_where=sa.text("deleted_at IS NULL"),
    )
    op.create_index(
        "uq_supervisor_update_draft_owner",
        "supervisor_updates",
        ["project_id", "update_date", "supervisor_id"],
        unique=True,
        postgresql_where=sa.text("deleted_at IS NULL AND status IN ('draft', 'submitted')"),
    )


def downgrade() -> None:
    op.drop_index("uq_supervisor_update_draft_owner", table_name="supervisor_updates")
    op.drop_index("idx_supervisor_updates_supervisor", table_name="supervisor_updates")
    op.drop_index("idx_supervisor_updates_project_date", table_name="supervisor_updates")
    op.drop_table("supervisor_updates")
