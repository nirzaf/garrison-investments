"""Bind and queue reviewed business password recovery."""

import sqlalchemy as sa

from alembic import op

revision = "202605310079"
down_revision = "202605310078"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "support_business_actions",
        sa.Column("recovery_destination_digest", sa.String(64), nullable=True),
    )
    op.drop_constraint(
        op.f("ck_support_business_actions_kind"), "support_business_actions", type_="check"
    )
    op.create_check_constraint(
        "kind",
        "support_business_actions",
        "(kind IN ('revoke_sessions','unlock','disable','reactivate')"
        " AND permission_key IS NULL AND permission_session_id IS NULL"
        " AND recovery_destination_digest IS NULL)"
        " OR (kind = 'permission_view' AND permission_key IS NOT NULL"
        " AND permission_session_id IS NOT NULL AND recovery_destination_digest IS NULL)"
        " OR (kind = 'recover' AND permission_key IS NULL AND permission_session_id IS NULL"
        " AND recovery_destination_digest IS NOT NULL)",
    )
    op.create_table(
        "support_recovery_deliveries",
        sa.Column(
            "action_id",
            sa.Uuid(),
            sa.ForeignKey("support_business_actions.id", ondelete="RESTRICT"),
            primary_key=True,
        ),
        sa.Column(
            "challenge_id",
            sa.Uuid(),
            sa.ForeignKey("auth_otp_challenges.id", ondelete="RESTRICT"),
            nullable=False,
            unique=True,
        ),
        sa.Column("status", sa.String(16), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
        sa.CheckConstraint("status IN ('pending','accepted')", name="status"),
    )


def downgrade() -> None:
    raise RuntimeError("Preserve support recovery issuance and queued delivery evidence.")
