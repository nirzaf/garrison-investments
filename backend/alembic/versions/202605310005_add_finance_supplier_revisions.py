"""Add edit revisions to invoices and suppliers.

Revision ID: 202605310005
Revises: 202605310004
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "202605310005"
down_revision: str | None = "202605310004"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    for table in ("invoices", "suppliers"):
        op.add_column(
            table, sa.Column("revision", sa.Integer(), server_default="1", nullable=False)
        )


def downgrade() -> None:
    for table in ("suppliers", "invoices"):
        op.drop_column(table, "revision")
