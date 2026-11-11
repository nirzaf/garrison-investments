# auth_otp_challenges

Defined in `backend/app/models/auth.py`

## Columns

| Column | Type | Nullable | Default | Foreign Key | Index/Key |
|---|---|---|---|---|---|
| `id` | UUID | — | uuid_generate_v4() | — | PRIMARY KEY |
| `attempts` | Integer | NOT NULL | 0 | — | — |
| `consumed_at` | TimestampTZ | NULL | — | — | — |
| `expires_at` | TimestampTZ | NOT NULL | — | — | — |
| `otp_hash` | String(255) | NOT NULL | — | — | — |
| `purpose` | String(32) | NOT NULL | login | — | — |
| `user_id` | UUID | NOT NULL | — | users.id | — |
| `created_at` | TimestampTZ | NOT NULL | now() | — | — |
| `updated_at` | TimestampTZ | NOT NULL | now() | — | — |
| `deleted_at` | TimestampTZ | NULL | — | — | — |

