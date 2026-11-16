"""Retain inventory-owner custody evidence for HR offboarding clearance."""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "202605310028"
down_revision: str | None = "202605310027"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "hr_offboarding_custody",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column(
            "case_id",
            sa.Uuid(),
            sa.ForeignKey("hr_offboarding_cases.id", ondelete="RESTRICT"),
            nullable=False,
        ),
        sa.Column("kind", sa.String(12), nullable=False),
        sa.Column(
            "movement_id",
            sa.Uuid(),
            sa.ForeignKey("inventory_movements.id", ondelete="RESTRICT"),
            unique=True,
        ),
        sa.Column("evidence_reference", sa.String(100), nullable=False),
        sa.Column(
            "recorded_by_id",
            sa.Uuid(),
            sa.ForeignKey("users.id", ondelete="RESTRICT"),
            nullable=False,
        ),
        sa.Column(
            "recorded_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()
        ),
        sa.UniqueConstraint("case_id", "evidence_reference"),
        sa.CheckConstraint(
            "(kind = 'returned' AND movement_id IS NOT NULL) OR "
            "(kind IN ('cleared', 'waived', 'flagged') AND movement_id IS NULL)",
            name="hr_custody_kind",
        ),
    )
    op.create_index(
        "ix_hr_offboarding_custody_case_recorded",
        "hr_offboarding_custody",
        ["case_id", "recorded_at", "id"],
    )


def downgrade() -> None:
    if op.get_bind().scalar(sa.text("SELECT EXISTS (SELECT 1 FROM hr_offboarding_custody)")):
        raise RuntimeError("Cannot remove retained offboarding custody evidence.")
    op.drop_table("hr_offboarding_custody")
