"""Validate the date range recorded for prorated leave credits."""

from collections.abc import Sequence

from alembic import op

revision: str = "202605310046"
down_revision: str | None = "202605310045"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute(
        "ALTER TABLE hr_leave_accruals VALIDATE CONSTRAINT "
        "ck_hr_leave_accruals_leave_accrual_eligible_dates"
    )


def downgrade() -> None:
    # Validation does not change write enforcement.
    pass
