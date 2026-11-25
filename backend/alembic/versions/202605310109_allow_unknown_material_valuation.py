"""Allow material requests to represent an unknown estimated cost."""

import sqlalchemy as sa

from alembic import op

revision = "202605310109"
down_revision = "202605310108"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.alter_column(
        "material_requests",
        "total_estimated_cost",
        existing_type=sa.Numeric(14, 2),
        existing_nullable=False,
        nullable=True,
        existing_server_default=sa.text("0"),
        server_default=None,
    )


def downgrade() -> None:
    connection = op.get_bind()
    has_unknown_values = connection.scalar(
        sa.text(
            "SELECT EXISTS "
            "(SELECT 1 FROM material_requests WHERE total_estimated_cost IS NULL)"
        )
    )
    if has_unknown_values:
        raise RuntimeError(
            "Cannot restore NOT NULL while material requests retain unknown valuations. "
            "Keep the compatible nullable schema during application rollback."
        )
    op.alter_column(
        "material_requests",
        "total_estimated_cost",
        existing_type=sa.Numeric(14, 2),
        existing_nullable=True,
        nullable=False,
        server_default=sa.text("0"),
    )
