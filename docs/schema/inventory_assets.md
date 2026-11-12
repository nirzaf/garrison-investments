# inventory_assets

Individually tagged assets with location, condition, and status.

[Schema index](README.md) · [SQLAlchemy model](../../backend/app/models/inventory.py)

## Columns

| Column | PostgreSQL type | Nullable | Server default |
| --- | --- | --- | --- |
| `id` | `uuid` | No | `uuid_generate_v4()` |
| `item_id` | `uuid` | No | — |
| `asset_tag` | `varchar(80)` | No | — |
| `current_location_id` | `uuid` | No | — |
| `condition` | `varchar(40)` | No | `'good'` |
| `status` | `varchar(30)` | No | `'active'` |
| `created_at` | `timestamptz` | No | `now()` |
| `updated_at` | `timestamptz` | No | `now()` |
| `deleted_at` | `timestamptz` | Yes | — |

## Keys and constraints

| Constraint | Rule |
| --- | --- |
| `pk_inventory_assets` | `PRIMARY KEY (id)` |

## Foreign keys

| Constraint | Local columns | Referenced columns | On delete |
| --- | --- | --- | --- |
| `fk_inventory_assets_current_location_id_storage_locations` | `(current_location_id)` | [`storage_locations(id)`](storage_locations.md) | `RESTRICT` |
| `fk_inventory_assets_item_id_inventory_items` | `(item_id)` | [`inventory_items(id)`](inventory_items.md) | `CASCADE` |

## Indexes

| Index | Method | Keys | Unique | Predicate |
| --- | --- | --- | --- | --- |
| `idx_assets_current_location` | `btree` | `current_location_id` | No | — |
| `uq_inventory_assets_tag_active` | `btree` | `asset_tag` | Yes | — |
