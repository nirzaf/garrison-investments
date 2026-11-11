# users

Defined in `backend/app/models/user.py`

## Columns

| Column | Type | Nullable | Default | Foreign Key | Index/Key |
|---|---|---|---|---|---|
| `id` | UUID | — | uuid_generate_v4() | — | PRIMARY KEY |
| `designation` | String(100) | NULL | — | — | — |
| `email` | String(255) | NOT NULL | — | — | YES |
| `employee_code` | String(64) | NULL | — | — | — |
| `failed_login_attempts` | Integer | NOT NULL | 0 | — | — |
| `full_name` | String(255) | NOT NULL | — | — | — |
| `is_active` | Boolean | NOT NULL | true | — | — |
| `last_login_at` | TimestampTZ | NULL | — | — | — |
| `locked_until` | TimestampTZ | NULL | — | — | — |
| `must_change_password` | Boolean | NOT NULL | true | — | — |
| `password_hash` | String(255) | NULL | — | — | — |
| `phone` | String(32) | NULL | — | — | — |
| `role` | String(64) | NOT NULL | — | — | — |
| `created_at` | TimestampTZ | NOT NULL | now() | — | — |
| `updated_at` | TimestampTZ | NOT NULL | now() | — | — |
| `deleted_at` | TimestampTZ | NULL | — | — | — |

