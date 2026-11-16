"""Validate the updated custody constraint against retained inventory receipts."""

from collections.abc import Sequence

from alembic import op

revision: str = "202605310031"
down_revision: str | None = "202605310030"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute(
        "ALTER TABLE hr_offboarding_custody "
        "VALIDATE CONSTRAINT ck_hr_offboarding_custody_hr_custody_area_kind"
    )


def downgrade() -> None:
    # The preceding revision owns the constraint.
    pass
