# `report_material_consumption`

Generated from the current SQLAlchemy model metadata in `backend/app/models`.

## Columns

| Column | Type | Nullable | Default | References |
|---|---|---:|---|---|
| `id` | `UUID` | No | `uuid_generate_v4()` |  |
| `report_id` | `UUID` | No | `` | daily_reports.id |
| `boq_item_id` | `UUID` | Yes | `` | boq_items.id |
| `material_name` | `VARCHAR(160)` | No | `` |  |
| `unit` | `VARCHAR(30)` | No | `` |  |
| `quantity` | `NUMERIC(14, 3)` | No | `` |  |
| `remarks` | `TEXT` | Yes | `` |  |
| `created_at` | `DATETIME` | No | `now()` |  |
| `updated_at` | `DATETIME` | No | `now()` |  |
| `deleted_at` | `DATETIME` | Yes | `` |  |

## Keys

- Primary key: `id`

## Outbound Relationships

| Column | References |
|---|---|
| `report_id` | `daily_reports.id` |
| `boq_item_id` | `boq_items.id` |
