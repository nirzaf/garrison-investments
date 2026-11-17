"""Allow reviewed support account disable and reactivation."""

from alembic import op

revision = "202605310075"
down_revision = "202605310074"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.drop_constraint(
        op.f("ck_support_business_actions_kind"), "support_business_actions", type_="check"
    )
    op.create_check_constraint(
        "kind",
        "support_business_actions",
        "kind IN ('revoke_sessions', 'unlock', 'disable', 'reactivate')",
    )


def downgrade() -> None:
    raise RuntimeError("Preserve support account lifecycle decisions and their audit records.")
