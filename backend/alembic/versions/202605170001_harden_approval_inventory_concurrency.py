"""harden approval and inventory concurrency

Revision ID: 202605170001
Revises: 202605160016
Create Date: 2026-05-17
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "202605170001"
down_revision: str | None = "202605160016"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute("CREATE SEQUENCE IF NOT EXISTS material_request_number_seq START WITH 1")
    op.execute(
        """
        SELECT setval(
            'material_request_number_seq',
            GREATEST(
                COALESCE(
                    (
                        SELECT MAX(
                            NULLIF(regexp_replace(request_number, '\\D', '', 'g'), '')::bigint
                        )
                        FROM material_requests
                    ),
                    0
                ),
                1
            ),
            true
        )
        """
    )
    op.create_index(
        "uq_approvals_open_request",
        "approvals",
        ["request_type", "request_id"],
        unique=True,
        postgresql_where=sa.text(
            "deleted_at IS NULL AND status IN ('pending', 'delegated', 'escalated')"
        ),
    )


def downgrade() -> None:
    op.drop_index("uq_approvals_open_request", table_name="approvals")
    op.execute("DROP SEQUENCE IF EXISTS material_request_number_seq")
