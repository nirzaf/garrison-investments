"""Allow a reviewed business menu projection."""

from alembic import op

revision = "202605310083"
down_revision = "202605310082"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.drop_constraint(
        op.f("ck_support_business_actions_kind"), "support_business_actions", type_="check"
    )
    op.create_check_constraint(
        "kind",
        "support_business_actions",
        "(kind IN ('revoke_sessions','unlock','disable','reactivate')"
        " AND permission_key IS NULL AND permission_session_id IS NULL"
        " AND recovery_destination_digest IS NULL AND source_event_id IS NULL)"
        " OR (kind = 'permission_view' AND permission_key IS NOT NULL"
        " AND permission_session_id IS NOT NULL AND recovery_destination_digest IS NULL"
        " AND source_event_id IS NULL)"
        " OR (kind = 'recover' AND permission_key IS NULL AND permission_session_id IS NULL"
        " AND recovery_destination_digest IS NOT NULL AND source_event_id IS NULL)"
        " OR (kind = 'request_summary' AND permission_key IS NULL"
        " AND permission_session_id IS NOT NULL AND recovery_destination_digest IS NULL"
        " AND source_event_id IS NOT NULL)"
        " OR (kind = 'navigation_view' AND permission_key IS NULL"
        " AND permission_session_id IS NOT NULL AND recovery_destination_digest IS NULL"
        " AND source_event_id IS NULL)",
    )


def downgrade() -> None:
    raise RuntimeError("Preserve reviewed navigation view evidence.")
