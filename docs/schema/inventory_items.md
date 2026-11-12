# inventory_items

Inventory catalog, units, thresholds, unit cost, and optional supplier.

[Schema index](README.md) · [SQLAlchemy model](../../backend/app/models/inventory.py)

## Columns

| Column | PostgreSQL type | Nullable | Server default |
| --- | --- | --- | --- |
| `id` | `uuid` | No | `uuid_generate_v4()` |
| `name` | `varchar(180)` | No | — |
| `item_code` | `varchar(60)` | Yes | — |
| `category` | `varchar(80)` | No | — |
| `item_type` | `varchar(30)` | No | — |
| `unit` | `varchar(20)` | No | — |
| `minimum_stock` | `numeric(14, 3)` | No | `0` |
| `reorder_level` | `numeric(14, 3)` | No | `0` |
| `unit_cost` | `numeric(14, 2)` | Yes | — |
| `supplier_id` | `uuid` | Yes | — |
| `is_active` | `boolean` | No | `true` |
| `created_at` | `timestamptz` | No | `now()` |
| `updated_at` | `timestamptz` | No | `now()` |
| `deleted_at` | `timestamptz` | Yes | — |

## Keys and constraints

| Constraint | Rule |
| --- | --- |
| `pk_inventory_items` | `PRIMARY KEY (id)` |

## Foreign keys

| Constraint | Local columns | Referenced columns | On delete |
| --- | --- | --- | --- |
| `fk_inventory_items_supplier_id_suppliers` | `(supplier_id)` | [`suppliers(id)`](suppliers.md) | `SET NULL` |

## Indexes

| Index | Method | Keys | Unique | Predicate |
| --- | --- | --- | --- | --- |
| `idx_inventory_items_category` | `btree` | `category` | No | — |
| `idx_inventory_items_type` | `btree` | `item_type` | No | — |
| `uq_inventory_items_code_active` | `btree` | `item_code` | Yes | `((item_code IS NOT NULL) AND (deleted_at IS NULL))` |
