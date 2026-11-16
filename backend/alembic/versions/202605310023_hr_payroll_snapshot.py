"""Retain encrypted payroll run snapshots for independent approval."""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "202605310023"
down_revision: str | None = "202605310022"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column("hr_payroll_runs", sa.Column("snapshot_encrypted", sa.Text(), nullable=True))


def downgrade() -> None:
    if op.get_bind().scalar(
        sa.text(
            "SELECT EXISTS (SELECT 1 FROM hr_payroll_runs WHERE snapshot_encrypted IS NOT NULL)"
        )
    ):
        raise RuntimeError("Cannot discard retained payroll snapshots.")
    op.drop_column("hr_payroll_runs", "snapshot_encrypted")
