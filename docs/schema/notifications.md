# notifications

Defined in `backend/app/models/notification.py`

## Columns

| Column | Type | Nullable | Default | Foreign Key | Index/Key |
|---|---|---|---|---|---|
| `id` | UUID | — | uuid_generate_v4() | — | PRIMARY KEY |
| `body` | Text | NOT NULL | — | — | — |
| `email_status` | String(20) | NULL | — | — | — |
| `is_read` | Boolean | NOT NULL | false | — | — |
| `muted` | Boolean | NOT NULL | false | — | — |
| `notification_type` | String(30) | NOT NULL | — | — | — |
| `read_at` | TimestampTZ | NULL | — | — | — |
| `reference_id` | UUID | NULL | — | — | — |
| `reference_type` | String(30) | NULL | — | — | — |
| `title` | String(200) | NOT NULL | — | — | — |
| `user_id` | UUID | NOT NULL | — | users.id | — |
| `created_at` | TimestampTZ | NOT NULL | now() | — | — |
| `updated_at` | TimestampTZ | NOT NULL | now() | — | — |
| `deleted_at` | TimestampTZ | NULL | — | — | — |

