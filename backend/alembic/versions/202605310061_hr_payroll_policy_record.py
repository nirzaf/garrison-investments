"""Retain a controlled business-policy reference on payroll policies."""

from sqlalchemy import Column
from sqlalchemy.dialects.postgresql import JSONB

from alembic import op

revision = "202605310061"
down_revision = "202605310060"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("hr_payroll_policies", Column("controlled_record", JSONB(), nullable=True))


def downgrade() -> None:
    raise RuntimeError("Controlled payroll policy references must be preserved.")
