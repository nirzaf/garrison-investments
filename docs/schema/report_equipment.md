# `report_equipment`

Generated from the current SQLAlchemy model metadata in `backend/app/models`.

## Columns

| Column | Type | Nullable | Default | References |
|---|---|---:|---|---|
| `id` | `UUID` | No | `uuid_generate_v4()` |  |
| `report_id` | `UUID` | No | `` | daily_reports.id |
| `equipment_name` | `VARCHAR(120)` | No | `` |  |
| `quantity` | `INTEGER` | No | `` |  |
| `hours_used` | `NUMERIC(6, 2)` | No | `0` |  |
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
