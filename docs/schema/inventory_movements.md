# `inventory_movements`

Generated from the current SQLAlchemy model metadata in `backend/app/models`.

## Columns

| Column | Type | Nullable | Default | References |
|---|---|---:|---|---|
| `id` | `UUID` | No | `uuid_generate_v4()` |  |
| `item_id` | `UUID` | No | `` | inventory_items.id |
| `asset_id` | `UUID` | Yes | `` | inventory_assets.id |
| `movement_type` | `VARCHAR(30)` | No | `` |  |
| `quantity` | `NUMERIC(14, 3)` | No | `` |  |
| `from_location_id` | `UUID` | Yes | `` | storage_locations.id |
| `to_location_id` | `UUID` | Yes | `` | storage_locations.id |
| `project_id` | `UUID` | Yes | `` | projects.id |
| `reference_type` | `VARCHAR(40)` | Yes | `` |  |
| `reference_id` | `UUID` | Yes | `` |  |
| `handled_by` | `UUID` | Yes | `` | users.id |
| `notes` | `TEXT` | Yes | `` |  |
| `created_at` | `DATETIME` | No | `now()` |  |
| `updated_at` | `DATETIME` | No | `now()` |  |
| `deleted_at` | `DATETIME` | Yes | `` |  |

## Keys

- Primary key: `id`

## Outbound Relationships

| Column | References |
|---|---|
| `item_id` | `inventory_items.id` |
| `asset_id` | `inventory_assets.id` |
| `from_location_id` | `storage_locations.id` |
| `to_location_id` | `storage_locations.id` |
| `project_id` | `projects.id` |
| `handled_by` | `users.id` |
