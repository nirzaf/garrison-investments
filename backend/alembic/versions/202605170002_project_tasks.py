"""add project tasks

Revision ID: 202605170002
Revises: 202605170001
Create Date: 2026-05-17
"""

from collections.abc import Sequence

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision: str = "202605170002"
down_revision: str | None = "202605170001"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "project_tasks",
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
            "milestone_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("project_milestones.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column(
            "dependency_task_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("project_tasks.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column(
            "owner_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("users.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column("name", sa.String(length=180), nullable=False),
        sa.Column("baseline_start_date", sa.Date(), nullable=True),
        sa.Column("baseline_end_date", sa.Date(), nullable=True),
        sa.Column("planned_start_date", sa.Date(), nullable=True),
        sa.Column("planned_end_date", sa.Date(), nullable=True),
        sa.Column("actual_start_date", sa.Date(), nullable=True),
        sa.Column("actual_end_date", sa.Date(), nullable=True),
        sa.Column(
            "status",
            sa.String(length=30),
            nullable=False,
            server_default=sa.text("'not_started'"),
        ),
        sa.Column(
            "progress_percentage",
            sa.Numeric(5, 2),
            nullable=False,
            server_default=sa.text("0"),
        ),
        sa.Column("delay_reason", sa.Text(), nullable=True),
        sa.Column("sort_order", sa.Integer(), nullable=False, server_default=sa.text("0")),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()
        ),
        sa.Column("deleted_at", sa.DateTime(timezone=True), nullable=True),
        sa.CheckConstraint(
            "status IN ('not_started', 'in_progress', 'blocked', 'completed', 'cancelled')",
            name="ck_project_tasks_status_valid",
        ),
        sa.CheckConstraint(
            "progress_percentage >= 0 AND progress_percentage <= 100",
            name="ck_project_tasks_progress_valid",
        ),
    )
    op.create_index("idx_project_tasks_project", "project_tasks", ["project_id", "status"])
    op.create_index("idx_project_tasks_owner", "project_tasks", ["owner_id"])
    op.create_index("idx_project_tasks_dependency", "project_tasks", ["dependency_task_id"])


def downgrade() -> None:
    op.drop_index("idx_project_tasks_dependency", table_name="project_tasks")
    op.drop_index("idx_project_tasks_owner", table_name="project_tasks")
    op.drop_index("idx_project_tasks_project", table_name="project_tasks")
    op.drop_table("project_tasks")
