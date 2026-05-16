# `auth_refresh_tokens`

Generated from the current SQLAlchemy model metadata in `backend/app/models`.

## Columns

| Column | Type | Nullable | Default | References |
|---|---|---:|---|---|
| `id` | `UUID` | No | `uuid_generate_v4()` |  |
| `user_id` | `UUID` | No | `` | users.id |
| `token_hash` | `VARCHAR(255)` | No | `` |  |
| `expires_at` | `DATETIME` | No | `` |  |
| `revoked_at` | `DATETIME` | Yes | `` |  |
| `created_at` | `DATETIME` | No | `now()` |  |
| `updated_at` | `DATETIME` | No | `now()` |  |
| `deleted_at` | `DATETIME` | Yes | `` |  |

## Keys

- Primary key: `id`

## Outbound Relationships

| Column | References |
|---|---|
| `user_id` | `users.id` |
