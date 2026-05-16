"""add user management fields

Revision ID: 202605160003
Revises: 202605160002
Create Date: 2026-05-16
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "202605160003"
down_revision: str | None = "202605160002"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column("users", sa.Column("designation", sa.String(length=100), nullable=True))
    op.execute(
        """
        WITH ranked_users AS (
            SELECT
                id,
                employee_code,
                ROW_NUMBER() OVER (
                    PARTITION BY employee_code
                    ORDER BY created_at ASC, id ASC
                ) AS duplicate_rank
            FROM users
            WHERE employee_code IS NOT NULL
              AND deleted_at IS NULL
        )
        UPDATE users
        SET employee_code = ranked_users.employee_code || '-' || SUBSTRING(users.id::text, 1, 8)
        FROM ranked_users
        WHERE users.id = ranked_users.id
          AND ranked_users.duplicate_rank > 1
        """
    )
    op.create_index(
        "ix_users_role_active",
        "users",
        ["role"],
        postgresql_where=sa.text("deleted_at IS NULL"),
    )
    op.create_index(
        "uq_users_employee_code_active",
        "users",
        ["employee_code"],
        unique=True,
        postgresql_where=sa.text("deleted_at IS NULL AND employee_code IS NOT NULL"),
    )


def downgrade() -> None:
    op.drop_index(
        "uq_users_employee_code_active",
        table_name="users",
        postgresql_where=sa.text("deleted_at IS NULL AND employee_code IS NOT NULL"),
    )
    op.drop_index(
        "ix_users_role_active",
        table_name="users",
        postgresql_where=sa.text("deleted_at IS NULL"),
    )
    op.drop_column("users", "designation")
