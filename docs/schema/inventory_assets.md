# `inventory_assets`

Generated from the current SQLAlchemy model metadata in `backend/app/models`.

## Columns

| Column | Type | Nullable | Default | References |
|---|---|---:|---|---|
| `id` | `UUID` | No | `uuid_generate_v4()` |  |
| `item_id` | `UUID` | No | `` | inventory_items.id |
| `asset_tag` | `VARCHAR(80)` | No | `` |  |
| `current_location_id` | `UUID` | No | `` | storage_locations.id |
| `condition` | `VARCHAR(40)` | No | `'good'` |  |
| `status` | `VARCHAR(30)` | No | `'active'` |  |
| `created_at` | `DATETIME` | No | `now()` |  |
| `updated_at` | `DATETIME` | No | `now()` |  |
| `deleted_at` | `DATETIME` | Yes | `` |  |

## Keys

- Primary key: `id`

## Outbound Relationships

| Column | References |
|---|---|
| `item_id` | `inventory_items.id` |
| `current_location_id` | `storage_locations.id` |

## Referenced By

| Source | Target |
|---|---|
| `inventory_movements.asset_id` | `inventory_assets.id` |
