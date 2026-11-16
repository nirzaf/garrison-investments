"""Add independent review to compensation terms while preserving existing history."""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "202605310050"
down_revision: str | None = "202605310049"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

TABLE = "hr_compensation_terms"
CHECK = "ck_hr_compensation_terms_hr_compensation_approval_status"


def upgrade() -> None:
    op.add_column(
        TABLE,
        sa.Column("approval_status", sa.String(20), nullable=False, server_default="approved"),
    )
    op.add_column(TABLE, sa.Column("proposed_by_id", sa.Uuid()))
    op.add_column(TABLE, sa.Column("rejection_reason_encrypted", sa.Text()))
    op.create_foreign_key(
        "fk_hr_compensation_proposer",
        TABLE,
        "users",
        ["proposed_by_id"],
        ["id"],
        ondelete="SET NULL",
        postgresql_not_valid=True,
    )
    op.create_check_constraint(
        op.f(CHECK),
        TABLE,
        "approval_status IN ('proposed', 'approved', 'rejected')",
        postgresql_not_valid=True,
    )


def downgrade() -> None:
    if op.get_bind().scalar(
        sa.text(
            "SELECT EXISTS (SELECT 1 FROM hr_compensation_terms "
            "WHERE approval_status <> 'approved' OR proposed_by_id IS NOT NULL "
            "OR rejection_reason_encrypted IS NOT NULL)"
        )
    ):
        raise RuntimeError("Cannot discard retained compensation review history.")
    op.drop_constraint(op.f(CHECK), TABLE, type_="check")
    op.drop_constraint("fk_hr_compensation_proposer", TABLE, type_="foreignkey")
    op.drop_column(TABLE, "rejection_reason_encrypted")
    op.drop_column(TABLE, "proposed_by_id")
    op.drop_column(TABLE, "approval_status")
