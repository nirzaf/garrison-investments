# auth_refresh_tokens

Defined in `backend/app/models/auth.py`

## Columns

| Column | Type | Nullable | Default | Foreign Key | Index/Key |
|---|---|---|---|---|---|
| `id` | UUID | — | uuid_generate_v4() | — | PRIMARY KEY |
| `user_id` | UUID | NOT NULL | — | users.id | — |
| `token_hash` | String(255) | NOT NULL | — | — | — |
| `expires_at` | TimestampTZ | NOT NULL | — | — | — |
| `revoked_at` | TimestampTZ | NULL | — | — | — |
