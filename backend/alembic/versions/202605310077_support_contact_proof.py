"""Bind offline owner-contact attestations to reviewed business proofs."""

import sqlalchemy as sa

from alembic import op

revision = "202605310077"
down_revision = "202605310076"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("support_business_proofs", sa.Column("contact_ref", sa.Uuid(), nullable=True))


def downgrade() -> None:
    raise RuntimeError("Preserve the proof binding for protected owner-contact attestations.")
