"""Record independently reviewed separation settlement evidence."""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "202605310032"
down_revision: str | None = "202605310031"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "hr_separation_settlements",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column(
            "case_id",
            sa.Uuid(),
            sa.ForeignKey("hr_offboarding_cases.id", ondelete="RESTRICT"),
            nullable=False,
        ),
        sa.Column("outcome", sa.String(16), nullable=False),
        sa.Column("evidence_reference", sa.String(100), nullable=False),
        sa.Column("status", sa.String(16), nullable=False, server_default="proposed"),
        sa.Column(
            "proposed_by_id",
            sa.Uuid(),
            sa.ForeignKey("users.id", ondelete="RESTRICT"),
            nullable=False,
        ),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
        sa.Column("reviewed_by_id", sa.Uuid(), sa.ForeignKey("users.id", ondelete="RESTRICT")),
        sa.Column("reviewed_at", sa.DateTime(timezone=True)),
        sa.Column("review_reference", sa.String(100)),
        sa.UniqueConstraint("case_id", "evidence_reference"),
        sa.CheckConstraint(
            "outcome IN ('outstanding', 'settled', 'nothing_due')",
            name="separation_settlement_outcome",
        ),
        sa.CheckConstraint(
            "(status = 'proposed' AND reviewed_by_id IS NULL AND reviewed_at IS NULL "
            "AND review_reference IS NULL) OR "
            "(status IN ('approved', 'rejected') AND reviewed_by_id IS NOT NULL "
            "AND reviewed_by_id <> proposed_by_id AND reviewed_at IS NOT NULL "
            "AND review_reference IS NOT NULL)",
            name="separation_settlement_review",
        ),
    )
    op.create_index(
        "ix_hr_separation_settlements_case_created",
        "hr_separation_settlements",
        ["case_id", "created_at", "id"],
    )

    op.create_index(
        "uq_hr_separation_settlements_open",
        "hr_separation_settlements",
        ["case_id"],
        unique=True,
        postgresql_where=sa.text("status = 'proposed'"),
    )


def downgrade() -> None:
    if op.get_bind().scalar(sa.text("SELECT EXISTS (SELECT 1 FROM hr_separation_settlements)")):
        raise RuntimeError("Cannot remove retained separation settlement evidence.")
    op.drop_table("hr_separation_settlements")
