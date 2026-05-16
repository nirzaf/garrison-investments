# `auth_otp_challenges`

Generated from the current SQLAlchemy model metadata in `backend/app/models`.

## Columns

| Column | Type | Nullable | Default | References |
|---|---|---:|---|---|
| `id` | `UUID` | No | `uuid_generate_v4()` |  |
| `user_id` | `UUID` | No | `` | users.id |
| `purpose` | `VARCHAR(32)` | No | `'login'` |  |
| `otp_hash` | `VARCHAR(255)` | No | `` |  |
| `expires_at` | `DATETIME` | No | `` |  |
| `consumed_at` | `DATETIME` | Yes | `` |  |
| `attempts` | `INTEGER` | No | `0` |  |
| `created_at` | `DATETIME` | No | `now()` |  |
| `updated_at` | `DATETIME` | No | `now()` |  |
| `deleted_at` | `DATETIME` | Yes | `` |  |

## Keys

- Primary key: `id`

## Outbound Relationships

| Column | References |
|---|---|
| `user_id` | `users.id` |
