"""Allow explicitly reviewed calendar-day leave accrual proration."""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "202605310045"
down_revision: str | None = "202605310044"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

CHECK = "ck_hr_leave_accruals_leave_accrual_eligible_dates"


def upgrade() -> None:
    op.add_column(
        "hr_leave_policies",
        sa.Column(
            "prorate_by_calendar_day", sa.Boolean(), nullable=False, server_default=sa.false()
        ),
    )
    op.add_column("hr_leave_accruals", sa.Column("eligible_from", sa.Date()))
    op.add_column("hr_leave_accruals", sa.Column("eligible_through", sa.Date()))
    op.create_check_constraint(
        op.f(CHECK),
        "hr_leave_accruals",
        "(eligible_from IS NULL AND eligible_through IS NULL) OR "
        "(eligible_from IS NOT NULL AND eligible_through IS NOT NULL AND "
        "period_start <= eligible_from AND eligible_from <= eligible_through "
        "AND eligible_through <= period_end)",
        postgresql_not_valid=True,
    )


def downgrade() -> None:
    if op.get_bind().scalar(
        sa.text(
            "SELECT EXISTS (SELECT 1 FROM hr_leave_policies WHERE prorate_by_calendar_day) OR "
            "EXISTS (SELECT 1 FROM hr_leave_accruals WHERE eligible_from IS NOT NULL)"
        )
    ):
        raise RuntimeError("Cannot discard prorated leave policies or retained accrual evidence.")
    op.drop_constraint(op.f(CHECK), "hr_leave_accruals", type_="check")
    op.drop_column("hr_leave_accruals", "eligible_through")
    op.drop_column("hr_leave_accruals", "eligible_from")
    op.drop_column("hr_leave_policies", "prorate_by_calendar_day")
