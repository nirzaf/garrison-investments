# users

Defined in `backend/app/models/user.py`

## Columns

| Column | Type | Nullable | Default | Foreign Key | Index/Key |
|---|---|---|---|---|---|
| `id` | UUID | — | uuid_generate_v4() | — | PRIMARY KEY |
| `email` | String(255) | NOT NULL | — | — | YES |
| `full_name` | String(255) | NOT NULL | — | — | — |
| `role` | String(64) | NOT NULL | — | — | — |
| `employee_code` | String(64) | NULL | — | — | — |
| `phone` | String(32) | NULL | — | — | — |
| `designation` | String(100) | NULL | — | — | — |
| `password_hash` | String(255) | NULL | — | — | — |
| `is_active` | Boolean | NOT NULL | true | — | — |
| `must_change_password` | Boolean | NOT NULL | true | — | — |
| `failed_login_attempts` | Integer | NOT NULL | 0 | — | — |
| `locked_until` | TimestampTZ | NULL | — | — | — |
| `last_login_at` | TimestampTZ | NULL | — | — | — |
