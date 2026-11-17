"""Bind a support view to one independently linked request event."""

import sqlalchemy as sa

from alembic import op

revision = "202605310082"
down_revision = "202605310081"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "support_business_actions", sa.Column("source_event_id", sa.Uuid(), nullable=True)
    )
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
        " AND source_event_id IS NOT NULL)",
    )


def downgrade() -> None:
    raise RuntimeError("Preserve the request-summary review and disclosure binding.")
