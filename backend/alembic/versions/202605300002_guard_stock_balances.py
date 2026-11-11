"""Enforce nonnegative stock balances on new writes during reconciliation."""

from collections.abc import Sequence

from alembic import op

revision: str = "202605300002"
down_revision: str | None = "202605300001"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

TABLE = "inventory_location_stock"
ON_HAND_CHECK = "ck_inventory_location_stock_on_hand_nonnegative"
RESERVED_CHECK = "ck_inventory_location_stock_reserved_nonnegative"


def upgrade() -> None:
    # Existing rows stay available for review without inventing or dropping quantities.
    op.create_check_constraint(
        op.f(ON_HAND_CHECK), TABLE, "on_hand_qty >= 0", postgresql_not_valid=True
    )
    op.create_check_constraint(
        op.f(RESERVED_CHECK), TABLE, "reserved_qty >= 0", postgresql_not_valid=True
    )


def downgrade() -> None:
    op.drop_constraint(op.f(RESERVED_CHECK), TABLE, type_="check")
    op.drop_constraint(op.f(ON_HAND_CHECK), TABLE, type_="check")
