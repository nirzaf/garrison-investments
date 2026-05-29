# notifications

Defined in `backend/app/models/notification.py`

## Columns

| Column | Type | Nullable | Default | Foreign Key | Index/Key |
|---|---|---|---|---|---|
| `id` | UUID | — | uuid_generate_v4() | — | PRIMARY KEY |
| `user_id` | UUID | NOT NULL | — | users.id | — |
| `title` | String(200) | NOT NULL | — | — | — |
| `body` | Text | NOT NULL | — | — | — |
| `notification_type` | String(30) | NOT NULL | — | — | — |
| `reference_type` | String(30) | NULL | — | — | — |
| `reference_id` | UUID | NULL | — | — | — |
| `is_read` | Boolean | NOT NULL | false | — | — |
| `muted` | Boolean | NOT NULL | false | — | — |
| `email_status` | String(20) | NULL | — | — | — |
| `read_at` | TimestampTZ | NULL | — | — | — |
