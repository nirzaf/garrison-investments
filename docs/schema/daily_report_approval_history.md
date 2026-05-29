# daily_report_approval_history

Defined in `backend/app/models/daily_report.py`

## Columns

| Column | Type | Nullable | Default | Foreign Key | Index/Key |
|---|---|---|---|---|---|
| `id` | UUID | — | uuid_generate_v4() | — | PRIMARY KEY |
| `actor_id` | UUID | NULL | — | users.id | — |
| `comments` | Text | NULL | — | — | — |
| `decided_at` | TimestampTZ | NOT NULL | — | — | — |
| `decision` | String(20) | NOT NULL | — | — | — |
| `previous_status` | String(20) | NOT NULL | — | — | — |
| `report_id` | UUID | NOT NULL | — | daily_reports.id | — |
| `created_at` | TimestampTZ | NOT NULL | now() | — | — |
| `updated_at` | TimestampTZ | NOT NULL | now() | — | — |
| `deleted_at` | TimestampTZ | NULL | — | — | — |

