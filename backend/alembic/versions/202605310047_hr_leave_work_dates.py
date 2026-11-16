"""Retain the work dates reviewed on each leave request."""

from collections.abc import Sequence

import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import ARRAY

from alembic import op

revision: str = "202605310047"
down_revision: str | None = "202605310046"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column("hr_leave_requests", sa.Column("scheduled_work_dates", ARRAY(sa.Date())))


def downgrade() -> None:
    if op.get_bind().scalar(
        sa.text(
            "SELECT EXISTS (SELECT 1 FROM hr_leave_requests WHERE scheduled_work_dates IS NOT NULL)"
        )
    ):
        raise RuntimeError("Cannot discard retained leave work dates.")
    op.drop_column("hr_leave_requests", "scheduled_work_dates")
