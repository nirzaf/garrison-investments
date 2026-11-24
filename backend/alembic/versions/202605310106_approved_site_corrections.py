"""Link approved site workflow corrections to their original records."""

import sqlalchemy as sa

from alembic import op

revision = "202605310106"
down_revision = "202605310105"
branch_labels = None
depends_on = None


def upgrade() -> None:
    for table in ("supervisor_updates", "material_requests"):
        op.add_column(table, sa.Column("previous_id", sa.Uuid(), nullable=True))
        op.create_foreign_key(
            f"fk_{table}_previous_id", table, table, ["previous_id"], ["id"], ondelete="RESTRICT"
        )
        op.create_index(
            f"uq_{table}_previous_id",
            table,
            ["previous_id"],
            unique=True,
            postgresql_where=sa.text("previous_id IS NOT NULL"),
        )


def downgrade() -> None:
    raise RuntimeError("Preserve the approved site correction history.")
