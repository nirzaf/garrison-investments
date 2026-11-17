"""Require an independently verified email code after a support passkey."""

import sqlalchemy as sa

from alembic import op

revision = "202605310089"
down_revision = "202605310088"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "support_email_otps",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column(
            "login_challenge_id",
            sa.Uuid(),
            sa.ForeignKey("support_login_challenges.id", ondelete="RESTRICT"),
            nullable=False,
            unique=True,
        ),
        sa.Column("code_digest", sa.String(64), nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("attempts", sa.Integer(), nullable=False),
        sa.Column("accepted_at", sa.DateTime(timezone=True)),
        sa.Column("used_at", sa.DateTime(timezone=True)),
        sa.CheckConstraint("attempts BETWEEN 0 AND 5", name="attempts"),
    )


def downgrade() -> None:
    raise RuntimeError("Preserve support email verification records.")
