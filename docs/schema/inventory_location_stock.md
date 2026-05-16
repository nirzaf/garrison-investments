# `inventory_location_stock`

Generated from the current SQLAlchemy model metadata in `backend/app/models`.

## Columns

| Column | Type | Nullable | Default | References |
|---|---|---:|---|---|
| `id` | `UUID` | No | `uuid_generate_v4()` |  |
| `item_id` | `UUID` | No | `` | inventory_items.id |
| `location_id` | `UUID` | No | `` | storage_locations.id |
| `on_hand_qty` | `NUMERIC(14, 3)` | No | `0` |  |
| `reserved_qty` | `NUMERIC(14, 3)` | No | `0` |  |
| `created_at` | `DATETIME` | No | `now()` |  |
| `updated_at` | `DATETIME` | No | `now()` |  |
| `deleted_at` | `DATETIME` | Yes | `` |  |

## Keys

- Primary key: `id`

## Outbound Relationships

| Column | References |
|---|---|
| `item_id` | `inventory_items.id` |
| `location_id` | `storage_locations.id` |
