# `import_batches`

Generated from the current SQLAlchemy model metadata in `backend/app/models`.

## Columns

| Column | Type | Nullable | Default | References |
|---|---|---:|---|---|
| `id` | `UUID` | No | `uuid_generate_v4()` |  |
| `template_type` | `VARCHAR(40)` | No | `` |  |
| `file_name` | `VARCHAR(255)` | No | `` |  |
| `status` | `VARCHAR(30)` | No | `` |  |
| `created_by` | `UUID` | Yes | `` | users.id |
| `row_count` | `INTEGER` | No | `0` |  |
| `error_count` | `INTEGER` | No | `0` |  |
| `summary` | `JSONB` | Yes | `` |  |
| `created_at` | `DATETIME` | No | `now()` |  |
| `updated_at` | `DATETIME` | No | `now()` |  |
| `deleted_at` | `DATETIME` | Yes | `` |  |

## Keys

- Primary key: `id`

## Outbound Relationships

| Column | References |
|---|---|
| `created_by` | `users.id` |
