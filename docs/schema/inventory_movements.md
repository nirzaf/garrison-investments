# inventory_movements

Stock and asset movement history, with references to the source operation where available.

[Schema index](README.md) · [SQLAlchemy model](../../backend/app/models/inventory.py)

For imported movements, `import_batch_id` and `import_row_index` identify the originating row for replay protection. See the [import row migration](../../backend/alembic/versions/202605300001_import_row_idempotency.py).

## Columns

| Column | PostgreSQL type | Nullable | Server default |
| --- | --- | --- | --- |
| `id` | `uuid` | No | `uuid_generate_v4()` |
| `item_id` | `uuid` | No | — |
| `asset_id` | `uuid` | Yes | — |
| `movement_type` | `varchar(30)` | No | — |
| `quantity` | `numeric(14, 3)` | No | — |
| `from_location_id` | `uuid` | Yes | — |
| `to_location_id` | `uuid` | Yes | — |
| `project_id` | `uuid` | Yes | — |
| `reference_type` | `varchar(40)` | Yes | — |
| `reference_id` | `uuid` | Yes | — |
| `handled_by` | `uuid` | Yes | — |
| `notes` | `text` | Yes | — |
| `created_at` | `timestamptz` | No | `now()` |
| `updated_at` | `timestamptz` | No | `now()` |
| `deleted_at` | `timestamptz` | Yes | — |
| `import_batch_id` | `uuid` | Yes | — |
| `import_row_index` | `integer` | Yes | — |

## Keys and constraints

| Constraint | Rule |
| --- | --- |
| `pk_inventory_movements` | `PRIMARY KEY (id)` |

## Foreign keys

| Constraint | Local columns | Referenced columns | On delete |
| --- | --- | --- | --- |
| `fk_inventory_movements_asset_id_inventory_assets` | `(asset_id)` | [`inventory_assets(id)`](inventory_assets.md) | `SET NULL` |
| `fk_inventory_movements_from_location_id_storage_locations` | `(from_location_id)` | [`storage_locations(id)`](storage_locations.md) | `SET NULL` |
| `fk_inventory_movements_handled_by_users` | `(handled_by)` | [`users(id)`](users.md) | `SET NULL` |
| `fk_inventory_movements_item_id_inventory_items` | `(item_id)` | [`inventory_items(id)`](inventory_items.md) | `RESTRICT` |
| `fk_inventory_movements_project_id_projects` | `(project_id)` | [`projects(id)`](projects.md) | `SET NULL` |
| `fk_inventory_movements_to_location_id_storage_locations` | `(to_location_id)` | [`storage_locations(id)`](storage_locations.md) | `SET NULL` |

## Indexes

| Index | Method | Keys | Unique | Predicate |
| --- | --- | --- | --- | --- |
| `idx_inventory_movements_asset` | `btree` | `asset_id` | No | — |
| `idx_inventory_movements_item` | `btree` | `item_id, created_at` | No | — |
| `idx_inventory_movements_project` | `btree` | `project_id` | No | — |
| `uq_movements_import_row` | `btree` | `import_batch_id, import_row_index` | Yes | `(import_batch_id IS NOT NULL)` |
