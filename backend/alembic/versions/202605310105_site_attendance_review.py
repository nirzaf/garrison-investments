"""Bind Site Engineer and HR attendance decisions to an immutable site submission."""

import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import JSONB

from alembic import op

revision = "202605310105"
down_revision = "202605310104"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("hr_attendance_entries", sa.Column("site_submission_revision", sa.Integer()))
    op.create_table(
        "hr_site_attendance_submissions",
        sa.Column(
            "entry_id",
            sa.Uuid(),
            sa.ForeignKey("hr_attendance_entries.id", ondelete="RESTRICT"),
            primary_key=True,
        ),
        sa.Column("submission_revision", sa.Integer(), primary_key=True),
        sa.Column("requirements", JSONB(), nullable=False),
        *[
            sa.Column(
                column,
                sa.Uuid(),
                sa.ForeignKey("users.id", ondelete="RESTRICT"),
                nullable=column == "hr_id",
            )
            for column in ("submitted_by", "engineer_id", "hr_id")
        ],
        *[
            column
            for stage in ("engineer", "hr")
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
        sa.CheckConstraint(
            "engineer_id <> submitted_by AND (hr_id IS NULL OR "
            "(hr_id <> engineer_id AND hr_id <> submitted_by))",
            name="site_attendance_separation",
        ),
    )
    op.create_index(
        "ix_hr_site_attendance_project_date",
        "hr_attendance_entries",
        ["project_id", "work_date", "id"],
        postgresql_where=sa.text("source = 'site'"),
    )


def downgrade() -> None:
    raise RuntimeError(
        "Preserve site attendance and its recorded decisions on application rollback."
    )
