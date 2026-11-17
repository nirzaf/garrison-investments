"""Extend reviewed custody decisions to bounded support capability changes."""

import sqlalchemy as sa

from alembic import op

revision = "202605310067"
down_revision = "202605310066"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.rename_table("support_suspensions", "support_custody_actions")
    op.rename_table("support_suspension_proofs", "support_custody_proofs")
    op.rename_table("support_suspension_events", "support_custody_events")
    for table in ("support_custody_proofs", "support_custody_events"):
        op.alter_column(table, "suspension_id", new_column_name="custody_action_id")
    op.add_column(
        "support_custody_actions",
        sa.Column("kind", sa.String(16), server_default="suspend", nullable=False),
    )
    op.add_column("support_custody_actions", sa.Column("capability", sa.String(32)))
    op.add_column("support_custody_actions", sa.Column("enable", sa.Boolean()))
    op.create_check_constraint(
        "bounded_action",
        "support_custody_actions",
        "(kind = 'suspend' AND capability IS NULL AND enable IS NULL) OR "
        "(kind = 'grant_change' AND capability IS NOT NULL AND "
        "capability IN ('cases.manage', 'logs.runtime') AND enable IS NOT NULL)",
    )


def downgrade() -> None:
    raise RuntimeError("Preserve reviewed support actions and custody evidence during rollback.")
