"""Retain independent QS and engineer decisions for submitted site progress."""

import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import JSONB

from alembic import op

revision = "202605310104"
down_revision = "202605310103"
branch_labels = None
depends_on = None


def upgrade() -> None:
    for column in (
        sa.Column("revision", sa.Integer(), nullable=False, server_default="1"),
        sa.Column("submission_revision", sa.Integer()),
        sa.Column("activity_scope", sa.Text()),
        sa.Column("remaining_work", sa.Text()),
        sa.Column("completed_area", sa.String(255)),
        sa.Column("completed_quantity", sa.Numeric(14, 3)),
        sa.Column("quantity_unit", sa.String(30)),
        sa.Column("progress_percentage", sa.Numeric(5, 2)),
    ):
        op.add_column("supervisor_updates", column)
    op.drop_constraint(
        op.f("ck_supervisor_updates_ck_supervisor_updates_status_valid"),
        "supervisor_updates",
        type_="check",
    )
    op.create_check_constraint(
        "status_valid",
        "supervisor_updates",
        "status IN ('draft','submitted','pending_qs','pending_engineer',"
        "'returned','verified','rejected')",
    )
    op.drop_index("uq_supervisor_update_draft_owner", table_name="supervisor_updates")
    op.create_index(
        "uq_supervisor_update_draft_owner",
        "supervisor_updates",
        ["project_id", "update_date", "supervisor_id"],
        unique=True,
        postgresql_where=sa.text(
            "deleted_at IS NULL AND status IN ('draft','submitted','pending_qs','pending_engineer')"
        ),
    )
    op.create_table(
        "supervisor_update_submissions",
        sa.Column(
            "update_id",
            sa.Uuid(),
            sa.ForeignKey("supervisor_updates.id", ondelete="RESTRICT"),
            primary_key=True,
        ),
        sa.Column("submission_revision", sa.Integer(), primary_key=True),
        sa.Column("requirements", JSONB(), nullable=False),
        sa.Column("evidence_ids", JSONB(), nullable=False),
        sa.Column(
            "engineer_id", sa.Uuid(), sa.ForeignKey("users.id", ondelete="RESTRICT"), nullable=False
        ),
        sa.Column("qs_id", sa.Uuid(), sa.ForeignKey("users.id", ondelete="RESTRICT")),
        *[
            column
            for stage in ("qs", "engineer")
            for column in (
                sa.Column(f"{stage}_decision", sa.String(20)),
                sa.Column(f"{stage}_comments", sa.Text()),
                sa.Column(f"{stage}_decided_at", sa.DateTime(timezone=True)),
            )
        ],
        sa.Column(
            "created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()
        ),
        sa.CheckConstraint("qs_id IS NULL OR qs_id <> engineer_id", name="distinct_reviewers"),
    )
    op.create_index(
        "ix_supervisor_update_submissions_qs_review",
        "supervisor_update_submissions",
        ["qs_id", "update_id", "submission_revision"],
    )


def downgrade() -> None:
    raise RuntimeError("Preserve independent site-progress review evidence during rollback.")
