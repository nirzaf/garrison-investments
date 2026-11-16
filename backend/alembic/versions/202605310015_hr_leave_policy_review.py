"""Add effective dates and independent review to leave policies."""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "202605310015"
down_revision: str | None = "202605310014"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

TABLE = "hr_leave_policies"


def upgrade() -> None:
    op.add_column(
        TABLE, sa.Column("status", sa.String(16), nullable=False, server_default="legacy")
    )
    op.alter_column(TABLE, "status", server_default="draft")
    op.add_column(TABLE, sa.Column("effective_from", sa.Date()))
    op.add_column(TABLE, sa.Column("effective_to", sa.Date()))
    op.add_column(TABLE, sa.Column("created_by_id", sa.Uuid()))
    op.add_column(TABLE, sa.Column("rejection_reason", sa.String(500)))
    op.create_foreign_key(
        "fk_hr_leave_policy_creator",
        TABLE,
        "users",
        ["created_by_id"],
        ["id"],
        ondelete="SET NULL",
        postgresql_not_valid=True,
    )
    op.create_check_constraint(
        "hr_leave_policy_status",
        TABLE,
        "status IN ('legacy', 'draft', 'approved', 'rejected')",
        postgresql_not_valid=True,
    )
    op.create_check_constraint(
        "hr_leave_policy_effective_window",
        TABLE,
        "status = 'legacy' OR (effective_from IS NOT NULL AND effective_to IS NOT NULL "
        "AND effective_from <= effective_to)",
        postgresql_not_valid=True,
    )


def downgrade() -> None:
    op.drop_constraint("hr_leave_policy_effective_window", TABLE, type_="check")
    op.drop_constraint("hr_leave_policy_status", TABLE, type_="check")
    op.drop_constraint("fk_hr_leave_policy_creator", TABLE, type_="foreignkey")
    for column in ("rejection_reason", "created_by_id", "effective_to", "effective_from", "status"):
        op.drop_column(TABLE, column)
