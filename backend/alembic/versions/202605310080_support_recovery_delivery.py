"""Track recovery transport acceptance and interrupted attempts."""

import sqlalchemy as sa

from alembic import op

revision = "202605310080"
down_revision = "202605310079"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "support_recovery_deliveries",
        sa.Column("dispatch_started_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.add_column(
        "support_recovery_deliveries",
        sa.Column("dispatch_finished_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.drop_constraint(
        op.f("ck_support_recovery_deliveries_status"), "support_recovery_deliveries", type_="check"
    )
    op.create_check_constraint(
        "status", "support_recovery_deliveries",
        "status IN ('pending','dispatching','accepted','unknown','cancelled')",
    )


def downgrade() -> None:
    raise RuntimeError("Preserve support recovery delivery history.")
