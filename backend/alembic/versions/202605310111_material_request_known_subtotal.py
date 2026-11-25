"""Keep a non-null known subtotal for incompletely valued material requests."""

import sqlalchemy as sa

from alembic import op

revision = "202605310111"
down_revision = "202605310110"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # Earlier releases stored NULL for unknown valuation. Preserve the known
    # portion from the request's persisted line-price snapshots; the immutable
    # submission marker controls whether the API may present this as a total.
    op.execute(
        sa.text(
            "UPDATE material_requests AS r "
            "SET total_estimated_cost = COALESCE(( "
            "  SELECT SUM(l.unit_cost * l.quantity) "
            "  FROM material_request_lines AS l "
            "  WHERE l.request_id = r.id AND l.deleted_at IS NULL "
            "    AND l.unit_cost IS NOT NULL "
            "), 0) "
            "WHERE r.total_estimated_cost IS NULL"
        )
    )
    op.alter_column(
        "material_requests",
        "total_estimated_cost",
        existing_type=sa.Numeric(14, 2),
        existing_nullable=True,
        nullable=False,
        server_default=sa.text("0"),
    )


def downgrade() -> None:
    # Keep the known subtotal values on downgrade. Nullable storage remains a
    # compatible superset for the previous application version.
    op.alter_column(
        "material_requests",
        "total_estimated_cost",
        existing_type=sa.Numeric(14, 2),
        existing_nullable=False,
        nullable=True,
        server_default=None,
    )
