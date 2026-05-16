"""add daily reports

Revision ID: 202605160006
Revises: 202605160005
Create Date: 2026-05-16
"""

from collections.abc import Sequence

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision: str = "202605160006"
down_revision: str | None = "202605160005"
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
    op.execute(
        "ALTER TABLE supervisor_updates "
        "DROP CONSTRAINT IF EXISTS ck_supervisor_updates_day_type_valid"
    )
    op.execute(
        "ALTER TABLE supervisor_updates "
        "DROP CONSTRAINT IF EXISTS ck_supervisor_updates_ck_supervisor_updates_day_type_valid"
    )
    op.create_check_constraint(
        op.f("ck_supervisor_updates_day_type_valid"),
        "supervisor_updates",
        "day_type IN ('weekday', 'friday', 'public_holiday')",
    )

    op.create_table(
        "daily_reports",
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
            "engineer_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("users.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("report_number", sa.String(length=60), nullable=True),
        sa.Column("report_date", sa.Date(), nullable=False),
        sa.Column("work_location", sa.String(length=255), nullable=False),
        sa.Column("manpower_total", sa.Integer(), nullable=False, server_default=sa.text("0")),
        sa.Column("overtime_hours", sa.Numeric(5, 2), nullable=False, server_default=sa.text("0")),
        sa.Column("work_completed", sa.Text(), nullable=False),
        sa.Column("progress_percentage", sa.Numeric(5, 2), nullable=False),
        sa.Column("safety_incidents", sa.Integer(), nullable=False, server_default=sa.text("0")),
        sa.Column("safety_notes", sa.Text(), nullable=True),
        sa.Column("wir_status", sa.String(length=50), nullable=False),
        sa.Column("inspection_status", sa.String(length=50), nullable=False),
        sa.Column("delay_notes", sa.Text(), nullable=True),
        sa.Column("next_day_plan", sa.Text(), nullable=False),
        sa.Column("supervisor_update_ids", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("photo_refs", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("attachment_refs", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column(
            "status",
            sa.String(length=20),
            nullable=False,
            server_default=sa.text("'draft'"),
        ),
        sa.Column("submitted_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "approved_by",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("users.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column("approved_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("rejection_comments", sa.Text(), nullable=True),
        sa.Column("extra_fields", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        *timestamp_columns(),
        sa.CheckConstraint(
            "status IN ('draft', 'submitted', 'approved', 'rejected')",
            name="ck_daily_reports_status_valid",
        ),
        sa.CheckConstraint(
            "progress_percentage >= 0 AND progress_percentage <= 100",
            name="ck_daily_reports_progress_valid",
        ),
        sa.CheckConstraint(
            "safety_incidents >= 0 AND manpower_total >= 0",
            name="ck_daily_reports_counts_valid",
        ),
    )
    op.create_index(
        "idx_daily_reports_project_date",
        "daily_reports",
        ["project_id", sa.text("report_date DESC")],
        postgresql_where=sa.text("deleted_at IS NULL"),
    )
    op.create_index("idx_daily_reports_status", "daily_reports", ["status"])
    op.create_index(
        "uq_daily_reports_report_number",
        "daily_reports",
        ["report_number"],
        unique=True,
        postgresql_where=sa.text("report_number IS NOT NULL"),
    )
    op.create_index(
        "idx_daily_reports_extra",
        "daily_reports",
        ["extra_fields"],
        postgresql_using="gin",
    )

    op.create_table(
        "report_manpower",
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
        sa.Column("trade", sa.String(length=100), nullable=False),
        sa.Column("count", sa.Integer(), nullable=False),
        sa.Column("overtime_hours", sa.Numeric(5, 2), nullable=False, server_default=sa.text("0")),
        *timestamp_columns(),
    )
    op.create_index("idx_report_manpower_report", "report_manpower", ["report_id"])

    op.create_table(
        "report_equipment",
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
        sa.Column("equipment_name", sa.String(length=120), nullable=False),
        sa.Column("quantity", sa.Integer(), nullable=False),
        sa.Column("hours_used", sa.Numeric(6, 2), nullable=False, server_default=sa.text("0")),
        sa.Column("remarks", sa.Text(), nullable=True),
        *timestamp_columns(),
    )
    op.create_index("idx_report_equipment_report", "report_equipment", ["report_id"])

    op.create_table(
        "report_material_consumption",
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
            "boq_item_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("boq_items.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column("material_name", sa.String(length=160), nullable=False),
        sa.Column("unit", sa.String(length=30), nullable=False),
        sa.Column("quantity", sa.Numeric(14, 3), nullable=False),
        sa.Column("remarks", sa.Text(), nullable=True),
        *timestamp_columns(),
    )
    op.create_index(
        "idx_report_material_consumption_report",
        "report_material_consumption",
        ["report_id"],
    )


def downgrade() -> None:
    op.drop_index(
        "idx_report_material_consumption_report",
        table_name="report_material_consumption",
    )
    op.drop_table("report_material_consumption")
    op.drop_index("idx_report_equipment_report", table_name="report_equipment")
    op.drop_table("report_equipment")
    op.drop_index("idx_report_manpower_report", table_name="report_manpower")
    op.drop_table("report_manpower")
    op.drop_index("idx_daily_reports_extra", table_name="daily_reports")
    op.drop_index("uq_daily_reports_report_number", table_name="daily_reports")
    op.drop_index("idx_daily_reports_status", table_name="daily_reports")
    op.drop_index("idx_daily_reports_project_date", table_name="daily_reports")
    op.drop_table("daily_reports")
    op.execute(
        "ALTER TABLE supervisor_updates "
        "DROP CONSTRAINT IF EXISTS ck_supervisor_updates_day_type_valid"
    )
    op.execute(
        "ALTER TABLE supervisor_updates "
        "DROP CONSTRAINT IF EXISTS ck_supervisor_updates_ck_supervisor_updates_day_type_valid"
    )
    op.create_check_constraint(
        op.f("ck_supervisor_updates_day_type_valid"),
        "supervisor_updates",
        "day_type IN ('weekday', 'weekend', 'holiday')",
    )
