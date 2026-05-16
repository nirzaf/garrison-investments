# `activity_log`

Generated from the current SQLAlchemy model metadata in `backend/app/models`.

## Columns

| Column | Type | Nullable | Default | References |
|---|---|---:|---|---|
| `id` | `UUID` | No | `uuid_generate_v4()` |  |
| `user_id` | `UUID` | Yes | `` | users.id |
| `action` | `VARCHAR(64)` | No | `` |  |
| `entity_type` | `VARCHAR(64)` | Yes | `` |  |
| `entity_id` | `UUID` | Yes | `` |  |
| `ip_address` | `VARCHAR(64)` | Yes | `` |  |
| `user_agent` | `VARCHAR(512)` | Yes | `` |  |
| `comments` | `TEXT` | Yes | `` |  |
| `old_values` | `JSONB` | Yes | `` |  |
| `new_values` | `JSONB` | Yes | `` |  |
| `created_at` | `DATETIME` | No | `now()` |  |
| `updated_at` | `DATETIME` | No | `now()` |  |
| `deleted_at` | `DATETIME` | Yes | `` |  |

## Keys

- Primary key: `id`

## Outbound Relationships

| Column | References |
|---|---|
| `user_id` | `users.id` |
