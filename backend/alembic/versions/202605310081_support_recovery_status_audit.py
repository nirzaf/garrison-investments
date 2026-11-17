"""Audit scoped recovery-status reads."""

from alembic import op

revision = "202605310081"
down_revision = "202605310080"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.drop_constraint(
        op.f("ck_support_business_events_event"), "support_business_events", type_="check"
    )
    op.create_check_constraint(
        "event", "support_business_events",
        "event IN ('proposed', 'proof_denied', 'applied', 'status_read')",
    )


def downgrade() -> None:
    raise RuntimeError("Preserve audited recovery-status disclosures.")
