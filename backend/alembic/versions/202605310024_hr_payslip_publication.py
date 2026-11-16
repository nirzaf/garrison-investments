"""Record explicit release of an approved payroll snapshot to employees."""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "202605310024"
down_revision: str | None = "202605310023"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "hr_payslip_publications",
        sa.Column(
            "run_id",
            sa.Uuid(),
            sa.ForeignKey("hr_payroll_runs.id", ondelete="RESTRICT"),
            primary_key=True,
        ),
        sa.Column(
            "published_by_id",
            sa.Uuid(),
            sa.ForeignKey("users.id", ondelete="RESTRICT"),
            nullable=False,
        ),
        sa.Column("snapshot_digest", sa.String(64), nullable=False),
        sa.Column(
            "published_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()
        ),
    )


def downgrade() -> None:
    if op.get_bind().scalar(sa.text("SELECT EXISTS (SELECT 1 FROM hr_payslip_publications)")):
        raise RuntimeError("Cannot remove retained payslip publication receipts.")
    op.drop_table("hr_payslip_publications")
