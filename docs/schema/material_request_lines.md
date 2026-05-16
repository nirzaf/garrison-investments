# `material_request_lines`

Generated from the current SQLAlchemy model metadata in `backend/app/models`.

## Columns

| Column | Type | Nullable | Default | References |
|---|---|---:|---|---|
| `id` | `UUID` | No | `uuid_generate_v4()` |  |
| `request_id` | `UUID` | No | `` | material_requests.id |
| `item_id` | `UUID` | No | `` | inventory_items.id |
| `quantity` | `NUMERIC(14, 3)` | No | `` |  |
| `reserved_quantity` | `NUMERIC(14, 3)` | No | `0` |  |
| `issued_quantity` | `NUMERIC(14, 3)` | No | `0` |  |
| `unit_cost` | `NUMERIC(14, 2)` | Yes | `` |  |
| `created_at` | `DATETIME` | No | `now()` |  |
| `updated_at` | `DATETIME` | No | `now()` |  |
| `deleted_at` | `DATETIME` | Yes | `` |  |

## Keys

- Primary key: `id`

## Outbound Relationships

| Column | References |
|---|---|
| `request_id` | `material_requests.id` |
| `item_id` | `inventory_items.id` |
