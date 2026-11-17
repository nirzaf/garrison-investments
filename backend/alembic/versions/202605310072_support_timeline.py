"""Record scoped support timeline reads in the existing append-only case audit."""

from alembic import op

revision = "202605310072"
down_revision = "202605310071"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.drop_constraint(op.f("ck_support_case_events_action"), "support_case_events", type_="check")
    op.create_check_constraint(
        "action",
        "support_case_events",
        "action IN ('created', 'read', 'transitioned', 'timeline_read')",
    )


def downgrade() -> None:
    raise RuntimeError("Preserve support timeline read evidence during rollback.")
