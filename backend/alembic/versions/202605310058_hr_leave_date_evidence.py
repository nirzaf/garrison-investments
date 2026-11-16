"""Retain independently reviewed dates for legacy approved leave."""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "202605310058"
down_revision: str | None = "202605310057"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "hr_leave_date_evidence",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column(
            "request_id", sa.Uuid(), sa.ForeignKey("hr_leave_requests.id", ondelete="RESTRICT"),
            nullable=False,
        ),
        sa.Column(
            "ledger_id", sa.Uuid(), sa.ForeignKey("hr_leave_ledger.id", ondelete="RESTRICT"),
            nullable=False,
        ),
        sa.Column("request_revision", sa.Integer(), nullable=False),
        sa.Column("detail_encrypted", sa.Text(), nullable=False),
        sa.Column("status", sa.String(20), server_default="submitted", nullable=False),
        sa.Column(
            "submitted_by_id", sa.Uuid(), sa.ForeignKey("users.id", ondelete="RESTRICT"),
            nullable=False,
        ),
        sa.Column("decided_by_id", sa.Uuid(), sa.ForeignKey("users.id", ondelete="RESTRICT")),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.Column("decided_at", sa.DateTime(timezone=True)),
        sa.CheckConstraint(
            "(status = 'submitted' AND decided_by_id IS NULL AND decided_at IS NULL) OR "
            "(status IN ('approved', 'rejected') AND decided_by_id IS NOT NULL "
            "AND decided_at IS NOT NULL AND decided_by_id <> submitted_by_id)",
            name="leave_date_evidence_decision",
        ),
    )
    # The index belongs to a new empty table.
    op.create_index(
        "ix_hr_leave_date_evidence_request_created", "hr_leave_date_evidence",
        ["request_id", "created_at", "id"],
    )


def downgrade() -> None:
    raise RuntimeError("Reviewed legacy leave date evidence must be preserved.")
