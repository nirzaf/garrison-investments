"""Retain external payroll settlement events against the registered handoff."""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "202605310027"
down_revision: str | None = "202605310026"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "hr_payroll_settlement_events",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column(
            "run_id",
            sa.Uuid(),
            sa.ForeignKey("hr_payroll_exports.run_id", ondelete="RESTRICT"),
            nullable=False,
        ),
        sa.Column(
            "payment_reference",
            sa.Uuid(),
            sa.ForeignKey("hr_payroll_lines.id", ondelete="RESTRICT"),
            nullable=False,
        ),
        sa.Column("kind", sa.String(12), nullable=False),
        sa.Column("amount_encrypted", sa.Text(), nullable=False),
        sa.Column(
            "reverses_event_id",
            sa.Uuid(),
            sa.ForeignKey("hr_payroll_settlement_events.id", ondelete="RESTRICT"),
        ),
        sa.Column("occurred_on", sa.Date(), nullable=False),
        sa.Column("evidence_encrypted", sa.Text(), nullable=False),
        sa.Column("evidence_digest", sa.String(64), nullable=False, unique=True),
        sa.Column(
            "recorded_by_id",
            sa.Uuid(),
            sa.ForeignKey("users.id", ondelete="RESTRICT"),
            nullable=False,
        ),
        sa.Column(
            "recorded_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()
        ),
        sa.CheckConstraint(
            "(kind IN ('paid', 'failed') AND reverses_event_id IS NULL) OR "
            "(kind = 'reversed' AND reverses_event_id IS NOT NULL)",
            name="payroll_settlement_kind",
        ),
    )
    op.create_index(
        "ix_hr_payroll_settlement_run_recorded",
        "hr_payroll_settlement_events",
        ["run_id", "recorded_at", "id"],
    )


def downgrade() -> None:
    if op.get_bind().scalar(sa.text("SELECT EXISTS (SELECT 1 FROM hr_payroll_settlement_events)")):
        raise RuntimeError("Cannot remove retained payroll settlement events.")
    op.drop_table("hr_payroll_settlement_events")
