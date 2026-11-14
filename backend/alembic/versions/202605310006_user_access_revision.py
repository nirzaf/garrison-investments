"""Add user access revisions for session invalidation.

Revision ID: 202605310006
Revises: 202605310005
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "202605310006"
down_revision: str | None = "202605310005"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "users", sa.Column("access_revision", sa.Integer(), server_default="0", nullable=False)
    )


def downgrade() -> None:
    op.drop_column("users", "access_revision")
