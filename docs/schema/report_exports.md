# `report_exports`

Generated from the current SQLAlchemy model metadata in `backend/app/models`.

## Columns

| Column | Type | Nullable | Default | References |
|---|---|---:|---|---|
| `id` | `UUID` | No | `uuid_generate_v4()` |  |
| `report_id` | `UUID` | No | `` | daily_reports.id |
| `generated_by` | `UUID` | Yes | `` | users.id |
| `file_name` | `VARCHAR(255)` | No | `` |  |
| `object_key` | `VARCHAR(512)` | No | `` |  |
| `content_type` | `VARCHAR(120)` | No | `` |  |
| `status` | `VARCHAR(20)` | No | `'ready'` |  |
| `error_message` | `TEXT` | Yes | `` |  |
| `email_status` | `VARCHAR(20)` | Yes | `` |  |
| `email_error` | `TEXT` | Yes | `` |  |
| `emailed_at` | `DATETIME` | Yes | `` |  |
| `generated_at` | `DATETIME` | No | `` |  |
| `created_at` | `DATETIME` | No | `now()` |  |
| `updated_at` | `DATETIME` | No | `now()` |  |
| `deleted_at` | `DATETIME` | Yes | `` |  |

## Keys

- Primary key: `id`

## Outbound Relationships

| Column | References |
|---|---|
| `report_id` | `daily_reports.id` |
| `generated_by` | `users.id` |
