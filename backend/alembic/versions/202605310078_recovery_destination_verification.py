"""Retain real email OTP evidence for reviewed business recovery."""

import sqlalchemy as sa

from alembic import op

revision = "202605310078"
down_revision = "202605310077"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "auth_otp_challenges", sa.Column("delivery_email_digest", sa.String(64), nullable=True)
    )
    op.add_column("users", sa.Column("recovery_email_digest", sa.String(64), nullable=True))
    op.add_column(
        "users", sa.Column("recovery_email_verified_at", sa.DateTime(timezone=True), nullable=True)
    )


def downgrade() -> None:
    raise RuntimeError("Preserve verified recovery destination evidence.")
