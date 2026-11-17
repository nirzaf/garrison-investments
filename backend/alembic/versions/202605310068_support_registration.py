"""Add reviewed two-device support registration and recovery."""

import sqlalchemy as sa

from alembic import op

revision = "202605310068"
down_revision = "202605310067"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.drop_constraint(
        op.f("ck_support_custody_actions_bounded_action"), "support_custody_actions", type_="check"
    )
    op.create_check_constraint(
        "bounded_action",
        "support_custody_actions",
        "(kind IN ('suspend', 'enroll', 'recover') AND capability IS NULL AND enable IS NULL) OR "
        "(kind = 'grant_change' AND capability IS NOT NULL AND "
        "capability IN ('cases.manage', 'logs.runtime') AND enable IS NOT NULL)",
    )
    op.drop_constraint(
        op.f("ck_support_suspension_events_action"), "support_custody_events", type_="check"
    )
    op.create_check_constraint(
        "action",
        "support_custody_events",
        "action IN ('proposed', 'reviewed', 'executed', 'proof_denied', 'floor_denied', "
        "'passkey_added', 'operator_activated', 'registration_denied')",
    )
    op.alter_column("support_custody_events", "action", type_=sa.String(24))
    op.create_table(
        "support_registrations",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column(
            "custody_action_id",
            sa.Uuid(),
            sa.ForeignKey("support_custody_actions.id", ondelete="RESTRICT"),
            nullable=False,
        ),
        sa.Column("invitation_hash", sa.String(64), unique=True, nullable=False),
        sa.Column("grant_epoch", sa.BigInteger(), nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("challenge", sa.LargeBinary(32)),
        sa.Column("challenge_expires_at", sa.DateTime(timezone=True)),
        sa.Column("consumed_at", sa.DateTime(timezone=True)),
        sa.CheckConstraint("grant_epoch > 0", name="grant_epoch"),
        sa.CheckConstraint(
            "(challenge IS NULL) = (challenge_expires_at IS NULL)"
            " AND (challenge IS NULL OR octet_length(challenge) = 32)",
            name="challenge",
        ),
    )


def downgrade() -> None:
    raise RuntimeError("Preserve support registration and custody evidence during rollback.")
