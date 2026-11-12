# inventory_location_stock

On-hand and reserved balances for each item and storage location.

[Schema index](README.md) · [SQLAlchemy model](../../backend/app/models/inventory.py)

The [inventory service](../../backend/app/services/inventory_service.py) maintains balances when it reserves, issues, returns, or adjusts stock. The [reservation repair migration](../../backend/alembic/versions/202605300003_repair_inventory_reservations.py) reconciles existing balances and validates the nonnegative checks.

## Columns

| Column | PostgreSQL type | Nullable | Server default |
| --- | --- | --- | --- |
| `id` | `uuid` | No | `uuid_generate_v4()` |
| `item_id` | `uuid` | No | — |
| `location_id` | `uuid` | No | — |
| `on_hand_qty` | `numeric(14, 3)` | No | `0` |
| `reserved_qty` | `numeric(14, 3)` | No | `0` |
| `created_at` | `timestamptz` | No | `now()` |
| `updated_at` | `timestamptz` | No | `now()` |
| `deleted_at` | `timestamptz` | Yes | — |

## Keys and constraints

| Constraint | Rule |
| --- | --- |
| `pk_inventory_location_stock` | `PRIMARY KEY (id)` |
| `uq_inventory_stock_item_location` | `UNIQUE (item_id, location_id)` |
| `ck_inventory_location_stock_on_hand_nonnegative` | `CHECK ((on_hand_qty >= 0))` |
| `ck_inventory_location_stock_reserved_nonnegative` | `CHECK ((reserved_qty >= 0))` |

## Foreign keys

| Constraint | Local columns | Referenced columns | On delete |
| --- | --- | --- | --- |
| `fk_inventory_location_stock_item_id_inventory_items` | `(item_id)` | [`inventory_items(id)`](inventory_items.md) | `CASCADE` |
| `fk_inventory_location_stock_location_id_storage_locations` | `(location_id)` | [`storage_locations(id)`](storage_locations.md) | `CASCADE` |

## Indexes

| Index | Method | Keys | Unique | Predicate |
| --- | --- | --- | --- | --- |
| `idx_inventory_stock_item` | `btree` | `item_id` | No | — |
| `idx_inventory_stock_location` | `btree` | `location_id` | No | — |
