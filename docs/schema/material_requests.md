# `material_requests`

Generated from the current SQLAlchemy model metadata in `backend/app/models`.

## Columns

| Column | Type | Nullable | Default | References |
|---|---|---:|---|---|
| `id` | `UUID` | No | `uuid_generate_v4()` |  |
| `request_number` | `VARCHAR(60)` | No | `` |  |
| `project_id` | `UUID` | No | `` | projects.id |
| `requester_id` | `UUID` | Yes | `` | users.id |
| `from_location_id` | `UUID` | Yes | `` | storage_locations.id |
| `status` | `VARCHAR(30)` | No | `'requested'` |  |
| `total_estimated_cost` | `NUMERIC(14, 2)` | No | `0` |  |
| `notes` | `TEXT` | Yes | `` |  |
| `created_at` | `DATETIME` | No | `now()` |  |
| `updated_at` | `DATETIME` | No | `now()` |  |
| `deleted_at` | `DATETIME` | Yes | `` |  |

## Keys

- Primary key: `id`

## Outbound Relationships

| Column | References |
|---|---|
| `project_id` | `projects.id` |
| `requester_id` | `users.id` |
| `from_location_id` | `storage_locations.id` |

## Referenced By

| Source | Target |
|---|---|
| `material_request_lines.request_id` | `material_requests.id` |
