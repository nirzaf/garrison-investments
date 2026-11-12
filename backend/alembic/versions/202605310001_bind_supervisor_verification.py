"""Bind supervisor verification to its daily report.

Revision ID: 202605310001
Revises: 202605300003
"""

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision = "202605310001"
down_revision = "202605300003"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "supervisor_updates",
        sa.Column("verified_report_id", postgresql.UUID(as_uuid=True), nullable=True),
    )
    op.create_foreign_key(
        "fk_supervisor_updates_verified_report_id",
        "supervisor_updates",
        "daily_reports",
        ["verified_report_id"],
        ["id"],
        ondelete="RESTRICT",
    )
    op.create_index(
        "ix_supervisor_updates_verified_report_id",
        "supervisor_updates",
        ["verified_report_id"],
    )
    # A draft reference alone cannot establish historical verification ownership.
    op.execute("""
        WITH candidates AS (
            SELECT u.id, array_agg(r.id) AS report_ids
            FROM supervisor_updates AS u
            JOIN daily_reports AS r
              ON r.project_id = u.project_id
             AND r.engineer_id = u.verified_by
             AND r.submitted_at >= u.verified_at
             AND r.deleted_at IS NULL
             AND r.supervisor_update_ids @> jsonb_build_array(u.id::text)
            WHERE u.status = 'verified' AND u.deleted_at IS NULL
            GROUP BY u.id
        )
        UPDATE supervisor_updates AS u
        SET verified_report_id = candidates.report_ids[1]
        FROM candidates
        WHERE u.id = candidates.id AND cardinality(candidates.report_ids) = 1
        """)


def downgrade() -> None:
    op.drop_index("ix_supervisor_updates_verified_report_id", table_name="supervisor_updates")
    op.drop_constraint(
        "fk_supervisor_updates_verified_report_id", "supervisor_updates", type_="foreignkey"
    )
    op.drop_column("supervisor_updates", "verified_report_id")
