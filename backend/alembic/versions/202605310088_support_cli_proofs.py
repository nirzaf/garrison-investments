"""Relay a sealed WebAuthn assertion to the original technical CLI session."""

import sqlalchemy as sa

from alembic import op

revision = "202605310088"
down_revision = "202605310087"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "support_cli_proofs",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("proof_id", sa.Uuid(), nullable=False, unique=True),
        sa.Column(
            "session_id",
            sa.Uuid(),
            sa.ForeignKey("support_sessions.id", ondelete="RESTRICT"),
            nullable=False,
        ),
        sa.Column("pairing_hash", sa.String(64), nullable=False),
        sa.Column("public_key", sa.String(512), nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("sealed", sa.String(32768)),
        sa.Column("taken_at", sa.DateTime(timezone=True)),
        sa.CheckConstraint(
            "(sealed IS NULL) OR (taken_at IS NULL AND length(sealed) BETWEEN 1 AND 32768)",
            name="sealed_state",
        ),
    )


def downgrade() -> None:
    raise RuntimeError("Preserve reviewed tool handoff records.")
