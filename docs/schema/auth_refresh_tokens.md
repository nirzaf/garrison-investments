# auth_refresh_tokens

Defined in `backend/app/models/auth.py`

## Columns

| Column | Type | Nullable | Default | Foreign Key | Index/Key |
|---|---|---|---|---|---|
| `id` | UUID | — | uuid_generate_v4() | — | PRIMARY KEY |
| `expires_at` | TimestampTZ | NOT NULL | — | — | — |
| `revoked_at` | TimestampTZ | NULL | — | — | — |
| `token_hash` | String(255) | NOT NULL | — | — | — |
| `user_id` | UUID | NOT NULL | — | users.id | — |
| `created_at` | TimestampTZ | NOT NULL | now() | — | — |
| `updated_at` | TimestampTZ | NOT NULL | now() | — | — |
| `deleted_at` | TimestampTZ | NULL | — | — | — |

