"""Require explicit treatment of active HR Executive accounts before retirement.

Revision ID: 202605310011
Revises: 202605310010
"""

from collections.abc import Sequence

from alembic import op

revision: str = "202605310011"
down_revision: str | None = "202605310010"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute("""
        DO $$
        BEGIN
            IF EXISTS (
                SELECT 1 FROM users
                WHERE role = 'hr_executive' AND is_active AND deleted_at IS NULL
            ) THEN
                RAISE EXCEPTION 'Resolve active HR Executive accounts before release.';
            END IF;
        END
        $$;
    """)


def downgrade() -> None:
    # No user was changed by this migration.
    pass
