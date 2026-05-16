# `daily_report_approval_history`

Generated from the current SQLAlchemy model metadata in `backend/app/models`.

## Columns

| Column | Type | Nullable | Default | References |
|---|---|---:|---|---|
| `id` | `UUID` | No | `uuid_generate_v4()` |  |
| `report_id` | `UUID` | No | `` | daily_reports.id |
| `actor_id` | `UUID` | Yes | `` | users.id |
| `decision` | `VARCHAR(20)` | No | `` |  |
| `previous_status` | `VARCHAR(20)` | No | `` |  |
| `comments` | `TEXT` | Yes | `` |  |
| `decided_at` | `DATETIME` | No | `` |  |
| `created_at` | `DATETIME` | No | `now()` |  |
| `updated_at` | `DATETIME` | No | `now()` |  |
| `deleted_at` | `DATETIME` | Yes | `` |  |

## Keys

- Primary key: `id`

## Outbound Relationships

| Column | References |
|---|---|
| `report_id` | `daily_reports.id` |
| `actor_id` | `users.id` |
