"""Repair derived reservation balances, then validate the stock balance checks.

C4 left ``reserved_quantity`` holding the full line quantity after part of it had
been issued, and left reservations behind on issued/cancelled requests. Both columns
repaired here are derived from ``quantity``/``issued_quantity`` and the movement log,
so the recompute inventories nothing and discards nothing.

``VALIDATE CONSTRAINT`` aborts (and rolls back) if a historical ``on_hand_qty`` is
still negative: that balance cannot be derived from any record, so an operator must
reconcile it first with ``scripts/report_inventory_reservation_drift.py``.

Revision ID: 202605300003
Revises: 202605300002
Create Date: 2026-05-30
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import context, op

revision: str = "202605300003"
down_revision: str | None = "202605300002"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

TABLE = "inventory_location_stock"
ON_HAND_CHECK = "ck_inventory_location_stock_on_hand_nonnegative"
RESERVED_CHECK = "ck_inventory_location_stock_reserved_nonnegative"

# A line reserves only what is reserved and NOT yet issued; closed requests hold nothing.
LINE_REPAIR = """
WITH desired AS (
    SELECT line.id,
           CASE
               WHEN request.status IN ('reserved', 'partially_issued')
                   THEN GREATEST(0, line.quantity - line.issued_quantity)
               ELSE 0
           END AS reserved_quantity
    FROM material_request_lines AS line
    JOIN material_requests AS request ON request.id = line.request_id
    WHERE line.deleted_at IS NULL
      AND request.deleted_at IS NULL
)
UPDATE material_request_lines AS line
SET reserved_quantity = desired.reserved_quantity
FROM desired
WHERE line.id = desired.id
  AND line.reserved_quantity IS DISTINCT FROM desired.reserved_quantity
"""

STOCK_REPAIR = """
WITH request_reservations AS (
    SELECT line.item_id,
           request.from_location_id AS location_id,
           SUM(GREATEST(0, line.quantity - line.issued_quantity)) AS qty
    FROM material_request_lines AS line
    JOIN material_requests AS request ON request.id = line.request_id
    WHERE line.deleted_at IS NULL
      AND request.deleted_at IS NULL
      AND request.status IN ('reserved', 'partially_issued')
      AND request.from_location_id IS NOT NULL
    GROUP BY line.item_id, request.from_location_id
),
manual_reservations AS (
    -- Reserves raised outside a material request are real claims with no line to describe them.
    SELECT item_id, from_location_id AS location_id, SUM(quantity) AS qty
    FROM inventory_movements
    WHERE movement_type = 'reserve'
      AND reference_type IS DISTINCT FROM 'material_request'
      AND deleted_at IS NULL
      AND from_location_id IS NOT NULL
    GROUP BY item_id, from_location_id
),
desired AS (
    SELECT stock.id,
           GREATEST(0, COALESCE(requests.qty, 0) + COALESCE(manual.qty, 0)) AS reserved_qty
    FROM inventory_location_stock AS stock
    LEFT JOIN request_reservations AS requests
        ON requests.item_id = stock.item_id AND requests.location_id = stock.location_id
    LEFT JOIN manual_reservations AS manual
        ON manual.item_id = stock.item_id AND manual.location_id = stock.location_id
    WHERE stock.deleted_at IS NULL
)
UPDATE inventory_location_stock AS stock
SET reserved_qty = desired.reserved_qty
FROM desired
WHERE stock.id = desired.id
  AND stock.reserved_qty IS DISTINCT FROM desired.reserved_qty
"""

REPAIR_STATEMENTS = (LINE_REPAIR, STOCK_REPAIR)
REPAIR_TARGETS = ("material_request_lines", TABLE)

VALIDATE_STATEMENTS = (
    f"ALTER TABLE {TABLE} VALIDATE CONSTRAINT {ON_HAND_CHECK}",
    f"ALTER TABLE {TABLE} VALIDATE CONSTRAINT {RESERVED_CHECK}",
)


def upgrade() -> None:
    for target, statement in zip(REPAIR_TARGETS, REPAIR_STATEMENTS, strict=True):
        if context.is_offline_mode():
            op.execute(statement)
        else:
            # Only differing rows are touched, so rowcount is the drift that existed before.
            recomputed = op.get_bind().execute(sa.text(statement)).rowcount
            print(f"repair_inventory_reservations: {target} rows_recomputed={recomputed}")
    for statement in VALIDATE_STATEMENTS:
        op.execute(statement)


def downgrade() -> None:
    # The recompute is derived, not reversible; restore the unvalidated guards that
    # 202605300002 leaves behind so the schema matches the previous revision exactly.
    op.execute(f"ALTER TABLE {TABLE} DROP CONSTRAINT {RESERVED_CHECK}")
    op.execute(f"ALTER TABLE {TABLE} DROP CONSTRAINT {ON_HAND_CHECK}")
    op.execute(
        f"ALTER TABLE {TABLE} ADD CONSTRAINT {ON_HAND_CHECK} CHECK (on_hand_qty >= 0) NOT VALID"
    )
    op.execute(
        f"ALTER TABLE {TABLE} ADD CONSTRAINT {RESERVED_CHECK} CHECK (reserved_qty >= 0) NOT VALID"
    )
