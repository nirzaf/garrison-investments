# `storage_locations`

Generated from the current SQLAlchemy model metadata in `backend/app/models`.

## Columns

| Column | Type | Nullable | Default | References |
|---|---|---:|---|---|
| `id` | `UUID` | No | `uuid_generate_v4()` |  |
| `name` | `VARCHAR(160)` | No | `` |  |
| `code` | `VARCHAR(40)` | No | `` |  |
| `location_type` | `VARCHAR(30)` | No | `` |  |
| `project_id` | `UUID` | Yes | `` | projects.id |
| `address` | `TEXT` | Yes | `` |  |
| `is_active` | `BOOLEAN` | No | `true` |  |
| `created_at` | `DATETIME` | No | `now()` |  |
| `updated_at` | `DATETIME` | No | `now()` |  |
| `deleted_at` | `DATETIME` | Yes | `` |  |

## Keys

- Primary key: `id`

## Outbound Relationships

| Column | References |
|---|---|
| `project_id` | `projects.id` |

## Referenced By

| Source | Target |
|---|---|
| `inventory_assets.current_location_id` | `storage_locations.id` |
| `inventory_location_stock.location_id` | `storage_locations.id` |
| `inventory_movements.from_location_id` | `storage_locations.id` |
| `inventory_movements.to_location_id` | `storage_locations.id` |
| `material_requests.from_location_id` | `storage_locations.id` |
