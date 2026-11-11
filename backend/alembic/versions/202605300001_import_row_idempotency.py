"""import row idempotency for inventory movements

Revision ID: 202605300001
Revises: 202605290002
Create Date: 2026-05-30
"""

from collections.abc import Sequence

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision: str = "202605300001"
down_revision: str | None = "202605290002"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "inventory_movements",
        sa.Column("import_batch_id", postgresql.UUID(as_uuid=True), nullable=True),
    )
    op.add_column(
        "inventory_movements",
        sa.Column("import_row_index", sa.Integer(), nullable=True),
    )
    # Partial so the vast majority of movements (manual, report-driven) stay unconstrained.
    op.create_index(
        "uq_movements_import_row",
        "inventory_movements",
        ["import_batch_id", "import_row_index"],
        unique=True,
        postgresql_where=sa.text("import_batch_id IS NOT NULL"),
    )


def downgrade() -> None:
    op.drop_index("uq_movements_import_row", table_name="inventory_movements")
    op.drop_column("inventory_movements", "import_row_index")
    op.drop_column("inventory_movements", "import_batch_id")