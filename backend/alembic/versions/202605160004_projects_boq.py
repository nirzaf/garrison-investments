"""add projects boq milestones

Revision ID: 202605160004
Revises: 202605160003
Create Date: 2026-05-16
"""

from collections.abc import Sequence

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision: str = "202605160004"
down_revision: str | None = "202605160003"
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
        "projects",
        sa.Column(
            "id",
            postgresql.UUID(as_uuid=True),
            primary_key=True,
            server_default=sa.text("uuid_generate_v4()"),
        ),
        sa.Column("name", sa.String(length=200), nullable=False),
        sa.Column("code", sa.String(length=20), nullable=False),
        sa.Column("location", sa.Text(), nullable=True),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column("scope_of_work", sa.Text(), nullable=False),
        sa.Column(
            "status",
            sa.String(length=30),
            nullable=False,
            server_default=sa.text("'planning'"),
        ),
        sa.Column("budget_amount", sa.Numeric(15, 2), nullable=True),
        sa.Column("start_date", sa.Date(), nullable=True),
        sa.Column("target_end_date", sa.Date(), nullable=False),
        sa.Column("actual_end_date", sa.Date(), nullable=True),
        sa.Column("client_name", sa.String(length=200), nullable=True),
        sa.Column("contract_number", sa.String(length=50), nullable=True),
        sa.Column(
            "progress_percentage",
            sa.Numeric(5, 2),
            nullable=False,
            server_default=sa.text("0"),
        ),
        sa.Column(
            "created_by",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("users.id", ondelete="SET NULL"),
            nullable=True,
        ),
        *timestamp_columns(),
        sa.CheckConstraint(
            "status IN ('planning', 'active', 'on_hold', 'completed', 'cancelled')",
            name="ck_projects_status_valid",
        ),
    )
    op.create_index(
        "idx_projects_status",
        "projects",
        ["status"],
        postgresql_where=sa.text("deleted_at IS NULL"),
    )
    op.create_index("idx_projects_code", "projects", ["code"])
    op.create_index(
        "uq_projects_code_active",
        "projects",
        ["code"],
        unique=True,
        postgresql_where=sa.text("deleted_at IS NULL"),
    )

    op.create_table(
        "project_members",
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
            "user_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("users.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("role_in_project", sa.String(length=50), nullable=True),
        sa.Column(
            "assigned_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
        *timestamp_columns(),
    )
    op.create_index("idx_project_members_project", "project_members", ["project_id"])
    op.create_index("idx_project_members_user", "project_members", ["user_id"])
    op.create_index(
        "uq_project_members_active",
        "project_members",
        ["project_id", "user_id"],
        unique=True,
        postgresql_where=sa.text("deleted_at IS NULL"),
    )

    op.create_table(
        "project_milestones",
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
        sa.Column("name", sa.String(length=150), nullable=False),
        sa.Column("discipline", sa.String(length=50), nullable=True),
        sa.Column("planned_start_date", sa.Date(), nullable=True),
        sa.Column("planned_end_date", sa.Date(), nullable=True),
        sa.Column("actual_start_date", sa.Date(), nullable=True),
        sa.Column("actual_end_date", sa.Date(), nullable=True),
        sa.Column(
            "progress_percentage",
            sa.Numeric(5, 2),
            nullable=False,
            server_default=sa.text("0"),
        ),
        sa.Column(
            "status",
            sa.String(length=30),
            nullable=False,
            server_default=sa.text("'not_started'"),
        ),
        sa.Column("sort_order", sa.Integer(), nullable=False, server_default=sa.text("0")),
        *timestamp_columns(),
    )
    op.create_index(
        "idx_project_milestones_project",
        "project_milestones",
        ["project_id", "sort_order"],
    )
    op.create_index(
        "idx_project_milestones_status",
        "project_milestones",
        ["status"],
        postgresql_where=sa.text("deleted_at IS NULL"),
    )

    op.create_table(
        "boq_items",
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
        sa.Column("item_code", sa.String(length=50), nullable=False),
        sa.Column("description", sa.Text(), nullable=False),
        sa.Column("discipline", sa.String(length=50), nullable=True),
        sa.Column("phase", sa.String(length=100), nullable=True),
        sa.Column("unit", sa.String(length=20), nullable=False),
        sa.Column("planned_quantity", sa.Numeric(14, 3), nullable=False),
        sa.Column(
            "approved_quantity",
            sa.Numeric(14, 3),
            nullable=False,
            server_default=sa.text("0"),
        ),
        sa.Column("unit_rate", sa.Numeric(14, 2), nullable=False),
        sa.Column("planned_amount", sa.Numeric(15, 2), nullable=False),
        *timestamp_columns(),
    )
    op.create_index("idx_boq_items_project", "boq_items", ["project_id"])
    op.create_index("idx_boq_items_milestone", "boq_items", ["milestone_id"])
    op.create_index(
        "uq_boq_items_project_code_active",
        "boq_items",
        ["project_id", "item_code"],
        unique=True,
        postgresql_where=sa.text("deleted_at IS NULL"),
    )


def downgrade() -> None:
    op.drop_index("uq_boq_items_project_code_active", table_name="boq_items")
    op.drop_index("idx_boq_items_milestone", table_name="boq_items")
    op.drop_index("idx_boq_items_project", table_name="boq_items")
    op.drop_table("boq_items")
    op.drop_index("idx_project_milestones_status", table_name="project_milestones")
    op.drop_index("idx_project_milestones_project", table_name="project_milestones")
    op.drop_table("project_milestones")
    op.drop_index("uq_project_members_active", table_name="project_members")
    op.drop_index("idx_project_members_user", table_name="project_members")
    op.drop_index("idx_project_members_project", table_name="project_members")
    op.drop_table("project_members")
    op.drop_index("uq_projects_code_active", table_name="projects")
    op.drop_index("idx_projects_code", table_name="projects")
    op.drop_index("idx_projects_status", table_name="projects")
    op.drop_table("projects")
