# auth_otp_challenges

Defined in `backend/app/models/auth.py`

## Columns

| Column | Type | Nullable | Default | Foreign Key | Index/Key |
|---|---|---|---|---|---|
| `id` | UUID | — | uuid_generate_v4() | — | PRIMARY KEY |
| `user_id` | UUID | NOT NULL | — | users.id | — |
| `purpose` | String(32) | NOT NULL | login | — | — |
| `otp_hash` | String(255) | NOT NULL | — | — | — |
| `expires_at` | TimestampTZ | NOT NULL | — | — | — |
| `consumed_at` | TimestampTZ | NULL | — | — | — |
| `attempts` | Integer | NOT NULL | 0 | — | — |
