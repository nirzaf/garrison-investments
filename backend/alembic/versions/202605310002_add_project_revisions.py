"""Add revisions for project and task edits.

Revision ID: 202605310002
Revises: 202605310001
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "202605310002"
down_revision: str | None = "202605310001"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    for table in ("projects", "project_tasks"):
        op.add_column(
            table, sa.Column("revision", sa.Integer(), server_default="1", nullable=False)
        )


def downgrade() -> None:
    for table in ("project_tasks", "projects"):
        op.drop_column(table, "revision")
