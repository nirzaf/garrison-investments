# `notifications`

Generated from the current SQLAlchemy model metadata in `backend/app/models`.

## Columns

| Column | Type | Nullable | Default | References |
|---|---|---:|---|---|
| `id` | `UUID` | No | `uuid_generate_v4()` |  |
| `user_id` | `UUID` | No | `` | users.id |
| `title` | `VARCHAR(200)` | No | `` |  |
| `body` | `TEXT` | No | `` |  |
| `notification_type` | `VARCHAR(30)` | No | `` |  |
| `reference_type` | `VARCHAR(30)` | Yes | `` |  |
| `reference_id` | `UUID` | Yes | `` |  |
| `is_read` | `BOOLEAN` | No | `false` |  |
| `muted` | `BOOLEAN` | No | `false` |  |
| `email_status` | `VARCHAR(20)` | Yes | `` |  |
| `read_at` | `DATETIME` | Yes | `` |  |
| `created_at` | `DATETIME` | No | `now()` |  |
| `updated_at` | `DATETIME` | No | `now()` |  |
| `deleted_at` | `DATETIME` | Yes | `` |  |

## Keys

- Primary key: `id`

## Outbound Relationships

| Column | References |
|---|---|
| `user_id` | `users.id` |
